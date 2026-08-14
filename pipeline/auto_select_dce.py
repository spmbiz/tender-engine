from __future__ import annotations

import argparse
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

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

    if rec.get("seen_before"):
        score -= 80
        reasons.append("-80:seen-before")
    if rec.get("current") is False:
        score -= 100
        reasons.append("-100:not-current")
    return max(-100, min(100, score)), reasons


def select(records: Iterable[dict], minimum: int = 34, limit: int = 320, blocked_ids: set[str] | None = None) -> list[dict]:
    blocked_norm = {str(x).strip().casefold() for x in (blocked_ids or set()) if str(x).strip()}
    scored = []
    for rec in records:
        cid = str(rec.get("candidate_id") or "").strip()
        if not cid or cid.casefold() in blocked_norm:
            continue
        score, reasons = retrieval_score(rec)
        if score < minimum:
            continue
        scored.append((score, cid, reasons, rec))

    # A merged source harvest can legitimately contain duplicate source identities.
    # Rank with the full deterministic retrieval score, then keep one best record per
    # canonical ID. The exported preliminary score is deliberately capped at 89:
    # 90-100 belongs to the mandatory post-DCE/GPT evidence gate in this repository.
    scored.sort(key=lambda x: (-x[0], str(x[3].get("deadline") or "9999"), x[1]))
    out = []
    emitted: set[str] = set()
    for raw_score, cid, reasons, rec in scored:
        key = cid.casefold()
        if key in emitted:
            continue
        emitted.add(key)
        out.append({
            "candidate_id": cid,
            "preliminary_score": min(89, raw_score),
            "wide_read_run_id": rec.get("wide_read_run_id"),
            "status": "AUTO_DCE_PREFETCH",
            "selection_reason": "deterministic retrieval priority only; GPT final qualification still required | " + ", ".join(reasons[:8]),
        })
        if len(out) >= limit:
            break
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
    summary = {"input": len(rows), "blocked_ids": len(blocked), "selected": len(selected), "minimum": args.minimum, "limit": args.limit}
    out.with_suffix(out.suffix + ".summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
