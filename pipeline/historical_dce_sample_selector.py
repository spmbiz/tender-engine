#!/usr/bin/env python3
"""Compatibility entrypoint for the Global Core v4-aware historical DCE selector.

The original v1 implementation pre-dated the canonical Warehouse_Source /
Historical_Tender_ID schema and did not emit resolver-ready portal/notice/route
fields. Keep this path stable for old workflows while delegating to the tested
v2 implementation.
"""
try:
    from pipeline.historical_dce_sample_selector_v2 import *  # noqa: F401,F403
except ModuleNotFoundError:
    from historical_dce_sample_selector_v2 import *  # type: ignore # noqa: F401,F403

if __name__ == "__main__":
    main()
