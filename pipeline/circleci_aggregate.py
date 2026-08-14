from __future__ import annotations

import base64
import io
import json
import os
import subprocess
import tarfile
import tempfile
from pathlib import Path

import requests

from auto_select_dce import load_jsonl, select

GH = "https://api.github.com"
TOKEN = os.environ.get("FLEET_GITHUB_TOKEN", "")
REPO = os.environ.get("CIRCLE_PROJECT_USERNAME", "") + "/" + os.environ.get("CIRCLE_PROJECT_REPONAME", "")
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
SOURCE_RUN = "circle-" + os.environ.get("CIRCLE_WORKFLOW_ID", "unknown")
TAG = "discovery-harvest-" + SOURCE_RUN


def rel():
    r = requests.get(f"{GH}/repos/{REPO}/releases/tags/{TAG}", headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


def upload(name: str, data: bytes, ctype="application/octet-stream"):
    release = rel()
    for a in release.get("assets", []):
        if a.get("name") == name:
            requests.delete(f"{GH}/repos/{REPO}/releases/assets/{a['id']}", headers=HEADERS, timeout=30).raise_for_status()
    h = dict(HEADERS)
    h["Content-Type"] = ctype
    r = requests.post(release["upload_url"].split("{")[0], headers=h, params={"name": name}, data=data, timeout=120)
    if r.status_code != 201:
        raise RuntimeError(f"upload {name}: {r.status_code} {r.text[:500]}")


def update_file(path: str, text: str):
    gr = requests.get(f"{GH}/repos/{REPO}/contents/{path}?ref=main", headers=HEADERS, timeout=30)
    sha = gr.json().get("sha") if gr.status_code == 200 else None
    payload = {
        "message": f"CircleCI autonomous DCE queue {SOURCE_RUN}",
        "content": base64.b64encode(text.encode()).decode(),
        "branch": "main",
    }
    if sha:
        payload["sha"] = sha
    r = requests.put(f"{GH}/repos/{REPO}/contents/{path}", headers=HEADERS, json=payload, timeout=30)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"queue update: {r.status_code} {r.text[:700]}")


def dispatch(selection_path: str, count: int):
    active = requests.get(f"{GH}/repos/{REPO}/actions/runs?status=in_progress&per_page=50", headers=HEADERS, timeout=30).json().get("workflow_runs", [])
    dce_active = any(x.get("path", "").endswith("dce-fanout-v2.yml") for x in active)
    if dce_active:
        return {"dispatched": False, "reason": "dce_already_active"}
    payload = {
        "ref": "main",
        "inputs": {
            "selection_path": selection_path,
            "source_discovery_run": SOURCE_RUN,
            "max_jobs": str(count),
            "max_parallel": "20",
            "max_shards": "256",
            "jobs_per_shard": "2",
        },
    }
    r = requests.post(f"{GH}/repos/{REPO}/actions/workflows/dce-fanout-v2.yml/dispatches", headers=HEADERS, json=payload, timeout=30)
    if r.status_code != 204:
        raise RuntimeError(f"DCE dispatch: {r.status_code} {r.text[:700]}")
    return {"dispatched": True, "max_parallel": 20}


def main():
    if not TOKEN:
        raise SystemExit("FLEET_GITHUB_TOKEN missing")
    release = rel()
    assets = [a for a in release.get("assets", []) if (a.get("name") or "").startswith("discovery-contracts-finder-circle-")]
    if len(assets) < 1:
        raise SystemExit("no CircleCI shard assets found")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "input"
        root.mkdir()
        for a in assets:
            h = dict(HEADERS)
            h["Accept"] = "application/octet-stream"
            b = requests.get(a["url"], headers=h, timeout=120)
            b.raise_for_status()
            dest = root / a["name"].removesuffix(".tar.gz")
            dest.mkdir()
            with tarfile.open(fileobj=io.BytesIO(b.content), mode="r:gz") as tf:
                tf.extractall(dest, filter="data")
        merged = Path(td) / "merged"
        subprocess.run(["python", "pipeline/merge_discovery.py", "--root", str(root), "--out", str(merged)], check=True)
        packets = Path(td) / "wide_read_packets"
        subprocess.run(["python", "pipeline/wide_read_packets.py", "--input", str(merged / "current_candidates.jsonl"), "--out", str(packets), "--packet-size", "250"], check=True)
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            tf.add(merged, arcname="merged")
            tf.add(packets, arcname="wide_read_packets")
        upload(f"supergreen-wide-read-{SOURCE_RUN}.tar.gz", buf.getvalue(), "application/gzip")
        summary = json.loads((merged / "stats.json").read_text())
        summary.update({"provider": "circleci", "source_run": SOURCE_RUN, "shard_assets": len(assets)})
        upload(f"discovery-summary-{SOURCE_RUN}.json", json.dumps(summary, indent=2).encode(), "application/json")
        rows = list(load_jsonl(merged / "current_candidates.jsonl"))
        for r in rows:
            r["wide_read_run_id"] = SOURCE_RUN
        selected = select(rows, minimum=34, limit=320, blocked_ids=set())
        qpath = "queues/auto_circle_selection_latest.jsonl"
        qtext = "".join(json.dumps(x, ensure_ascii=False, separators=(",", ":")) + "\n" for x in selected)
        result = {"selected": len(selected), "dce": {"dispatched": False, "reason": "empty_selection"}}
        if selected:
            update_file(qpath, qtext)
            result["dce"] = dispatch(qpath, len(selected))
        upload(f"circle-summary-{SOURCE_RUN}.json", json.dumps(result, indent=2).encode(), "application/json")
        print(json.dumps({**summary, **result}, indent=2))


if __name__ == "__main__":
    main()
