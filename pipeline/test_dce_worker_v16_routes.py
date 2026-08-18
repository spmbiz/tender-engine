from __future__ import annotations

from build_matrix import BROWSER_PORTALS, SUPPORTED, resolve_dce_portal
from dce_worker_v16 import _za_ocid
from ocds_release_normalizer import docs_from_release


def main() -> None:
    for portal in ("ZA_ETENDERS", "ZA_ETENDERS_OCDS"):
        assert portal in SUPPORTED
        assert portal not in BROWSER_PORTALS

    candidate = {
        "candidate_id": "ZA_ETENDERS_OCDS:ocds-9t57fa-165805-2026-08-17",
        "source": "ZA_ETENDERS_OCDS",
        "portal": "ZA_ETENDERS",
        "ocid": "ocds-9t57fa-165805",
        "notice_url": "https://ocds-api.etenders.gov.za/api/OCDSReleases/release/ocds-9t57fa-165805",
        "route": {"document_urls": []},
    }
    portal, raw = resolve_dce_portal(candidate)
    assert portal == "ZA_ETENDERS", (portal, raw)
    assert _za_ocid(candidate) == "ocds-9t57fa-165805"

    legacy = {
        "candidate_id": "ZA_ETENDERS_OCDS:ocds-9t57fa-165805-2026-08-17",
        "source": "ZA_ETENDERS_OCDS",
        "portal": "ZA_ETENDERS_OCDS",
    }
    assert _za_ocid(legacy) == "ocds-9t57fa-165805"

    release = {
        "tender": {
            "documents": [
                {
                    "id": "spec",
                    "title": "Bid specification",
                    "documentType": "tenderNotice",
                    "url": "https://www.etenders.gov.za/Home/Download/?blobName=spec.pdf",
                    "format": "application/pdf",
                }
            ]
        },
        "planning": {
            "documents": [
                {
                    "id": "plan",
                    "title": "Planning document",
                    "url": "https://example.test/plan.pdf",
                }
            ]
        },
    }
    docs = docs_from_release(release)
    assert [d["id"] for d in docs] == ["spec", "plan"], docs
    assert docs[0]["url"].startswith("https://www.etenders.gov.za/")
    print({"za_http_portals": 2, "ocid": _za_ocid(candidate), "docs": len(docs), "status": "ok"})


if __name__ == "__main__":
    main()
