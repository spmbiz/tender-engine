from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from final_verdict_guard import REQUIRED_GATES

PORTAL_GENERIC_FILE_PATTERNS = [
    re.compile(r"^depot[-_ ]?pli\.pdf$", re.I),
    re.compile(r"^CGU.*marches.*\.pdf$", re.I),
    re.compile(r"^rib-tender-nutzungsbedingungen.*\.pdf$", re.I),
    re.compile(r"^agb\.pdf$", re.I),
    re.compile(r"^Datenschutzbestimmungen_Vergabe-Abteilung\.pdf$", re.I),
    re.compile(r"^BOE-A-2017-12902-E\.pdf$", re.I),
]

# Candidate-specific relevance is deliberately independent from business fit. It
# answers only: "does this retrieved procurement document actually belong to this
# notice?" A mismatch blocks use of the document as evidence but NEVER discards the
# tender itself; the candidate remains retriable through another DCE route.
RELEVANCE_STOPWORDS = {
    "the", "and", "for", "with", "from", "this", "that", "into", "public", "service",
    "services", "supply", "supplies", "contract", "tender", "procurement", "request",
    "proposal", "solicitation", "notice", "digital", "online", "support", "provision",
    "development", "system", "systems", "project", "framework", "agreement", "management",
}
REFERENCE_KEYS = (
    "solicitation_number", "solicitationNumber", "notice_number", "noticeNumber",
    "reference", "reference_number", "referenceNumber", "tender_reference",
    "procurement_reference", "opportunity_id", "opportunityId", "publication_number",
)


def load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None


def is_portal_generic_file(file_rec: dict) -> bool:
    name = str((file_rec or {}).get("name") or "").strip()
    return bool(name) and any(rx.search(name) for rx in PORTAL_GENERIC_FILE_PATTERNS)


def legacy_content_quality(raw_status: str, files: list[dict]) -> tuple[str, str, bool]:
    if raw_status != "DOWNLOADED_PUBLIC":
        return raw_status, "NOT_APPLICABLE", False
    if not files:
        return "DOWNLOADED_PUBLIC_EMPTY", "EXTRACTION_EMPTY", False
    substantive = [f for f in files if not is_portal_generic_file(f)]
    if not substantive:
        return "PORTAL_GENERIC_ONLY", "PORTAL_GENERIC_ONLY", False
    return "DCE_CONTENT_UNVERIFIED", "UNKNOWN_RETRIEVED_DOCUMENT", False


def resolve_evidence(raw_status: str, files: list[dict], evidence: dict) -> tuple[str, str, bool]:
    if isinstance(evidence, dict) and str(evidence.get("contract") or "").upper() in {
        "DCE_EVIDENCE_QUALITY_V1",
        "DCE_EVIDENCE_QUALITY_V2",
    }:
        return (
            str(evidence.get("derived_status") or raw_status),
            str(evidence.get("content_quality") or "UNKNOWN"),
            bool(evidence.get("gate_readiness")),
        )
    return legacy_content_quality(raw_status, files)


def _norm(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def _compact(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _distinctive_title_tokens(title: str) -> list[str]:
    toks = re.findall(r"[a-z0-9]{4,}", _norm(title))
    return sorted({t for t in toks if t not in RELEVANCE_STOPWORDS})


def candidate_document_relevance(candidate: dict, corpus: str) -> dict:
    """Prove that a substantive procurement corpus is candidate-specific.

    This is intentionally stricter than generic DCE classification. Multiple
    procurement markers prove "this is a procurement document"; they do not prove
    "this is the procurement document for candidate X".
    """
    corpus_norm = _norm(corpus)
    corpus_compact = _compact(corpus)
    title = str(candidate.get("title") or "").strip()
    title_norm = _norm(title)
    title_tokens = _distinctive_title_tokens(title)

    reference_hits = []
    references = []
    for key in REFERENCE_KEYS:
        value = str(candidate.get(key) or "").strip()
        if not value:
            continue
        compact = _compact(value)
        if len(compact) < 5:
            continue
        references.append({"key": key, "value": value})
        if compact in corpus_compact:
            reference_hits.append({"key": key, "value": value})

    title_phrase_hit = bool(title_norm and len(title_norm) >= 10 and title_norm in corpus_norm)
    token_hits = [t for t in title_tokens if re.search(rf"\b{re.escape(t)}\b", corpus_norm)]
    token_ratio = len(token_hits) / len(title_tokens) if title_tokens else 0.0

    # Candidate identity can be proven by an explicit reference, by the normalized
    # title phrase, or by several distinctive title tokens. One generic token is
    # never enough; this is what prevents a huge generic PIEE manual from becoming
    # the DCE for "CCA, DIGITAL I/O" merely because it contains "digital".
    if reference_hits:
        status = "PROVEN_BY_REFERENCE"
        proven = True
    elif title_phrase_hit:
        status = "PROVEN_BY_TITLE_PHRASE"
        proven = True
    elif len(token_hits) >= 2 and token_ratio >= 0.5:
        status = "PROVEN_BY_TITLE_TOKENS"
        proven = True
    else:
        status = "UNPROVEN_CANDIDATE_DOCUMENT_MATCH"
        proven = False

    return {
        "status": status,
        "proven": proven,
        "title": title,
        "title_phrase_hit": title_phrase_hit,
        "title_distinctive_tokens": title_tokens[:30],
        "title_token_hits": token_hits[:30],
        "title_token_ratio": round(token_ratio, 4),
        "candidate_references": references[:20],
        "reference_hits": reference_hits[:20],
        "rule": "Procurement markers prove document type only. Gate evidence is allowed only when candidate-specific title/reference relevance is independently proven.",
    }


def review_template(gate_snippets: dict, gate_readiness: bool) -> dict:
    out = {}
    for gate in REQUIRED_GATES:
        out[gate] = {
            "status": "UNKNOWN",
            "evidence": [],
            "evidence_candidates": (gate_snippets.get(gate) or [])[:8] if gate_readiness else [],
            "notes": "",
        }
    return out


def quality_key(row: dict) -> tuple:
    return (
        bool(row.get("gate_readiness")),
        bool((row.get("candidate_document_relevance") or {}).get("proven")),
        not bool(row.get("deadline_conflict")),
        row.get("status") == "DOWNLOADED_PUBLIC",
        int(row.get("corpus_chars") or 0),
        int(row.get("documents_extracted") or 0),
    )


def portal_yield_metrics(rows: list[dict], batch_results: list[dict]) -> dict[str, dict]:
    stats: dict[str, dict] = defaultdict(lambda: {
        "candidates": 0,
        "gate_ready_substantive_dce": 0,
        "raw_downloaded_public": 0,
        "auth_required": 0,
        "generic_or_unresolved": 0,
        "candidate_relevance_unproven": 0,
        "candidate_processing_seconds": 0.0,
        "retries": 0,
        "rate_limit_signals": 0,
        "worker_failures": 0,
        "raw_status_counts": Counter(),
        "derived_status_counts": Counter(),
    })
    row_portal = {}
    for row in rows:
        portal = str(row.get("portal") or "UNKNOWN").upper()
        cid = str(row.get("candidate_id") or "").casefold()
        if cid:
            row_portal[cid] = portal
        s = stats[portal]
        s["candidates"] += 1
        s["gate_ready_substantive_dce"] += int(bool(row.get("gate_readiness")))
        s["raw_downloaded_public"] += int(str(row.get("raw_status") or "") == "DOWNLOADED_PUBLIC")
        s["auth_required"] += int(str(row.get("raw_status") or "") in {"AUTH_REQUIRED", "INTEREST_RECORDING_REQUIRED"})
        s["candidate_relevance_unproven"] += int(
            str((row.get("candidate_document_relevance") or {}).get("status") or "").startswith("UNPROVEN")
        )
        s["generic_or_unresolved"] += int(str(row.get("status") or "") in {
            "GENERIC_PUBLIC_PAGE_UNRESOLVED", "PORTAL_GENERIC_ONLY", "DCE_CONTENT_UNVERIFIED",
            "DCE_CANDIDATE_RELEVANCE_UNVERIFIED", "TED_DOWNSTREAM_ADAPTER_PENDING",
            "TED_ROUTE_UNRESOLVED", "ROUTE_INCOMPLETE",
        })
        s["raw_status_counts"][str(row.get("raw_status") or "UNKNOWN")] += 1
        s["derived_status_counts"][str(row.get("status") or "UNKNOWN")] += 1

    for rec in batch_results:
        cid = str(rec.get("candidate_id") or "").casefold()
        portal = str(rec.get("portal") or row_portal.get(cid) or "UNKNOWN").upper()
        s = stats[portal]
        s["candidate_processing_seconds"] += max(0.0, float(rec.get("elapsed_seconds") or 0.0))
        s["retries"] += int(rec.get("retries") or 0)
        s["rate_limit_signals"] += int(bool(rec.get("rate_limited")))
        s["worker_failures"] += int(int(rec.get("returncode") or 0) != 0)

    out = {}
    for portal, s in sorted(stats.items()):
        candidates = int(s["candidates"])
        useful = int(s["gate_ready_substantive_dce"])
        seconds = float(s["candidate_processing_seconds"])
        minutes = seconds / 60.0
        out[portal] = {
            "candidates": candidates,
            "gate_ready_substantive_dce": useful,
            "useful_rate": round(useful / candidates, 6) if candidates else 0.0,
            "raw_downloaded_public": int(s["raw_downloaded_public"]),
            "auth_required": int(s["auth_required"]),
            "auth_rate": round(int(s["auth_required"]) / candidates, 6) if candidates else 0.0,
            "generic_or_unresolved": int(s["generic_or_unresolved"]),
            "candidate_relevance_unproven": int(s["candidate_relevance_unproven"]),
            "candidate_processing_seconds": round(seconds, 3),
            "candidate_processing_minutes": round(minutes, 6),
            "useful_per_candidate_processing_minute": round(useful / minutes, 6) if minutes > 0 else 0.0,
            "retries": int(s["retries"]),
            "rate_limit_signals": int(s["rate_limit_signals"]),
            "worker_failures": int(s["worker_failures"]),
            "raw_status_counts": dict(s["raw_status_counts"]),
            "derived_status_counts": dict(s["derived_status_counts"]),
        }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="dce-artifacts")
    ap.add_argument("--out", default="dce-aggregate")
    args = ap.parse_args()

    root = Path(args.root)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    by_candidate: dict[str, dict] = {}
    raw_manifest_rows = 0

    for manifest_path in sorted(root.rglob("manifest.json")):
        manifest = load(manifest_path)
        if not isinstance(manifest, dict) or "candidate_id" not in manifest:
            continue
        raw_manifest_rows += 1
        candidate_root = manifest_path.parent
        candidate = manifest.get("candidate") or load(candidate_root / "candidate.json") or {}
        gates = load(candidate_root / "gate_snippets.json") or {}
        evidence = load(candidate_root / "evidence_quality.json") or {}
        authority = load(candidate_root / "authority_conflicts.json") or {}
        deadline_authority = authority.get("deadline") if isinstance(authority, dict) else {}
        doc_index = load(candidate_root / "document_index.json") or []
        corpus_path = candidate_root / "corpus.txt"
        corpus_text = corpus_path.read_text(encoding="utf-8", errors="replace") if corpus_path.exists() else ""
        raw_status = str(manifest.get("status") or "UNKNOWN")
        files = manifest.get("files") or []
        status, content_quality, gate_readiness = resolve_evidence(raw_status, files, evidence)

        candidate_relevance = candidate_document_relevance(candidate, corpus_text) if gate_readiness else {
            "status": "NOT_EVALUATED_EVIDENCE_NOT_GATE_READY",
            "proven": False,
            "rule": "Candidate-specific relevance is evaluated only after the material is substantively procurement-like.",
        }
        if gate_readiness and not candidate_relevance.get("proven"):
            gate_readiness = False
            status = "DCE_CANDIDATE_RELEVANCE_UNVERIFIED"
            content_quality = "SUBSTANTIVE_DCE_RELEVANCE_UNVERIFIED"

        gate_snippets = gates.get("categories") or {}
        deadline_conflict = bool(deadline_authority.get("conflict")) if isinstance(deadline_authority, dict) else False
        deadline_authority_status = deadline_authority.get("status") if isinstance(deadline_authority, dict) else None
        cid = str(manifest.get("candidate_id"))
        row = {
            "candidate_id": cid,
            "title": candidate.get("title"),
            "buyer": candidate.get("buyer"),
            "portal": str(manifest.get("portal") or candidate.get("portal") or candidate.get("source") or "UNKNOWN").upper(),
            "raw_status": raw_status,
            "status": status,
            "content_quality": content_quality,
            "gate_readiness": gate_readiness,
            "eligible_for_gate_review": gate_readiness,
            "finalization_allowed": False,
            "evidence_quality": evidence,
            "candidate_document_relevance": candidate_relevance,
            "authority_conflicts": authority,
            "deadline_authority_status": deadline_authority_status,
            "deadline_conflict": deadline_conflict,
            "deadline": candidate.get("deadline"),
            "estimated_value": candidate.get("estimated_value"),
            "currency": candidate.get("currency"),
            "notice_url": candidate.get("notice_url"),
            "preliminary_score": candidate.get("preliminary_score") or candidate.get("pre_score"),
            "files": files,
            "documents_extracted": len(doc_index) if isinstance(doc_index, list) else 0,
            "corpus_chars": len(corpus_text),
            "gate_evidence_counts": gates.get("evidence_counts") or {},
            "gate_snippets": gate_snippets,
            "mandatory_gate_names": REQUIRED_GATES,
            "review_template": review_template(gate_snippets, gate_readiness),
            "artifact_relative_root": str(candidate_root.relative_to(root)),
            "gpt_instruction": (
                "DOWNLOADED_PUBLIC is transport success, not proof of DCE. Only review mandatory gates when gate_readiness=true. "
                "A procurement-like document must also be independently proven relevant to this exact candidate by title/reference evidence. "
                "DCE_CANDIDATE_RELEVANCE_UNVERIFIED means retry/inspect another route; it does NOT mean reject the tender. "
                "Fill every review_template gate as PASS/PASS_CONDITIONAL/FAIL_HARD/UNKNOWN/NOT_APPLICABLE with source evidence. "
                "Resolve authority_conflicts explicitly; a deadline conflict or unknown authoritative DCE deadline blocks finalization. "
                "FINAL_SUPER_GREEN or score >=90 is forbidden while any potentially disqualifying gate is UNKNOWN/FAIL or lacks evidence. "
                "Never infer a PASS from absence of a snippet; missing evidence remains UNKNOWN."
            ),
        }
        current = by_candidate.get(cid.casefold())
        if current is None or quality_key(row) > quality_key(current):
            by_candidate[cid.casefold()] = row

    rows = sorted(by_candidate.values(), key=lambda r: str(r.get("candidate_id") or ""))
    counts = Counter(str(r.get("status") or "UNKNOWN") for r in rows)
    raw_counts = Counter(str(r.get("raw_status") or "UNKNOWN") for r in rows)
    quality_counts = Counter(str(r.get("content_quality") or "UNKNOWN") for r in rows)
    deadline_authority_counts = Counter(str(r.get("deadline_authority_status") or "MISSING") for r in rows)
    relevance_counts = Counter(str((r.get("candidate_document_relevance") or {}).get("status") or "MISSING") for r in rows)

    with (out / "deep_review_queue.jsonl").open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    batch_results = []
    for path in sorted(root.rglob("batch_results.json")):
        obj = load(path)
        if isinstance(obj, list):
            batch_results.extend(x for x in obj if isinstance(x, dict))

    shard_metrics = []
    for path in sorted(root.rglob("_shard_metrics.json")):
        obj = load(path)
        if isinstance(obj, dict):
            shard_metrics.append(obj)

    raw_bytes = sum(int(x.get("raw_worker_tree_bytes") or 0) for x in shard_metrics)
    slim_bytes = sum(int(x.get("slim_handoff_bytes") or x.get("slim_handoff_bytes_before_metrics") or 0) for x in shard_metrics)
    retries = sum(int(x.get("retries") or 0) for x in batch_results)
    rate_limited = sum(1 for x in batch_results if x.get("rate_limited"))
    worker_failures = sum(1 for x in batch_results if int(x.get("returncode") or 0) != 0)
    gate_ready_count = sum(1 for r in rows if r.get("gate_readiness"))
    deadline_conflict_count = sum(1 for r in rows if r.get("deadline_conflict"))
    relevance_unproven_count = sum(
        1 for r in rows if str((r.get("candidate_document_relevance") or {}).get("status") or "").startswith("UNPROVEN")
    )
    portal_yield = portal_yield_metrics(rows, batch_results)
    (out / "portal_yield.json").write_text(json.dumps(portal_yield, indent=2, ensure_ascii=False), encoding="utf-8")

    summary = {
        "candidates": len(rows),
        "raw_manifest_rows": raw_manifest_rows,
        "duplicate_manifest_rows_removed": max(0, raw_manifest_rows - len(rows)),
        "raw_status_counts": dict(raw_counts),
        "derived_status_counts": dict(counts),
        "content_quality_counts": dict(quality_counts),
        "candidate_document_relevance_counts": dict(relevance_counts),
        "candidate_relevance_unproven": relevance_unproven_count,
        "deadline_authority_status_counts": dict(deadline_authority_counts),
        "deadline_conflicts": deadline_conflict_count,
        "raw_downloaded_public": raw_counts.get("DOWNLOADED_PUBLIC", 0),
        "gate_ready_substantive_dce": gate_ready_count,
        "gate_blocked_or_unverified": max(0, len(rows) - gate_ready_count),
        "access_guide_only": quality_counts.get("ACCESS_GUIDE_ONLY", 0),
        "portal_generic_only": quality_counts.get("PORTAL_GENERIC_ONLY", 0),
        "content_unverified": quality_counts.get("UNKNOWN_RETRIEVED_DOCUMENT", 0),
        "fully_extracted_gate_ready": sum(1 for r in rows if r.get("gate_readiness") and r.get("corpus_chars", 0) > 0),
        "worker_retries": retries,
        "worker_failures": worker_failures,
        "rate_limit_signals": rate_limited,
        "shard_metric_count": len(shard_metrics),
        "raw_worker_tree_bytes": raw_bytes,
        "slim_handoff_bytes": slim_bytes,
        "handoff_storage_reduction_ratio": round((1 - slim_bytes / raw_bytes) if raw_bytes else 0, 6),
        "portal_yield": portal_yield,
        "portal_yield_time_basis": "candidate_processing_minutes; not yet exact GitHub runner wall-time",
        "raw_archives_in_final_artifact": False,
        "mandatory_gate_names": REQUIRED_GATES,
        "contract": "Only candidate-specific gate_ready_substantive_dce rows may advance to mandatory-gate adjudication. A relevance mismatch blocks the document as evidence, not the tender; alternative DCE routes remain eligible for retry.",
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
