// Run the actual UI with a minimal DOM to check query-edit lifecycle and stale responses.
// node tests/test_ui.js (no packages or browser downloads required).
'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
class Element {
 constructor(){this.children=[];this.listeners={};this.value='';this.hidden=false;this.disabled=false;this.checked=false;}
 append(...xs){this.children.push(...xs);}
 replaceChildren(...xs){this.children=xs;}
 addEventListener(name,cb){this.listeners[name]=cb;}
 setAttribute(){}
}
const nodes=new Map();
const node=id=>{if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);};
node('#page-size').value='10';node('#mode').value='auto';
const fields={condition:'cholera',population:'children',severity:null,task:'treatment',preferred_source:null};
const requests=[];
let deferNext=null;
function response(url){
 if(url==='/api/status')return {stats:{source_files:582,indexed_canonical_documents:561,passages:21951,excluded_sources:18},languages:[],genres:[],hybrid_available:true,reranker_available:true,dense_note:'local'};
 const p=new URL(url,'http://localhost').searchParams;
 const f={...fields};
 for(const k of Object.keys(f))if(p.has('facet_'+k))f[k]=p.get('facet_'+k)||null;
 return {facets:f,query:p.get('q'),retrieval_query:p.get('q'),results:[],mode:'hybrid',evidence:'limited',message:'Candidates',total_results:0,latency_ms:1};
}
const context=vm.createContext({document:{querySelector:node,createElement:()=>new Element()},URLSearchParams,console,fetch:async url=>{
 requests.push(url);
 if(deferNext){const deferred=deferNext;deferNext=null;return await deferred;}
 return {ok:true,json:async()=>response(url)};
}});
const root=process.env.SEARCH_PROJECT_ROOT||path.resolve(__dirname,'..');
vm.runInContext(fs.readFileSync(path.join(root,'local_search/static/ui.js'),'utf8'),context);
const flush=async()=>{for(let i=0;i<4;i++)await new Promise(setImmediate);};
const run=()=>vm.runInContext('runSearch(false)',context);
const params=()=>new URL(requests.at(-1),'http://localhost').searchParams;
const chip=k=>node('#facet-chips').children.find(c=>c.children[0].textContent===k+':');
(async()=>{
 await flush();
 node('#q').value='cholera treatment children';await run();
 assert.equal(params().has('facet_condition'),false);
 await run();assert.equal(params().has('facet_condition'),false,'Automatic hints must not silently rewrite the query');
 let c=chip('condition');c.children[1].value='tuberculosis';c.children[1].listeners.change();await flush();
 assert.equal(params().get('facet_condition'),'tuberculosis');
 chip('condition').children[2].listeners.click();await flush();
 assert.equal(params().has('facet_condition'),true);assert.equal(params().get('facet_condition'),'','Removed field must reach backend as empty');
 node('#q').value='new request';node('#q').listeners.input();await run();
 assert.equal(params().has('facet_condition'),false,'New request must not inherit edited fields');
 assert.equal(node('#reset-facets').hidden,true);
 let resolveOld;deferNext=new Promise(r=>resolveOld=r);
 const old=run();
 node('#q').value='latest request';node('#q').listeners.input();await run();
 resolveOld({ok:true,json:async()=>({...response('/api/search?q=old'),facets:{condition:'STALE'}})});await old;
 assert.notEqual(vm.runInContext('activeFacets.condition',context),'STALE','Stale response must not overwrite newer state');
 console.log('UI lifecycle passed: explicit edits/removals, new-query reset, and stale-response protection.');
})().catch(e=>{console.error(e);process.exitCode=1;});
