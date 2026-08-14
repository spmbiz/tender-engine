from __future__ import annotations

import argparse
import os
from urllib.parse import quote

import requests

API = "https://circleci.com/api/v2"


def fail(message: str) -> None:
    raise SystemExit(message)


def main() -> None:
    ap = argparse.ArgumentParser(description="Install/replace the CircleCI FLEET_GITHUB_TOKEN project environment variable without printing its value.")
    ap.add_argument("--project-slug", default="gh/walidgdg1-ai/tender-engine")
    ap.add_argument("--name", default="FLEET_GITHUB_TOKEN")
    args = ap.parse_args()

    circle_token = os.environ.get("CIRCLE_TOKEN", "").strip()
    github_token = os.environ.get("FLEET_GITHUB_TOKEN", "").strip()
    if not circle_token:
        fail("CIRCLE_TOKEN is required in the local environment.")
    if not github_token:
        fail("FLEET_GITHUB_TOKEN is required in the local environment.")

    project = quote(args.project_slug, safe="/")
    name = quote(args.name, safe="")
    headers = {
        "Circle-Token": circle_token,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    # Replace cleanly because the create endpoint is deterministic while an existing
    # variable may otherwise return a conflict depending on CircleCI project state.
    existing = requests.get(f"{API}/project/{project}/envvar/{name}", headers=headers, timeout=30)
    if existing.status_code == 200:
        deleted = requests.delete(f"{API}/project/{project}/envvar/{name}", headers=headers, timeout=30)
        if deleted.status_code >= 400:
            fail(f"Could not replace existing {args.name}: HTTP {deleted.status_code}")
    elif existing.status_code not in (404,):
        fail(f"Could not inspect CircleCI project environment: HTTP {existing.status_code}")

    created = requests.post(
        f"{API}/project/{project}/envvar",
        headers=headers,
        json={"name": args.name, "value": github_token},
        timeout=30,
    )
    if created.status_code != 201:
        fail(f"CircleCI environment variable create failed: HTTP {created.status_code} {created.text[:300]}")

    verified = requests.get(f"{API}/project/{project}/envvar/{name}", headers=headers, timeout=30)
    if verified.status_code != 200:
        fail(f"CircleCI environment variable verification failed: HTTP {verified.status_code}")

    payload = verified.json()
    masked = payload.get("value")
    print(f"CircleCI bridge installed: {payload.get('name', args.name)}={masked or '[masked]'}")
    print("Secret value was not printed. The next circleci-fleet tick can pass durable-bridge and unlock the 30-way fanout.")


if __name__ == "__main__":
    main()
