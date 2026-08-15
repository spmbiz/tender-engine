#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,re,csv
from pathlib import Path

# Discovery mechanisms only. These are intentionally broader than current Atlas lanes.
PATTERNS={
 'COMPLIANCE_POLICY_REPORTING':r'\b(compliance|regulatory reporting|policy review|policy analysis|governance review|compliance monitoring|compliance support)\b',
 'RECORDS_CASE_ADMINISTRATION':r'\b(records management|case management services|file management|filing services|document management|archive management|registry services|records administration)\b',
 'CLAIMS_APPLICATION_PROCESSING':r'\b(claims processing|claims administration|application processing|application assessment|eligibility assessment|benefit processing|case processing)\b',
 'GRANTS_PROGRAM_ADMINISTRATION':r'\b(grant administration|grants administration|grant management|program administration|programme administration|fund administration)\b',
 'PROCUREMENT_CONTRACT_ADMIN_SUPPORT':r'\b(procurement support|contract administration|contract management support|tender support|acquisition support|purchasing support|sourcing support)\b',
 'DATABASE_DIRECTORY_MAINTENANCE':r'\b(database maintenance|database updating|directory maintenance|directory services|registry maintenance|register maintenance|data maintenance|database population)\b',
 'SECRETARIAT_MINUTES_MEETING_ADMIN':r'\b(secretariat services|committee secretariat|board secretariat|minute taking|minutes taking|meeting minutes|meeting administration)\b',
 'CAPTIONING_ACCESSIBILITY_SUPPORT':r'\b(captioning|closed caption|live caption|accessibility support|accessible document|document accessibility|wcag remediation|alternate format)\b',
 'TECHNICAL_DOCUMENTATION_MANUALS':r'\b(technical documentation|technical writing|manual development|procedure writing|standard operating procedure|sop development|user manual|documentation services)\b',
 'RESEARCH_MONITORING_INTELLIGENCE':r'\b(media monitoring|monitoring service|research monitoring|market intelligence|competitive intelligence|horizon scanning|environmental scan|evidence scan)\b',
 'SUBSCRIPTION_DATA_INFORMATION_RESELL':r'\b(subscription service|database subscription|information subscription|data subscription|research subscription|news subscription|market data|information service subscription)\b',
 'PAYROLL_BENEFITS_ADMIN':r'\b(payroll services|payroll administration|benefits administration|employee benefits administration|salary packaging|pension administration)\b',
 'COLLECTIONS_RECEIVABLES_RECOVERY':r'\b(debt collection|collection agency|collections services|receivables recovery|recovery services|accounts receivable collection)\b',
 'SURVEY_PANEL_FIELDWORK':r'\b(survey services|survey research|polling services|questionnaire services|panel research|research panel|fieldwork services|respondent recruitment)\b',
 'CONTACT_CALL_HELPDESK_BPO':r'\b(call centre|call center|contact centre|contact center|help desk|service desk|customer support|customer service centre|telephone support)\b',
 'CONTENT_MODERATION_CLASSIFICATION':r'\b(content moderation|content classification|taxonomy services|categorisation services|categorization services|tagging services|content tagging)\b',
 'ASSET_INVENTORY_DATA_CAPTURE':r'\b(asset inventory|asset register|inventory data|stocktaking services|inventory services|asset tagging|asset data collection)\b',
 'CREDENTIAL_SCREENING_VERIFICATION':r'\b(background check|background screening|credential verification|identity verification|pre-employment screening|reference checking|verification services)\b',
 'BOOKKEEPING_TRANSACTION_PROCESSING':r'\b(bookkeeping|accounts payable processing|accounts receivable processing|invoice processing|transaction processing|financial administration services)\b',
 'FOIA_DISCLOSURE_REDACTION':r'\b(freedom of information|foia|disclosure processing|access to information|redaction services|document redaction|privacy review)\b',
 'LOCAL_VENDOR_COORDINATION':r'\b(vendor management|supplier management|service coordination|facilities coordination|subcontractor management|vendor coordination)\b',
 'RENTAL_EQUIPMENT_BROKERAGE':r'\b(equipment rental|equipment hire|vehicle rental|rental services|lease services|leasing services)\b',
 'PROMO_EVENT_KIT_FULFILMENT':r'\b(event kits|conference materials|delegate packs|promotional packs|welcome packs|event materials|conference supplies)\b',
 'PHOTO_VIDEO_DIGITIZATION_MEDIA':r'\b(photo digitization|photo scanning|video digitization|film digitization|audio digitization|media digitization|archive media conversion)\b',
}
RX={k:re.compile(v,re.I) for k,v in PATTERNS.items()}


def read_jsonl(path):
    return [json.loads(x) for x in Path(path).read_text(encoding='utf-8').splitlines() if x.strip()]


def blob(r):
    k=r.get('cluster_key') or {}
    ex=r.get('examples') or []
    titles=' '.join((e.get('title') or '') for e in ex)
    return ' '.join([str(r.get('phrase_signature') or ''),str(r.get('code_description') or ''),str(k.get('native_code') or ''),titles])


def metrics(r):
    return {x:r.get(x) for x in ('records','buyers','repeat_buyers','suppliers','top_supplier_share','median_value','median_bidders')}


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--semantic',required=True); ap.add_argument('--code-only',required=True); ap.add_argument('--out',required=True); ap.add_argument('--semantic-start',type=int,default=1000); ap.add_argument('--semantic-end',type=int,default=3000); a=ap.parse_args()
    out=Path(a.out); out.mkdir(parents=True,exist_ok=True)
    sem=read_jsonl(a.semantic); code=read_jsonl(a.code_only)
    rows=[('SEMANTIC_NEXT_WAVE',r) for r in sem[a.semantic_start:a.semantic_end]] + [('CODE_ONLY_FULL',r) for r in code]
    tagged=[]; untagged=[]
    for queue,r in rows:
        text=blob(r)
        hits=[name for name,rx in RX.items() if rx.search(text)]
        if hits:
            for h in hits: tagged.append((h,queue,r,text))
        else: untagged.append((queue,r,text))

    stats={}
    for h,q,r,text in tagged:
        s=stats.setdefault(h,{'cluster_pairs':0,'records_sum':0.0,'buyers_sum':0.0,'repeat_buyers_sum':0.0,'suppliers_sum':0.0,'sources':{},'examples':[]})
        s['cluster_pairs']+=1
        for fld,key in [('records','records_sum'),('buyers','buyers_sum'),('repeat_buyers','repeat_buyers_sum'),('suppliers','suppliers_sum')]: s[key]+=float(r.get(fld) or 0)
        src=r.get('source') or 'UNKNOWN'; s['sources'][src]=s['sources'].get(src,0)+1
        if len(s['examples'])<20:
            s['examples'].append({'queue':q,'source':src,'triage':r.get('triage'),'cluster_key':r.get('cluster_key'),'phrase_signature':r.get('phrase_signature'),'code_description':r.get('code_description'),'metrics':metrics(r),'examples':(r.get('examples') or [])[:3]})
    ordered=sorted(stats.items(),key=lambda kv:(kv[1]['cluster_pairs'],kv[1]['records_sum']),reverse=True)

    summary={'version':'HISTORICAL_OPEN_WORLD_NEXT_WAVE_V3','semantic_total_available':len(sem),'semantic_slice':[a.semantic_start,a.semantic_end],'code_only_total_available':len(code),'clusters_reviewed':len(rows),'tagged_cluster_mechanism_pairs':len(tagged),'untagged_clusters':len(untagged),'mechanisms':{k:{x:v for x,v in s.items() if x!='examples'} for k,s in ordered},'historical_only':True,'record_deletion':False,'verdict_role':'DISCOVERY_NOT_PROMOTION'}
    (out/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8')

    with (out/'tagged_clusters.csv').open('w',encoding='utf-8',newline='') as f:
        w=csv.writer(f); w.writerow(['mechanism','queue','source','triage','records','buyers','repeat_buyers','suppliers','top_supplier_share','median_value','median_bidders','phrase_signature','code_description','example_titles'])
        for h,q,r,text in sorted(tagged,key=lambda z:(z[0],-(z[2].get('triage') or 0))):
            ex=' || '.join((e.get('title') or '') for e in (r.get('examples') or [])[:4])
            w.writerow([h,q,r.get('source'),r.get('triage'),r.get('records'),r.get('buyers'),r.get('repeat_buyers'),r.get('suppliers'),r.get('top_supplier_share'),r.get('median_value'),r.get('median_bidders'),r.get('phrase_signature'),r.get('code_description'),ex])

    with (out/'untagged_top.jsonl').open('w',encoding='utf-8') as f:
        for q,r,text in sorted(untagged,key=lambda z:z[1].get('triage') or 0,reverse=True)[:1000]: f.write(json.dumps({'queue':q,**r},ensure_ascii=False)+'\n')

    lines=['# Historical Open-World Next Wave v3','',f'- clusters reviewed **{len(rows):,}**',f'- tagged cluster×mechanism pairs **{len(tagged):,}**',f'- still untagged **{len(untagged):,}**','', 'This is ontology-independent discovery after the first 1,000 semantic clusters. Tags are hypotheses only; underlying records are preserved.','']
    for h,s in ordered:
        lines += [f'## {h}',f"- cluster pairs **{s['cluster_pairs']}** · summed records **{int(s['records_sum']):,}** · buyers-observations **{int(s['buyers_sum']):,}** · repeat-buyer observations **{int(s['repeat_buyers_sum']):,}** · supplier observations **{int(s['suppliers_sum']):,}**"]
        for e in s['examples'][:8]:
            titles=' | '.join((x.get('title') or '') for x in e['examples'])
            lines.append(f"- {e['source']} · triage {e['triage']} · {e['phrase_signature']} · {e['code_description']} :: {titles}")
        lines.append('')
    (out/'REPORT.md').write_text('\n'.join(lines),encoding='utf-8')

if __name__=='__main__': main()
