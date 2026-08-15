#!/usr/bin/env python3
from __future__ import annotations

"""Apply audited Hunt Sub-Niches v2 Precision findings to historical retrieval priors.

Only retrieval priority changes. HOLD_* rules are audit records and are ignored
by the live loader. No DCE/eligibility gate is ever satisfied here.
"""
import argparse, json
from datetime import datetime, timezone
from pathlib import Path


def mk(lane,country,n,score,bonus,decision,patterns,negative=()):
    return {"lane":lane,"country":country,"sample_size":n,"historical_score":score,
            "priority_bonus":bonus,"decision":decision,"match_field":"title",
            "patterns":list(patterns),"negative_patterns":list(negative)}


def upsert(rules,new,aliases=()):
    names={new['lane'],*aliases}
    for i,r in enumerate(rules):
        if r.get('country','')==new.get('country','') and r.get('lane') in names:
            rules[i]=new; return
    rules.append(new)


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--priors',default='control/historical_market_priors.json'); ap.add_argument('--out',default='control/historical_market_priors.json'); a=ap.parse_args()
    data=json.loads(Path(a.priors).read_text(encoding='utf-8'))
    assert data.get('contract')=='TENDER_MARKET_BRAIN_PRIORS_V1' and data.get('status')=='READY'
    rules=list(data.get('lane_rules') or [])

    # Germany: strongest clean sub-niche after title-level QA, with observed
    # median 3.5 bidders and fragmented winner structure in the historical sample.
    upsert(rules,mk('Website support / accessibility / hosting','GERMANY',123,81.91,6,'PROMOTE_CORE',[
      r'(?:webseite|website|internetauftritt|webauftritt).{0,90}(?:pflege|wartung|betreuung|support|hosting|betrieb)',
      r'(?:pflege|wartung|betreuung|support|hosting|betrieb).{0,90}(?:webseite|website|internetauftritt|webauftritt)'],
      [r'hardware',r'security portal',r'portal crane']))

    # France web support: "construction du site internet" is legitimate web build
    # language, so generic construction is no longer a negative when paired with
    # explicit site/web + support/hosting/maintenance title evidence.
    upsert(rules,mk('Website support / accessibility / hosting','FRANCE',111,78.32,5,'PROMOTE_CORE',[
      r'(?:site web|site internet|website|portail web).{0,90}(?:maintenance|support|h[eé]bergement|entretien|mise [àa] jour)',
      r'(?:maintenance|support|h[eé]bergement|entretien|mise [àa] jour).{0,90}(?:site web|site internet|website|portail web)'],
      [r'hardware',r'mat[eé]riel informatique',r'security portal',r'x-ray']))

    # Written translation and human interpreting are now separate commercial
    # motions. Only written translation receives a live historical boost.
    upsert(rules,mk('Written translation','FRANCE',63,78.25,5,'PROMOTE_CORE',[
      r'\btraduction\b',r'traduction de textes?',r'traduction de documents?',r'translation services?'],
      [r'interpr[eé]tariat',r'interpr[eé]tation',r'mat[eé]riel',r'[eé]quipement',r'audiovisuel',r'location',r'translationnelle',r'translational',r'm[eé]decine']),aliases=('Translation','Translation services'))
    upsert(rules,mk('Human interpreting','FRANCE',150,81.27,0,'HOLD_STAFFING_MODEL',[
      r'interpr[eé]tariat',r'interpr[eé]tation.{0,60}(?:langue|linguistique|simultan|conf[eé]rence|traduct)'],
      [r'logiciel d.?interpr[eé]tation',r'centre d.?interpr[eé]tation',r'sentier d.?interpr[eé]tation',r'signal[eé]tique.{0,30}interpr[eé]tation',r'mobilier d.?interpr[eé]tation',r'barrage',r'auscultation',r'mat[eé]riel',r'[eé]quipement']))

    # Pure transcription remains AI+human-QA friendly. Stenotypy is held because
    # a named/specialist human delivery model may be mandatory.
    upsert(rules,mk('Transcription / speech-to-text','FRANCE',45,76.21,4,'PROMOTE_CORE',[
      r'\btranscription\b',r'\bretranscription\b',r'speech[- ]to[- ]text'],
      [r'st[eé]notyp',r'st[eé]nograph',r'dna transcription',r'gene transcription',r'g[eè]ne',r'transcription factor']))
    upsert(rules,mk('Stenotypy / stenography','FRANCE',31,71.93,0,'HOLD_STAFFING_MODEL',[
      r'st[eé]notyp',r'st[eé]nograph'],[]))

    # Canada: written translation is boosted modestly; interpretation/sign
    # language remains a separate staffing-dependent motion.
    upsert(rules,mk('Written translation','CANADA',37,77.02,3,'PROMOTE_CORE',[
      r'translation services?',r'professional translation',r'technical translation',r'english to french',r'french to english'],
      [r'interpretation',r'interpreting',r'simultaneous',r'sign language',r'\basl\b',r'\blsq\b',r'equipment',r'hardware',r'translational']),aliases=('Translation','Translation services'))
    upsert(rules,mk('Interpretation / sign-language services','CANADA',34,74.64,0,'HOLD_STAFFING_MODEL',[
      r'interpretation services?',r'interpreting',r'simultaneous interpretation',r'sign language',r'\basl\b',r'\blsq\b'],
      [r'equipment',r'hardware',r'audiovisual equipment']))

    data['lane_rules']=rules
    data['generated_at']=datetime.now(timezone.utc).isoformat()
    data['source_release']='walidgdg1-ai/tender-engine:market-intelligence-v9-final-qa + market-intelligence-micro-niche-v2-precision + market-intelligence-hunt-subniches-v2-precision'
    data['source_scope']='Global Core v4 notice-first. Route-aware and title-led historical priors; staffing-dependent language services are explicitly held from live promotion.'
    data['hunt_subniche_v2_precision']={
      'authority':'control/spm_hunt_subniches_v2_precision/REPORT.md',
      'source_release':'market-intelligence-hunt-subniches-v2-precision',
      'classified_notice_first_tenders':3780,'sub_niches':31,
      'strengthened':['Germany website maintenance/support'],
      'refined':['France website support','France written translation','France pure transcription','Canada written translation'],
      'held':['France human interpreting','France stenotypy/stenography','Canada interpretation/sign-language'],
      'rule':'HOLD_* is audit-only and ignored by the live loader; only PROMOTE_CORE/PROMOTE_BROKER affects retrieval priority.'}
    Path(a.out).write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')

if __name__=='__main__': main()
