from __future__ import annotations

import dce_batch_worker_v20 as impl

# Preserve the validated V20 two-stage scheduler byte-for-byte; V21 only swaps
# the resolver executable so Czech NEN can gain a dedicated documents route.
impl.ACTIVE_WORKER = "pipeline/dce_worker_v21.py"


if __name__ == "__main__":
    impl.main()
