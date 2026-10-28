'use strict';
const $=s=>document.querySelector(s);
const el=(tag,cls,text)=>{const e=document.createElement(tag);if(cls)e.className=cls;if(text!==undefined)e.textContent=text;return e;};
let currentSource=null,currentLine=1,requestId=0,searchParams=null,loadedCount=0,activeFacets={},facetsEdited=false;
const langNames={en:'English',fr:'Français',es:'Español',ar:'العربية',unknown:'Unknown'};
function renderFacets(facets){
 const c=$('#facet-chips');c.replaceChildren();
 if(!facets)return c.hidden=true;
 activeFacets={...facets};
 let hasAny=false;
 for(const [k,v] of Object.entries(facets)){
  if(!v)continue;
  hasAny=true;
  const chip=el('span','chip');
  chip.append(el('strong','',k+':'));
  const input=el('input');
  input.value=v;
  input.setAttribute('aria-label','Query '+k.replaceAll('_',' '));
  input.addEventListener('change',()=>{activeFacets[k]=input.value.trim();facetsEdited=true;runSearch(false);});
  chip.append(input);
  const rm=el('button','chip-remove','✕');
  rm.title='Remove '+k;
  rm.type='button';
  rm.addEventListener('click',()=>{activeFacets[k]='';facetsEdited=true;runSearch(false);});
  chip.append(rm);
  c.append(chip);
 }
 c.hidden=!hasAny;
 $('#reset-facets').hidden=!facetsEdited;
}
async function api(url){const r=await fetch(url);const d=await r.json();if(!r.ok)throw Error(d.error||'Local request failed');return d;}
function fileButton(name,line=1,end=line){const b=el('button','file-button',name);b.type='button';b.addEventListener('click',()=>openSource(name,line,end));return b;}
function relatedRows(rows,parent){for(const r of rows){const row=el('div','related-row');row.append(el('span','',r.relationship?r.relationship.replaceAll('_',' ')+' · text similarity only; differences unreviewed':'Grouped related version; differences unreviewed'));for(const s of r.sources)row.append(fileButton(s.filename));parent.append(row);}}
async function openSource(filename,line=1,end=line){
 try{const d=await api('/api/document?filename='+encodeURIComponent(filename));currentSource=d;currentLine=line;
 $('#source-filename').textContent=filename;
 $('#source-meta').textContent=`${d.genre} · ${langNames[d.language]||d.language} · ${d.line_count} original lines`+(d.supplied_language&&d.supplied_language!==d.language?' · Supplied language label: '+(langNames[d.supplied_language]||d.supplied_language):'')+(d.excluded_reason?' · Excluded from topic search: '+d.excluded_reason:'');
 const warning=$('#source-review');warning.replaceChildren();
 if(d.review?.warnings?.length)for(const w of d.review.warnings)warning.append(el('p','quality',w.note+' (source lines '+w.line_start+'–'+w.line_end+')'));
 $('#pdf-note').textContent='PDF lookup ID: '+filename.replace(/\.md$/,'')+' · PDF location not configured';
 const content=$('#source-content');content.replaceChildren();
 const fragment=document.createDocumentFragment();d.text.split(/\r?\n/).forEach((text,i)=>{const row=el('div','source-line'+(i+1>=line&&i+1<=end?' match':''));row.id='line-'+(i+1);row.append(el('span','',String(i+1)));const span=el('span','',text);span.dir='auto';row.append(span);fragment.append(row);});content.append(fragment);
 if(!$('#document-dialog').open)$('#document-dialog').showModal();
 requestAnimationFrame(()=>$('#line-'+line)?.scrollIntoView({block:'center'}));
 }catch(e){$('#search-status').replaceChildren(el('div','notice limited',e.message));}
}
function renderResult(r,i){const card=el('article','result');const top=el('div','result-top');top.append(el('span','rank',String(i+1).padStart(2,'0')));const body=el('div','result-main');top.append(body);card.append(top);
 const h=el('h2','',r.title);h.dir='auto';body.append(h);
 const p=r.passage;body.append(fileButton(r.filename,p?.line_start||1,p?.line_end||1));
 const meta=el('div','metadata');for(const text of [r.genre,langNames[r.language]||r.language,r.content_role.replaceAll('_',' ')])meta.append(el('span','',text));body.append(meta);
 if(r.supplied_language&&r.supplied_language!==r.language)body.append(el('div','quality','Text language: '+(langNames[r.language]||r.language)+' · supplied label: '+(langNames[r.supplied_language]||r.supplied_language)));
 if(r.title_source==='opening_excerpt')body.append(el('div','quality','Display label is an opening excerpt, not a verified document title.'));
 if(r.review){const review=el('details');review.append(el('summary','','Reviewed content: '+r.review.role.replaceAll('_',' ')));review.append(el('p','',r.review.reason));review.append(el('p','','Document-structure review only; medical correctness and currency not verified.'));for(const w of r.review.warnings||[])review.append(el('p','quality',w.note+' (source lines '+w.line_start+'–'+w.line_end+')'));body.append(review);}
 if(r.topic_match==='semantic')body.append(el('div','quality','Semantic candidate · wording may differ, including across languages. Review source relevance.'));
 if(r.topic_match==='partial')body.append(el('div','quality','Partial keyword match · missing query words: '+r.missing_terms.join(', ')));
 if(r.quality.length)body.append(el('div','quality',r.quality.map(x=>x.replaceAll('_',' ')).join(' · ')));
 if(p){if(p.section)body.append(el('div','section',p.section));const snippet=el('div','passage',p.text);snippet.dir='auto';body.append(snippet);const open=el('button','source-link',`Open original · lines ${p.line_start}–${p.line_end}`);open.addEventListener('click',()=>openSource(r.filename,p.line_start,p.line_end));body.append(open);}
 if(r.excluded_reason)body.append(el('div','notice limited','Excluded from default topic search: '+r.excluded_reason.replaceAll('_',' ')));
 if(r.other_passages?.length){const sections=el('details');sections.append(el('summary','','Other matching sections in this document'));for(const x of r.other_passages){const b=el('button','',x.section||'Lines '+x.line_start+'–'+x.line_end);b.addEventListener('click',()=>openSource(r.filename,x.line_start,x.line_end));sections.append(b);}body.append(sections);}
 if(r.sources.length>1){const details=el('details');details.append(el('summary','',`${r.sources.length} identical source files — all PDF mappings retained`));for(const s of r.sources)details.append(fileButton(s.filename,p?.line_start||1,p?.line_end||1));body.append(details);}
 if(r.related.length){const details=el('details');details.append(el('summary','',`${r.related.length} related files / possible versions — not merged`));relatedRows(r.related,details);body.append(details);}
 if(r.grouped_versions.length){const details=el('details');details.append(el('summary','',`${r.grouped_versions.length} likely versions grouped here — inspect differences`));relatedRows(r.grouped_versions,details);body.append(details);}
 return card;
}
async function runSearch(append=false){
 const id=++requestId;$('#search-button').disabled=true;$('#load-more').disabled=true;$('#search-status').textContent='Searching local passages…';
 if(!append){
  loadedCount=0;$('#results').replaceChildren();$('#load-more').hidden=true;$('#pagination-status').textContent='';
  searchParams=new URLSearchParams({q:$('#q').value,language:$('#language').value,genre:$('#genre').value,mode:$('#mode').value,group:$('#group').checked,partial:$('#partial').checked,limit:$('#page-size').value,rerank:$('#rerank').checked});
  // Send empty fields too, so an explicit removal stays removed.
  if(facetsEdited)for(const [k,v] of Object.entries(activeFacets))searchParams.set('facet_'+k,v||'');
 }
 const params=new URLSearchParams(searchParams);params.set('offset',String(loadedCount));
 try{
  const data=await api('/api/search?'+params);if(id!==requestId)return;
  if(!append&&data.facets)renderFacets(data.facets);
  const offset=loadedCount;$('#results').append(...data.results.map((r,i)=>renderResult(r,offset+i)));loadedCount+=data.results.length;
  const label=`Showing ${loadedCount} of ${data.total_results} ranked candidate documents · ${data.latency_ms} ms retrieval · ${data.mode==='hybrid'?'Hybrid / BM25 + vectors':'Keyword / BM25'}`;
  const notice=el('div','notice'+(data.evidence==='limited'||data.evidence==='none'?' limited':''));notice.append(el('strong','',label),el('div','',data.message));
  notice.append(el('div','candidate-note','Counts describe the retrieved candidate pool, not confirmed relevant documents or every match in the library.'));
  if(data.retrieval_query!==data.query)notice.append(el('div','candidate-note','Searching edited fields: '+(data.retrieval_query||'(empty)')));
  if(data.rerank_status==='applied')notice.append(el('div','candidate-note','Local AI reranking applied to English candidates in the first ten positions.'));
  else if(data.rerank_note)notice.append(el('div','candidate-note',data.rerank_note));
  if(data.hidden_partial_count)notice.append(el('div','candidate-note',`${data.hidden_partial_count} partial-word candidate documents hidden. Enable “Include partial keyword matches” to inspect them.`));
  $('#search-status').replaceChildren(notice);$('#load-more').hidden=!data.has_more;
  $('#pagination-status').textContent=data.has_more?'More ranked candidates are available.':(loadedCount?'End of the current ranked candidate pool.':'');
 }catch(e){if(id===requestId){if(!append)$('#results').replaceChildren();$('#search-status').replaceChildren(el('div','notice limited',e.message));}}
 finally{if(id===requestId){$('#search-button').disabled=false;$('#load-more').disabled=false;}}
}
$('#search-form').addEventListener('submit',event=>{event.preventDefault();runSearch(false);});
$('#q').addEventListener('input',()=>{activeFacets={};facetsEdited=false;$('#facet-chips').hidden=true;$('#reset-facets').hidden=true;requestId++;$('#search-button').disabled=false;$('#load-more').hidden=true;$('#search-status').textContent='Request changed. Search to update results.';});
$('#reset-facets').addEventListener('click',()=>{activeFacets={};facetsEdited=false;runSearch(false);});
$('#load-more').addEventListener('click',()=>runSearch(true));
$('#close-dialog').addEventListener('click',()=>$('#document-dialog').close());
$('#jump-match').addEventListener('click',()=>$('#line-'+currentLine)?.scrollIntoView({block:'center'}));
$('#download-source').addEventListener('click',()=>{if(!currentSource)return;const a=el('a');const u=URL.createObjectURL(new Blob([currentSource.text],{type:'text/markdown;charset=utf-8'}));a.href=u;a.download=currentSource.filename;a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);});
api('/api/status').then(s=>{$('#rerank').disabled=!s.reranker_available;$('#rerank').checked=!!s.reranker_available;for(const l of s.languages){const o=el('option','',langNames[l]||l);o.value=l;$('#language').append(o);}for(const g of s.genres){const o=el('option','',g);o.value=g;$('#genre').append(o);}if(s.hybrid_available){const o=el('option','','Hybrid / BM25 + E5');o.value='hybrid';$('#mode').append(o);}$('#library-status').textContent=`${s.stats.source_files} original files · ${s.stats.indexed_canonical_documents} searchable documents · ${s.stats.passages.toLocaleString()} passages · ${s.stats.excluded_sources} repeated-shell sources excluded. ${s.dense_note}`;}).catch(e=>$('#library-status').textContent=e.message);
