from __future__ import annotations

# Import the V2 wrapper first so it patches the shared Cyprus listing module's
# parse_page contract before the workspace probe imports parse_page from it.
try:
    from pipeline import discover_cy_epps_published_global_v2 as _listing_v2  # noqa: F401
    from pipeline import probe_cy_epps_workspace_contract as probe
except ModuleNotFoundError:
    import discover_cy_epps_published_global_v2 as _listing_v2  # noqa: F401
    import probe_cy_epps_workspace_contract as probe


def main() -> None:
    probe.main()


if __name__ == "__main__":
    main()
