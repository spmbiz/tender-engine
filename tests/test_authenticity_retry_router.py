from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'pipeline' / 'build_authenticity_retry_router.py'


def run_router(tmp_path: Path, inbox: dict, state: dict):
    inbox_path=tmp_path/'inbox.json'; state_path=tmp_path/'state.json'; plan=tmp_path/'plan.json'
    inbox_path.write_text(json.dumps(inbox),encoding='utf-8')
    state_path.write_text(json.dumps(state),encoding='utf-8')
    subprocess.run([
        sys.executable,str(SCRIPT),'--inbox',str(inbox_path),'--state',str(state_path),'--plan',str(plan),
        '--limit-per-source','12','--max-attempts','2','--cooldown-days','7'
    ],check=True,cwd=tmp_path)
    return json.loads(plan.read_text(encoding='utf-8'))


def candidate(cid, portal):
    return {'candidate_id':cid,'portal':portal,'review_stage':'DCE_AUTHENTICITY','source_dce_run_id':123}


def test_router_only_selects_proven_retry_sources_and_exact_namespaces(tmp_path: Path):
    inbox={'review_queue':[
        candidate('IE:123','IRELAND_ETENDERS'),
        candidate('ZA_ETENDERS_OCDS:ocds-9t57fa-abc','ZA_ETENDERS'),
        candidate('EE-RHR:456','EE_RHR'),
        candidate('TED:789','TED'),
        candidate('ZA:wrong','ZA_ETENDERS'),
    ]}
    plan=run_router(tmp_path,inbox,{'records':{}})
    assert plan['selected_counts']=={'IRELAND':1,'ZA_ETENDERS':1,'ESTONIA':1}
    assert plan['blocked']['unsupported']==2


def test_router_honors_cooldown_and_absolute_attempt_cap(tmp_path: Path):
    now=datetime.now(timezone.utc)
    inbox={'review_queue':[
        candidate('IE:cool','IRELAND_ETENDERS'),
        candidate('IE:cap','IRELAND_ETENDERS'),
        candidate('IE:ready','IRELAND_ETENDERS'),
    ]}
    state={'records':{
        'IE:cool':{'attempts':1,'last_dispatched_at':(now-timedelta(days=1)).isoformat()},
        'IE:cap':{'attempts':2,'last_dispatched_at':(now-timedelta(days=20)).isoformat()},
        'IE:ready':{'attempts':1,'last_dispatched_at':(now-timedelta(days=8)).isoformat()},
    }}
    plan=run_router(tmp_path,inbox,state)
    ids=[x['candidate_id'] for x in plan['selected']['IRELAND']]
    assert ids==['IE:ready']
    assert plan['blocked']['cooldown']==1
    assert plan['blocked']['attempt_cap']==1
