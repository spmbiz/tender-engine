from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

BASE = "https://pmp.b2g.etat.lu"
LIST_URL = BASE + "/?AllCons=&EnCours=&page=Entreprise.EntrepriseAdvancedSearch"
OUT = Path(os.getenv("DISCOVERY_OUT", "discovery/global/LUX_PMP"))
OUT.mkdir(parents=True, exist_ok=True)
MAX_PAGES = max(1, int(os.getenv("LUX_MAX_PAGES", "10")))
NOW = datetime.now(ZoneInfo("Europe/Luxembourg"))
S = requests.Session()
S.headers.update({"User-Agent": "Tender-Engine/6.0 (+public procurement research; official PMP public pages)"})
CONSULT_RE = re.compile(r"/entreprise/consultation/(\d+)")
DATE_RE = re.compile(r"\b(\d{1,2}/\d{1,2}/\d{4})\s+(\d{1,2}:\d{2})\b")


def clean(v):
    return " ".join(str(v or "").split())


def get(url, params=None):
    for attempt in range(4):
        try:
            r = S.get(url, params=params, timeout=45, allow_redirects=True)
            if r.status_code in (408, 425, 429) or r.status_code >= 500:
                if attempt < 3:
                    time.sleep(min(10, 2 ** attempt))
                    continue
            r.raise_for_status()
            return r
        except Exception:
            if attempt == 3:
                raise
            time.sleep(min(8, 2 ** attempt))
    raise RuntimeError(url)


def parse_detail(cid: str, url: str):
    r = get(url)
    soup = BeautifulSoup(r.text, "html.parser")
    text = clean(soup.get_text(" ", strip=True))
    def after(label: str, stop_labels: tuple[str, ...]):
        m = re.search(re.escape(label) + r"\s*:\s*(.+?)\s+(?=" + "|".join(re.escape(x) + r"\s*:" for x in stop_labels) + r")", text, re.I)
        return clean(m.group(1)) if m else None

    title = after("Intitulé", ("Objet", "Organisme", "Entité publique", "Service"))
    obj = after("Objet", ("Organisme", "Entité publique", "Service", "Type d'avis", "Procédure"))
    ref = after("Référence", ("Intitulé", "Objet", "Organisme"))
    deadline = None
    m = re.search(r"Date et heure limite de remise des plis\s*:\s*(\d{1,2}/\d{1,2}/\d{4})\s+(\d{1,2}:\d{2})", text, re.I)
    if m:
        try:
            deadline = datetime.strptime(f"{m.group(1)} {m.group(2)}", "%d/%m/%Y %H:%M").replace(tzinfo=ZoneInfo("Europe/Luxembourg"))
        except ValueError:
            pass
    if deadline and deadline < NOW:
        return None

    buyer = after("Service", ("Type d'avis", "Procédure", "Catégorie principale", "Lots")) or after("Organisme", ("Entité publique", "Service", "Type d'avis"))
    cpv = None
    m = re.search(r"Code CPV\s*:\s*(\d{8})", text, re.I)
    if m:
        cpv = m.group(1)
    has_dce = bool(re.search(r"Pièces de la consultation\s+(?!Aucune pièce)(?:Dossier de soumission|.+?\b(?:Ko|Mo)\b)", text, re.I))
    return {
        "candidate_id": f"LU-PMP:{cid}",
        "source": "LUX_PMP",
        "portal": "LUX_PMP",
        "notice_id": clean(ref) or cid,
        "title": clean(title) or f"Luxembourg consultation {cid}",
        "buyer": clean(buyer) or None,
        "deadline": deadline.isoformat() if deadline else None,
        "current": True,
        "notice_url": r.url,
        "description": clean(obj) or text[:1500],
        "cpv": cpv,
        "currency": "EUR",
        "route": {
            "detail_url": r.url,
            "public_url": r.url,
            "consultation_id": cid,
            "documents_publicly_listed": has_dce,
        },
        "discovered_at": NOW.isoformat(),
    }


def list_ids():
    # The official current-opportunities view renders consultation links server-side.
    # We harvest the current list and dedupe IDs before touching detail pages.
    r = get(LIST_URL)
    soup = BeautifulSoup(r.text, "html.parser")
    ids = []
    for a in soup.find_all("a", href=True):
        m = CONSULT_RE.search(a.get("href") or "")
        if m and m.group(1) not in ids:
            ids.append(m.group(1))
    return ids


def main():
    ids = list_ids()
    # The public current page typically exposes the current result set directly.
    # MAX_PAGES is retained as a capacity guard for future pagination support.
    rows = []
    errors = []
    for cid in ids[: max(25, MAX_PAGES * 50)]:
        url = f"{BASE}/entreprise/consultation/{cid}"
        try:
            rec = parse_detail(cid, url)
            if rec:
                rows.append(rec)
        except Exception as exc:
            errors.append({"consultation_id": cid, "url": url, "error": repr(exc)})
    by_id = {r["candidate_id"]: r for r in rows}
    rows = sorted(by_id.values(), key=lambda r: (r.get("deadline") or "9999", r["candidate_id"]))
    for name in ("raw.jsonl", "current.jsonl"):
        with (OUT / name).open("w", encoding="utf-8") as f:
            for rec in rows:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    stats = {
        "source": "LUX_PMP",
        "official_url": LIST_URL,
        "list_consultation_ids": len(ids),
        "raw_materialized": len(rows),
        "current_materialized": len(rows),
        "with_public_dce_signal": sum(1 for r in rows if (r.get("route") or {}).get("documents_publicly_listed")),
        "errors": errors,
        "generated_at": NOW.isoformat(),
    }
    (OUT / "stats.json").write_text(json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(stats, indent=2, ensure_ascii=False))
    if errors and not rows:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
