from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(__file__))
PIPELINE = os.path.join(ROOT, "pipeline")
if PIPELINE not in sys.path:
    sys.path.insert(0, PIPELINE)

import dce_worker as base
import dce_worker_v21 as v21


def main() -> None:
    cases = [
        (
            {
                "candidate_id": "CZ-NEN:N006-24-V00026710",
                "portal": "CZ_NIPEZ",
                "notice_url": "https://nen.nipez.cz/verejne-zakazky/detail-zakazky/N006-24-V00026710",
                "route": {"detail_url": "https://nen.nipez.cz/verejne-zakazky/detail-zakazky/N006-24-V00026710"},
            },
            "https://nen.nipez.cz/verejne-zakazky/detail-zakazky/N006-24-V00026710/zadavaci-dokumentace",
        ),
        (
            {
                "candidate_id": "CZ-NEN:N006-26-V00009433",
                "portal": "CZ_NIPEZ_PUBLIC",
                "route": {"documents_url": "https://nen.nipez.cz/verejne-zakazky/detail-zakazky/N006-26-V00009433/zadavaci-dokumentace?foo=bar"},
            },
            "https://nen.nipez.cz/verejne-zakazky/detail-zakazky/N006-26-V00009433/zadavaci-dokumentace",
        ),
    ]
    for candidate, expected in cases:
        got = v21.nen_documents_url(candidate)
        assert got == expected, (candidate, got, expected)

    assert v21.NEN_DOWNLOAD_ALL_RE.search("Stáhnout všechny přílohy")
    assert v21.NEN_DOWNLOAD_ALL_RE.search("Download all attachments")
    assert base.ADAPTERS["CZ_NIPEZ"] is v21.adapter_cz_nen_v21
    assert base.ADAPTERS["CZ_NIPEZ_PUBLIC"] is v21.adapter_cz_nen_v21

    no_route = {"candidate_id": "CZ:other", "portal": "CZ_NIPEZ", "notice_url": "https://example.org/tender/1"}
    assert v21.nen_documents_url(no_route) is None

    print({
        "worker": "v21",
        "canonical_nen_routes": len(cases),
        "public_download_all_control": True,
        "registered_portals": ["CZ_NIPEZ", "CZ_NIPEZ_PUBLIC"],
        "status": "ok",
    })


if __name__ == "__main__":
    main()
