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


def identities(row: dict[str, Any]) -> tuple[set[str], set[str]]:
    route = row.get("route") if isinstance(row.get("route"), dict) else {}
    refs = {
        clean(row.get("reference")),
        clean(route.get("reference")),
        clean(row.get("notice_id")),
    }
    ocids = {
        clean(row.get("ocid")),
        clean(row.get("procedure_id")),
        clean(route.get("ocid")),
    }
    refs.discard("")
    ocids.discard("")
    return refs, ocids


def build_index(rows: list[dict[str, Any]]):
    refs: dict[str, set[int]] = {}
    ocids: dict[str, set[int]] = {}
    for idx, row in enumerate(rows):
        rset, oset = identities(row)
        for ref in rset:
            refs.setdefault(ref, set()).add(idx)
        for ocid in oset:
            ocids.setdefault(ocid, set()).add(idx)
    return refs, ocids


def direct_contract_complete(stats: dict[str, Any], row_count: int) -> bool:
    if stats.get("enumeration_complete") is not True or stats.get("errors"):
        return False
    if stats.get("state_chain_bootstrap_proven") is not True:
        return False
    if stats.get("filtered_current_search_proven") is not True and stats.get("direct_filtered_post_proven") is not True:
        return False
    if stats.get("count_matches_official_total") is not True:
        return False
    try:
        return int(stats.get("total_reported")) == row_count
    except Exception:
        return False


def bulk_contract_complete(stats: dict[str, Any]) -> bool:
    if stats.get("publication_window_enumeration_complete") is not True or stats.get("errors"):
        return False
    expected = stats.get("requests_expected")
    completed = stats.get("requests_completed")
    try:
        if expected is not None and completed is not None and int(expected) != int(completed):
            return False
    except Exception:
        return False
    return True


def reconcile(bulk_dir: Path, direct_dir: Path) -> dict[str, Any]:
    bulk_stats_path = bulk_dir / "stats.json"
    direct_stats_path = direct_dir / "stats.json"
    bulk_stats = read_json(bulk_stats_path)
    direct_stats = read_json(direct_stats_path)
    bulk_rows = list(iter_jsonl(bulk_dir / "current.jsonl"))
    direct_rows = list(iter_jsonl(direct_dir / "current.jsonl"))

    direct_complete = direct_contract_complete(direct_stats, len(direct_rows))
    bulk_complete = bulk_contract_complete(bulk_stats)
    bulk_refs, bulk_ocids = build_index(bulk_rows)

    exact_notice_links = 0
    procedure_links = 0
    unmatched_direct = 0
    used_bulk: set[int] = set()
    final_rows: list[dict[str, Any]] = []
    link_proof: list[dict[str, Any]] = []

    for direct in direct_rows:
        refs, ocids = identities(direct)
        exact_idxs: set[int] = set()
        for ref in refs:
            exact_idxs.update(bulk_refs.get(ref) or set())

        method = None
        linked_idxs: set[int] = set()
        if exact_idxs:
            method = "EXACT_NOTICE_REFERENCE"
            linked_idxs = exact_idxs
            exact_notice_links += 1
        else:
            # An OCID identifies a procurement process, not necessarily the same
            # publication. It is useful enrichment linkage but is never promoted
            # to destructive notice identity.
            proc_idxs: set[int] = set()
            for ocid in ocids:
                proc_idxs.update(bulk_ocids.get(ocid) or set())
            if proc_idxs:
                method = "PROCEDURE_OCID_LINK"
                linked_idxs = proc_idxs
                procedure_links += 1
            else:
                unmatched_direct += 1

        row = dict(direct)
        row["source"] = "UK_PCS_OCDS"
        row["grain"] = "NOTICE_FIRST_TENDER"
        row["current"] = True
        row["currentness_evidence"] = "PCS_OFFICIAL_CURRENT_OPPORTUNITY_REGISTRY_EXHAUSTIVE"
        route = dict(row.get("route") or {})
        route["current_registry_authoritative"] = True
        if method:
            route["bulk_enrichment_link_method"] = method
            route["bulk_enrichment_candidate_ids"] = [
                clean(bulk_rows[i].get("candidate_id")) for i in sorted(linked_idxs)
            ]
            used_bulk.update(linked_idxs)
        row["route"] = route
        final_rows.append(row)
        link_proof.append({
            "direct_candidate_id": clean(direct.get("candidate_id")) or None,
            "link_method": method,
            "bulk_candidate_ids": route.get("bulk_enrichment_candidate_ids") or [],
        })

    # Bulk rows that the authoritative Current Opportunity registry does not list
    # are preserved for diagnostics/enrichment, but never counted as live current.
    bulk_only = [row for idx, row in enumerate(bulk_rows) if idx not in used_bulk]
    for row in bulk_only:
        row = dict(row)
        row["current"] = False
        row["currentness_evidence"] = "BULK_RECONSTRUCTION_NOT_PRESENT_IN_OFFICIAL_CURRENT_REGISTRY"
    final_rows.sort(key=lambda x: (str(x.get("deadline") or "9999"), clean(x.get("candidate_id"))))

    proof_dir = bulk_dir / "reconciliation"
    proof_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(proof_dir / "direct_current.jsonl", direct_rows)
    write_jsonl(proof_dir / "bulk_current_not_in_direct_registry.jsonl", bulk_only)
    write_jsonl(proof_dir / "link_proof.jsonl", link_proof)
    (proof_dir / "direct_stats.json").write_text(json.dumps(direct_stats, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    write_jsonl(bulk_dir / "current.jsonl", final_rows)
    # Preserve the full official bulk reconstruction as raw evidence rather than
    # replacing it with the direct registry projection.
    raw_rows = list(iter_jsonl(bulk_dir / "raw.jsonl"))
    if raw_rows:
        write_jsonl(bulk_dir / "raw.jsonl", raw_rows)

    coverage_complete = bool(direct_complete and len(final_rows) == len(direct_rows) and len(direct_rows) > 0)
    bulk_linked = exact_notice_links + procedure_links
    recall = (bulk_linked / len(direct_rows)) if direct_rows else 0.0
    proof = {
        "schema": "PCS_CURRENT_REGISTRY_AUTHORITATIVE_RECONCILIATION_V2",
        "direct_current_contract_complete": direct_complete,
        "direct_official_total_reported": direct_stats.get("total_reported"),
        "direct_current_rows": len(direct_rows),
        "final_current_rows": len(final_rows),
        "bulk_publication_contract_complete": bulk_complete,
        "bulk_current_rows_before_reconcile": len(bulk_rows),
        "exact_notice_reference_links": exact_notice_links,
        "procedure_ocid_links": procedure_links,
        "direct_without_bulk_enrichment": unmatched_direct,
        "bulk_enrichment_recall_against_official_current": recall,
        "bulk_current_not_in_direct_registry": len(bulk_only),
        "coverage_complete": coverage_complete,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "semantics": "The exhaustively paged official PCS Current Opportunity registry is authoritative for live current-universe coverage. Monthly OCDS bulk is an enrichment/provenance surface, not an eligibility condition for existence in the current registry. Exact notice references are notice identity; OCID links are procedure-level enrichment only and never destructive notice dedupe. Bulk-only reconstructed-current rows are preserved diagnostically but excluded from current.jsonl.",
    }
    (proof_dir / "summary.json").write_text(json.dumps(proof, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    bulk_stats["publication_bulk_listing_contract"] = bulk_stats.get("listing_contract")
    bulk_stats["listing_contract"] = "PCS_CURRENT_OPPORTUNITY_REGISTRY_V5_AUTHORITATIVE_PLUS_BULK_ENRICHMENT"
    bulk_stats["current_universe_reconciliation"] = proof
    bulk_stats["bulk_current_materialized_before_reconcile"] = len(bulk_rows)
    bulk_stats["current_materialized"] = len(final_rows)
    bulk_stats["enumeration_exhausted"] = coverage_complete
    bulk_stats["enumeration_complete"] = coverage_complete
    bulk_stats["live_candidate_capable"] = bool(final_rows)
    bulk_stats["live_coverage_credit_allowed"] = coverage_complete
    bulk_stats["generated_at"] = datetime.now(timezone.utc).isoformat()
    bulk_stats["warnings"] = list(bulk_stats.get("warnings") or []) + ([{
        "type": "PCS_BULK_ENRICHMENT_RECALL_BELOW_CURRENT_REGISTRY",
        "bulk_enrichment_recall_against_official_current": recall,
        "direct_without_bulk_enrichment": unmatched_direct,
        "impact": "ENRICHMENT_ONLY_NOT_LIVE_COVERAGE",
    }] if unmatched_direct else [])
    bulk_stats["semantics"] = "Official PCS Current Opportunity registry is the authoritative live enumeration surface and must prove state-chained filtered page exhaustion plus exact official total reconciliation. Official monthly OCDS bulk is retained as a richer enrichment/provenance surface. Failure of bulk enrichment recall does not erase official current-registry opportunities; it remains a separately reported quality metric."
    bulk_stats_path.write_text(json.dumps(bulk_stats, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return proof


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bulk", type=Path, required=True)
    ap.add_argument("--direct", type=Path, required=True)
    args = ap.parse_args()
    proof = reconcile(args.bulk, args.direct)
    print(json.dumps(proof, indent=2, ensure_ascii=False))
    if proof.get("coverage_complete") is not True:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
