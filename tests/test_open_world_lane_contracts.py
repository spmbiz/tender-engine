from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def text(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_discovery_workflow_wires_new_live_recall_lanes():
    body = text('.github/workflows/supergreen-discovery-v2.yml')
    assert 'UNGM_PUBLIC' in body
    assert 'discover_ungm_public.py' in body
    assert 'discover_uk_pcs_current.py' in body
    assert 'discover_it_anac_pvl.py' in body
    assert 'discover_epps_published_fallback.py' in body


def test_ungm_is_measured_internally_not_assumed_external():
    body = text('pipeline/source_coverage_guard.py')
    assert 'discovery-global-ungm-public' in body
    assert '"UNGM_PUBLIC"' in body
    assert 'EXTERNAL_REQUIRED_LANES=[]' in body


def test_bounded_fallbacks_never_claim_exhaustive_coverage():
    italy = text('pipeline/discover_it_anac_pvl.py')
    epps = text('pipeline/discover_epps_published_fallback.py')
    assert '"live_coverage_credit_allowed": False' in italy
    assert '"enumeration_complete": False' in italy
    assert '"live_coverage_credit_allowed": False' in epps
    assert '"enumeration_complete": False' in epps


def test_current_registry_lanes_require_exhaustion():
    pcs = text('pipeline/discover_uk_pcs_bulk_current.py')
    ungm = text('pipeline/discover_ungm_public.py')
    for body in (pcs, ungm):
        assert 'enumeration_exhausted' in body
        assert 'enumeration_complete' in body
        assert 'live_coverage_credit_allowed' in body


def test_pcs_coverage_is_contract_aware_and_bulk_requires_101():
    guard = text('pipeline/source_coverage_guard.py')
    # Legacy browser/direct POST proofs stay available for old packs.
    assert 'PCS_FILTERED_SEARCH_PROOF_MISSING' in guard
    assert 'PCS_FILTERED_PAGE_TOTAL_NOT_STABLE' in guard
    assert 'search_navigation_proven' in guard
    assert 'direct_filtered_post_proven' in guard
    # Official bulk packs remain contract-aware and Website Contract Notice 101 is mandatory.
    assert 'PCS_OFFICIAL_MONTH_TYPE_BULK_OCDS_' in guard
    assert 'PCS_BULK_PUBLICATION_PARTITIONS_INCOMPLETE' in guard
    assert 'PCS_BULK_REQUEST_COUNT_MISMATCH' in guard
    assert 'PCS_BULK_WEBSITE_CONTRACT_NOTICE_101_MISSING' in guard
    # Do not pin this regression to an obsolete schema revision. V10 added a
    # stronger direct-current reconciliation proof while preserving the contract.
    assert 'SOURCE_COVERAGE_GUARD_V' in guard
    assert 'PCS_DIRECT_RECONCILE_PROOF' in guard or 'PCS_CONTRACT_AWARE' in guard


def test_qwen_live_entrypoint_is_rich_and_old_prompt_state_is_invalidated():
    entry = text('pipeline/qwen_notice_batch_selfheal.py')
    rich = text('pipeline/qwen_notice_batch_selfheal_rich.py')
    merge = text('pipeline/merge_qwen_classification_state.py')
    runtime = text('control/qwen_batch_runtime_config.json')
    evaluator = text('pipeline/evaluate_qwen_recall_golden.py')
    assert 'qwen_notice_batch_selfheal_rich' in entry
    assert 'qwen_notice_batch_selfheal_core as base' in rich
    assert 'qwen-batch-high-recall-business-fit-v3-rich' in rich
    for field in ('lots', 'notice_eligibility', 'award_criteria', 'subcontracting'):
        assert field in rich
    assert 'REQUIRED_PROMPT_VERSION = "qwen-batch-high-recall-business-fit-v3-rich"' in merge
    assert 'previous_wrong_prompt_dropped' in merge
    # Runtime config is generated and may be BLOCKED with no champion. The
    # permanent corpus gate belongs in the evaluator contract, not in ephemeral
    # generated runtime state.
    assert 'DEFAULT_MIN_CASES = 500' in evaluator
    assert 'DEFAULT_MIN_POSITIVES = 100' in evaluator
    assert '"automatic_rejection_enabled": false' in runtime


def test_calibration_corpus_never_auto_labels_dce_red_as_notice_reject():
    body = text('pipeline/build_qwen_calibration_corpus.py')
    assert 'POSITIVE_CLASSES' in body
    assert '"GREEN"' in body and '"YELLOW"' in body
    assert 'RED DCE verdicts are not auto-labelled' in body
