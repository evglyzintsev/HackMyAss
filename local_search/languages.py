"""Local language audit; supplied CSV values remain preserved as provenance."""
import hashlib
import json
import sqlite3
from pathlib import Path


def apply_language_audit(db_path, review_path=None, detect=False):
    db_path=Path(db_path).resolve()
    root=db_path.parent.parent
    if not (root/'Parsed').is_dir():
        c=sqlite3.connect(db_path)
        root=Path(json.loads(c.execute("SELECT value FROM manifest WHERE key='source_root'").fetchone()[0]));c.close()
    review_path=Path(review_path) if review_path else root/'analysis/source_language_review.json'
    saved=json.loads(review_path.read_text()).get('files',{}) if review_path.exists() else {}
    by_hash={r['raw_hash']:r for r in saved.values() if r.get('effective_language')!=r.get('supplied_language')}
    identifier=None
    if detect:
        from langid.langid import LanguageIdentifier,model
        identifier=LanguageIdentifier.from_modelstring(model,norm_probs=True)
        identifier.set_languages(['en','fr','es','ar'])
    c=sqlite3.connect(db_path);c.row_factory=sqlite3.Row
    c.execute('''CREATE TABLE IF NOT EXISTS source_languages(filename TEXT PRIMARY KEY,
        supplied_language TEXT,detected_language TEXT,effective_language TEXT,method TEXT)''')
    changes=[]
    output={}
    rows=c.execute('SELECT * FROM sources ORDER BY filename').fetchall()
    for source in rows:
        filename=source['filename']
        old=c.execute('SELECT supplied_language FROM source_languages WHERE filename=?',(filename,)).fetchone()
        supplied=old[0] if old else source['language']
        review=saved.get(filename) or by_hash.get(source['raw_hash'])
        if review:
            review=dict(review,supplied_language=supplied)
        if review and review.get('raw_hash')!=source['raw_hash']:
            review=None
        role=c.execute('SELECT content_role FROM documents WHERE doc_id=?',(source['doc_id'],)).fetchone()[0]
        if identifier and role!='content':
            # Reference lists, drug indexes and menus have misleading language statistics.
            review={'raw_hash':source['raw_hash'],'supplied_language':supplied,'detected_language':None,
                    'effective_language':supplied,'method':'csv_retained_nonprose'}
        if identifier and role=='content':
            blocks=c.execute("SELECT text FROM passages WHERE doc_id=? AND role!='references' ORDER BY id LIMIT 8",(source['doc_id'],)).fetchall()
            sample='\n'.join(r[0] for r in blocks)[:12000]
            if len(sample)>=200:
                lang,probability=identifier.classify(sample)
                # Use conservative high-certainty overrides; otherwise retain supplied metadata.
                effective=lang if probability>=.99 else supplied
                review={'raw_hash':source['raw_hash'],'supplied_language':supplied,'detected_language':lang,
                        'effective_language':effective,'model_probability':float(probability),
                        'method':'offline_langid_high_certainty' if effective!=supplied else 'csv_retained'}
        if not review:
            review={'raw_hash':source['raw_hash'],'supplied_language':supplied,'detected_language':None,
                    'effective_language':supplied,'method':'csv_retained'}
        output[filename]=review
        c.execute('INSERT OR REPLACE INTO source_languages VALUES(?,?,?,?,?)',
                  (filename,supplied,review['detected_language'],review['effective_language'],review['method']))
        c.execute('UPDATE sources SET language=? WHERE filename=?',(review['effective_language'],filename))
        if review['effective_language']!=supplied:
            changes.append({'filename':filename,**review})
    for doc in c.execute('SELECT doc_id,quality FROM documents').fetchall():
        primary=c.execute('SELECT effective_language,supplied_language FROM source_languages WHERE filename=?',(doc['doc_id'],)).fetchone()
        if primary:
            quality=json.loads(doc['quality'])
            quality=[q for q in quality if q!='csv_language_corrected']
            if primary[0]!=primary[1]:
                quality.append('csv_language_corrected')
            c.execute('UPDATE documents SET language=?,quality=? WHERE doc_id=?',(primary[0],json.dumps(quality),doc['doc_id']))
    c.commit();c.close()
    if detect:
        review_path.parent.mkdir(parents=True,exist_ok=True)
        review_path.write_text(json.dumps({'scope':'Offline text-language audit, not clinical validation. Supplied CSV is unchanged.',
                              'files':output,'corrections':changes},ensure_ascii=False,indent=2))
    return changes
