from pathlib import Path

p=Path('pipeline/build_notice_intelligence_ledger.py')
text=p.read_text(encoding='utf-8')

old_prev='''    ledger: list[dict[str, Any]] = []
    change_queue: list[dict[str, Any]] = []
'''
new_prev='''    previous_sources: Counter[str] = Counter(str(row.get("source") or "UNKNOWN") for row in previous.values())

    ledger: list[dict[str, Any]] = []
    change_queue: list[dict[str, Any]] = []
'''

old_drop='''    dropped = sorted(set(previous) - seen)
    summary = {
'''
new_drop='''    dropped = sorted(set(previous) - seen)
    previous_count = len(previous)
    current_count = len(ledger)
    total_ratio = (current_count / previous_count) if previous_count else 1.0
    source_regressions = {}
    for source, prior_count in previous_sources.items():
        now_count = int(sources.get(source, 0))
        if prior_count >= 500 and now_count < prior_count * 0.50:
            source_regressions[source] = {
                "previous": prior_count,
                "current": now_count,
                "ratio": (now_count / prior_count) if prior_count else 0.0,
            }
    hard_fail = bool(
        (previous_count >= 1000 and total_ratio < 0.80)
        or source_regressions
    )
    summary = {
'''

old_rules='''        "sources": dict(sorted(sources.items())),
        "rules": {
'''
new_rules='''        "sources": dict(sorted(sources.items())),
        "generation_qualification": {
            "status": "REJECT_REGRESSION" if hard_fail else "PASS",
            "hard_fail": hard_fail,
            "current_vs_previous_ratio": total_ratio,
            "minimum_total_ratio": 0.80,
            "major_source_min_previous": 500,
            "major_source_min_ratio": 0.50,
            "source_regressions": source_regressions,
            "rule": "Never advance the stable ledger on catastrophic whole-universe loss or a >50% collapse of a previously large source. Snapshot carry-forward should normally prevent these conditions; hitting this guard requires investigation or an explicit code change, never silent acceptance.",
        },
        "rules": {
'''

old_main='''    write_jsonl(Path(args.ledger_out), ledger)
    write_jsonl(Path(args.change_queue_out), changes)
'''
new_main='''    qualification = summary.get("generation_qualification") or {}
    if qualification.get("hard_fail"):
        Path(args.summary_out).write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\\n", encoding="utf-8")
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        raise SystemExit("Refusing to advance ledger: snapshot generation regressed below durable safety thresholds")

    write_jsonl(Path(args.ledger_out), ledger)
    write_jsonl(Path(args.change_queue_out), changes)
'''

for old,new,label in ((old_prev,new_prev,'previous_sources'),(old_drop,new_drop,'qualification'),(old_rules,new_rules,'summary'),(old_main,new_main,'main_guard')):
    if old not in text:
        raise SystemExit(f'ledger regression anchor missing: {label}')
    if text.count(old)!=1:
        raise SystemExit(f'ledger regression anchor non-unique: {label}')
    text=text.replace(old,new,1)

p.write_text(text,encoding='utf-8')
print('ledger regression guard applied')
