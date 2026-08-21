#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    n = text.count(old)
    if n != 1:
        raise SystemExit(f"{label}: expected exactly one match, got {n}")
    return text.replace(old, new, 1)


def patch_semantic_workflow() -> None:
    path = ".github/workflows/qwen-live-classification.yml"
    text = read(path)

    m = re.search(r"(?ms)^on:\n(?P<dispatch>  workflow_dispatch:\n.*?)(?=^  workflow_run:).*?^permissions:\n", text)
    if not m:
        raise SystemExit("qwen-live-classification: cannot isolate trigger block")
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
    text = replace_once(text, "or 192)\n          except Exception: n=192", "or 96)\n          except Exception: n=96", "semantic planner fallback")
    text = replace_once(text, "print(max(16,min(480,n)))", "print(max(16,min(96,n)))", "semantic planner cap")
    text = text.replace(
        "Recovery drainer owns durable Qwen→DCE publication and continuation after this workflow completes.",
        "Continuous conveyor owns durable Qwen publication; backlog watchdog owns continuation.",
    )
    text = text.replace(
        "Qwen→DCE persistence, DCE dispatch and continuation are delegated to Qwen Live Recovery Drainer.",
        "Qwen persistence is delegated to the continuous conveyor; continuation is delegated to the backlog watchdog.",
    )

    if "  workflow_run:" in text.split("permissions:", 1)[0] or "  schedule:" in text.split("permissions:", 1)[0] or "  push:" in text.split("permissions:", 1)[0]:
        raise SystemExit("semantic workflow still has non-controller triggers")
    if "default: '192'" in text or "min(480,n)" in text:
        raise SystemExit("semantic workflow still exposes old shard sizing")
    write(path, text)


def patch_conveyor() -> None:
    path = ".github/workflows/qwen-live-conveyor.yml"
    text = read(path)
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
        raise SystemExit(f"qwen-live-conveyor: continuation step replacement count={n}")
    if "gh workflow run qwen-live-classification.yml" in text:
        raise SystemExit("qwen-live-conveyor still directly dispatches semantic Qwen")
    write(path, text)


def patch_qwen_dce_triage() -> None:
    path = ".github/workflows/qwen-dce-triage.yml"
    text = read(path)
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
          allowed,_=dynamic_tender_parallel(requested)
          print(max(0,min(requested,int(allowed))))
          PY
          )"
"""
    text = replace_once(text, old_workers, new_workers, "Qwen DCE shared admission")
    if "workflows: [\"DCE Fanout V2\"]" in text:
        raise SystemExit("qwen-dce-triage still auto-triggers from DCE Fanout")
    if "dynamic_tender_parallel" not in text:
        raise SystemExit("qwen-dce-triage does not use shared capacity admission")
    write(path, text)


def patch_dce_fanout() -> None:
    path = ".github/workflows/dce-fanout-v2.yml"
    text = read(path)
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
        raise SystemExit(f"dce-fanout: Qwen DCE handoff replacement count={n}")
    if "gh workflow run qwen-dce-triage.yml" in text:
        raise SystemExit("DCE Fanout still directly dispatches Qwen DCE triage")
    write(path, text)


def main() -> None:
    patch_semantic_workflow()
    patch_conveyor()
    patch_qwen_dce_triage()
    patch_dce_fanout()
    print("QWEN_CONTROL_PLANE_AUDIT_V3_APPLIED")


if __name__ == "__main__":
    main()
