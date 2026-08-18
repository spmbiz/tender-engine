from __future__ import annotations

import dce_batch_worker_v20 as impl

# Preserve the validated V20 two-stage scheduler byte-for-byte; V22 is an additive
# resolver hardening layer over V21. This pointer is promoted only after the V22
# regression and previous-main A/B checks pass on the PR branch.
impl.ACTIVE_WORKER = "pipeline/dce_worker_v22.py"


if __name__ == "__main__":
    impl.main()
