from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'pipeline'))
from final_verdict_guard import REQUIRED_GATES, validate_record


def resolved_gates():
    return {g:{'status':'PASS','evidence':['source snippet']} for g in REQUIRED_GATES}


def consistent_authority():
    return {'deadline':{'status':'CONSISTENT_NOTICE_DATE_FOUND_IN_DCE','conflict':False}}


def test_blocks_final_without_dce():
    rec={'candidate_id':'X','classification':'FINAL_SUPER_GREEN','score':94,'evidence_quality':{'content_quality':'ACCESS_GUIDE_ONLY','gate_readiness':False},'authority_conflicts':consistent_authority(),'gates':resolved_gates()}
    errs=validate_record(rec)
    assert any('gate_readiness' in e for e in errs)


def test_blocks_unknown_gate():
    gates=resolved_gates(); gates['turnover_financial']={'status':'UNKNOWN'}
    rec={'candidate_id':'X','classification':'FINAL_SUPER_GREEN','score':94,'evidence_quality':{'content_quality':'SUBSTANTIVE_DCE_PRESENT','gate_readiness':True},'authority_conflicts':consistent_authority(),'gates':gates}
    errs=validate_record(rec)
    assert any('turnover_financial' in e for e in errs)


def test_blocks_deadline_conflict():
    rec={'candidate_id':'X','classification':'FINAL_SUPER_GREEN','score':94,'evidence_quality':{'content_quality':'SUBSTANTIVE_DCE_PRESENT','gate_readiness':True},'authority_conflicts':{'deadline':{'status':'DEADLINE_CONFLICT_REVIEW_REQUIRED','conflict':True}},'gates':resolved_gates()}
    errs=validate_record(rec)
    assert any('deadline conflict' in e for e in errs)


def test_accepts_fully_evidenced_final():
    rec={'candidate_id':'X','classification':'FINAL_SUPER_GREEN','score':94,'evidence_quality':{'content_quality':'SUBSTANTIVE_DCE_PRESENT','gate_readiness':True},'authority_conflicts':consistent_authority(),'gates':resolved_gates()}
    assert validate_record(rec)==[]
