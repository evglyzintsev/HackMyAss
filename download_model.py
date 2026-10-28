#!/usr/bin/env python3
"""Explicit one-time public model download. Never reads or uploads source documents."""
import json
import os
from pathlib import Path

os.environ['HF_HUB_DISABLE_TELEMETRY']='1'
os.environ['DO_NOT_TRACK']='1'

if __name__=='__main__':
    from huggingface_hub import HfApi, snapshot_download
    repo='intfloat/multilingual-e5-small'
    root=Path(__file__).resolve().parent
    destination=root/'models/multilingual-e5-small'
    revision='614241f622f53c4eeff9890bdc4f31cfecc418b3'
    info = HfApi(token=False).model_info(repo, revision=revision)
    print(f'Downloading {repo} at pinned revision {revision}',flush=True)
    snapshot_download(repo_id=repo,revision=revision,local_dir=destination,token=False,
        allow_patterns=['model.safetensors','*.json','*.txt','*.model','README.md','LICENSE*','1_Pooling/*'])
    if not (destination/'model.safetensors').exists():
        raise RuntimeError('Expected safetensors model weights were not downloaded.')
    (root/'models/download_manifest.json').write_text(json.dumps({'repository':repo,'revision':revision,
        'local_path':'models/multilingual-e5-small','license':getattr(info.card_data,'license',None)},indent=2))
    print(f'Model saved locally: {destination}',flush=True)
