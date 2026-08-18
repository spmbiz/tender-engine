from __future__ import annotations

import dce_worker_v15 as v15
import dce_worker_v22 as v22
import dce_worker_v23 as v23  # noqa: F401 - installs the production-safe V23 state


def test_v23_restores_canonical_placsp_matcher():
    assert v15._entry_match is v22._ORIGINAL_ENTRY_MATCH


def test_v23_retains_v22_route_adapters():
    import dce_worker as base
    assert base.ADAPTERS["FR_PLACE"] is v22.adapter_place_v22
    assert base.ADAPTERS["CZ_NIPEZ"] is v22.adapter_nen_v22
    assert base.ADAPTERS["CZ_NIPEZ_PUBLIC"] is v22.adapter_nen_v22


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"PASS {len(tests)} V23 tests")
