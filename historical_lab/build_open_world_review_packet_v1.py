#!/usr/bin/env python3
from __future__ import annotations

import argparse,csv,json,math
from collections import Counter,defaultdict
from pathlib import Path


def fnum(v):
    try:
        x=float(v)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def load(path: Path, source_label: str):
    out=[]
    with path.open(encoding='utf-8',errors='replace',newline='') as f:
        for r in csv.DictReader(f):
            n=int(float(r.get('records') or 0))
            val=fnum(r.get('median_value'))
            bid=fnum(r.get('median_bidders'))
            buyers=None
            # Structural score intentionally ignores legacy avg_priority.
            volume=min(1.0, math.log1p(n)/math.log(101))
            value=0.35 if val is None else min(1.0, math.log1p(max(0,val))/math.log(2_000_001))
            comp=0.50 if bid is None else (1.0 if bid<=1 else .88 if bid<=3 else .72 if bid<=5 else .52 if bid<=10 else .25)
            # Mild diversity bonus for coded clusters; NO_CODE remains included.
            code=(r.get('code') or 'NO_CODE').strip() or 'NO_CODE'
            coded=.9 if code!='NO_CODE' else .65
            structural=round(100*(.42*volume+.28*value+.22*comp+.08*coded),2)
            x=dict(r)
            x.update(source_label=source_label, structural_signal=structural, median_value_num=val, median_bidders_num=bid)
            out.append(x)
    return out


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--global-core',required=True)
    ap.add_argument('--usa',required=True)
    ap.add_argument('--australia',required=True)
    ap.add_argument('--out',required=True)
    a=ap.parse_args()
    rows=[]
    rows += load(Path(a.global_core),'GLOBAL_CORE_V4')
    rows += load(Path(a.usa),'USASPENDING_V1')
    rows += load(Path(a.australia),'AUSTENDER_V1')

    # Keep all clusters in accounting. Review packet is a triage view only.
    candidates=[r for r in rows if int(float(r.get('records') or 0))>=3]
    candidates.sort(key=lambda r:(-r['structural_signal'],-int(float(r.get('records') or 0)),r.get('country',''),r.get('title_signature','')))

    # Avoid one country/source/code swamping human review. Round-robin caps retain diversity.
    selected=[]; per_country=Counter(); per_source=Counter(); per_code=Counter()
    for r in candidates:
        country=(r.get('country') or 'UNKNOWN').strip()
        src=r['source_label']; code=(r.get('code') or 'NO_CODE').strip()
        if per_country[country]>=80: continue
        if per_source[src]>=180: continue
        if per_code[(src,country,code)]>=12: continue
        selected.append(r); per_country[country]+=1; per_source[src]+=1; per_code[(src,country,code)]+=1
        if len(selected)>=420: break

    out=Path(a.out); out.mkdir(parents=True,exist_ok=True)
    fields=['source_label','warehouse_source','country','broad_family','code','title_signature','records','median_value','median_bidders','structural_signal']
    with (out/'review_packet.csv').open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore'); w.writeheader(); w.writerows(selected)

    # Markdown split into readable blocks, directly consumable by GPT/manual review.
    lines=['# Historical Open-World Review Packet v1','',
           'Structural triage only. Legacy `avg_priority` is deliberately ignored. No live/DCE evidence is used.','',
           f'- All existing open-world clusters loaded: **{len(rows):,}**',
           f'- Recurring clusters (>=3 records): **{len(candidates):,}**',
           f'- Diverse review packet: **{len(selected):,}**','']
    bysrc=defaultdict(list)
    for r in selected: bysrc[r['source_label']].append(r)
    for src in ('GLOBAL_CORE_V4','AUSTENDER_V1','USASPENDING_V1'):
        part=bysrc[src]
        lines += [f'## {src} — {len(part)} cohorts','']
        for i,r in enumerate(part,1):
            val=r.get('median_value') or 'UNKNOWN'; bid=r.get('median_bidders') or 'UNKNOWN'
            lines.append(f"{i}. **{r.get('country') or 'UNKNOWN'}** · code `{r.get('code') or 'NO_CODE'}` · n={r.get('records')} · median={val} · bidders={bid} · structure={r['structural_signal']} — {r.get('title_signature') or ''}")
        lines.append('')
    (out/'REVIEW_PACKET.md').write_text('\n'.join(lines),encoding='utf-8')
    summary={'all_clusters_loaded':len(rows),'recurring_clusters':len(candidates),'review_packet':len(selected),'source_counts':dict(Counter(r['source_label'] for r in selected)),'country_counts':dict(Counter((r.get('country') or 'UNKNOWN') for r in selected)),'legacy_avg_priority_used':False,'live_or_dce_used':False}
    (out/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8')

if __name__=='__main__': main()
