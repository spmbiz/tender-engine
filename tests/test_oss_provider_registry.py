from pathlib import Path

from pipeline.audit_oss_provider_registry import audit


def test_registry_is_machine_valid_and_live_paths_exist():
    root = Path(__file__).resolve().parents[1]
    result = audit(root / "control" / "oss_provider_registry.json", root)
    assert result["valid"] is True
    assert result["missing_implementations"] == []
    assert result["duplicate_keys"] == []


def test_registry_keeps_unimplemented_p0_visible():
    root = Path(__file__).resolve().parents[1]
    result = audit(root / "control" / "oss_provider_registry.json", root)
    assert "MA_PMMP" in result["p0_open"]
    assert "EE_RHR" in result["p0_open"]
    assert "AU_NSW_ETENDERING" in result["p0_open"]
