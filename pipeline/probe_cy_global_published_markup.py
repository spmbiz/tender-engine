from __future__ import annotations

import html
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

OUT = Path(os.getenv("CY_GLOBAL_PUBLISHED_MARKUP_OUT", "control/cy_global_published_markup_probe.json"))
URL = "https://www.eprocurement.gov.cy/epps/notices/viewPublishedNotices.do"
UA = "Tender-Engine/7.4 (+public procurement research; Cyprus Published Notices markup inspection)"
TOKENS = (
    "pagelinks",
    "pagebanner",
    "d-446978-p",
    "d-446978-n",
    "d-446978-s",
    "50174",
    "50,174",
    "50.174",
    "Επόμε",
    "Next",
)


def clean(value):
    return " ".join(str(value or "").split())


def snippets(text: str, token: str, radius: int = 900, limit: int = 12):
    out = []
    start = 0
    lower = text.lower()
    target = token.lower()
    while len(out) < limit:
        idx = lower.find(target, start)
        if idx < 0:
            break
        out.append(text[max(0, idx - radius):min(len(text), idx + len(token) + radius)])
        start = idx + len(token)
    return out


def attrs(node):
    return {str(k): v for k, v in node.attrs.items() if k in {"id", "name", "class", "action", "method", "onclick", "href", "value", "type", "rel"}}


def main():
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,*/*"})
    errors = []
    result = {}
    try:
        response = session.get(URL, timeout=60, allow_redirects=True)
        response.raise_for_status()
        text = response.text
        soup = BeautifulSoup(text, "html.parser")
        anchors = []
        for a in soup.find_all("a", href=True):
            href = a.get("href") or ""
            onclick = a.get("onclick") or ""
            label = clean(a.get_text(" ", strip=True))
            if (
                "446978" in href
                or "446978" in onclick
                or re.search(r"next|previous|επόμε|προηγ|first|last|›|»|‹|«", label, re.I)
                or any(c in (a.get("class") or []) for c in ("next", "previous", "pagelink"))
            ):
                anchors.append({
                    "text": label,
                    "href": urljoin(response.url, href),
                    "onclick": onclick or None,
                    "attrs": attrs(a),
                })

        forms = []
        for form in soup.find_all("form"):
            serialized = str(form)
            if "446978" in serialized or "PublishedNotices" in serialized or "publishedNotices" in serialized:
                hidden = []
                for inp in form.find_all("input"):
                    name = inp.get("name") or ""
                    if "446978" in name or inp.get("type") == "hidden":
                        hidden.append({"name": name, "value": inp.get("value"), "type": inp.get("type")})
                forms.append({
                    "attrs": attrs(form),
                    "action": urljoin(response.url, form.get("action") or ""),
                    "hidden_inputs": hidden[:100],
                    "html_prefix": serialized[:5000],
                })

        script_hits = []
        for script in soup.find_all("script"):
            body = script.string or script.get_text(" ", strip=False) or ""
            if "446978" in body or "PublishedNotices" in body or "displaytag" in body.lower():
                script_hits.append(body[:8000])

        class_hits = []
        for node in soup.find_all(True):
            classes = " ".join(node.get("class") or [])
            ident = clean(node.get("id"))
            if re.search(r"page|pager|displaytag|pagination", classes + " " + ident, re.I):
                class_hits.append({
                    "tag": node.name,
                    "attrs": attrs(node),
                    "text": clean(node.get_text(" ", strip=True))[:3000],
                    "html": str(node)[:6000],
                })

        token_snippets = {token: snippets(text, token) for token in TOKENS if token.lower() in text.lower()}
        long_numbers = sorted({
            int(re.sub(r"\D", "", raw))
            for raw in re.findall(r"\b\d[\d,. ]{3,}\b", clean(soup.get_text(" ", strip=True)))
            if re.sub(r"\D", "", raw)
        }, reverse=True)[:50]

        result = {
            "status": response.status_code,
            "final_url": response.url,
            "bytes": len(response.content),
            "title": clean(soup.title.get_text(" ", strip=True)) if soup.title else None,
            "anchors": anchors[:200],
            "forms": forms[:30],
            "script_hits": script_hits[:30],
            "pager_markup_hits": class_hits[:50],
            "token_snippets": token_snippets,
            "largest_visible_numbers": long_numbers,
        }
    except Exception as exc:
        errors.append({"error": repr(exc)})

    payload = {
        "schema": "CY_EPPS_GLOBAL_PUBLISHED_MARKUP_PROBE_V1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "url": URL,
        "result": result,
        "errors": errors,
        "pass": bool(not errors and result.get("status") == 200 and (result.get("anchors") or result.get("forms") or result.get("token_snippets"))),
        "semantics": (
            "Read-only markup inspection of the national Cyprus Published Notices page to discover the publisher's own pagination mechanism. "
            "It records pager-related anchors, forms, scripts, classes and bounded HTML snippets; it does not synthesize or execute a page-number request."
        ),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    if not payload["pass"]:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
