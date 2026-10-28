#!/usr/bin/env python3
"""Explicit one-time cross-encoder download for local offline reranking."""
import json
import os
from pathlib import Path

os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
os.environ['DO_NOT_TRACK'] = '1'

if __name__ == '__main__':
    from huggingface_hub import HfApi, snapshot_download
    repo = 'cross-encoder/ms-marco-MiniLM-L-6-v2'
    root = Path(__file__).resolve().parent
    destination = root / 'models/reranker'
    revision = '233902d25c440f23af6f7d6e94d2946bac0bee0a'
    info = HfApi(token=False).model_info(repo, revision=revision)
    print(f'Downloading {repo} at pinned revision {revision} (~80MB)...', flush=True)
    snapshot_download(
        repo_id=repo,
        revision=revision,
        local_dir=destination,
        token=False,
        allow_patterns=['model.safetensors', '*.json', '*.txt', 'README.md', 'LICENSE*']
    )
    if not (destination / 'model.safetensors').exists():
        raise RuntimeError('Expected model weights were not downloaded.')

    manifest_path = root / 'models/reranker_manifest.json'
    manifest_path.write_text(json.dumps({
        'repository': repo,
        'revision': revision,
        'local_path': 'models/reranker',
        'license': getattr(info.card_data, 'license', 'apache-2.0')
    }, indent=2))
    print(f'Reranker model saved locally: {destination}', flush=True)
