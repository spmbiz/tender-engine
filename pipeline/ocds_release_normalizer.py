from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any


def clean(v: Any) -> str:
    return " ".join(str(v or "").split())


def parse_dt(v: Any) -> datetime | None:
    s = clean(v)
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        try:
            return datetime.fromisoformat(s[:10]).replace(tzinfo=timezone.utc)
        except Exception:
            return None


def raw_hash(obj: Any) -> str:
    payload = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def docs_from_release(release: dict[str, Any]) -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    seen: set[str] = set()
    containers: list[Any] = [
        (release.get("tender") or {}).get("documents"),
        (release.get("planning") or {}).get("documents"),
    ]
    for contract in release.get("contracts") or []:
        if isinstance(contract, dict):
            containers.append(contract.get("documents"))
            implementation = contract.get("implementation") or {}
            if isinstance(implementation, dict):
                containers.append(implementation.get("documents"))
    for arr in containers:
        if not isinstance(arr, list):
            continue
        for doc in arr:
            if not isinstance(doc, dict):
                continue
            url = clean(doc.get("url"))
            if not url or url in seen:
                continue
            seen.add(url)
            docs.append({
                "id": clean(doc.get("id")) or None,
                "title": clean(doc.get("title")) or None,
                "document_type": clean(doc.get("documentType")) or None,
                "url": url,
                "format": clean(doc.get("format")) or None,
                "date_published": clean(doc.get("datePublished")) or None,
            })
    return docs


def cpv_codes(release: dict[str, Any]) -> list[str]:
    tender = release.get("tender") or {}
    values: list[str] = []
    candidates = [tender.get("classification")]
    for item in tender.get("items") or []:
        if isinstance(item, dict):
            candidates.extend([item.get("classification"), item.get("classifications")])
    for c in candidates:
        if isinstance(c, dict):
            cid = clean(c.get("id"))
            if cid and cid not in values:
                values.append(cid)
        elif isinstance(c, list):
            for x in c:
                if isinstance(x, dict):
                    cid = clean(x.get("id"))
                    if cid and cid not in values:
                        values.append(cid)
    return values


def money(v: Any) -> tuple[float | None, str | None]:
    if not isinstance(v, dict):
        return None, None
    amount = v.get("amount")
    try:
        amount_f = float(amount) if amount not in (None, "") else None
    except Exception:
        amount_f = None
    return amount_f, clean(v.get("currency")) or None


def buyer_party(release: dict[str, Any]) -> dict[str, Any]:
    buyer = release.get("buyer") or (release.get("tender") or {}).get("procuringEntity") or {}
    if not isinstance(buyer, dict):
        buyer = {}
    bid = clean(buyer.get("id"))
    name = clean(buyer.get("name"))
    party = None
    for p in release.get("parties") or []:
        if isinstance(p, dict) and bid and clean(p.get("id")) == bid:
            party = p
            break
    party = party or {}
    identifier = party.get("identifier") or {}
    contact = party.get("contactPoint") or {}
    return {
        "id": bid or None,
        "name": name or clean(party.get("name")) or None,
        "legal_name": clean(identifier.get("legalName")) if isinstance(identifier, dict) else None,
        "email": clean(contact.get("email")) if isinstance(contact, dict) else None,
        "telephone": clean(contact.get("telephone")) if isinstance(contact, dict) else None,
        "url": clean(contact.get("url")) if isinstance(contact, dict) else None,
    }


def release_to_candidate(
    release: dict[str, Any], *, source: str, portal: str, notice_url: str | None = None, now: datetime | None = None
) -> dict[str, Any] | None:
    now = now or datetime.now(timezone.utc)
    ocid = clean(release.get("ocid"))
    rid = clean(release.get("id")) or ocid
    tender = release.get("tender") or {}
    if not isinstance(tender, dict) or not rid:
        return None
    title = clean(tender.get("title")) or clean(tender.get("description"))
    if not title:
        return None
    period = tender.get("tenderPeriod") or {}
    deadline = parse_dt(period.get("endDate") if isinstance(period, dict) else None)
    published = parse_dt(release.get("date"))
    status = clean(tender.get("status")).lower()
    current = bool((deadline and deadline >= now) or (not deadline and status in {"active", "planned"}))
    amount, currency = money(tender.get("value"))
    docs = docs_from_release(release)
    buyer = buyer_party(release)
    tenderers = tender.get("tenderers") if isinstance(tender.get("tenderers"), list) else None
    return {
        "candidate_id": f"{source}:{rid}",
        "source": source,
        "portal": portal,
        "grain": "NOTICE_FIRST_TENDER",
        "notice_id": rid,
        "procedure_id": ocid or None,
        "ocid": ocid or None,
        "title": title,
        "description": clean(tender.get("description")),
        "buyer": buyer.get("name"),
        "buyer_id": buyer.get("id"),
        "buyer_contact": {k: v for k, v in buyer.items() if k not in {"name", "id"} and v},
        "deadline": deadline.isoformat() if deadline else None,
        "published": published.isoformat() if published else None,
        "current": current,
        "notice_url": notice_url,
        "cpv": cpv_codes(release),
        "estimated_value": amount,
        "currency": currency,
        "procurement_method": clean(tender.get("procurementMethod")) or None,
        "procurement_method_details": clean(tender.get("procurementMethodDetails")) or None,
        "tender_status": status or None,
        "tenderers_received_observed": len(tenderers) if tenderers is not None else None,
        "route": {
            "document_urls": [d["url"] for d in docs],
            "documents": docs,
            "route_status": "DOWNLOADED_PUBLIC_ROUTE_DISCOVERED" if docs else "NO_PUBLIC_FILE_OBSERVED_IN_RELEASE",
        },
        "source_release_hash": raw_hash(release),
        "observed_at": now.isoformat(),
    }


def release_awards(release: dict[str, Any], *, source: str, portal: str, notice_url: str | None = None) -> list[dict[str, Any]]:
    ocid = clean(release.get("ocid"))
    buyer = buyer_party(release)
    tender = release.get("tender") or {}
    tenderers = tender.get("tenderers") if isinstance(tender, dict) and isinstance(tender.get("tenderers"), list) else None
    out: list[dict[str, Any]] = []
    for award in release.get("awards") or []:
        if not isinstance(award, dict):
            continue
        award_id = clean(award.get("id"))
        amount, currency = money(award.get("value"))
        suppliers = award.get("suppliers") if isinstance(award.get("suppliers"), list) else []
        base = {
            "grain": "AWARD",
            "source": source,
            "portal": portal,
            "ocid": ocid or None,
            "award_id": award_id or None,
            "award_title": clean(award.get("title")) or None,
            "award_status": clean(award.get("status")) or None,
            "amount": amount,
            "currency": currency,
            "buyer_id": buyer.get("id"),
            "buyer_name": buyer.get("name"),
            "tenderers_received_observed": len(tenderers) if tenderers is not None else None,
            "notice_url": notice_url,
            "source_release_hash": raw_hash(release),
        }
        if suppliers:
            for supplier in suppliers:
                if not isinstance(supplier, dict):
                    continue
                out.append({**base, "supplier_id": clean(supplier.get("id")) or None, "supplier_name": clean(supplier.get("name")) or None})
        else:
            out.append({**base, "supplier_id": None, "supplier_name": None})
    return out
