from __future__ import annotations

import argparse
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path

POSITIVE_GROUPS = {
    "WEB_APP": re.compile(r"\b(?:web\s*site|website|site\s+web|internetseite|webauftritt|web\s+portal|portal\s+web|intranet|extranet|cms\b|content management|web\s+application|webapp|mobile\s+app|application development|digital platform|online platform)\b", re.I),
    "CREATIVE": re.compile(r"\b(?:graphic design|design graphique|grafikdesign|branding|brand identity|visual identity|communication services?|communications? campaign|marketing|content creation|copywriting|editorial|social media|animation|motion design|video production|film production|audiovisual|photography)\b", re.I),
    "LANGUAGE": re.compile(r"\b(?:translation|traduction|übersetzung|transcription|proofreading|revision linguistique|interpreting|locali[sz]ation)\b", re.I),
    "PRINT": re.compile(r"\b(?:printing services?|print services?|impression|imprimerie|brochures?|flyers?|leaflets?|booklets?|posters?|signage|signalétique|promotional material|publications?)\b", re.I),
    "DATA_DIGITIZE": re.compile(r"\b(?:digitisation|digitization|digitalisation|document scanning|scanning services?|data entry|data processing|document management|records management|archive digit|workflow automation|process automation|robotic process automation|rpa\b)\b", re.I),
    "TRAINING_DIGITAL": re.compile(r"\b(?:e-learning|elearning|online training|digital training|training content|learning platform|learning management system|lms\b|instructional design)\b", re.I),
    "SOFTWARE_LIGHT": re.compile(r"\b(?:software development|application software|custom software|saas\b|software as a service|licen[cs]e renewal|software licen[cs]es?)\b", re.I),
}

HARD_NEGATIVE = re.compile(
    r"\b(?:construction|civil works?|road works?|bridge works?|renovation works?|roofing|masonry|excavation|demolition|"
    r"security guard|security officer|armed security|patient transport|ambulance|clinical services?|medical services?|laboratory services?|"
    r"generator maintenance|chiller maintenance|vehicle maintenance|aircraft maintenance|ship repair|firefighting vehicle|fire truck|"
    r"fuel delivery|diesel delivery|ammunition|weapon|herbicide application|pest control|laundry services?|food services?|catering services?|"
    r"electrical works?|plumbing works?|hvac works?|painting works?|insulation works?|snow clearing|waste collection|janitorial|cleaning services?)\b",
    re.I,
)

FRICTION = re.compile(
    r"\b(?:sap\b|oracle\b|salesforce\b|microsoft dynamics|cybersecurity|soc\b|siem\b|penetration testing|network infrastructure|"
    r"data center|datacenter|managed it|managed service|24/7|on-site support|onsite support|hardware installation|telecommunications network|"
    r"authorized reseller|authorised reseller|manufacturer authorization|top secret|secret clearance|security clearance|fedramp)\b",
    re.I,
)

INFO_ONLY = re.compile(r"\b(?:sources sought|industry day|request for information|\brfi\b|prior information notice|pin only|market consultation|award notice|contract award)\b", re.I)

KNOWN_PRIORITY = {
    "IE:8670172", "IE:8763289", "IE:8855660", "IE:8693030",
}


def load(path: Path):
    with path.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            line=line.strip()
            if line:
                obj=json.loads(line)
                if isinstance(obj, dict):
                    yield obj


def clean(value, limit=1800):
    text=re.sub(r"<[^>]+>", " ", str(value or ""))
    return " ".join(text.split())[:limit]


def first(row, *keys):
    for key in keys:
        value=row.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def deadline_open(row):
    value=str(first(row,"deadline","submission_deadline","deadline_iso") or "").strip()
    if not value:
        return True
    try:
        return date.fromisoformat(value[:10]) >= datetime.now(timezone.utc).date()
    except Exception:
        return True


def score(row):
    title=clean(first(row,"title","name"),700)
    desc=clean(first(row,"description","summary","short_description"),1800)
    text=f"{title} {desc}"
    cid=str(first(row,"candidate_id") or "")
    groups=[name for name,rx in POSITIVE_GROUPS.items() if rx.search(text)]
    s=0
    if cid in KNOWN_PRIORITY:
        s += 70
    s += 28*len(groups)
    if groups and not HARD_NEGATIVE.search(text):
        s += 15
    if HARD_NEGATIVE.search(text):
        s -= 70
    if FRICTION.search(text):
        s -= 22
    if INFO_ONLY.search(text):
        s -= 90
    # SAM is not excluded, but requires stronger positive evidence after the noisy wave.
    if cid.startswith("US-SAM:"):
        s -= 18
    deadline=str(first(row,"deadline","submission_deadline","deadline_iso") or "")
    return s, groups, title, desc, deadline


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-items", type=int, default=400)
    ap.add_argument("--min-score", type=int, default=20)
    args=ap.parse_args()

    ranked=[]
    total=0
    open_count=0
    for row in load(Path(args.input)):
        total += 1
        if not deadline_open(row):
            continue
        open_count += 1
        s,groups,title,desc,deadline=score(row)
        if s < args.min_score or not groups:
            continue
        ranked.append({
            "candidate_id": first(row,"candidate_id"),
            "title": title,
            "buyer": first(row,"buyer","contracting_authority","organisation","organization"),
            "deadline": deadline or None,
            "notice_url": first(row,"notice_url","source_url","url"),
            "portal": first(row,"portal"),
            "source": first(row,"source"),
            "estimated_value": first(row,"estimated_value","value"),
            "currency": first(row,"currency"),
            "rescue_score": s,
            "positive_groups": groups,
            "description_excerpt": desc,
            "pre_dce_state": "GPT_SEMANTIC_REVIEW_REQUIRED",
        })

    ranked.sort(key=lambda x:(int(x["rescue_score"]), str(x.get("deadline") or "9999")), reverse=True)
    items=ranked[:max(0,args.max_items)]
    payload={
        "schema":"SPM_RESCUE_POOL_V1",
        "generated_at":datetime.now(timezone.utc).isoformat(),
        "source_total":total,
        "source_open_or_unknown_deadline":open_count,
        "matched_before_cap":len(ranked),
        "count":len(items),
        "items":items,
        "contract":"This is a high-recall pre-DCE pool only. rescue_score is lexical triage, never eligibility or SUPERGREEN. GPT Web must semantically review title+description before writing a DCE selection manifest.",
    }
    out=Path(args.out)
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({k:payload[k] for k in ("source_total","source_open_or_unknown_deadline","matched_before_cap","count")},indent=2))

if __name__=="__main__":
    main()
