from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

OUT = Path(os.getenv('OUT', 'ted-shape-probe'))
OUT.mkdir(parents=True, exist_ok=True)
now = datetime.now(timezone.utc)
start = now - timedelta(days=int(os.getenv('LOOKBACK_DAYS', '120')))
query = f"PD = ({start:%Y%m%d} <> {now:%Y%m%d}) AND form-type = competition"
body = {
    'query': query,
    'fields': [
        'publication-number','notice-title','buyer-name','publication-date','deadline',
        'estimated-value-proc','estimated-value-cur-proc','description-proc','procedure-type',
        'notice-type','form-type','classification-cpv'
    ],
    'limit': 5,
    'scope': 'ACTIVE',
    'checkQuerySyntax': False,
    'paginationMode': 'PAGE_NUMBER',
    'page': 1,
}
r = requests.post(
    'https://api.ted.europa.eu/v3/notices/search',
    json=body,
    timeout=60,
    headers={'User-Agent':'Tender-Engine/2.1 response-shape probe'},
)
r.raise_for_status()
data = r.json()
(OUT/'response.json').write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
items = data.get('notices') or data.get('results') or data.get('items') or []
first = items[0] if isinstance(items, list) and items and isinstance(items[0], dict) else None
summary = {
    'query': query,
    'top_level_keys': list(data.keys()),
    'totalNoticeCount': data.get('totalNoticeCount'),
    'items_type': type(items).__name__,
    'items_count': len(items) if isinstance(items, list) else None,
    'first_item_type': type(items[0]).__name__ if isinstance(items, list) and items else None,
    'first_item_keys': list(first.keys()) if first else None,
}
(OUT/'summary.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding='utf-8')
print(json.dumps(summary, indent=2, ensure_ascii=False))
print('--- FIRST NOTICE RAW ---')
print(json.dumps(first, indent=2, ensure_ascii=False)[:30000])
