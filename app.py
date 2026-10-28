#!/usr/bin/env python3
"""Local browser search UI: standard-library server, no hosted services or downloads."""
import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from local_search.search import connect, document, manifest, search

ROOT=Path(__file__).resolve().parent


def serve(db_path,port,use_reranker=True):
    c=connect(db_path)
    info=manifest(c)
    languages=[r[0] for r in c.execute('SELECT DISTINCT language FROM sources ORDER BY language')]
    genres=[r[0] for r in c.execute('SELECT DISTINCT genre FROM sources ORDER BY genre')]
    c.close()
    dense=None
    dense_note='No local vector index. Keyword search is active; no model is downloaded.'
    if (db_path.parent/'embedding_manifest.json').exists():
        try:
            from local_search.embeddings import DenseIndex
            dense=DenseIndex(db_path)
            dense_note='Local E5 vectors loaded. Hybrid search is available.'
        except Exception as exc:
            dense_note=f'Vectors unavailable: {exc}. Keyword search is active.'
    reranker = None
    reranker_path = ROOT / 'models' / 'reranker'
    if use_reranker and reranker_path.is_dir():
        try:
            from local_search.reranker import LocalReranker
            reranker = LocalReranker(reranker_path, device='cpu')
            dense_note += ' Local AI reranker available for English query/candidate passages.'
        except Exception as exc:
            dense_note += ' Local reranker unavailable; normal retrieval remains active.'
            print(f'Reranker load failed: {exc}')
    elif not use_reranker:
        dense_note += ' Passage reranking is disabled.'
    else:
        dense_note += ' No local passage reranker model is installed.'
    dense_lock=threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):
            pass  # Do not log clinical search queries.

        def send(self,value,status=200,kind='application/json; charset=utf-8'):
            payload=json.dumps(value,ensure_ascii=False).encode() if kind.startswith('application/json') else value
            self.send_response(status)
            self.send_header('Content-Type',kind)
            self.send_header('Content-Length',str(len(payload)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Referrer-Policy','no-referrer')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            # Bound to loopback; also reject unexpected Host headers (DNS rebinding).
            if self.headers.get('Host','') not in {f'127.0.0.1:{port}',f'localhost:{port}'}:
                return self.send({'error':'Local requests only'},403)
            url=urlparse(self.path)
            args=parse_qs(url.query,keep_blank_values=True)
            get=lambda name,default='':args.get(name,[default])[0]
            try:
                if url.path=='/api/status':
                    self.send(dict(info,embedding_status='ready' if dense is not None else 'unavailable',languages=languages,genres=genres,hybrid_available=dense is not None,dense_note=dense_note,reranker_available=reranker is not None,parser_method='local_rules'))
                elif url.path=='/api/search':
                    facets = {}
                    for field in ('condition', 'population', 'severity', 'task', 'preferred_source'):
                        if f'facet_{field}' in args:
                            facets[field] = get(f'facet_{field}')[:500]
                    with dense_lock:
                        self.send(search(db_path,get('q'),get('language'),get('genre'),dense=dense,
                                         reranker=reranker if get('rerank','true')=='true' else None,
                                         group_related=get('group')=='true',mode=get('mode','auto'),
                                         limit=int(get('limit','10')),offset=int(get('offset','0')),
                                         include_partial=get('partial')=='true',
                                         facets=facets if facets else None))
                elif url.path=='/api/document':
                    self.send(document(db_path,get('filename')))
                elif url.path in ('/','/ui.js','/style.css'):
                    name={'/':'index.html','/ui.js':'ui.js','/style.css':'style.css'}[url.path]
                    mime={'/':'text/html; charset=utf-8','/ui.js':'application/javascript; charset=utf-8','/style.css':'text/css; charset=utf-8'}[url.path]
                    self.send((ROOT/'local_search'/'static'/name).read_bytes(),kind=mime)
                else:
                    self.send({'error':'Not found'},404)
            except KeyError:
                self.send({'error':'Unknown source filename'},404)
            except ValueError as exc:
                self.send({'error':str(exc)},409)
            except Exception:
                import traceback
                traceback.print_exc()
                self.send({'error':'Search failed. Check the local terminal.'},500)

    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    print(f'Local search: http://127.0.0.1:{port}',flush=True)
    print(dense_note,flush=True)
    print('Listening on this computer only. Ctrl+C stops the server.',flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db',type=Path,default=ROOT/'data/search.sqlite')
    p.add_argument('--port',type=int,default=8765)
    p.add_argument('--no-rerank',action='store_true',help='Skip loading the optional passage model')
    args=p.parse_args()
    if not args.db.exists():
        p.error('Build the local index first: python3 build_index.py')
    serve(args.db.resolve(),args.port,use_reranker=not args.no_rerank)
