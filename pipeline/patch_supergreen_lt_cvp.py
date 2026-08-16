from __future__ import annotations

from pathlib import Path

PATH = Path('.github/workflows/supergreen-discovery-v2.yml')
SOURCE = 'LT_CVP_API'

text = PATH.read_text(encoding='utf-8')
original = text

matrix_old = 'UK_PCS_OCDS, UK_FTS_OCDS]'
matrix_new = 'UK_PCS_OCDS, UK_FTS_OCDS, LT_CVP_API]'
if SOURCE not in text:
    if matrix_old not in text:
        raise SystemExit('SuperGreen source-matrix anchor missing')
    text = text.replace(matrix_old, matrix_new, 1)

case_anchor = '            UK_FTS_OCDS) if [ "$DISCOVERY_MODE" = reconcile ]; then days=30; pages=150; else days=5; pages=80; fi; python pipeline/discover_uk_fts_ocds.py --output "$DISCOVERY_OUT" --lookback-days "$days" --max-pages "$pages" --page-size 100 ;;\n'
lt_case = '            LT_CVP_API) python -m pip install --disable-pip-version-check -q brotli; if [ "$DISCOVERY_MODE" = reconcile ]; then pages=200; else pages=40; fi; python pipeline/discover_lt_cvp_api.py --output "$DISCOVERY_OUT" --page-size 250 --max-pages "$pages" ;;\n'
if lt_case not in text:
    if case_anchor not in text:
        raise SystemExit('UK_FTS_OCDS case anchor missing')
    text = text.replace(case_anchor, case_anchor + lt_case, 1)

if text != original:
    PATH.write_text(text, encoding='utf-8')
    print('Patched SuperGreen with LT_CVP_API')
else:
    print('No changes needed')
