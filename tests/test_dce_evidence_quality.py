import json
import tempfile
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'pipeline'))
from dce_evidence_quality import classify_candidate


def make_root(corpus, name='document.pdf', title='Website hosting maintenance security development'):
    td = tempfile.TemporaryDirectory()
    root = Path(td.name)
    (root/'manifest.json').write_text(json.dumps({'candidate_id':'X:1','status':'DOWNLOADED_PUBLIC','candidate':{'candidate_id':'X:1','title':title},'files':[{'name':name}]}))
    (root/'candidate.json').write_text(json.dumps({'candidate_id':'X:1','title':title}))
    (root/'document_index.json').write_text(json.dumps([{'name':name,'text_chars':len(corpus)}]))
    (root/'corpus.txt').write_text(corpus)
    return td, root


def test_access_guide_is_not_dce():
    td, root = make_root('INSTRUCTIONS ON HOW TO ACCESS WMO TENDERS. Register on UNGM. Click Express Interest. Then click View Documents.', 'WMO - INSTRUCTIONS ON HOW TO ACCESS WMO TENDERS.pdf')
    try:
        x=classify_candidate(root)
        assert x['content_quality']=='ACCESS_GUIDE_ONLY'
        assert x['derived_status']=='INTEREST_RECORDING_REQUIRED'
        assert x['gate_readiness'] is False
    finally:
        td.cleanup()


def test_real_rft_is_gate_ready():
    corpus='Request for Tender. Scope of Work. Technical Specifications. Award Criteria. Pricing Schedule. Submission deadline. Public Liability. Professional Indemnity.'
    td, root = make_root(corpus, 'RFT.pdf')
    try:
        x=classify_candidate(root)
        assert x['content_quality']=='SUBSTANTIVE_DCE_PRESENT'
        assert x['gate_readiness'] is True
        assert x['derived_status']=='DOWNLOADED_PUBLIC'
    finally:
        td.cleanup()


def test_unknown_download_does_not_become_authoritative():
    td, root = make_root('Welcome to the portal. General information only.', 'info.pdf')
    try:
        x=classify_candidate(root)
        assert x['content_quality'] in {'UNKNOWN_RETRIEVED_DOCUMENT','EXTRACTION_EMPTY'}
        assert x['gate_readiness'] is False
        assert x['derived_status'] in {'DCE_CONTENT_UNVERIFIED','DOWNLOADED_PUBLIC_EMPTY'}
    finally:
        td.cleanup()
