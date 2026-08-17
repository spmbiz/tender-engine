from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ALLOWED = {"FINAL_SUPER_GREEN", "GREEN", "YELLOW", "RED"}


def load(path: Path) -> dict[str, Any]:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def key(row: dict[str, Any]) -> str:
    return str(row.get("candidate_id") or "").strip().casefold()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bank", default="control/final_supergreen_bank.json")
    ap.add_argument("--adjudications-dir", default="control/adjudications")
    args = ap.parse_args()

    bank_path = Path(args.bank)
    bank = load(bank_path)
    items = [x for x in bank.get("items", []) if isinstance(x, dict) and key(x)]
    by_id = {key(x): x for x in items}
    changed = 0

    for path in sorted(Path(args.adjudications_dir).glob("*.json")):
        adjud = load(path)
        if adjud.get("persist_to_final_bank") is not True:
            continue
        source_run = adjud.get("source_dce_run") or adjud.get("source_dce_run_id")
        adjudicated_at = adjud.get("created_at") or datetime.now(timezone.utc).isoformat()
        for result in adjud.get("results", []) or []:
            if not isinstance(result, dict) or not key(result):
                continue
            cls = str(result.get("classification") or result.get("verdict") or "").upper()
            if cls not in ALLOWED:
                continue
            new = {
                "candidate_id": result.get("candidate_id"),
                "title": result.get("title"),
                "buyer": result.get("buyer"),
                "deadline": result.get("deadline"),
                "classification": cls,
                "final_score": int(result.get("final_score") or result.get("score") or 0),
                "source_dce_run_id": int(source_run) if str(source_run or "").isdigit() else source_run,
                "adjudicated_at": adjudicated_at,
                "evidence_quality": result.get("evidence_quality") or "SUBSTANTIVE_DCE_PRESENT",
                "deadline_authority": result.get("deadline_authority") or "REVIEWED_BY_GPT_WEB",
                "mandatory_gate_statuses": result.get("mandatory_gate_statuses") or {},
                "blockers": result.get("blockers") or result.get("decisive_blockers") or [],
                "unknowns": result.get("unknowns") or result.get("remaining_risks") or [],
                "why": result.get("why") or "GPT Web adjudication persisted from authoritative DCE evidence.",
                "action": result.get("action") or "NO_ACTION",
                "notice_url": result.get("notice_url"),
            }
            old = by_id.get(key(new))
            if old == new:
                continue
            # Never degrade an existing richer FINAL_SUPER_GREEN/GREEN record with a
            # lower-classification adjudication for the same candidate.
            rank = {"FINAL_SUPER_GREEN": 4, "GREEN": 3, "YELLOW": 2, "RED": 1}
            if old and rank.get(str(old.get("classification") or "").upper(), 0) > rank[cls]:
                continue
            by_id[key(new)] = new
            changed += 1

    out = list(by_id.values())
    rank = {"FINAL_SUPER_GREEN": 4, "GREEN": 3, "YELLOW": 2, "RED": 1}
    out.sort(key=lambda r: (rank.get(str(r.get("classification") or "").upper(), 0), int(r.get("final_score") or 0)), reverse=True)
    bank["schema"] = bank.get("schema") or "GPT_FINAL_SUPERGREEN_BANK_V2"
    bank["updated_at"] = datetime.now(timezone.utc).isoformat()
    bank["items"] = out
    bank["contract"] = bank.get("contract") or "Only GPT Web may persist FINAL_SUPER_GREEN/GREEN/YELLOW/RED here after adjudicating authoritative DCE evidence. Missing evidence is UNKNOWN. Never infer SPM turnover, references, staff, insurance, certifications, licences, reseller status or geographic eligibility. Closed/expired opportunities must not be presented as live supergreens."
    bank_path.write_text(json.dumps(bank, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"merged": changed, "bank_items": len(out)}, indent=2))


if __name__ == "__main__":
    main()
