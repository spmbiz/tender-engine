from pipeline.discover_uk_pcs_current_direct_v13 import parse_rows


def test_same_ocid_different_notice_references_do_not_collapse():
    html = """
    <html><body>
      Showing page 1 of 1 total 2 items
      <table>
        <tr><td><a href="notice1">First notice</a> Reference No: AUG100 OCID: ocds-shared Published By: Buyer A Deadline Date: 31-Dec-26 Notice Type: Contract Notice</td></tr>
        <tr><td><a href="notice2">Second notice</a> Reference No: AUG101 OCID: ocds-shared Published By: Buyer A Deadline Date: 31-Dec-26 Notice Type: Contract Notice</td></tr>
      </table>
    </body></html>
    """
    records = {}
    page, pages, total, parsed = parse_rows(html, records)
    assert (page, pages, total, parsed) == (1, 1, 2, 2)
    assert sorted(records) == ["UK-PCS:AUG100", "UK-PCS:AUG101"]
    assert {row["procedure_id"] for row in records.values()} == {"ocds-shared"}
