from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

LEAN_TERMS = {
    "website": 20, "web site": 20, "cms": 22, "web portal": 20, "portal": 8,
    "hosting": 10, "maintenance": 7, "seo": 15,
    "graphic design": 20, "branding": 18, "creative": 16,
    "video": 18, "animation": 17, "audiovisual": 14,
    "marketing": 15, "social media": 17, "communications": 10,
    "content": 10, "editorial": 14, "publication": 8, "copywriting": 18,
    "translation": 13, "transcription": 18, "interpreting": 6,
    "print": 11, "printing": 13, "brochure": 12,
    "software": 10, "application": 8, "automation": 15, "data": 6,
    "artificial intelligence": 18, " ai ": 10, "digital": 7,
}
HARD_SCOPE_RED = {
    "construction": 22, "civil works": 28, "road works": 30, "roofing": 24,
    "pharmaceutical": 30, "medical equipment": 25, "clinical": 20,
    "security guard": 24, "catering": 20, "cleaning services": 20,
    "vehicle supply": 18, "firearms": 100, "ammunition": 100,
}


def load_jsonl(path: Path):
    rows = []
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                x = json.loads(line)
            except Exception:
                continue
            if isinstance(x, dict):
                rows.append(x)
    return rows


def parse_deadline(v):
    if not v:
        return None
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
    except Exception:
        return None


def priority(row: dict):
    text = " " + re.sub(r"\s+", " ", " ".join(str(row.get(k) or "") for k in ("title", "buyer"))).lower() + " "
    score = int(row.get("preliminary_score") or 0)
    reasons = []
    for term, pts in LEAN_TERMS.items():
        if term in text:
            score += pts
            reasons.append(f"+{pts}:{term.strip()}")
    for term, pts in HARD_SCOPE_RED.items():
        if term in text:
            score -= pts
            reasons.append(f"-{pts}:{term}")
    chars = int(row.get("corpus_chars") or 0)
    docs = int(row.get("documents_extracted") or 0)
    if chars >= 100_000:
        score += 8; reasons.append("+8:rich-dce-corpus")
    elif chars >= 25_000:
        score += 4; reasons.append("+4:substantive-dce-corpus")
    if docs >= 3:
        score += 4; reasons.append("+4:multi-document-dce")
    counts = row.get("gate_evidence_counts") or {}
    covered = sum(1 for v in counts.values() if int(v or 0) > 0)
    score += min(10, covered)
    if covered:
        reasons.append(f"+{min(10,covered)}:gate-evidence-coverage-{covered}")
    return score, reasons


def compact(row: dict, rank_score: int, reasons: list[str]):
    return {
        "candidate_id": row.get("candidate_id"),
        "title": row.get("title"),
        "buyer": row.get("buyer"),
        "portal": row.get("portal"),
        "deadline": row.get("deadline"),
        "estimated_value": row.get("estimated_value"),
        "currency": row.get("currency"),
        "notice_url": row.get("notice_url"),
        "preliminary_score": row.get("preliminary_score"),
        "gpt_review_priority": rank_score,
        "priority_reasons": reasons[:20],
        "gate_readiness": bool(row.get("gate_readiness")),
        "content_quality": row.get("content_quality"),
        "deadline_conflict": bool(row.get("deadline_conflict")),
        "deadline_authority_status": row.get("deadline_authority_status"),
        "documents_extracted": row.get("documents_extracted"),
        "corpus_chars": row.get("corpus_chars"),
        "gate_evidence_counts": row.get("gate_evidence_counts") or {},
        "gate_snippets": row.get("gate_snippets") or {},
        "review_template": row.get("review_template") or {},
        "files": row.get("files") or [],
        "authority_conflicts": row.get("authority_conflicts") or {},
        "artifact_relative_root": row.get("artifact_relative_root"),
        "finalization_allowed": False,
        "classification_contract": (
            "This row is SUPERGREEN_READY_FOR_GPT_REVIEW, not a final Supergreen. "
            "GPT must adjudicate every mandatory gate from authoritative DCE evidence. "
            "FINAL_SUPER_GREEN/90+ remains forbidden if any potentially disqualifying gate is UNKNOWN/FAIL or lacks evidence."
        ),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="dce-aggregate/deep_review_queue.jsonl")
    ap.add_argument("--summary", default="dce-aggregate/summary.json")
    ap.add_argument("--out", default="dce-aggregate/supergreen-ready")
    ap.add_argument("--limit", type=int, default=200)
    args = ap.parse_args()
    src = Path(args.input)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    ready = []
    blocked = []
    for row in load_jsonl(src):
        dl = parse_deadline(row.get("deadline"))
        current = dl is None or dl >= now
        gate_ready = bool(row.get("gate_readiness"))
        conflict = bool(row.get("deadline_conflict"))
        if not gate_ready or not current or conflict:
            blocked.append({
                "candidate_id": row.get("candidate_id"),
                "title": row.get("title"),
                "portal": row.get("portal"),
                "deadline": row.get("deadline"),
                "reason": "not_gate_ready" if not gate_ready else ("expired" if not current else "deadline_conflict"),
                "status": row.get("status"),
                "content_quality": row.get("content_quality"),
            })
            continue
        s, reasons = priority(row)
        ready.append(compact(row, s, reasons))
    ready.sort(key=lambda r: (-int(r.get("gpt_review_priority") or 0), str(r.get("deadline") or "9999"), str(r.get("candidate_id") or "")))
    ready = ready[: max(1, args.limit)]
    with (out / "supergreen_ready.jsonl").open("w", encoding="utf-8") as f:
        for r in ready:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with (out / "blocked_from_supergreen_review.jsonl").open("w", encoding="utf-8") as f:
        for r in blocked:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    by_portal = Counter(str(r.get("portal") or "UNKNOWN") for r in ready)
    payload = {
        "contract": "GPT_SUPERGREEN_READY_PACK_V1",
        "generated_at": now.isoformat(),
        "ready_rows": len(ready),
        "blocked_rows": len(blocked),
        "portal_counts": dict(by_portal),
        "source_summary_path": args.summary,
        "instruction": (
            "Analyze supergreen_ready.jsonl from top to bottom. For each candidate, use gate_snippets/review_template and, when needed, "
            "the corresponding DCE corpus/files in the canonical DCE release. Resolve all 14 mandatory gates. Return FINAL_SUPER_GREEN only "
            "when all potentially disqualifying gates are evidenced PASS/PASS_CONDITIONAL with an honest fulfilment plan. Otherwise classify "
            "GREEN_PARTNERABLE, DCE_PENDING/UNKNOWN, or RED. Do not infer PASS from silence."
        ),
    }
    (out / "manifest.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "ANALYZE_ME.md").write_text(
        "# Latest Supergreen-ready DCE review pack\n\n"
        f"Ready candidates: **{len(ready)}**\n\n"
        "Start with `supergreen_ready.jsonl`. These candidates already have substantive authoritative DCE material and no known deadline conflict. "
        "They are prioritized for lean SPM fulfilment but are **not pre-declared Supergreens**. Adjudicate every mandatory gate from evidence. "
        "For the final answer, lead with genuine FINAL_SUPER_GREEN opportunities, then partnerable candidates, then blockers. Include exact deadline, value, buyer, DCE/gate evidence, and why SPM can actually ship it.\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
