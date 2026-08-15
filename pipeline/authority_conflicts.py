from __future__ import annotations

import argparse
import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path

MONTHS = {
    # EN / FR / DE / ES / IT / NL
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
    # PL
    'stycznia':1,'styczen':1,'lutego':2,'luty':2,'marca':3,'marzec':3,'kwietnia':4,'kwiecien':4,
    'maja':5,'czerwca':6,'czerwiec':6,'lipca':7,'lipiec':7,'sierpnia':8,'sierpien':8,
    'września':9,'wrzesnia':9,'wrzesien':9,'października':10,'pazdziernika':10,'pazdziernik':10,
    'listopada':11,'listopad':11,'grudnia':12,'grudzien':12,
    # CZ / SK common inflected month forms
    'ledna':1,'leden':1,'února':2,'unora':2,'brezna':3,'března':3,'dubna':4,'kvetna':5,'května':5,
    'cervna':6,'června':6,'cervence':7,'července':7,'srpna':8,'zari':9,'září':9,'rijna':10,'října':10,
    'listopadu':11,'prosince':12,
}

DEADLINE_WORDS = re.compile(
    r"deadline|closing date|submission date|date limite|remise des offres|réception des offres|reception des offres|"
    r"angebotsfrist|einreichungsfrist|uiterste datum|indiening|"
    r"termin sk[łl]adania ofert|termin z[łl]o[żz]enia ofert|sk[łl]adanie ofert|"
    r"plazo de presentaci[oó]n|fecha l[ií]mite|"
    r"termine (?:di )?presentazione|scadenza (?:per )?(?:la )?presentazione|"
    r"prazo para apresenta[cç][aã]o|data limite|"
    r"lh[uů]ta pro pod[aá]n[ií] nab[ií]dek|lhota na predkladanie pon[uú]k|"
    r"dáta deiridh|data deiridh|"
    r"tilbudsfrist|frist for afgivelse|tarjousten j[aä]tt[oö]aika|"
    r"pied[aā]v[aā]jumu iesniegšanas termi[nņ]š|pasi[uū]lym[uų] pateikimo terminas",
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
    if not value:
        return None
    s = str(value).strip().replace('Z', '+00:00')
    try:
        return datetime.fromisoformat(s).date().isoformat()
    except Exception:
        m = re.search(r"20\d{2}-\d{2}-\d{2}", s)
        return m.group(0) if m else None


def _fold(value: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFKD', value or '') if not unicodedata.combining(c)).lower().strip('.')


_NORMALIZED_MONTHS = {_fold(k): v for k, v in MONTHS.items()}


def _month(token: str) -> int | None:
    return _NORMALIZED_MONTHS.get(_fold(token))


def _valid_date(y: int, mo: int, d: int) -> str | None:
    try:
        return datetime(y, mo, d).date().isoformat()
    except Exception:
        return None


def extract_dates(text: str) -> list[dict]:
    rows = []
    seen = set()
    for m in DATE_PATTERNS[0].finditer(text):
        y, mo, d = map(int, m.groups())
        key = _valid_date(y, mo, d)
        if key and key not in seen:
            seen.add(key)
            rows.append({'date': key, 'match': m.group(0), 'context': text[max(0, m.start()-220):m.end()+220]})
    for m in DATE_PATTERNS[1].finditer(text):
        d, mo, y = map(int, m.groups())
        key = _valid_date(y, mo, d)
        if key and key not in seen:
            seen.add(key)
            rows.append({'date': key, 'match': m.group(0), 'context': text[max(0, m.start()-220):m.end()+220]})
    for idx in (2, 3):
        for m in DATE_PATTERNS[idx].finditer(text):
            if idx == 2:
                d = int(m.group(1)); mo = _month(m.group(2)); y = int(m.group(3))
            else:
                mo = _month(m.group(1)); d = int(m.group(2)); y = int(m.group(3))
            if not mo:
                continue
            key = _valid_date(y, mo, d)
            if key and key not in seen:
                seen.add(key)
                rows.append({'date': key, 'match': m.group(0), 'context': text[max(0, m.start()-220):m.end()+220]})
    return rows


def _contexts_around_deadline_words(text: str, before: int = 650, after: int = 1300, max_hits: int = 80) -> list[str]:
    chunks = []
    seen = set()
    for m in DEADLINE_WORDS.finditer(text or ''):
        chunk = text[max(0, m.start()-before):min(len(text), m.end()+after)]
        key = re.sub(r"\s+", " ", chunk[:300]).casefold()
        if key in seen:
            continue
        seen.add(key)
        chunks.append(chunk)
        if len(chunks) >= max_hits:
            break
    return chunks


def deadline_contexts(gates: dict, corpus: str) -> tuple[str, dict]:
    cats = gates.get('categories') or {}
    hits = cats.get('submission') or cats.get('deadline_submission') or []
    gate_chunks = []
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        s = str(hit.get('snippet') or '')
        gate_chunks.extend(_contexts_around_deadline_words(s, before=500, after=900, max_hits=20))

    # Search the full extracted DCE as a recall rescue. This never changes the
    # evidence contract: only gate-ready authoritative DCE text is scanned.
    corpus_chunks = _contexts_around_deadline_words(corpus, before=650, after=1300, max_hits=80)
    all_chunks = []
    seen = set()
    for chunk in gate_chunks + corpus_chunks:
        key = re.sub(r"\s+", " ", chunk[:400]).casefold()
        if key not in seen:
            seen.add(key)
            all_chunks.append(chunk)
    return '\n'.join(all_chunks), {
        'gate_contexts': len(gate_chunks),
        'corpus_contexts': len(corpus_chunks),
        'unique_contexts': len(all_chunks),
    }


def process(root: Path) -> dict:
    candidate = load(root / 'candidate.json', {})
    gates = load(root / 'gate_snippets.json', {})
    evidence = load(root / 'evidence_quality.json', {})
    corpus_path = root / 'corpus.txt'
    corpus = corpus_path.read_text(encoding='utf-8', errors='replace') if corpus_path.exists() else ''
    notice_date = parse_notice_date(candidate.get('deadline'))
    context, context_stats = deadline_contexts(gates, corpus) if evidence.get('gate_readiness') else ('', {'gate_contexts': 0, 'corpus_contexts': 0, 'unique_contexts': 0})
    found = extract_dates(context)
    dce_dates = sorted({x['date'] for x in found})

    if not evidence.get('gate_readiness'):
        status = 'NOT_APPLICABLE_DCE_NOT_GATE_READY'; conflict = False
    elif not dce_dates:
        status = 'UNKNOWN_NO_DCE_DEADLINE_PARSED'; conflict = False
    elif notice_date and notice_date in dce_dates:
        status = 'CONSISTENT_NOTICE_DATE_FOUND_IN_DCE'; conflict = False
    elif notice_date:
        status = 'DEADLINE_CONFLICT_REVIEW_REQUIRED'; conflict = True
    elif len(dce_dates) == 1:
        status = 'DCE_DEADLINE_FOUND_NOTICE_DEADLINE_MISSING'; conflict = False
    else:
        status = 'DCE_MULTIPLE_DEADLINE_DATES_REVIEW_REQUIRED'; conflict = True

    result = {
        'contract': 'AUTHORITY_CONFLICTS_V2',
        'candidate_id': candidate.get('candidate_id') or root.name,
        'deadline': {
            'status': status,
            'conflict': conflict,
            'notice_deadline_raw': candidate.get('deadline'),
            'notice_deadline_date': notice_date,
            'dce_deadline_candidates': dce_dates,
            'evidence': found[:30],
            'context_stats': context_stats,
            'rule': 'Never silently overwrite deadline metadata. Deadline candidates come only from authoritative gate-ready DCE text near deadline language; unresolved/multiple/conflicting dates require review before final 90+/FINAL_SUPER_GREEN.'
        }
    }
    (root / 'authority_conflicts.json').write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default='out')
    args = ap.parse_args()
    base = Path(args.root)
    roots = sorted(set(p.parent for p in base.rglob('manifest.json')))
    rows = [process(r) for r in roots]
    statuses = sorted({r['deadline']['status'] for r in rows})
    print(json.dumps({
        'candidates': len(rows),
        'deadline_conflicts': sum(1 for r in rows if r['deadline']['conflict']),
        'deadline_parsed': sum(1 for r in rows if r['deadline']['status'] not in {'UNKNOWN_NO_DCE_DEADLINE_PARSED', 'NOT_APPLICABLE_DCE_NOT_GATE_READY'}),
        'statuses': {s: sum(1 for r in rows if r['deadline']['status'] == s) for s in statuses},
    }, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
