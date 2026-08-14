from pathlib import Path
import json
BASE=Path('adapter_store/SCOTLAND_PCS'); BASE.mkdir(parents=True,exist_ok=True)
results=[{'key':'CULTURE_COLLECTIVE','ref':'JUL560711','status':'RECORD_INTEREST_REQUIRED','files':[]},{'key':'VIDEO_PRODUCTION','ref':'JUL560975','status':'RECORD_INTEREST_REQUIRED','files':[]}]
for r in results:
    out=BASE/r['key']; out.mkdir(parents=True,exist_ok=True); (out/'manifest.json').write_text(json.dumps(r,indent=2),encoding='utf-8')
print(json.dumps(results,indent=2))