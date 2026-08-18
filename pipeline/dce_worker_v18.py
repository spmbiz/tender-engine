from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

import dce_worker as base
import dce_worker_v2 as v2
import dce_worker_v7 as v7
import dce_worker_v14 as v14
import dce_worker_v17 as v17  # registers the complete v17 stack first

URL_RE = re.compile(r"https?://[^\s<>\"']+", re.I)
PROCUREMENT_CONTEXT_RE = re.compile(
    r"Vergabeunterlagen|Ausschreibungsunterlagen|Beschaffungsunterlagen|"
    r"procurement documents?|tender documents?|Unterlagen.{0,80}(?:Zugang|abruf|download)|"
    r"Zugang.{0,80}Unterlagen|Vergabeplattform|e-?Vergabe",
    re.I | re.S,
)
PROCUREMENT_HOST_RE = re.compile(
    r"(?:evergabe|e-vergabe|vergabe|dtvp|bieter|tender|procure|auftrag|subreport|rib\.)",
    re.I,
)
FILE_RE = re.compile(r"\.(?:pdf|zip|docx?|xlsx?|xls|pptx?|csv|7z)(?:$|[?#])", re.I)


def _clean_url(value: str) -> str:
    return str(value or "").strip().rstrip(".,);]}>'\"")


def _rendered_de_routes_v18(url: str, out: Path, manifest: dict) -> list[tuple[int, str, str]]:
    pw = browser = context = page = None
    found: dict[str, tuple[int, str, str]] = {}
    try:
        pw, browser, context = v2.optimized_browser_context()
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2200)
        try:
            page.wait_for_load_state("networkidle", timeout=9000)
        except Exception:
            pass
        body = page.locator("body").inner_text(timeout=15000)
        if body:
            (out / "portal_page.txt").write_text(body[:1_500_000], encoding="utf-8")

        page_host = (urlparse(page.url).hostname or "").casefold()
        try:
            anchors = page.locator("a[href]").evaluate_all(
                "els => els.map(a => ({href:a.href||'', text:(a.innerText||a.textContent||'').trim()}))"
            )
        except Exception:
            anchors = []
        for item in anchors or []:
            href = _clean_url(str((item or {}).get("href") or ""))
            text = re.sub(r"\s+", " ", str((item or {}).get("text") or "")).strip()
            if not href.startswith(("http://", "https://")):
                continue
            host = (urlparse(href).hostname or "").casefold()
            score = 0
            if FILE_RE.search(href):
                score += 12
            if v14.portal_for_url_v14(href):
                score += 10
            if host and host != page_host and PROCUREMENT_HOST_RE.search(host):
                score += 8
            if PROCUREMENT_CONTEXT_RE.search(f"{text} {href}"):
                score += 8
            if score:
                prev = found.get(href)
                if prev is None or score > prev[0]:
                    found[href] = (score, href, text[:300] or "anchor")

        for match in URL_RE.finditer(body or ""):
            href = _clean_url(match.group(0))
            if not href.startswith(("http://", "https://")):
                continue
            host = (urlparse(href).hostname or "").casefold()
            if not host or host == page_host:
                continue
            start = max(0, match.start() - 350)
            end = min(len(body), match.end() + 350)
            context_text = re.sub(r"\s+", " ", body[start:end]).strip()
            score = 0
            classified = v14.portal_for_url_v14(href)
            if FILE_RE.search(href):
                score += 12
            if classified:
                score += 12
            if PROCUREMENT_HOST_RE.search(host):
                score += 8
            if PROCUREMENT_CONTEXT_RE.search(context_text):
                score += 10
            if score < 12:
                continue
            prev = found.get(href)
            if prev is None or score > prev[0]:
                found[href] = (score, href, context_text[:500] or "visible-text-url")

        rows = sorted(found.values(), key=lambda x: (-x[0], x[1]))[:50]
        manifest.setdefault("dce_method_attempts", []).append(
            {
                "method": "DE_DOE_RENDERED_TEXT_ROUTES_V18",
                "url": url,
                "resolved_url": str(page.url),
                "outcome": "LINKS_FOUND" if rows else "NO_DOCUMENT_LINKS",
                "candidate_links": [
                    {"score": score, "url": href, "context": context}
                    for score, href, context in rows
                ],
            }
        )
        return rows
    except Exception as exc:
        manifest.setdefault("dce_method_attempts", []).append(
            {
                "method": "DE_DOE_RENDERED_TEXT_ROUTES_V18",
                "url": url,
                "outcome": "ERROR",
                "error": repr(exc)[:700],
            }
        )
        return []
    finally:
        try:
            if page:
                page.close()
        except Exception:
            pass
        try:
            if browser:
                browser.close()
        except Exception:
            pass
        try:
            if pw:
                pw.stop()
        except Exception:
            pass


v7._de_browser_links = _rendered_de_routes_v18
base.ADAPTERS["DE_DOE"] = v7.adapter_germany_doe

if __name__ == "__main__":
    v2.main()
