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

POSITIVE = {
    "website": 38, "web site": 38, "web portal": 35, "portal": 20, "cms": 30,
    "digital": 15, "seo": 28, "hosting": 20, "maintenance": 14,
    "graphic design": 36, "design services": 28, "creative": 30, "branding": 30,
    "video": 34, "animation": 32, "audiovisual": 26, "audio visual": 26,
    "marketing": 28, "campaign": 24, "communications": 22, "social media": 28,
    "content": 18, "editorial": 22, "publication": 16,
    "print": 26, "printing": 30, "brochure": 26, "leaflet": 26,
    "transcription": 30, "translation": 20,
    "software": 18, "application": 13, "app development": 30,
    "data": 10, "automation": 22, "artificial intelligence": 28, " ai ": 18,
}

NEGATIVE = {
    "construction": 35, "civil works": 40, "road works": 40, "roof": 30,
    "medical equipment": 35, "pharmaceutical": 40, "clinical": 25,
    "legal services": 25, "audit services": 20, "security guard": 30,
    "cleaning": 30, "catering": 30, "food supply": 30, "vehicle": 25,
    "firearms": 100, "ammunition": 100, "weapon": 100,
}

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


def history_adjustment(rec: dict, portal_performance: dict | None) -> tuple[int, list[str]]:
    """Bounded rolling source-yield adjustment; never an eligibility score."""
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

    # Small samples can inform exploration ordering but cannot swing retrieval score hard.
    scale = 0.35 if n < MIN_HISTORY_FOR_EXPLOIT else 1.0
    if smooth >= 0.45:
        base = 22
    elif smooth >= 0.20:
        base = 14
    elif smooth >= 0.12:
        base = 7
    elif smooth <= 0.03:
        base = -22
    elif smooth <= 0.06:
        base = -14
    elif smooth <= 0.10:
        base = -7
    else:
        base = 0
    yield_delta = int(round(base * scale))
    delta += yield_delta
    if yield_delta:
        reasons.append(f"{yield_delta:+d}:rolling-portal-yield")

    if n >= MIN_HISTORY_FOR_EXPLOIT:
        if auth >= 0.75:
            delta -= 14
            reasons.append("-14:rolling-auth-rate")
        elif auth >= 0.45:
            delta -= 7
            reasons.append("-7:rolling-auth-rate")
        if generic >= 0.80:
            delta -= 10
            reasons.append("-10:rolling-generic-rate")
        elif generic >= 0.60:
            delta -= 5
            reasons.append("-5:rolling-generic-rate")

    return max(-30, min(24, delta)), reasons


def portal_cap(limit: int, pkey: str, portal_performance: dict | None) -> int:
    """Progressively move capacity to proven routes while preserving diversity."""
    if pkey in SAM_PORTALS:
        return max(16, math.ceil(limit * 0.125))
    hist = performance_record(portal_performance, pkey)
    n = int(hist.get("candidates") or 0)
    smooth = float(hist.get("smoothed_useful_rate") or 0.0)
    if n >= 80 and smooth >= 0.35:
        share = 0.45
    elif n >= 20 and smooth >= 0.18:
        share = 0.30
    elif n >= 30 and smooth <= 0.03:
        share = 0.10
    elif n >= 20 and smooth <= 0.10:
        share = 0.15
    else:
        share = 0.25
    return max(12, math.ceil(limit * share))


def sam_adjustment(rec: dict) -> tuple[int, list[str]]:
    portal = portal_key(rec)
    if portal not in SAM_PORTALS:
        return 0, []

    score = 0
    reasons = []
    set_aside = re.sub(r"\s+", " ", str(rec.get("set_aside") or "").strip()).casefold()
    if set_aside not in SAM_OPEN_SET_ASIDE_VALUES:
        score -= 85
        reasons.append("-85:us-set-aside")

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
            score += 10
            reasons.append("+10:sam-live-solicitation")

    route = rec.get("route") or {}
    direct_docs = [u for u in (route.get("document_urls") or []) if isinstance(u, str) and u.startswith(("http://", "https://"))]
    if direct_docs:
        score += 20
        reasons.append("+20:sam-direct-public-doc-route")
    else:
        score -= 14
        reasons.append("-14:sam-no-direct-doc-route")
    return score, reasons


def retrieval_score(rec: dict, portal_performance: dict | None = None) -> tuple[int, list[str]]:
    text = " " + re.sub(r"\s+", " ", " ".join(str(rec.get(k) or "") for k in ("title", "description", "buyer"))).lower() + " "
    score = 0
    reasons = []
    for term, pts in POSITIVE.items():
        if term in text:
            score += pts
            reasons.append(f"+{pts}:{term.strip()}")
    for term, pts in NEGATIVE.items():
        if term in text:
            score -= pts
            reasons.append(f"-{pts}:{term}")

    value = rec.get("estimated_value")
    try:
        value = float(value) if value not in (None, "") else None
    except Exception:
        value = None
    if value is not None and value > 0:
        if value <= 250_000:
            score += 10
            reasons.append("+10:lean-value-band")
        elif value <= 750_000:
            score += 5
            reasons.append("+5:moderate-value-band")
        elif value >= 5_000_000:
            score -= 8
            reasons.append("-8:very-large-value")
        score += min(6, int(math.log10(max(value, 1))))

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
            score -= 18
            reasons.append("-18:deadline-too-close")
        elif days <= 30:
            score += 6
            reasons.append("+6:actionable-deadline")

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
    score, cid, reasons, rec, cid_key, tb_key = item
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
        "wide_read_run_id": rec.get("wide_read_run_id"),
        "status": "AUTO_DCE_PREFETCH",
        "selection_portal": pkey,
        "selection_bucket": bucket,
        "selection_reason": "deterministic retrieval priority only; GPT final qualification still required | " + ", ".join(reasons[:16]),
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
    # No one under-observed portal gets more than half the exploration budget.
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
        score, reasons = retrieval_score(rec, portal_performance=portal_performance)
        all_scored.append((score, cid, reasons, rec, cid_key, tb_key))

    all_scored.sort(key=lambda x: (-x[0], str(x[3].get("deadline") or "9999"), x[1]))
    recall_floor = max(0, minimum - 24)
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

    # Fill residual capacity by best adjusted score across both pools, still obeying
    # dynamic per-portal caps. Then relax non-SAM caps only if otherwise unable to
    # reach the requested batch size; SAM's 12.5% hard cap never relaxes.
    _fill_ranked(eligible, out, emitted_ids, emitted_tb, counts, limit, limit, portal_performance, "elastic-fill")
    if len(out) < limit:
        for relax_share in (0.55, 0.70):
            for item in eligible:
                if len(out) >= limit:
                    break
                pkey = portal_key(item[3])
                cap = portal_cap(limit, pkey, portal_performance) if pkey in SAM_PORTALS else max(portal_cap(limit, pkey, portal_performance), math.ceil(limit * relax_share))
                if counts[pkey] >= cap:
                    continue
                _emit(out, item, emitted_ids, emitted_tb, counts, "elastic-relaxed")
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
        by_portal[portal] = {"selected": count, "history_n": n, "smoothed_useful_rate": round(rate, 6), "modeled_useful": round(modeled, 3)}
    return {
        "modeled_expected_useful": round(expected, 3),
        "modeled_expected_useful_rate": round(expected / max(1, len(selected)), 6),
        "selected_with_history": known,
        "by_portal": by_portal,
        "note": "Modeled from bounded rolling retrieval history with a 0.20 prior for unseen routes; not a realized outcome.",
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
    sam_count = sum(portal_counts.get(p, 0) for p in SAM_PORTALS)
    sam_cap = max(16, math.ceil(args.limit * 0.125))
    summary = {
        "input": len(rows),
        "blocked_ids": len(blocked),
        "selected": len(selected),
        "minimum": args.minimum,
        "recall_floor": max(0, args.minimum - 24),
        "limit": args.limit,
        "explore_share_target": EXPLORE_SHARE,
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
