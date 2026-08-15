#!/usr/bin/env python3
from __future__ import annotations

"""Fast exhaustive SPM live review routing.

Same preservation contract as build_live_spm_review_pool.py, but historical lane
regexes are compiled once. Every live row survives in HIT or RESIDUAL.
"""
import argparse,gzip,json,math,re
from collections import Counter
from pathlib import Path
from typing import Any

SOURCE_COUNTRY={
"US_SAM":"USA","FR":"FRANCE","DE":"GERMANY","CA":"CANADA","QC":"CANADA - QUEBEC","UK":"UNITED KINGDOM","IE":"IRELAND","AU":"AUSTRALIA","NZ":"NEW ZEALAND","NL":"NETHERLANDS","PL":"POLAND","DK":"DENMARK","FI":"FINLAND","ES_PLACSP":"SPAIN","GR_KHMDHS":"GREECE","PT_BASE_OPEN":"PORTUGAL","CZ_ZAKAZKY_GOV":"CZECHIA","CH_SIMAP":"SWITZERLAND","NO_DOFFIN":"NORWAY","LV_IUB":"LATVIA","LU":"LUXEMBOURG","BE":"BELGIUM","CY":"CYPRUS","MT":"MALTA"}
ALIASES={
"FRANCE":{"FRA","FR","FRANCE"},"GERMANY":{"DEU","DE","GERMANY"},"UNITED KINGDOM":{"GBR","GB","UK","UNITED KINGDOM"},"IRELAND":{"IRL","IE","IRELAND"},"CANADA":{"CAN","CA","CANADA"},"CANADA - QUEBEC":{"CANADA - QUEBEC","QUEBEC","QC"},"USA":{"USA","US","UNITED STATES","UNITED STATES OF AMERICA"},"AUSTRALIA":{"AUS","AU","AUSTRALIA"},"NEW ZEALAND":{"NZL","NZ","NEW ZEALAND"},"LUXEMBOURG":{"LUX","LU","LUXEMBOURG"}}
LEAN_PATTERNS={
"web_cms":r"website|web site|site web|site internet|webseite|internetauftritt|wordpress|drupal|\bcms\b|web portal|portail web|webportal",
"design_dtp":r"graphic design|design graphique|conception graphique|graphisme|mise en page|desktop publishing|\bdtp\b|visual identity|identit[eé] visuelle|infograph",
"print_broker":r"printing services?|prestations? d['’]impression|services? d['’]impression|travaux d['’]impression|imprimerie|print production|brochure|magazine printing|routage|mailing|mise sous pli",
"promo_goods":r"promotional merchandise|branded merchandise|promotional items|objets publicitaires|articles promotionnels|goodies|corporate gifts",
"translation":r"translation services?|professional translation|technical translation|traduction de textes|prestations? de traduction|services? de traduction|linguistic services?",
"transcription":r"transcription services?|retranscription|speech[- ]to[- ]text|meeting transcription|debate transcription|st[eé]notyp",
"digitization":r"document digitization|document digitisation|num[eé]risation de documents|digitalisation de documents|document scanning|\bocr\b|archive digitization|archive digitisation",
"video_media":r"video production|film production|production vid[eé]o|motion graphics|animation video|audiovisual production|podcast production|content production",
"social_marketing":r"social media management|community management|gestion des r[eé]seaux sociaux|digital marketing|seo services?|search engine optimization|content marketing",
"research_surveys":r"market research|customer survey|satisfaction survey|opinion poll|research panel|user research",
"media_monitoring":r"media monitoring|press monitoring|social listening|revue de presse|veille m[eé]diatique",
"software_resale":r"software licen[cs](?:e|es|ing)|software subscription|saas subscription|licences? logicielles?|license renewal|licence renewal",
"automation_data":r"robotic process automation|\brpa\b|workflow automation|process automation|data entry|data processing|document processing|low[- ]code|no[- ]code|chatbot|artificial intelligence|\bai\b services?",
"accessibility":r"web accessibility|digital accessibility|accessibilit[eé] num[eé]rique|\bwcag\b|\brgaa\b|pdf[- ]ua",
"hosting_support":r"web hosting|website maintenance|web maintenance|hosting and support|h[eé]bergement.*site|maintenance.*site (?:web|internet)|pflege.*webseite|wartung.*webseite"}
LEAN_RX={k:re.compile(v,re.I) for k,v in LEAN_PATTERNS.items()}
BLOCKER_PATTERNS={
"SOLE_SOURCE_OR_OEM":r"sole source|only one responsible source|source approval request|approved source|original equipment manufacturer|\boem\b|single source",
"MANDATORY_ONSITE_OR_FIELD":r"must be performed on[- ]site|required on[- ]site|work will be performed on[- ]site|mandatory site visit|présence sur site obligatoire|intervention sur site|vor ort",
"REGULATED_OR_CERTIFIED_STAFF":r"mandatory qualifications|must be certified|required certification|licensed professional|professional license|security clearance|habilitat|certifi[eé].{0,50}obligatoire",
"SET_ASIDE_OR_LOCAL_RESTRICTION":r"small business set[- ]aside|8\(a\)|hubzone|service[- ]disabled veteran|woman[- ]owned small business|local suppliers? only|domestic suppliers? only",
"SOURCES_SOUGHT_OR_RFI":r"sources sought|request for information|\brfi\b|market research purposes|information and planning purposes|not a request for (?:proposal|quotation|bid)",
"CONSTRUCTION_HEAVY":r"construction works?|civil works?|general contractor|architectural and engineering|road works?|building works?|ma[iî]trise d['’]oeuvre|travaux de construction",
"MEDICAL_CLINICAL":r"clinical services?|medical services?|patient care|physician|nursing services?|hospital staffing|medical simulator operator"}
BLOCKER_RX={k:re.compile(v,re.I|re.S) for k,v in BLOCKER_PATTERNS.items()}

def infer_country(r):
    c=str(r.get('country') or '').strip().upper()
    return c if c and c!='UNKNOWN' else SOURCE_COUNTRY.get(str(r.get('source_family') or '').upper(),'')

def country_match(rule_country,country):
    if not rule_country:return True
    if not country:return False
    return country in ALIASES.get(rule_country,{rule_country})

def compile_priors(path:Path):
    try:d=json.loads(path.read_text(encoding='utf-8'))
    except Exception:return []
    out=[]
    for rule in d.get('lane_rules') or []:
        if not isinstance(rule,dict):continue
        if str(rule.get('decision') or '').upper() not in {'PROMOTE_CORE','PROMOTE_BROKER'}:continue
        if int(rule.get('sample_size') or 0)<8:continue
        try:pos=[re.compile(str(x),re.I) for x in rule.get('patterns') or []]; neg=[re.compile(str(x),re.I) for x in rule.get('negative_patterns') or []]
        except re.error:continue
        if not pos:continue
        out.append({'lane':str(rule.get('lane') or 'UNKNOWN'),'country':str(rule.get('country') or '').strip().upper(),'sample':int(rule.get('sample_size') or 0),'bonus':max(-6,min(6,int(round(float(rule.get('priority_bonus') or 0))))),'field':str(rule.get('match_field') or 'all').lower(),'pos':pos,'neg':neg})
    return out

def historical(r,rules,country,all_text,title):
    best=0;reason=''
    for q in rules:
        if not country_match(q['country'],country):continue
        hay=title if q['field']=='title' else all_text
        if not any(rx.search(hay) for rx in q['pos']):continue
        if any(rx.search(hay) for rx in q['neg']):continue
        if abs(q['bonus'])>abs(best):best=q['bonus'];reason=f"{q['bonus']:+d}:historical-lane:{q['lane']}(n={q['sample']})"
    return best,[reason] if reason else []

def analyze(rec,rules):
    r=dict(rec); country=infer_country(r); title=str(r.get('title') or '')[:3000]; desc=str(r.get('description') or '')[:6000]
    all_text=' '.join((title,desc,str(r.get('cpv_or_category') or '')[:1000],str(r.get('notice_eligibility') or '')[:1500],str(r.get('procedure') or '')[:500]))
    hdelta,hreasons=historical(r,rules,country,all_text,title)
    lean=[k for k,rx in LEAN_RX.items() if rx.search(all_text)]; blockers=[k for k,rx in BLOCKER_RX.items() if rx.search(all_text)]
    p=20+max(0,hdelta)*5+min(24,8*len(lean))+(6 if r.get('open_state')=='OPEN_CONFIRMED_BY_DEADLINE' else 0)+(4 if len(desc)>250 else 0)+(2 if r.get('notice_eligibility') else 0)+(2 if r.get('estimated_value') not in (None,'') else 0)-min(35,9*len(blockers));p=max(0,min(89,p))
    r.update({'resolved_country':country or None,'review_bucket':'PLAYBOOK_OR_LEAN_HIT' if hdelta>0 or lean else 'RESIDUAL_OPEN_WORLD','review_priority':round(p,2),'historical_priority_adjustment':hdelta,'historical_prior_reasons':hreasons,'lean_ontology_hits':lean,'pre_dce_blocker_flags':blockers,'review_rule':'Ordering heuristic only. GPT semantic review + authoritative DCE decide business fit; residuals are preserved.'})
    return r

def write(path,rows):
    with path.open('w',encoding='utf-8') as f:
        for r in rows:f.write(json.dumps(r,ensure_ascii=False,separators=(',',':'))+'\n')

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--snapshot',required=True);ap.add_argument('--priors',required=True);ap.add_argument('--manifest',required=True);ap.add_argument('--coverage',required=True);ap.add_argument('--out',required=True);ap.add_argument('--packet-size',type=int,default=400);a=ap.parse_args()
    out=Path(a.out);out.mkdir(parents=True,exist_ok=True);(out/'residual-packets').mkdir(exist_ok=True);rules=compile_priors(Path(a.priors))
    rows=[]
    with gzip.open(a.snapshot,'rt',encoding='utf-8',errors='replace') as f:
        for line in f:
            if line.strip():
                x=json.loads(line)
                if isinstance(x,dict):rows.append(analyze(x,rules))
    hits=[r for r in rows if r['review_bucket']=='PLAYBOOK_OR_LEAN_HIT'];res=[r for r in rows if r['review_bucket']=='RESIDUAL_OPEN_WORLD']
    hits.sort(key=lambda r:(-r['review_priority'],r.get('deadline_utc') or '9999',r.get('candidate_id') or ''));res.sort(key=lambda r:(r.get('deadline_utc') or '9999',r.get('source_family') or '',r.get('candidate_id') or ''))
    write(out/'playbook_lean_hits.jsonl',hits);write(out/'top_review_1000.jsonl',hits[:1000]);pack=[];n=max(1,a.packet_size)
    for i in range(0,len(res),n):name=f"residual-{i//n:04d}.jsonl";pack.append(name);write(out/'residual-packets'/name,res[i:i+n])
    cov=json.load(open(a.coverage,encoding='utf-8'));m=json.load(open(a.manifest,encoding='utf-8'))
    s={'contract':'LIVE_SPM_REVIEW_POOL_V1','source_discovery_run':m.get('source_discovery_run'),'snapshot_rows':len(rows),'playbook_or_lean_hits':len(hits),'residual_open_world':len(res),'coverage_status':cov.get('coverage_status') or m.get('discovery_coverage_status'),'missing_packs':cov.get('missing_packs') or [],'degraded_packs':cov.get('degraded_packs') or [],'external_missing_lanes':cov.get('external_missing_lanes') or [],'hit_ontology_counts':dict(Counter(x for r in hits for x in r['lean_ontology_hits'])),'hit_source_counts':dict(Counter(str(r.get('source_family') or 'UNKNOWN') for r in hits).most_common()),'blocker_flag_counts':dict(Counter(x for r in rows for x in r['pre_dce_blocker_flags'])),'residual_packet_count':len(pack),'residual_packet_size':n,'residual_packet_files':pack,'compiled_historical_rules':len(rules),'preservation_rule':'Every snapshot row is represented in hit or residual output. Residuals are not discarded.','final_verdict_allowed':False}
    assert len(hits)+len(res)==len(rows);(out/'summary.json').write_text(json.dumps(s,indent=2,ensure_ascii=False)+'\n',encoding='utf-8');print(json.dumps(s,indent=2,ensure_ascii=False))
if __name__=='__main__':main()
