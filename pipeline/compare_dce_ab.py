from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

BAD_STATUSES = {
    "ADAPTER_PENDING",
    "STARTED",
    "WORKER_ERROR",
    "BATCH_EXCEPTION",
    "UNKNOWN",
}
RETRYABLE_STATUSES = {"ERROR_RETRYABLE"}
EXPLICIT_TERMINAL = {
    "DOWNLOADED_PUBLIC",
    "NO_PUBLIC_FILE",
    "AUTH_REQUIRED",
    "CAPTCHA_REQUIRED",
    "INTEREST_RECORDING_REQUIRED",
    "ROUTE_INCOMPLETE",
    "GENERIC_PUBLIC_PAGE_UNRESOLVED",
    "TED_ROUTE_UNRESOLVED",
    "TED_DOWNSTREAM_ADAPTER_PENDING",
}


def _load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None


def _batch(root: Path) -> dict[str, dict]:
    obj = _load_json(root / "batch_results.json")
    rows = obj if isinstance(obj, list) else []
    return {str(r.get("candidate_id") or ""): r for r in rows if isinstance(r, dict) and r.get("candidate_id")}


def _manifests(root: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for path in root.rglob("manifest.json"):
        obj = _load_json(path)
        if isinstance(obj, dict) and obj.get("candidate_id"):
            out[str(obj["candidate_id"])] = obj
    return out


def _file_shas(manifest: dict) -> set[str]:
    return {
        str(f.get("sha256"))
        for f in manifest.get("files") or []
        if isinstance(f, dict) and f.get("sha256")
    }


def _file_count(manifest: dict) -> int:
    return len([f for f in manifest.get("files") or [] if isinstance(f, dict)])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline-dir", required=True)
    ap.add_argument("--current-dir", required=True)
    ap.add_argument("--out", default="dce-ab-report")
    ap.add_argument("--fail-on-regression", action="store_true")
    args = ap.parse_args()

    baseline_root = Path(args.baseline_dir)
    current_root = Path(args.current_dir)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    bb = _batch(baseline_root)
    cb = _batch(current_root)
    bm = _manifests(baseline_root)
    cm = _manifests(current_root)
    ids = sorted(set(bb) | set(cb) | set(bm) | set(cm))

    rows = []
    hard_regressions = []
    warnings = []
    improvements = []

    for cid in ids:
        br = bb.get(cid, {})
        cr = cb.get(cid, {})
        bman = bm.get(cid, {})
        cman = cm.get(cid, {})
        bs = str(cr.get("baseline_status") or br.get("status") or bman.get("status") or "MISSING")
        cs = str(cr.get("status") or cman.get("status") or "MISSING")
        bf = _file_count(bman)
        cf = _file_count(cman)
        bsha = _file_shas(bman)
        csha = _file_shas(cman)
        bel = float(br.get("elapsed_seconds") or 0)
        cel = float(cr.get("elapsed_seconds") or 0)
        bcode = br.get("returncode")
        ccode = cr.get("returncode")

        reasons: list[str] = []
        warn: list[str] = []
        improved: list[str] = []

        if cid not in bb or cid not in bm:
            reasons.append("baseline_result_missing")
        if cid not in cb or cid not in cm:
            reasons.append("current_result_missing")

        if (bf > 0 or bs == "DOWNLOADED_PUBLIC") and not (cf > 0 and cs == "DOWNLOADED_PUBLIC"):
            reasons.append("lost_downloaded_public_dce")
        if bcode in (0, None) and ccode not in (0, None):
            reasons.append(f"returncode_regressed:{bcode}->{ccode}")
        if bs not in BAD_STATUSES and cs in BAD_STATUSES:
            reasons.append(f"terminal_to_broken_status:{bs}->{cs}")
        if bs in EXPLICIT_TERMINAL and cs == "MISSING":
            reasons.append("current_manifest_missing")

        if bf == 0 and cf > 0:
            improved.append("new_public_download")
        if bs in BAD_STATUSES | RETRYABLE_STATUSES and cs in EXPLICIT_TERMINAL:
            improved.append(f"resolved_status:{bs}->{cs}")
        if bs != "DOWNLOADED_PUBLIC" and cs == "DOWNLOADED_PUBLIC":
            improved.append(f"status_to_download:{bs}->{cs}")

        if bf > 0 and cf > 0 and bsha and csha and not (bsha & csha):
            warn.append("download_sha_set_changed")
        if bs != cs:
            warn.append(f"status_changed:{bs}->{cs}")
        if bel > 0 and cel > max(bel * 2.5, bel + 20):
            warn.append(f"latency_regression:{bel:.3f}s->{cel:.3f}s")
        if cs in RETRYABLE_STATUSES:
            warn.append("current_retryable_error")

        row = {
            "candidate_id": cid,
            "baseline": {"status": bs, "files": bf, "elapsed_seconds": bel, "returncode": bcode},
            "current": {"status": cs, "files": cf, "elapsed_seconds": cel, "returncode": ccode},
            "hard_regressions": reasons,
            "warnings": warn,
            "improvements": improved,
        }
        rows.append(row)
        if reasons:
            hard_regressions.append(row)
        if warn:
            warnings.append(row)
        if improved:
            improvements.append(row)

    summary = {
        "candidate_count": len(ids),
        "baseline_results": len(bb),
        "current_results": len(cb),
        "hard_regression_count": len(hard_regressions),
        "warning_count": len(warnings),
        "improvement_count": len(improvements),
        "baseline_statuses": dict(Counter(str(r.get("status") or "MISSING") for r in bb.values())),
        "current_statuses": dict(Counter(str(r.get("status") or "MISSING") for r in cb.values())),
        "baseline_wall_candidate_seconds": round(sum(float(r.get("elapsed_seconds") or 0) for r in bb.values()), 3),
        "current_wall_candidate_seconds": round(sum(float(r.get("elapsed_seconds") or 0) for r in cb.values()), 3),
        "hard_regressions": hard_regressions,
        "warnings": warnings,
        "improvements": improvements,
        "rows": rows,
    }
    (out_dir / "report.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = [
        "# DCE rollback A/B report",
        "",
        f"Candidates: **{len(ids)}**",
        f"Hard regressions: **{len(hard_regressions)}**",
        f"Warnings: **{len(warnings)}**",
        f"Improvements: **{len(improvements)}**",
        f"Baseline candidate-seconds: **{summary['baseline_wall_candidate_seconds']}**",
        f"Current candidate-seconds: **{summary['current_wall_candidate_seconds']}**",
        "",
        "| candidate | baseline | current | files b→c | time b→c | verdict |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        b = row["baseline"]
        c = row["current"]
        verdict = "REGRESSION" if row["hard_regressions"] else ("IMPROVED" if row["improvements"] else ("WARN" if row["warnings"] else "SAME/OK"))
        lines.append(
            f"| {row['candidate_id']} | {b['status']} | {c['status']} | {b['files']}→{c['files']} | {b['elapsed_seconds']:.2f}s→{c['elapsed_seconds']:.2f}s | {verdict} |"
        )
    if hard_regressions:
        lines += ["", "## Hard regressions", ""]
        for row in hard_regressions:
            lines.append(f"- **{row['candidate_id']}** — {', '.join(row['hard_regressions'])}")
    if warnings:
        lines += ["", "## Warnings", ""]
        for row in warnings:
            lines.append(f"- **{row['candidate_id']}** — {', '.join(row['warnings'])}")
    (out_dir / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(json.dumps({k: summary[k] for k in (
        "candidate_count", "hard_regression_count", "warning_count", "improvement_count",
        "baseline_wall_candidate_seconds", "current_wall_candidate_seconds"
    )}, indent=2))
    if args.fail_on_regression and hard_regressions:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
