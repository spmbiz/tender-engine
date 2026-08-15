#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv
from collections import defaultdict
from pathlib import Path


def read(p):
    with open(p,encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--examples',required=True);ap.add_argument('--winners',required=True);ap.add_argument('--buyers',required=True);ap.add_argument('--out',required=True);ap.add_argument('--group-cols',default='family,subfamily');ap.add_argument('--title',default='Historical Decomposition QA Packet');a=ap.parse_args()
    ex,wi,bu=read(a.examples),read(a.winners),read(a.buyers); groups=[x.strip() for x in a.group_cols.split(',') if x.strip()]
    def key(r):return tuple(r.get(g,'') for g in groups)
    E=defaultdict(list);W=defaultdict(list);B=defaultdict(list)
    for r in ex:E[key(r)].append(r)
    for r in wi:W[key(r)].append(r)
    for r in bu:B[key(r)].append(r)
    keys=sorted(set(E)|set(W)|set(B))
    lines=[f'# {a.title}','', 'This packet is for semantic/business QA. Representative examples and winner/buyer names are historical evidence; any strategic interpretation remains a model hypothesis.','']
    for k in keys:
        label=' → '.join(f'{g}={v}' for g,v in zip(groups,k))
        lines += [f'## {label}','']
        if E[k]:
            lines.append('### Representative examples')
            for r in E[k][:12]:
                bits=[]
                for c in ('buyer','supplier','title','award_value','reference_value','native_code','native_subcategory','subcategory','category'):
                    if r.get(c):bits.append(f'{c}: {r[c]}')
                lines.append('- '+' | '.join(bits))
            lines.append('')
        if W[k]:
            lines.append('### Top historical winners')
            for r in W[k][:15]:
                s=r.get('supplier','UNKNOWN'); awards=r.get('awards') or r.get('weighted_awards') or ''; share=r.get('supplier_share') or ''; shape=r.get('supplier_name_shape') or ''
                lines.append(f'- {s} — awards={awards} share={share} {shape}'.rstrip())
            lines.append('')
        if B[k]:
            lines.append('### Top historical buyers')
            for r in B[k][:15]:
                lines.append(f"- {r.get('buyer','UNKNOWN')} — awards={r.get('awards','')}")
            lines.append('')
    Path(a.out).write_text('\n'.join(lines),encoding='utf-8')
if __name__=='__main__':main()
