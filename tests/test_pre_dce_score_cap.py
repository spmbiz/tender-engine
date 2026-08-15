from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'pipeline'))
from auto_select_dce import retrieval_score, select


def test_retrieval_priority_may_be_high_but_export_never_exceeds_89():
    rec={
        'candidate_id':'CAP:1',
        'title':'Website web portal CMS graphic design creative branding video animation marketing social media transcription automation artificial intelligence',
        'description':'website portal cms hosting maintenance graphic design video marketing content translation app development automation',
        'buyer':'Public Buyer',
        'estimated_value':100000,
        'deadline':'2099-08-30T12:00:00+00:00',
        'current':True,
    }
    raw,_=retrieval_score(rec)
    assert raw >= 90
    rows=select([rec],minimum=0,limit=10)
    assert rows
    assert rows[0]['preliminary_score']==89
    assert rows[0]['status']=='AUTO_DCE_PREFETCH'


def test_all_pre_dce_exports_are_below_final_threshold():
    records=[
        {'candidate_id':f'CAP:{i}','title':'website cms graphic design video marketing','estimated_value':50000+i,'deadline':'2099-08-30T12:00:00+00:00','current':True}
        for i in range(5)
    ]
    rows=select(records,minimum=0,limit=10)
    assert all(int(r['preliminary_score']) <= 89 for r in rows)
