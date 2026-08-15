#!/usr/bin/env python3
from __future__ import annotations

import argparse, json, re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

BUCKETS = {
    "web_cms_digital": [
        "website","web site","site web","site internet","webdesign","web design","web development","wordpress","drupal","cms","content management system","web portal","digital portal","online portal","internetauftritt","webseite","website redesign","refonte site","sitio web","portal web","website maintenance","web maintenance"
    ],
    "design_branding_graphics": [
        "graphic design","design graphique","grafikdesign","visual identity","identité visuelle","branding","brand identity","corporate identity","creative services","communication design","layout design","mise en page","illustration","infographic","infographie","artwork","brochure design","logo design"
    ],
    "video_photo_audio": [
        "video production","production vidéo","videoproduktion","video editing","montage vidéo","post production","post-production","animation","motion graphics","audiovisual","audiovisuel","film production","photography","photographie","photo services","podcast","voice over","voice-over","recording services","livestream","live stream"
    ],
    "translation_transcription_language": [
        "translation","traduction","übersetzung","translation services","interpretation","interpreting","transcription","captioning","subtitling","subtitle","sous-titrage","localisation services","localization services","proofreading","revision linguistique","language services"
    ],
    "marketing_content_social": [
        "social media","content creation","digital content","copywriting","content production","communications campaign","communication campaign","marketing campaign","digital marketing","public relations","publicity campaign","media campaign","community management","editorial services","content strategy","newsletter","communication support"
    ],
    "print_signage_promo": [
        "printing","print services","impression","druckleistungen","brochure","leaflet","flyer","booklet","catalogue","catalog","poster","affiche","banner","signage","display materials","promotional material","promotional items","goodies","printed matter","publication printing","large format print","roll-up","rollup","stand graphics"
    ],
    "training_elearning": [
        "e-learning","elearning","learning platform","learning management system","training content","online training","digital learning","course development","training videos","instructional design","moodle","webinar","training materials","formation en ligne","contenu pédagogique"
    ],
    "data_digitisation_research": [
        "data entry","document digitisation","document digitization","digitisation","digitization","scanning services","records digitisation","data cleaning","data collection","survey design","online survey","questionnaire","market research","desk research","database update","data migration","data processing","document processing","indexing services"
    ],
    "events_exhibition": [
        "event management","event organisation","event organization","conference organisation","conference organization","exhibition stand","trade fair stand","booth design","stand design","event production","event support","conference support","seminar organisation","exhibition services","expo stand","temporary exhibition"
    ],
    "simple_supply_middleman": [
        "office supplies","stationery","promotional items","promotional goods","corporate gifts","bags","tote bags","uniforms","workwear","printed clothing","t-shirts","tshirts","furniture supply","office furniture","signage supply","display stands","banners","folders","notebooks","pens","badges","lanyards","envelopes","labels","stickers","calendars","printed materials","publication materials"
    ],
}

SERVICE_CPV_PREFIXES = ("72", "73", "79", "80")
HARD_NOISE = [
    "construction works","roadworks","sewer","wastewater","asbestos","hvac","roof replacement","bridge construction",
    "medical device","surgical","pharmaceutical","ambulance","firearm","ammunition","missile","weapon system","aircraft spare",
    "fuel supply","vehicle maintenance","food service","catering service","security guarding"
]


def compact(v, limit=3000):
    if v in (None,"",[],{}): return None
    if isinstance(v,(dict,list)):
        s=json.dumps(v,ensure_ascii=False,separators=(",",":"))
    else: s=str(v)
    s=re.sub(r"\s+"," ",s).strip()
    return s[:limit] or None


def row_text(r):
    return " \n ".join(str(r.get(k) or "") for k in ("title","description","cpv_or_category","notice_eligibility","procedure","buyer")).lower()


def cpv_service(r):
    s=str(r.get("cpv_or_category") or "")
    m=re.search(r"\b(\d{8})\b", s)
    return bool(m and m.group(1).startswith(SERVICE_CPV_PREFIXES))


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--packets", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--summary", required=True)
    ap.add_argument("--per-bucket", type=int, default=450)
    ap.add_argument("--max-total", type=int, default=1800)
    args=ap.parse_args()

    rows=[]
    for p in sorted(Path().glob(args.packets)):
        with p.open("r",encoding="utf-8",errors="replace") as f:
            for line in f:
                if not line.strip(): continue
                try:r=json.loads(line)
                except Exception: continue
                if isinstance(r,dict): rows.append(r)

    by_bucket=defaultdict(list)
    for r in rows:
        text=row_text(r)
        # Noise filtering only removes obviously non-SPM categories; it does not rank survivors.
        if any(t in text for t in HARD_NOISE):
            continue
        matched=[]; evidence=[]
        for bucket,terms in BUCKETS.items():
            hits=[t for t in terms if t in text]
            if hits:
                matched.append(bucket); evidence.extend(hits[:6])
        if not matched and cpv_service(r):
            matched=["service_cpv_catchall"]
            evidence=["service_cpv_prefix"]
        if not matched: continue
        slim={
            "candidate_id":r.get("candidate_id"),
            "source_family":r.get("source_family"),
            "buyer":compact(r.get("buyer"),600),
            "title":compact(r.get("title"),1200),
            "description":compact(r.get("description"),2600),
            "cpv_or_category":compact(r.get("cpv_or_category"),1000),
            "estimated_value":r.get("estimated_value"),
            "currency":r.get("currency"),
            "publication_date":r.get("publication_date"),
            "deadline":r.get("deadline"),
            "deadline_utc":r.get("deadline_utc"),
            "open_state":r.get("open_state"),
            "procedure":compact(r.get("procedure"),500),
            "notice_eligibility":compact(r.get("notice_eligibility"),1800),
            "award_criteria":compact(r.get("award_criteria"),1200),
            "subcontracting":compact(r.get("subcontracting"),800),
            "urls":r.get("urls") or [],
            "recall_buckets":sorted(set(matched)),
            "recall_evidence":sorted(set(evidence))[:12],
        }
        for b in matched:
            by_bucket[b].append(slim)

    # Pure recall surface: keep nearest deadlines first inside each topic so GPT can act on time-sensitive work.
    chosen=[]; seen=set(); bucket_counts={}
    order=list(BUCKETS)+["service_cpv_catchall"]
    for b in order:
        arr=by_bucket.get(b,[])
        arr.sort(key=lambda r:(r.get("deadline_utc") or "9999", r.get("publication_date") or ""))
        n=0
        for r in arr:
            cid=str(r.get("candidate_id") or "")
            if not cid or cid in seen: continue
            chosen.append(r); seen.add(cid); n+=1
            if n>=args.per_bucket or len(chosen)>=args.max_total: break
        bucket_counts[b]=n
        if len(chosen)>=args.max_total: break

    out=Path(args.out); out.parent.mkdir(parents=True,exist_ok=True)
    with out.open("w",encoding="utf-8") as f:
        for r in chosen: f.write(json.dumps(r,ensure_ascii=False,separators=(",",":"))+"\n")
    summary={
        "schema":"GPT_RECALL_SURFACE_V1",
        "generated_at":datetime.now(timezone.utc).isoformat(),
        "source_snapshot_rows":len(rows),
        "recall_surface_rows":len(chosen),
        "rule":"Recall/compression only. No row is green because it appears here; GPT must semantically review before any DCE request.",
        "bucket_counts":bucket_counts,
        "unique_candidates":len(seen),
    }
    Path(args.summary).write_text(json.dumps(summary,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(json.dumps(summary,indent=2,ensure_ascii=False))

if __name__=="__main__": main()
