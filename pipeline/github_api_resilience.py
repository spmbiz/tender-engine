from __future__ import annotations

"""Resilient low-call GitHub API transport for the autonomous Tender controller.

The controller uses one mutable Release for a few small state documents. Heavy DCE
payloads are persisted elsewhere by a single aggregate writer. This module keeps
controller state safe when the installation token is temporarily rate-limited:

- bounded exponential backoff + jitter for 403/429/5xx;
- no full Release refresh after every mutable asset upload;
- a semantic local checkpoint for controller-state.json, committed by the workflow;
- newest-state wins between the Release copy and the checked-out checkpoint;
- reporting assets degrade gracefully on an exhausted rate limit.
"""

import json
import random
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

CHECKPOINT = Path("control/controller_state_checkpoint.json")
MAX_ATTEMPTS = 5
BASE_BACKOFF = 3.0
MAX_BACKOFF = 45.0


class RateLimitDeferred(RuntimeError):
    pass


def _is_rate_limit(response: requests.Response) -> bool:
    if response.status_code == 429:
        return True
    if response.status_code != 403:
        return False
    text = (response.text or "").lower()
    remaining = response.headers.get("X-RateLimit-Remaining")
    return remaining == "0" or "rate limit" in text or "secondary rate" in text


def _sleep_seconds(response: requests.Response | None, attempt: int) -> float:
    if response is not None:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return min(MAX_BACKOFF, max(1.0, float(retry_after)))
            except Exception:
                pass
        reset = response.headers.get("X-RateLimit-Reset")
        if reset:
            try:
                delta = float(reset) - datetime.now(timezone.utc).timestamp()
                if 0 < delta <= MAX_BACKOFF:
                    return max(1.0, delta)
            except Exception:
                pass
    base = min(MAX_BACKOFF, BASE_BACKOFF * (2 ** max(0, attempt - 1)))
    return base + random.uniform(0, min(3.0, base * 0.2))


def _request(method: str, url: str, *, headers: dict[str, str], timeout: int = 60, **kwargs) -> requests.Response:
    last: requests.Response | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            r = requests.request(method, url, headers=headers, timeout=timeout, **kwargs)
        except requests.RequestException as exc:
            if attempt == MAX_ATTEMPTS:
                raise RuntimeError(f"GitHub network failure after {attempt} attempts: {exc}") from exc
            time.sleep(_sleep_seconds(None, attempt))
            continue
        last = r
        retryable = _is_rate_limit(r) or r.status_code >= 500
        if not retryable:
            return r
        if attempt < MAX_ATTEMPTS:
            wait = _sleep_seconds(r, attempt)
            print(json.dumps({
                "github_api_retry": {
                    "method": method,
                    "status": r.status_code,
                    "attempt": attempt,
                    "sleep_seconds": round(wait, 2),
                    "rate_limited": _is_rate_limit(r),
                }
            }, separators=(",", ":")))
            time.sleep(wait)
    assert last is not None
    if _is_rate_limit(last):
        raise RateLimitDeferred(f"GitHub API rate limit remained exhausted after {MAX_ATTEMPTS} attempts")
    return last


def _parse_updated_at(blob: bytes | None) -> float:
    if not blob:
        return 0.0
    try:
        data = json.loads(blob.decode("utf-8"))
        raw = str(data.get("updated_at") or "")
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp() if raw else 0.0
    except Exception:
        return 0.0


def _semantic_state(obj: dict) -> dict:
    # updated_at is observability, not lease/progress state. Ignoring it prevents a
    # five-minute controller tick from producing a Git commit when nothing changed.
    out = dict(obj)
    out.pop("updated_at", None)
    return out


def _read_checkpoint() -> bytes | None:
    try:
        if CHECKPOINT.is_file() and CHECKPOINT.stat().st_size > 0:
            return CHECKPOINT.read_bytes()
    except Exception:
        pass
    return None


def _write_checkpoint(data: bytes) -> None:
    try:
        obj = json.loads(data.decode("utf-8"))
    except Exception:
        return
    existing_blob = _read_checkpoint()
    if existing_blob:
        try:
            existing = json.loads(existing_blob.decode("utf-8"))
            if _semantic_state(existing) == _semantic_state(obj):
                return
        except Exception:
            pass
    CHECKPOINT.parent.mkdir(parents=True, exist_ok=True)
    CHECKPOINT.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def install(fc: Any) -> None:
    """Monkey-patch the shared fleet_controller module in-place."""

    def req(method: str, url: str, **kwargs):
        r = _request(method, url, headers=fc.HEADERS, timeout=60, **kwargs)
        if r.status_code >= 400:
            raise RuntimeError(f"GitHub API {method} {url} -> {r.status_code}: {r.text[:1000]}")
        return r

    def api(path: str, method: str = "GET", **kwargs):
        return req(method, fc.API + path, **kwargs)

    def get_release(tag: str):
        r = _request(
            "GET",
            f"{fc.API}/repos/{fc.REPO}/releases/tags/{tag}",
            headers=fc.HEADERS,
            timeout=30,
        )
        if r.status_code == 404:
            return None
        if r.status_code >= 400:
            raise RuntimeError(r.text[:1000])
        return r.json()

    def download_asset(rel: dict, name: str) -> bytes | None:
        remote: bytes | None = None
        asset = next((a for a in rel.get("assets", []) if a.get("name") == name), None)
        if asset:
            headers = dict(fc.HEADERS)
            headers["Accept"] = "application/octet-stream"
            try:
                r = _request("GET", asset["url"], headers=headers, timeout=60)
                if r.status_code >= 400:
                    raise RuntimeError(f"asset download {name}: {r.status_code} {r.text[:500]}")
                remote = r.content
            except RateLimitDeferred:
                if name != fc.STATE_ASSET:
                    print(json.dumps({"github_state_transport": {"asset": name, "status": "RATE_LIMIT_DEFERRED_READ"}}, separators=(",", ":")))
                    return None

        if name == fc.STATE_ASSET:
            local = _read_checkpoint()
            if local and _parse_updated_at(local) > _parse_updated_at(remote):
                print(json.dumps({"github_state_transport": {"asset": name, "source": "repo_checkpoint_newer_than_release"}}, separators=(",", ":")))
                return local
            if remote is not None:
                return remote
            if local is not None:
                print(json.dumps({"github_state_transport": {"asset": name, "source": "repo_checkpoint_release_unavailable"}}, separators=(",", ":")))
                return local
        return remote

    def upload_asset(rel: dict, name: str, data: bytes, content_type: str = "application/octet-stream"):
        if name == fc.STATE_ASSET:
            _write_checkpoint(data)

        existing = next((a for a in rel.get("assets", []) if a.get("name") == name), None)
        try:
            if existing:
                d = _request(
                    "DELETE",
                    f"{fc.API}/repos/{fc.REPO}/releases/assets/{existing['id']}",
                    headers=fc.HEADERS,
                    timeout=30,
                )
                if d.status_code not in (204, 404):
                    raise RuntimeError(f"asset delete {name}: {d.status_code} {d.text[:500]}")

            upload_url = rel["upload_url"].split("{")[0]
            headers = dict(fc.HEADERS)
            headers["Content-Type"] = content_type
            r = _request(
                "POST",
                upload_url,
                headers=headers,
                timeout=60,
                params={"name": name},
                data=data,
            )
            if r.status_code >= 400:
                raise RuntimeError(f"asset upload {name}: {r.status_code} {r.text[:500]}")
            new_asset = r.json()
            rel["assets"] = [a for a in rel.get("assets", []) if a.get("name") != name] + [new_asset]
            return new_asset
        except RateLimitDeferred:
            print(json.dumps({
                "github_state_transport": {
                    "asset": name,
                    "status": "RATE_LIMIT_DEFERRED_WRITE",
                    "checkpoint_available": name == fc.STATE_ASSET and CHECKPOINT.exists(),
                }
            }, separators=(",", ":")))
            return None

    fc.req = req
    fc.api = api
    fc.get_release = get_release
    fc.download_asset = download_asset
    fc.upload_asset = upload_asset
