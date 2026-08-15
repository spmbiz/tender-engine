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

# ---------------------------------------------------------------------------
# High-recall notice selector
# ---------------------------------------------------------------------------
# This stage is intentionally permissive. Its job is to decide which notices are
# worth spending DCE retrieval capacity on, NOT to decide final bid eligibility.
# False positives are acceptable here; false negatives are expensive.
#
# The strict truth gate lives downstream in authoritative DCE reading.
# ---------------------------------------------------------------------------

STRONG_SCOPE_SIGNALS: dict[str, dict[str, int]] = {
    "SPM_WEB": {
        "website redesign": 94,
        "website development": 94,
        "web development": 92,
        "web design": 92,
        "web portal": 90,
        "website migration": 90,
        "cms migration": 88,
        "landing page": 86,
        "web accessibility": 84,
        "intranet redesign": 84,
        "wordpress": 84,
        "drupal": 84,
        "typo3": 84,
        "website": 78,
        "web site": 78,
        "cms": 72,
    },
    "SPM_DESIGN": {
        "graphic design": 92,
        "visual identity": 90,
        "brand identity": 90,
        "branding": 86,
        "layout design": 86,
        "publication design": 86,
        "annual report design": 88,
        "typesetting": 82,
        "illustration": 80,
        "creative design": 84,
    },
    "SPM_VIDEO": {
        "video production": 92,
        "video editing": 94,
        "motion graphics": 92,
        "audiovisual production": 90,
        "audio visual production": 90,
        "post-production": 88,
        "post production": 88,
        "explainer video": 90,
        "animation production": 88,
        "film production": 84,
        "animation": 78,
    },
    "SPM_CONTENT_MARKETING": {
        "digital marketing": 88,
        "social media management": 88,
        "social media content": 90,
        "content production": 86,
        "content creation": 84,
        "copywriting": 82,
        "search engine optimization": 84,
        "search engine optimisation": 84,
        "seo services": 84,
        "digital campaign": 84,
        "online campaign": 80,
        "communications campaign": 78,
    },
    "SPM_TRANSCRIPTION": {
        "transcription": 92,
        "subtitling": 90,
        "captioning": 88,
        "closed captions": 88,
        "speech to text": 82,
    },
    "SPM_SOFTWARE_AUTOMATION": {
        "workflow automation": 90,
        "robotic process automation": 88,
        "rpa development": 88,
        "api integration": 88,
        "software development": 86,
        "application development": 86,
        "app development": 86,
        "web application": 88,
        "database development": 82,
        "data migration": 80,
        "system integration": 80,
        "systems integration": 80,
        "low-code": 82,
        "low code": 82,
        "no-code": 82,
        "no code": 82,
        "data processing services": 78,
        "data entry services": 76,
    },
    "SPM_PRINT_MIDDLEMAN": {
        "printing services": 92,
        "printing service": 92,
        "print services": 90,
        "brochure printing": 94,
        "leaflet printing": 94,
        "booklet printing": 94,
        "poster printing": 90,
        "printed materials": 86,
        "publication printing": 88,
        "annual report printing": 90,
        "printing": 76,
        "brochure": 72,
        "leaflet": 72,
        "booklet": 72,
    },
    "SPM_DIGITAL_TRAINING": {
        "digital skills training": 84,
        "digital training": 82,
        "it training": 82,
        "ict training": 82,
        "software training": 82,
        "cybersecurity training": 80,
        "cyber security training": 80,
        "web training": 78,
        "online training": 76,
        "e-learning": 84,
        "e learning": 84,
        "learning management system": 88,
        "lms development": 88,
        "training video production": 88,
        "e-learning content": 84,
        "e learning content": 84,
    },
}

# Broader signals are kept on purpose. They are not enough to call something a
# SUPER GREEN, but they ARE enough to justify DCE retrieval when capacity exists.
RECALL_SCOPE_SIGNALS: dict[str, dict[str, int]] = {
    "SPM_IT_POTENTIAL": {
        "it services": 68,
        "ict services": 68,
        "information technology services": 70,
        "software services": 68,
        "software": 58,
        "saas": 66,
        "cloud services": 64,
        "cloud platform": 64,
        "digital services": 64,
        "digital platform": 66,
        "technology services": 60,
        "it consulting": 62,
        "technology consulting": 60,
        "digital transformation": 68,
        "managed services": 54,
        "application support": 60,
        "software maintenance": 58,
        "data services": 54,
        "data management": 58,
        "database": 54,
        "portal": 52,
    },
    "SPM_TRAINING_POTENTIAL": {
        "training services": 52,
        "training course": 50,
        "training courses": 50,
        "workshop": 48,
        "workshops": 48,
        "coaching services": 46,
        "trainer": 44,
        "facilitator": 44,
    },
    "SPM_COMMS_POTENTIAL": {
        "communications services": 58,
        "communication services": 58,
        "public relations": 62,
        "media services": 58,
        "content services": 56,
        "communications support": 54,
        "campaign services": 56,
    },
    "SPM_RESALE_POTENTIAL": {
        "software licences": 62,
        "software licenses": 62,
        "licence renewal": 58,
        "license renewal": 58,
        "subscription services": 56,
        "cloud subscription": 60,
    },
}

# Narrow CPVs are strong; broad digital/IT CPVs are deliberately accepted at a
# lower score to preserve recall for non-English notices.
CPV_FIT_PREFIXES: tuple[tuple[str, str, int], ...] = (
    ("72413", "SPM_WEB", 88),
    ("72415", "SPM_WEB", 82),
    ("724", "SPM_WEB", 68),
    ("722", "SPM_SOFTWARE_AUTOMATION", 72),
    ("720", "SPM_IT_POTENTIAL", 60),
    ("798", "SPM_PRINT_MIDDLEMAN", 84),
    ("9211", "SPM_VIDEO", 82),
    ("7934", "SPM_CONTENT_MARKETING", 78),
    ("7953", "SPM_TRANSCRIPTION", 78),
    ("805", "SPM_TRAINING_POTENTIAL", 48),
)

# SAM NAICS families that are plausibly digital/creative/print/service work. These
# are a *positive* signal, not a mandatory eligibility requirement.
SAM_DIGITAL_NAICS_PREFIXES: tuple[tuple[str, str, int], ...] = (
    ("541511", "SPM_SOFTWARE_AUTOMATION", 74),
    ("541512", "SPM_SOFTWARE_AUTOMATION", 72),
    ("541513", "SPM_IT_POTENTIAL", 62),
    ("541519", "SPM_IT_POTENTIAL", 62),
    ("518210", "SPM_IT_POTENTIAL", 62),
    ("519", "SPM_CONTENT_MARKETING", 52),
    ("541430", "SPM_DESIGN", 78),
    ("541810", "SPM_CONTENT_MARKETING", 72),
    ("541613", "SPM_CONTENT_MARKETING", 58),
    ("512110", "SPM_VIDEO", 74),
    ("512191", "SPM_VIDEO", 72),
    ("561410", "SPM_TRANSCRIPTION", 62),
    ("323111", "SPM_PRINT_MIDDLEMAN", 78),
    ("323113", "SPM_PRINT_MIDDLEMAN", 76),
    ("611420", "SPM_DIGITAL_TRAINING", 64),
    ("611430", "SPM_TRAINING_POTENTIAL", 52),
)

# Truly obvious physical commodity / construction titles can be hard-rejected when
# there is no title-level digital signal. We intentionally keep this list narrow.
OBVIOUS_PHYSICAL_TITLE_RX = re.compile(
    r"\b(transmitter|pressure transmitter|valve|washer|bearing|pump|gasket|seal assembly|"
    r"cable assembly|connector|fastener|bolt|screw|nut,|motor,|gearbox|compressor|"
    r"roof replacement|roofing works?|road construction|asphalt paving|bridge repair|"
    r"plumbing works?|hvac replacement|boiler replacement|electrical rewiring|"
    r"demolition works?|excavation works?)\b",
    re.I,
)

SAM_OPEN_SET_ASIDE_VALUES = {
    "", "none", "n/a", "na", "not applicable", "no set aside used",
    "no set-aside used", "not set aside", "unrestricted", "full and open competition",
}
SAM_HARD_NON_BID_TYPES = (
    "award", "justification", "intent to bundle", "fair opportunity / limited sources justification",
)
SAM_SOFT_NON_BID_TYPES = {
    "sources sought": -24,
    "special notice": -22,
    "presolicitation": -8,
    "presolicitation notice": -8,
    "request for information": -24,
    "rfi": -24,
}
SAM_PORTALS = {"US_SAM", "US_SAM_BULK"}
EXPLORE_SHARE = 0.20
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


def _clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def _title_text(rec: dict) -> str:
    return f" {_clean(rec.get('title'))} "


def _description_text(rec: dict) -> str:
    keys = ("description", "category", "categories", "procedure", "notice_eligibility")
    return " " + " ".join(_clean(rec.get(k)) for k in keys if rec.get(k)) + " "


def _cpv_tokens(rec: dict) -> list[str]:
    raw = " ".join(str(rec.get(k) or "") for k in ("cpv", "cpv_codes", "cpv_or_category", "category"))
    return re.findall(r"\b\d{5,8}\b", raw)


def _naics_tokens(rec: dict) -> list[str]:
    raw = " ".join(str(rec.get(k) or "") for k in ("naics", "naics_code", "naics_codes", "classification"))
    return re.findall(r"\b\d{5,6}\b", raw)


def _signal_scan(text: str, groups: dict[str, dict[str, int]], *, generic_description: bool = False):
    scores: dict[str, int] = {}
    hits: dict[str, list[str]] = defaultdict(list)
    for fit_class, signals in groups.items():
        for phrase, pts in signals.items():
            # In long descriptions, single generic tokens are too vulnerable to
            # procurement boilerplate. Keep only multiword/strong phrases there.
            if generic_description and " " not in phrase and phrase in {"website", "printing", "brochure", "leaflet", "booklet", "software", "database", "portal", "animation"}:
                continue
            if phrase in text:
                scores[fit_class] = max(scores.get(fit_class, 0), pts)
                hits[fit_class].append(phrase)
    return scores, hits


def business_fit(rec: dict) -> tuple[bool, str, int, list[str]]:
    """High-recall fit gate. Unknown/ambiguous digital work stays alive for DCE reading."""
    title = _title_text(rec)
    desc = _description_text(rec)
    portal = portal_key(rec)
    reasons: list[str] = []

    title_scores, title_hits = _signal_scan(title, STRONG_SCOPE_SIGNALS)
    broad_title_scores, broad_title_hits = _signal_scan(title, RECALL_SCOPE_SIGNALS)
    desc_scores, desc_hits = _signal_scan(desc, STRONG_SCOPE_SIGNALS, generic_description=True)
    broad_desc_scores, broad_desc_hits = _signal_scan(desc, RECALL_SCOPE_SIGNALS, generic_description=True)

    class_scores: dict[str, int] = {}
    signal_hits: dict[str, list[str]] = defaultdict(list)

    def merge(scores, hits, weight=0):
        for cls, score in scores.items():
            class_scores[cls] = max(class_scores.get(cls, 0), max(0, score + weight))
            signal_hits[cls].extend(hits.get(cls, []))

    merge(title_scores, title_hits, 0)
    merge(broad_title_scores, broad_title_hits, 0)
    # Description signals are useful, but slightly discounted versus title-level scope.
    merge(desc_scores, desc_hits, -6)
    merge(broad_desc_scores, broad_desc_hits, -8)

    for cpv in _cpv_tokens(rec):
        for prefix, fit_class, pts in CPV_FIT_PREFIXES:
            if cpv.startswith(prefix):
                class_scores[fit_class] = max(class_scores.get(fit_class, 0), pts)
                signal_hits[fit_class].append(f"cpv:{cpv}")

    naics_tokens = _naics_tokens(rec)
    for naics in naics_tokens:
        for prefix, fit_class, pts in SAM_DIGITAL_NAICS_PREFIXES:
            if naics.startswith(prefix):
                class_scores[fit_class] = max(class_scores.get(fit_class, 0), pts)
                signal_hits[fit_class].append(f"naics:{naics}")

    # Anti-boilerplate rule for SAM: obvious manufactured/physical item title +
    # manufacturing NAICS + no title-level digital signal means the "website" or
    # "printing" hit in boilerplate is not a plausible SPM opportunity.
    title_has_digital = bool(title_scores or broad_title_scores)
    sam_manufacturing = any(n.startswith(("31", "32", "33")) for n in naics_tokens)
    if portal in SAM_PORTALS and OBVIOUS_PHYSICAL_TITLE_RX.search(title) and sam_manufacturing and not title_has_digital:
        return False, "REJECT_SAM_PHYSICAL_COMMODITY", -100, [
            "reject:sam-physical-title-plus-manufacturing-naics",
            f"title:{_clean(rec.get('title'))[:120]}",
            f"naics:{','.join(naics_tokens[:4])}",
        ]

    # Non-SAM obvious physical titles are rejected only when there is no digital
    # signal or digital/creative CPV at all. This remains intentionally narrow.
    if portal not in SAM_PORTALS and OBVIOUS_PHYSICAL_TITLE_RX.search(title) and not title_has_digital:
        if not any(cls.startswith("SPM_") and class_scores.get(cls, 0) >= 60 for cls in class_scores):
            return False, "REJECT_OBVIOUS_PHYSICAL", -100, ["reject:obvious-physical-title-no-digital-signal"]

    if not class_scores:
        return False, "REJECT_NO_RECALL_SIGNAL", -100, ["reject:no-digital-creative-print-training-it-recall-signal"]

    fit_class, base = max(class_scores.items(), key=lambda kv: (kv[1], kv[0]))
    # Breadth bonus is intentionally small: multiple clues improve confidence but
    # should not swamp a strong title or classification signal.
    unique_hits = sorted({h for values in signal_hits.values() for h in values})
    fit_score = min(100, base + min(8, max(0, len(unique_hits) - 1) * 2))
    reasons.append(f"fit:{fit_class}:{fit_score}")
    if title_has_digital:
        reasons.append("scope-signal:title")
    elif desc_scores or broad_desc_scores:
        reasons.append("scope-signal:description")
    for cls, hits in sorted(signal_hits.items()):
        if hits:
            reasons.append(f"signals:{cls}:{','.join(sorted(set(hits))[:6])}")
    return True, fit_class, fit_score, reasons


def history_adjustment(rec: dict, portal_performance: dict | None) -> tuple[int, list[str]]:
    """Portal DCE yield is a small tiebreaker, never a business-fit substitute."""
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
    # Diversity without starving large markets. A single portal may still consume a
    # substantial share when it has genuinely relevant work.
    if pkey in SAM_PORTALS:
        return max(24, math.ceil(limit * 0.20))
    hist = performance_record(portal_performance, pkey)
    n = int(hist.get("candidates") or 0)
    smooth = float(hist.get("smoothed_useful_rate") or 0.0)
    if n >= 80 and smooth >= 0.35:
        share = 0.35
    elif n >= 20 and smooth >= 0.18:
        share = 0.30
    elif n >= 30 and smooth <= 0.03:
        share = 0.12
    elif n >= 20 and smooth <= 0.10:
        share = 0.18
    else:
        share = 0.25
    return max(16, math.ceil(limit * share))


def sam_adjustment(rec: dict) -> tuple[int, list[str]]:
    portal = portal_key(rec)
    if portal not in SAM_PORTALS:
        return 0, []

    score = 0
    reasons: list[str] = []
    set_aside = _clean(rec.get("set_aside"))
    # Keep set-asides visible for partnering/subcontracting possibilities, but rank
    # them below unrestricted solicitations.
    if set_aside not in SAM_OPEN_SET_ASIDE_VALUES:
        score -= 34
        reasons.append("-34:us-set-aside-risk-not-hard-reject")

    notice_type = _clean(rec.get("type"))
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
        score -= 2
        reasons.append("-2:sam-no-direct-doc-route")
    return score, reasons


def retrieval_score(rec: dict, portal_performance: dict | None = None) -> tuple[int, list[str]]:
    eligible, _fit_class, fit_score, fit_reasons = business_fit(rec)
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
            score -= 8
            reasons.append("-8:very-large-value")

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
            score -= 16
            reasons.append("-16:deadline-too-close")
        elif days <= 30:
            score += 4
            reasons.append("+4:actionable-deadline")

    sam_delta, sam_reasons = sam_adjustment(rec)
    score += sam_delta
    reasons.extend(sam_reasons)

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
        "selection_reason": "HIGH_RECALL notice selection; authoritative DCE decides truth | " + ", ".join(reasons[:20]),
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
    explore_portal_cap = max(8, math.ceil(limit * EXPLORE_SHARE / 2))
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


def select(records: Iterable[dict], minimum: int = 0, limit: int = 640, blocked_ids: set[str] | None = None, portal_performance: dict | None = None) -> list[dict]:
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
        # Hard non-bid/current/expired states can push a row below zero. Ambiguous
        # business-fit rows stay eligible because minimum is normally zero.
        if score < minimum:
            continue
        all_scored.append((score, cid, reasons, rec, cid_key, tb_key, fit_class, fit_score))

    all_scored.sort(key=lambda x: (-x[0], -x[7], str(x[3].get("deadline") or "9999"), x[1]))
    exploit = []
    explore = []
    for item in all_scored:
        pkey = portal_key(item[3])
        n = int(performance_record(portal_performance, pkey).get("candidates") or 0)
        (exploit if n >= MIN_HISTORY_FOR_EXPLOIT else explore).append(item)

    out = []
    emitted_ids: set[str] = set()
    emitted_tb: set[tuple[str, str]] = set()
    counts: Counter[str] = Counter()
    explore_target_count = min(limit, max(1, round(limit * EXPLORE_SHARE)))
    exploit_target_count = max(0, limit - explore_target_count)

    _fill_ranked(exploit, out, emitted_ids, emitted_tb, counts, exploit_target_count, limit, portal_performance, "exploit")
    explore_absolute_target = min(limit, len(out) + explore_target_count)
    _fill_explore_round_robin(explore, out, emitted_ids, emitted_tb, counts, explore_absolute_target, limit, portal_performance)

    # Elastic fill comes only from the high-recall relevant pool. Relax portal share
    # before ever inventing non-fit candidates.
    _fill_ranked(all_scored, out, emitted_ids, emitted_tb, counts, limit, limit, portal_performance, "elastic-recall")
    if len(out) < limit:
        for relax_share in (0.40, 0.55, 0.70):
            for item in all_scored:
                if len(out) >= limit:
                    break
                pkey = portal_key(item[3])
                cap = max(portal_cap(limit, pkey, portal_performance), math.ceil(limit * relax_share))
                if counts[pkey] >= cap:
                    continue
                _emit(out, item, emitted_ids, emitted_tb, counts, "elastic-portal-relaxed-recall")
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
        "note": "Portal yield is only a retrieval tiebreaker inside a high-recall business-relevant pool.",
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--minimum", type=int, default=0)
    ap.add_argument("--limit", type=int, default=640)
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
    fit_results = [business_fit(rec) for rec in rows]
    total_fit = sum(1 for ok, _, _, _ in fit_results if ok)
    reject_counts = Counter(cls for ok, cls, _, _ in fit_results if not ok)

    summary = {
        "input": len(rows),
        "blocked_ids": len(blocked),
        "high_recall_business_pool": total_fit,
        "rejected_as_no_recall_signal_or_obvious_physical": len(rows) - total_fit,
        "reject_counts": dict(reject_counts),
        "selected": len(selected),
        "minimum": args.minimum,
        "limit": args.limit,
        "fit_policy": "Recall-first: ambiguous digital/IT/training/communications/portal work is retained for DCE reading. Only obvious non-bid or physical commodity noise is suppressed early.",
        "explore_share_target": EXPLORE_SHARE,
        "selection_fit_counts": fit_counts,
        "selection_portal_counts": portal_counts,
        "selection_bucket_counts": bucket_counts,
        "max_portal_share": round(max(portal_counts.values(), default=0) / max(1, len(selected)), 6),
        "history_run_ids": (performance.get("run_ids") or [])[-8:],
        "modeled_yield": modeled_expected(selected, performance),
    }
    out.with_suffix(out.suffix + ".summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
