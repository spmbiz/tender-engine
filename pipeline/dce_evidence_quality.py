from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ACCESS_GUIDE_FILENAME_PATTERNS = [
    r"instructions?.*(?:access|tender|portal)",
    r"how.*access.*tender",
    r"user.?guide",
    r"supplier.*guide",
    r"portal.*guide",
    r"terms.*use",
    r"nutzungsbedingungen",
    r"datenschutz",
    r"cgu.*march",
    r"depot[-_ ]?pli",
]

ACCESS_GUIDE_TEXT_PATTERNS = [
    r"instructions? on how to access",
    r"how to access .*tenders?",
    r"express interest",
    r"view documents",
    r"register(?:ed|ing|ation)? (?:on|at|with) (?:the )?(?:ungm|portal|e[- ]?tender)",
    r"supplier registration",
    r"complete your registration",
    r"login to (?:the )?(?:portal|system)",
    r"click (?:on )?[\"']?(?:express interest|view documents)",
    r"redirected to .*tender",
]

INTEREST_REQUIRED_PATTERNS = [
    r"express interest",
    r"record(?:ing)? (?:your )?interest",
    r"register interest",
]

SUBSTANTIVE_PATTERNS = [
    r"request for tender",
    r"request for proposal",
    r"invitation to tender",
    r"invitation to submit",
    r"terms of reference",
    r"scope of work",
    r"statement of work",
    r"requirements and specifications",
    r"technical specifications?",
    r"award criteria",
    r"selection criteria",
    r"evaluation criteria",
    r"pricing schedule",
    r"form of tender",
    r"conditions of contract",
    r"contract duration",
    r"submission deadline",
    r"deadline for (?:receipt|submission)",
    r"minimum turnover",
    r"professional indemnity",
    r"public liability",
]

GENERIC_FILENAME_RX = [re.compile(p, re.I) for p in ACCESS_GUIDE_FILENAME_PATTERNS]
ACCESS_RX = [re.compile(p, re.I) for p in ACCESS_GUIDE_TEXT_PATTERNS]
INTEREST_RX = [re.compile(p, re.I) for p in INTEREST_REQUIRED_PATTERNS]
SUBSTANTIVE_RX = [re.compile(p, re.I) for p in SUBSTANTIVE_PATTERNS]

STOPWORDS = {
    "the", "and", "for", "with", "from", "this", "that", "into", "website", "services", "service",
    "tender", "contract", "public", "procurement", "provision", "creation", "development", "support",
}


def _load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return default


def _matches(regexes: list[re.Pattern], text: str) -> list[str]:
    out = []
    for rx in regexes:
        m = rx.search(text or "")
        if m:
            out.append(m.group(0)[:160])
    return out


def _title_tokens(title: str) -> list[str]:
    toks = re.findall(r"[A-Za-zÀ-ÿ0-9]{4,}", (title or "").lower())
    return sorted({t for t in toks if t not in STOPWORDS})


def _title_overlap(title: str, text: str) -> dict:
    toks = _title_tokens(title)
    if not toks:
        return {"tokens": [], "hits": [], "ratio": 0.0}
    low = (text or "").lower()
    hits = [t for t in toks if t in low]
    return {"tokens": toks[:30], "hits": hits[:30], "ratio": round(len(hits) / len(toks), 4)}


def classify_candidate(root: Path) -> dict:
    manifest = _load(root / "manifest.json", {})
    candidate = manifest.get("candidate") or _load(root / "candidate.json", {})
    docs = _load(root / "document_index.json", [])
    corpus_path = root / "corpus.txt"
    corpus = corpus_path.read_text(encoding="utf-8", errors="replace") if corpus_path.exists() else ""
    raw_status = str(manifest.get("status") or "UNKNOWN")
    filenames = [str(x.get("name") or "") for x in docs if isinstance(x, dict)]
    generic_names = [n for n in filenames if n and any(rx.search(n) for rx in GENERIC_FILENAME_RX)]
    access_hits = _matches(ACCESS_RX, corpus)
    interest_hits = _matches(INTEREST_RX, corpus)
    substantive_hits = _matches(SUBSTANTIVE_RX, corpus)
    title_match = _title_overlap(str(candidate.get("title") or ""), corpus)
    text_chars = len(corpus)
    extracted_text_docs = sum(1 for x in docs if isinstance(x, dict) and int(x.get("text_chars") or 0) > 0)

    quality = "NOT_APPLICABLE"
    derived_status = raw_status
    gate_readiness = False
    reasons: list[str] = []

    if raw_status == "DOWNLOADED_PUBLIC":
        if extracted_text_docs == 0 or text_chars < 50:
            quality = "EXTRACTION_EMPTY"
            derived_status = "DOWNLOADED_PUBLIC_EMPTY"
            reasons.append("downloaded_files_but_no_extractable_authoritative_text")
        else:
            all_named_generic = bool(filenames) and len(generic_names) == len([n for n in filenames if n])
            strong_access_guide = len(access_hits) >= 2 and len(substantive_hits) <= 1
            weak_specificity = title_match["ratio"] < 0.25
            if all_named_generic or (strong_access_guide and (weak_specificity or text_chars < 120_000)):
                quality = "ACCESS_GUIDE_ONLY" if access_hits else "PORTAL_GENERIC_ONLY"
                if interest_hits:
                    derived_status = "INTEREST_RECORDING_REQUIRED"
                    reasons.append("retrieved_material_instructs_supplier_to_express_or_record_interest_before_real_documents")
                else:
                    derived_status = "PORTAL_GENERIC_ONLY"
                    reasons.append("retrieved_material_is_portal_or_access_boilerplate_not_procurement_specification")
            elif len(substantive_hits) >= 2:
                quality = "MIXED_SUBSTANTIVE_AND_GUIDE" if len(access_hits) >= 2 else "SUBSTANTIVE_DCE_PRESENT"
                derived_status = "DOWNLOADED_PUBLIC"
                gate_readiness = True
                reasons.append("multiple_authoritative_procurement_markers_detected")
            elif title_match["ratio"] >= 0.4 and text_chars >= 2_000:
                quality = "SUBSTANTIVE_DCE_PRESENT"
                derived_status = "DOWNLOADED_PUBLIC"
                gate_readiness = True
                reasons.append("strong_candidate_specificity_in_retrieved_text")
            else:
                quality = "UNKNOWN_RETRIEVED_DOCUMENT"
                derived_status = "DCE_CONTENT_UNVERIFIED"
                reasons.append("download_succeeded_but_authoritative_dce_content_not_proven")
    else:
        reasons.append("retrieval_status_not_downloaded_public")

    return {
        "contract": "DCE_EVIDENCE_QUALITY_V1",
        "candidate_id": manifest.get("candidate_id") or candidate.get("candidate_id") or root.name,
        "raw_status": raw_status,
        "derived_status": derived_status,
        "content_quality": quality,
        "gate_readiness": gate_readiness,
        "text_chars": text_chars,
        "documents_indexed": len(docs) if isinstance(docs, list) else 0,
        "documents_with_text": extracted_text_docs,
        "generic_filename_hits": generic_names[:30],
        "access_guide_hits": access_hits,
        "interest_required_hits": interest_hits,
        "substantive_marker_hits": substantive_hits,
        "candidate_title_overlap": title_match,
        "reasons": reasons,
        "rule": "DOWNLOADED_PUBLIC is transport success only. Mandatory-gate review is permitted only when gate_readiness=true.",
    }


def process(root: Path) -> dict:
    result = classify_candidate(root)
    (root / "evidence_quality.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="out")
    args = ap.parse_args()
    base = Path(args.root)
    roots = sorted(set(p.parent for p in base.rglob("manifest.json")))
    rows = [process(root) for root in roots]
    from collections import Counter
    summary = {
        "candidates": len(rows),
        "content_quality_counts": dict(Counter(r["content_quality"] for r in rows)),
        "derived_status_counts": dict(Counter(r["derived_status"] for r in rows)),
        "gate_ready": sum(1 for r in rows if r["gate_readiness"]),
        "gate_blocked": sum(1 for r in rows if not r["gate_readiness"]),
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
