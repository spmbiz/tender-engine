from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

IMPLEMENTED_STATES = {"LIVE_EXISTING", "SHADOW_ADDED", "AUTHORIZED_IMPORT", "LIVE_VALIDATED"}
OPEN_STATES = {"PENDING_IMPLEMENTATION", "PENDING_AUTH"}


def load_validations(path: Path | None) -> dict:
    if path is None or not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    validations = data.get("validations") or {}
    return validations if isinstance(validations, dict) else {}


def audit(registry_path: Path, repo_root: Path, validations_path: Path | None = None) -> dict:
    data = json.loads(registry_path.read_text(encoding="utf-8"))
    entries = data.get("entries") or []
    validations = load_validations(validations_path or (repo_root / "control" / "oss_provider_validations.json"))
    by_status = Counter()
    by_effective_status = Counter()
    by_priority = defaultdict(Counter)
    missing_implementations = []
    duplicate_keys = []
    unknown_validation_keys = []
    seen = set()
    effective_entries = []

    for entry in entries:
        key = str(entry.get("key") or "")
        status = str(entry.get("status") or "UNKNOWN")
        validation = validations.get(key) if isinstance(validations.get(key), dict) else None
        validation_status = str((validation or {}).get("status") or "")
        effective_status = "LIVE_VALIDATED" if validation_status == "LIVE_VALIDATED" else status
        priority = str(entry.get("priority") or "UNSET")
        by_status[status] += 1
        by_effective_status[effective_status] += 1
        by_priority[priority][effective_status] += 1
        if key in seen:
            duplicate_keys.append(key)
        seen.add(key)

        implementation = (validation or {}).get("implementation") or entry.get("implementation")
        if effective_status in IMPLEMENTED_STATES and implementation:
            if not (repo_root / str(implementation)).exists():
                missing_implementations.append({"key": key, "implementation": implementation})

        effective_entries.append(
            {
                "key": key,
                "priority": priority,
                "registry_status": status,
                "effective_status": effective_status,
                "validation_status": validation_status or None,
            }
        )

    for key in validations:
        if key not in seen:
            unknown_validation_keys.append(key)

    p0_open = [
        item["key"]
        for item in effective_entries
        if item["priority"].startswith("P0") and item["effective_status"] in OPEN_STATES
    ]
    return {
        "schema_version": data.get("schema_version"),
        "entries": len(entries),
        "status_counts": dict(sorted(by_status.items())),
        "effective_status_counts": dict(sorted(by_effective_status.items())),
        "priority_status_counts": {k: dict(sorted(v.items())) for k, v in sorted(by_priority.items())},
        "p0_open": sorted(p0_open),
        "live_validated": sorted(
            item["key"] for item in effective_entries if item["effective_status"] == "LIVE_VALIDATED"
        ),
        "missing_implementations": missing_implementations,
        "duplicate_keys": sorted(duplicate_keys),
        "unknown_validation_keys": sorted(unknown_validation_keys),
        "valid": not missing_implementations and not duplicate_keys and not unknown_validation_keys,
        "note": "Registry state describes implementation intent; validation overlays require concrete run evidence. UNKNOWN and PENDING are never promoted without validation evidence.",
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--registry", type=Path, default=Path("control/oss_provider_registry.json"))
    ap.add_argument("--validations", type=Path, default=Path("control/oss_provider_validations.json"))
    ap.add_argument("--repo-root", type=Path, default=Path("."))
    ap.add_argument("--output", type=Path)
    args = ap.parse_args()
    result = audit(args.registry, args.repo_root, args.validations)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    if not result["valid"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
