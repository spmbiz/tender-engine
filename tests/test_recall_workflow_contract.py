from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_ted_workflow_has_checkpoint_persistence_margin():
    text = (ROOT / ".github/workflows/supergreen-discovery-v2.yml").read_text(encoding="utf-8")
    section = text.split("  ted-discovery:", 1)[1].split("  contracts-finder-discovery:", 1)[0]
    assert "timeout-minutes: 70" in section
    assert "timeout-minutes: 55" in section
    assert "Persist TED discovery durably BEFORE completeness validation\n        if: always()" in section
    assert "assert s.get('enumeration_complete') is True" in section


def test_snapshot_workflow_recovers_previous_live_universe():
    text = (ROOT / ".github/workflows/live-world-snapshot.yml").read_text(encoding="utf-8")
    assert "PREVIOUS_SNAPSHOT_PATH" in text
    assert 'previous+=(--previous "$PREVIOUS_SNAPSHOT_PATH")' in text
    assert "('missing_packs','degraded_packs','external_missing_lanes')" in text


def test_qwen_defaults_spend_more_capacity_on_false_negative_audits():
    text = (ROOT / "pipeline/build_qwen_dce_selection_coded.py").read_text(encoding="utf-8")
    assert "--explore-share\", type=float, default=.30" in text
    assert "--reject-audit-share\", type=float, default=.20" in text
    assert "recall_guard_until_qwen_benchmark_passes" in text
