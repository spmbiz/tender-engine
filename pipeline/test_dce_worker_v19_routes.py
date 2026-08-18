from __future__ import annotations

from dce_worker_v19 import _sk_documents_url, _strong_sk_urls

HTML = '''
<html><body>
<a href="/verejne-obstaravanie/cyklus-a-dokumenty">Dokumenty</a>
<a href="/vyhladavanie/vyhladavanie-zakaziek/dokumenty/558849?sort=nazov&sort-dir=ASC">sort</a>
<a href="/vyhladavanie/vyhladavanie-zakaziek/dokumenty/558849?tx_web2pdf_pi1%5Baction%5D=generatePdfLink&cHash=abc">Export PDF</a>
<a href="/files/specification.pdf">Specification</a>
</body></html>
'''


def main() -> None:
    candidate = {
        "portal": "SK_UVO_PUBLIC",
        "notice_url": "https://www.uvo.gov.sk/vyhladavanie/vyhladavanie-zakaziek/detail/558849",
        "route": {
            "detail_url": "https://www.uvo.gov.sk/vyhladavanie/vyhladavanie-zakaziek/detail/558849",
            "documents_url": "https://www.uvo.gov.sk/vyhladavanie/vyhladavanie-zakaziek/dokumenty/558849",
        },
    }
    docs = _sk_documents_url(candidate)
    assert docs == "https://www.uvo.gov.sk/vyhladavanie/vyhladavanie-zakaziek/dokumenty/558849"
    urls = _strong_sk_urls(HTML, docs, "558849")
    assert len(urls) == 2, urls
    assert any("generatePdfLink" in u for u in urls), urls
    assert any(u.endswith("specification.pdf") for u in urls), urls
    assert not any("sort=" in u for u in urls), urls
    assert not any("cyklus-a-dokumenty" in u for u in urls), urls
    print({"sk_uvo_strong_urls": len(urls), "navigation_filtered": True, "status": "ok"})


if __name__ == "__main__":
    main()
