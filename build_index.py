#!/usr/bin/env python3
"""Build a separate local SQLite index. Never changes Parsed/ or contacts a service."""
import argparse
import csv
import hashlib
import json
import os
import sqlite3
import time
from collections import Counter, defaultdict
from pathlib import Path

from local_search.ingest import VERSION, normalize, parse, passages, shell, shingles, tokens

ROOT = Path(__file__).resolve().parent
SCHEMA = '''
CREATE TABLE documents(doc_id TEXT PRIMARY KEY, raw_hash TEXT, title TEXT, title_source TEXT,
 genre TEXT, language TEXT, content_role TEXT, quality TEXT, excluded_reason TEXT);
CREATE TABLE source_languages(filename TEXT PRIMARY KEY,supplied_language TEXT,detected_language TEXT,effective_language TEXT,method TEXT);
CREATE TABLE sources(filename TEXT PRIMARY KEY, doc_id TEXT REFERENCES documents(doc_id),
 genre TEXT, language TEXT, raw_hash TEXT);
CREATE TABLE passages(id INTEGER PRIMARY KEY, doc_id TEXT REFERENCES documents(doc_id),
 section TEXT, text TEXT, role TEXT, line_start INTEGER, line_end INTEGER);
CREATE INDEX passages_doc ON passages(doc_id);
CREATE INDEX sources_doc ON sources(doc_id);
CREATE TABLE relationships(doc_a TEXT, doc_b TEXT, kind TEXT, jaccard REAL, coverage_a REAL, coverage_b REAL,
 PRIMARY KEY(doc_a,doc_b));
CREATE VIRTUAL TABLE passage_fts USING fts5(title,section,body,content='',tokenize='unicode61 remove_diacritics 2');
CREATE TABLE reviews(doc_id TEXT PRIMARY KEY, details TEXT);
CREATE TABLE document_rows(id INTEGER PRIMARY KEY,doc_id TEXT UNIQUE);
CREATE VIRTUAL TABLE document_fts USING fts5(title,body,content='',tokenize='unicode61 remove_diacritics 2');
CREATE TABLE manifest(key TEXT PRIMARY KEY, value TEXT);
'''

def source_metadata(path):
    with path.open(encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    metadata = {}
    for row in rows:
        if row['id'] in metadata:
            raise ValueError('Duplicate metadata ID: ' + row['id'])
        metadata[row['id']] = row
    return metadata


def build(root=ROOT, output=None):
    root = Path(root).resolve()
    out = Path(output) if output else root / 'data/search.sqlite'
    out.parent.mkdir(parents=True, exist_ok=True)
    temporary = out.with_suffix('.building.sqlite')
    if temporary.exists():
        temporary.unlink()
    c = sqlite3.connect(temporary)
    c.executescript(SCHEMA)
    meta = source_metadata(root / 'D4GC Challenge 2026 Documentation.csv')
    groups = defaultdict(list)
    raw_contents = {}
    files = sorted((root / 'Parsed').glob('*.md'))
    if not files:
        raise ValueError('No source documents found')
    for p in files:
        content = p.read_bytes()
        h = hashlib.sha256(content).hexdigest()
        groups[h].append(p.name)
        raw_contents.setdefault(h, content.decode('utf-8'))
    stats = Counter(source_files=len(files), exact_unique_documents=len(groups), extra_exact_copies=len(files)-len(groups))
    review_path=root/'analysis/guideline_content_review.json'
    reviews=json.loads(review_path.read_text())['files'] if review_path.exists() else {}
    signatures = {}
    token_hashes = defaultdict(list)
    for raw_hash, filenames in groups.items():
        doc_id = filenames[0]
        m = meta.get(Path(doc_id).stem, {})
        genre, language = m.get('genre', 'Unknown'), m.get('language', 'unknown')
        raw = raw_contents[raw_hash]
        parsed = parse(raw, doc_id, genre)
        review=next((reviews[f] for f in filenames if f in reviews and reviews[f].get('raw_hash')==raw_hash),None)
        if review:
            roles={'substantive':'content','index':'index_or_front_matter','introduction_or_cover':'index_or_front_matter',
                   'glossary':'back_matter','bibliography':'back_matter','contributors':'back_matter'}
            parsed['content_role']=roles.get(review['role'],parsed['content_role'])
            parsed['quality']=[q for q in parsed['quality'] if q not in ('index_or_front_matter','back_matter')]
            if parsed['content_role']!='content':
                parsed['quality'].append(parsed['content_role'])
            parsed['quality'].extend(w['code'] for w in review.get('warnings',[]))
            c.execute('INSERT INTO reviews VALUES(?,?)',(doc_id,json.dumps(review,ensure_ascii=False)))
            stats['reviewed_guideline_sources']+=len(filenames)
        elif any(f in reviews for f in filenames):
            stats['stale_reviews_ignored']+=1
        reason = 'confirmed_repeated_site_shell' if shell(raw) else ''
        if reason:
            stats['excluded_sources'] += len(filenames)
            stats['excluded_canonical_documents'] += 1
        c.execute('INSERT INTO documents VALUES(?,?,?,?,?,?,?,?,?)',
                  (doc_id, raw_hash, parsed['title'], parsed['title_source'], genre, language,
                   parsed['content_role'], json.dumps(parsed['quality']), reason))
        for fname in filenames:
            fm = meta.get(Path(fname).stem, {})
            c.execute('INSERT INTO sources VALUES(?,?,?,?,?)', (fname, doc_id, fm.get('genre','Unknown'), fm.get('language','unknown'), raw_hash))
            if not fm:
                stats['sources_without_csv_metadata'] += 1
        if reason:
            continue
        for p in passages(parsed['blocks']):
            row = c.execute('INSERT INTO passages(doc_id,section,text,role,line_start,line_end) VALUES(?,?,?,?,?,?)',
                            (doc_id, p['section'], p['text'], p['role'], p['line_start'], p['line_end']))
            c.execute('INSERT INTO passage_fts(rowid,title,section,body) VALUES(?,?,?,?)',
                      (row.lastrowid, normalize(parsed['title']) if parsed['title_source']!='opening_excerpt' else '', normalize(p['section']), normalize(p['text'])))
            stats['passages'] += 1
        cleaned = '\n'.join(b['text'] for b in parsed['blocks'])
        docrow=c.execute('INSERT INTO document_rows(doc_id) VALUES(?)',(doc_id,))
        c.execute('INSERT INTO document_fts(rowid,title,body) VALUES(?,?,?)',
                  (docrow.lastrowid,normalize(parsed['title']) if parsed['title_source']!='opening_excerpt' else '',normalize(cleaned)))
        norm_tokens = tokens(cleaned)
        token_hashes[hashlib.sha256(' '.join(norm_tokens).encode()).hexdigest()].append(doc_id)
        if len(norm_tokens) >= 150:
            signatures[doc_id] = shingles(cleaned)
    # High-similarity suggestions only. Different raw sources are never automatically merged.
    relations = {}
    for group in token_hashes.values():
        if len(group) > 1:
            for i, a in enumerate(group):
                for b in group[i+1:]:
                    relations[tuple(sorted((a,b)))] = ('same_normalized_words_review', 1., 1., 1.)
    names = sorted(signatures)
    for i, a in enumerate(names):
        sa = signatures[a]
        for b in names[i+1:]:
            sb = signatures[b]
            if not sa or not sb or min(len(sa),len(sb))/max(len(sa),len(sb)) < .2:
                continue
            overlap = len(sa & sb)
            ca, cb = overlap / len(sa), overlap / len(sb)
            jac = overlap / max(1, len(sa) + len(sb) - overlap)
            if jac >= .82 or (max(ca,cb) >= .94 and overlap >= 100):
                kind = 'possible_version' if jac >= .82 else 'possible_excerpt'
                relations.setdefault((a,b), (kind, jac, ca, cb))
    for (a,b), values in sorted(relations.items()):
        c.execute('INSERT INTO relationships VALUES(?,?,?,?,?,?)', (a,b,*values))
    stats['related_document_pairs_review'] = len(relations)
    stats['indexed_canonical_documents'] = c.execute('SELECT count(DISTINCT doc_id) FROM passages').fetchone()[0]
    manifest = {'version': VERSION, 'build_id': hashlib.sha256(os.urandom(32)).hexdigest(),
                'source_root': str(root), 'created_at': time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
                'stats': dict(stats), 'embedding_status': 'not_built'}
    c.executemany('INSERT INTO manifest VALUES(?,?)', [(k,json.dumps(v)) for k,v in manifest.items()])
    c.execute("INSERT INTO passage_fts(passage_fts) VALUES('optimize')")
    c.execute("INSERT INTO document_fts(document_fts) VALUES('optimize')")
    c.commit()
    assert c.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    c.close()
    from local_search.languages import apply_language_audit
    apply_language_audit(temporary,review_path=root/'analysis/source_language_review.json')
    os.replace(temporary, out)
    print(json.dumps(manifest, indent=2))
    return manifest

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    start = time.perf_counter()
    build(args.root, args.output)
    print(f'Build completed in {time.perf_counter()-start:.2f}s')
