#!/usr/bin/env python3
from pathlib import Path
import json
from local_search.languages import apply_language_audit
if __name__=='__main__':
    changes=apply_language_audit(Path(__file__).resolve().parent/'data/search.sqlite',detect=True)
    print(json.dumps(changes,ensure_ascii=False,indent=2))
