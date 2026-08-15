#!/usr/bin/env python3
from __future__ import annotations

"""Resolve historical BOAMP notice URLs to authoritative downstream DCE routes.

Uses the official BOAMP Explore API rather than scraping rendered notice HTML.
This is research routing only: it never authenticates, bypasses CAPTCHA, or creates
a bid verdict. Structured DCE/submission URLs found in the full notice payload are
preserved with their JSON path provenance.
"""

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlparse

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
try:
    from portal_routes import route_for
except Exception:  # fail-soft for standalone use
    route_for = lambda _url: None

API = "https://www.boamp.fr/api/explore/v2.1/catalog/datasets/piamp_qualification_mp/records"
IDWEB_RE = re.compile(r"idweb[:=](?:%22|\")?([0-9]{2}-[0-9]+)", re.I)
URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.I)
AUTH_RE = re.compile(r"\blog[ -]?in\b|connexion|se connecter|identification|cr[eé]er un compte|anmelden", re.I)
CAPTCHA_RE = re.compile(r"captcha|recaptcha|code de s[eé]curit[eé]|security code", re.I)
INTEREST_RE = re.compile(r"manifester.*int[eé]r[eê]t|register interest|express interest", re.I)
FILE_RE = re.compile(r"\.(?:pdf|zip|docx?|xlsx?|xls|pptx?|7z)(?:$|[?#])", re.I)


def load_jsonl(path: Path) -> list[dict]:
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        if isinstance(obj, dict):
            out.append(obj)
    return out


def idweb_from(rec: dict) -> str:
    for value in (rec.get("notice_url"), rec.get("primary_source_url"), (rec.get("route") or {}).get("detail_url")):
        m = IDWEB_RE.search(str(value or ""))
        if m:
            return m.group(1)
    return ""


def maybe_json(value):
    if isinstance(value, str):
        s = value.strip()
        if s[:1] in "[{":
            try:
                return json.loads(s)
            except Exception:
                return value
    return value


def walk_urls(obj, path=""):
    obj = maybe_json(obj)
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{path}.{k}" if path else str(k)
            yield from walk_urls(v, p)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk_urls(v, f"{path}[{i}]")
    elif isinstance(obj, str):
        for url in URL_RE.findall(obj):
            yield path, url.rstrip("),.;]}")


def route_score(path: str, url: str) -> int:
    p = path.casefold()
    host = (urlparse(url).hostname or "").casefold()
    score = 0
    if "callfortendersdocumentreference" in p:
        score += 120
    if "urldocconsul" in p:
        score += 120
    if "document" in p or "dce" in p:
        score += 65
    if p.endswith(".uri") or "externalreference" in p:
        score += 45
    if "tenderrecipientparty" in p or "endpointid" in p:
        score += 35
    if "communication" in p:
        score += 25
    if FILE_RE.search(url):
        score += 90
    if any(x in p for x in ("appeal", "mediation", "reviewbody", "additionalinformationparty")):
        score -= 120
    if host.endswith("boamp.fr"):
        score -= 100
    return score


def classify_worker_portal(url: str) -> str:
    route = route_for(url)
    if route and route.key in {"FR_AWS", "FR_PLACE", "BE_EPROC", "DE_DTVP", "DE_EVERGABE", "LUX_PMP", "IRELAND_ETENDERS"}:
        return route.key
    return "GENERIC_PUBLIC_PAGE"


def probe_url(session: requests.Session, url: str, timeout: int = 20, max_bytes: int = 400_000) -> dict:
    try:
        with session.get(url, timeout=timeout, allow_redirects=True, stream=True) as r:
            chunks = []
            total = 0
            for chunk in r.iter_content(65536):
                if not chunk:
                    continue
                take = chunk[: max(0, max_bytes - total)]
                chunks.append(take)
                total += len(take)
                if total >= max_bytes:
                    break
            body = b"".join(chunks)
            ct = (r.headers.get("content-type") or "").lower()
            cd = (r.headers.get("content-disposition") or "").lower()
            magic = body[:8]
            fileish = bool(r.ok and body and ("attachment" in cd or any(x in ct for x in ("application/pdf", "application/zip", "application/octet-stream", "application/vnd")) or magic.startswith(b"%PDF-") or magic.startswith(b"PK\x03\x04")))
            text = ""
            if not fileish and ("html" in ct or "text/" in ct or body.lstrip().startswith(b"<")):
                text = body.decode(r.encoding or "utf-8", errors="replace")
                text = re.sub(r"<script\b[^>]*>.*?</script>", " ", text, flags=re.I | re.S)
                text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
                text = re.sub(r"<[^>]+>", " ", text)
                text = re.sub(r"\s+", " ", text)[:200_000]
            if fileish:
                state = "DIRECT_FILE"
            elif r.status_code in (401, 403) or AUTH_RE.search(text):
                state = "AUTH_REQUIRED"
            elif CAPTCHA_RE.search(text):
                state = "CAPTCHA_REQUIRED"
            elif INTEREST_RE.search(text):
                state = "INTEREST_REQUIRED"
            elif r.ok:
                state = "PUBLIC_PAGE"
            elif r.status_code == 404:
                state = "NOT_FOUND"
            elif r.status_code == 429 or r.status_code >= 500:
                state = "RETRYABLE_HTTP"
            else:
                state = "HTTP_ERROR"
            return {"state": state, "http_status": r.status_code, "resolved_url": r.url, "content_type": r.headers.get("content-type"), "bytes_read": len(body)}
    except requests.Timeout:
        return {"state": "TIMEOUT", "http_status": None, "resolved_url": None, "content_type": None, "bytes_read": 0}
    except Exception as exc:
        return {"state": "ERROR", "http_status": None, "resolved_url": None, "content_type": None, "bytes_read": 0, "error": repr(exc)[:400]}


def resolve_one(session: requests.Session, rec: dict) -> tuple[dict, dict | None]:
    base = {k: rec.get(k) for k in ("candidate_id", "historical_sub_niche", "country", "buyer", "title", "publication_date", "notice_url")}
    idweb = idweb_from(rec)
    if not idweb:
        return {**base, "idweb": None, "status": "NO_IDWEB", "route_candidates": []}, None
    try:
        r = session.get(API, params={"where": f'idweb="{idweb}"', "limit": 5}, timeout=30)
        if not r.ok:
            return {**base, "idweb": idweb, "status": "API_HTTP_ERROR", "api_http_status": r.status_code, "route_candidates": []}, None
        payload = r.json()
        results = payload.get("results") or []
    except Exception as exc:
        return {**base, "idweb": idweb, "status": "API_ERROR", "error": repr(exc)[:400], "route_candidates": []}, None
    exact = next((x for x in results if str(x.get("idweb")) == idweb), None)
    if not exact:
        return {**base, "idweb": idweb, "status": "API_RECORD_NOT_FOUND", "api_result_count": len(results), "route_candidates": []}, None

    candidates = []
    seen = set()
    for path, url in walk_urls(exact.get("donnees")):
        if url in seen:
            continue
        seen.add(url)
        score = route_score(path, url)
        if score < 25:
            continue
        candidates.append({"url": url, "json_path": path, "route_score": score})
    candidates.sort(key=lambda x: (-x["route_score"], x["url"]))
    for cand in candidates[:8]:
        cand["worker_portal"] = classify_worker_portal(cand["url"])
        cand["probe"] = probe_url(session, cand["url"])

    if not candidates:
        status = "API_NOTICE_FOUND_NO_DCE_ROUTE"
        resolved = None
    else:
        best = candidates[0]
        status = "DCE_ROUTE_FOUND"
        resolved = dict(rec)
        route = dict(resolved.get("route") or {})
        route["boamp_idweb"] = idweb
        route["boamp_api_url"] = r.url
        route["detail_url"] = best["probe"].get("resolved_url") or best["url"]
        route["boamp_route_provenance"] = best["json_path"]
        route["boamp_route_candidates"] = [x["url"] for x in candidates[:8]]
        if best["probe"].get("state") == "DIRECT_FILE":
            route["document_urls"] = [best["probe"].get("resolved_url") or best["url"]]
            resolved["portal"] = "DIRECT_HTTP"
        else:
            resolved["portal"] = best["worker_portal"]
        resolved["route"] = route
        resolved["research_status"] = "HISTORICAL_DCE_ROUTE_RESOLVED"
        resolved["final_verdict_allowed"] = False

    out = {
        **base,
        "idweb": idweb,
        "status": status,
        "api_http_status": r.status_code,
        "api_record_url": r.url,
        "boamp_family": exact.get("famille"),
        "boamp_procedure": exact.get("type_procedure"),
        "boamp_deadline": exact.get("datelimitereponse"),
        "route_candidates": candidates[:8],
    }
    return out, resolved


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--queue", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    rows = [r for r in load_jsonl(Path(args.queue)) if str(r.get("portal") or "").upper() == "FR_BOAMP"]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": "Tender-Engine/HistoricalBOAMPResolver-1.0 open-data research", "Accept": "application/json,text/html,*/*"})
    results = []
    resolved = []
    for rec in rows:
        r, c = resolve_one(session, rec)
        results.append(r)
        if c:
            resolved.append(c)
    with (out / "boamp_routes.jsonl").open("w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n")
    with (out / "resolved_candidates.jsonl").open("w", encoding="utf-8") as f:
        for r in resolved:
            f.write(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n")
    states = Counter(r["status"] for r in results)
    route_domains = Counter()
    probe_states = Counter()
    by_niche = defaultdict(Counter)
    for r in results:
        by_niche[str(r.get("historical_sub_niche"))][r["status"]] += 1
        for c in r.get("route_candidates") or []:
            host = (urlparse(c["url"]).hostname or "UNKNOWN").lower()
            route_domains[host] += 1
            probe_states[str((c.get("probe") or {}).get("state") or "UNPROBED")] += 1
    summary = {
        "contract": "HISTORICAL_BOAMP_DCE_ROUTE_RESOLVER_V1",
        "input_boamp_candidates": len(rows),
        "resolved_candidates": len(resolved),
        "states": dict(states),
        "route_domains": dict(route_domains.most_common()),
        "probe_states": dict(probe_states),
        "by_subniche": {k: dict(v) for k, v in sorted(by_niche.items())},
        "official_api": API,
        "final_verdict_allowed": False,
        "note": "Official BOAMP open-data route resolution only. Downstream access gates are surfaced and never bypassed.",
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
