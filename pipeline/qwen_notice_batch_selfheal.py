#!/usr/bin/env python3
from qwen_notice_batch_selfheal_rich import base
from qwen_live_checkpoint_publisher import run_with_live_checkpoints

if __name__ == "__main__":
    run_with_live_checkpoints(base.main)
