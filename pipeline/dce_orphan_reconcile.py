from __future__ import annotations

"""Recover durable DCE work that is no longer the controller's pending lease.

A controller/recovery race must never cause already-persisted candidate packs to be
selected again. This module scans a bounded recent DCE run window, proves durable
single-writer execution from the bundle manifest, rehydrates the exact materialized
queue from the same Release, and merges only actually-executed candidate IDs into
processed_candidate_ids.
"""

import json
import re
from typing import Any

BUNDLE_MANIFEST = "dce-canonical-packs-manifest.json"
MAX_TRACKED_DCE_RUNS = 2_000
MAX_REMEMBERED_CANDIDATES = 100_000


def _slugify(value: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", value or "candidate").strip("-")
    return (s or "candidate")[:120]


def _dedupe(values):
    return list(dict.fromkeys(str(x) for x in values if str(x).strip()))


def _release_assets(fc: Any, run_id: str):
    rel = fc.get_release(f"dce-harvest-{run_id}")
    if not rel:
        return None, []
    rows = []
    for page in range(1, 20):
        payload = fc.api(f"/repos/{fc.REPO}/releases/{rel['id']}/assets?per_page=100&page={page}").json()
        if not isinstance(payload, list):
            return None, []
        rows.extend(x for x in payload if isinstance(x, dict))
        if len(payload) < 100:
            break
    return rel, rows


def _download_named(fc: Any, rel: dict, rows: list[dict], name: str) -> bytes | None:
    if not any(str(x.get("name") or "") == name for x in rows):
        return None
    return fc.download_asset({**rel, "assets": rows}, name)


def _exact_executed_ids(fc: Any, run_id: str) -> list[str] | None:
    rel, rows = _release_assets(fc, run_id)
    if not rel:
        return None
    names = {str(x.get("name") or "") for x in rows}
    if BUNDLE_MANIFEST not in names:
        return None

    manifest_blob = _download_named(fc, rel, rows, BUNDLE_MANIFEST)
    if not manifest_blob:
        return None
    manifest = json.loads(manifest_blob.decode("utf-8"))
    if manifest.get("contract") != "DCE_SINGLE_WRITER_RELEASE_BUNDLE_V1":
        return None
    executed_slugs = set()
    for bundle in manifest.get("bundles") or []:
        for member in bundle.get("members") or []:
            name = str(member.get("name") or "")
            if name.startswith("candidate-") and name.endswith(".tar.gz"):
                executed_slugs.add(name[len("candidate-"):-len(".tar.gz")])
    if not executed_slugs:
        return None

    queue_name = f"dce-candidate-queue-{run_id}.jsonl"
    queue_blob = _download_named(fc, rel, rows, queue_name)
    if not queue_blob:
        return None
    exact = []
    for line in queue_blob.decode("utf-8", errors="replace").splitlines():
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if not isinstance(rec, dict):
            continue
        cid = str(rec.get("candidate_id") or "").strip()
        if cid and _slugify(cid) in executed_slugs:
            exact.append(cid)
    return _dedupe(exact)


def reconcile(fc: Any, state: dict, actions: list[dict], *, recent_limit: int = 20) -> None:
    tracked = set(str(x) for x in state.get("processed_dce_runs", []))
    current_pending = state.get("pending_dce_batch") or {}
    current_run_id = str(current_pending.get("workflow_run_id") or "")
    recovered = []

    # Run status is deliberately not a gate: a parent workflow can remain stale
    # in_progress even after a recovery workflow has durably written the bundle.
    for run in fc.workflow_runs("dce-fanout-v2.yml", limit=recent_limit):
        rid = str(run.get("id") or "")
        if not rid or rid in tracked or rid == current_run_id:
            continue
        try:
            exact = _exact_executed_ids(fc, rid)
        except Exception as exc:
            actions.append({
                "type": "dce_orphan_reconcile_retryable",
                "workflow_run_id": rid,
                "error": str(exc)[:300],
            })
            continue
        if exact is None:
            continue
        before = len(state.get("processed_candidate_ids", []))
        state["processed_candidate_ids"] = _dedupe(
            list(state.get("processed_candidate_ids", [])) + exact
        )[-MAX_REMEMBERED_CANDIDATES:]
        added = len(state["processed_candidate_ids"]) - before
        tracked.add(rid)
        recovered.append({
            "workflow_run_id": rid,
            "durable_executed": len(exact),
            "net_new_processed_ids": max(0, added),
        })

    state["processed_dce_runs"] = _dedupe(list(tracked))[-MAX_TRACKED_DCE_RUNS:]
    if recovered:
        actions.append({
            "type": "durable_orphan_dce_reconciliation",
            "runs": recovered,
            "runs_recovered": len(recovered),
            "durable_candidates_recovered": sum(x["durable_executed"] for x in recovered),
        })
