#!/usr/bin/env python3
"""Record local retrieval timings and results. Relevance metrics require human judgments."""
import argparse
import hashlib
import json
import platform
import statistics
from pathlib import Path

from local_search.search import connect, manifest, search

ROOT=Path(__file__).resolve().parent
QUERIES=[
 'Cholera treatment guidelines for children with severe dehydration',
 'pulmonary tuberculosis treatment',
 'malaria treatment pregnancy',
 'postpartum hemorrhage management',
 'measles complications children',
 'antibiotic resistance surveillance',
 'mental health refugees',
 'tuberculose traitement',
 'rougeole vaccination',
 'tuberculosis tratamiento',
 'الكوليرا',
 'xyznotadiseasezzzz',
 'tuberculosis treatment children',
 'penicillin dosage',
 'P24.md',
]

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db',type=Path,default=ROOT/'data/search.sqlite')
    p.add_argument('--output',type=Path,default=ROOT/'data/evaluation.json')
    p.add_argument('--judgments',type=Path,help='JSON object: query -> list of clinician-judged relevant original filenames')
    p.add_argument('--hybrid',action='store_true',help='Require existing local vector index and runtime; never download')
    p.add_argument('--rerank',action='store_true',help='Use the existing local English passage reranker; never download')
    p.add_argument('--include-partial',action='store_true',help='Include broader lexical partial matches (use for comparison with previous evaluations)')
    args=p.parse_args()
    judgments=json.loads(args.judgments.read_text()) if args.judgments else {}
    dense=None
    if args.hybrid:
        from local_search.embeddings import DenseIndex
        dense=DenseIndex(args.db)
    reranker=None
    if args.rerank:
        from local_search.reranker import LocalReranker
        reranker=LocalReranker(ROOT/'models/reranker')
    targets_path=ROOT/'evaluation/retrieval_targets.json'
    targets=json.loads(targets_path.read_text())['queries'] if targets_path.exists() else {}
    records=[]
    for q in QUERIES:
        search(args.db,q,dense=dense,reranker=reranker,include_partial=args.include_partial)  # warm-up; model loading excluded
        timings=[]
        for _ in range(3):
            result=search(args.db,q,dense=dense,reranker=reranker,include_partial=args.include_partial)
            timings.append(result['latency_ms'])
        record={'query':q,'actual_mode':result['mode'],'vector_warning':result.get('vector_warning'),'rerank_status':result.get('rerank_status'),'rerank_note':result.get('rerank_note'),'median_warm_ms':statistics.median(timings),'evidence':result['evidence'],
                'top3':[{'filename':r['filename'],'all_source_files':[s['filename'] for s in r['sources']],
                         'section':r['passage']['section'] if r['passage'] else '', 'genre':r['genre'],
                         'content_role':r['content_role'],'matched_terms':r['matched_terms'],'match_kind':r['match_kind']} for r in result['results'][:3]],
                'precision_at_3':None,'success_at_3':None}
        record['total_ranked_candidates']=result['total_candidates']
        record['total_visible_results']=result['total_results']
        record['hidden_partial_count']=result['hidden_partial_count']
        record['top10_source_files']=[[s['filename'] for s in r['sources']] for r in result['results']]
        target=targets.get(q,{})
        expected=set(target.get('expected_files',[]))
        ranks=[i+1 for i,r in enumerate(result['results']) if expected & {s['filename'] for s in r['sources']}]
        record['reviewed_source_rank_within_10']=min(ranks) if ranks else None
        record['guidance_gap_review']=target.get('guidance_gap')
        record['warning_for_guidance_gap']=result['evidence']=='limited' if target.get('guidance_gap') else None
        if q in judgments:
            relevant=set(judgments[q])
            hits=sum(bool(set(r['all_source_files'])&relevant) for r in record['top3'])
            record['precision_at_3']=hits/3
            record['success_at_3']=int(hits>0)
        records.append(record)
    c=connect(args.db)
    intact=True
    for r in c.execute('SELECT filename,raw_hash FROM sources'):
        path=ROOT/'Parsed'/r['filename']
        intact &= hashlib.sha256(path.read_bytes()).hexdigest()==r['raw_hash']
    m=manifest(c);c.close()
    report={'mode':'hybrid' if dense else 'keyword','reranker_requested':args.rerank,'build_id':m['build_id'],'python':platform.python_version(),
            'platform':platform.platform(),'original_sources_match_index_hashes':intact,
            'index_bytes':args.db.stat().st_size,'queries':records, 'include_partial':args.include_partial, 'reviewed_targets_note':'Source-content retrieval checks only, not clinical relevance or accuracy judgments.',
            'note':'Warm timings include a repeated-query memory cache in hybrid mode; uncached timings are measured separately. Not representative of an old laptop. No clinical relevance scores unless judgments supplied. Cross-language semantic matching requires hybrid mode.'}
    args.output.write_text(json.dumps(report,indent=2,ensure_ascii=False))
    print(f'{len(records)} queries; median warm retrieval {statistics.median(r["median_warm_ms"] for r in records):.1f} ms; source hashes intact: {intact}')
    print(f'Report: {args.output}')
