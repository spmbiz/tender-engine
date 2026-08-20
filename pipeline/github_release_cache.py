from __future__ import annotations

import io
import json
import os
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

DEFAULT_REPO = "walidgdg1-ai/tender-engine"
UA = "Tender-Engine/7.6 (+durable verified discovery release cache)"


def parse_dt(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def session() -> requests.Session:
    s = requests.Session()
    headers = {"User-Agent": UA, "Accept": "application/vnd.github+json"}
    token = os.getenv("GH_TOKEN", "").strip() or os.getenv("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    s.headers.update(headers)
    return s


def release_by_tag(tag: str, *, repo: str = DEFAULT_REPO) -> dict[str, Any]:
    if not tag:
        raise RuntimeError("RELEASE_TAG_EMPTY")
    url = f"https://api.github.com/repos/{repo}/releases/tags/{tag}"
    response = session().get(url, timeout=45)
    response.raise_for_status()
    value = response.json()
    if not isinstance(value, dict):
        raise RuntimeError("RELEASE_METADATA_NOT_OBJECT")
    return value


def release_age_seconds(release: dict[str, Any], *, now: datetime | None = None) -> float | None:
    now = now or datetime.now(timezone.utc)
    published = parse_dt(release.get("published_at") or release.get("created_at"))
    if not published:
        return None
    return max(0.0, (now - published.astimezone(timezone.utc)).total_seconds())


def asset(release: dict[str, Any], name: str) -> dict[str, Any]:
    matches = [x for x in release.get("assets") or [] if isinstance(x, dict) and x.get("name") == name]
    if len(matches) != 1:
        raise RuntimeError(f"RELEASE_ASSET_CARDINALITY name={name!r} matches={len(matches)}")
    return matches[0]


def download_asset(release: dict[str, Any], name: str) -> bytes:
    item = asset(release, name)
    url = item.get("browser_download_url")
    if not url:
        raise RuntimeError(f"RELEASE_ASSET_URL_MISSING:{name}")
    s = session()
    response = s.get(url, timeout=180, headers={**s.headers, "Accept": "application/octet-stream"})
    response.raise_for_status()
    body = response.content
    expected = item.get("size")
    if expected is not None and int(expected) != len(body):
        raise RuntimeError(f"RELEASE_ASSET_SIZE_MISMATCH expected={expected} actual={len(body)}")
    return body


def extract_tar_gz_bytes(body: bytes, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(body), mode="r:gz") as archive:
        root = destination.resolve()
        members = []
        for member in archive.getmembers():
            target = (destination / member.name).resolve()
            if target != root and root not in target.parents:
                raise RuntimeError(f"UNSAFE_TAR_MEMBER:{member.name}")
            members.append(member)
        archive.extractall(destination, members=members)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON_NOT_OBJECT:{path}")
    return value
