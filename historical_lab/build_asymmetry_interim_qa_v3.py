#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,json
from collections import defaultdict
from pathlib import Path


def read_csv(p):
    with open(p,encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))

def num(x):
    try:return float(x)
    except:return None

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--input',required=True);ap.add_argument('--out',required=True);a=ap.parse_args()
    root=Path(a.input);out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    pure=read_csv(root/'global_info_pure_core.csv')
    ex=read_csv(root/'global_info_examples.csv')
    tagged=read_csv(root/'open_world_tagged_clusters.csv')
    unknown=[]
    with open(root/'open_world_untagged_top.jsonl',encoding='utf-8') as f:
        for line in f:
            if line.strip():unknown.append(json.loads(line))
    exmap=defaultdict(list)
    for r in ex:exmap[(r.get('info_family',''),r.get('purity_class',''))].append(r)
    pure_sorted=sorted(pure,key=lambda r:(num(r.get('records')) or 0,num(r.get('buyers')) or 0),reverse=True)
    lines=['# Asymmetry Deep Dive v3 — Interim Semantic QA','',
           'Scope: historical archive only. Completed Global Core pure-information-work and open-world outputs; USA/Australia corrections are handled separately.','',
           '## Pure information-work core','']
    for r in pure_sorted:
        f=r.get('info_family');n=r.get('records');buyers=r.get('buyers');countries=r.get('countries');bidders=r.get('median_bidders')
        lines += [f'### {f}',f'- strict pure rows **{n}** · buyers **{buyers}** · countries **{countries}** · median bidders **{bidders or "UNKNOWN"}**']
        candidates=exmap.get((f,'PURE_DIGITAL_OR_REMOTE_SERVICE'),[])
        chosen=list(candidates[:5])
        tail=sorted(candidates,key=lambda x:(num(x.get('reference_value')) is None,num(x.get('reference_value')) or 1e99))
        for x in tail:
            if x not in chosen:chosen.append(x)
            if len(chosen)>=10:break
        for x in chosen[:10]:
            lines.append(f"- example: {x.get('country')} · {x.get('buyer')} · {x.get('title')} · value={x.get('reference_value') or 'UNKNOWN'} {x.get('currency') or ''} · bidders={x.get('bidder_count') or 'UNKNOWN'}")
        lines.append('')
    lines += ['## Next-wave mechanisms actually tagged','']
    by=defaultdict(list)
    for r in tagged:by[r.get('mechanism','UNKNOWN')].append(r)
    for mech,rows in sorted(by.items(),key=lambda kv:sum(num(x.get('records')) or 0 for x in kv[1]),reverse=True):
        rs=sum(num(x.get('records')) or 0 for x in rows);bs=sum(num(x.get('buyers')) or 0 for x in rows);ss=sum(num(x.get('suppliers')) or 0 for x in rows)
        lines += [f'### {mech}',f'- cluster matches **{len(rows)}** · summed record observations **{int(rs):,}** · buyer observations **{int(bs):,}** · supplier observations **{int(ss):,}**']
        for x in sorted(rows,key=lambda z:num(z.get('triage')) or 0,reverse=True)[:8]:
            lines.append(f"- {x.get('source')} · triage {x.get('triage')} · sig={x.get('phrase_signature')} · code={x.get('code_description')} · examples={x.get('example_titles')}")
        lines.append('')
    lines += ['## Highest-triage still-untagged clusters','',
              'These are especially important: the mechanism dictionary still does not know what they are. No negative verdict is implied.','']
    for i,r in enumerate(sorted(unknown,key=lambda x:x.get('triage') or 0,reverse=True)[:120],1):
        k=r.get('cluster_key') or {};examples=r.get('examples') or []
        lines += [f"### {i}. {r.get('source')} · triage {r.get('triage')}",
                  f"- {k.get('country')} / {k.get('currency')} · code={k.get('native_code')} · {r.get('code_description')} · signature={r.get('phrase_signature')}",
                  f"- records={r.get('records')} buyers={r.get('buyers')} repeat={r.get('repeat_buyers')} suppliers={r.get('suppliers')} top_share={r.get('top_supplier_share')} median={r.get('median_value')} bidders={r.get('median_bidders')}"]
        for e in examples[:5]:lines.append(f"- example: {e.get('buyer')} — {e.get('title')} — {e.get('reference_value')}")
        lines.append('')
    summary={'version':'ASYMMETRY_DEEPDIVE_V3_INTERIM_QA','pure_information_families':len(pure_sorted),'pure_information_rows_sum':sum(int(num(x.get('records')) or 0) for x in pure_sorted),'open_world_mechanisms_tagged':len(by),'open_world_tagged_cluster_rows':len(tagged),'open_world_untagged_rows_available':len(unknown),'historical_only':True,'record_deletion':False,'note':'Evidence for model review, not automatic promotion.'}
    (out/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8')
    (out/'QA_PACKET.md').write_text('\n'.join(lines),encoding='utf-8')
if __name__=='__main__':main()
