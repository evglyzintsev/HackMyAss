#!/usr/bin/env python3
"""Build vectors using an existing local multilingual E5 model; no downloads."""
import argparse
from pathlib import Path
from local_search.embeddings import build_vectors

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--model',type=Path,required=True)
    p.add_argument('--db',type=Path,default=Path(__file__).resolve().parent/'data/search.sqlite')
    p.add_argument('--device',choices=['auto','cpu','mps'],default='auto',help='Preprocessing only; serving uses CPU')
    p.add_argument('--batch-size',type=int,default=24)
    p.add_argument('--max-tokens',type=int,default=256)
    args=p.parse_args()
    build_vectors(args.db,args.model,args.device,args.batch_size,args.max_tokens)
