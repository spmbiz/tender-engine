from __future__ import annotations

import argparse
import json
import re
import unicodedata
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
    'november':11,'nov':11,'novembre':11,'noviembre':11,
    'december':12,'dec':12,'décembre':12,'decembre':12,'dezember':12,'diciembre':12,'dicembre':12,
    'stycznia':1,'styczen':1,'lutego':2,'luty':2,'marca':3,'marzec':3,'kwietnia':4,'kwiecien':4,
    'maja':5,'czerwca':6,'czerwiec':6,'lipca':7,'lipiec':7,'sierpnia':8,'sierpien':8,
    'września':9,'wrzesnia':9,'wrzesien':9,'października':10,'pazdziernika':10,'pazdziernik':10,
    'listopada':11,'listopad':11,'grudnia':12,'grudzien':12,
    'ledna':1,'leden':1,'února':2,'unora':2,'brezna':3,'března':3,'dubna':4,'kvetna':5,'května':5,
    'cervna':6,'června':6,'cervence':7,'července':7,'srpna':8,'zari':9,'září':9,'rijna':10,'října':10,
    'listopadu':11,'prosince':12,
}

# Broad retrieval vocabulary. This is only used to build a bounded corpus of
# deadline-ish contexts. Final authority is decided by the labelled patterns below.
DEADLINE_WORDS = re.compile(
    r"deadline|closing date|submission date|date limite|remise des offres|réception des offres|reception des offres|"
    r"angebotsfrist|einreichungsfrist|teilnahmefrist|uiterste datum|indiening|"
    r"termin sk[łl]adania ofert|termin z[łl]o[żz]enia ofert|sk[łl]adanie ofert|"
    r"plazo de presentaci[oó]n|fecha l[ií]mite|"
    r"termine (?:di )?presentazione|scadenza (?:per )?(?:la )?presentazione|"
    r"prazo para apresenta[cç][aã]o|data limite|"
    r"lh[uů]ta pro pod[aá]n[ií] nab[ií]dek|lhota na predkladanie pon[uú]k|"
    r"dáta deiridh|data deiridh|tilbudsfrist|frist for afgivelse|tarjousten j[aä]tt[oö]aika|"
    r"pied[aā]v[aā]jumu iesniegšanas termi[nņ]š|pasi[uū]lym[uų] pateikimo terminas|queries|additional information|clarifications",
    re.I,
)

# A date is authoritative for bid timing only when it is locally attached to a
# submission/participation phrase. Query/clarification dates are explicitly separate.
SUBMISSION_WORDS = re.compile(
    r"deadline for receipt of (?:tenders|offers|requests to participate|quotations)|"
    r"closing date for (?:tender )?submission|closing date for submissions|deadline for (?:tender )?submission|"
    r"deadline for receipt of quotations|deadline for receipt of bids|submission deadline|tender deadline|bid deadline|"
    r"(?:rfq|rfp|bid|tender|quotation|proposal)\s+closing date|"
    r"remise des offres|réception des offres|reception des offres|date limite de (?:remise|réception|reception) des offres|"
    r"angebotsfrist|einreichungsfrist|teilnahmefrist|frist (?:zur|für die|fuer die) (?:abgabe|einreichung)|"
    r"termin sk[łl]adania ofert|termin z[łl]o[żz]enia ofert|plazo de presentaci[oó]n|"
    r"termine (?:di )?presentazione|scadenza (?:per )?(?:la )?presentazione|"
    r"prazo para apresenta[cç][aã]o|lh[uů]ta pro pod[aá]n[ií] nab[ií]dek|lhota na predkladanie pon[uú]k|"
    r"tilbudsfrist|frist for afgivelse|tarjousten j[aä]tt[oö]aika|"
    r"pied[aā]v[aā]jumu iesniegšanas termi[nņ]š|pasi[uū]lym[uų] pateikimo terminas",
    re.I,
)
QUERY_WORDS = re.compile(
    r"deadline for requesting additional information|closing date for quer(?:y|ies)|deadline for quer(?:y|ies)|"
    r"clarification deadline|deadline for clarification|questions? due|queries due|"
    r"frist.*(?:fragen|b[ei]eterfragen)|fragen zum vergabeverfahren|date limite.*questions|"
    r"deadline.*additional information",
    re.I,
)

DATE_PATTERNS = [
    re.compile(r"\b(20\d{2})[-/.](0?[1-9]|1[0-2])[-/.](0?[1-9]|[12]\d|3[01])\b"),
    re.compile(r"\b(0?[1-9]|[12]\d|3[01])[./-](0?[1-9]|1[0-2])[./-](20\d{2})\b"),
    re.compile(r"\b(0?[1-9]|[12]\d|3[01])(?:st|nd|rd|th)?\s+([A-Za-zÀ-ž]+)\s+(20\d{2})\b", re.I),
    re.compile(r"\b([A-Za-zÀ-ž]+)\s+(0?[1-9]|[12]\d|3[01])(?:st|nd|rd|th)?,?\s+(20\d{2})\b", re.I),
]


def load(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding='utf-8', errors='replace'))
    except Exception:
        return {} if default is None else default


def parse_notice_date(value) -> str | None:
    if not value: return None
    s = str(value).strip().replace('Z', '+00:00')
    try: return datetime.fromisoformat(s).date().isoformat()
    except Exception:
        m = re.search(r"20\d{2}-\d{2}-\d{2}", s); return m.group(0) if m else None


def _fold(value: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFKD', value or '') if not unicodedata.combining(c)).lower().strip('.')


_NORMALIZED_MONTHS = {_fold(k): v for k, v in MONTHS.items()}


def _month(token: str) -> int | None: return _NORMALIZED_MONTHS.get(_fold(token))


def _valid_date(y: int, mo: int, d: int) -> str | None:
    try: return datetime(y, mo, d).date().isoformat()
    except Exception: return None


def extract_dates(text: str) -> list[dict]:
    """Extract dates with absolute spans so labels can bind to the nearest date."""
    rows=[]; seen=set()
    for pidx, pattern in enumerate(DATE_PATTERNS):
        for m in pattern.finditer(text):
            if pidx == 0:
                y,mo,d=map(int,m.groups())
            elif pidx == 1:
                d,mo,y=map(int,m.groups())
            elif pidx == 2:
                d=int(m.group(1)); mo=_month(m.group(2)); y=int(m.group(3))
                if not mo: continue
            else:
                mo=_month(m.group(1)); d=int(m.group(2)); y=int(m.group(3))
                if not mo: continue
            key=_valid_date(y,mo,d)
            # Keep duplicate dates at different positions: their semantic label can differ.
            uniq=(key,m.start(),m.end())
            if key and uniq not in seen:
                seen.add(uniq)
                rows.append({
                    'date':key,'match':m.group(0),'start':m.start(),'end':m.end(),
                    'context':text[max(0,m.start()-220):m.end()+220]
                })
    return sorted(rows,key=lambda r:r['start'])


def _contexts_around_deadline_words(text: str, before: int=650, after: int=1300, max_hits: int=80) -> list[str]:
    chunks=[]; seen=set()
    for m in DEADLINE_WORDS.finditer(text or ''):
        chunk=text[max(0,m.start()-before):min(len(text),m.end()+after)]; key=re.sub(r"\s+"," ",chunk[:300]).casefold()
        if key in seen: continue
        seen.add(key); chunks.append(chunk)
        if len(chunks)>=max_hits: break
    return chunks


def deadline_contexts(gates: dict, corpus: str) -> tuple[str,dict]:
    cats=gates.get('categories') or {}; hits=cats.get('submission') or cats.get('deadline_submission') or []; gate_chunks=[]
    for hit in hits:
        if isinstance(hit,dict): gate_chunks.extend(_contexts_around_deadline_words(str(hit.get('snippet') or ''),before=500,after=900,max_hits=20))
    corpus_chunks=_contexts_around_deadline_words(corpus,before=650,after=1300,max_hits=80); all_chunks=[]; seen=set()
    for chunk in gate_chunks+corpus_chunks:
        key=re.sub(r"\s+"," ",chunk[:400]).casefold()
        if key not in seen: seen.add(key); all_chunks.append(chunk)
    return '\n'.join(all_chunks),{'gate_contexts':len(gate_chunks),'corpus_contexts':len(corpus_chunks),'unique_contexts':len(all_chunks)}


def labelled_deadline_dates(text: str) -> list[dict]:
    # Procurement PDFs/HTML frequently use NBSP/narrow-NBSP between words.
    # Replace them one-for-one so regex labels match while every date/span offset
    # remains valid against the original text used for evidence context.
    scan_text=(text or '').replace('\u00a0',' ').replace('\u202f',' ')
    dates=extract_dates(scan_text)
    labelled=[]; seen=set()
    for label,rx in (('SUBMISSION',SUBMISSION_WORDS),('QUERY',QUERY_WORDS)):
        for kw in rx.finditer(scan_text):
            # Deadline values normally appear after the label. Permit a tiny prefix
            # for layouts where a table puts the date immediately before the label.
            candidates=[d for d in dates if d['start'] >= kw.start()-25 and d['start'] <= kw.end()+240]
            if not candidates: continue
            nearest=min(candidates,key=lambda d:(abs(d['start']-kw.end()),d['start']))
            if abs(nearest['start']-kw.end()) > 240: continue
            k=(label,nearest['date'],nearest['start'])
            if k in seen: continue
            seen.add(k)
            labelled.append({
                'date':nearest['date'],'match':nearest['match'],'label':label,
                'keyword':kw.group(0),'distance':nearest['start']-kw.end(),
                'context':scan_text[max(0,kw.start()-180):min(len(scan_text),nearest['end']+300)]
            })
    return labelled


def process(root: Path) -> dict:
    candidate=load(root/'candidate.json',{}); gates=load(root/'gate_snippets.json',{}); evidence=load(root/'evidence_quality.json',{}); corpus_path=root/'corpus.txt'; corpus=corpus_path.read_text(encoding='utf-8',errors='replace') if corpus_path.exists() else ''; notice_date=parse_notice_date(candidate.get('deadline'))
    context,stats=deadline_contexts(gates,corpus) if evidence.get('gate_readiness') else ('',{'gate_contexts':0,'corpus_contexts':0,'unique_contexts':0})
    found=extract_dates(context)
    labelled=labelled_deadline_dates(context)
    all_dates=sorted({x['date'] for x in found})
    submission_dates=sorted({x['date'] for x in labelled if x['label']=='SUBMISSION'})
    query_dates=sorted({x['date'] for x in labelled if x['label']=='QUERY'})
    resolved_submission_date=None

    if not evidence.get('gate_readiness'):
        status='NOT_APPLICABLE_DCE_NOT_GATE_READY'; conflict=False
    elif len(submission_dates)==1:
        resolved_submission_date=submission_dates[0]
        if notice_date == resolved_submission_date:
            status='CONSISTENT_AUTHORITATIVE_SUBMISSION_DATE'; conflict=False
        elif notice_date:
            # DCE is authoritative and explicitly labels this as the bid/participation deadline.
            # Treat a notice field that instead held a query date as resolved metadata mismatch,
            # not an unresolved eligibility conflict.
            status='DCE_AUTHORITATIVE_SUBMISSION_DATE_OVERRIDES_NOTICE_METADATA'; conflict=False
        else:
            status='DCE_AUTHORITATIVE_SUBMISSION_DATE_FOUND_NOTICE_MISSING'; conflict=False
    elif len(submission_dates)>1:
        status='DCE_MULTIPLE_SUBMISSION_DEADLINES_REVIEW_REQUIRED'; conflict=True
    elif notice_date and notice_date in query_dates:
        status='NOTICE_DATE_MATCHES_QUERY_DEADLINE_NOT_SUBMISSION_REVIEW_REQUIRED'; conflict=True
    elif not all_dates:
        status='UNKNOWN_NO_DCE_DEADLINE_PARSED'; conflict=False
    elif notice_date and notice_date in all_dates:
        status='NOTICE_DATE_FOUND_BUT_UNLABELLED_IN_DCE_REVIEW_REQUIRED'; conflict=True
    elif notice_date:
        status='UNLABELLED_DCE_DEADLINE_CONFLICT_REVIEW_REQUIRED'; conflict=True
    elif len(all_dates)==1:
        status='DCE_UNLABELLED_DATE_FOUND_NOTICE_MISSING_REVIEW_REQUIRED'; conflict=True
    else:
        status='DCE_MULTIPLE_UNLABELLED_DEADLINE_DATES_REVIEW_REQUIRED'; conflict=True

    result={
        'contract':'AUTHORITY_CONFLICTS_V3',
        'candidate_id':candidate.get('candidate_id') or root.name,
        'deadline':{
            'status':status,'conflict':conflict,
            'notice_deadline_raw':candidate.get('deadline'),'notice_deadline_date':notice_date,
            'authoritative_submission_date':resolved_submission_date,
            'submission_deadline_candidates':submission_dates,
            'query_deadline_candidates':query_dates,
            'dce_deadline_candidates':all_dates,
            'labelled_evidence':labelled[:30],
            'evidence':[{k:v for k,v in x.items() if k not in {'start','end'}} for x in found[:30]],
            'context_stats':stats,
            'rule':'Only dates locally attached to tender/bid/quotation submission or requests-to-participate language can automatically resolve bid timing. Query/clarification dates are never accepted as submission deadlines. Missing/ambiguous submission evidence remains review-required before FINAL_SUPER_GREEN.'
        }
    }
    (root/'authority_conflicts.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8'); return result


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--root',default='out')
    args=ap.parse_args()
    roots=sorted(set(p.parent for p in Path(args.root).rglob('manifest.json')))
    rows=[process(r) for r in roots]
    statuses=sorted({r['deadline']['status'] for r in rows})
    summary={
        'candidates':len(rows),
        'deadline_conflicts':sum(1 for r in rows if r['deadline']['conflict']),
        'authoritative_submission_dates':sum(1 for r in rows if r['deadline'].get('authoritative_submission_date')),
        'statuses':{s:sum(1 for r in rows if r['deadline']['status']==s) for s in statuses},
    }
    print(json.dumps(summary,indent=2,ensure_ascii=False))


if __name__=='__main__': main()
