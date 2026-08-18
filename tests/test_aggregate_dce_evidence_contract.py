from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))

from aggregate_dce import resolve_evidence


def evidence(contract: str, ready: bool = True) -> dict:
    return {
        "contract": contract,
        "derived_status": "DOWNLOADED_PUBLIC",
        "content_quality": "SUBSTANTIVE_DCE_PRESENT",
        "gate_readiness": ready,
    }


def test_v1_remains_authoritative():
    assert resolve_evidence(
        "DOWNLOADED_PUBLIC", [{"name": "rft.pdf"}], evidence("DCE_EVIDENCE_QUALITY_V1")
    ) == ("DOWNLOADED_PUBLIC", "SUBSTANTIVE_DCE_PRESENT", True)


def test_v2_is_authoritative_and_gate_ready():
    assert resolve_evidence(
        "DOWNLOADED_PUBLIC", [{"name": "rft.pdf"}], evidence("DCE_EVIDENCE_QUALITY_V2")
    ) == ("DOWNLOADED_PUBLIC", "SUBSTANTIVE_DCE_PRESENT", True)


def test_unknown_future_contract_does_not_auto_promote():
    status, quality, ready = resolve_evidence(
        "DOWNLOADED_PUBLIC", [{"name": "rft.pdf"}], evidence("DCE_EVIDENCE_QUALITY_V3")
    )
    assert status == "DCE_CONTENT_UNVERIFIED"
    assert quality == "UNKNOWN_RETRIEVED_DOCUMENT"
    assert ready is False
