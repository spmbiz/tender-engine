#!/usr/bin/env python3
from __future__ import annotations

import html

import resolve_historical_boamp_routes as resolver

# Official production BOAMP dataset documented by DILA/data.gouv.fr.
resolver.API = "https://boamp-datadila.opendatasoft.com/api/explore/v2.1/catalog/datasets/boamp/records"

# BOAMP structured payloads may HTML-escape query separators. Preserve the exact
# structured provenance but normalize the URL before probing/worker hand-off.
_base_walk_urls = resolver.walk_urls

def _clean_walk_urls(obj, path=""):
    for json_path, url in _base_walk_urls(obj, path):
        yield json_path, html.unescape(url)

resolver.walk_urls = _clean_walk_urls

# Fail closed on buyer-profile-only endpoints. They remain useful discovery
# metadata but are not DCE/document routes. Strong document references survive:
# CallForTendersDocumentReference, urlDocConsul, and document.coord.url.
_base_route_score = resolver.route_score

def _strict_route_score(path: str, url: str) -> int:
    p = str(path or "").casefold()
    strong = (
        "callfortendersdocumentreference" in p
        or "urldocconsul" in p
        or "document.coord.url" in p
    )
    weak_profile_only = (
        "urlprofilach" in p
        or "tenderrecipientparty" in p
        or ("endpointid" in p and not strong)
    )
    if weak_profile_only and not strong:
        return 0
    return _base_route_score(path, url)

resolver.route_score = _strict_route_score

if __name__ == "__main__":
    resolver.main()
