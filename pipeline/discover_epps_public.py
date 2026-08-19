from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

BASE_URL = os.environ["EPPS_BASE_URL"].rstrip("/")
SOURCE = os.environ["EPPS_SOURCE"].strip().upper()
PREFIX = os.getenv("EPPS_ID_PREFIX", SOURCE).strip()
TZ = ZoneInfo(os.getenv("EPPS_TIMEZONE", "Europe/Brussels"))
OUT = Path(os.getenv("DISCOVERY_OUT", f"discovery/global/{SOURCE}"))
OUT.mkdir(parents=True, exist_ok=True)
PAGE_START = max(1, int(os.getenv("PAGE_START", "1")))
PAGE_END = max(PAGE_START, int(os.getenv("PAGE_END", "20")))
PAGE_SIZE = max(10, min(100, int(os.getenv("PAGE_SIZE", "100"))))
NOW = datetime.now(TZ)
S = requests.Session()
S.headers.update({"User-Agent":"Tender-Engine/6.8 (+public procurement research; official ePPS public registries)","Accept":"text/html,application/xhtml+xml,*/*"})
RESOURCE_RE=re.compile(r"resourceId=(\d+)",re.I)
TEXTUAL_DEADLINE_RE=re.compile(r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})\s+(\d{2}:\d{2}:\d{2})\s+(?:CET|CEST|EET|EEST|GMT|UTC|IST)\s+(\d{4})\b",re.I)
NUMERIC_DEADLINE_RE=re.compile(r"\b(\d{1,2}/\d{1,2}/\d{4})\s+(\d{1,2}:\d{2}(?::\d{2})?)\b")
EXPIRED_STATUS=re.compile(r"\b(?:awarded|archived|cancelled|canceled|closed|evaluation|completed|withdrawn|concluded|for archival)\b|(?:Ακυρώ|Κατακυρ|Παγιωμ|Ολοκληρ)",re.I)
LIVE_STATUS=re.compile(r"\b(?:tender submission|open|awaiting tender opening|submission)\b|(?:Υποβολ|Προσφορ)",re.I)
CAPTCHA_RE=re.compile(r"\bcaptcha\b|type the code shown|κωδικό captcha",re.I)

def clean(v): return " ".join(str(v or "").split())
def request(url):
    last=None
    for attempt in range(4):
        try:
            r=S.get(url,timeout=45,allow_redirects=True);last=r
            if r.status_code in (408,425,429) or r.status_code>=500:
                if attempt<3:time.sleep(min(12,2**attempt)+0.25*attempt);continue
            r.raise_for_status();return r
        except Exception:
            if attempt==3:raise
            time.sleep(min(8,2**attempt))
    if last is not None:last.raise_for_status()
    raise RuntimeError(url)
def parse_deadline(text):
    hits=list(NUMERIC_DEADLINE_RE.finditer(text or ""))
    for m in reversed(hits):
        raw=f"{m.group(1)} {m.group(2)}"
        for fmt in ("%d/%m/%Y %H:%M:%S","%d/%m/%Y %H:%M"):
            try:return datetime.strptime(raw,fmt).replace(tzinfo=TZ)
            except ValueError:pass
    hits=list(TEXTUAL_DEADLINE_RE.finditer(text or ""))
    if hits:
        m=hits[-1]
        try:return datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(4)} {m.group(3)}","%b %d %Y %H:%M:%S").replace(tzinfo=TZ)
        except ValueError:pass
    return None
def cells_for(tr):return [clean(td.get_text(" ",strip=True)) for td in tr.find_all("td")]
def header_map(soup):
    best=[]
    for tr in soup.find_all("tr"):
        headers=[clean(x.get_text(" ",strip=True)).lower() for x in tr.find_all("th")]
        if len(headers)>len(best):best=headers
    return best
def pick(cells,headers,needles):
    for i,h in enumerate(headers):
        if any(n in h for n in needles) and i<len(cells):return cells[i]
    return None
def parse_page(html,page_url,page_no):
    soup=BeautifulSoup(html,"html.parser");headers=header_map(soup);rows=[]
    for tr in soup.find_all("tr"):
        rid=None;detail_url=None;title=None
        for a in tr.find_all("a",href=True):
            href=a.get("href") or "";m=RESOURCE_RE.search(href)
            if m:rid=m.group(1);detail_url=urljoin(page_url,href);title=clean(a.get_text(" ",strip=True)) or title;break
        if not rid:
            m=RESOURCE_RE.search(str(tr))
            if not m:continue
            rid=m.group(1);detail_url=f"{BASE_URL}/epps/cft/prepareViewCfTWS.do?resourceId={rid}"
        text=clean(tr.get_text(" ",strip=True));cells=cells_for(tr);deadline=parse_deadline(text)
        if deadline and deadline<NOW:continue
        status=pick(cells,headers,("status","κατάσταση"))
        if status and EXPIRED_STATUS.search(status) and not LIVE_STATUS.search(status):continue
        if EXPIRED_STATUS.search(text) and not LIVE_STATUS.search(text):continue
        title=title or pick(cells,headers,("cft title","τίτλος")) or (cells[1] if len(cells)>1 else None)
        buyer=pick(cells,headers,("contracting authority"," ca ","αναθέτουσα")) or (cells[3] if len(cells)>4 else None)
        ca_unique=pick(cells,headers,("unique id","μοναδικός")) or (cells[2] if len(cells)>3 else None)
        procedure=pick(cells,headers,("procedure","διαδικασία"));value=pick(cells,headers,("estimated value","εκτιμώμενη αξία"));estimated_value=None
        if value:
            m=re.search(r"\d[\d,. ]*",value)
            if m:
                try:estimated_value=float(m.group(0).replace(" ","").replace(",",""))
                except ValueError:pass
        rows.append({"candidate_id":f"{PREFIX}:{rid}","source":SOURCE,"portal":SOURCE,"resource_id":rid,"notice_id":clean(ca_unique) or rid,"title":clean(title) or text[:300],"buyer":clean(buyer) or None,"country":"CY" if SOURCE=="CYPRUS_EPPS" else ("MT" if SOURCE=="MALTA_EPPS" else None),"deadline":deadline.isoformat() if deadline else None,"current":True,"currentness_evidence":"CYPRUS_OFFICIAL_RECENT_TENDERS_QUICKSEARCH" if SOURCE=="CYPRUS_EPPS" else "EPPS_PUBLIC_REGISTRY","notice_url":detail_url,"description":text,"procurement_method":clean(procedure) or None,"source_status":clean(status) or None,"estimated_value":estimated_value,"currency":"EUR","route":{"resource_id":rid,"base_url":BASE_URL,"detail_url":detail_url,"documents_url":f"{BASE_URL}/epps/cft/listContractDocuments.do?resourceId={rid}"},"discovery_page":page_no,"discovered_at":NOW.isoformat()})
    return rows

def page_url(pg):
    if SOURCE=="CYPRUS_EPPS":
        # The Cyprus Treasury's official Public Procurement portal links its
        # "Recent Tenders" surface to this public quick-search route. It does
        # not bypass the CAPTCHA-gated advanced search; it is an independent,
        # intentionally public recall surface exposed by the authority itself.
        return f"{BASE_URL}/epps/quickSearchAction.do?latest=true&searchSelect=4&T01_ps={PAGE_SIZE}&d-3680175-n=1&d-3680175-o=2&d-3680175-p={pg}&d-3680175-s=deadline"
    if SOURCE=="MALTA_EPPS":
        return f"{BASE_URL}/epps/quickSearchAction.do?T01_ps={PAGE_SIZE}&d-3680175-n=1&d-3680175-o=2&d-3680175-p={pg}&d-3680175-s=deadline&searchSelect=1"
    return f"{BASE_URL}/epps/quickSearchAction.do?T01_ps={PAGE_SIZE}&d-3680175-p={pg}&searchSelect=1"
def main():
    by_id={};errors=[];warnings=[];pages=0;empty_streak=0;captcha_pages=[];exhausted=False
    for pg in range(PAGE_START,PAGE_END+1):
        url=page_url(pg)
        try:
            r=request(url)
            body=r.text
            if CAPTCHA_RE.search(body):
                captcha_pages.append(pg)
                errors.append({"page":pg,"url":r.url,"type":"PUBLIC_SEARCH_CAPTCHA_GATE","message":"Official ePPS response requires CAPTCHA; automation stops rather than bypassing it."})
                break
            records=parse_page(body,r.url,pg);pages+=1;empty_streak=empty_streak+1 if not records else 0
            for rec in records:by_id.setdefault(rec["candidate_id"],rec)
            if empty_streak>=2:
                exhausted=True
                break
        except Exception as exc:errors.append({"page":pg,"url":url,"error":repr(exc)})
    if not errors and not captcha_pages and PAGE_END>=PAGE_START and empty_streak<2:
        warnings.append({"type":"PAGE_WINDOW_ENDED_WITHOUT_EXHAUSTION_PROOF","page_end":PAGE_END})
    if SOURCE=="CYPRUS_EPPS":
        warnings.append({"type":"CYPRUS_RECENT_TENDERS_QUICKSEARCH_RECALL_ONLY","coverage_credit":False,"followup":"PUBLISHED_NOTICES_UNION"})
    rows=sorted(by_id.values(),key=lambda r:(r.get("deadline") or "9999",r["candidate_id"]))
    for name in ("raw.jsonl","current.jsonl"):
        with (OUT/name).open("w",encoding="utf-8") as f:
            for rec in rows:f.write(json.dumps(rec,ensure_ascii=False)+"\n")
    # Cyprus Recent Tenders is a useful official recall surface, but it is not
    # evidence of exhaustive nationwide current-registry coverage. Always leave
    # it incomplete so the workflow unions Published Notices afterward.
    enumeration_complete=bool(exhausted and not errors and rows and SOURCE!="CYPRUS_EPPS")
    contract="CYPRUS_EPPS_OFFICIAL_RECENT_TENDERS_QUICKSEARCH_V4_RECALL" if SOURCE=="CYPRUS_EPPS" else "EPPS_PRODUCTION_REGISTRY_V3_CAPTCHA_AWARE"
    stats={"source":SOURCE,"base_url":BASE_URL,"listing_contract":contract,"page_start":PAGE_START,"page_end_requested":PAGE_END,"pages_fetched":pages,"current_materialized":len(rows),"raw_materialized":len(rows),"deadline_parsed":sum(1 for r in rows if r.get("deadline")),"buyer_parsed":sum(1 for r in rows if r.get("buyer")),"value_parsed":sum(1 for r in rows if r.get("estimated_value") is not None),"captcha_pages":captcha_pages,"enumeration_exhausted":bool(exhausted and SOURCE!="CYPRUS_EPPS"),"enumeration_complete":enumeration_complete,"live_candidate_capable":bool(rows),"live_coverage_credit_allowed":enumeration_complete,"errors":errors,"warnings":warnings,"generated_at":NOW.isoformat(),"semantics":"Never bypass CAPTCHA. Cyprus uses the authority-linked Recent Tenders quick-search only as additive recall and always forces Published Notices union; it never receives exhaustive coverage credit. Other ePPS lanes require two consecutive parse-empty registry pages with no CAPTCHA/error for exhaustion."}
    (OUT/"stats.json").write_text(json.dumps(stats,indent=2,ensure_ascii=False),encoding="utf-8");print(json.dumps(stats,indent=2,ensure_ascii=False))
    if not rows:raise SystemExit(3)
    if errors or not enumeration_complete:raise SystemExit(2)
if __name__=="__main__":main()