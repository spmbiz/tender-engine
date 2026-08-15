#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,re
from pathlib import Path
from historical_lab.open_world_next_wave_v3 import PATTERNS,RX,read_jsonl,blob

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--semantic',required=True);ap.add_argument('--code-only',required=True);ap.add_argument('--out',required=True);ap.add_argument('--semantic-start',type=int,default=1000);ap.add_argument('--semantic-end',type=int,default=3000);a=ap.parse_args();out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    sem=read_jsonl(a.semantic);code=read_jsonl(a.code_only);rows=[('SEMANTIC_NEXT_WAVE',r) for r in sem[a.semantic_start:a.semantic_end]]+[('CODE_ONLY_FULL',r) for r in code]
    tagged=[];untagged=[]
    for q,r in rows:
        hits=[name for name,rx in RX.items() if rx.search(blob(r))]
        if hits:tagged.append((q,r,hits))
        else:untagged.append((q,r))
    ordered=sorted(untagged,key=lambda z:z[1].get('triage') or 0,reverse=True)
    with (out/'untagged_all.jsonl').open('w',encoding='utf-8') as f:
        for q,r in ordered:f.write(json.dumps({'queue':q,**r},ensure_ascii=False)+'\n')
    with (out/'tagged_all.jsonl').open('w',encoding='utf-8') as f:
        for q,r,hits in tagged:f.write(json.dumps({'queue':q,'mechanisms':hits,**r},ensure_ascii=False)+'\n')
    summary={'version':'HISTORICAL_OPEN_WORLD_UNTAGGED_FULL_V3_1','semantic_total_available':len(sem),'semantic_slice':[a.semantic_start,a.semantic_end],'code_only_total_available':len(code),'clusters_reviewed':len(rows),'tagged_clusters':len(tagged),'untagged_clusters':len(untagged),'historical_only':True,'record_deletion':False,'purpose':'Persist the complete remaining unknown queue for economic/native-code analysis rather than truncating to top 1000.'}
    (out/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8')
    (out/'REPORT.md').write_text(f"# Open-World Full Unknown Queue v3.1\n\n- reviewed **{len(rows):,}**\n- tagged by mechanism dictionary **{len(tagged):,}**\n- still untagged and now fully persisted **{len(untagged):,}**\n\nNo record or cluster is dropped because it lacks a known mechanism.\n",encoding='utf-8')
if __name__=='__main__':main()
