from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests

OUT = Path(os.getenv("IT_ANAC_PVL_BUNDLE_PROBE_OUT", "control/it_anac_pvl_bundle_probe.json"))
BASE = "https://pubblicitalegale.anticorruzione.it"
START = BASE + "/ricerca-generica"
UA = "Tender-Engine/7.1 (+public procurement research; official ANAC PVL frontend contract inspection)"
TERMS = [
    "/api/v0/avvisi",
    "dataScadenza",
    "dataPubblicazioneStart",
    "dataPubblicazioneEnd",
    "codiceScheda",
    "ricercaArchivio",
    "attivo",
    "stato",
]


def contexts(text: str, term: str, *, radius: int = 900, cap: int = 12):
    out = []
    start = 0
    while len(out) < cap:
        idx = text.find(term, start)
        if idx < 0:
            break
        left = max(0, idx - radius)
        right = min(len(text), idx + len(term) + radius)
        out.append(text[left:right])
        start = idx + len(term)
    return out


def main():
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept": "text/html,*/*"})
    result = {
        "schema": "IT_ANAC_PVL_FRONTEND_BUNDLE_CONTRACT_PROBE_V1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "start_url": START,
        "scripts": [],
        "matches": {},
        "errors": [],
    }
    try:
        landing = session.get(START, timeout=60)
        landing.raise_for_status()
        html = landing.text
        srcs = re.findall(r"<script[^>]+src=[\"']([^\"']+)[\"']", html, re.I)
        scripts = []
        for src in srcs:
            url = urljoin(START, src)
            if not url.startswith(BASE):
                continue
            try:
                response = session.get(url, timeout=90)
                response.raise_for_status()
                text = response.text
                scripts.append((url, text))
                result["scripts"].append({
                    "url": url,
                    "status": response.status_code,
                    "bytes": len(response.content),
                })
            except Exception as exc:
                result["errors"].append({"script": url, "error": repr(exc)})

        for term in TERMS:
            hits = []
            for url, text in scripts:
                found = contexts(text, term)
                if found:
                    hits.append({"script": url, "contexts": found})
            result["matches"][term] = hits
        result["landing_status"] = landing.status_code
        result["landing_bytes"] = len(landing.content)
    except Exception as exc:
        result["errors"].append({"stage": "landing", "error": repr(exc)})

    result["pass"] = bool(result["matches"].get("/api/v0/avvisi")) and not result["errors"]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if not result["pass"]:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
