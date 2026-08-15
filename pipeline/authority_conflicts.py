from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

MONTHS = {
    'january':1,'jan':1,'janvier':1,'januar':1,'enero':1,'gennaio':1,'januari':1,
    'february':2,'feb':2,'février':2,'fevrier':2,'februar':2,'febrero':2,'febbraio':2,'februari':2,
    'march':3,'mar':3,'mars':3,'märz':3,'maerz':3,'marzo':3,'maart':3,
    'april':4,'apr':4,'avril':4,'abril':4,'aprile':4,
    'may':5,'mai':5,'mayo':5,'maggio':5,'mei':5,
    'june':6,'jun':6,'juin':6,'juni':6,'junio':6,'giugno':6,
    'july':7,'jul':7,'juillet':7,'juli':7,'julio':7,'luglio':7,
    'august':8,'aug':8,'août':8,'aout':8,'agosto':8,'augustus':8,
    'september':9,'sep':9,'sept':9,'septembre':9,'septiembre':9,'settembre':9,
    'october':10,'oct':10,'octobre':10,'oktober':10,'octubre':10,'ottobre':10,
    'november':11,'nov':11,'novembre':11,'noviembre':11,'novembre_it':11,
    'december':12,'dec':12,'décembre':12,'decembre':12,'dezember':12,'diciembre':12,'dicembre':12,
}

DEADLINE_WORDS = re.compile(
    r"deadline|closing date|submission date|date limite|remise des offres|réception des offres|reception des offres|"
    r"angebotsfrist|einreichungsfrist|uiterste datum|indiening|termin sk[łl]adania ofert|plazo de presentaci[oó]n|"
    r"termine (?:di )?presentazione|prazo para apresenta[cç][aã]o|dáta deiridh|data deiridh",
    re.I,
)

DATE_PATTERNS = [
    re.compile(r"\b(20\d{2})[-/](0?[1-9]|1[0-2])[-/](0?[1-9]|[12]\d|3[01])\b"),
    re.compile(r"\b(0?[1-9]|[12]\d|3[01])[./-](0?[1-9]|1[0-2])[./-](20\d{2})\b"),
    re.compile(r"\b(0?[1-9]|[12]\d|3[01])(?:st|nd|rd|th)?\s+([A-Za-zÀ-ÿ]+)\s+(20\d{2})\b", re.I),
    re.compile(r"\b([A-Za-zÀ-ÿ]+)\s+(0?[1-9]|[12]\d|3[01])(?:st|nd|rd|th)?,?\s+(20\d{2})\b", re.I),
]


def load(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding='utf-8', errors='replace'))
    except Exception:
        return {} if default is None else default


def parse_notice_date(value) -> str | None:
    if not value:
        return None
    s=str(value).strip().replace('Z','+00:00')
    try:
        return datetime.fromisoformat(s).date().isoformat()
    except Exception:
        m=re.search(r"20\d{2}-\d{2}-\d{2}",s)
        return m.group(0) if m else None


def _month(token: str) -> int | None:
    t=token.lower().strip('.').replace('é','e').replace('û','u').replace('ä','a')
    normalized={k.replace('é','e').replace('û','u').replace('ä','a'):v for k,v in MONTHS.items()}
    return normalized.get(t)


def extract_dates(text: str) -> list[dict]:
    rows=[]; seen=set()
    for m in DATE_PATTERNS[0].finditer(text):
        y,mo,d=map(int,m.groups()); key=f'{y:04d}-{mo:02d}-{d:02d}'
        if key not in seen: seen.add(key); rows.append({'date':key,'match':m.group(0),'context':text[max(0,m.start()-180):m.end()+180]})
    for m in DATE_PATTERNS[1].finditer(text):
        d,mo,y=map(int,m.groups()); key=f'{y:04d}-{mo:02d}-{d:02d}'
        if key not in seen: seen.add(key); rows.append({'date':key,'match':m.group(0),'context':text[max(0,m.start()-180):m.end()+180]})
    for idx in (2,3):
        for m in DATE_PATTERNS[idx].finditer(text):
            if idx==2: d=int(m.group(1)); mo=_month(m.group(2)); y=int(m.group(3))
            else: mo=_month(m.group(1)); d=int(m.group(2)); y=int(m.group(3))
            if not mo: continue
            key=f'{y:04d}-{mo:02d}-{d:02d}'
            if key not in seen: seen.add(key); rows.append({'date':key,'match':m.group(0),'context':text[max(0,m.start()-180):m.end()+180]})
    return rows


def deadline_contexts(gates: dict) -> str:
    cats=gates.get('categories') or {}
    hits=cats.get('submission') or cats.get('deadline_submission') or []
    chunks=[]
    for hit in hits:
        if not isinstance(hit,dict): continue
        s=str(hit.get('snippet') or '')
        for m in DEADLINE_WORDS.finditer(s):
            chunks.append(s[max(0,m.start()-500):m.end()+900])
    return '\n'.join(chunks)


def process(root: Path) -> dict:
    candidate=load(root/'candidate.json',{})
    gates=load(root/'gate_snippets.json',{})
    evidence=load(root/'evidence_quality.json',{})
    notice_date=parse_notice_date(candidate.get('deadline'))
    context=deadline_contexts(gates) if evidence.get('gate_readiness') else ''
    found=extract_dates(context)
    dce_dates=sorted({x['date'] for x in found})
    if not evidence.get('gate_readiness'):
        status='NOT_APPLICABLE_DCE_NOT_GATE_READY'; conflict=False
    elif not dce_dates:
        status='UNKNOWN_NO_DCE_DEADLINE_PARSED'; conflict=False
    elif notice_date and notice_date in dce_dates:
        status='CONSISTENT_NOTICE_DATE_FOUND_IN_DCE'; conflict=False
    elif notice_date:
        status='DEADLINE_CONFLICT_REVIEW_REQUIRED'; conflict=True
    else:
        status='DCE_DEADLINE_FOUND_NOTICE_DEADLINE_MISSING'; conflict=False
    result={
        'contract':'AUTHORITY_CONFLICTS_V1',
        'candidate_id':candidate.get('candidate_id') or root.name,
        'deadline':{
            'status':status,
            'conflict':conflict,
            'notice_deadline_raw':candidate.get('deadline'),
            'notice_deadline_date':notice_date,
            'dce_deadline_candidates':dce_dates,
            'evidence':found[:20],
            'rule':'Never silently overwrite deadline metadata. A parsed conflict requires explicit authoritative reconciliation before final 90+/FINAL_SUPER_GREEN.'
        }
    }
    (root/'authority_conflicts.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
    return result


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--root',default='out'); args=ap.parse_args()
    base=Path(args.root); roots=sorted(set(p.parent for p in base.rglob('manifest.json')))
    rows=[process(r) for r in roots]
    print(json.dumps({'candidates':len(rows),'deadline_conflicts':sum(1 for r in rows if r['deadline']['conflict']),'statuses':{s:sum(1 for r in rows if r['deadline']['status']==s) for s in sorted({r['deadline']['status'] for r in rows})}},indent=2,ensure_ascii=False))

if __name__=='__main__': main()
