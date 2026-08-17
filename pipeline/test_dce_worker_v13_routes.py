from __future__ import annotations

from dce_worker_v13 import portal_for_url_v13

CASES = {
    "https://www.tenderned.nl/aankondigingen/overzicht/408958": "NL_TENDERNED_PUBLIC",
    "https://www.simap.ch/shabforms/servlet/Search?NOTICE_NR=1": "CH_SIMAP_PUBLIC",
    "https://riigihanked.riik.ee/rhr-web/#/procurement/1/general-info": "EE_RHR",
    "https://www.bi-medien.de/ausschreibungsdienste/ausschreibungen/1": "DE_BI_MEDIEN",
    "https://ezamowienia.gov.pl/mp-client/search/list/ocds-1": "PL_EZAMOWIENIA",
    "https://www.lajunta.es/licitacion/fichaExpte.do?idExpediente=1": "ES_LAJUNTA",
    "https://www.evergabe.de/unterlagen/1": "DE_EVERGABE_DE",
    "https://www.lwl.org/zek/verfahren/1": "DE_LWL",
    "https://cloud.3p.eu/Rooms/DisplayPages/LayoutInitial?ContainerId=1": "THREEP_CLOUD",
    "https://bip.slaskie.pl/ogloszenia/1": "PL_BIP_SLASKIE",
    "https://www.comdia.com/tender/1": "COMDIA_PUBLIC",
    "https://buyer.e-marchespublics.com/NetServer/1": "FR_E_MARCHESPUBLICS",
    "https://foo.example/NetServer/TenderingProcedureDetails?function=_Details&TenderOID=1": "NETSERVER_PUBLIC",
    "https://www.uvo.gov.sk/vyhladavanie/vyhladavanie-zakaziek/detail/558849": "SK_UVO_PUBLIC",
    "https://www.evergabe.nrw.de/VMPSatellite/notice/CXS7YDGYT8D4LQ59/documents": "DE_EVERGABE_NRW",
    "https://platformazakupowa.pl/transakcja/1341777": "PL_PLATFORMZAKUPOWA",
    "https://contractaciopublica.cat/ca/detall-publicacio/04a024a4-0945-467b-9689-66fa0e0b05c0/300786198": "ES_CATALONIA_PUBLIC",
    "https://www.e-avrop.com/forma/e-Upphandling/leverantor/annons/procurement.aspx?id=72089&ownerid=1703": "SE_EAVROP",
    "https://www.acingov.pt/acingovprod/2/index.php/zonaPublica/zona_publica_c/indexProcedimentosActivos/356": "PT_ACINGOV",
}


def main() -> None:
    failures = []
    for url, expected in CASES.items():
        actual = portal_for_url_v13(url)
        if actual != expected:
            failures.append({"url": url, "expected": expected, "actual": actual})
    if failures:
        raise SystemExit(f"v13 route mapping failures: {failures}")
    print({"route_cases": len(CASES), "status": "ok"})


if __name__ == "__main__":
    main()
