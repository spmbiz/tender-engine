#!/usr/bin/env python3
"""Open-world historical review v2.

Fixes v1 example attribution by joining examples on the full commercial-cluster key rather
than phrase_signature alone. Meaningless/`other` phrase signatures are preserved in a
separate code-only queue instead of being discarded.
"""
from __future__ import annotations
import argparse,csv,json,re
from pathlib import Path

KNOWN=re.compile(r'''(?ix)\b(web|website|cms|hosting|accessibility|translation|transcription|subtitle|proofread|graphic|design|dtp|layout|printing|print|mailing|envelop|fulfil|routage|mise\s+sous\s+pli|software|licen[cs]|saas|cloud|reseller|value\s+added\s+reseller|staffing|temporary\s+personnel|labour\s+hire|contractor|business\s+analyst|developer|engineer|cyber|devops|data\s+analyst|data\s+engineer|technical\s+writer|project\s+manager|program\s+manager|scrum|agile|travel\s+agency|travel\s+management|media\s+buy|insurance\s+broker|real\s+estate\s+broker|freight\s+forward|office\s+suppl|stationery|furniture|workwear|ppe|protective\s+clothing|paper|toner|ink\s+cartridge|signage|school\s+suppl|promotional\s+(item|merch)|goodies|uniform|packaging\s+material|waste\s+bags|recruitment|expert\s+witness|litigati|interpreter|interpretation|court\s+report|training|e-learning|elearning|assurance\s+review|program\s+evaluation|event\s+management|venue\s+hire|janitorial|custodial|pest\s+control|laundry|grounds\s+maintenance|lodging|hotel)\b''')
HEAVY=re.compile(r'(?ix)\b(construction|road\s+works|civil\s+works|building\s+works|demolition|bridge\s+works|sewer|pipeline|medical\s+device|pharmaceutical|weapon|ammunition|fuel|electricity\s+supply|gas\s+supply)\b')
KEYCOLS=('warehouse_source','country','currency','route_band','native_code','phrase_signature')

def read(p):
 with open(p,encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def fnum(v):
 try:return float(str(v).replace(',','').strip())
 except:return None
def ckey(r):return tuple((r.get(k) or '').strip() for k in KEYCOLS)
def score(r):
 n=fnum(r.get('records')) or 0;b=fnum(r.get('buyers')) or 0;rb=fnum(r.get('repeat_buyers')) or 0;s=fnum(r.get('suppliers')) or 0;sig=(r.get('phrase_signature') or '')+' '+(r.get('code_description') or '')
 x=(min(n,2500)**.5)*2+(min(b,750)**.5)*3+(min(rb,250)**.5)*2+(min(s,750)**.5)
 sh=fnum(r.get('top_supplier_share'))
 if sh is not None:x+=(1-min(max(sh,0),1))*8
 if HEAVY.search(sig):x-=15
 return round(x,3)
def meaningful(sig):
 s=re.sub(r'[^a-z0-9]+',' ',(sig or '').lower()).strip()
 return bool(s and s not in {'other','unknown','n','none','na'} and len(s)>=5)

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--input',required=True);ap.add_argument('--out',required=True);a=ap.parse_args();root=Path(a.input);out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
 semantic=[];codeonly=[];source_counts={}
 for src in ('global_core','usa','australia'):
  hs=read(root/f'{src}_high_signal_clusters.csv'); ex=read(root/f'{src}_cluster_examples.csv'); em={}
  for e in ex:em.setdefault(ckey(e),[]).append(e)
  kept=0
  for r in hs:
   blob=' | '.join((r.get('country',''),r.get('currency',''),r.get('route_band',''),r.get('native_code',''),r.get('code_description',''),r.get('phrase_signature','')))
   if KNOWN.search(blob):continue
   item={'source':src,'triage':score(r),'cluster_key':dict(zip(KEYCOLS,ckey(r))),'records':fnum(r.get('records')),'buyers':fnum(r.get('buyers')),'repeat_buyers':fnum(r.get('repeat_buyers')),'suppliers':fnum(r.get('suppliers')),'top_supplier_share':fnum(r.get('top_supplier_share')),'median_value':fnum(r.get('median_value')),'median_bidders':fnum(r.get('median_bidders')),'code_description':r.get('code_description'),'phrase_signature':r.get('phrase_signature'),'heavy_flag':bool(HEAVY.search(blob)),'examples':[{'tender_id':e.get('tender_id'),'buyer':e.get('buyer_name'),'title':e.get('title'),'reference_value':e.get('reference_value'),'publication_date':e.get('publication_date')} for e in em.get(ckey(r),[])[:6]]}
   (semantic if meaningful(r.get('phrase_signature')) else codeonly).append(item);kept+=1
  source_counts[src]={'input_high_signal':len(hs),'after_known_lane_exclusion':kept}
 semantic.sort(key=lambda x:x['triage'],reverse=True);codeonly.sort(key=lambda x:x['triage'],reverse=True)
 semq=semantic[:3000];codeq=codeonly[:1500]
 for name,rows in [('semantic_review_queue.jsonl',semq),('code_only_review_queue.jsonl',codeq)]:
  with (out/name).open('w',encoding='utf-8') as f:
   for x in rows:f.write(json.dumps(x,ensure_ascii=False)+'\n')
 summary={'version':'HISTORICAL_OPEN_WORLD_UNKNOWNS_V2','source_counts':source_counts,'semantic_candidates':len(semantic),'code_only_candidates':len(codeonly),'semantic_review_queue':len(semq),'code_only_review_queue':len(codeq),'join_key':list(KEYCOLS),'v1_bug_fixed':'examples are joined on full cluster key, not phrase_signature alone','historical_only':True,'record_deletion':False}
 (out/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8')
 def packet(path,title,rows,limit):
  lines=[f'# {title}','', 'Historical-only review queue. No source record is deleted or rejected by inclusion/exclusion here.','']
  for i,x in enumerate(rows[:limit],1):
   k=x['cluster_key'];lines += [f"## {i}. {x['source']} · triage {x['triage']}",f"- {k['country']} / {k['currency']} · route={k['route_band']} · code={k['native_code']} · {x['code_description']}",f"- signature: {x['phrase_signature']}",f"- records={x['records']} buyers={x['buyers']} repeat={x['repeat_buyers']} suppliers={x['suppliers']} top_share={x['top_supplier_share']} median={x['median_value']} bidders={x['median_bidders']} heavy={x['heavy_flag']}"]
   for e in x['examples'][:5]:lines.append(f"- example: {e['buyer']} — {e['title']} — {e['reference_value']}")
   lines.append('')
  (out/path).write_text('\n'.join(lines),encoding='utf-8')
 packet('SEMANTIC_REVIEW_PACKET.md','Historical Open-World Unknowns v2 — Semantic Signatures',semq,500)
 packet('CODE_ONLY_REVIEW_PACKET.md','Historical Open-World Unknowns v2 — Code-only / weak signatures',codeq,300)
if __name__=='__main__':main()
