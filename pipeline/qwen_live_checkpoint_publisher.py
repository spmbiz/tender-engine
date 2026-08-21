#!/usr/bin/env python3
from __future__ import annotations

import base64
import gzip
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Iterable

try:
    from qwen_notice_post_guard import guard as post_guard
except ImportError:  # package/test execution
    from pipeline.qwen_notice_post_guard import guard as post_guard


CHECKPOINT_SUFFIX = "-guarded-checkpoint.jsonl"
DEFAULT_INTERVAL_SECONDS = 20.0


def _arg_value(argv: list[str], name: str) -> str | None:
    try:
        idx = argv.index(name)
    except ValueError:
        return None
    if idx + 1 >= len(argv):
        return None
    value = str(argv[idx + 1]).strip()
    return value or None


def _opener(path: Path):
    return gzip.open(path, "rt", encoding="utf-8") if path.suffix == ".gz" else path.open("r", encoding="utf-8")


def _candidate_id(row: dict[str, Any]) -> str:
    notice = row.get("notice") if isinstance(row.get("notice"), dict) else {}
    return str(
        row.get("canonical_notice_id")
        or row.get("candidate_id")
        or row.get("id")
        or notice.get("candidate_id")
        or notice.get("notice_id")
        or notice.get("id")
        or notice.get("i")
        or ""
    ).strip()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    rows: list[dict[str, Any]] = []
    with _opener(path) as fh:
        for lineno, raw in enumerate(fh, start=1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                row = json.loads(raw)
            except Exception as exc:
                raise ValueError(f"invalid checkpoint JSONL {path}:{lineno}: {type(exc).__name__}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"non-object checkpoint JSONL {path}:{lineno}")
            rows.append(row)
    return rows


def load_exact_context(queue_path: Path) -> dict[str, dict[str, Any]]:
    contexts: dict[str, dict[str, Any]] = {}
    for row in read_jsonl(queue_path):
        candidate = _candidate_id(row)
        if not candidate:
            raise ValueError(f"queue row missing canonical id in {queue_path}")
        if candidate in contexts:
            raise ValueError(f"duplicate canonical id in checkpoint queue: {candidate}")
        contexts[candidate] = row
    return contexts


def guarded_checkpoint_rows(
    raw_rows: Iterable[dict[str, Any]],
    exact_context: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Apply the exact-context post guard before a row may leave the worker.

    This is deliberately the same guard contract used by the final worker output.
    Missing exact context fails closed: an intermediate row is never published on
    embedded/truncated context alone.
    """
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in raw_rows:
        candidate = _candidate_id(row)
        if not candidate:
            raise ValueError("raw checkpoint row missing canonical id")
        if candidate in seen:
            raise ValueError(f"duplicate raw checkpoint candidate: {candidate}")
        seen.add(candidate)
        context = exact_context.get(candidate)
        if context is None:
            raise ValueError(f"missing exact checkpoint context: {candidate}")
        guarded = post_guard(row, context, context_source="worker_live_checkpoint_exact_shard")
        if _candidate_id(guarded) != candidate:
            raise ValueError(f"post guard changed candidate id: {candidate}")
        out.append(guarded)
    return out


def write_jsonl_atomic(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    count = 0
    with tmp.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
            count += 1
        fh.flush()
        os.fsync(fh.fileno())
    tmp.replace(path)
    return count


def checkpoint_path_for(raw_path: Path) -> Path:
    name = raw_path.name
    if name.endswith("-raw.jsonl"):
        name = name[: -len("-raw.jsonl")] + CHECKPOINT_SUFFIX
    else:
        name = raw_path.stem + CHECKPOINT_SUFFIX
    return raw_path.with_name(name)


def _github_auth_env() -> dict[str, str] | None:
    env = os.environ.copy()
    if env.get("GH_TOKEN"):
        return env
    try:
        header = subprocess.check_output(
            ["git", "config", "--local", "--get", "http.https://github.com/.extraheader"],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=5,
        ).strip()
        match = re.search(r"basic\s+(\S+)", header, flags=re.I)
        if not match:
            return None
        decoded = base64.b64decode(match.group(1)).decode("utf-8", errors="ignore")
        token = decoded.split(":", 1)[1] if ":" in decoded else ""
        if not token:
            return None
        env["GH_TOKEN"] = token
        return env
    except Exception:
        return None


def _ensure_release(tag: str, repo: str, env: dict[str, str]) -> bool:
    view = subprocess.run(
        ["gh", "release", "view", tag, "--repo", repo],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=15,
        check=False,
    )
    if view.returncode == 0:
        return True
    create = subprocess.run(
        [
            "gh", "release", "create", tag, "--repo", repo,
            "--target", os.environ.get("GITHUB_SHA", "main"),
            "--title", f"Qwen Live Progress {os.environ.get('GITHUB_RUN_ID', '')}",
            "--notes", "Externally readable Qwen progress plus exact-context guarded intermediate checkpoints.",
        ],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=25,
        check=False,
    )
    if create.returncode == 0:
        return True
    retry = subprocess.run(
        ["gh", "release", "view", tag, "--repo", repo],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=15,
        check=False,
    )
    return retry.returncode == 0


def upload_checkpoint(path: Path, *, run_id: str, repo: str) -> bool:
    if not path.exists() or path.stat().st_size == 0:
        return False
    env = _github_auth_env()
    if env is None:
        return False
    tag = f"qwen-live-progress-{run_id}"
    if not _ensure_release(tag, repo, env):
        return False
    try:
        proc = subprocess.run(
            ["gh", "release", "upload", tag, str(path), "--clobber", "--repo", repo],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
            check=False,
        )
    except Exception as exc:
        print(
            "QWEN_GUARDED_CHECKPOINT_UPLOAD_FAIL "
            + json.dumps({"error": type(exc).__name__, "asset": path.name}, separators=(",", ":")),
            flush=True,
        )
        return False
    if proc.returncode != 0:
        print(
            "QWEN_GUARDED_CHECKPOINT_UPLOAD_FAIL "
            + json.dumps(
                {"returncode": proc.returncode, "asset": path.name, "stderr_tail": (proc.stderr or "")[-300:]},
                separators=(",", ":"),
            ),
            flush=True,
        )
        return False
    return True


def publish_once(
    raw_path: Path,
    checkpoint_path: Path,
    exact_context: dict[str, dict[str, Any]],
    *,
    run_id: str,
    repo: str,
    previous_digest: str | None,
) -> tuple[str | None, int, bool]:
    if not raw_path.exists() or raw_path.stat().st_size == 0:
        return previous_digest, 0, False
    raw_bytes = raw_path.read_bytes()
    digest = hashlib.sha256(raw_bytes).hexdigest()
    if digest == previous_digest:
        return previous_digest, 0, False
    raw_rows = read_jsonl(raw_path)
    if not raw_rows:
        return digest, 0, False
    guarded = guarded_checkpoint_rows(raw_rows, exact_context)
    count = write_jsonl_atomic(checkpoint_path, guarded)
    uploaded = upload_checkpoint(checkpoint_path, run_id=run_id, repo=repo)
    if uploaded:
        print(
            "QWEN_GUARDED_CHECKPOINT_PUBLISHED "
            + json.dumps(
                {"run_id": run_id, "asset": checkpoint_path.name, "rows": count, "raw_sha256": digest},
                separators=(",", ":"),
            ),
            flush=True,
        )
        return digest, count, True
    # Retry the same raw generation next interval when transport/auth was transient.
    return previous_digest, count, False


def _publisher_loop(
    stop: threading.Event,
    *,
    raw_path: Path,
    checkpoint_path: Path,
    exact_context: dict[str, dict[str, Any]],
    run_id: str,
    repo: str,
    interval_seconds: float,
) -> None:
    digest: str | None = None
    while True:
        try:
            digest, _, _ = publish_once(
                raw_path,
                checkpoint_path,
                exact_context,
                run_id=run_id,
                repo=repo,
                previous_digest=digest,
            )
        except Exception as exc:
            print(
                "QWEN_GUARDED_CHECKPOINT_BUILD_FAIL "
                + json.dumps({"error": type(exc).__name__, "detail": str(exc)[-500:]}, separators=(",", ":")),
                flush=True,
            )
        if stop.wait(interval_seconds):
            break
    # One final best-effort flush when the classifier returns normally.
    try:
        publish_once(
            raw_path,
            checkpoint_path,
            exact_context,
            run_id=run_id,
            repo=repo,
            previous_digest=digest,
        )
    except Exception as exc:
        print(
            "QWEN_GUARDED_CHECKPOINT_FINAL_FAIL "
            + json.dumps({"error": type(exc).__name__, "detail": str(exc)[-500:]}, separators=(",", ":")),
            flush=True,
        )


def run_with_live_checkpoints(main_fn: Callable[[], None], argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    if os.environ.get("GITHUB_ACTIONS") != "true":
        main_fn()
        return
    run_id = str(os.environ.get("GITHUB_RUN_ID") or "").strip()
    repo = str(os.environ.get("GITHUB_REPOSITORY") or "").strip()
    raw = _arg_value(argv, "--out")
    queue = _arg_value(argv, "--queue")
    if not run_id.isdigit() or not repo or not raw or not queue:
        main_fn()
        return

    raw_path = Path(raw)
    queue_path = Path(queue)
    try:
        exact_context = load_exact_context(queue_path)
    except Exception as exc:
        print(
            "QWEN_GUARDED_CHECKPOINT_DISABLED "
            + json.dumps({"reason": type(exc).__name__, "detail": str(exc)[-500:]}, separators=(",", ":")),
            flush=True,
        )
        main_fn()
        return

    checkpoint_path = checkpoint_path_for(raw_path)
    try:
        interval = float(os.environ.get("QWEN_CHECKPOINT_UPLOAD_INTERVAL_SECONDS") or DEFAULT_INTERVAL_SECONDS)
    except Exception:
        interval = DEFAULT_INTERVAL_SECONDS
    interval = max(5.0, min(120.0, interval))
    stop = threading.Event()
    thread = threading.Thread(
        target=_publisher_loop,
        kwargs={
            "stop": stop,
            "raw_path": raw_path,
            "checkpoint_path": checkpoint_path,
            "exact_context": exact_context,
            "run_id": run_id,
            "repo": repo,
            "interval_seconds": interval,
        },
        name="qwen-guarded-checkpoint-publisher",
        daemon=True,
    )
    thread.start()
    print(
        "QWEN_GUARDED_CHECKPOINT_ENABLED "
        + json.dumps({"run_id": run_id, "asset": checkpoint_path.name, "interval_seconds": interval}, separators=(",", ":")),
        flush=True,
    )
    try:
        main_fn()
    finally:
        stop.set()
        thread.join(timeout=35.0)
