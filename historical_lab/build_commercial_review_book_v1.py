#!/usr/bin/env python3
from __future__ import annotations

import argparse,csv,json,re
from collections import defaultdict,Counter
from pathlib import Path


def read_csv(path: Path):
    if not path.exists(): return []
    with path.open(encoding='utf-8',errors='replace',newline='') as f:
        return list(csv.DictReader(f))


def nint(v):
    try:return int(float(v or 0))
    except:return 0


def fnum(v):
    try:return float(v)
    except:return None


def semantic_signature_ok(s: str)->bool:
    s=(s or '').strip()
    letters=sum(ch.isalpha() for ch in s)
    words=re.findall(r'[A-Za-zÀ-ÿ]{3,}',s)
    if letters<12 or len(words)<3:return False
    # Reject signatures that are essentially contract/reference-number templates.
    alpha=' '.join(words).lower()
    if alpha in {'con gaucon','request proposal','task order','delivery order'}:return False
    return True


def build(prefix:str, root:Path, cap:int):
    clusters=read_csv(root/f'{prefix}_high_signal_clusters.csv')
    examples=read_csv(root/f'{prefix}_cluster_examples.csv')
    ex=defaultdict(list)
    key_fields=('country','currency','route_band','native_code','phrase_signature')
    for r in examples:
        k=tuple((r.get(x) or '') for x in key_fields)
        if len(ex[k])<3:ex[k].append(r)
    clusters.sort(key=lambda r:(-(fnum(r.get('market_structure_signal')) or 0),-nint(r.get('records'))))
    selected=[]; per_country=Counter(); per_code=Counter()
    for r in clusters:
        if nint(r.get('records'))<3:continue
        sig=r.get('phrase_signature') or ''
        if not semantic_signature_ok(sig):continue
        country=r.get('country') or 'UNKNOWN'; code=r.get('native_code') or 'NO_CODE'
        if per_country[country]>=35:continue
        if per_code[(country,code)]>=8:continue
        k=tuple((r.get(x) or '') for x in key_fields)
        row=dict(r); row['_examples']=ex.get(k,[])
        selected.append(row);per_country[country]+=1;per_code[(country,code)]+=1
        if len(selected)>=cap:break
    return selected


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',required=True);ap.add_argument('--out',required=True);a=ap.parse_args()
    root=Path(a.root);out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    sources=[]
    for p,label,cap in [('global_core','GLOBAL CORE NOTICE-FIRST',140),('australia','AUSTENDER AWARD-FIRST',70),('usa','USASPENDING AWARD-FIRST',100)]:
        if (root/f'{p}_high_signal_clusters.csv').exists():sources.append((label,build(p,root,cap)))
    lines=['# Historical Commercial Review Book v1','',
           'Derived strictly from historical structured archives. No live notices or DCEs are used.','',
           'Clusters are ranked by the new empirical market-structure miner. This book only removes signatures that are visibly reference-number noise; semantic business-fit adjudication remains manual.','']
    flat=[]
    for label,rows in sources:
        lines += [f'## {label} — {len(rows)} reviewable cohorts','']
        for i,r in enumerate(rows,1):
            top=r.get('top_supplier_share')
            topdisp='UNKNOWN' if top in (None,'') else f"{100*float(top):.1f}%"
            lines.append(f"### {i}. {r.get('country')} · `{r.get('native_code')}` · {r.get('phrase_signature')}")
            lines.append(f"- Structure: **{r.get('market_structure_signal')}** · records **{r.get('records')}** · buyers **{r.get('buyers')}** · repeat buyers **{r.get('repeat_buyers')}**")
            lines.append(f"- Route `{r.get('route_band')}` · currency `{r.get('currency')}` · p25 **{r.get('p25_value') or 'UNKNOWN'}** · median **{r.get('median_value') or 'UNKNOWN'}** · p75 **{r.get('p75_value') or 'UNKNOWN'}**")
            lines.append(f"- Median bidders **{r.get('median_bidders') or 'UNKNOWN'}** · suppliers **{r.get('suppliers') or 'UNKNOWN'}** · top supplier share **{topdisp}** · shape `{r.get('recurrence_shape')}`")
            examples=r.get('_examples') or []
            if examples:
                lines.append('- Historical examples:')
                for e in examples:
                    lines.append(f"  - {e.get('buyer_name') or 'UNKNOWN BUYER'} — {e.get('title') or ''} — value {e.get('reference_value') or 'UNKNOWN'}")
            lines.append('')
            x={k:v for k,v in r.items() if k!='_examples'};x['examples']=examples;flat.append(x)
    (out/'REVIEW_BOOK.md').write_text('\n'.join(lines),encoding='utf-8')
    (out/'review_book.json').write_text(json.dumps(flat,ensure_ascii=False,indent=2),encoding='utf-8')
    summary={'sources':{label:len(rows) for label,rows in sources},'total_reviewable':sum(len(rows) for _,rows in sources),'live_used':False,'dce_used':False,'semantic_finalized':False}
    (out/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8')

if __name__=='__main__':main()
