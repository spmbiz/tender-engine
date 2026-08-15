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


def parse_deadline(v):
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except Exception:
        return None


def portal_key(rec: dict) -> str:
    return str(rec.get("portal") or rec.get("source") or "UNKNOWN").strip().upper() or "UNKNOWN"


def sam_adjustment(rec: dict) -> tuple[int, list[str]]:
    """Prevent US SAM discovery volume from masquerading as Belgian-bid eligibility.

    The official bulk feed is useful for discovery, but many rows are US small-business
    set-asides or non-bid notices and the SAM web UI commonly gates attachments behind
    authentication. Penalize those before they consume expensive DCE fanout slots.
    """
    portal = portal_key(rec)
    if portal not in {"US_SAM", "US_SAM_BULK"}:
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


def retrieval_score(rec: dict) -> tuple[int, list[str]]:
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

    if rec.get("seen_before"):
        score -= 80
        reasons.append("-80:seen-before")
    if rec.get("current") is False:
        score -= 100
        reasons.append("-100:not-current")
    return max(-100, min(100, score)), reasons


def _emit(out, item, emitted_ids, emitted_tb, counts):
    raw_score, cid, reasons, rec, cid_key, tb_key = item
    if cid_key in emitted_ids or (tb_key and tb_key in emitted_tb):
        return False
    emitted_ids.add(cid_key)
    if tb_key:
        emitted_tb.add(tb_key)
    pkey = portal_key(rec)
    counts[pkey] += 1
    out.append({
        "candidate_id": cid,
        "preliminary_score": min(89, raw_score),
        "wide_read_run_id": rec.get("wide_read_run_id"),
        "status": "AUTO_DCE_PREFETCH",
        "selection_portal": pkey,
        "selection_reason": "deterministic retrieval priority only; GPT final qualification still required | " + ", ".join(reasons[:12]),
    })
    return True


def select(records: Iterable[dict], minimum: int = 34, limit: int = 320, blocked_ids: set[str] | None = None) -> list[dict]:
    rows = list(records)
    blocked_norm = {str(x).strip().casefold() for x in (blocked_ids or set()) if str(x).strip()}
    blocked_tb: set[tuple[str, str]] = set()
    for rec in rows:
        cid_key, tb_key = identity(rec)
        if cid_key in blocked_norm and tb_key:
            blocked_tb.add(tb_key)

    scored = []
    for rec in rows:
        cid = str(rec.get("candidate_id") or "").strip()
        cid_key, tb_key = identity(rec)
        if not cid or cid_key in blocked_norm or (tb_key and tb_key in blocked_tb):
            continue
        score, reasons = retrieval_score(rec)
        if score < minimum:
            continue
        scored.append((score, cid, reasons, rec, cid_key, tb_key))

    # Use exact materialization identity semantics, but do not let one giant source
    # monopolize an expensive 320-candidate DCE wave. First pass applies a soft
    # source cap; second pass fills remaining capacity round-robin from portal
    # overflow. This preserves throughput while materially increasing world coverage.
    scored.sort(key=lambda x: (-x[0], str(x[3].get("deadline") or "9999"), x[1]))
    default_cap = max(24, math.ceil(limit * 0.25))
    special_caps = {"US_SAM": max(24, math.ceil(limit * 0.125)), "US_SAM_BULK": max(24, math.ceil(limit * 0.125))}

    out = []
    emitted_ids: set[str] = set()
    emitted_tb: set[tuple[str, str]] = set()
    counts: Counter[str] = Counter()
    overflow: dict[str, list] = defaultdict(list)

    for item in scored:
        pkey = portal_key(item[3])
        cap = special_caps.get(pkey, default_cap)
        if counts[pkey] >= cap:
            overflow[pkey].append(item)
            continue
        _emit(out, item, emitted_ids, emitted_tb, counts)
        if len(out) >= limit:
            return out

    # Fill any remaining capacity fairly. Highest score still matters within a
    # portal, but each active portal gets one turn before any gets a second.
    active = [p for p, items in overflow.items() if items]
    active.sort(key=lambda p: (-overflow[p][0][0], p))
    while active and len(out) < limit:
        next_active = []
        for pkey in active:
            items = overflow[pkey]
            while items:
                item = items.pop(0)
                if _emit(out, item, emitted_ids, emitted_tb, counts):
                    break
            if items:
                next_active.append(pkey)
            if len(out) >= limit:
                break
        active = next_active

    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--minimum", type=int, default=34)
    ap.add_argument("--limit", type=int, default=320)
    ap.add_argument("--blocked", action="append", default=[])
    args = ap.parse_args()

    blocked = set()
    for p in args.blocked:
        for rec in load_jsonl(Path(p)):
            cid = str(rec.get("candidate_id") or "").strip()
            if cid:
                blocked.add(cid)
    rows = list(load_jsonl(Path(args.input)))
    selected = select(rows, minimum=args.minimum, limit=args.limit, blocked_ids=blocked)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for rec in selected:
            f.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n")
    portal_counts = dict(Counter(str(x.get("selection_portal") or "UNKNOWN") for x in selected))
    summary = {
        "input": len(rows),
        "blocked_ids": len(blocked),
        "selected": len(selected),
        "minimum": args.minimum,
        "limit": args.limit,
        "selection_portal_counts": portal_counts,
        "max_portal_share": round(max(portal_counts.values(), default=0) / max(1, len(selected)), 6),
    }
    out.with_suffix(out.suffix + ".summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
