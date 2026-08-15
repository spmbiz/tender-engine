from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path


DECISIVE = (
    "turnover_financial",
    "references_experience",
    "insurance",
    "team_cvs",
    "certifications",
    "onsite_geography",
    "subcontracting_consortium",
    "hosting_security_data",
)


def clean(value: object, limit: int) -> str:
    s = re.sub(r"\s+", " ", str(value or "")).strip().replace("|", "/")
    return s if len(s) <= limit else s[: max(0, limit - 1)] + "…"


def load_jsonl(path: Path) -> list[dict]:
    out = []
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def triage_score(row: dict) -> float:
    if row.get("status") != "DOWNLOADED_PUBLIC" or row.get("content_quality") != "SUBSTANTIVE_FILE_PRESENT":
        return -10_000.0
    score = float(row.get("preliminary_score") or 0)
    counts = row.get("gate_evidence_counts") or {}
    weights = {
        "turnover_financial": 5.0,
        "references_experience": 3.5,
        "insurance": 2.0,
        "team_cvs": 3.0,
        "certifications": 4.0,
        "onsite_geography": 3.0,
        "hosting_security_data": 1.5,
    }
    for key, weight in weights.items():
        score -= weight * math.log1p(max(0, int(counts.get(key) or 0)))
    try:
        value = float(row.get("estimated_value") or 0)
    except Exception:
        value = 0
    if 0 < value <= 250_000:
        score += 7
    elif 0 < value <= 750_000:
        score += 3
    docs = int(row.get("documents_extracted") or 0)
    if 0 < docs <= 15:
        score += 3
    elif docs >= 100:
        score -= 3
    return score


def first_snippets(row: dict, category: str, max_items: int = 1, max_chars: int = 520) -> list[str]:
    cats = row.get("gate_snippets") or {}
    items = cats.get(category) or []
    out = []
    for item in items[:max_items]:
        if not isinstance(item, dict):
            continue
        snip = clean(item.get("snippet"), max_chars)
        if snip:
            out.append(snip)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--queue", default="dce-aggregate/deep_review_queue.jsonl")
    ap.add_argument("--summary", default="dce-aggregate/summary.json")
    ap.add_argument("--out", default="dce-aggregate/gpt_release_notes.md")
    ap.add_argument("--top", type=int, default=80)
    ap.add_argument("--evidence-top", type=int, default=12)
    ap.add_argument("--max-chars", type=int, default=120000)
    args = ap.parse_args()

    rows = load_jsonl(Path(args.queue))
    try:
        summary = json.loads(Path(args.summary).read_text(encoding="utf-8"))
    except Exception:
        summary = {}
    ranked = sorted(rows, key=lambda r: (-triage_score(r), str(r.get("deadline") or "9999"), str(r.get("candidate_id") or "")))

    lines = [
        "# GPT DCE Handoff",
        "",
        "This is a reconstructible compact review index. It is NOT an eligibility verdict. Zero keyword hits do not prove a gate is absent. FINAL_SUPER_GREEN still requires full authoritative DCE reading and explicit mandatory-gate resolution.",
        "",
        "## Batch summary",
        "",
        "```json",
        json.dumps(summary, ensure_ascii=False, separators=(",", ":")),
        "```",
        "",
        "## Priority review index",
        "",
        "`triage` is only a retrieval-review ordering score; it is not a final tender score.",
        "",
    ]

    for row in ranked[: max(1, args.top)]:
        counts = row.get("gate_evidence_counts") or {}
        count_str = ",".join(f"{k}={int(counts.get(k) or 0)}" for k in DECISIVE)
        value = row.get("estimated_value")
        currency = row.get("currency") or ""
        lines.append(
            f"- **{clean(row.get('candidate_id'), 60)}** | triage={triage_score(row):.1f} | prelim={row.get('preliminary_score')} | "
            f"status={clean(row.get('status'), 35)} | docs={int(row.get('documents_extracted') or 0)} | corpus={int(row.get('corpus_chars') or 0)} chars | "
            f"value={value} {currency} | deadline={clean(row.get('deadline'), 35)} | **{clean(row.get('title'), 180)}** | buyer={clean(row.get('buyer'), 100)} | gates[{count_str}] | notice={clean(row.get('notice_url'), 300)}"
        )

    lines += ["", "## Evidence preview for top candidates", ""]
    for row in ranked[: max(1, args.evidence_top)]:
        lines.append(f"### {clean(row.get('candidate_id'), 70)} — {clean(row.get('title'), 180)}")
        lines.append(f"Notice: {clean(row.get('notice_url'), 350)}")
        emitted = False
        for cat in DECISIVE:
            snippets = first_snippets(row, cat, max_items=1)
            for snip in snippets:
                emitted = True
                lines.append(f"- **{cat}**: {snip}")
        if not emitted:
            lines.append("- No decisive-category keyword snippets extracted; this means UNKNOWN, not PASS.")
        lines.append("")

    text = "\n".join(lines)
    if len(text) > args.max_chars:
        text = text[: args.max_chars - 200] + "\n\n[TRUNCATED TO RELEASE-NOTE SIZE BUDGET]\n"
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(json.dumps({"rows": len(rows), "ranked": min(len(ranked), args.top), "chars": len(text), "out": str(out)}, indent=2))


if __name__ == "__main__":
    main()
