#!/usr/bin/env python3
import argparse,json
from pathlib import Path

ap=argparse.ArgumentParser()
ap.add_argument('--input',required=True)
ap.add_argument('--out',required=True)
ap.add_argument('--limit',type=int,default=250)
a=ap.parse_args()
rows=[]
with open(a.input,encoding='utf-8') as f:
    for i,line in enumerate(f):
        if i>=a.limit: break
        if not line.strip(): continue
        x=json.loads(line)
        rows.append({k:x.get(k) for k in ['candidate_id','score','source_family','title','buyer','deadline','estimated_value','positive_hits','negative_hits']})
Path(a.out).parent.mkdir(parents=True,exist_ok=True)
with open(a.out,'w',encoding='utf-8') as f:
    json.dump(rows,f,ensure_ascii=False,indent=2)
print(json.dumps({'rows':len(rows),'out':a.out}))
