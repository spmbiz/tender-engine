#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> bool:
    p = ROOT / path
    before = p.read_text(encoding="utf-8")
    if before == text:
        return False
    p.write_text(text, encoding="utf-8")
    return True


def replace_once(text: str, old: str, new: str, label: str) -> str:
    n = text.count(old)
    if n != 1:
        raise SystemExit(f"{label}: expected exactly one match, got {n}")
    return text.replace(old, new, 1)


def trigger_block(text: str, path: str) -> str:
    if "permissions:" not in text:
        raise SystemExit(f"{path}: permissions block missing")
    return text.split("permissions:", 1)[0]


def manual_only_trigger(text: str, path: str) -> bool:
    trigger = trigger_block(text, path)
    return (
        "workflow_dispatch:" in trigger
        and "workflow_run:" not in trigger
        and "schedule:" not in trigger
        and "push:" not in trigger
    )


def semantic_v3(text: str) -> bool:
    path = ".github/workflows/qwen-live-classification.yml"
    return (
        manual_only_trigger(text, path)
        and "default: '96'" in text
        and "default: '192'" not in text
        and "REQUESTED_PER_SHARD: ${{ github.event.inputs.per_shard || '96' }}" in text
        and "if: github.event_name == 'workflow_dispatch'" in text
        and "or 96)\n          except Exception: n=96" in text
        and "print(max(16,min(96,n)))" in text
        and "min(480,n)" not in text
        and "semantic controller owns continuation" in text
    )


def conveyor_v3(text: str) -> bool:
    return (
        "gh workflow run qwen-live-classification.yml" not in text
        and "Semantic continuation is owned by the canonical controller" in text
        and "Qwen Backlog Watchdog is the single semantic dispatch owner." in text
    )


def qwen_dce_triage_v3(text: str) -> bool:
    path = ".github/workflows/qwen-dce-triage.yml"
    return (
        manual_only_trigger(text, path)
        and 'workflows: ["DCE Fanout V2"]' not in text
        and "if: github.event_name == 'workflow_dispatch'" in text
        and 'rid="$INPUT_RUN"' in text
        and "dynamic_tender_parallel" in text
    )


def dce_fanout_v3(text: str) -> bool:
    return (
        "gh workflow run qwen-dce-triage.yml" not in text
        and "gh workflow run qwen-dce-drainer.yml --ref main" in text
        and "Wake the canonical Qwen DCE triage controller after durable persistence" in text
    )


def patch_semantic_workflow() -> bool:
    path = ".github/workflows/qwen-live-classification.yml"
    text = read(path)
    if semantic_v3(text):
        return False

    # Only transform the exact legacy topology. Anything partly migrated or
    # otherwise unexpected fails closed instead of being guessed into shape.
    m = re.search(r"(?ms)^on:\n(?P<dispatch>  workflow_dispatch:\n.*?)(?=^  workflow_run:).*?^permissions:\n", text)
    if not m:
        raise SystemExit("qwen-live-classification: neither canonical V3 nor exact legacy trigger topology")
    text = text[: m.start()] + "on:\n" + m.group("dispatch") + "\npermissions:\n" + text[m.end() :]

    text = replace_once(text, "default: '192'", "default: '96'", "semantic manual default")
    text = replace_once(
        text,
        "description: Retained for compatibility; recovery drainer owns continuation",
        "description: Retained for compatibility; semantic controller owns continuation",
        "semantic continuation description",
    )
    text = replace_once(
        text,
        "if: github.event_name != 'workflow_run' || github.event.workflow_run.conclusion == 'success'",
        "if: github.event_name == 'workflow_dispatch'",
        "semantic plan event guard",
    )
    text = replace_once(
        text,
        "REQUESTED_PER_SHARD: ${{ github.event.inputs.per_shard || '192' }}",
        "REQUESTED_PER_SHARD: ${{ github.event.inputs.per_shard || '96' }}",
        "semantic requested per shard",
    )
    text = replace_once(
        text,
        "or 192)\n          except Exception: n=192",
        "or 96)\n          except Exception: n=96",
        "semantic planner fallback",
    )
    text = replace_once(text, "print(max(16,min(480,n)))", "print(max(16,min(96,n)))", "semantic planner cap")
    text = text.replace(
        "Recovery drainer owns durable Qwen→DCE publication and continuation after this workflow completes.",
        "Continuous conveyor owns durable Qwen publication; backlog watchdog owns continuation.",
    )
    text = text.replace(
        "Qwen→DCE persistence, DCE dispatch and continuation are delegated to Qwen Live Recovery Drainer.",
        "Qwen persistence is delegated to the continuous conveyor; continuation is delegated to the backlog watchdog.",
    )

    if not semantic_v3(text):
        raise SystemExit("qwen-live-classification: V3 postcondition failed")
    return write(path, text)


def patch_conveyor() -> bool:
    path = ".github/workflows/qwen-live-conveyor.yml"
    text = read(path)
    if conveyor_v3(text):
        return False

    pattern = re.compile(
        r"(?ms)^      - name: Ensure semantic backfill remains continuously primed before DCE\n.*?(?=^      - name: )"
    )
    replacement = (
        "      - name: Semantic continuation is owned by the canonical controller\n"
        "        shell: bash\n"
        "        run: |\n"
        "          echo 'No semantic worker is dispatched from the conveyor.'\n"
        "          echo 'Qwen Backlog Watchdog is the single semantic dispatch owner.'\n\n"
    )
    text, n = pattern.subn(replacement, text, count=1)
    if n != 1:
        raise SystemExit("qwen-live-conveyor: neither canonical V3 nor exact legacy continuation step")
    if not conveyor_v3(text):
        raise SystemExit("qwen-live-conveyor: V3 postcondition failed")
    return write(path, text)


def patch_qwen_dce_triage() -> bool:
    path = ".github/workflows/qwen-dce-triage.yml"
    text = read(path)
    if qwen_dce_triage_v3(text):
        return False

    text = replace_once(
        text,
        'on:\n  workflow_run:\n    workflows: ["DCE Fanout V2"]\n    types: [completed]\n  workflow_dispatch:\n',
        "on:\n  workflow_dispatch:\n",
        "Qwen DCE direct trigger removal",
    )
    text = replace_once(
        text,
        "if: github.event_name != 'workflow_run' || github.event.workflow_run.conclusion == 'success'",
        "if: github.event_name == 'workflow_dispatch'",
        "Qwen DCE plan guard",
    )
    old_resolve = """          if [ '${{ github.event_name }}' = 'workflow_run' ]; then
            rid='${{ github.event.workflow_run.id }}'
          else
            rid="$INPUT_RUN"
          fi
"""
    text = replace_once(text, old_resolve, '          rid="$INPUT_RUN"\n', "Qwen DCE source resolve")

    old_workers = """          workers="$(GATE_READY="$gate_ready" python - <<'PY'
          import os
          g=int(os.environ['GATE_READY'])
          try:w=int(os.environ.get('REQUESTED_WORKERS') or 4)
          except Exception:w=4
          w=max(1,min(6,w))
          print(0 if g==0 else min(w,g))
          PY
          )"
"""
    new_workers = """          workers="$(GATE_READY="$gate_ready" python - <<'PY'
          import os
          from pipeline.global_admission import dynamic_tender_parallel
          g=int(os.environ['GATE_READY'])
          try:w=int(os.environ.get('REQUESTED_WORKERS') or 4)
          except Exception:w=4
          w=max(1,min(6,w))
          requested=0 if g==0 else min(w,g)
          if requested <= 0:
              print(0)
          else:
              allowed,_=dynamic_tender_parallel(requested)
              print(max(0,min(requested,int(allowed))))
          PY
          )"
"""
    text = replace_once(text, old_workers, new_workers, "Qwen DCE shared admission")
    if not qwen_dce_triage_v3(text):
        raise SystemExit("qwen-dce-triage: V3 postcondition failed")
    return write(path, text)


def patch_dce_fanout() -> bool:
    path = ".github/workflows/dce-fanout-v2.yml"
    text = read(path)
    if dce_fanout_v3(text):
        return False

    pattern = re.compile(
        r"(?ms)^      - name: Dispatch Qwen DCE gate triage immediately after durable persistence\n.*?(?=^      - name: Persist this exact attempt set and continue the unseen DCE queue immediately)"
    )
    replacement = """      - name: Wake the canonical Qwen DCE triage controller after durable persistence
        env:
          GH_TOKEN: ${{ github.token }}
        shell: bash
        run: |
          set -euo pipefail
          gh workflow run qwen-dce-drainer.yml --ref main
          echo "Canonical Qwen DCE drainer woken for durable DCE run $GITHUB_RUN_ID" >> "$GITHUB_STEP_SUMMARY"
"""
    text, n = pattern.subn(replacement, text, count=1)
    if n != 1:
        raise SystemExit("dce-fanout: neither canonical V3 nor exact legacy Qwen DCE handoff")
    if not dce_fanout_v3(text):
        raise SystemExit("dce-fanout: V3 postcondition failed")
    return write(path, text)


def make_cpu_benchmark_manual_only(path: str) -> bool:
    text = read(path)
    if manual_only_trigger(text, path):
        return False
    m = re.search(r"(?ms)^on:\n.*?^permissions:\n", text)
    if not m:
        raise SystemExit(f"{path}: cannot isolate trigger block")
    text = text[: m.start()] + "on:\n  workflow_dispatch:\n\npermissions:\n" + text[m.end() :]
    if not manual_only_trigger(text, path):
        raise SystemExit(f"{path}: manual-only postcondition failed")
    return write(path, text)


def patch_cpu_benchmarks() -> int:
    # These launch llama.cpp CPU workers and must not steal hosted runners from the
    # semantic backfill. They remain available explicitly for engineering use.
    changed = 0
    changed += int(make_cpu_benchmark_manual_only(".github/workflows/qwen-batch-autotune-selfheal.yml"))
    changed += int(make_cpu_benchmark_manual_only(".github/workflows/pipeline-ab-live-canary-v2.yml"))
    return changed


def main() -> None:
    changed = 0
    changed += int(patch_semantic_workflow())
    changed += int(patch_conveyor())
    changed += int(patch_qwen_dce_triage())
    changed += int(patch_dce_fanout())
    changed += patch_cpu_benchmarks()
    if changed:
        print(f"QWEN_CONTROL_PLANE_AUDIT_V3_APPLIED changed_files={changed}")
    else:
        print("QWEN_CONTROL_PLANE_AUDIT_V3_ALREADY_APPLIED changed_files=0")


if __name__ == "__main__":
    main()
