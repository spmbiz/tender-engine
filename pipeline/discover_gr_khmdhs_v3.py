from __future__ import annotations

"""Production wrapper for the proven KIMDIS empty-window contract.

The V3 transport/pagination implementation lives in ``discover_gr_khmdhs_v2``.
A focused official-source probe established that KIMDIS returns HTTP 404 with the
JSON message ``No notices found for the given criteria`` for a valid future date
window containing zero notices, while adjacent non-empty windows return HTTP 200.

This wrapper recognizes only that exact publisher message (plus the stricter
legacy recognizer) and leaves every other HTTP 404 fatal/fail-closed.
"""

try:
    from pipeline import discover_gr_khmdhs_v2 as base
except ModuleNotFoundError:
    import discover_gr_khmdhs_v2 as base

# Capture the already-tested V2 classifier BEFORE monkeypatching the module.
# Calling ``base.verified_no_data_404`` after the patch would recurse back into
# this wrapper forever.
_ORIGINAL_VERIFIED_NO_DATA_404 = base.verified_no_data_404


def verified_no_data_404(response, page: int) -> bool:
    if _ORIGINAL_VERIFIED_NO_DATA_404(response, page):
        return True
    if response.status_code != 404 or page != 0:
        return False
    try:
        payload = response.json()
    except Exception:
        return False
    if not isinstance(payload, dict):
        return False
    message = base.clean(payload.get("message")).lower()
    try:
        status = int(payload.get("status"))
    except Exception:
        status = None
    return status == 404 and message == "no notices found for the given criteria"


# Patch only the narrow empty-window classifier. All request pacing, Retry-After,
# stable totals, exact row reconciliation, cancellation filtering and fail-closed
# behavior remain the already-proven V3 implementation.
base.verified_no_data_404 = verified_no_data_404


def main() -> None:
    base.main()


if __name__ == "__main__":
    main()
