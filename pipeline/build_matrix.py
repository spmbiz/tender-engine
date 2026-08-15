from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

BROWSER_PORTALS = {
    "TED","IRELAND_ETENDERS","FR_PLACE","LUX_PMP","SCOTLAND_PCS",
    "CA_CANADABUYS","QC_SEAO","DE_DOE","FR_BOAMP","NZ_GETS","AU_AUSTENDER",
    "US_SAM","US_SAM_BULK","NL_TENDERNED","NL_TENDERNED_RSS","CH_SIMAP","LV_IUB",
    "NO_DOFFIN","PL_EZAMOWIENIA","PL_BZP","GR_KHMDHS","ES_PLACSP","FI_HILMA",
    "PT_BASE_OPEN","PT_BASE","DK_UDBUD","DK_UDBUD_PUBLIC","CZ_ZAKAZKY_GOV","CZ_NIPEZ",
    "CYPRUS_EPPS","LITHUANIA_EPPS","MALTA_EPPS",
    "SI_EJN","SK_UVO",
}
SUPPORTED = BROWSER_PORTALS | {
    "UNGM","DIRECT_HTTP","UK_CONTRACTS_FINDER","GENERIC_EPPS","GENERIC_PUBLIC_PAGE","TED_PUBLIC_PAGE_FAST",
}


def slugify(value: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", value or "candidate").strip("-")
    return (s or "candidate")[:100]


def load_lines(path: Path):
    rows = []
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line: continue
            try: rec = json.loads(line)
            except Exception: continue
            if isinstance(rec, dict): rows.append((line_no, rec))
    return rows


def main():
    ap=argparse.ArgumentParser();ap.add_argument("--queue",default="queues/dce_candidates.jsonl");ap.add_argument("--max-jobs",type=int,default=int(os.getenv("MAX_DCE_JOBS","80")));ap.add_argument("--out",default="matrix.json");args=ap.parse_args()
    include=[];skipped=[]
    for line_no,rec in load_lines(Path(args.queue)):
        status=str(rec.get("status") or "QUEUED").upper()
        if status not in {"QUEUED","READY","DCE_PENDING","AUTO_DCE_PREFETCH"}:
            skipped.append({"line":line_no,"candidate_id":rec.get("candidate_id"),"reason":f"status:{status}"});continue
        portal=str(rec.get("portal") or rec.get("portal_key") or rec.get("source") or "").upper()
        if portal not in SUPPORTED:
            skipped.append({"line":line_no,"candidate_id":rec.get("candidate_id"),"reason":f"unsupported:{portal}"});continue
        cid=str(rec.get("candidate_id") or f"line-{line_no}")
        include.append({"line_no":line_no,"candidate_id":cid,"slug":slugify(cid),"portal":portal,"needs_browser":portal in BROWSER_PORTALS})
        if len(include)>=args.max_jobs: break
    payload={"include":include};Path(args.out).write_text(json.dumps(payload,indent=2),encoding="utf-8");Path("matrix_skipped.json").write_text(json.dumps(skipped,indent=2),encoding="utf-8")
    gh=os.getenv("GITHUB_OUTPUT")
    if gh:
        with open(gh,"a",encoding="utf-8") as f:f.write("matrix="+json.dumps(payload,separators=(",",":"))+"\n");f.write(f"count={len(include)}\n")
    print(json.dumps({"count":len(include),"matrix":payload,"skipped":skipped},indent=2))

if __name__=="__main__":main()
