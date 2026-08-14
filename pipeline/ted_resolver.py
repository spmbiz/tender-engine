from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from urllib.parse import parse_qs, urlparse

import requests

TED_SEARCH = "https://api.ted.europa.eu/v3/notices/search"
FILE_RE = re.compile(r"\.(?:pdf|zip|docx?|xlsx?|xls|pptx?|csv|7z)(?:$|[?#])", re.I)
DIRECT_ROUTE_FIELDS = [
    "document-url-lot",
    "document-url-part",
    "document-restricted-url-lot",
    "document-restricted-url-part",
    "submission-url-lot",
    "tool-atypical-url-lot",
    "tool-url-part",
]


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def collect_urls(value):
    out = []
    if isinstance(value, str):
        if value.startswith(("http://", "https://")):
            out.append(value)
    elif isinstance(value, dict):
        for v in value.values():
            out.extend(collect_urls(v))
    elif isinstance(value, list):
        for v in value:
            out.extend(collect_urls(v))
    return out


def extract_bt15(xml_bytes: bytes):
    root = ET.fromstring(xml_bytes)
    refs = []
    all_uris = []
    for el in root.iter():
        if local(el.tag) == "URI" and el.text:
            text = el.text.strip()
            if text.startswith(("http://", "https://")):
                all_uris.append(text)
    for ref in root.iter():
        if local(ref.tag) != "CallForTendersDocumentReference":
            continue
        rec = {"document_types": [], "ids": [], "uris": []}
        for x in ref.iter():
            name = local(x.tag)
            text = (x.text or "").strip()
            if not text:
                continue
            if name == "DocumentType":
                rec["document_types"].append(text)
            elif name == "ID":
                rec["ids"].append(text)
            elif name == "URI" and text.startswith(("http://", "https://")):
                rec["uris"].append(text)
        if rec["uris"]:
            refs.append(rec)
    return refs, list(dict.fromkeys(all_uris))


def epps_route(url: str) -> dict:
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    rid = (qs.get("resourceId") or qs.get("resourceid") or [None])[0]
    if not rid:
        m = re.search(r"resourceId=(\d+)", url, re.I)
        rid = m.group(1) if m else None
    route = {"detail_url": url, "base_url": f"{parsed.scheme}://{parsed.netloc}"}
    if rid:
        route["resource_id"] = rid
    return route


def classify_downstream(url: str):
    low = url.lower()
    parsed = urlparse(url)
    host = parsed.netloc.lower().split(":")[0]
    qs = parse_qs(parsed.query)
    if "etenders.gov.ie" in low:
        return "IRELAND_ETENDERS", epps_route(url)
    if "eprocurement.gov.cy" in low and "/epps/" in low:
        return "CYPRUS_EPPS", epps_route(url)
    if "viesiejipirkimai.lt" in low and "/epps/" in low:
        return "LITHUANIA_EPPS", epps_route(url)
    if "marches-publics.gouv.fr" in low:
        m = re.search(r"/consultation/(\d+)", url)
        consultation_id = m.group(1) if m else (qs.get("id") or [None])[0]
        org = (qs.get("orgAcronyme") or qs.get("orgacronyme") or [None])[0]
        route = {"detail_url": url}
        if consultation_id:
            route["consultation_id"] = consultation_id
        if org:
            route["org_acronym"] = org
        if "telechargementdce" in low or "demandetelechargementdce" in low:
            route["documents_url"] = url
        return "FR_PLACE", route
    if "pmp.b2g.etat.lu" in low:
        return "LUX_PMP", {"documents_url": url}
    if "publiccontractsscotland.gov.uk" in low:
        return "SCOTLAND_PCS", {"detail_url": url}
    if "ungm.org" in low:
        m = re.search(r"/Notice/(\d+)", url, re.I)
        return "UNGM", {"notice_id": m.group(1) if m else None, "detail_url": url}

    # High-volume TED downstream portals. These are kept as explicit portal keys so
    # retrieval can be measured independently and barriers remain visible.
    if host in {"www.dtvp.de", "dtvp.de"}:
        return "DE_DTVP", {"detail_url": url}
    if host.endswith("marches-publics.info") or host.endswith("aws-achat.info"):
        return "FR_AWS", {"detail_url": url}
    if host in {"www.publicprocurement.be", "publicprocurement.be", "eprocurement.gov.be", "www.eprocurement.gov.be"}:
        return "BE_EPROC", {"detail_url": url}
    if host in {"contrataciondelestado.es", "www.contrataciondelestado.es"}:
        return "ES_PLACSP", {"detail_url": url}
    if host in {"www.evergabe-online.de", "evergabe-online.de"}:
        return "DE_EVERGABE", {"detail_url": url}

    if FILE_RE.search(url):
        return "DIRECT_HTTP", {"document_urls": [url]}
    return None, {"detail_url": url}


def append_downstream(result: dict, urls):
    existing = {x.get("url") for x in result["downstream"]}
    for url in urls:
        if not url or url in existing:
            continue
        low = url.lower()
        if "ted.europa.eu" in low and re.search(r"/notice/|/en/notice", low):
            continue
        portal, subroute = classify_downstream(url)
        result["downstream"].append({"url": url, "portal": portal, "route": subroute})
        existing.add(url)


def resolve_ted_candidate(candidate: dict, timeout: int = 60) -> dict:
    route = candidate.get("route") or {}
    publication_number = str(
        route.get("publication_number")
        or candidate.get("publication_number")
        or str(candidate.get("candidate_id") or "").removeprefix("TED:")
    ).strip()
    result = {
        "publication_number": publication_number,
        "search_api_status": None,
        "search_api_document_urls": [],
        "search_api_submission_urls": [],
        "xml_candidates": [],
        "xml_url_used": None,
        "bt15": [],
        "all_uris": [],
        "downstream": [],
        "error": None,
    }
    if not publication_number:
        result["error"] = "missing_publication_number"
        return result

    session = requests.Session()
    session.headers.update({"User-Agent": "Tender-Engine/2.0 public procurement research"})
    body = {
        "query": f"publication-number = {publication_number}",
        "fields": ["publication-number", *DIRECT_ROUTE_FIELDS],
        "page": 1,
        "limit": 10,
        "scope": "ALL",
        "checkQuerySyntax": False,
        "paginationMode": "PAGE_NUMBER",
    }
    data = None
    try:
        r = session.post(TED_SEARCH, json=body, timeout=timeout)
        result["search_api_status"] = r.status_code
        if r.ok:
            data = r.json()
            notices = data.get("notices") or []
            if notices:
                notice = notices[0]
                doc_urls = []
                submission_urls = []
                for field in DIRECT_ROUTE_FIELDS:
                    vals = collect_urls(notice.get(field))
                    if field.startswith("document-"):
                        doc_urls.extend(vals)
                    else:
                        submission_urls.extend(vals)
                result["search_api_document_urls"] = list(dict.fromkeys(doc_urls))
                result["search_api_submission_urls"] = list(dict.fromkeys(submission_urls))
                append_downstream(result, result["search_api_document_urls"])
                if not result["downstream"]:
                    append_downstream(result, result["search_api_submission_urls"])
            urls = collect_urls(data)
            xmls = [u for u in urls if re.search(r"(?:/xml(?:$|[?#])|\.xml(?:$|[?#]))", u, re.I)]
            result["xml_candidates"].extend(xmls)
    except Exception as exc:
        result["error"] = f"search_api:{exc!r}"

    if result["downstream"]:
        return result

    result["xml_candidates"].append(f"https://ted.europa.eu/en/notice/{publication_number}/xml")
    result["xml_candidates"] = list(dict.fromkeys(result["xml_candidates"]))

    xml_bytes = None
    for xml_url in result["xml_candidates"]:
        try:
            rr = session.get(xml_url, timeout=timeout, allow_redirects=True)
            if rr.ok and rr.content and b"<" in rr.content[:500]:
                ET.fromstring(rr.content)
                xml_bytes = rr.content
                result["xml_url_used"] = rr.url
                break
        except Exception:
            continue

    if not xml_bytes:
        result["error"] = (result["error"] + "; " if result["error"] else "") + "no_direct_bt15_and_no_parseable_xml"
        return result

    try:
        refs, uris = extract_bt15(xml_bytes)
        result["bt15"] = refs
        result["all_uris"] = uris
    except Exception as exc:
        result["error"] = (result["error"] + "; " if result["error"] else "") + f"xml_parse:{exc!r}"
        return result

    ordered = []
    for ref in result["bt15"]:
        ordered.extend(ref.get("uris") or [])
    ordered.extend(result["all_uris"])
    append_downstream(result, ordered)
    return result
