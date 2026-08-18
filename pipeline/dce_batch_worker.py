from __future__ import annotations

import dce_batch_worker_v20 as impl

# Preserve the validated V20 two-stage scheduler byte-for-byte. V23 retains the
# measured V22 hardening gains while restoring canonical PLACSP identity matching.
impl.ACTIVE_WORKER = "pipeline/dce_worker_v23.py"


if __name__ == "__main__":
    impl.main()
