from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlparse


def load(path: Path):
    try:
        return json.loads(path.read_text(encoding='utf-8', errors='replace'))
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', required=True)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()
    root = Path(args.root)
    statuses = Counter()
    domains = Counter()
    pending_domains = Counter()
    examples = defaultdict(list)
    rows = []
    for mp in sorted(root.rglob('manifest.json')):
        m = load(mp)
        if not isinstance(m, dict):
            continue
        cid = str(m.get('candidate_id') or '')
        status = str(m.get('status') or 'UNKNOWN')
        statuses[status] += 1
        attempts = m.get('ted_downstream_attempts') or []
        unsupported = m.get('ted_unsupported_routes') or []
        seen_domains = set()
        for item in list(attempts) + list(unsupported):
            if not isinstance(item, dict):
                continue
            url = str(item.get('url') or '')
            host = urlparse(url).netloc.lower().split(':')[0]
            if host:
                seen_domains.add(host)
        tr = m.get('ted_resolution') or {}
        if not seen_domains:
            for item in (tr.get('downstream') or [] if isinstance(tr, dict) else []):
                if isinstance(item, dict):
                    host = urlparse(str(item.get('url') or '')).netloc.lower().split(':')[0]
                    if host:
                        seen_domains.add(host)
        for host in sorted(seen_domains):
            domains[host] += 1
            if status == 'TED_DOWNSTREAM_ADAPTER_PENDING':
                pending_domains[host] += 1
                if len(examples[host]) < 5:
                    examples[host].append(cid)
        rows.append({'candidate_id': cid, 'status': status, 'domains': sorted(seen_domains)})
    result = {
        'candidates': len(rows),
        'status_counts': dict(statuses.most_common()),
        'all_downstream_domains': dict(domains.most_common()),
        'pending_downstream_domains': dict(pending_domains.most_common()),
        'pending_examples': dict(examples),
        'rows': rows,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k != 'rows'}, indent=2, ensure_ascii=False))

if __name__ == '__main__':
    main()
