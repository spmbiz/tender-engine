from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

import dce_country_benchmark as base


EXTRA_TARGETS = ["CA-QC", "DK", "FI", "SI", "ZA", "AU"]
base.TARGET_COUNTRIES[:] = [
    "LU", "IE", "GB-SCT", "GB", "GR", "CA", "CA-QC", "US", "ZA",
    "SK", "HU", "PL", "ES", "DE", "BG", "BE", "NL", "EE", "CH",
    "FR", "LV", "CZ", "DK", "FI", "SI", "RO", "HR", "AT", "IT",
    "PT", "SE", "NO", "NZ", "AU",
]

base.PORTAL_COUNTRY.update({
    "QC_SEAO": "CA-QC", "SEAO": "CA-QC", "CA_SEAO": "CA-QC",
    "DK_UDBUD": "DK", "DK_UDBUD_DK": "DK",
    "FI_HILMA": "FI",
    "SI_EJN": "SI", "SI_EJN_PUBLIC": "SI",
    "ZA_ETENDERS": "ZA", "ZA_ETENDERS_OCDS": "ZA",
    "AU_AUSTENDER": "AU", "AUSTENDER": "AU",
})

# Specific jurisdictions must win before broad country metadata. This matters
# for Scotland (often country=GB) and Quebec (often country=CA).
SPECIAL_PREFIXES = [
    ("UK_PCS_OCDS:", "GB-SCT"), ("uk_pcs_ocds:", "GB-SCT"),
    ("QC-", "CA-QC"), ("DK-", "DK"), ("FI-", "FI"), ("SI-", "SI"),
    ("ZA_", "ZA"), ("ZA-", "ZA"), ("AU-", "AU"),
]


def infer_country(rec: dict) -> str:
    # 1. Portal is the most authoritative jurisdiction signal for specialized
    # procurement systems and avoids Scotland/Quebec being swallowed by GB/CA.
    for raw in (
        rec.get("portal"), rec.get("portal_key"), rec.get("source"),
        rec.get("selection_portal"), rec.get("source_portal"),
    ):
        portal = str(raw or "").strip().upper()
        if portal in base.PORTAL_COUNTRY:
            return base.PORTAL_COUNTRY[portal]

    # 2. Candidate IDs often encode the exact jurisdiction.
    cid = str(rec.get("candidate_id") or "")
    for prefix, code in SPECIAL_PREFIXES + base.PREFIX_COUNTRY:
        if cid.startswith(prefix):
            return code

    # 3. Broad metadata is the final fallback.
    for key in ("country_code", "country", "buyer_country", "iso_country", "jurisdiction_country"):
        code = base.norm_code(rec.get(key))
        if code:
            return code
    buyer = rec.get("buyer")
    if isinstance(buyer, dict):
        for key in ("country_code", "country", "countryCode", "iso_country"):
            code = base.norm_code(buyer.get(key))
            if code:
                return code
    return ""


base.infer_country = infer_country
_ORIGINAL_SUMMARIZE_COUNTRY = base.cmd_summarize_country


def cmd_summarize_country(args) -> None:
    """Score transport and evidence quality separately.

    A file existing is not enough. The same extraction/evidence-quality/aggregate
    stack used by production must prove that the corpus is substantive and
    candidate-matched before it counts as usable DCE for country grading.
    """
    root = Path(args.out)
    subprocess.run([sys.executable, "pipeline/extract_corpus.py", "--root", str(root)], check=True)
    subprocess.run([sys.executable, "pipeline/dce_evidence_quality.py", "--root", str(root)], check=True)
    quality_out = root / "country-quality-aggregate"
    subprocess.run([sys.executable, "pipeline/aggregate_dce.py", "--root", str(root), "--out", str(quality_out)], check=True)

    _ORIGINAL_SUMMARIZE_COUNTRY(args)
    summary_path = Path(args.summary)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    quality = json.loads((quality_out / "summary.json").read_text(encoding="utf-8"))

    n = int(summary.get("sample_size") or 0)
    transport = int(quality.get("raw_downloaded_public") or summary.get("downloaded_public") or 0)
    usable = int(quality.get("gate_ready_substantive_dce") or 0)
    barriers = int(summary.get("legitimate_barrier") or 0)
    summary.update({
        "transport_downloaded_public": transport,
        "transport_rate": round(transport / n, 4) if n else 0.0,
        "usable_gate_ready_dce": usable,
        "usable_rate": round(usable / n, 4) if n else 0.0,
        "quality_handled_rate": round((usable + barriers) / n, 4) if n else 0.0,
        "candidate_relevance_unproven": int(quality.get("candidate_relevance_unproven") or 0),
        "content_unverified": int(quality.get("content_unverified") or 0),
        "content_quality_counts": quality.get("content_quality_counts") or {},
        "derived_status_counts": quality.get("derived_status_counts") or {},
        "quality_contract": "usable means SUBSTANTIVE_DCE_PRESENT and candidate-document relevance proven by production evidence-quality rules",
    })
    rate = float(summary["usable_rate"])
    summary["grade"] = "A" if rate >= 0.75 else "B" if rate >= 0.50 else "C" if rate >= 0.25 else "D-GATED" if float(summary["quality_handled_rate"]) >= 0.75 else "D"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "rows"}, indent=2, ensure_ascii=False))


def cmd_aggregate(args) -> None:
    summaries = []
    for root in [Path(x) for x in args.inputs]:
        for p in root.rglob("country-summary.json"):
            try:
                obj = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            if isinstance(obj, dict):
                summaries.append(obj)
    summaries.sort(key=lambda x: str(x.get("country") or ""))
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    total_n = sum(int(s.get("sample_size") or 0) for s in summaries)
    total_transport = sum(int(s.get("transport_downloaded_public") or s.get("downloaded_public") or 0) for s in summaries)
    total_usable = sum(int(s.get("usable_gate_ready_dce") or 0) for s in summaries)
    total_barrier = sum(int(s.get("legitimate_barrier") or 0) for s in summaries)
    payload = {
        "countries_tested": len(summaries),
        "sample_size_total": total_n,
        "transport_downloaded_public_total": total_transport,
        "usable_gate_ready_dce_total": total_usable,
        "legitimate_barrier_total": total_barrier,
        "overall_transport_rate": round(total_transport / total_n, 4) if total_n else 0.0,
        "overall_usable_rate": round(total_usable / total_n, 4) if total_n else 0.0,
        "overall_quality_handled_rate": round((total_usable + total_barrier) / total_n, 4) if total_n else 0.0,
        "countries": summaries,
    }
    (out / "report.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    fields = [
        "country", "sample_size", "transport_downloaded_public", "usable_gate_ready_dce",
        "legitimate_barrier", "no_public_file_or_route", "retryable_error", "transport_rate",
        "usable_rate", "quality_handled_rate", "candidate_relevance_unproven", "content_unverified",
        "candidate_seconds", "http_probe_promoted", "confidence", "grade",
    ]
    with (out / "report.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for s in summaries:
            w.writerow({k: s.get(k) for k in fields})

    md = [
        "# DCE Country Validation V2", "",
        f"Countries tested: **{len(summaries)}**  ",
        f"Real tender candidates: **{total_n}**  ",
        f"Transport downloads: **{total_transport}** ({payload['overall_transport_rate']:.1%})  ",
        f"Usable gate-ready DCE: **{total_usable}** ({payload['overall_usable_rate']:.1%})  ",
        f"Usable or correctly stopped at legitimate gate: **{total_usable + total_barrier}** ({payload['overall_quality_handled_rate']:.1%})", "",
        "| Country | N | Transport | Usable DCE | Gate | Unresolved | Retryable | Transport % | Usable % | Handled % | HTTP→no browser | Grade |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for s in summaries:
        md.append(
            f"| {s.get('country')} | {s.get('sample_size')} | {s.get('transport_downloaded_public')} | {s.get('usable_gate_ready_dce')} | "
            f"{s.get('legitimate_barrier')} | {s.get('no_public_file_or_route')} | {s.get('retryable_error')} | "
            f"{float(s.get('transport_rate') or 0):.0%} | {float(s.get('usable_rate') or 0):.0%} | "
            f"{float(s.get('quality_handled_rate') or 0):.0%} | {s.get('http_probe_promoted')} | {s.get('grade')} |"
        )
    md += [
        "", "Notes:",
        "- Transport means the resolver persisted at least one downloaded file.",
        "- Usable DCE means production evidence-quality rules found substantive procurement material and proved candidate-document relevance.",
        "- Auth/CAPTCHA/registration/interest/controlled-document boundaries count as legitimate barriers, never as downloads.",
        "- This measures the current live corpus; it is not a claim that every tender ever published in the jurisdiction behaves identically.",
    ]
    (out / "REPORT.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in payload.items() if k != "countries"}, indent=2))


base.cmd_summarize_country = cmd_summarize_country
base.cmd_aggregate = cmd_aggregate


if __name__ == "__main__":
    base.main()
