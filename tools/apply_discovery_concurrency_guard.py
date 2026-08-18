from pathlib import Path

p=Path('.github/workflows/supergreen-discovery-v2.yml')
text=p.read_text(encoding='utf-8')
anchor='''permissions:\n  contents: write\n\n'''
replacement='''permissions:\n  contents: write\n\nconcurrency:\n  group: supergreen-discovery-v2-global\n  cancel-in-progress: false\n\n'''
if 'group: supergreen-discovery-v2-global' in text:
    print('discovery concurrency guard already present')
    raise SystemExit(0)
if anchor not in text or text.count(anchor)!=1:
    raise SystemExit('discovery concurrency anchor missing/non-unique')
p.write_text(text.replace(anchor,replacement,1),encoding='utf-8')
print('discovery concurrency guard applied')
