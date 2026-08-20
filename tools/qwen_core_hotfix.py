from pathlib import Path


def patch(path, old, new):
    p=Path(path)
    s=p.read_text(encoding='utf-8')
    if new in s:
        print('already',path)
        return
    if old not in s:
        raise SystemExit(f'missing expected block in {path}: {old[:100]!r}')
    p.write_text(s.replace(old,new,1),encoding='utf-8')
    print('patched',path)

# Qwen classifier defaults and safety heartbeat.
p='.github/workflows/qwen-live-classification.yml'
patch(p,"default: '192'","default: '480'")
patch(p,"- cron: '43 */6 * * *'","- cron: '43 * * * *'")
patch(p,"REQUESTED_PER_SHARD: ${{ github.event.inputs.per_shard || '192' }}","REQUESTED_PER_SHARD: ${{ github.event.inputs.per_shard || '480' }}")
patch(p,"try: n=int(os.environ.get('REQUESTED_PER_SHARD') or 192)\n          except Exception: n=192","try: n=int(os.environ.get('REQUESTED_PER_SHARD') or 480)\n          except Exception: n=480")

# Central DCE hard clamp: even an old or future dispatcher asking for 60 cannot
# starve the semantic backfill.
p='.github/workflows/dce-fanout-v2.yml'
old="""          DCE_MAX_PARALLEL=\"$(python - <<'PY'\n          import os\n          try:\n              requested=int(os.environ.get('DCE_REQUESTED_MAX_PARALLEL') or 24)\n          except Exception:\n              requested=24\n          print(max(1,min(60,requested)))\n          PY\n          )\""" 
new="""          DCE_MAX_PARALLEL=\"$(python - <<'PY'\n          import json, os\n          from pathlib import Path\n          try:\n              requested=int(os.environ.get('DCE_REQUESTED_MAX_PARALLEL') or 24)\n          except Exception:\n              requested=24\n          remaining=0\n          try:\n              remaining=max(0,int(json.loads(Path('control/qwen_live/classification_summary.json').read_text(encoding='utf-8')).get('remaining_classification_queue') or 0))\n          except Exception:\n              pass\n          cap=2 if remaining >= 50000 else 4 if remaining >= 20000 else 6 if remaining >= 5000 else 10 if remaining > 0 else 60\n          print(max(1,min(60,requested,cap)))\n          PY\n          )\"""
patch(p,old,new)

# DCE's direct Qwen gate pre-read is useful, but 4 extra runners every DCE batch is
# excessive during the 100k semantic backfill.
patch(p,"-f workers=4\n          echo \"Direct Qwen DCE handoff dispatched", "-f workers=1\n          echo \"Direct Qwen DCE handoff dispatched")

# Continuous conveyor: request the full bounded worker size and start semantic
# classification before refreshing/dispatching DCE. The DCE drainer is separately
# hard-capped, but ordering Qwen first avoids a race for newly freed slots.
p='.github/workflows/qwen-live-conveyor.yml'
patch(p,"-f per_shard=192 \\\n                -f auto_continue=false", "-f per_shard=480 \\\n                -f auto_continue=false")
patch(p,"echo 'Dispatched next 192-row bounded Qwen realtime pass.'", "echo 'Dispatched next 480-row bounded Qwen realtime pass.'")
patch(p,"          refresh_selection\n          ensure_qwen_running", "          ensure_qwen_running\n          refresh_selection")

print('QWEN_CORE_HOTFIX_OK')
