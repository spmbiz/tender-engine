from __future__ import annotations

import dce_worker as base
import dce_worker_v2 as v2
import dce_worker_v5 as v5  # noqa: F401 - imports and registers all v5 adapters first

# Malta uses the same European Dynamics ePPS public document flow already proven
# for Ireland/Cyprus/Lithuania. Keep it explicit so discovery and DCE contracts stay aligned.
base.ADAPTERS["MALTA_EPPS"] = v2.optimized_epps

# New public national discovery lanes may initially use the guarded cascade while
# portal-specific resolvers are benchmarked. These names are intentionally explicit.
for portal in (
    "BELGIUM_PUBLIC",
    "SI_EJN",
    "SK_UVO",
    "HU_EKR",
    "RO_SEAP",
    "AT_OGD",
    "BG_AOP",
    "HR_EOJN",
    "EE_RHR",
    "SE_PUBLIC",
    "IS_RIKISKAUP",
):
    base.ADAPTERS.setdefault(portal, v5.v4.cascade_public_adapter)

if __name__ == "__main__":
    v2.main()
