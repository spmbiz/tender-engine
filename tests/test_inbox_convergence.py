import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'pipeline'))
import publish_supergreen_hot as p

def row():
    return {'candidate_id':'X:1','title':'Web development services','deadline':'2099-09-21T12:00:00+00:00','review_stage':'BUSINESS_GATES','gate_readiness':True,'evidence_gate_coverage':2,'evidence_by_gate':{'deliverables_scope':[{'text':'website development'}],'submission':[{'text':'tenders due 21 September 2099'}]},'source_dce_run_id':42,'priority_score':60}

def test_rebases_on_latest_existing(monkeypatch):
    latest={'schema':'GPT_WEB_REVIEW_INBOX_V2','review_queue':[row()],'pending_final_review':[row()],'counts':{'pending_gpt_web_review':1}}
    def fake_get(repo,path,branch,token):
        if path.endswith('final_supergreen_bank.json'): return {'items':[]},'a'
        if path.endswith('supergreen_hot.json'): return {'final_supergreens':[],'greens':[]},'b'
        if path.endswith('gpt_review_hot.json'): return {'latest_dce_run_id':42,'items':[]},'c'
        raise AssertionError(path)
    captured={}
    def fake_publish(repo,path,branch,token,builder,msg,attempts):
        captured['payload']=builder(latest)
        return {'published':True}
    monkeypatch.setattr(p,'gh_get',fake_get)
    monkeypatch.setattr(p,'publish',fake_publish)
    p.publish_live_inbox('owner/repo','main','token','42','7',2)
    assert captured['payload']['counts']['pending_gpt_web_review']==1
    assert captured['payload']['review_queue'][0]['candidate_id']=='X:1'
