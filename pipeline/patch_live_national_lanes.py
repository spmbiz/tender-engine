from __future__ import annotations

import re
from pathlib import Path

PATH=Path('.github/workflows/supergreen-discovery-v2.yml')
text=PATH.read_text(encoding='utf-8')
original=text

anchor='  global-official-discovery:'
pos=text.find(anchor)
if pos<0: raise SystemExit('global-official-discovery anchor missing')
head=text[:pos];tail=text[pos:]

# Add national sources to the global official source matrix without touching ePPS above.
m=re.search(r'(\n\s*source:\s*\[)([^\]]+)(\])',tail)
if not m: raise SystemExit('global source matrix missing')
items=[x.strip() for x in m.group(2).split(',') if x.strip()]
for source in ('SI_EJN','SK_UVO','EE_RHR'):
    if source not in items: items.append(source)
replacement=m.group(1)+', '.join(items)+m.group(3)
tail=tail[:m.start()]+replacement+tail[m.end():]

# Add explicit source scripts. Idempotent and positioned before generic fallback.
case_anchor="            IT_ANAC_DELTA) python pipeline/discover_it_anac_delta.py ;;\n"
if case_anchor not in tail: raise SystemExit('IT_ANAC_DELTA case anchor missing')
extra=''
if 'SI_EJN) python pipeline/discover_si_ejn_browser.py ;;' not in tail:
    extra += '            SI_EJN) python pipeline/discover_si_ejn_browser.py ;;\n'
if 'SK_UVO) python pipeline/discover_sk_uvo.py ;;' not in tail:
    extra += '            SK_UVO) python pipeline/discover_sk_uvo.py ;;\n'
if 'EE_RHR) python pipeline/discover_ee_rhr.py --output "$DISCOVERY_OUT"' not in tail:
    extra += '            EE_RHR) if [ "$DISCOVERY_MODE" = reconcile ]; then months=3; else months=2; fi; python pipeline/discover_ee_rhr.py --output "$DISCOVERY_OUT" --months "$months" ;;\n'
tail=tail.replace(case_anchor,case_anchor+extra,1)
text=head+tail

# Ensure the global worker reuses system Chrome for browser-backed national lanes.
install_line='      - run: python -m pip install --disable-pip-version-check -q requests beautifulsoup4 playwright\n'
reuse='''      - name: Reuse runner Chrome for browser-backed national lanes\n        run: |\n          chrome="$(command -v google-chrome || command -v google-chrome-stable || command -v chromium || true)"\n          if [ -n "$chrome" ]; then echo "CHROME_BIN=$chrome" >> "$GITHUB_ENV"; fi\n'''
pos=text.find(anchor);head=text[:pos];tail=text[pos:]
if 'Reuse runner Chrome for browser-backed national lanes' not in tail:
    if install_line not in tail: raise SystemExit('global playwright install line missing')
    tail=tail.replace(install_line,install_line+reuse,1)
text=head+tail

if text==original:
    print('No changes needed')
else:
    PATH.write_text(text,encoding='utf-8')
    print('Patched SuperGreen Discovery V2 with SI_EJN + SK_UVO + EE_RHR')
