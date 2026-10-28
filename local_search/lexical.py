"""Diversified lexical candidates from passage and whole-document BM25 rankings.

Whole-document length normalization supplies a small focus signal; passage evidence
remains dominant. Only rank positions are fused across the two indexes. No genre
is excluded or treated as authority, and every returned row is an original passage.
"""
from collections import Counter
import sqlite3


PASSAGE_POOL = 1000
DOCUMENT_POOL = 100
SEED_DOCUMENTS = 20
PASSAGES_PER_DOCUMENT = 4
RRF_K = 60


def _passage_rows(c, match, sql_filter, params, extra='', extra_params=(), limit=PASSAGE_POOL):
    return c.execute('''SELECT p.*, bm25(passage_fts,1.5,3.,1.) AS lexical_rank
        FROM passage_fts JOIN passages p ON p.id=passage_fts.rowid
        JOIN documents d USING(doc_id)
        WHERE passage_fts MATCH ?'''+sql_filter+extra+
        ' ORDER BY lexical_rank,p.id LIMIT ?',
        [match,*params,*extra_params,limit]).fetchall()


def _adjusted_passage_key(row):
    # SQLite BM25 is negative, lower is better. Scaling toward zero demotes references
    # using scores from the SAME passage index, before per-document candidate caps.
    weight = .25 if row['role'] == 'references' else 1.
    return row['lexical_rank'] * weight, row['id']


def retrieve(c, match, sql_filter, params, limit=100):
    """Return ranked sqlite.Row objects containing p.* and lexical_rank.

    `sql_filter` is a trusted internal SQL fragment referring to documents as `d`;
    its values are always supplied separately in `params`. MATCH remains a bound
    value. Unknown user terms keep partial-match retrieval behavior unchanged.
    """
    if limit <= 0:
        return []
    rows = _passage_rows(c,match,sql_filter,params)
    if not rows:
        return []
    candidates = {r['id']:r for r in rows}
    try:
        documents = c.execute('''SELECT dr.doc_id,
                bm25(document_fts,2.,1.) AS document_rank
            FROM document_fts JOIN document_rows dr ON dr.id=document_fts.rowid
            JOIN documents d USING(doc_id)
            WHERE document_fts MATCH ?'''+sql_filter+
            ' ORDER BY document_rank,dr.doc_id LIMIT ?',
            [match,*params,DOCUMENT_POOL]).fetchall()
    except sqlite3.OperationalError as exc:
        # Existing on-disk indexes can still serve lexical search while a new index
        # is being prepared. Do not hide syntax errors or other database failures.
        if 'no such table: document_fts' not in str(exc) and 'no such table: document_rows' not in str(exc):
            raise
        documents = []
    document_ranks = {r['doc_id']:rank for rank,r in enumerate(documents,1)}
    represented = {r['doc_id'] for r in rows}
    for doc in documents[:SEED_DOCUMENTS]:
        doc_id = doc['doc_id']
        if doc_id in represented:
            continue
        # A focused document can miss the global passage pool. Retrieve real matching
        # passages, not a synthetic document row or unrelated opening paragraph.
        seeded = _passage_rows(c,match,sql_filter,params,
                              extra=' AND p.doc_id=?',extra_params=(doc_id,),limit=16)
        for row in sorted(seeded,key=_adjusted_passage_key)[:PASSAGES_PER_DOCUMENT]:
            candidates[row['id']] = row

    # Rank after reference demotion and passage diversity, so a long report cannot
    # spend most of the rank positions merely by providing many overlapping chunks.
    diversified = []
    counts = Counter()
    for row in sorted(candidates.values(),key=_adjusted_passage_key):
        if counts[row['doc_id']] >= PASSAGES_PER_DOCUMENT:
            continue
        counts[row['doc_id']] += 1
        diversified.append(row)
    passage_ranks = {r['id']:rank for rank,r in enumerate(diversified,1)}

    def fused(row):
        passage_score = .8 / (RRF_K + passage_ranks[row['id']])
        doc_rank = document_ranks.get(row['doc_id'])
        document_score = .2 / (RRF_K + doc_rank) if doc_rank is not None else 0.
        return -(passage_score + document_score), row['id']

    return sorted(diversified,key=fused)[:limit]
