#!/usr/bin/env python3
from __future__ import annotations

# Compatibility shim.
#
# Every import continues to expose the exact frozen pre-code selector API so
# tests and downstream Python callers see the historical functions unchanged.
# Only CLI execution is routed through the code-aware scheduler, which may
# reorder DCE capacity but never changes Qwen classification, KEEP/DROP,
# dce_eligible, identity, or authoritative DCE/final gates.
from build_qwen_dce_selection_base import *  # noqa: F401,F403


if __name__ == "__main__":
    from build_qwen_dce_selection_coded import main as _coded_main

    _coded_main()
