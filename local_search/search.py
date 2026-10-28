"""SQLite keyword retrieval, optional local dense retrieval, and rank fusion."""
import json
import re
import sqlite3
import time
from pathlib import Path
from .ingest import STOPWORDS, WORD, tokens
from .lexical import retrieve as diversified_lexical


def connect(path):
    c = sqlite3.connect(f'file:{Path(path).resolve()}?mode=ro', uri=True)
    c.row_factory = sqlite3.Row
    return c


def manifest(c):
    return {r['key']: json.loads(r['value']) for r in c.execute('SELECT * FROM manifest')}


def rrf(rankings, k=60):
    scores = {}
    for ranking in rankings:
        for rank, pid in enumerate(dict.fromkeys(ranking), 1):
            scores[pid] = scores.get(pid, 0) + 1 / (k + rank)
    return scores


def query_terms(query):
    return list(dict.fromkeys(t for t in tokens(query) if t not in STOPWORDS and len(t)>1))[:32]


ACTION_TERMS = {'treatment','management','guideline','dose','dosage','protocol','therapy',
                'traitement','tratamiento','prise','charge','gestion','posologie','علاج','العلاج','جرعة'}
CLINICAL_TASKS = ACTION_TERMS | {'complication','complications','diagnosis','diagnostic','symptom','symptoms',
                                'contraindication','contraindications','prevention'}
NON_CLINICAL_GENRES = {'Financial Report', 'Activity Report Chapter'}

# Clinical facet lexicon for query parsing
POPULATION_TERMS = {
    'child': 'children', 'children': 'children', 'pediatric': 'children', 'paediatric': 'children',
    'infant': 'infants', 'infants': 'infants', 'neonate': 'neonates', 'neonates': 'neonates', 'newborn': 'neonates',
    'newborns': 'neonates', 'adult': 'adults', 'adults': 'adults', 'adolescent': 'adolescents',
    'adolescents': 'adolescents', 'pregnancy': 'pregnancy', 'pregnant': 'pregnancy', 'maternal': 'pregnancy',
    'refugee': 'refugees', 'refugees': 'refugees', 'displaced': 'refugees',
    'enfant': 'children', 'enfants': 'children', 'pédiatrique': 'children', 'nourrisson': 'infants',
    'grossesse': 'pregnancy', 'femme enceinte': 'pregnancy', 'nouveau-né': 'neonates',
    'niño': 'children', 'niños': 'children', 'pediátrico': 'children', 'lactante': 'infants',
    'embarazo': 'pregnancy', 'embarazada': 'pregnancy', 'recién nacido': 'neonates',
    'طفل': 'children', 'أطفال': 'children', 'حامل': 'pregnancy', 'الحمل': 'pregnancy', 'رضيع': 'infants',
}

SEVERITY_TERMS = {
    'severe': 'severe', 'acute': 'acute', 'chronic': 'chronic', 'mild': 'mild', 'moderate': 'moderate',
    'complicated': 'complicated', 'uncomplicated': 'uncomplicated', 'emergency': 'emergency',
    'shock': 'shock', 'dehydration': 'dehydration', 'severe dehydration': 'severe dehydration',
    'sévère': 'severe', 'grave': 'severe', 'aigu': 'acute', 'aigue': 'acute', 'chronique': 'chronic',
    'compliqué': 'complicated', 'choc': 'shock', 'déshydratation': 'dehydration',
    'severo': 'severe', 'grave': 'severe', 'agudo': 'acute', 'crónico': 'chronic',
    'complicado': 'complicated', 'deshidratación': 'dehydration',
    'شديد': 'severe', 'حادة': 'acute', 'حاد': 'acute', 'مزمن': 'chronic', 'صدمة': 'shock', 'جفاف': 'dehydration',
}

TASK_TERMS = {
    'treatment': 'treatment', 'treatments': 'treatment', 'therapy': 'treatment', 'management': 'management',
    'dose': 'dosage', 'dosage': 'dosage', 'protocol': 'protocol', 'guideline': 'guideline', 'guidelines': 'guideline',
    'diagnosis': 'diagnosis', 'diagnostic': 'diagnosis', 'symptom': 'symptoms', 'symptoms': 'symptoms',
    'prevention': 'prevention', 'vaccination': 'vaccination', 'vaccine': 'vaccination',
    'surveillance': 'surveillance', 'monitoring': 'monitoring', 'screening': 'screening',
    'traitement': 'treatment', 'prise en charge': 'management', 'posologie': 'dosage', 'protocole': 'protocol',
    'guide': 'guideline', 'diagnostic': 'diagnosis', 'symptôme': 'symptoms', 'symptômes': 'symptoms',
    'prévention': 'prevention', 'vaccination': 'vaccination',
    'tratamiento': 'treatment', 'manejo': 'management', 'dosis': 'dosage', 'protocolo': 'protocol',
    'guía': 'guideline', 'diagnóstico': 'diagnosis', 'síntomas': 'symptoms', 'prevención': 'prevention',
    'علاج': 'treatment', 'جرعة': 'dosage', 'بروتوكول': 'protocol', 'دليل': 'guideline', 'تشخيص': 'diagnosis',
    'وقاية': 'prevention', 'لقاح': 'vaccination', 'تطعيم': 'vaccination',
}

SOURCE_TERMS = {
    'guideline': 'clinical guideline', 'guidelines': 'clinical guideline', 'protocol': 'clinical guideline',
    'manual': 'clinical guideline', 'guide': 'clinical guideline', 'monograph': 'clinical guideline',
    'guia': 'clinical guideline', 'guía': 'clinical guideline', 'protocole': 'clinical guideline',
    'article': 'peer-reviewed article', 'study': 'peer-reviewed article', 'paper': 'peer-reviewed article',
    'report': 'report', 'brief': 'advocacy brief',
}


FACET_FIELDS = ('condition', 'population', 'severity', 'task', 'preferred_source')


def parse_query(raw_query):
    """Editable hints from local rules, not diagnosis or clinical entity recognition.

    Match normalized phrases but retain unknown words and explicit negation.
    The original query remains the retrieval input until a user edits a field.
    """
    clean = raw_query.strip()
    spans = list(WORD.finditer(clean))
    words = [tokens(m.group())[0] for m in spans]
    lexicons = {
        'population': {k:v for k,v in POPULATION_TERMS.items()
                       if k not in {'maternal', 'displaced'}},
        'severity': dict(SEVERITY_TERMS, **{
            'déshydratation sévère':'severe dehydration',
            'deshidratación severa':'severe dehydration'}),
        'task': TASK_TERMS, 'preferred_source': SOURCE_TERMS,
    }
    values = {k:[] for k in FACET_FIELDS}
    consumed = set()
    negations = {'not', 'no', 'without', 'excluding', 'except', 'sans', 'non',
                 'pas', 'sin', 'excepto', 'بدون', 'غير'}
    for field, lexicon in lexicons.items():
        phrases = sorted(((tokens(k), v) for k,v in lexicon.items()),
                         key=lambda x: -len(x[0]))
        used = set()
        for phrase, value in phrases:
            for i in range(len(words)-len(phrase)+1):
                end = i+len(phrase)
                if used.intersection(range(i,end)) or words[i:end] != phrase:
                    continue
                start = i
                # Keep "not in children", "without severe dehydration", etc.
                for j in range(i-1,max(-1,i-4),-1):
                    if words[j] in negations:
                        start=j
                        value_here=clean[spans[start].start():spans[end-1].end()]
                        break
                    if words[j] not in STOPWORDS:
                        break
                else:
                    value_here=value
                if start==i:
                    value_here=value
                if value_here not in values[field]:
                    values[field].append(value_here)
                used.update(range(i,end));consumed.update(range(start,end))
    # Unrecognized terms are preserved verbatim. No whole-query fallback fabricates a disease.
    remaining = [m.group() for i,m in enumerate(spans)
                 if i not in consumed and words[i] not in STOPWORDS]
    values['condition'] = remaining
    return {k:' '.join(v) or None for k,v in values.items()}


def edited_query(original, parsed, overrides):
    if overrides is None:
        return original
    for key, value in overrides.items():
        if key in parsed:
            if not isinstance(value, str):
                raise ValueError('Query fields must be text.')
            parsed[key] = value.strip()[:500] or None
    return ' '.join(dict.fromkeys(parsed[k] for k in FACET_FIELDS
                                 if k!='preferred_source' and parsed[k]))[:500]


def refresh_passage_evidence(record, terms, context_terms, dense_ids):
    """Evidence labels must describe the passage actually displayed after reranking."""
    p = record['passage']
    if p is None:
        return
    title = record['title'] if record['title_source']!='opening_excerpt' else ''
    words = set(tokens(title+' '+p['section']+' '+p['text']))
    hits = [t for t in terms if t in words]
    complete = context_terms <= set(hits)
    semantic = p['id'] in dense_ids
    record.update(matched_terms=hits, missing_terms=[t for t in terms if t not in hits],
                  topic_match='full' if complete else ('semantic' if semantic else 'partial'),
                  match_kind='word_match' if complete else ('semantic' if semantic else 'partial_keyword'))




def minimum_span(words, required):
    if not required:
        return None
    counts={}
    left=0
    best=None
    for right,word in enumerate(words):
        if word in required:
            counts[word]=counts.get(word,0)+1
        while len(counts)==len(required):
            span=right-left+1
            best=span if best is None else min(best,span)
            first=words[left]
            if first in counts:
                counts[first]-=1
                if counts[first]==0:
                    del counts[first]
            left+=1
    return best


def search(db_path, query, language='', genre='', dense=None, reranker=None, limit=10, group_related=False, mode='auto', offset=0, include_partial=False, facets=None):
    start = time.perf_counter()
    # Page size limits presentation, never the number of distinct ranked documents.
    limit=max(1,min(50,int(limit)))
    offset=max(0,int(offset))
    c = connect(db_path)
    query = query.strip()[:500]
    parsed_facets = parse_query(query)
    retrieval_query = edited_query(query, parsed_facets, facets)
    terms = query_terms(retrieval_query)
    mode_name = 'hybrid' if dense is not None and mode != 'keyword' else 'keyword'
    result = {'query': query, 'retrieval_query':retrieval_query, 'facets': parsed_facets,
              'parser_method':'local_rules', 'rerank_status':'not_used',
              'mode': mode_name, 'results': [], 'evidence': 'none', 'message': '', 'latency_ms': 0,
              'offset':offset,'limit':limit,'total_candidates':0,'total_results':0,
              'hidden_partial_count':0,'has_more':False,'include_partial':bool(include_partial)}
    # Identifier lookup is exact and includes excluded records so PDF mappings are never lost.
    lookup = query if query.endswith('.md') else query+'.md'
    source = c.execute('SELECT * FROM sources WHERE filename=?', (lookup,)).fetchone()
    if source:
        doc = c.execute('SELECT * FROM documents WHERE doc_id=?',(source['doc_id'],)).fetchone()
        passage = c.execute('SELECT * FROM passages WHERE doc_id=? ORDER BY id LIMIT 1',(source['doc_id'],)).fetchone()
        result['results'] = [result_record(c, doc, passage, 0, [], preferred=source['filename'])] if offset==0 else []
        result['total_candidates']=result['total_results']=1
        result['evidence'], result['message'] = 'identifier', 'Exact source filename match. This is not a relevance judgment.'
    elif terms:
        conditions, params = [], []
        source_conditions = []
        if language:
            source_conditions.append('s.language=?');params.append(language)
        if genre:
            source_conditions.append('s.genre=?');params.append(genre)
        if source_conditions:
            conditions.append('EXISTS(SELECT 1 FROM sources s WHERE s.doc_id=d.doc_id AND '
                              +' AND '.join(source_conditions)+')')
        sql_filter = (' AND '+' AND '.join(conditions)) if conditions else ''
        match = ' OR '.join('"'+t.replace('"','""')+'"' for t in terms)
        lexical=diversified_lexical(c,match,sql_filter,params)
        rankings = [[r['id'] for r in lexical]]
        allowed = None
        dense_ids=set()
        if mode_name == 'hybrid':
            if conditions:
                allowed={r[0] for r in c.execute('SELECT p.id FROM passages p JOIN documents d USING(doc_id) WHERE 1=1'+sql_filter,params)}
            try:
                semantic=dense.search(retrieval_query,100,allowed)
                dense_ids=set(semantic)
                rankings.append(semantic)
            except Exception:
                mode_name='keyword'
                result['mode']='keyword'
                result['vector_warning']='The local vector search failed; these are keyword results.'
        scores = rrf(rankings)
        clinical_intent = bool(set(terms) & CLINICAL_TASKS) or bool(parsed_facets.get('task')) or bool(parsed_facets.get('preferred_source') == 'clinical guideline')
        context_terms=set(terms)-ACTION_TERMS
        context_terms-= {'complication','complications','diagnosis','diagnostic','symptom','symptoms','prevention'}
        if not context_terms:
            context_terms=set(terms)
        candidates=[]
        for pid, score in scores.items():
            p=c.execute('SELECT * FROM passages WHERE id=?',(pid,)).fetchone()
            d=c.execute('SELECT * FROM documents WHERE doc_id=?',(p['doc_id'],)).fetchone()
            title_text = d['title'] if d['title_source'] != 'opening_excerpt' else ''
            evidence_words=tokens(title_text+' '+p['section']+' '+p['text'])
            evidence_tokens=set(evidence_words)
            hit_terms=[t for t in terms if t in evidence_tokens]
            # Match coverage is a ranking heuristic, never displayed as clinical confidence.
            coverage=len(context_terms & set(hit_terms))/len(context_terms)
            # Zero lexical overlap must not bury multilingual semantic candidates.
            score *= (.75 + .25*coverage) if pid in dense_ids else (.25 + .75*coverage)
            span=minimum_span(evidence_words,context_terms)
            if span is not None and len(context_terms)>1:
                score *= 1.15 if span<=8*len(context_terms)+8 else .85
            task_terms=set(terms)&ACTION_TERMS
            if task_terms & set(tokens(p['section'])):
                score *= 1.35
            if p['role']=='references':
                score *= .4
            if clinical_intent and d['genre']=='Clinical Guideline Chapter' and d['content_role']=='content':
                score *= 1.2
            if clinical_intent and d['genre'] in NON_CLINICAL_GENRES:
                score *= 0.65
            preference = parsed_facets.get('preferred_source') or ''
            if ((preference=='clinical guideline' and d['genre']=='Clinical Guideline Chapter'
                 and d['content_role']=='content') or
                (preference=='peer-reviewed article' and d['genre']=='Peer-reviewed Article')):
                score *= 1.08  # Editable source preference, never a hidden hard filter.
            if d['content_role']!='content':
                score *= .72
            candidates.append((score,p,d,hit_terms))
        candidates.sort(key=lambda x:(-x[0],x[1]['id']))
        all_candidate_docs={p['doc_id'] for _,p,_,_ in candidates}
        eligible_docs={p['doc_id'] for _,p,_,hits in candidates
                       if include_partial or context_terms<=set(hits) or p['id'] in dense_ids}
        result['total_candidates']=len(all_candidate_docs)
        result['hidden_partial_count']=len(all_candidate_docs-eligible_docs)
        seen=set()
        groups=[]
        grouped_under={}
        for score,p,d,hits in candidates:
            doc_id=d['doc_id']
            complete=context_terms<=set(hits)
            is_semantic=p['id'] in dense_ids
            if not include_partial and not complete and not is_semantic:
                continue
            if doc_id in seen:
                continue
            if group_related:
                close=[r[0] if r[1]==doc_id else r[1] for r in c.execute(
                    'SELECT doc_a,doc_b FROM relationships WHERE (doc_a=? OR doc_b=?) AND jaccard>=0.9',(doc_id,doc_id))]
                previous=next((x for x in close if x in grouped_under),None)
                if previous:
                    groups[grouped_under[previous]]['grouped_versions'].append(source_summary(c,doc_id))
                    seen.add(doc_id)
                    continue
            record=result_record(c,d,p,score,hits)
            if source_conditions:
                selected = next(s for s in record['sources']
                                if (not language or s['language']==language)
                                and (not genre or s['genre']==genre))
                record.update({k:selected[k] for k in ('filename','genre','language','supplied_language')})
            record['missing_terms']=[t for t in terms if t not in hits]
            record['topic_match']='full' if complete else ('semantic' if is_semantic else 'partial')
            record['match_kind']='word_match' if complete else ('semantic' if is_semantic else 'partial_keyword')
            record['other_passages']=[]
            for _,other,_,_ in candidates:
                if other['doc_id']==doc_id and other['id']!=p['id'] and other['role']!='references' and other['section']!=p['section']:
                    record['other_passages'].append(dict(other))
                    if len(record['other_passages'])>=2:
                        break
            grouped_under[doc_id]=len(groups)
            groups.append(record)
            seen.add(doc_id)
        if reranker is not None and groups:
            from .reranker import query_eligibility
            permitted, note = query_eligibility(retrieval_query)
            result['rerank_note']=note
            if permitted:
                try:
                    groups = reranker.rerank(retrieval_query, groups, top_k=10,
                                             clinical_intent=clinical_intent, query_language='en',
                                             eligible={x['doc_id'] for x in groups if x['content_role']=='content'
                                                       and 'missing_drug_identity' not in x['quality']})
                    result['rerank_status']='applied' if any(x.get('reranked') for x in groups) else 'skipped'
                except Exception:
                    result['rerank_status']='fallback'
                    result['rerank_note']='Local reranking failed; the BM25/vector ranking is shown.'
            else:
                result['rerank_status']='skipped'
            for record in groups:
                refresh_passage_evidence(record, terms, context_terms, dense_ids)
        result['total_results']=len(groups)
        result['results']=groups[offset:offset+limit]
        result['has_more']=offset+limit<len(groups)
        if groups:
            top=groups[0]
            required=max(1,(len(terms)+1)//2)
            no_guidance = clinical_intent and not any(x['genre']=='Clinical Guideline Chapter' and x['content_role']=='content' and 'missing_drug_identity' not in x['quality'] and x['passage']['role']!='references' and context_terms <= set(x['matched_terms']) for x in groups[:5])
            weak=len(top['matched_terms'])<required or top['content_role']!='content' or 'missing_drug_identity' in top['quality'] or no_guidance
            result['evidence']='limited' if weak else 'unverified'
            semantic_guidance=mode_name=='hybrid' and any(x['genre']=='Clinical Guideline Chapter' and x['content_role']=='content' and x['topic_match']=='semantic' and x['passage']['role']!='references' for x in groups[:5])
            result['message']=('Some guideline candidates use different wording or language. Inspect the source passage for the condition, population, and severity.' if no_guidance and semantic_guidance else 'No guideline passage matches all topic/context words among the first five results. Check the condition, population, and severity; these may be background matches.' if no_guidance else 'Limited lexical evidence or non-substantive content in the top match. The collection may not contain the requested guidance.' if weak else
                'Retrieved source matches. Relevance, clinical applicability, and currency are not verified by the search score.')
        else:
            if result['hidden_partial_count']:
                result['evidence']='limited'
            result['message']=('No complete topic-word matches in the ranked candidate pool. Enable partial keyword matches to inspect broader candidates.'
                               if result['hidden_partial_count'] else 'No matching passages. Try fewer terms, another spelling, or broader filters.')
    else:
        result['message']='Enter a disease, topic, phrase, or exact .md filename.'
    if result.get('vector_warning'):
        result['message']=result['vector_warning']+' '+result['message']
    result['latency_ms']=round((time.perf_counter()-start)*1000,2)
    c.close()
    return result


def review_record(c,doc_id):
    r=c.execute('SELECT details FROM reviews WHERE doc_id=?',(doc_id,)).fetchone()
    return json.loads(r[0]) if r else None


def sources_for(c,doc_id):
    return [dict(x) for x in c.execute('''SELECT s.filename,s.genre,s.language,
        COALESCE(l.supplied_language,s.language) AS supplied_language,l.method AS language_method
        FROM sources s LEFT JOIN source_languages l USING(filename) WHERE s.doc_id=? ORDER BY s.filename''',(doc_id,))]


def source_summary(c,doc_id):
    row=c.execute('SELECT title,content_role FROM documents WHERE doc_id=?',(doc_id,)).fetchone()
    files=sources_for(c,doc_id)
    return {'doc_id':doc_id,'title':row['title'],'content_role':row['content_role'],'sources':files}


def result_record(c,d,p,score,hits,preferred=None):
    sources=sources_for(c,d['doc_id'])
    related=[]
    for r in c.execute('SELECT * FROM relationships WHERE doc_a=? OR doc_b=?',(d['doc_id'],d['doc_id'])):
        other=r['doc_b'] if r['doc_a']==d['doc_id'] else r['doc_a']
        related.append(dict(source_summary(c,other), relationship=r['kind'], similarity=round(r['jaccard'],3),
                            source_coverage=round(r['coverage_a'] if r['doc_a']==d['doc_id'] else r['coverage_b'],3)))
    return {'doc_id':d['doc_id'],'filename':preferred or d['doc_id'],'title':d['title'],'title_source':d['title_source'],
            'genre':d['genre'],'language':d['language'],'supplied_language':next((s['supplied_language'] for s in sources if s['filename']==(preferred or d['doc_id'])),d['language']),'content_role':d['content_role'],
            'quality':json.loads(d['quality']),'excluded_reason':d['excluded_reason'],'sources':sources,
            'passage':dict(p) if p else None,'matched_terms':hits,'missing_terms':[], 'topic_match':'identifier', 'match_kind':'identifier',
            'other_passages':[], 'review':review_record(c,d['doc_id']), 'related':related,'grouped_versions':[]}


def document(db_path,filename):
    c=connect(db_path)
    row=c.execute('SELECT s.*,d.title,d.quality,d.excluded_reason,COALESCE(l.supplied_language,s.language) AS supplied_language FROM sources s JOIN documents d USING(doc_id) LEFT JOIN source_languages l USING(filename) WHERE s.filename=?',(filename,)).fetchone()
    if row is None:
        c.close()
        raise KeyError('Unknown source filename')
    packaged_root=Path(db_path).resolve().parent.parent
    root=packaged_root if (packaged_root/'Parsed').is_dir() else Path(manifest(c)['source_root'])
    p=root/'Parsed'/row['filename']
    import hashlib
    raw=p.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=row['raw_hash']:
        c.close()
        raise ValueError('Source file changed since indexing. Rebuild the index before using passage locations.')
    answer=dict(row)
    answer['text']=raw.decode('utf-8')
    answer['line_count']=len(answer['text'].split('\n'))
    answer['review']=review_record(c,row['doc_id'])
    c.close()
    return answer


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument('query');p.add_argument('--db',type=Path,default=Path(__file__).resolve().parent.parent/'data/search.sqlite')
    args=p.parse_args()
    print(json.dumps(search(args.db,args.query),ensure_ascii=False,indent=2))
