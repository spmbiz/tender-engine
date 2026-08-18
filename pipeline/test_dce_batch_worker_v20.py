from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import dce_batch_worker as v20


def main() -> None:
    assert v20._probe_manifest_is_success({"status": "DOWNLOADED_PUBLIC", "files": [{"sha256": "abc"}]})
    assert not v20._probe_manifest_is_success({"status": "DOWNLOADED_PUBLIC", "files": []})
    assert not v20._probe_manifest_is_success({"status": "ERROR_RETRYABLE", "files": [{"sha256": "abc"}]})
    assert not v20._probe_manifest_is_success({"status": "DOWNLOADED_PUBLIC", "files": ["not-a-file-record"]})

    with TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        stage = v20._probe_stage_root(str(out))
        assert stage != out
        assert stage.parent == out.parent
        assert stage.name.startswith(".out-http-probe-v20")

    assert v20.ACTIVE_WORKER == "pipeline/dce_worker_v20.py"
    print({
        "scheduler": "candidate-http-probe-then-browser-fallback",
        "promote_requires": "DOWNLOADED_PUBLIC+file-record",
        "staging_isolated": True,
        "status": "ok",
    })


if __name__ == "__main__":
    main()
