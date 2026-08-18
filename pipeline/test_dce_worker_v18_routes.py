from __future__ import annotations

from dce_worker_v18 import (
    PROCUREMENT_CONTEXT_RE,
    PROCUREMENT_HOST_RE,
    _clean_url,
)


def main() -> None:
    text = (
        "Die Vergabeunterlagen stehen für einen uneingeschränkten und vollständigen "
        "direkten Zugang gebührenfrei zur Verfügung unter "
        "https://www.evergabe-online.de/tenderdetails.html?id=821416."
    )
    assert PROCUREMENT_CONTEXT_RE.search(text)
    assert PROCUREMENT_HOST_RE.search("www.evergabe-online.de")
    assert _clean_url("https://www.evergabe-online.de/tenderdetails.html?id=821416.)") == (
        "https://www.evergabe-online.de/tenderdetails.html?id=821416"
    )

    unrelated = "Datenschutz https://example.org/privacy"
    assert not PROCUREMENT_CONTEXT_RE.search(unrelated)
    assert not PROCUREMENT_HOST_RE.search("example.org")
    print({"de_doe_text_route": "strict_procurement_context", "status": "ok"})


if __name__ == "__main__":
    main()
