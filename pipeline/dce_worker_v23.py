from __future__ import annotations

import dce_worker_v15 as v15
import dce_worker_v22 as v22

# V23 is the production-safe promotion wrapper for V22.
#
# V22's transport hygiene, auth refinement, NEN profile recovery and PLACE route
# recovery are retained. Its experimental TED -> PLACSP exact-title fallback did
# not produce any measured live uplift, so fail closed and restore the validated
# canonical V15/V17 PLACSP identity matcher before processing candidates.
v15._entry_match = v22._ORIGINAL_ENTRY_MATCH


if __name__ == "__main__":
    v22.v21.v20.install_http_probe_guard()
    v22.v2.main()
