from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path


def audit(registry_path: Path, repo_root: Path) -> dict:
    data = json.loads(registry_path.read_text(encoding="utf-8"))
    entries = data.get("entries") or []
    by_status = Counter()
    by_priority = defaultdict(Counter)
    missing_implementations = []
    duplicate_keys = []
    seen = set()

    for entry in entries:
        key = str(entry.get("key") or "")
        status = str(entry.get("status") or "UNKNOWN")
        priority = str(entry.get("priority") or "UNSET")
        by_status[status] += 1
        by_priority[priority][status] += 1
        if key in seen:
            duplicate_keys.append(key)
        seen.add(key)

        implementation = entry.get("implementation")
        if status in {"LIVE_EXISTING", "SHADOW_ADDED", "AUTHORIZED_IMPORT"} and implementation:
            if not (repo_root / str(implementation)).exists():
                missing_implementations.append({"key": key, "implementation": implementation})

    p0_open = [
        entry["key"]
        for entry in entries
        if str(entry.get("priority", "")).startswith("P0")
        and entry.get("status") in {"PENDING_IMPLEMENTATION", "PENDING_AUTH"}
    ]
    return {
        "schema_version": data.get("schema_version"),
        "entries": len(entries),
        "status_counts": dict(sorted(by_status.items())),
        "priority_status_counts": {k: dict(sorted(v.items())) for k, v in sorted(by_priority.items())},
        "p0_open": sorted(p0_open),
        "missing_implementations": missing_implementations,
        "duplicate_keys": sorted(duplicate_keys),
        "valid": not missing_implementations and not duplicate_keys,
        "note": "Implementation presence is not live validation; health/run evidence remains authoritative.",
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--registry", type=Path, default=Path("control/oss_provider_registry.json"))
    ap.add_argument("--repo-root", type=Path, default=Path("."))
    ap.add_argument("--output", type=Path)
    args = ap.parse_args()
    result = audit(args.registry, args.repo_root)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    if not result["valid"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
