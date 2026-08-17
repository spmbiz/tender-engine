from __future__ import annotations

from dce_worker_v14 import portal_for_url_v14

CASES = {
    "https://procontract.due-north.com/SupplierRegistration/GridViewOpportunities": "UK_PROCONTRACT",
    "https://csg.delta-esourcing.com/commonNoticeSearch/viewNotice.html?displayNoticeId=1017935297": "UK_DELTA",
    "https://www.delta-esourcing.com/delta/loginRespondToList.html?noticeId=1": "UK_DELTA",
    "https://ucl.in-tendhost.co.uk/ucl/aspx/Home": "UK_INTEND",
    "https://ministryofjusticecommercial.ukp.app.jaggaer.com/web/login.html": "UK_JAGGAER",
    "https://nhsengland.bravosolution.co.uk/web/login.html": "UK_JAGGAER",
    "https://atamis-9529.my.salesforce-sites.com/?SearchType=Projects": "UK_ATAMIS",
    "https://atamis-ukparliament.my.site.com/s/Welcome": "UK_ATAMIS",
    "https://www.tenderlink.com/npdc/": "NZ_TENDERLINK",
    "https://uk.eu-supply.com/ctm/Supplier/PublicPurchase/1/0/0": "EU_SUPPLY_PUBLIC",
}


def main() -> None:
    failures = []
    for url, expected in CASES.items():
        actual = portal_for_url_v14(url)
        if actual != expected:
            failures.append({"url": url, "expected": expected, "actual": actual})
    if failures:
        raise SystemExit(f"v14 route mapping failures: {failures}")
    print({"route_cases": len(CASES), "status": "ok"})


if __name__ == "__main__":
    main()
