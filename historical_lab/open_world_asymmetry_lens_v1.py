#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,re,csv
from pathlib import Path

# These are mechanisms, not verdicts. A cluster may match several.
MECH={
 'RECRUITMENT_MATCHING': r'\b(recruitment|recruiting|headhunt|executive search|talent acquisition|personnel search)\b',
 'TRAINING_CONTENT_DELIVERY': r'\b(training|education and training|course|tuition|learning services|instruction|workshop)\b',
 'ASSURANCE_REVIEW_EVALUATION': r'\b(assurance review|independent review|evaluation|assessment|quality review|peer review|verification|validation)\b',
 'EXPERT_NETWORK_PROFESSIONAL': r'\b(expert witness|expert services|specialist advice|specialist services|litigative consultant|prosecution counsel)\b',
 'LODGING_RELOCATION_AGGREGATION': r'\b(lodging|hotel|motel|relocation|accommodation)\b',
 'LOCAL_SERVICE_SUBCONTRACTING': r'\b(janitorial|custodial|pest control|laundry services|grounds maintenance|cleaning services)\b',
 'COMMODITY_DISTRIBUTION': r'\b(salt|deicing|de-icing|water drinking|paper goods|office consumables|food supply|bread|beef|bulk supply)\b',
 'TELECOM_RESELL_AGGREGATION': r'\b(wireless services|telecommunications|mobile service|telecom service|network carrier)\b',
 'ICT_HARDWARE_DISTRIBUTION': r'\b(ict hardware|ict equipment|computer equipment and accessories|computer equipment)\b',
 'RENTAL_LEASING_INTERMEDIATION': r'\b(lease|leasing|rental|hire of|equipment hire)\b',
 'LEGAL_SERVICE_NETWORK': r'\b(legal services|legal advice|counsel|law firm)\b',
 'AUDIT_INSPECTION_TESTING': r'\b(audit|inspection|testing services|test services|certification|calibration)\b',
 'CALL_CONTACT_SUPPORT': r'\b(call center|call centre|contact center|contact centre|help desk|customer support|customer service)\b',
 'EVENT_CONFERENCE_OPERATIONS': r'\b(event management|conference|seminar|venue hire|event services|exhibition)\b',
 'INTERPRETATION_LANGUAGE': r'\b(interpreting|interpretation services|interpreter)\b',
 'RECORDS_INFO_ADMIN': r'\b(records management|record management|filing|document management|information management|archive services|archiving)\b',
 'COLLECTIONS_RECOVERY': r'\b(debt collection|collection services|recovery services|receivables)\b',
 'BENEFITS_PAYROLL_ADMIN': r'\b(payroll|benefits administration|employee benefits|salary packaging)\b',
 'SURVEY_FIELD_RESEARCH': r'\b(survey services|survey research|market research|polling|questionnaire|field research)\b',
 'CONTENT_MEDIA_PRODUCTION': r'\b(video production|photography|animation|copywriting|editorial|content production|public relations)\b',
}
RX={k:re.compile(v,re.I) for k,v in MECH.items()}

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--input',required=True);ap.add_argument('--out',required=True);a=ap.parse_args()
 out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
 rows=[json.loads(x) for x in Path(a.input).read_text(encoding='utf-8').splitlines() if x.strip()]
 tagged=[]
 for r in rows:
  blob=(r.get('text','')+' '+' '.join(r.get('examples') or [])).lower()
  hits=[k for k,rx in RX.items() if rx.search(blob)]
  if not hits:continue
  for h in hits:
   tagged.append((h,r))
 stats={}
 for h,r in tagged:
  s=stats.setdefault(h,{'clusters':0,'records_sum':0.0,'buyers_sum':0.0,'suppliers_sum':0.0,'examples':[]})
  s['clusters']+=1;m=r.get('metrics') or {}
  s['records_sum']+=m.get('records') or 0;s['buyers_sum']+=m.get('buyers') or 0;s['suppliers_sum']+=m.get('suppliers') or 0
  if len(s['examples'])<12:s['examples'].append({'source':r.get('source'),'triage':r.get('triage'),'text':r.get('text'),'metrics':m,'examples':r.get('examples')})
 ordered=sorted(stats.items(),key=lambda kv:(kv[1]['clusters'],kv[1]['records_sum']),reverse=True)
 (out/'summary.json').write_text(json.dumps({'version':'HISTORICAL_OPEN_WORLD_ASYMMETRY_LENS_V1','reviewed_unknown_clusters':len(rows),'tagged_cluster_mechanism_pairs':len(tagged),'mechanisms':{k:{x:v for x,v in s.items() if x!='examples'} for k,s in ordered},'historical_only':True,'verdict_role':'DISCOVERY_NOT_PROMOTION'},indent=2,ensure_ascii=False),encoding='utf-8')
 lines=['# Historical Open-World Asymmetry Lens v1','',f'- unknown clusters reviewed: **{len(rows)}**',f'- mechanism matches: **{len(tagged)}**','', 'Mechanism tags are discovery hypotheses only. They do not delete, reject or promote the underlying records.','']
 for h,s in ordered:
  lines += [f'## {h}',f"- clusters **{s['clusters']}** · summed records **{int(s['records_sum']):,}** · summed buyer-count observations **{int(s['buyers_sum']):,}** · summed supplier-count observations **{int(s['suppliers_sum']):,}**"]
  for e in s['examples'][:8]:
   m=e['metrics'];lines.append(f"- {e['source']} · triage {e['triage']} · records={m.get('records')} buyers={m.get('buyers')} suppliers={m.get('suppliers')} median={m.get('median_value')} :: {e['text']}")
  lines.append('')
 (out/'REPORT.md').write_text('\n'.join(lines),encoding='utf-8')
 with open(out/'tagged_clusters.csv','w',encoding='utf-8',newline='') as f:
  w=csv.writer(f);w.writerow(['mechanism','source','triage','records','buyers','suppliers','median_value','text'])
  for h,r in sorted(tagged,key=lambda x:x[1].get('triage',0),reverse=True):
   m=r.get('metrics') or {};w.writerow([h,r.get('source'),r.get('triage'),m.get('records'),m.get('buyers'),m.get('suppliers'),m.get('median_value'),r.get('text')])
if __name__=='__main__':main()
