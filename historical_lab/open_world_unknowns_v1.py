#!/usr/bin/env python3
"""Build a historical-only review queue of commercially interesting clusters that do not
obviously match the current SPM ontology.

This is intentionally recall-first. It never deletes records or declares a business family
false. Known-family text is used only to create a *review lane* of not-yet-named clusters.
Canonical historical archives/releases remain authority.
"""
from __future__ import annotations
import argparse,csv,json,re
from pathlib import Path

KNOWN = re.compile(r"""(?ix)
\b(web|website|cms|wordpress|drupal|hosting|accessibility|translation|transcription|subtitle|caption|proofread|graphic|design|dtp|layout|printing|print|mailing|envelop|fulfil|fulfill|routage|mise\s+sous\s+pli|software|licen[cs]|saas|cloud|reseller|value\s+added\s+reseller|\bvar\b|staffing|temporary\s+personnel|labour\s+hire|contractor|business\s+analyst|developer|engineer|cyber|devops|data\s+analyst|data\s+engineer|technical\s+writer|project\s+manager|program\s+manager|scrum|agile|travel\s+agency|travel\s+management|media\s+buy|insurance\s+broker|real\s+estate\s+broker|freight\s+forward|office\s+suppl|stationery|furniture|workwear|ppe|epi|protective\s+clothing|paper|toner|ink\s+cartridge|signage|school\s+suppl|promotional\s+(item|merch)|goodies|uniform|packaging\s+material|waste\s+bags)\b
""")

BAD_HEAVY = re.compile(r"(?ix)\b(construction|road\s+works|civil\s+works|engineering\s+works|architectural\s+works|hospital\s+clinical|surgery|medical\s+device|pharmaceutical|weapon|ammunition|fuel\s+supply|electricity\s+supply|gas\s+supply)\b")

METRIC_HINTS = {
 'records':['records','record_count','cluster_records','n','count'],
 'buyers':['buyers','buyer_count','unique_buyers','distinct_buyers'],
 'repeat_buyers':['repeat_buyers','recurring_buyers'],
 'suppliers':['suppliers','supplier_count','unique_suppliers','distinct_suppliers'],
 'median_value':['median_value','median_award_value','median_estimated_value','median_reference_value'],
 'median_bidders':['median_bidders','median_bidder_count'],
 'score':['historical_score','priority_score','structure_score','score'],
}
TEXT_HINTS=['cluster_signature','signature','normalized_signature','title_signature','cluster_key','title','scope','description','native_code','route','country','currency']
ID_HINTS=['cluster_id','cluster_key','id','signature']

def pick(d, names):
    lower={k.lower():k for k in d}
    for n in names:
        if n in lower:return lower[n]
    for k in d:
        lk=k.lower()
        if any(n in lk for n in names):return k
    return None

def num(v):
    try:return float(str(v).replace(',','').strip())
    except:return None

def read(path):
    with open(path,encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--input',required=True);ap.add_argument('--out',required=True);a=ap.parse_args()
    root=Path(a.input);out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    all_candidates=[];schemas={}
    for source in ('global_core','usa','australia'):
        hp=root/f'{source}_high_signal_clusters.csv'
        ep=root/f'{source}_cluster_examples.csv'
        if not hp.exists():continue
        rows=read(hp); ex=read(ep) if ep.exists() else []
        if not rows:continue
        schemas[source]={'high_signal_columns':list(rows[0]),'example_columns':list(ex[0]) if ex else []}
        # Build an example-text map using whichever cluster-ish field is common.
        hkeys=list(rows[0]); ekeys=list(ex[0]) if ex else []
        common=[k for k in hkeys if k in ekeys and any(t in k.lower() for t in ('cluster','signature','key'))]
        join=common[0] if common else None
        exmap={}
        if join:
            for r in ex:
                exmap.setdefault(r.get(join,''),[]).append(r)
        for r in rows:
            text=' | '.join(str(r.get(k,'')) for k in r if any(h in k.lower() for h in TEXT_HINTS)).strip()
            if KNOWN.search(text):continue
            heavy=bool(BAD_HEAVY.search(text))
            metrics={}
            for m,hints in METRIC_HINTS.items():
                k=pick(r,hints); metrics[m]=num(r.get(k)) if k else None
            records=metrics['records'] or 0; buyers=metrics['buyers'] or 0; suppliers=metrics['suppliers']
            # Structure-only triage: broad/repeat markets first. Heavy sectors retained but demoted.
            triage=(min(records,1000)**0.5)*2 + (min(buyers,500)**0.5)*3
            if metrics['repeat_buyers'] is not None: triage += min(metrics['repeat_buyers'],100)**0.5*2
            if suppliers is not None: triage += min(suppliers,500)**0.5
            if metrics['score'] is not None: triage += max(0,min(metrics['score'],100))/20
            if heavy:triage-=12
            example_rows=exmap.get(r.get(join,''),[])[:4] if join else []
            examples=[]
            for er in example_rows:
                et=' | '.join(str(er.get(k,'')) for k in er if any(x in k.lower() for x in ('title','buyer','scope','description')))
                if et:examples.append(et[:700])
            all_candidates.append({'source':source,'triage':round(triage,3),'heavy_flag':heavy,'text':text[:1200],'metrics':metrics,'examples':examples,'raw':r})
    all_candidates.sort(key=lambda x:x['triage'],reverse=True)
    # Diversity: no more than 4 exact normalized text-prefix siblings.
    selected=[];seen={}
    for c in all_candidates:
        key=re.sub(r'\W+',' ',c['text'].lower()).strip()[:90]
        if seen.get(key,0)>=4:continue
        seen[key]=seen.get(key,0)+1;selected.append(c)
        if len(selected)>=1000:break
    (out/'summary.json').write_text(json.dumps({'version':'HISTORICAL_OPEN_WORLD_UNKNOWNS_V1','candidate_clusters_after_known_lane_exclusion':len(all_candidates),'review_queue':len(selected),'sources':schemas,'historical_only':True,'record_deletion':False,'interpretation':'Review queue only; absence from current ontology is not itself evidence of SPM fit.'},indent=2,ensure_ascii=False),encoding='utf-8')
    with open(out/'review_queue.jsonl','w',encoding='utf-8') as f:
        for x in selected:f.write(json.dumps(x,ensure_ascii=False)+'\n')
    lines=['# Historical Open-World Unknowns v1','',f'- candidates after known-lane exclusion: **{len(all_candidates):,}**',f'- review queue: **{len(selected):,}**','', 'This is a historical-only semantic review queue. It deliberately preserves weird/unknown markets and never deletes their source records.','']
    for i,c in enumerate(selected[:250],1):
        m=c['metrics']; lines += [f"## {i}. {c['source']} · triage {c['triage']}" ,f"- records={m['records']} buyers={m['buyers']} repeat_buyers={m['repeat_buyers']} suppliers={m['suppliers']} median_value={m['median_value']} median_bidders={m['median_bidders']} heavy_flag={c['heavy_flag']}",f"- signature: {c['text']}"]
        for e in c['examples'][:3]:lines.append(f'- example: {e}')
        lines.append('')
    (out/'REVIEW_PACKET.md').write_text('\n'.join(lines),encoding='utf-8')
if __name__=='__main__':main()
