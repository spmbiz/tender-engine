#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,json
from collections import defaultdict
from pathlib import Path

def read(p):
    with open(p,encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def n(v):
    try:return float(v) if v not in ('',None,'None') else None
    except:return None

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--matrix',required=True);ap.add_argument('--examples',required=True);ap.add_argument('--out',required=True);a=ap.parse_args();out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    rows=read(a.matrix); ex=read(a.examples); fam=defaultdict(lambda:{'title_digital':0,'scope_digital':0,'physical':0,'onsite':0,'legal':0,'total':0,'countries':set(),'weighted_values':[],'bidders':[],'suppliers':0.0})
    for r in rows:
        f=r['info_family'];rec=int(float(r['records']));d=fam[f];d['total']+=rec;d['countries'].add(r['country'])
        flag=r['delivery_flag'];sig=r['signal_source']
        if flag=='DIGITAL_FIRST_OR_REMOTE_PLAUSIBLE' and sig=='TITLE_SIGNAL':d['title_digital']+=rec
        elif flag=='DIGITAL_FIRST_OR_REMOTE_PLAUSIBLE':d['scope_digital']+=rec
        elif flag.startswith('PHYSICAL'):d['physical']+=rec
        elif flag=='ONSITE_OR_LOCATION_DEPENDENT':d['onsite']+=rec
        elif flag=='LEGAL_SPECIALIST_RISK':d['legal']+=rec
        med=n(r.get('median_value')); bid=n(r.get('median_bidders')); sup=n(r.get('suppliers'))
        if med is not None:d['weighted_values'].append((med,rec))
        if bid is not None:d['bidders'].append((bid,rec))
        if sup is not None:d['suppliers']+=sup
    def wavg(vals):
        den=sum(w for _,w in vals);return sum(x*w for x,w in vals)/den if den else None
    ranking=[]
    for f,d in fam.items():
        # Directional SPM score: strong credit for title-led remote evidence; physical/legal are penalties.
        score=100*(d['title_digital']+0.35*d['scope_digital'])/max(d['total'],1) - 45*d['physical']/max(d['total'],1)-55*d['legal']/max(d['total'],1)-40*d['onsite']/max(d['total'],1)
        ranking.append({'family':f,'total':d['total'],'title_digital':d['title_digital'],'scope_digital':d['scope_digital'],'physical':d['physical'],'onsite':d['onsite'],'legal':d['legal'],'countries':len(d['countries']),'weighted_median_value_proxy':wavg(d['weighted_values']),'weighted_median_bidders_proxy':wavg(d['bidders']),'asymmetry_evidence_score':round(score,1)})
    ranking.sort(key=lambda x:(x['asymmetry_evidence_score'],x['title_digital'],x['total']),reverse=True)
    with (out/'family_asymmetry.csv').open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(ranking[0]));w.writeheader();w.writerows(ranking)
    # Pull title-led digital examples only for manual QA.
    ekeep=[r for r in ex if r.get('delivery_flag')=='DIGITAL_FIRST_OR_REMOTE_PLAUSIBLE' and r.get('signal_source')=='TITLE_SIGNAL']
    by=defaultdict(list)
    for r in ekeep:by[r['info_family']].append(r)
    lines=['# SPM Information-Work Asymmetry View v1','', 'Historical-only derived view. `asymmetry_evidence_score` is a routing heuristic, not a source fact or bidability verdict. It rewards explicit title-led digital/remote evidence and penalizes physical/legal/onsite composition.','']
    for i,r in enumerate(ranking,1):
        lines += [f"## {i}. {r['family']} — asymmetry evidence {r['asymmetry_evidence_score']}",f"- total **{r['total']}** · title+digital **{r['title_digital']}** · scope+digital **{r['scope_digital']}** · physical **{r['physical']}** · onsite **{r['onsite']}** · legal **{r['legal']}** · countries **{r['countries']}**",f"- weighted median-value proxy **{r['weighted_median_value_proxy']}** · bidders proxy **{r['weighted_median_bidders_proxy']}**"]
        for e in by.get(r['family'],[])[:6]:
            lines.append(f"- example: {e.get('country')} — {e.get('buyer')} — {e.get('title')} — value {e.get('reference_value')}")
        lines.append('')
    (out/'REPORT.md').write_text('\n'.join(lines),encoding='utf-8')
    (out/'summary.json').write_text(json.dumps({'version':'SPM_INFORMATION_WORK_ASYMMETRY_VIEW_V1','families':len(ranking),'precision_rows':sum(r['total'] for r in ranking),'title_led_digital_rows':sum(r['title_digital'] for r in ranking),'ranking':ranking,'historical_only':True,'score_role':'MODEL_ROUTING_HEURISTIC_NOT_FACT','record_deletion':False},indent=2,ensure_ascii=False),encoding='utf-8')
if __name__=='__main__':main()
