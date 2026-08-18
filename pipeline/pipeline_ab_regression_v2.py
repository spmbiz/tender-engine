#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

import pipeline_ab_regression as ab


def scan_real_qwen_preemption(repo: Path) -> list[str]:
    """Flag only automatic workflows that can actually cancel an Actions run.

    `cancel-in-progress` on a workflow's *own concurrency group* is not Qwen
    preemption. Likewise reading `actions/runs/${id}` for status is harmless.
    We only reject actual cancel/force-cancel API endpoints or `gh run cancel`.
    """
    bad: list[str] = []
    root = repo / ".github/workflows"
    for p in sorted(root.glob("qwen-*.yml")):
        text = p.read_text(encoding="utf-8", errors="replace")
        lowered = text.lower()
        actual_cancel = (
            "gh run cancel" in lowered
            or re.search(r"actions/runs/[^\s\"']+/(?:force-)?cancel\b", lowered) is not None
            or re.search(r"gh\s+api[^\n]*(?:force-)?cancel", lowered) is not None
        )
        automatic = bool(re.search(r"(?m)^\s{2}(push|schedule|workflow_run):", text))
        if actual_cancel and automatic:
            bad.append(p.name)
    return bad


ab.scan_preemption = scan_real_qwen_preemption

if __name__ == "__main__":
    ab.main()
