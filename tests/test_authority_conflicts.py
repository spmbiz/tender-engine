import json,tempfile,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'pipeline'))
from authority_conflicts import process

def make(deadline,snippet):
    td=tempfile.TemporaryDirectory(); r=Path(td.name)
    (r/'manifest.json').write_text(json.dumps({'candidate_id':'X','status':'DOWNLOADED_PUBLIC'}))
    (r/'candidate.json').write_text(json.dumps({'candidate_id':'X','deadline':deadline}))
    (r/'evidence_quality.json').write_text(json.dumps({'gate_readiness':True}))
    (r/'gate_snippets.json').write_text(json.dumps({'categories':{'submission':[{'snippet':snippet}]}}))
    return td,r

def test_consistent_authoritative_submission_deadline():
    td,r=make('2026-08-24T17:30:00+01:00','Tender submission deadline: 24 August 2026 at 17:30.')
    try:
        x=process(r)['deadline']
        assert x['status']=='CONSISTENT_AUTHORITATIVE_SUBMISSION_DATE'
        assert x['conflict'] is False
        assert x['authoritative_submission_date']=='2026-08-24'
    finally: td.cleanup()

def test_authoritative_submission_deadline_overrides_notice_metadata():
    td,r=make('2026-08-21T12:00:00+01:00','Closing date for submission is 4 September 2026 at 12:00.')
    try:
        x=process(r)['deadline']
        assert x['conflict'] is False
        assert x['status']=='DCE_AUTHORITATIVE_SUBMISSION_DATE_OVERRIDES_NOTICE_METADATA'
        assert x['authoritative_submission_date']=='2026-09-04'
    finally: td.cleanup()
