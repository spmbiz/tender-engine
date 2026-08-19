from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def iter_jsonl(path: Path):
    if not path.exists():
        return
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line_no, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception as exc:
                raise RuntimeError(f"INVALID_JSONL {path}:{line_no}: {exc!r}") from exc
            if isinstance(row, dict):
                yield row


def write_jsonl(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def authoritative_identities(row: dict[str, Any]) -> tuple[set[str], set[str]]:
    route = row.get("route") if isinstance(row.get("route"), dict) else {}
    ocids = {
        clean(row.get("ocid")),
        clean(row.get("procedure_id")),
        clean(route.get("ocid")),
    }
    refs = {
        clean(row.get("reference")),
        clean(route.get("reference")),
        clean(row.get("notice_id")),
    }
    ocids.discard("")
    refs.discard("")
    return ocids, refs


def build_identity_index(rows: list[dict[str, Any]]) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    ocid_index: dict[str, set[str]] = {}
    ref_index: dict[str, set[str]] = {}
    for row in rows:
        candidate_id = clean(row.get("candidate_id"))
        if not candidate_id:
            continue
        ocids, refs = authoritative_identities(row)
        for value in ocids:
            ocid_index.setdefault(value, set()).add(candidate_id)
        for value in refs:
            ref_index.setdefault(value, set()).add(candidate_id)
    return ocid_index, ref_index


def deterministic_match(
    direct_row: dict[str, Any],
    bulk_ocids: dict[str, set[str]],
    bulk_refs: dict[str, set[str]],
) -> tuple[str | None, list[str]]:
    ocids, refs = authoritative_identities(direct_row)
    for ocid in sorted(ocids):
        matches = sorted(bulk_ocids.get(ocid) or [])
        if matches:
            return f"OCID:{ocid}", matches
    for ref in sorted(refs):
        matches = sorted(bulk_refs.get(ref) or [])
        if matches:
            return f"REFERENCE:{ref}", matches
    return None, []


def bulk_publication_contract_complete(stats: dict[str, Any]) -> bool:
    if stats.get("publication_window_enumeration_complete") is not True:
        return False
    if stats.get("errors"):
        return False
    expected = stats.get("requests_expected")
    completed = stats.get("requests_completed")
    if expected is not None and completed is not None:
        try:
            if int(expected) != int(completed):
                return False
        except Exception:
            return False
    notice_types = []
    for value in stats.get("notice_types") or []:
        try:
            notice_types.append(int(value))
        except Exception:
            continue
    return 101 in notice_types


def direct_current_contract_complete(stats: dict[str, Any], row_count: int) -> bool:
    if stats.get("enumeration_complete") is not True:
        return False
    if stats.get("errors"):
        return False
    if stats.get("filtered_current_search_proven") is not True and stats.get("direct_filtered_post_proven") is not True:
        return False
    if stats.get("count_matches_official_total") is not True:
        return False
    total = stats.get("total_reported")
    if total is None:
        return False
    try:
        return row_count >= int(total)
    except Exception:
        return False


def reconcile(bulk_dir: Path, direct_dir: Path) -> dict[str, Any]:
    bulk_stats_path = bulk_dir / "stats.json"
    direct_stats_path = direct_dir / "stats.json"
    bulk_stats = read_json(bulk_stats_path)
    direct_stats = read_json(direct_stats_path)
    bulk_rows = list(iter_jsonl(bulk_dir / "current.jsonl"))
    direct_rows = list(iter_jsonl(direct_dir / "current.jsonl"))

    bulk_ocids, bulk_refs = build_identity_index(bulk_rows)
    matches: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    missing_rows: list[dict[str, Any]] = []

    for row in direct_rows:
        evidence, candidate_ids = deterministic_match(row, bulk_ocids, bulk_refs)
        direct_id = clean(row.get("candidate_id")) or None
        direct_ocids, direct_refs = authoritative_identities(row)
        if evidence:
            matches.append({
                "direct_candidate_id": direct_id,
                "match_evidence": evidence,
                "bulk_candidate_ids": candidate_ids,
            })
        else:
            missing.append({
                "direct_candidate_id": direct_id,
                "ocids": sorted(direct_ocids),
                "references": sorted(direct_refs),
                "title": clean(row.get("title")) or None,
                "buyer": clean(row.get("buyer")) or None,
                "deadline": row.get("deadline"),
            })
            supplemental = dict(row)
            supplemental["currentness_evidence"] = "PCS_OFFICIAL_CURRENT_OPPORTUNITY_DIRECT_RECONCILE_SUPPLEMENT"
            route = dict(supplemental.get("route") or {})
            route["reconciliation_origin"] = "PCS_CURRENT_OPPORTUNITIES_DIRECT_ASPNET_POST"
            supplemental["route"] = route
            missing_rows.append(supplemental)

    bulk_complete = bulk_publication_contract_complete(bulk_stats)
    direct_complete = direct_current_contract_complete(direct_stats, len(direct_rows))
    all_current_matched_to_bulk = direct_complete and not missing
    complete = bool(bulk_complete and all_current_matched_to_bulk)

    # Do not discard authoritative direct-only current opportunities even when the
    # bulk recall proof fails. They remain available to downstream discovery, while
    # coverage stays fail-closed until the bulk itself contains every official
    # Current Opportunity through an exact identity.
    final_rows = list(bulk_rows)
    known_ids = {clean(x.get("candidate_id")) for x in final_rows if clean(x.get("candidate_id"))}
    for row in missing_rows:
        cid = clean(row.get("candidate_id"))
        if cid and cid not in known_ids:
            final_rows.append(row)
            known_ids.add(cid)
    final_rows.sort(key=lambda x: (str(x.get("deadline") or "9999"), clean(x.get("candidate_id"))))
    write_jsonl(bulk_dir / "current.jsonl", final_rows)
    write_jsonl(bulk_dir / "raw.jsonl", final_rows)

    proof_dir = bulk_dir / "reconciliation"
    proof_dir.mkdir(parents=True, exist_ok=True)
    if missing_rows:
        write_jsonl(proof_dir / "direct_current_missing_from_bulk.jsonl", missing_rows)
    else:
        write_jsonl(proof_dir / "direct_current_missing_from_bulk.jsonl", [])
    # Preserve the official direct current registry as evidence, even when it is
    # fully matched, so the coverage claim is reconstructible from the Release.
    write_jsonl(proof_dir / "direct_current.jsonl", direct_rows)
    (proof_dir / "direct_stats.json").write_text(
        json.dumps(direct_stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    direct_total = direct_stats.get("total_reported")
    recall_ratio = (len(matches) / len(direct_rows)) if direct_rows else 0.0
    proof = {
        "schema": "PCS_BULK_CURRENT_UNIVERSE_RECONCILIATION_V1",
        "bulk_publication_contract_complete": bulk_complete,
        "direct_current_contract_complete": direct_complete,
        "direct_official_total_reported": direct_total,
        "direct_current_rows": len(direct_rows),
        "bulk_current_rows_before_reconcile": len(bulk_rows),
        "exact_matched_direct_rows": len(matches),
        "direct_missing_from_bulk": len(missing),
        "bulk_recall_against_official_current": recall_ratio,
        "all_official_current_matched_to_bulk": all_current_matched_to_bulk,
        "final_current_rows_after_supplement": len(final_rows),
        "coverage_complete": complete,
        "missing": missing,
        "match_sample": matches[:100],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "semantics": "Independent exact-identity reconciliation between the official PCS Current Opportunity registry and the official PCS monthly OCDS bulk. OCID is preferred, exact reference is fallback, and fuzzy matching is forbidden. Direct-only official current rows are preserved as supplemental candidates but do not grant full coverage credit: every official current row must already be represented in the bulk, and both enumeration contracts must be complete.",
    }
    (proof_dir / "summary.json").write_text(
        json.dumps(proof, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    old_listing = bulk_stats.get("listing_contract")
    bulk_stats["publication_bulk_listing_contract"] = old_listing
    bulk_stats["listing_contract"] = "PCS_OFFICIAL_MONTH_TYPE_BULK_OCDS_V4_DIRECT_CURRENT_RECONCILED"
    bulk_stats["bulk_current_materialized_before_reconcile"] = len(bulk_rows)
    bulk_stats["current_materialized"] = len(final_rows)
    bulk_stats["current_universe_reconciliation"] = {
        "contract": proof["schema"],
        "direct_official_total_reported": direct_total,
        "direct_current_rows": len(direct_rows),
        "exact_matched_direct_rows": len(matches),
        "direct_missing_from_bulk": len(missing),
        "bulk_recall_against_official_current": recall_ratio,
        "all_official_current_matched_to_bulk": all_current_matched_to_bulk,
        "direct_current_contract_complete": direct_complete,
        "coverage_complete": complete,
    }
    bulk_stats["enumeration_exhausted"] = complete
    bulk_stats["enumeration_complete"] = complete
    bulk_stats["live_candidate_capable"] = bool(final_rows)
    bulk_stats["live_coverage_credit_allowed"] = complete and bool(final_rows)
    warnings = list(bulk_stats.get("warnings") or [])
    warnings = [w for w in warnings if not (isinstance(w, dict) and w.get("type") == "CURRENT_UNIVERSE_RECONCILIATION_PENDING")]
    if not complete:
        warnings.append({
            "type": "CURRENT_UNIVERSE_RECONCILIATION_INCOMPLETE",
            "direct_contract_complete": direct_complete,
            "bulk_publication_contract_complete": bulk_complete,
            "direct_missing_from_bulk": len(missing),
        })
    bulk_stats["warnings"] = warnings
    bulk_stats["generated_at"] = datetime.now(timezone.utc).isoformat()
    bulk_stats["semantics"] = "Official PCS monthly OCDS bulk plus independent official Current Opportunity reconciliation. Publication partitions and notice type 101 must be complete; the direct Current Opportunity universe must itself prove filtered page exhaustion and official count reconciliation; and every direct current row must exact-match a bulk row by OCID or exact reference before full live coverage credit is allowed. Direct-only rows are preserved for recall but keep coverage fail-closed."
    bulk_stats_path.write_text(json.dumps(bulk_stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return proof


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bulk", type=Path, required=True)
    ap.add_argument("--direct", type=Path, required=True)
    args = ap.parse_args()
    proof = reconcile(args.bulk, args.direct)
    print(json.dumps(proof, ensure_ascii=False, indent=2))
    if not proof.get("coverage_complete"):
        raise SystemExit(3)


if __name__ == "__main__":
    main()
