from __future__ import annotations

import argparse, hashlib, json, os
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE='https://dati.anticorruzione.it/opendata/download/dataset/cig-{year}/filesystem/cig_{fmt}_{year}_{month:02d}.zip'

def sha256(path:Path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--year',type=int,required=True);ap.add_argument('--month',type=int,required=True);ap.add_argument('--out',default='archive/it_anac_cig');args=ap.parse_args()
    out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    sess=requests.Session();sess.headers.update({'User-Agent':'Tender-Engine/5.3 (+public procurement research)','Accept':'application/zip,application/octet-stream,*/*'})
    attempts=[];saved=None
    for fmt in ('json','csv'):
        url=BASE.format(year=args.year,month=args.month,fmt=fmt)
        try:
            with sess.get(url,timeout=180,stream=True,allow_redirects=True) as r:
                rec={'format':fmt.upper(),'url':url,'resolved_url':r.url,'status':r.status_code,'content_type':r.headers.get('content-type'),'content_length':int(r.headers.get('content-length') or 0)}
                attempts.append(rec)
                if not r.ok:continue
                path=out/f'cig_{fmt}_{args.year}_{args.month:02d}.zip';total=0;prefix=b''
                with path.open('wb') as f:
                    for chunk in r.iter_content(1024*1024):
                        if not chunk:continue
                        if not prefix:prefix=chunk[:8]
                        total+=len(chunk);f.write(chunk)
                rec['bytes']=total;rec['magic']=prefix.hex()
                if not prefix.startswith(b'PK\x03\x04'):
                    path.unlink(missing_ok=True);rec['outcome']='NON_ZIP_BODY';continue
                rec['outcome']='DOWNLOADED';rec['file']=path.name;rec['sha256']=sha256(path);saved=rec;break
        except Exception as exc:attempts.append({'format':fmt.upper(),'url':url,'error':repr(exc)})
    stats={'source':'IT_ANAC_CIG_MONTHLY_ARCHIVE','year':args.year,'month':args.month,'generated_at':datetime.now(timezone.utc).isoformat(),'saved':saved,'attempts':attempts,'official_pattern':BASE,'semantics':'Authoritative ANAC monthly CIG archive. Archive/history evidence, not by itself proof that a procedure is currently open.'}
    (out/'stats.json').write_text(json.dumps(stats,indent=2,ensure_ascii=False),encoding='utf-8');print(json.dumps(stats,indent=2,ensure_ascii=False))
    if not saved:raise SystemExit(2)
if __name__=='__main__':main()
