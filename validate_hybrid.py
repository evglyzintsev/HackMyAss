#!/usr/bin/env python3
"""Validate the complete LOCAL vector index, offline serving, source IDs, and pagination."""
import hashlib
import json
from pathlib import Path
import socket
import time
from unittest.mock import patch

ROOT=Path(__file__).resolve().parent

if __name__=='__main__':
    import numpy as np
    from local_search.embeddings import DenseIndex
    from local_search.search import connect, document, search
    db=ROOT/'data/search.sqlite'
    with patch.object(socket.socket,'connect',side_effect=AssertionError('Network forbidden')), \
         patch('socket.create_connection',side_effect=AssertionError('Network forbidden')):
        start=time.perf_counter();dense=DenseIndex(db);cold=time.perf_counter()-start
        assert dense.model.device.type=='cpu'
        norms=np.linalg.norm(dense.vectors,axis=1)
        np.testing.assert_allclose(norms,1.,atol=1e-4)
        cases=[]
        for q,language,expected in [
            ('pulmonary tuberculosis treatment','fr','P22.md'),
            ('tuberculose traitement','en','P21.md'),
            ('postpartum hemorrhage management','en','P23.md'),
        ]:
            dense._query_cache.clear()
            r=search(db,q,language=language,dense=dense,limit=20)
            assert r['mode']=='hybrid' and not r.get('vector_warning')
            names=[s['filename'] for x in r['results'][:3] for s in x['sources']]
            assert expected in names,(q,expected,names)
            cases.append({'query':q,'language_filter':language,'expected_source':expected,'top3_files':names,
                          'uncached_retrieval_ms':r['latency_ms'],'mode':r['mode']})
        a=search(db,'tuberculosis',dense=dense,limit=10)
        b=search(db,'tuberculosis',dense=dense,limit=10,offset=10)
        assert a['has_more'] and b['results']
        assert not ({r['doc_id'] for r in a['results']} & {r['doc_id'] for r in b['results']})
        assert a['total_results']==b['total_results']
        lexical=search(db,'Cholera treatment guidelines for children with severe dehydration',mode='keyword')
        assert len(lexical['results'])<10  # no page-size padding of partial keyword matches
        assert search(db,'P24.md',dense=dense)['results'][0]['filename']=='P24.md'
        assert 'missing_drug_identity' in search(db,'P24.md',dense=dense)['results'][0]['quality']
        c=connect(db)
        for row in c.execute('SELECT filename,raw_hash FROM sources'):
            assert hashlib.sha256((ROOT/'Parsed'/row['filename']).read_bytes()).hexdigest()==row['raw_hash']
        source_count=c.execute('SELECT count(*) FROM sources').fetchone()[0];c.close()
        assert document(db,'P21.md')['filename']=='P21.md'
    report={'network_blocked':True,'serving_device':'cpu','model_load_seconds':round(cold,3),
            'vector_rows':len(dense.ids),'passages_covered':len(set(dense.ids.tolist())),
            'dimensions':dense.vectors.shape[1],'max_norm_error':float(np.max(np.abs(norms-1))),
            'original_sources_unchanged':source_count,'pagination_total_candidate_documents':a['total_results'],
            'second_page_count':len(b['results']),'keyword_cholera_count_without_partial_padding':len(lexical['results']),
            'cross_language_and_source_checks':cases,'clinical_validation':False}
    (ROOT/'data/hybrid_validation.json').write_text(json.dumps(report,indent=2,ensure_ascii=False))
    print(json.dumps(report,indent=2,ensure_ascii=False))
