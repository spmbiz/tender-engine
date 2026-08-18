from pathlib import Path

p=Path('pipeline/discover_ungm_public.py')
text=p.read_text(encoding='utf-8')
old='page = await browser.new_page(viewport={"width": 1440, "height": 1000}, user_agent=UA)'
new='page = await browser.new_page(viewport={"width": 1440, "height": 1000})'
if old not in text:
    raise SystemExit('UNGM UA anchor missing')
if text.count(old) != 1:
    raise SystemExit('UNGM UA anchor not unique')
p.write_text(text.replace(old,new,1),encoding='utf-8')
print('UNGM default browser UA restored')
