import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'pipeline' / 'source_coverage_guard.py'


def write_stats(root: Path, name: str, payload=None):
    p=root/name; p.mkdir(parents=True,exist_ok=True)
    (p/'stats.json').write_text(json.dumps(payload or {'items':1}))


def test_partial_coverage_is_explicit_not_fatal():
    with tempfile.TemporaryDirectory() as td:
        root=Path(td)/'d'; out=Path(td)/'coverage.json'; root.mkdir()
        write_stats(root,'discovery-ted')
        proc=subprocess.run([sys.executable,str(SCRIPT),'--root',str(root),'--out',str(out)],capture_output=True,text=True)
        assert proc.returncode==0
        x=json.loads(out.read_text())
        assert x['coverage_status']=='PARTIAL_WORLD_COVERAGE'
        assert x['worldwide_claim_allowed'] is False
        assert 'UNGM_PUBLIC' in x['external_missing_lanes']


def test_strict_mode_fails_on_missing_lanes():
    with tempfile.TemporaryDirectory() as td:
        root=Path(td)/'d'; out=Path(td)/'coverage.json'; root.mkdir()
        proc=subprocess.run([sys.executable,str(SCRIPT),'--root',str(root),'--out',str(out),'--strict'],capture_output=True,text=True)
        assert proc.returncode!=0
