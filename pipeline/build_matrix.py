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
}
SUPPORTED = BROWSER_PORTALS | {
    "US_SAM", "US_SAM_BULK",
    "UNGM", "DIRECT_HTTP", "UK_CONTRACTS_FINDER", "TED_PUBLIC_PAGE_FAST",
}

# Discovery/provider identifiers are provenance, not necessarily DCE adapter
# identifiers.  This map translates only the resolver view; the original portal,
# source and selection_portal fields remain untouched in the candidate record.
PORTAL_ALIASES = {
    # Public Contracts Scotland OCDS/open-data lane -> proven PCS resolver.
    "PUBLIC_CONTRACTS_SCOTLAND": "SCOTLAND_PCS",
    "UK_PCS_OCDS": "SCOTLAND_PCS",
    "PCS_OCDS": "SCOTLAND_PCS",
    # New open-data lanes currently use the guarded generic public-page cascade.
    # This is preferable to silently dropping them, and remains fail-closed for
    # evidence: a page hit is not DCE evidence unless an actual file is retrieved.
    "WORLD_BANK": "GENERIC_PUBLIC_PAGE",
    "WORLD_BANK_PROCUREMENT": "GENERIC_PUBLIC_PAGE",
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
    if str(candidate.get("notice_url") or "").startswith(("http://", "https://")):
        return True
    route = candidate.get("route") or {}
    if isinstance(route, dict):
        for key, value in route.items():
            if key == "document_urls" and isinstance(value, list):
                if any(isinstance(u, str) and u.startswith(("http://", "https://")) for u in value):
                    return True
            if isinstance(value, str) and value.startswith(("http://", "https://")):
                return True
    for doc in candidate.get("documents") or []:
        if isinstance(doc, str) and doc.startswith(("http://", "https://")):
            return True
        if isinstance(doc, dict) and str(doc.get("url") or "").startswith(("http://", "https://")):
            return True
    return False


def resolve_dce_portal(candidate: dict) -> tuple[str, str]:
    """Return (resolver_portal, raw_portal) for a live candidate.

    We inspect every provenance field instead of trusting the first non-empty one:
    wide-read records can carry a human/display portal while the selection manifest
    carries the stable provider key.  Known aliases win.  If no adapter name is
    recognized but a public URL exists, use the guarded generic public-page resolver
    rather than dropping the candidate before DCE.  No URL => remain unsupported.
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
