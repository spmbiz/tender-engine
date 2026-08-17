from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path

from dce_attempt_ledger import load_attempt_index, was_attempted

QWEN_STATUS = "AUTO_DCE_PREFETCH_QWEN"


def load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if not isinstance(obj, dict):
                raise ValueError(f"{path}:{line_no}: expected JSON object")
            rows.append(obj)
    return rows


def norm(value: object) -> str:
    s = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def canonical_candidate_id(value: object) -> str:
    """Normalize cross-stage candidate identity without changing stored IDs.

    Portal normalizers historically varied in source-prefix casing (for example
    UK_PCS_OCDS:... versus uk_pcs_ocds:...). Qwen/ledger identity is casefolded,
    so DCE materialization must use the same rule or semantically selected rows can
    disappear even though the exact canonical notice is present in the harvest.
    """
    return str(value or "").strip().casefold()


def identity(rec: dict) -> tuple[str, tuple[str, str] | None]:
    cid = canonical_candidate_id(rec.get("candidate_id"))
    title = norm(rec.get("title"))
    buyer = norm(rec.get("buyer"))
    return cid, ((title, buyer) if title and buyer else None)


def build_candidate_index(candidates: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for rec in candidates:
        cid = canonical_candidate_id(rec.get("candidate_id"))
        if cid and cid not in out:
            out[cid] = rec
    return out


def load_selection(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if text.startswith("{"):
        try:
            obj = json.loads(text)
        except json.JSONDecodeError:
            obj = None
        if isinstance(obj, dict) and isinstance(obj.get("candidate_ids"), list):
            default_score = min(89, int(obj.get("default_preliminary_score", 84)))
            default_status = str(obj.get("status") or "DCE_PENDING")
            default_run = obj.get("wide_read_run_id")
            default_reason = obj.get("selection_reason")
            out = []
            for cid in obj["candidate_ids"]:
                rec = {
                    "candidate_id": str(cid),
                    "preliminary_score": default_score,
                    "status": default_status,
                }
                if default_run is not None:
                    rec["wide_read_run_id"] = default_run
                if default_reason:
                    rec["selection_reason"] = default_reason
                out.append(rec)
            return out
    if path.suffix.lower() == ".json":
        obj = json.loads(text)
        if isinstance(obj, list):
            return [x if isinstance(x, dict) else {"candidate_id": str(x)} for x in obj]
    return load_jsonl(path)


def qwen_pre_admission(base: dict, sel: dict) -> tuple[bool, str]:
    """Honor the already-calibrated Qwen selection as DCE admission.

    The persisted Qwen queue is already bounded and deliberately mixes primary,
    elastic, exploration and reject-audit lanes. A second regex gate here used to
    discard/defer most of that shortlist, destroying recall and repeatedly feeding
    only a tiny subset to DCE. DCE resolution is the authoritative next gate.
    """
    if str(sel.get("status") or "").upper() != QWEN_STATUS:
        return True, "not_qwen_lane"
    return True, "qwen_selected_high_recall"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", required=True)
    ap.add_argument("--selection", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--exclude-queue", default="")
    ap.add_argument("--attempt-ledger", default="control/dce_attempt_ledger.jsonl")
    args = ap.parse_args()

    candidates = load_jsonl(Path(args.candidates))
    selection = load_selection(Path(args.selection))
    by_id = build_candidate_index(candidates)

    exclude_rows = load_jsonl(Path(args.exclude_queue)) if args.exclude_queue else []
    excluded_ids: set[str] = set()
    excluded_tb: set[tuple[str, str]] = set()
    for rec in exclude_rows:
        cid, tb = identity(rec)
        if cid:
            excluded_ids.add(cid)
        if tb:
            excluded_tb.add(tb)

    attempt_index = load_attempt_index(Path(args.attempt_ledger)) if args.attempt_ledger else {}

    selected: list[dict] = []
    missing: list[str] = []
    duplicate_selection: list[str] = []
    excluded_existing: list[str] = []
    excluded_attempted: list[str] = []
    excluded_qwen_pre_admission: list[dict] = []
    qwen_admission_reasons: dict[str, int] = {}
    seen: set[str] = set()
    seen_tb: set[tuple[str, str]] = set()

    for sel in selection:
        cid = str(sel.get("candidate_id") or "").strip()
        cid_key = canonical_candidate_id(cid)
        if not cid_key:
            continue
        if cid_key in seen:
            duplicate_selection.append(cid)
            continue
        seen.add(cid_key)

        base = by_id.get(cid_key)
        if not base:
            missing.append(cid)
            continue

        candidate_for_attempt = dict(base)
        for key in (
            "preliminary_score",
            "business_fit_score",
            "wide_read_run_id",
            "status",
            "selection_portal",
            "selection_reason",
            "selection_bucket",
            "selection_fit_class",
            "selection_freshness",
            "qwen",
        ):
            if key in sel:
                candidate_for_attempt[key] = sel[key]

        if was_attempted(candidate_for_attempt, attempt_index):
            excluded_attempted.append(cid)
            continue

        base_cid_key, tb_key = identity(base)
        if base_cid_key in excluded_ids or (tb_key and tb_key in excluded_tb):
            excluded_existing.append(cid)
            continue
        if tb_key and tb_key in seen_tb:
            duplicate_selection.append(cid)
            continue

        allowed, admission_reason = qwen_pre_admission(base, sel)
        qwen_admission_reasons[admission_reason] = qwen_admission_reasons.get(admission_reason, 0) + 1
        if not allowed:
            excluded_qwen_pre_admission.append({"candidate_id": cid, "reason": admission_reason})
            continue

        if tb_key:
            seen_tb.add(tb_key)

        rec = candidate_for_attempt
        rec["qwen_pre_admission_reason"] = admission_reason
        if int(rec.get("preliminary_score") or 0) > 89:
            raise SystemExit(f"Pre-DCE score exceeds 89 for {cid}")
        rec["selection_manifest_candidate_id"] = cid
        selected.append(rec)

    accounted = (
        len(selected)
        + len(missing)
        + len(excluded_existing)
        + len(excluded_attempted)
        + len(duplicate_selection)
        + len(excluded_qwen_pre_admission)
    )
    if accounted != len(selection):
        raise SystemExit(
            f"Coverage mismatch: selected={len(selected)} missing_snapshot={len(missing)} "
            f"existing={len(excluded_existing)} attempted={len(excluded_attempted)} "
            f"duplicates={len(duplicate_selection)} qwen_deferred={len(excluded_qwen_pre_admission)} "
            f"selection={len(selection)}"
        )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for rec in selected:
            f.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n")

    summary = {
        "canonical_candidate_pool": len(candidates),
        "selection_manifest_records": len(selection),
        "missing_from_source_snapshot_count": len(missing),
        "missing_from_source_snapshot_candidate_ids": missing,
        "excluded_as_existing_exact_identity": len(excluded_existing),
        "excluded_existing_candidate_ids": excluded_existing,
        "excluded_as_durable_attempt": len(excluded_attempted),
        "excluded_attempted_candidate_ids": excluded_attempted,
        "deduplicated_exact_identity_count": len(duplicate_selection),
        "deduplicated_candidate_ids": duplicate_selection,
        "qwen_pre_admission_deferred_count": len(excluded_qwen_pre_admission),
        "qwen_pre_admission_deferred": excluded_qwen_pre_admission,
        "qwen_pre_admission_reasons": qwen_admission_reasons,
        "materialized_queue_records": len(selected),
        "queue_exhausted": bool(selection) and not selected,
        "coverage_ok": accounted == len(selection),
        "max_preliminary_score": max((int(r.get("preliminary_score") or 0) for r in selected), default=0),
        "source_run_ids": sorted(
            {str(r.get("wide_read_run_id")) for r in selected if r.get("wide_read_run_id") is not None}
        ),
    }
    summary_path = out.with_suffix(out.suffix + ".summary.json")
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
