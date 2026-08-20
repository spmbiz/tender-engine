from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if new in text:
        print(f"already patched: {path}")
        return
    if old not in text:
        raise SystemExit(f"expected block missing in {path}")
    text = text.replace(old, new, 1)
    p.write_text(text, encoding="utf-8")
    print(f"patched: {path}")


# 1) Universal DCE fanout clamp. Every dispatcher is downstream of this file, so
# no DCE path can steal the semantic backfill slots even if it requests 60.
replace_once(
    ".github/workflows/dce-fanout-v2.yml",
    """          DCE_MAX_PARALLEL=\"$(python - <<'PY'\n          import os\n          try:\n              requested=int(os.environ.get('DCE_REQUESTED_MAX_PARALLEL') or 24)\n          except Exception:\n              requested=24\n          print(max(1,min(60,requested)))\n          PY\n          )\"\n""",
    """          DCE_MAX_PARALLEL=\"$(python - <<'PY'\n          import json, os\n          from pathlib import Path\n          try:\n              requested=int(os.environ.get('DCE_REQUESTED_MAX_PARALLEL') or 24)\n          except Exception:\n              requested=24\n          remaining=0\n          p=Path('control/qwen_live/classification_summary.json')\n          try:\n              remaining=max(0,int(json.loads(p.read_text(encoding='utf-8')).get('remaining_classification_queue') or 0))\n          except Exception:\n              remaining=0\n          if remaining >= 50000:\n              backfill_cap=2\n          elif remaining >= 20000:\n              backfill_cap=4\n          elif remaining >= 5000:\n              backfill_cap=6\n          elif remaining > 0:\n              backfill_cap=10\n          else:\n              backfill_cap=60\n          print(max(1,min(60,requested,backfill_cap)))\n          PY\n          )\"\n""",
)

# 2) Qwen live defaults: use the large bounded shard by default and keep an hourly
# safety trigger. The 10-minute guardian remains the primary continuation path.
replace_once(
    ".github/workflows/qwen-live-classification.yml",
    """        default: '192'\n""",
    """        default: '480'\n""",
)
replace_once(
    ".github/workflows/qwen-live-classification.yml",
    """    - cron: '43 */6 * * *'\n""",
    """    - cron: '43 * * * *'\n""",
)
replace_once(
    ".github/workflows/qwen-live-classification.yml",
    """          REQUESTED_PER_SHARD: ${{ github.event.inputs.per_shard || '192' }}\n""",
    """          REQUESTED_PER_SHARD: ${{ github.event.inputs.per_shard || '480' }}\n""",
)
replace_once(
    ".github/workflows/qwen-live-classification.yml",
    """          try: n=int(os.environ.get('REQUESTED_PER_SHARD') or 192)\n          except Exception: n=192\n""",
    """          try: n=int(os.environ.get('REQUESTED_PER_SHARD') or 480)\n          except Exception: n=480\n""",
)

# 3) Recovery drainer must give semantic classification first claim on capacity.
# If Qwen is not active yet, do NOT start DCE first; the later continuation step
# starts Qwen. On the next tick DCE may consume only the bounded residual slice.
replace_once(
    ".github/workflows/qwen-live-recovery-drainer.yml",
    """          # Prevent duplicate Qwen-DCE runs on main, while allowing the separate\n          # autonomous fleet-dce batch to keep working in parallel.\n""",
    """          # Semantic backfill owns first claim on Tender capacity. Starting DCE\n          # before Qwen was a starvation bug: DCE occupied the free slots, then the\n          # Qwen plan observed zero capacity and produced no classification workers.\n          qwen_active=\"$(gh run list --workflow qwen-live-classification.yml --limit 30 --json status --jq '[.[] | select(.status==\"queued\" or .status==\"in_progress\" or .status==\"waiting\" or .status==\"pending\")] | length')\"\n          if [ '${{ steps.rebuild.outputs.remaining }}' != '0' ] && [ \"$qwen_active\" -eq 0 ]; then\n            echo 'No Qwen semantic pass active yet; reserving free Tender slots for Qwen first.'\n            exit 0\n          fi\n\n          # Prevent duplicate Qwen-DCE runs on main, while allowing the separate\n          # autonomous fleet-dce batch to keep working in parallel.\n""",
)
replace_once(
    ".github/workflows/qwen-live-recovery-drainer.yml",
    """          from pipeline.global_admission import dynamic_tender_parallel\n          allowed,_=dynamic_tender_parallel(10)\n          print(max(0,min(10,int(allowed))))\n""",
    """          import json\n          from pathlib import Path\n          from pipeline.global_admission import dynamic_tender_parallel\n          try:\n              remaining=max(0,int(json.loads(Path('control/qwen_live/classification_summary.json').read_text(encoding='utf-8')).get('remaining_classification_queue') or 0))\n          except Exception:\n              remaining=0\n          cap=2 if remaining >= 50000 else 4 if remaining >= 20000 else 6 if remaining >= 5000 else 10\n          allowed,_=dynamic_tender_parallel(cap)\n          print(max(0,min(cap,int(allowed))))\n""",
)
replace_once(
    ".github/workflows/qwen-live-recovery-drainer.yml",
    """              -f per_shard=192 \\\n""",
    """              -f per_shard=480 \\\n""",
)

# 4) Qwen DCE triage is useful, but during the 100k semantic backfill it must not
# reserve four extra CPU runners every five minutes. Scale it with the same backlog.
replace_once(
    ".github/workflows/qwen-dce-drainer.yml",
    """            echo \"Dispatching recent missing Qwen DCE pre-read for durable DCE run $rid age=${age_seconds}s\"\n            gh workflow run qwen-dce-triage.yml --repo \"$REPO\" --ref main -f dce_run_id=\"$rid\" -f workers=4\n""",
    """            workers=4\n            remaining=0\n            if [ -s control/qwen_live/classification_summary.json ]; then\n              remaining=\"$(python -c \"import json;print(int(json.load(open('control/qwen_live/classification_summary.json')).get('remaining_classification_queue') or 0))\" 2>/dev/null || echo 0)\"\n            fi\n            if [ \"$remaining\" -ge 50000 ]; then workers=1; elif [ \"$remaining\" -ge 20000 ]; then workers=2; fi\n            echo \"Dispatching recent missing Qwen DCE pre-read for durable DCE run $rid age=${age_seconds}s workers=$workers semantic_backlog=$remaining\"\n            gh workflow run qwen-dce-triage.yml --repo \"$REPO\" --ref main -f dce_run_id=\"$rid\" -f workers=\"$workers\"\n""",
)

# 5) Backfill kick: a stale queued workflow must not block continuation forever.
# Healthy in-progress work is never preempted. Only queued/waiting/pending runs with
# no active Qwen pass and age >45m are cancelled before a fresh 480-worker pass.
replace_once(
    ".github/workflows/qwen-backfill-kick.yml",
    """          active=\"$(gh run list --workflow qwen-live-classification.yml --limit 30 --json status --jq '[.[] | select(.status==\"queued\" or .status==\"in_progress\" or .status==\"waiting\" or .status==\"pending\")] | length')\"\n          if [ \"$active\" -gt 0 ]; then\n            echo \"Qwen already active/queued ($active); no duplicate dispatch.\"\n            exit 0\n          fi\n""",
    """          in_progress=\"$(gh run list --workflow qwen-live-classification.yml --limit 30 --json status --jq '[.[] | select(.status==\"in_progress\")] | length')\"\n          if [ \"$in_progress\" -gt 0 ]; then\n            echo \"Qwen has $in_progress healthy in-progress pass(es); no duplicate dispatch.\"\n            exit 0\n          fi\n\n          now_epoch=\"$(date -u +%s)\"\n          mapfile -t waiting_runs < <(gh run list --workflow qwen-live-classification.yml --limit 30 --json databaseId,status,createdAt --jq '.[] | select(.status==\"queued\" or .status==\"waiting\" or .status==\"pending\") | \"\\(.databaseId)|\\(.createdAt)\"')\n          for entry in \"${waiting_runs[@]}\"; do\n            rid=\"${entry%%|*}\"\n            created=\"${entry#*|}\"\n            created_epoch=\"$(date -u -d \"$created\" +%s 2>/dev/null || echo \"$now_epoch\")\"\n            age=\"$((now_epoch-created_epoch))\"\n            if [ \"$age\" -gt 2700 ]; then\n              echo \"Cancelling stale queued Qwen run $rid age=${age}s\"\n              gh run cancel \"$rid\" || true\n            fi\n          done\n\n          queued=\"$(gh run list --workflow qwen-live-classification.yml --limit 30 --json status --jq '[.[] | select(.status==\"queued\" or .status==\"waiting\" or .status==\"pending\")] | length')\"\n          if [ \"$queued\" -gt 0 ]; then\n            echo \"Qwen already has $queued fresh queued pass(es); no duplicate dispatch.\"\n            exit 0\n          fi\n""",
)

print("Qwen blocker repair v2 complete")
