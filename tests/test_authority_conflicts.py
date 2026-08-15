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

def test_consistent_deadline():
    td,r=make('2026-08-24T17:30:00+01:00','Tender submission deadline: 24 August 2026 at 17:30.')
    try: assert process(r)['deadline']['status']=='CONSISTENT_NOTICE_DATE_FOUND_IN_DCE'
    finally: td.cleanup()

def test_conflicting_deadline_is_blocker():
    td,r=make('2026-08-21T12:00:00+01:00','Closing date for submission is 4 September 2026 at 12:00.')
    try:
        x=process(r)['deadline']; assert x['conflict'] is True; assert x['status']=='DEADLINE_CONFLICT_REVIEW_REQUIRED'
    finally: td.cleanup()
