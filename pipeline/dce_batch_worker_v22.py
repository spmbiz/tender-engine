from __future__ import annotations

import dce_batch_worker_v20 as impl

# Preserve the validated V20 scheduler byte-for-byte; V22 only swaps the resolver
# executable so transport hygiene and route recovery can be benchmarked safely.
impl.ACTIVE_WORKER = "pipeline/dce_worker_v22.py"


if __name__ == "__main__":
    impl.main()
