from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import dce_worker_v9 as v9


def test_collects_public_and_restricted_resource_metadata():
    payload = {
        "_embedded": {
            "opportunityAttachmentList": [
                {"attachments": [
                    {"resourceId": "public-1", "resourceName": "PWS.pdf", "access": 0},
                    {"resourceId": "restricted-1", "resourceName": "Controlled.zip", "access": 1},
                    {"resourceId": "public-2", "resourceName": "Pricing.xlsx", "access": "0"},
                ]}
            ]
        }
    }
    rows = []
    v9._collect_resource_records(payload, rows)
    assert {r["resource_id"] for r in rows} == {"public-1", "restricted-1", "public-2"}
    public = [r for r in rows if v9._is_public_access(r.get("access"))]
    assert {r["resource_id"] for r in public} == {"public-1", "public-2"}


def test_access_one_is_never_treated_as_public():
    assert v9._is_public_access(0)
    assert v9._is_public_access("0")
    assert v9._is_public_access(None)
    assert not v9._is_public_access(1)
    assert not v9._is_public_access("1")


def test_v3_download_url_is_supplier_public_route():
    url = v9.SAM_DOWNLOAD_URL.format(resource_id="abc123")
    assert url == "https://sam.gov/api/prod/opps/v3/opportunities/resources/files/abc123/download?api_key=null&token="
