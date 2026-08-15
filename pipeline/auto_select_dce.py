from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from materialize_dce_selection import identity

# The autonomous selector is a retrieval scheduler, not the business source of truth.
# Its first duty is nevertheless to avoid wasting DCE runners on opportunities that
# are plainly outside SPM Business's lean/digital execution envelope.
#
# Generic words such as "digital", "portal", "software", "application", "data",
# "maintenance", "content" or "communications" NEVER qualify an opportunity alone.
CORE_SIGNAL_GROUPS: dict[str, dict[str, int]] = {
    "SPM_WEB": {
        "website": 84,
        "web site": 84,
        "website redesign": 90,
        "website development": 90,
        "web development": 88,
        "web design": 88,
        "web portal": 82,
        "landing page": 80,
        "cms": 78,
        "wordpress": 84,
        "drupal": 84,
        "typo3": 84,
        "web accessibility": 78,
        "intranet redesign": 76,
    },
    "SPM_DESIGN": {
        "graphic design": 86,
        "visual identity": 84,
        "branding": 82,
        "layout design": 80,
        "publication design": 80,
        "annual report design": 82,
        "typesetting": 76,
        "illustration": 76,
        "creative design": 80,
    },
    "SPM_VIDEO": {
        "video production": 86,
        "video editing": 88,
        "animation": 82,
        "motion graphics": 86,
        "audiovisual production": 82,
        "audio visual production": 82,
        "post-production": 82,
        "post production": 82,
        "explainer video": 84,
        "film production": 76,
    },
    "SPM_CONTENT_MARKETING": {
        "digital marketing": 78,
        "social media management": 78,
        "social media content": 82,
        "content production": 78,
        "content creation": 76,
        "copywriting": 76,
        "search engine optimization": 80,
        "search engine optimisation": 80,
        "seo services": 80,
        "online campaign": 74,
        "digital campaign": 76,
    },
    "SPM_TRANSCRIPTION": {
        "transcription": 86,
        "subtitling": 84,
        "captioning": 84,
        "closed captions": 82,
    },
    "SPM_SOFTWARE_AUTOMATION": {
        "workflow automation": 84,
        "robotic process automation": 82,
        "rpa development": 82,
        "low-code": 80,
        "low code": 80,
        "no-code": 80,
        "no code": 80,
        "api integration": 80,
        "software development": 76,
        "application development": 76,
        "app development": 80,
        "web application": 80,
        "database development": 72,
        "data processing services": 72,
        "data entry services": 70,
        "system integration": 70,
    },
    "SPM_PRINT_MIDDLEMAN": {
        "printing services": 84,
        "printing service": 84,
        "print services": 82,
        "brochure printing": 86,
        "leaflet printing": 86,
        "booklet printing": 86,
        "poster printing": 82,
        "printed materials": 80,
        "publication printing": 80,
        "annual report printing": 82,
        "printing": 74,
        "brochure": 70,
        "leaflet": 70,
        "booklet": 70,
    },
}

# The narrow CPV families below are strong enough to qualify a notice even when its
# title is not English. Broad IT CPVs are deliberately not accepted by themselves.
CPV_FIT_PREFIXES: tuple[tuple[str, str, int], ...] = (
    ("72413", "SPM_WEB", 82),
    ("72415", "SPM_WEB", 76),
    ("798", "SPM_PRINT_MIDDLEMAN", 80),
    ("9211", "SPM_VIDEO", 78),
    ("7934", "SPM_CONTENT_MARKETING", 72),
    ("7953", "SPM_TRANSCRIPTION", 72),
)

# These are pre-DCE scheduling exclusions, not legal eligibility findings. The DCE
# gate reader remains authoritative on the final bid/no-bid verdict.
HARD_REJECT_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("physical-works", re.compile(
        r"\b(construction|civil works?|road works?|building works?|roofing|roof works?|"
        r"plumbing|hvac|heating system|electrical installation|renovation works?|"
        r"excavation|asphalt|bridge works?|demolition|masonry)\b", re.I)),
    ("physical-operations", re.compile(
        r"\b(cleaning services?|catering|food supply|waste collection|security guards?|"
        r"grounds maintenance|vehicle maintenance|fleet maintenance|janitorial)\b", re.I)),
    ("medical-regulated", re.compile(
        r"\b(pharmaceutical|clinical services?|medical equipment|laboratory testing|"
        r"medical devices?|surgical|patient care)\b", re.I)),
    ("regulated-professional", re.compile(
        r"\b(legal services?|statutory audit|audit services?|architectural services?|"
        r"engineering services?|engineering design|quantity surveying|land surveying)\b", re.I)),
    ("staffing-bodyshop", re.compile(
        r"\b(staff augmentation|temporary staff|temporary personnel|recruitment services?|"
        r"personnel supply|body ?shop(?:ping)?|consultant resources?|resource profiles?|"
        r"fte\b|full[- ]time equivalent|man[- ]days?|person[- ]days?)\b", re.I)),
    ("hardware-infrastructure", re.compile(
        r"\b(server hardware|network equipment|network switches?|routers?|structured cabling|"
        r"workstations?|laptops?|desktop computers?|storage appliances?|data centre hardware|"
        r"data center hardware|telecommunications equipment)\b", re.I)),
    ("onsite-field", re.compile(
        r"\b(on[- ]site services?|onsite services?|field services?|installation of equipment|"
        r"equipment installation|commissioning services?)\b", re.I)),
)

TRAINING_RE = re.compile(
    r"\b(training services?|training course|training courses|workshops?|coaching services?|"
    r"trainer|instructor|facilitator|classroom training|vocational training)\b", re.I
)
DIGITAL_PRODUCTION_EXCEPTION_RE = re.compile(
    r"\b(e[- ]learning platform|learning management system|lms development|"
    r"training video production|e[- ]learning content (?:creation|production|development))\b", re.I
)

SAM_OPEN_SET_ASIDE_VALUES = {
    "", "none", "n/a", "na", "not applicable", "no set aside used", "no set-aside used",
    "not set aside", "unrestricted", "full and open competition",
}
SAM_HARD_NON_BID_TYPES = (
    "award", "justification", "intent to bundle", "fair opportunity / limited sources justification",
)
SAM_SOFT_NON_BID_TYPES = {
    "sources sought": -60,
    "special notice": -50,
    "presolicitation": -18,
    "presolicitation notice": -18,
    "request for information": -55,
    "rfi": -55,
}
SAM_PORTALS = {"US_SAM", "US_SAM_BULK"}
EXPLORE_SHARE = 0.15
MIN_HISTORY_FOR_EXPLOIT = 20


def load_jsonl(path: Path) -> Iterable[dict]:
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if isinstance(obj, dict):
                rows.append(obj)
    return rows


def load_json(path: Path | None, default=None):
    if not path or not path.exists():
        return {} if default is None else default
    try:
        obj = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        return obj if isinstance(obj, dict) else ({} if default is None else default)
    except Exception:
        return {} if default is None else default


def parse_deadline(v):
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except Exception:
        return None


def portal_key(rec: dict) -> str:
    return str(rec.get("portal") or rec.get("source") or "UNKNOWN").strip().upper() or "UNKNOWN"


def performance_record(portal_performance: dict | None, pkey: str) -> dict:
    return (((portal_performance or {}).get("portals") or {}).get(pkey) or {})


def _record_text(rec: dict) -> str:
    keys = (
        "title", "description", "buyer", "cpv", "cpv_codes", "cpv_or_category",
        "category", "categories", "procedure", "notice_eligibility",
    )
    return " " + re.sub(r"\s+", " ", " ".join(str(rec.get(k) or "") for k in keys)).casefold() + " "


def _cpv_tokens(rec: dict) -> list[str]:
    raw = " ".join(str(rec.get(k) or "") for k in ("cpv", "cpv_codes", "cpv_or_category", "category"))
    return re.findall(r"\b\d{5,8}\b", raw)


def business_fit(rec: dict) -> tuple[bool, str, int, list[str]]:
    """Fail closed on obvious non-core work; require a concrete SPM execution signal."""
    text = _record_text(rec)
    reasons: list[str] = []

    for label, rx in HARD_REJECT_RULES:
        m = rx.search(text)
        if m:
            return False, "REJECT_NONCORE", -100, [f"reject:{label}:{m.group(0)[:80]}"]

    if TRAINING_RE.search(text) and not DIGITAL_PRODUCTION_EXCEPTION_RE.search(text):
        return False, "REJECT_TRAINING_DELIVERY", -100, ["reject:human-training-delivery"]

    class_scores: dict[str, int] = {}
    signal_hits: dict[str, list[str]] = defaultdict(list)
    for fit_class, signals in CORE_SIGNAL_GROUPS.items():
        for phrase, pts in signals.items():
            if phrase in text:
                class_scores[fit_class] = max(class_scores.get(fit_class, 0), pts)
                signal_hits[fit_class].append(phrase)

    for cpv in _cpv_tokens(rec):
        for prefix, fit_class, pts in CPV_FIT_PREFIXES:
            if cpv.startswith(prefix):
                class_scores[fit_class] = max(class_scores.get(fit_class, 0), pts)
                signal_hits[fit_class].append(f"cpv:{cpv}")

    if not class_scores:
        return False, "REJECT_NO_CORE_SIGNAL", -100, ["reject:no-concrete-spm-core-signal"]

    fit_class, base = max(class_scores.items(), key=lambda kv: (kv[1], kv[0]))
    all_hits = sum(len(v) for v in signal_hits.values())
    breadth_bonus = min(10, max(0, all_hits - 1) * 2)
    fit_score = min(100, base + breadth_bonus)
    reasons.append(f"fit:{fit_class}:{fit_score}")
    for cls, hits in sorted(signal_hits.items()):
        if hits:
            reasons.append(f"signals:{cls}:{','.join(hits[:5])}")
    return True, fit_class, fit_score, reasons


def history_adjustment(rec: dict, portal_performance: dict | None) -> tuple[int, list[str]]:
    """Portal yield is a tiebreaker inside the SPM-fit pool, never a fit substitute."""
    pkey = portal_key(rec)
    hist = performance_record(portal_performance, pkey)
    n = int(hist.get("candidates") or 0)
    if n < 10:
        return 0, [f"history-explore:n={n}"] if portal_performance else []

    smooth = float(hist.get("smoothed_useful_rate") or 0.0)
    auth = float(hist.get("auth_rate") or 0.0)
    generic = float(hist.get("generic_or_unresolved_rate") or 0.0)
    delta = 0
    reasons = [f"history:n={n},yield={smooth:.3f}"]

    scale = 0.5 if n < MIN_HISTORY_FOR_EXPLOIT else 1.0
    if smooth >= 0.45:
        base = 6
    elif smooth >= 0.20:
        base = 4
    elif smooth >= 0.12:
        base = 2
    elif smooth <= 0.03:
        base = -6
    elif smooth <= 0.06:
        base = -4
    elif smooth <= 0.10:
        base = -2
    else:
        base = 0
    yield_delta = int(round(base * scale))
    delta += yield_delta
    if yield_delta:
        reasons.append(f"{yield_delta:+d}:rolling-portal-yield")

    if n >= MIN_HISTORY_FOR_EXPLOIT:
        if auth >= 0.75:
            delta -= 2
            reasons.append("-2:rolling-auth-rate")
        elif auth >= 0.45:
            delta -= 1
            reasons.append("-1:rolling-auth-rate")
        if generic >= 0.80:
            delta -= 2
            reasons.append("-2:rolling-generic-rate")
        elif generic >= 0.60:
            delta -= 1
            reasons.append("-1:rolling-generic-rate")

    return max(-8, min(8, delta)), reasons


def portal_cap(limit: int, pkey: str, portal_performance: dict | None) -> int:
    """Diversify DCE work after business-fit gating; no portal may dominate the queue."""
    if pkey in SAM_PORTALS:
        return max(12, math.ceil(limit * 0.125))
    hist = performance_record(portal_performance, pkey)
    n = int(hist.get("candidates") or 0)
    smooth = float(hist.get("smoothed_useful_rate") or 0.0)
    if n >= 80 and smooth >= 0.35:
        share = 0.30
    elif n >= 20 and smooth >= 0.18:
        share = 0.25
    elif n >= 30 and smooth <= 0.03:
        share = 0.08
    elif n >= 20 and smooth <= 0.10:
        share = 0.12
    else:
        share = 0.20
    return max(8, math.ceil(limit * share))


def sam_adjustment(rec: dict) -> tuple[int, list[str]]:
    portal = portal_key(rec)
    if portal not in SAM_PORTALS:
        return 0, []

    score = 0
    reasons = []
    set_aside = re.sub(r"\s+", " ", str(rec.get("set_aside") or "").strip()).casefold()
    if set_aside not in SAM_OPEN_SET_ASIDE_VALUES:
        score -= 100
        reasons.append("-100:us-set-aside")

    notice_type = re.sub(r"\s+", " ", str(rec.get("type") or "").strip()).casefold()
    if notice_type:
        if any(term in notice_type for term in SAM_HARD_NON_BID_TYPES):
            score -= 100
            reasons.append("-100:sam-non-bid-notice")
        else:
            for term, penalty in SAM_SOFT_NON_BID_TYPES.items():
                if notice_type == term or term in notice_type:
                    score += penalty
                    reasons.append(f"{penalty}:sam-{term.replace(' ', '-')}")
                    break
        if "solicitation" in notice_type and "presolicitation" not in notice_type:
            score += 6
            reasons.append("+6:sam-live-solicitation")

    route = rec.get("route") or {}
    direct_docs = [u for u in (route.get("document_urls") or []) if isinstance(u, str) and u.startswith(("http://", "https://"))]
    if direct_docs:
        score += 6
        reasons.append("+6:sam-direct-public-doc-route")
    else:
        score -= 4
        reasons.append("-4:sam-no-direct-doc-route")
    return score, reasons


def retrieval_score(rec: dict, portal_performance: dict | None = None) -> tuple[int, list[str]]:
    eligible, fit_class, fit_score, fit_reasons = business_fit(rec)
    if not eligible:
        return -100, fit_reasons

    score = fit_score
    reasons = list(fit_reasons)

    value = rec.get("estimated_value")
    try:
        value = float(value) if value not in (None, "") else None
    except Exception:
        value = None
    if value is not None and value > 0:
        if value <= 250_000:
            score += 6
            reasons.append("+6:lean-value-band")
        elif value <= 750_000:
            score += 3
            reasons.append("+3:moderate-value-band")
        elif value >= 5_000_000:
            score -= 10
            reasons.append("-10:very-large-value")

    deadline = parse_deadline(rec.get("deadline"))
    now = datetime.now(timezone.utc)
    if deadline is not None:
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        days = (deadline - now).total_seconds() / 86400
        if days < 0:
            score -= 100
            reasons.append("-100:expired")
        elif days < 2:
            score -= 20
            reasons.append("-20:deadline-too-close")
        elif days <= 30:
            score += 4
            reasons.append("+4:actionable-deadline")

    sam_delta, sam_reasons = sam_adjustment(rec)
    score += sam_delta
    reasons.extend(sam_reasons)

    # Crucial ordering: portal yield can move an already-fit opportunity only a few
    # points. It can never rescue a non-core candidate because business_fit failed above.
    hist_delta, hist_reasons = history_adjustment(rec, portal_performance)
    score += hist_delta
    reasons.extend(hist_reasons)

    if rec.get("seen_before"):
        score -= 80
        reasons.append("-80:seen-before")
    if rec.get("current") is False:
        score -= 100
        reasons.append("-100:not-current")
    return max(-100, min(100, score)), reasons


def _emit(out, item, emitted_ids, emitted_tb, counts, bucket: str):
    score, cid, reasons, rec, cid_key, tb_key, fit_class, fit_score = item
    if cid_key in emitted_ids or (tb_key and tb_key in emitted_tb):
        return False
    emitted_ids.add(cid_key)
    if tb_key:
        emitted_tb.add(tb_key)
    pkey = portal_key(rec)
    counts[pkey] += 1
    out.append({
        "candidate_id": cid,
        "preliminary_score": min(89, score),
        "business_fit_score": fit_score,
        "selection_fit_class": fit_class,
        "wide_read_run_id": rec.get("wide_read_run_id"),
        "status": "AUTO_DCE_PREFETCH",
        "selection_portal": pkey,
        "selection_bucket": bucket,
        "selection_reason": "SPM business-fit gated first; portal DCE yield is secondary | " + ", ".join(reasons[:18]),
    })
    return True


def _fill_ranked(items, out, emitted_ids, emitted_tb, counts, target: int, limit: int, performance: dict | None, bucket: str):
    for item in items:
        if len(out) >= target:
            break
        pkey = portal_key(item[3])
        if counts[pkey] >= portal_cap(limit, pkey, performance):
            continue
        _emit(out, item, emitted_ids, emitted_tb, counts, bucket)


def _fill_explore_round_robin(items, out, emitted_ids, emitted_tb, counts, target: int, limit: int, performance: dict | None):
    grouped: dict[str, list] = defaultdict(list)
    for item in items:
        grouped[portal_key(item[3])].append(item)
    active = sorted(grouped, key=lambda p: (-grouped[p][0][0], p))
    explore_portal_cap = max(4, math.ceil(limit * EXPLORE_SHARE / 2))
    while active and len(out) < target:
        next_active = []
        for pkey in active:
            if len(out) >= target:
                break
            if counts[pkey] >= min(explore_portal_cap, portal_cap(limit, pkey, performance)):
                continue
            queue = grouped[pkey]
            while queue:
                item = queue.pop(0)
                if _emit(out, item, emitted_ids, emitted_tb, counts, "explore"):
                    break
            if queue and counts[pkey] < min(explore_portal_cap, portal_cap(limit, pkey, performance)):
                next_active.append(pkey)
        active = next_active


def select(records: Iterable[dict], minimum: int = 34, limit: int = 320, blocked_ids: set[str] | None = None, portal_performance: dict | None = None) -> list[dict]:
    rows = list(records)
    blocked_norm = {str(x).strip().casefold() for x in (blocked_ids or set()) if str(x).strip()}
    blocked_tb: set[tuple[str, str]] = set()
    for rec in rows:
        cid_key, tb_key = identity(rec)
        if cid_key in blocked_norm and tb_key:
            blocked_tb.add(tb_key)

    all_scored = []
    for rec in rows:
        cid = str(rec.get("candidate_id") or "").strip()
        cid_key, tb_key = identity(rec)
        if not cid or cid_key in blocked_norm or (tb_key and tb_key in blocked_tb):
            continue
        eligible, fit_class, fit_score, _ = business_fit(rec)
        if not eligible:
            continue
        score, reasons = retrieval_score(rec, portal_performance=portal_performance)
        all_scored.append((score, cid, reasons, rec, cid_key, tb_key, fit_class, fit_score))

    all_scored.sort(key=lambda x: (-x[0], -x[7], str(x[3].get("deadline") or "9999"), x[1]))
    recall_floor = max(0, minimum - 12)
    eligible = [x for x in all_scored if x[0] >= recall_floor]
    exploit = []
    explore = []
    for item in eligible:
        pkey = portal_key(item[3])
        n = int(performance_record(portal_performance, pkey).get("candidates") or 0)
        (exploit if n >= MIN_HISTORY_FOR_EXPLOIT else explore).append(item)

    out = []
    emitted_ids: set[str] = set()
    emitted_tb: set[tuple[str, str]] = set()
    counts: Counter[str] = Counter()
    explore_target_count = min(limit, max(1, round(limit * EXPLORE_SHARE)))
    exploit_target_count = max(0, limit - explore_target_count)

    exploit_primary = [x for x in exploit if x[0] >= minimum]
    exploit_recall = [x for x in exploit if x[0] < minimum]
    _fill_ranked(exploit_primary, out, emitted_ids, emitted_tb, counts, exploit_target_count, limit, portal_performance, "exploit")
    _fill_ranked(exploit_recall, out, emitted_ids, emitted_tb, counts, exploit_target_count, limit, portal_performance, "exploit-recall")

    explore_absolute_target = min(limit, len(out) + explore_target_count)
    _fill_explore_round_robin(explore, out, emitted_ids, emitted_tb, counts, explore_absolute_target, limit, portal_performance)

    # Fill only from the already business-fit pool. Capacity is allowed to remain
    # unused rather than backfilling garbage simply to hit a numeric batch target.
    _fill_ranked(eligible, out, emitted_ids, emitted_tb, counts, limit, limit, portal_performance, "elastic-fit-only")
    if len(out) < limit:
        for relax_share in (0.35, 0.45):
            for item in eligible:
                if len(out) >= limit:
                    break
                pkey = portal_key(item[3])
                cap = portal_cap(limit, pkey, portal_performance) if pkey in SAM_PORTALS else max(
                    portal_cap(limit, pkey, portal_performance), math.ceil(limit * relax_share)
                )
                if counts[pkey] >= cap:
                    continue
                _emit(out, item, emitted_ids, emitted_tb, counts, "elastic-portal-relaxed-fit-only")
            if len(out) >= limit:
                break
    return out


def modeled_expected(selected: list[dict], portal_performance: dict | None) -> dict:
    counts = Counter(str(x.get("selection_portal") or "UNKNOWN") for x in selected)
    expected = 0.0
    known = 0
    by_portal = {}
    for portal, count in counts.items():
        hist = performance_record(portal_performance, portal)
        n = int(hist.get("candidates") or 0)
        rate = float(hist.get("smoothed_useful_rate") or 0.2)
        if n:
            known += count
        modeled = count * rate
        expected += modeled
        by_portal[portal] = {
            "selected": count,
            "history_n": n,
            "smoothed_useful_rate": round(rate, 6),
            "modeled_useful": round(modeled, 3),
        }
    return {
        "modeled_expected_useful": round(expected, 3),
        "modeled_expected_useful_rate": round(expected / max(1, len(selected)), 6),
        "selected_with_history": known,
        "by_portal": by_portal,
        "note": "DCE-route yield model inside the already SPM-fit pool; never a business-fit or eligibility signal.",
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--minimum", type=int, default=34)
    ap.add_argument("--limit", type=int, default=320)
    ap.add_argument("--blocked", action="append", default=[])
    ap.add_argument("--performance", default="")
    args = ap.parse_args()

    blocked = set()
    for p in args.blocked:
        for rec in load_jsonl(Path(p)):
            cid = str(rec.get("candidate_id") or "").strip()
            if cid:
                blocked.add(cid)
    performance = load_json(Path(args.performance), {}) if args.performance else {}
    rows = list(load_jsonl(Path(args.input)))
    selected = select(rows, minimum=args.minimum, limit=args.limit, blocked_ids=blocked, portal_performance=performance)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for rec in selected:
            f.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n")

    portal_counts = dict(Counter(str(x.get("selection_portal") or "UNKNOWN") for x in selected))
    bucket_counts = dict(Counter(str(x.get("selection_bucket") or "UNKNOWN") for x in selected))
    fit_counts = dict(Counter(str(x.get("selection_fit_class") or "UNKNOWN") for x in selected))
    sam_count = sum(portal_counts.get(p, 0) for p in SAM_PORTALS)
    sam_cap = max(12, math.ceil(args.limit * 0.125))
    fit_results = [business_fit(rec) for rec in rows]
    total_fit = sum(1 for ok, _, _, _ in fit_results if ok)
    fit_reject_counts = Counter(cls for ok, cls, _, _ in fit_results if not ok)

    summary = {
        "input": len(rows),
        "blocked_ids": len(blocked),
        "spm_business_fit_pool": total_fit,
        "rejected_noncore": len(rows) - total_fit,
        "fit_reject_counts": dict(fit_reject_counts),
        "selected": len(selected),
        "minimum": args.minimum,
        "recall_floor": max(0, args.minimum - 12),
        "limit": args.limit,
        "fit_policy": "Concrete SPM digital/creative/print/automation signal required before portal-yield scoring; no non-core elastic backfill.",
        "explore_share_target": EXPLORE_SHARE,
        "selection_fit_counts": fit_counts,
        "selection_portal_counts": portal_counts,
        "selection_bucket_counts": bucket_counts,
        "max_portal_share": round(max(portal_counts.values(), default=0) / max(1, len(selected)), 6),
        "sam_count": sam_count,
        "sam_hard_cap": sam_cap,
        "sam_cap_respected": sam_count <= sam_cap,
        "history_run_ids": (performance.get("run_ids") or [])[-8:],
        "modeled_yield": modeled_expected(selected, performance),
    }
    out.with_suffix(out.suffix + ".summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
