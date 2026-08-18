from __future__ import annotations

import dce_batch_worker_v20 as impl

# Preserve the validated V20 two-stage scheduler byte-for-byte; V22 only swaps
# the resolver executable so FR_BOAMP becomes a buyer-profile/DCE router while
# retaining the validated V21 Czech NEN resolver underneath.
impl.ACTIVE_WORKER = "pipeline/dce_worker_v22.py"


if __name__ == "__main__":
    impl.main()
