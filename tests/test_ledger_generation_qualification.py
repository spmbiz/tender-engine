from pipeline.build_notice_intelligence_ledger import build


def row(i: int, source: str = "TED"):
    return {
        "candidate_id": f"{source}:{i}",
        "source": source,
        "source_family": source,
        "title": f"Tender {i}",
    }


def previous_row(i: int, source: str = "TED"):
    return {
        "canonical_notice_id": f"{source}:{i}",
        "source": source,
        "material_fields_hash": "old",
        "first_seen_at": "2026-08-01T00:00:00+00:00",
    }


def test_small_first_backfill_passes_generation_qualification():
    _, _, _, summary = build([row(i) for i in range(10)], [], now="2026-08-19T00:00:00+00:00", target_classifier_version="x")
    assert summary["generation_qualification"]["status"] == "PASS"


def test_catastrophic_total_regression_fails_generation_qualification():
    previous = [previous_row(i) for i in range(1000)]
    current = [row(i) for i in range(700)]
    _, _, _, summary = build(current, previous, now="2026-08-19T00:00:00+00:00", target_classifier_version="x")
    assert summary["generation_qualification"]["hard_fail"] is True
    assert summary["generation_qualification"]["current_vs_previous_ratio"] == 0.7


def test_large_source_collapse_fails_even_if_total_is_backfilled_elsewhere():
    previous = [previous_row(i, "TED") for i in range(600)] + [previous_row(i, "US") for i in range(600)]
    current = [row(i, "TED") for i in range(250)] + [row(i, "US") for i in range(950)]
    _, _, _, summary = build(current, previous, now="2026-08-19T00:00:00+00:00", target_classifier_version="x")
    q = summary["generation_qualification"]
    assert q["hard_fail"] is True
    assert "TED" in q["source_regressions"]
