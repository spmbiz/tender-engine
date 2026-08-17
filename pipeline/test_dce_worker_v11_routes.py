from __future__ import annotations

from dce_worker_v11 import portal_for_url

CASES = {
    "https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/tender-details/x-CN": "EU_FUNDING_TENDERS",
    "https://www.publicprocurement.be/publication-workspaces/x/documents": "BE_EPROC_V11",
    "https://s2c.mercell.com/today/227119": "MERCELL_S2C",
    "https://annonser.clira.io/upphandling/c089c3e2-94ad-44a6-8aa0-fa08b5d7dd07": "SE_CLIRA",
    "https://app.eop.bg/today/584841": "BG_EOP_PUBLIC",
    "https://e-licitatie.ro/pub/notices/contract-notices/view/1": "RO_SEAP_PUBLIC",
    "https://ekr.gov.hu/portal/kozbeszerzes/eljarasok/EKR000199982025/reszletek": "HU_EKR_PUBLIC",
    "https://eojn.hr/tender-eo/1": "HR_EOJN_PUBLIC",
    "https://www.uvo.gov.sk/vyhladavanie/vyhladavanie-zakaziek/detail/1": "SK_UVO_PUBLIC",
    "https://www.eis.gov.lv/EKEIS/Supplier/Procurement/1": "LV_EIS_PUBLIC",
    "https://nen.nipez.cz/verejne-zakazky/detail-zakazky/1": "CZ_NIPEZ_PUBLIC",
    "https://nepps.eprocurement.gov.gr/1": "GR_EPPS_PUBLIC",
    "https://www.achatpublic.com/sdm/ent/gen/ent_detail.do?PCSLID=1": "FR_ACHATPUBLIC",
    "https://www.marches-securises.fr/perso/1/": "FR_MARCHES_SECUR",
    "https://contractaciopublica.gencat.cat/ecofin_pscp/AppJava/notice.pscp?idDoc=1": "ES_CATALONIA_PUBLIC",
    "https://www.acquistinretepa.it/opencms/opencms/scheda_iniziativa.html?id=1": "IT_ACQUISTINRETEPA",
    "https://www.acingov.pt/acingovprod/2/index.php/zonaPublica/zona_publica_c/indexProcedure/1": "PT_ACINGOV",
    "https://gv.vergabeportal.at/Detail/1": "AT_VERGABEPORTAL",
    "https://www.vergabe24.de/vergabeunterlagen/1": "DE_VERGABE24",
    "https://foo.platformazakupowa.pl/transakcja/1": "PL_PLATFORMZAKUPOWA",
    "https://community.vortal.biz/PRODPublicTendering/NoticeDetail/Index?noticeId=1": "VORTAL_PUBLIC",
    "https://eu.eu-supply.com/ctm/Supplier/PublicPurchase/1/0/0": "EU_SUPPLY_PUBLIC",
}


def main() -> None:
    failures = []
    for url, expected in CASES.items():
        actual = portal_for_url(url)
        if actual != expected:
            failures.append({"url": url, "expected": expected, "actual": actual})
    if failures:
        raise SystemExit(f"route mapping failures: {failures}")
    print({"route_cases": len(CASES), "status": "ok"})


if __name__ == "__main__":
    main()
