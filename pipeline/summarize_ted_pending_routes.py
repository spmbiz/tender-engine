from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlparse


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None


def host_of(url: str) -> str:
    try:
        return urlparse(str(url or "")).netloc.lower().split(":")[0]
    except Exception:
        return ""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="route-sample")
    ap.add_argument("--json-out", default="pending-route-summary.json")
    ap.add_argument("--md-out", default="pending-route-summary.md")
    args = ap.parse_args()

    root = Path(args.root)
    host_counts: Counter[str] = Counter()
    portal_counts: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    examples: dict[str, list[dict]] = defaultdict(list)
    manifests = 0
    pending_manifests = 0

    for path in root.rglob("manifest.json"):
        m = load_json(path)
        if not isinstance(m, dict):
            continue
        manifests += 1
        status = str(m.get("status") or "UNKNOWN")
        status_counts[status] += 1
        if status != "TED_DOWNSTREAM_ADAPTER_PENDING":
            continue
        pending_manifests += 1
        candidate = m.get("candidate") or {}
        cid = str(m.get("candidate_id") or candidate.get("candidate_id") or "")
        title = str(candidate.get("title") or "")
        seen = set()
        for item in m.get("ted_unsupported_routes") or []:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "")
            host = host_of(url)
            portal = str(item.get("portal") or "UNCLASSIFIED")
            key = (host, portal, url)
            if key in seen:
                continue
            seen.add(key)
            if host:
                host_counts[host] += 1
            portal_counts[portal] += 1
            bucket = host or "(no-host)"
            if len(examples[bucket]) < 4:
                examples[bucket].append({"candidate_id": cid, "title": title[:220], "portal": portal, "url": url})

    payload = {
        "manifests_scanned": manifests,
        "pending_manifests": pending_manifests,
        "status_counts": dict(status_counts.most_common()),
        "pending_host_counts": dict(host_counts.most_common()),
        "pending_portal_counts": dict(portal_counts.most_common()),
        "examples": dict(examples),
    }
    Path(args.json_out).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = [
        "## TED downstream adapter backlog",
        "",
        f"Small-pack manifests scanned: **{manifests}**; `TED_DOWNSTREAM_ADAPTER_PENDING`: **{pending_manifests}**.",
        "",
        "This section is routing telemetry, not a tender-quality verdict.",
        "",
        "### Highest-frequency unresolved hosts",
        "",
    ]
    if not host_counts:
        lines.append("- No unresolved TED downstream host was recovered from the sampled small packs.")
    else:
        for host, count in host_counts.most_common(30):
            lines.append(f"- **{host}** — {count} pending route(s)")
            for ex in examples.get(host, [])[:2]:
                lines.append(f"  - {ex['candidate_id']} | {ex['portal']} | {ex['title']} | {ex['url']}")
    lines += ["", "### Unresolved route classifications", ""]
    for portal, count in portal_counts.most_common(20):
        lines.append(f"- **{portal}** — {count}")
    Path(args.md_out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
