"""Local-only E5 retrieval. Model acquisition is a separate, explicit command."""
import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path

os.environ['HF_HUB_OFFLINE']='1'
os.environ['TRANSFORMERS_OFFLINE']='1'
os.environ['HF_HUB_DISABLE_TELEMETRY']='1'
os.environ['DO_NOT_TRACK']='1'
os.environ['TOKENIZERS_PARALLELISM']='false'


def load_model(path, device='cpu', max_tokens=256):
    local=Path(path).expanduser().resolve()
    if not local.is_dir():
        raise ValueError('An existing local E5 model directory is required. Downloads are disabled during search.')
    import torch
    torch.set_num_threads(min(4,os.cpu_count() or 1))
    from sentence_transformers import SentenceTransformer
    model=SentenceTransformer(str(local),device=device,local_files_only=True,trust_remote_code=False,
                              model_kwargs={'use_safetensors':True})
    model.max_seq_length=min(int(model.max_seq_length),max_tokens)
    return model


def passage_windows(model,rows):
    tokenizer=model.tokenizer
    limit=int(model.max_seq_length)
    texts,ids=[],[]
    for row in rows:
        # A fallback opening excerpt is not a document title and should not contaminate every window.
        title='' if row['title_source']=='opening_excerpt' else row['title'][:200]
        header='\n'.join(x for x in (title,row['section'][:220]) if x)
        prefix='passage: '+(header+'\n' if header else '')
        budget=limit-len(tokenizer.encode(prefix,add_special_tokens=True))-8
        if budget<32:
            prefix,budget='passage: ',limit-16
        body=tokenizer.encode(row['text'],add_special_tokens=False,truncation=False,verbose=False)
        start=0
        while start<len(body):
            end=min(start+budget,len(body))
            text=prefix+tokenizer.decode(body[start:end],skip_special_tokens=True)
            while len(tokenizer.encode(text,add_special_tokens=True))>limit:
                end-=1
                if end<=start:
                    raise ValueError('Cannot fit model input window.')
                text=prefix+tokenizer.decode(body[start:end],skip_special_tokens=True)
            texts.append(text);ids.append(row['id'])
            if end>=len(body):
                break
            start=max(start+1,end-24)
    return ids,texts


def fingerprint(model_path):
    if not Path(model_path).is_dir():
        raise ValueError(f'Local model directory is missing: {model_path}')
    h=hashlib.sha256()
    for p in sorted(Path(model_path).rglob('*')):
        if not p.is_file() or any(part.startswith('.') for part in p.relative_to(model_path).parts):
            continue
        h.update(p.relative_to(model_path).as_posix().encode())
        with p.open('rb') as f:
            for chunk in iter(lambda:f.read(1024*1024),b''):
                h.update(chunk)
    return h.hexdigest()


def encode_cached(model,texts,cache_path,model_hash,batch_size=24):
    import numpy as np
    cache=sqlite3.connect(cache_path)
    cache.execute('CREATE TABLE IF NOT EXISTS vectors(key TEXT PRIMARY KEY,value BLOB)')
    keys=[hashlib.sha256((model_hash+f':tokens={model.max_seq_length}:v2:'+text).encode()).hexdigest() for text in texts]
    needed=dict(zip(keys,texts))
    vectors={}
    for key in needed:
        hit=cache.execute('SELECT value FROM vectors WHERE key=?',(key,)).fetchone()
        if hit:
            vectors[key]=np.frombuffer(hit[0],dtype=np.float32).copy()
    todo=[key for key in needed if key not in vectors]
    print(f'{len(texts):,} windows; {len(needed):,} unique; {len(vectors):,} cached; {len(todo):,} to encode.',flush=True)
    start=time.perf_counter()
    for offset in range(0,len(todo),batch_size):
        batch=todo[offset:offset+batch_size]
        encoded=model.encode([needed[key] for key in batch],normalize_embeddings=True,
                             batch_size=batch_size,show_progress_bar=False,convert_to_numpy=True)
        if not np.isfinite(encoded).all():
            raise ValueError('Non-finite embedding values.')
        for key,vector in zip(batch,encoded):
            vector=np.asarray(vector,dtype=np.float32)
            vectors[key]=vector
            cache.execute('INSERT OR REPLACE INTO vectors VALUES(?,?)',(key,vector.tobytes()))
        cache.commit()
        completed=min(offset+len(batch),len(todo))
        if offset==0 or completed==len(todo) or (offset//batch_size)%20==0:
            print(f'Encoded {completed:,}/{len(todo):,} windows · {completed/max(.01,time.perf_counter()-start):.1f}/s',flush=True)
    cache.close()
    return np.stack([vectors[key] for key in keys])


def build_vectors(db_path,model_path,device='auto',batch_size=24,max_tokens=256):
    import numpy as np
    import torch
    from local_search.search import connect,manifest
    model_path=Path(model_path).expanduser().resolve()
    if device=='auto':
        device='mps' if torch.backends.mps.is_available() else 'cpu'
    print(f'Preprocessing device: {device}; retrieval stays CPU-only.',flush=True)
    model=load_model(model_path,device=device,max_tokens=max_tokens)
    model_hash=fingerprint(model_path)
    c=connect(db_path);m=manifest(c)
    rows=c.execute('SELECT p.*,d.title,d.title_source FROM passages p JOIN documents d USING(doc_id) ORDER BY p.id').fetchall();c.close()
    ids,texts=passage_windows(model,rows)
    base=Path(db_path).resolve().parent
    vectors=encode_cached(model,texts,base/'vector_cache.sqlite',model_hash,batch_size)
    tmp=base/'embeddings.building.npz'
    np.savez(tmp,vectors=np.asarray(vectors,dtype=np.float32),passage_ids=np.asarray(ids,dtype=np.int64),build_id=np.array(m['build_id']))
    os.replace(tmp,base/'embeddings.npz')
    # Relative paths make the project/model bundle portable.
    info={'build_id':m['build_id'],'model_path':os.path.relpath(model_path,base),
          'model_sha256':model_hash,'model_family':'e5','query_prefix':'query: ','passage_prefix':'passage: ',
          'max_tokens':int(model.max_seq_length),'rows':len(ids),'dimensions':int(vectors.shape[1]),'preprocessing_device':device}
    meta_tmp=base/'embedding_manifest.building.json';meta_tmp.write_text(json.dumps(info,indent=2))
    os.replace(meta_tmp,base/'embedding_manifest.json')
    print(json.dumps(info,indent=2),flush=True)


class DenseIndex:
    def __init__(self,db_path):
        import numpy as np
        self.np=np
        base=Path(db_path).resolve().parent
        self.info=json.loads((base/'embedding_manifest.json').read_text())
        c=sqlite3.connect(f'file:{Path(db_path).resolve()}?mode=ro',uri=True)
        build_id=json.loads(c.execute("SELECT value FROM manifest WHERE key='build_id'").fetchone()[0])
        passage_rows=c.execute('SELECT id,doc_id,role FROM passages').fetchall()
        valid_ids={r[0] for r in passage_rows}
        self.passage_docs={r[0]:r[1] for r in passage_rows}
        self.reference_ids={r[0] for r in passage_rows if r[2]=='references'}
        c.close()
        with np.load(base/'embeddings.npz',allow_pickle=False) as data:
            if str(data['build_id'])!=build_id or self.info['build_id']!=build_id:
                raise ValueError('Vector index belongs to another text build. Rebuild vectors.')
            self.ids,self.vectors=data['passage_ids'].copy(),data['vectors'].copy()
        if set(self.ids.tolist())!=valid_ids or len(self.ids)!=len(self.vectors):
            raise ValueError('Vector rows do not match passage IDs.')
        if self.vectors.ndim!=2 or self.vectors.shape[1]!=self.info['dimensions'] or not np.isfinite(self.vectors).all():
            raise ValueError('Invalid embedding matrix.')
        model_path=Path(self.info['model_path'])
        if not model_path.is_absolute():
            model_path=(base/model_path).resolve()
        if fingerprint(model_path)!=self.info['model_sha256']:
            raise ValueError('Local model changed; rebuild vectors.')
        self.model=load_model(model_path,device='cpu',max_tokens=self.info.get('max_tokens',256))
        self.last_scores={}
        # Avoid duplicate encoding across pages/filter changes; this memory cache is never written or logged.
        self._query_cache={}

    def search(self,query,limit=100,allowed=None):
        np=self.np
        q=self._query_cache.get(query)
        if q is None:
            q=self.model.encode('query: '+query,normalize_embeddings=True,show_progress_bar=False,convert_to_numpy=True)
            if len(self._query_cache)>=16:
                self._query_cache.pop(next(iter(self._query_cache)))
            self._query_cache[query]=q
        q=np.asarray(q,dtype=np.float32).reshape(-1)
        if q.shape!=(self.vectors.shape[1],) or not np.isfinite(q).all():
            raise ValueError('Invalid local query embedding.')
        # Explicit contraction avoids platform BLAS floating-point flag issues.
        scores=np.einsum('ij,j->i',self.vectors,q,optimize=False)
        best={}
        for pid,score in zip(self.ids.tolist(),scores.tolist()):
            if allowed is None or pid in allowed:
                best[pid]=max(best.get(pid,-float('inf')),score)
        # Diverse candidate generation precedes fusion: long reports cannot occupy every slot.
        selected=[]
        counts={}
        for pid in sorted(best,key=lambda pid:best[pid]*(.25 if pid in self.reference_ids else 1),reverse=True):
            doc=self.passage_docs[pid]
            if counts.get(doc,0)>=4:
                continue
            counts[doc]=counts.get(doc,0)+1
            selected.append(pid)
            if len(selected)>=limit:
                break
        self.last_scores={pid:best[pid] for pid in selected}
        return selected
