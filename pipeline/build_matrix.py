from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

# Portals in this set require Playwright/browser-capable shards for their primary
# DCE route. US_SAM/US_SAM_BULK deliberately are NOT here: live no-Playwright
# canary 31914758322 proved SAM's public v3 resources endpoint can resolve and
# download real public attachments directly over HTTP.
#
# GENERIC_PUBLIC_PAGE is browser-capable by design: it tries HTTP first and then
# a JS-rendered page when static anchors are absent. Keeping it in the HTTP lane
# silently disabled that fallback on shards without Playwright.
BROWSER_PORTALS = {
    "TED", "IRELAND_ETENDERS", "FR_PLACE", "LUX_PMP", "SCOTLAND_PCS",
    "CA_CANADABUYS", "QC_SEAO", "DE_DOE", "FR_BOAMP", "NZ_GETS", "AU_AUSTENDER",
    "NL_TENDERNED", "NL_TENDERNED_RSS", "CH_SIMAP", "LV_IUB",
    "NO_DOFFIN", "PL_EZAMOWIENIA", "PL_BZP", "GR_KHMDHS", "ES_PLACSP", "FI_HILMA",
    "PT_BASE_OPEN", "PT_BASE", "DK_UDBUD", "DK_UDBUD_PUBLIC", "CZ_ZAKAZKY_GOV", "CZ_NIPEZ",
    "CYPRUS_EPPS", "LITHUANIA_EPPS", "MALTA_EPPS",
    "SI_EJN", "SK_UVO", "EE_RHR", "BELGIUM_PUBLIC", "HU_EKR", "RO_SEAP",
    "AT_OGD", "BG_AOP", "HR_EOJN", "SE_PUBLIC", "IS_RIKISKAUP",
    "DE_DTVP", "FR_AWS", "BE_EPROC", "DE_EVERGABE",
    "GENERIC_EPPS", "GENERIC_PUBLIC_PAGE",
    # v11-v13 named TED downstream families. These are browser-capable because the
    # public documents are frequently rendered by JS or exposed behind a safe
    # documents tab even when direct HTTP is attempted first by the worker.
    "EU_FUNDING_TENDERS", "BE_EPROC_V11", "MERCELL_S2C", "MERCELL_PUBLIC",
    "VORTAL_PUBLIC", "EU_SUPPLY_PUBLIC", "SE_CLIRA", "SE_EAVROP", "SE_TENDSIGN",
    "SE_KOMMERSANNONS", "NO_ARTIFIK", "BG_EOP_PUBLIC", "RO_SEAP_PUBLIC",
    "HU_EKR_PUBLIC", "HR_EOJN_PUBLIC", "SK_UVO_PUBLIC", "LV_EIS_PUBLIC",
    "CZ_NIPEZ_PUBLIC", "CZ_EGORDION", "CZ_ZAKAZKY_VENDOR", "GR_EPPS_PUBLIC",
    "FR_ACHATPUBLIC", "FR_MAXIMILIEN", "FR_MARCHES_SECUR", "FR_ALSACE_MARCHES",
    "FR_SAFETENDER", "ES_CATALONIA_PUBLIC", "ES_EUSKADI_PUBLIC", "ES_ANDALUCIA_PUBLIC",
    "ES_MADRID_PUBLIC", "ES_NAVARRA_PUBLIC", "IT_ACQUISTINRETEPA", "IT_ALBOFORNITORI",
    "IT_ALTOADIGE", "PT_ACINGOV", "AT_VERGABEPORTAL", "DE_SUBREPORT", "DE_VERGABE24",
    "DE_TENDER24", "DE_EVERGABE_NRW", "DE_DEUTSCHE_EVERGABE", "DE_RIB", "DE_LANDBW",
    "DE_GIZ", "DE_KFW", "DE_BWI", "DE_RLP", "DE_METROPOLERUHR", "DE_EVA", "DE_DAB",
    "PL_PLATFORMZAKUPOWA", "PL_EZAMAWIAJACY", "PL_LOGINTRADE", "PL_EB2B",
    "SAFETENDER_PUBLIC", "VEMAP_PUBLIC", "IT_TUTTOGARE", "IT_TRASPARE", "IT_MAGGIOLI",
    "IT_EPAL", "NL_TENDERNED_PUBLIC", "CH_SIMAP_PUBLIC", "DE_BI_MEDIEN",
    "ES_LAJUNTA", "DE_EVERGABE_DE", "DE_LWL", "THREEP_CLOUD", "PL_BIP_SLASKIE",
    "COMDIA_PUBLIC", "FR_E_MARCHESPUBLICS", "NETSERVER_PUBLIC",
}
SUPPORTED = BROWSER_PORTALS | {
    "US_SAM", "US_SAM_BULK",
    "UNGM", "DIRECT_HTTP", "UK_CONTRACTS_FINDER", "TED_PUBLIC_PAGE_FAST",
    "WORLD_BANK",
}

# Discovery/provider identifiers are provenance, not necessarily DCE adapter
# identifiers. This map translates only the resolver view; the original portal,
# source and selection_portal fields remain untouched in the candidate record.
PORTAL_ALIASES = {
    # Public Contracts Scotland OCDS/open-data lane -> dedicated PCS resolver.
    "PUBLIC_CONTRACTS_SCOTLAND": "SCOTLAND_PCS",
    "UK_PCS_OCDS": "SCOTLAND_PCS",
    "PCS_OCDS": "SCOTLAND_PCS",
    # World Bank has an official unauthenticated procurement-notice API and does
    # not need the fragile projects.worldbank.org browser page.
    "WORLD_BANK_PROCUREMENT": "WORLD_BANK",
    # These public web lanes still use the guarded generic public-page cascade.
    "UK_FIND_A_TENDER": "GENERIC_PUBLIC_PAGE",
    "UK_FTS_OCDS": "GENERIC_PUBLIC_PAGE",
    "LT_CVP_IS": "GENERIC_PUBLIC_PAGE",
    "LT_CVP_API": "GENERIC_PUBLIC_PAGE",
}


def _portal_token(value: object) -> str:
    """Normalize display/provider spellings without destroying provenance."""
    s = str(value or "").strip().upper()
    if not s:
        return ""
    return re.sub(r"[^A-Z0-9]+", "_", s).strip("_")


def candidate_has_public_route(candidate: dict) -> bool:
    """Whether the record contains an actual public notice/document route.

    Provider API bookkeeping endpoints are intentionally not enough. A record-only
    API row with no public document/notice landing page must not consume a browser
    shard just because `route.api_endpoint` starts with https://.
    """
    if str(candidate.get("notice_url") or "").startswith(("http://", "https://")):
        return True
    route = candidate.get("route") or {}
    if isinstance(route, dict):
        for key in ("detail_url", "document_landing_url", "documents_url", "notice_url", "public_url"):
            value = route.get(key)
            if isinstance(value, str) and value.startswith(("http://", "https://")):
                return True
        value = route.get("document_urls")
        if isinstance(value, list) and any(isinstance(u, str) and u.startswith(("http://", "https://")) for u in value):
            return True
    for doc in candidate.get("documents") or []:
        if isinstance(doc, str) and doc.startswith(("http://", "https://")):
            return True
        if isinstance(doc, dict) and str(doc.get("url") or "").startswith(("http://", "https://")):
            return True
    return False


def _explicit_record_only_without_dce(candidate: dict) -> bool:
    route = candidate.get("route") or {}
    if not isinstance(route, dict):
        return False
    mode = str(route.get("mode") or "").upper()
    state = str(route.get("route_state") or "").upper()
    if state in {"NO_PUBLIC_DOCUMENT_ROUTE_IN_API_RECORD", "NO_PUBLIC_DCE_ROUTE"}:
        return not candidate_has_public_route(candidate)
    if mode.endswith("_RECORD_ONLY"):
        return not candidate_has_public_route(candidate)
    return False


def resolve_dce_portal(candidate: dict) -> tuple[str, str]:
    """Return (resolver_portal, raw_portal) for a live candidate.

    We inspect every provenance field instead of trusting the first non-empty one:
    wide-read records can carry a human/display portal while the selection manifest
    carries the stable provider key. Known aliases win. If no adapter name is
    recognized but a real public notice/document URL exists, use the guarded generic
    public-page resolver. Explicit API-record-only rows are not fabricated into DCE.
    """
    raw_values = [
        candidate.get("resolver_portal"),
        candidate.get("portal"),
        candidate.get("portal_key"),
        candidate.get("selection_portal"),
        candidate.get("source"),
    ]
    tokens = []
    for value in raw_values:
        token = _portal_token(value)
        if token and token not in tokens:
            tokens.append(token)
    raw = tokens[0] if tokens else ""

    if _explicit_record_only_without_dce(candidate):
        return raw, raw

    for token in tokens:
        if token in SUPPORTED:
            return token, raw or token
        alias = PORTAL_ALIASES.get(token)
        if alias in SUPPORTED:
            return alias, raw or token

    if candidate_has_public_route(candidate):
        return "GENERIC_PUBLIC_PAGE", raw
    return raw, raw


def slugify(value: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", value or "candidate").strip("-")
    return (s or "candidate")[:100]


def load_lines(path: Path):
    rows = []
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if isinstance(rec, dict):
                rows.append((line_no, rec))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--queue", default="queues/dce_candidates.jsonl")
    ap.add_argument("--max-jobs", type=int, default=int(os.getenv("MAX_DCE_JOBS", "80")))
    ap.add_argument("--out", default="matrix.json")
    args = ap.parse_args()
    include = []
    skipped = []
    for line_no, rec in load_lines(Path(args.queue)):
        status = str(rec.get("status") or "QUEUED").upper()
        if status not in {"QUEUED", "READY", "DCE_PENDING", "AUTO_DCE_PREFETCH", "AUTO_DCE_PREFETCH_QWEN"}:
            skipped.append({"line": line_no, "candidate_id": rec.get("candidate_id"), "reason": f"status:{status}"})
            continue
        portal, raw_portal = resolve_dce_portal(rec)
        if portal not in SUPPORTED:
            skipped.append({"line": line_no, "candidate_id": rec.get("candidate_id"), "reason": f"unsupported:{raw_portal}"})
            continue
        cid = str(rec.get("candidate_id") or f"line-{line_no}")
        include.append({
            "line_no": line_no,
            "candidate_id": cid,
            "slug": slugify(cid),
            "portal": portal,
            "raw_portal": raw_portal,
            "needs_browser": portal in BROWSER_PORTALS,
        })
        if len(include) >= args.max_jobs:
            break
    payload = {"include": include}
    Path(args.out).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    Path("matrix_skipped.json").write_text(json.dumps(skipped, indent=2), encoding="utf-8")
    gh = os.getenv("GITHUB_OUTPUT")
    if gh:
        with open(gh, "a", encoding="utf-8") as f:
            f.write("matrix=" + json.dumps(payload, separators=(",", ":")) + "\n")
            f.write(f"count={len(include)}\n")
    print(json.dumps({"count": len(include), "matrix": payload, "skipped": skipped}, indent=2))


if __name__ == "__main__":
    main()
