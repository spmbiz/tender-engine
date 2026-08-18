from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))

from authority_conflicts import labelled_deadline_dates


def dates_for(label, text):
    return {x["date"] for x in labelled_deadline_dates(text) if x["label"] == label}


def test_etenders_nbsp_submission_and_query_stay_separate():
    text = (
        "Deadline\u00a0for\u00a0requesting\u00a0additional\u00a0information: 04/08/2026 12:00 +01:00. "
        "Deadline\u00a0for\u00a0receipt\u00a0of\u00a0tenders: 18/08/2026 17:00 +01:00."
    )
    assert dates_for("QUERY", text) == {"2026-08-04"}
    assert dates_for("SUBMISSION", text) == {"2026-08-18"}


def test_rfq_closing_date_is_submission_authority():
    text = "Request for Quotation Date 13 August 2026. RFQ Closing Date 28 August 2026. RFQ Closing Time 16h30."
    assert dates_for("SUBMISSION", text) == {"2026-08-28"}


def test_clarification_closing_date_is_not_submission_authority():
    text = "Clarification Closing Date 20 August 2026. Responses will follow later."
    assert dates_for("SUBMISSION", text) == set()
