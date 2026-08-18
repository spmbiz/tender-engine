import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'pipeline'))

import refresh_gpt_inbox_live as inbox


class _Resp:
    def __init__(self, payload: dict):
        self._raw = json.dumps(payload).encode('utf-8')
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self):
        return self._raw


def _row(cid='LIVE:1'):
    return {
        'candidate_id': cid,
        'title': 'Website development',
        'deadline': '2099-09-21T12:00:00+00:00',
        'review_stage': 'BUSINESS_GATES',
        'gate_readiness': True,
        'evidence_gate_coverage': 2,
        'evidence_by_gate': {
            'deliverables_scope': [{'text': 'website development'}],
            'submission': [{'text': 'tenders due 21 September 2099'}],
        },
        'source_dce_run_id': 42,
        'priority_score': 60,
    }


def test_live_canonical_inbox_wins_over_stale_local_snapshot(monkeypatch, tmp_path):
    stale = tmp_path / 'stale.json'
    stale.write_text(json.dumps({'review_queue': [], 'pending_final_review': []}), encoding='utf-8')
    live = {
        'schema': 'GPT_WEB_REVIEW_INBOX_V2',
        'review_queue': [_row()],
        'pending_final_review': [_row()],
        'counts': {'pending_gpt_web_review': 1},
    }
    monkeypatch.setenv('GITHUB_REPOSITORY', 'owner/repo')
    monkeypatch.setenv('GITHUB_TOKEN', 'token')
    monkeypatch.setattr(inbox.urllib.request, 'urlopen', lambda req, timeout=15: _Resp(live))
    loaded = inbox.load_live_current_inbox(stale)
    assert loaded['counts']['pending_gpt_web_review'] == 1
    assert loaded['review_queue'][0]['candidate_id'] == 'LIVE:1'


def test_local_fallback_remains_unchanged_without_actions_credentials(monkeypatch, tmp_path):
    local = tmp_path / 'local.json'
    local.write_text(json.dumps({'review_queue': [_row('LOCAL:1')]}), encoding='utf-8')
    monkeypatch.delenv('GITHUB_REPOSITORY', raising=False)
    monkeypatch.delenv('GITHUB_TOKEN', raising=False)
    monkeypatch.delenv('GH_TOKEN', raising=False)
    loaded = inbox.load_live_current_inbox(local)
    assert loaded['review_queue'][0]['candidate_id'] == 'LOCAL:1'
