#!/usr/bin/env python3
from __future__ import annotations

import resolve_historical_boamp_routes as resolver

# Official production BOAMP dataset documented by DILA/data.gouv.fr.
resolver.API = "https://boamp-datadila.opendatasoft.com/api/explore/v2.1/catalog/datasets/boamp/records"

if __name__ == "__main__":
    resolver.main()
