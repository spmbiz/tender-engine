#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def trigger_block(text: str, path: str) -> str:
    if "permissions:" not in text:
        raise SystemExit(f"{path}: permissions block missing")
    return text.split("permissions:", 1)[0]


def manual_only(text: str, path: str) -> bool:
    trigger = trigger_block(text, path)
    return (
        "workflow_dispatch:" in trigger
        and "workflow_run:" not in trigger
        and "schedule:" not in trigger
        and "push:" not in trigger
    )


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def validate_semantic() -> None:
    path = ".github/workflows/qwen-live-classification.yml"
    text = read(path)
    require("workflow_dispatch:" in trigger_block(text, path), "semantic: workflow_dispatch missing")
    require("default: '480'" in text, "semantic: canonical 480-row default missing")
    require("QWEN_OPERATIONAL_ROWS_PER_SHARD: '480'" in text, "semantic: operational 480 cap missing")
    require("REQUESTED_PER_SHARD: ${{ github.event.inputs.per_shard || '480' }}" in text, "semantic: 480 request fallback missing")
    require("print(max(16,min(480,n)))" in text, "semantic: canonical 480 planner cap missing")
    require("fallback=1" in text, "semantic: validated singleton fallback missing")
    require("QWEN_RICH_MIN_CONTEXT_CHARS: '2200'" in text, "semantic: explicit 2200 recall context env missing")
    require("--timeout 30" in text, "semantic: 30s request timeout missing")
    require("--description-chars 2200" in text, "semantic: explicit 2200 rich context budget missing")
    require("QWEN_TRANSPORT_RETRIES: '0'" in text, "semantic: production transport retries must be disabled")
    require("name: qwen-live-shards-${{ github.run_id }}" in text, "semantic: worker-only shard transport missing")
    require("--queue '${{ steps.shard.outputs.path }}'" in text, "semantic: exact-context post-guard queue missing")
    require("gh workflow run qwen-live-classification.yml" not in text, "semantic: self-dispatch must not exist")


def validate_conveyor() -> None:
    path = ".github/workflows/qwen-live-conveyor.yml"
    text = read(path)
    require("group: qwen-live-state-writer" in text, "conveyor: single writer lock missing")
    require("cancel-in-progress: false" in text, "conveyor: state writer must not be preempted")
    require("guarded-checkpoint.jsonl" in text, "conveyor: guarded checkpoint ingestion missing")
    require("qwen-live-*-guarded.jsonl" in text, "conveyor: final artifact ingestion missing")
    require("if [ '${{ steps.collect.outputs.novel }}' = '0' ]" in text, "conveyor: no-op fast path missing")
    require("gh workflow run qwen-live-classification.yml" not in text, "conveyor: semantic dispatch ownership violation")


def validate_retired_helpers() -> None:
    for path, marker in (
        (".github/workflows/qwen-live-checkpoint-conveyor.yml", "QWEN_CHECKPOINT_CONVEYOR_RETIRED"),
        (".github/workflows/qwen-live-recovery-drainer.yml", "QWEN_RECOVERY_DRAINER_RETIRED"),
    ):
        text = read(path)
        require(manual_only(text, path), f"{path}: retired helper must be manual-only")
        require(marker in text, f"{path}: retirement marker missing")
        require("contents: write" not in text, f"{path}: retired helper still has write permission")


def validate_qwen_dce() -> None:
    triage = read(".github/workflows/qwen-dce-triage.yml")
    fanout = read(".github/workflows/dce-fanout-v2.yml")
    require('workflows: ["DCE Fanout V2"]' not in trigger_block(triage, ".github/workflows/qwen-dce-triage.yml"), "DCE triage: direct fanout trigger resurrected")
    require("dynamic_tender_parallel" in triage, "DCE triage: shared fleet admission missing")
    require("gh workflow run qwen-dce-triage.yml" not in fanout, "DCE fanout: direct triage dispatch resurrected")
    require("gh workflow run qwen-dce-drainer.yml" in fanout, "DCE fanout: canonical drainer wake missing")


def validate_cpu_benchmarks() -> None:
    for name in ("qwen-batch-autotune-selfheal.yml", "pipeline-ab-live-canary-v2.yml"):
        path = f".github/workflows/{name}"
        require(manual_only(read(path), path), f"{name}: CPU benchmark must remain engineering-only")


def main() -> None:
    validate_semantic()
    validate_conveyor()
    validate_retired_helpers()
    validate_qwen_dce()
    validate_cpu_benchmarks()
    print("QWEN_CONTROL_PLANE_V4_VALIDATED mutations=0")


if __name__ == "__main__":
    main()
