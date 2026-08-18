from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

TARGET_COUNTRIES = [
    "LU", "IE", "GB-SCT", "GB", "GR", "CA", "SK", "HU", "PL", "ES",
    "DE", "BG", "BE", "NL", "EE", "CH", "FR", "LV", "CZ", "RO",
    "HR", "AT", "IT", "PT", "SE", "NO", "NZ", "US",
]

PORTAL_COUNTRY = {
    "LUX_PMP": "LU", "LU_PMP": "LU", "LUXEMBOURG_PMP": "LU",
    "IRELAND_ETENDERS": "IE", "IE_ETENDERS": "IE", "ETENDERS_IRELAND": "IE",
    "SCOTLAND_PCS": "GB-SCT", "UK_PCS_OCDS": "GB-SCT", "PUBLIC_CONTRACTS_SCOTLAND": "GB-SCT",
    "UK_FIND_A_TENDER": "GB", "UK_FTS_OCDS": "GB", "UK_CONTRACTS_FINDER": "GB",
    "UK_PROCONTRACT": "GB", "UK_ATAMIS": "GB", "UK_DELTA": "GB", "UK_INTEND": "GB", "UK_JAGGAER": "GB",
    "GR_KHMDHS": "GR", "GR_EPPS_PUBLIC": "GR",
    "CA_CANADABUYS": "CA", "CANADABUYS": "CA",
    "SK_UVO": "SK", "SK_UVO_PUBLIC": "SK",
    "HU_EKR": "HU", "HU_EKR_PUBLIC": "HU",
    "PL_BZP": "PL", "PL_EZAMOWIENIA": "PL", "PL_PLATFORMZAKUPOWA": "PL",
    "ES_PLACSP": "ES", "ES_CATALONIA_PUBLIC": "ES", "ES_EUSKADI_PUBLIC": "ES", "ES_ANDALUCIA_PUBLIC": "ES", "ES_MADRID_PUBLIC": "ES", "ES_NAVARRA_PUBLIC": "ES",
    "DE_DOE": "DE", "DE_EVERGABE_NRW": "DE", "DE_EVERGABE_DE": "DE", "DE_BI_MEDIEN": "DE", "DE_LWL": "DE",
    "BG_EOP_PUBLIC": "BG", "BG_CAISO_EOP": "BG",
    "BE_EPROC": "BE", "BE_EPROC_V11": "BE",
    "NL_TENDERNED_RSS": "NL", "NL_TENDERNED_PUBLIC": "NL", "NL_TENDERNED": "NL",
    "EE_RHR": "EE",
    "CH_SIMAP": "CH", "CH_SIMAP_PUBLIC": "CH",
    "FR_BOAMP": "FR", "FR_PLACE": "FR", "FR_ACHATPUBLIC": "FR", "FR_AWS": "FR", "FR_MAXIMILIEN": "FR", "FR_MARCHES_SECUR": "FR", "FR_E_MARCHESPUBLICS": "FR",
    "LV_IUB": "LV", "LV_IUB_PUBLIC": "LV", "LV_EIS_PUBLIC": "LV",
    "CZ_NIPEZ_PUBLIC": "CZ", "CZ_EGORDION": "CZ", "CZ_ZAKAZKY_VENDOR": "CZ",
    "RO_SEAP_PUBLIC": "RO", "RO_SEAP": "RO",
    "HR_EOJN_PUBLIC": "HR", "HR_EOJN": "HR",
    "AT_VERGABEPORTAL": "AT",
    "IT_ACQUISTINRETEPA": "IT", "IT_ALBOFORNITORI": "IT", "IT_ALTOADIGE": "IT", "IT_TUTTOGARE": "IT", "IT_TRANSPARE": "IT", "IT_MAGGIOLI": "IT", "IT_EPAL": "IT",
    "PT_ACINGOV": "PT",
    "SE_EAVROP": "SE", "SE_CLIRA": "SE", "SE_TENDSIGN": "SE", "SE_KOMMERSANNONS": "SE",
    "NO_DOFFIN": "NO", "NO_ARTIFIK": "NO",
    "NZ_GETS": "NZ", "NZ_TENDERLINK": "NZ",
    "US_SAM": "US", "SAM_GOV": "US", "SAM": "US",
}

PREFIX_COUNTRY = [
    ("UK_PCS_OCDS:", "GB-SCT"), ("uk_pcs_ocds:", "GB-SCT"),
    ("IE-", "IE"), ("GR-", "GR"), ("CA-", "CA"), ("SK-", "SK"), ("HU-", "HU"),
    ("PL-", "PL"), ("ES-", "ES"), ("DE-", "DE"), ("BG-", "BG"), ("BE-", "BE"),
    ("NL-", "NL"), ("EE-", "EE"), ("CH-", "CH"), ("FR-", "FR"), ("LV-", "LV"),
    ("CZ-", "CZ"), ("RO-", "RO"), ("HR-", "HR"), ("AT-", "AT"), ("IT-", "IT"),
    ("PT-", "PT"), ("SE-", "SE"), ("NO-", "NO"), ("NZ-", "NZ"), ("US-", "US"), ("LU-", "LU"),
]

STATUS_BARRIER = {"AUTH_REQUIRED", "CAPTCHA_REQUIRED", "INTEREST_RECORDING_REQUIRED", "CONTROLLED_DOCUMENT", "REGISTRATION_REQUIRED"}
STATUS_NO_PUBLIC = {"NO_PUBLIC_FILE", "GENERIC_PUBLIC_PAGE_UNRESOLVED", "ROUTE_INCOMPLETE", "ADAPTER_PENDING", "NO_PUBLIC_DCE"}
STATUS_RETRYABLE = {"ERROR_RETRYABLE", "WORKER_ERROR", "BATCH_EXCEPTION", "UNKNOWN", "MISSING_RESULT"}


def load_jsonl(path: Path):
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if not line.strip():
                continue
            obj = json.loads(line)
            if isinstance(obj, dict):
                yield obj


def norm_code(value: Any) -> str:
    s = str(value or "").strip().upper().replace("_", "-")
    aliases = {
        "UK": "GB", "GBR": "GB", "GREAT BRITAIN": "GB", "UNITED KINGDOM": "GB",
        "BELGIUM": "BE", "BEL": "BE", "FRANCE": "FR", "FRA": "FR", "GERMANY": "DE", "DEU": "DE",
        "SPAIN": "ES", "ESP": "ES", "ITALY": "IT", "ITA": "IT", "PORTUGAL": "PT", "PRT": "PT",
        "POLAND": "PL", "POL": "PL", "NETHERLANDS": "NL", "NLD": "NL", "IRELAND": "IE", "IRL": "IE",
        "GREECE": "GR", "GRC": "GR", "HUNGARY": "HU", "HUN": "HU", "SLOVAKIA": "SK", "SVK": "SK",
        "BULGARIA": "BG", "BGR": "BG", "ROMANIA": "RO", "ROU": "RO", "CROATIA": "HR", "HRV": "HR",
        "AUSTRIA": "AT", "AUT": "AT", "SWEDEN": "SE", "SWE": "SE", "NORWAY": "NO", "NOR": "NO",
        "SWITZERLAND": "CH", "CHE": "CH", "ESTONIA": "EE", "EST": "EE", "LATVIA": "LV", "LVA": "LV",
        "CZECHIA": "CZ", "CZECH REPUBLIC": "CZ", "CZE": "CZ", "LUXEMBOURG": "LU", "LUX": "LU",
        "CANADA": "CA", "CAN": "CA", "NEW ZEALAND": "NZ", "NZL": "NZ", "UNITED STATES": "US", "USA": "US",
    }
    s = aliases.get(s, s)
    return s if s in set(TARGET_COUNTRIES) | {"GB"} else ""


def infer_country(rec: dict) -> str:
    for key in ("country_code", "country", "buyer_country", "iso_country", "jurisdiction_country"):
        code = norm_code(rec.get(key))
        if code:
            return code
    buyer = rec.get("buyer")
    if isinstance(buyer, dict):
        for key in ("country_code", "country", "countryCode", "iso_country"):
            code = norm_code(buyer.get(key))
            if code:
                return code
    for raw in (rec.get("portal"), rec.get("portal_key"), rec.get("source"), rec.get("selection_portal"), rec.get("source_portal")):
        portal = str(raw or "").strip().upper()
        if portal in PORTAL_COUNTRY:
            return PORTAL_COUNTRY[portal]
    cid = str(rec.get("candidate_id") or "")
    for prefix, code in PREFIX_COUNTRY:
        if cid.startswith(prefix):
            return code
    return ""


def freshness(rec: dict) -> str:
    for key in ("updated_at", "updated", "publication_date", "published_at", "published", "notice_date", "deadline_utc", "deadline"):
        if rec.get(key):
            return str(rec[key])
    return ""


def cmd_sample(args):
    out = Path(args.out_dir)
    selections = out / "selections"
    selections.mkdir(parents=True, exist_ok=True)
    targets = [x.strip() for x in args.countries.split(",") if x.strip()]
    buckets = defaultdict(list)
    observed = Counter()
    for rec in load_jsonl(Path(args.candidates)):
        country = infer_country(rec)
        if country:
            observed[country] += 1
        if country not in targets:
            continue
        cid = str(rec.get("candidate_id") or "").strip()
        if cid:
            buckets[country].append(rec)
    matrix, inventory = [], []
    for country in targets:
        rows = buckets.get(country, [])
        rows.sort(key=lambda r: (freshness(r), str(r.get("candidate_id") or "")), reverse=True)
        chosen = rows[: args.per_country]
        path = selections / f"{country}.jsonl"
        with path.open("w", encoding="utf-8") as f:
            for rec in chosen:
                f.write(json.dumps({"candidate_id": rec["candidate_id"]}, ensure_ascii=False) + "\n")
        inventory.append({"country": country, "available": len(rows), "sampled": len(chosen), "selection": str(path), "candidate_ids": [str(r.get("candidate_id") or "") for r in chosen]})
        if chosen:
            matrix.append({"country": country, "selection_file": path.name, "count": len(chosen)})
    (out / "inventory.json").write_text(json.dumps(inventory, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "matrix.json").write_text(json.dumps({"include": matrix}, separators=(",", ":")), encoding="utf-8")
    print(json.dumps({"targets": len(targets), "countries_with_candidates": len(matrix), "sampled_total": sum(x["count"] for x in matrix), "per_country_target": args.per_country, "observed_country_counts": dict(observed)}, indent=2))


def find_manifests(root: Path):
    for p in root.rglob("manifest.json"):
        try:
            obj = json.loads(p.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        if isinstance(obj, dict):
            yield obj


def classify(status: str, files: int) -> str:
    s = status.upper()
    if s == "DOWNLOADED_PUBLIC" and files > 0:
        return "DOWNLOADED_PUBLIC"
    if s in STATUS_BARRIER:
        return "LEGITIMATE_BARRIER"
    if s in STATUS_NO_PUBLIC:
        return "NO_PUBLIC_FILE_OR_ROUTE"
    if s in STATUS_RETRYABLE or "TIMEOUT" in s or "ERROR" in s:
        return "ERROR_RETRYABLE"
    return "OTHER"


def cmd_summarize_country(args):
    queue = list(load_jsonl(Path(args.queue)))
    batch_path = Path(args.out) / "batch_results.json"
    batch = json.loads(batch_path.read_text(encoding="utf-8")) if batch_path.exists() else []
    by_id = {str(x.get("candidate_id") or ""): x for x in batch if isinstance(x, dict)}
    manifest_by_id = {}
    for m in find_manifests(Path(args.out)):
        cid = str(m.get("candidate_id") or m.get("id") or "")
        if cid:
            manifest_by_id[cid] = m
    rows, classes, status_counts = [], Counter(), Counter()
    total_files = 0
    total_seconds = 0.0
    promoted = 0
    for q in queue:
        cid = str(q.get("candidate_id") or "")
        b = by_id.get(cid, {})
        m = manifest_by_id.get(cid, {})
        status = str(m.get("status") or b.get("status") or "MISSING_RESULT").upper()
        files = len(m.get("files") or []) if isinstance(m, dict) else 0
        klass = classify(status, files)
        elapsed = float(b.get("elapsed_seconds") or 0)
        scheduler = m.get("scheduler_v20") if isinstance(m, dict) else {}
        was_promoted = bool(isinstance(scheduler, dict) and scheduler.get("browser_skipped"))
        promoted += int(was_promoted)
        rows.append({"candidate_id": cid, "status": status, "class": klass, "files": files, "elapsed_seconds": round(elapsed, 3), "http_probe_promoted": was_promoted})
        classes[klass] += 1
        status_counts[status] += 1
        total_files += files
        total_seconds += elapsed
    n = len(queue)
    downloaded = classes["DOWNLOADED_PUBLIC"]
    barriers = classes["LEGITIMATE_BARRIER"]
    retrieval_rate = downloaded / n if n else 0
    handled_rate = (downloaded + barriers) / n if n else 0
    confidence = "HIGH" if n >= 10 else "MEDIUM" if n >= 5 else "LOW"
    grade = "A" if retrieval_rate >= 0.75 else "B" if retrieval_rate >= 0.50 else "C" if retrieval_rate >= 0.25 else "D-GATED" if handled_rate >= 0.75 else "D"
    summary = {
        "country": args.country, "sample_size": n, "downloaded_public": downloaded, "legitimate_barrier": barriers,
        "no_public_file_or_route": classes["NO_PUBLIC_FILE_OR_ROUTE"], "retryable_error": classes["ERROR_RETRYABLE"], "other": classes["OTHER"],
        "retrieval_rate": round(retrieval_rate, 4), "handled_rate": round(handled_rate, 4), "unique_manifest_files": total_files,
        "candidate_seconds": round(total_seconds, 3), "http_probe_promoted": promoted, "confidence": confidence, "grade": grade,
        "status_counts": dict(status_counts), "rows": rows,
    }
    Path(args.summary).write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "rows"}, indent=2, ensure_ascii=False))


def cmd_aggregate(args):
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
    total_dl = sum(int(s.get("downloaded_public") or 0) for s in summaries)
    total_barrier = sum(int(s.get("legitimate_barrier") or 0) for s in summaries)
    payload = {"countries_tested": len(summaries), "sample_size_total": total_n, "downloaded_public_total": total_dl, "legitimate_barrier_total": total_barrier, "overall_retrieval_rate": round(total_dl / total_n, 4) if total_n else 0, "overall_handled_rate": round((total_dl + total_barrier) / total_n, 4) if total_n else 0, "countries": summaries}
    (out / "report.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    fields = ["country", "sample_size", "downloaded_public", "legitimate_barrier", "no_public_file_or_route", "retryable_error", "retrieval_rate", "handled_rate", "unique_manifest_files", "candidate_seconds", "http_probe_promoted", "confidence", "grade"]
    with (out / "report.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for s in summaries:
            w.writerow({k: s.get(k) for k in fields})
    md = ["# DCE Country Validation", "", f"Countries tested: **{len(summaries)}**  ", f"Real tender candidates: **{total_n}**  ", f"Downloaded public DCE: **{total_dl}** ({payload['overall_retrieval_rate']:.1%})  ", f"Downloaded or correctly stopped at legitimate gate: **{total_dl + total_barrier}** ({payload['overall_handled_rate']:.1%})", "", "| Country | N | DCE | Gate | No public/route | Retryable | Retrieval | Handled | HTTP→no browser | Grade |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
    for s in summaries:
        md.append(f"| {s.get('country')} | {s.get('sample_size')} | {s.get('downloaded_public')} | {s.get('legitimate_barrier')} | {s.get('no_public_file_or_route')} | {s.get('retryable_error')} | {float(s.get('retrieval_rate') or 0):.0%} | {float(s.get('handled_rate') or 0):.0%} | {s.get('http_probe_promoted')} | {s.get('grade')} |")
    md += ["", "Notes:", "- `DOWNLOADED_PUBLIC` requires at least one persisted file record in the candidate manifest.", "- `LEGITIMATE_BARRIER` means the resolver reached an auth/CAPTCHA/registration/interest/controlled-document boundary and stopped rather than bypassing it.", "- Small samples are marked medium/low confidence; this benchmark measures the current live corpus, not every tender ever published in the jurisdiction."]
    (out / "REPORT.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in payload.items() if k != "countries"}, indent=2))


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("sample")
    p.add_argument("--candidates", required=True)
    p.add_argument("--out-dir", required=True)
    p.add_argument("--per-country", type=int, default=12)
    p.add_argument("--countries", default=",".join(TARGET_COUNTRIES))
    p.set_defaults(func=cmd_sample)
    p = sp.add_parser("summarize-country")
    p.add_argument("--country", required=True)
    p.add_argument("--queue", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--summary", required=True)
    p.set_defaults(func=cmd_summarize_country)
    p = sp.add_parser("aggregate")
    p.add_argument("--inputs", nargs="+", required=True)
    p.add_argument("--out-dir", required=True)
    p.set_defaults(func=cmd_aggregate)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
