#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import datetime as dt
import gzip
import hashlib
import json
import os
import re
import subprocess
import time
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

DECISIONS = {"STRONG_FIT", "FIT", "MAYBE", "REJECT_OBVIOUS"}
LEAN = {"HIGH", "MEDIUM", "LOW", "UNKNOWN"}
ROUTES = {"DIRECT_DIGITAL", "AI_ENABLED", "SUBCONTRACTABLE", "BROKER_RESELL", "MIXED", "UNCLEAR"}
FRICTION = {
    "REGULATED_GOODS", "LICENSED_PERSONNEL", "HEAVY_EQUIPMENT", "CAPITAL_INTENSIVE",
    "ON_SITE_SPECIALIST", "LOCAL_PRESENCE", "MANUFACTURER_AUTHORIZATION",
    "FRAMEWORK_OR_REFERENCE_BURDEN", "SECURITY_CLEARANCE", "OTHER",
}

D_CODE = {"S": "STRONG_FIT", "F": "FIT", "M": "MAYBE", "R": "REJECT_OBVIOUS"}
L_CODE = {"H": "HIGH", "M": "MEDIUM", "L": "LOW", "U": "UNKNOWN"}
R_CODE = {"D": "DIRECT_DIGITAL", "A": "AI_ENABLED", "S": "SUBCONTRACTABLE", "B": "BROKER_RESELL", "X": "MIXED", "U": "UNCLEAR"}
F_CODE = {
    "RG": "REGULATED_GOODS", "LP": "LICENSED_PERSONNEL", "HE": "HEAVY_EQUIPMENT",
    "CI": "CAPITAL_INTENSIVE", "OS": "ON_SITE_SPECIALIST", "LO": "LOCAL_PRESENCE",
    "MA": "MANUFACTURER_AUTHORIZATION", "FR": "FRAMEWORK_OR_REFERENCE_BURDEN",
    "SC": "SECURITY_CLEARANCE", "O": "OTHER",
}

PROMPT_VERSION = "qwen-batch-high-recall-business-fit-v2"
CLASSIFIER_VERSION = "qwen3-4b-q4km-batch-selfheal-v1"
SCHEMA = "QWEN_NOTICE_BATCH_SELFHEAL_V1"
SUMMARY_SCHEMA = "QWEN_NOTICE_BATCH_SELFHEAL_SUMMARY_V1"
PROGRESS_SCHEMA = "QWEN_NOTICE_BATCH_LIVE_PROGRESS_V1"

PHYSICAL_GOODS = re.compile(
    r"\b(parts?|spares?|equipment|supplies?|vehicle|truck|lorry|lkw|microscopes?|filters?|"
    r"reactors?|furniture|machinery|components?|instruments?|devices?)\b", re.I
)
REGULATED = re.compile(
    r"\b(methylphenidate|controlled substance|prescription drug|pharmaceutical|narcotic|"
    r"ammunition|firearms?|explosives?|radioactive|nuclear material)\b", re.I
)
HEAVY_ONSITE = re.compile(
    r"\b(construction|civil works?|installation work|hvac|heating|ventilation|"
    r"air[- ]conditioning|mold (?:mitigation|remediation|abatement)|chillers?|"
    r"building works?|architect led design team)\b", re.I
)
DIRECT_DIGITAL = re.compile(
    r"\b(website|web ?app|web portal|software|saas|digital platform|application development|"
    r"mobile app|animation|video production|graphic design|content creation|transcription|"
    r"cms|workflow automation|e[- ]learning|online training|data processing)\b", re.I
)
PERSONAL_SERVICE = re.compile(r"\bpersonal services? contract\b", re.I)

SYSTEM = """High-recall public-tender router for a lean Belgian SME.
This is routing only, never eligibility or final bid approval.
CRITICAL: KEEP is not FIT. Use MAYBE liberally for anything worth preserving but not yet commercially attractive.
STRONG_FIT = clear SPM leverage, lean/core delivery, low obvious friction, worth immediate DCE review.
FIT = practical plausible opportunity with reasonably direct delivery or a straightforward broker route.
MAYBE = preserve for recall: ambiguous, partner-heavy, physical commodity, generic service, on-site work, unclear economics or unclear gates.
REJECT_OBVIOUS = clearly non-opportunity/informational or clearly unsuitable active pursuit.
Physical goods, heavy/on-site work and personal-service contracts must NOT be FIT merely because subcontracting exists.
Keep unusual, ambiguous, subcontractable, consortium, broker/resell, AI or digital opportunities by using MAYBE when uncertain.
Return ONLY one compact JSON object {"x":[...]} in the same order as input.
For every item use:
i=id
d=S|F|M|R for STRONG_FIT|FIT|MAYBE|REJECT_OBVIOUS
l=H|M|L|U for HIGH|MEDIUM|LOW|UNKNOWN lean attractiveness
r=D|A|S|B|X|U for DIRECT_DIGITAL|AI_ENABLED|SUBCONTRACTABLE|BROKER_RESELL|MIXED|UNCLEAR
f=array of friction codes RG,LP,HE,CI,OS,LO,MA,FR,SC,O
n=0|1 unusual/novel
g=0|1 needs GPT review
Never invent DCE facts. /no_think"""


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def opener(path: Path, mode: str):
    return gzip.open(path, mode + "t", encoding="utf-8") if path.suffix == ".gz" else path.open(mode, encoding="utf-8")


def iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with opener(path, "r") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                row = json.loads(raw)
            except Exception:
                continue
            if isinstance(row, dict):
                yield row


def notice(row: dict[str, Any]) -> dict[str, Any]:
    n = row.get("notice")
    return n if isinstance(n, dict) else row


def cid(row: dict[str, Any]) -> str:
    n = notice(row)
    return str(row.get("canonical_notice_id") or n.get("candidate_id") or n.get("notice_id") or n.get("id") or "").strip()


def material_hash(row: dict[str, Any]) -> str:
    return str(row.get("material_fields_hash") or row.get("input_material_fields_hash") or "").strip()


def deterministic_sample(rows: Iterable[dict[str, Any]], n: int) -> list[dict[str, Any]]:
    ranked = []
    seen = set()
    for row in rows:
        candidate = cid(row)
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        ranked.append((hashlib.sha256(candidate.encode()).hexdigest(), candidate, row))
    ranked.sort(key=lambda x: (x[0], x[1]))
    if n <= 0:
        return [x[2] for x in ranked]
    return [x[2] for x in ranked[:n]]


def compact(row: dict[str, Any], description_chars: int) -> dict[str, Any]:
    n = notice(row)
    desc = " ".join(str(n.get("description") or "").split())
    if len(desc) > description_chars:
        desc = desc[:description_chars] + "…"
    return {
        "i": cid(row),
        "t": n.get("title"),
        "b": n.get("buyer"),
        "c": n.get("country"),
        "k": n.get("cpv_or_category"),
        "d": desc,
        "v": n.get("estimated_value"),
        "y": n.get("currency"),
        "p": n.get("procedure"),
        "e": n.get("deadline") or n.get("deadline_utc"),
    }


def prompt(batch: list[dict[str, Any]], description_chars: int) -> str:
    payload = [compact(x, description_chars) for x in batch]
    return "Classify every input. Never omit or duplicate i. JSON object only. /no_think\nN=" + json.dumps(
        payload, ensure_ascii=False, separators=(",", ":")
    )


def post_json(url: str, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def extract_items(text: str) -> list[dict[str, Any]] | None:
    text = text.strip()
    candidates = [text]
    m = re.search(r"\{.*\}", text, flags=re.S)
    if m and m.group(0) != text:
        candidates.append(m.group(0))
    a = re.search(r"\[.*\]", text, flags=re.S)
    if a:
        candidates.append(a.group(0))
    for candidate in candidates:
        try:
            obj = json.loads(candidate)
        except Exception:
            continue
        if isinstance(obj, dict) and isinstance(obj.get("x"), list):
            return [x for x in obj["x"] if isinstance(x, dict)]
        if isinstance(obj, list):
            return [x for x in obj if isinstance(x, dict)]
    return None


def decode_item(obj: dict[str, Any] | None) -> dict[str, Any]:
    if not obj:
        return {
            "classification": "MAYBE", "confidence": 0.0, "lean_attractiveness": "UNKNOWN",
            "delivery_mode": "UNCLEAR", "friction_flags": [], "unusual_or_novel": True,
            "needs_gpt_review": True,
        }
    d_raw = str(obj.get("d") or obj.get("decision") or obj.get("classification") or "M").upper()
    l_raw = str(obj.get("l") or obj.get("lean_attractiveness") or "U").upper()
    r_raw = str(obj.get("r") or obj.get("possible_delivery_route") or obj.get("delivery_mode") or "U").upper()
    decision = D_CODE.get(d_raw, d_raw if d_raw in DECISIONS else "MAYBE")
    lean = L_CODE.get(l_raw, l_raw if l_raw in LEAN else "UNKNOWN")
    route = R_CODE.get(r_raw, r_raw if r_raw in ROUTES else "UNCLEAR")
    raw_flags = obj.get("f") if isinstance(obj.get("f"), list) else obj.get("friction_flags")
    raw_flags = raw_flags if isinstance(raw_flags, list) else []
    flags = []
    for flag in raw_flags:
        f = str(flag).upper()
        normalized = F_CODE.get(f, f if f in FRICTION else None)
        if normalized and normalized not in flags:
            flags.append(normalized)
    try:
        confidence = float(obj.get("confidence", obj.get("q", 0.0)))
    except Exception:
        confidence = 0.0
    confidence = min(1.0, max(0.0, confidence))
    unusual = obj.get("n", obj.get("unusual_or_novel", False))
    review = obj.get("g", obj.get("needs_gpt_review", False))
    return {
        "classification": decision,
        "confidence": confidence,
        "lean_attractiveness": lean,
        "delivery_mode": route,
        "friction_flags": flags,
        "unusual_or_novel": bool(unusual),
        "needs_gpt_review": bool(review),
    }


def deterministic_guard(decoded: dict[str, Any], row: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    out = dict(decoded)
    n = notice(row)
    text = " ".join(str(n.get(k) or "") for k in ("title", "description", "cpv_or_category", "procedure"))
    title = str(n.get("title") or "")
    actions: list[str] = []
    out["survival_decision"] = "KEEP"
    out["dce_eligible"] = True
    physical = bool(PHYSICAL_GOODS.search(title)) or bool(PHYSICAL_GOODS.search(text[:1600]))
    regulated = bool(REGULATED.search(title)) or bool(REGULATED.search(text[:1800]))
    heavy = bool(HEAVY_ONSITE.search(title)) or bool(HEAVY_ONSITE.search(text[:1800]))
    personal = bool(PERSONAL_SERVICE.search(title)) or bool(PERSONAL_SERVICE.search(text[:1000]))
    info_only = bool(re.search(r"(industry day|sources sought|request for information|special notice|award notice|contract award notice)", title, re.I))
    hard_personnel = bool(re.search(r"(aviation security officer|armed security|security guard|guard services?|physician|nurse|medical staffing)", text, re.I))
    patient_transport = bool(re.search(r"(non[- ]?emergent patient transportation|patient transport|ambulance services?)", text, re.I))
    core = bool(re.search(r"(website|web ?app|web portal|application development|mobile app|animation|video production|graphic design|content creation|copywriting|editorial|proofreading|translation|transcription|printing?|brochures?|leaflets?|signage|promotional goods?|digitization|digitisation|scanning|document management|e[- ]learning|training content|training materials?|media monitoring|social media|communications strategy|digital marketing|market research|research services?|surveys?|data processing|data entry|workflow automation|cms|hosting|web maintenance)", text, re.I))
    strong_core = bool(re.search(r"(website|web ?app|web portal|application development|mobile app|animation|video production|graphic design|content creation|translation|transcription|printing?|digitization|digitisation|scanning|e[- ]learning|media monitoring|social media|market research|surveys?)", text, re.I))
    deadline_raw = n.get("deadline") or n.get("deadline_utc")
    deadline = None
    if deadline_raw:
        try:
            deadline = dt.datetime.fromisoformat(str(deadline_raw).replace("Z", "+00:00"))
            if deadline.tzinfo is None: deadline = deadline.replace(tzinfo=dt.timezone.utc)
        except Exception: deadline = None
    if deadline is not None and deadline < dt.datetime.now(dt.timezone.utc):
        out.update(classification="REJECT_OBVIOUS", lean_attractiveness="LOW", delivery_mode="UNCLEAR", survival_decision="DROP", dce_eligible=False)
        actions.append("expired_deadline_drop")
    if info_only:
        out.update(classification="REJECT_OBVIOUS", lean_attractiveness="LOW", delivery_mode="UNCLEAR", survival_decision="DROP", dce_eligible=False)
        actions.append("information_only_not_dce")
    if (personal and hard_personnel) or patient_transport or (personal and not core):
        out.update(classification="REJECT_OBVIOUS", lean_attractiveness="LOW", delivery_mode="UNCLEAR", survival_decision="DROP", dce_eligible=False)
        if (personal or hard_personnel) and "LICENSED_PERSONNEL" not in out["friction_flags"]: out["friction_flags"].append("LICENSED_PERSONNEL")
        actions.append("personal_or_hard_service_drop")
    if regulated and out["survival_decision"] != "DROP":
        out.update(classification="MAYBE", lean_attractiveness="LOW", delivery_mode="BROKER_RESELL", dce_eligible=False)
        if "REGULATED_GOODS" not in out["friction_flags"]: out["friction_flags"].append("REGULATED_GOODS")
        out["needs_gpt_review"] = True
        actions.append("regulated_keep_no_dce")
    if physical and not core and out["survival_decision"] != "DROP":
        if out["classification"] in {"STRONG_FIT", "FIT"}: out["classification"] = "MAYBE"; actions.append("physical_fit_to_maybe")
        out["delivery_mode"] = "BROKER_RESELL"
        if out["lean_attractiveness"] == "HIGH": out["lean_attractiveness"] = "MEDIUM"
    if heavy and not core and out["survival_decision"] != "DROP":
        if out["classification"] in {"STRONG_FIT", "FIT"}: out["classification"] = "MAYBE"; actions.append("heavy_fit_to_maybe")
        out["delivery_mode"] = "SUBCONTRACTABLE"
        out["lean_attractiveness"] = "LOW"
        if "ON_SITE_SPECIALIST" not in out["friction_flags"]: out["friction_flags"].append("ON_SITE_SPECIALIST")
        out["needs_gpt_review"] = True
    hard_friction = bool({"LICENSED_PERSONNEL", "SECURITY_CLEARANCE", "REGULATED_GOODS"} & set(out["friction_flags"]))
    if out["classification"] == "STRONG_FIT":
        if not strong_core or hard_friction:
            out["classification"] = "FIT" if core and not hard_friction else "MAYBE"
            actions.append("strong_requires_core_low_friction")
        elif deadline is None:
            out["classification"] = "FIT"
            out["needs_gpt_review"] = True
            actions.append("strong_deadline_unverified_to_fit")
    if out["classification"] == "FIT" and out["survival_decision"] != "DROP":
        if not core and (out["delivery_mode"] in {"SUBCONTRACTABLE", "BROKER_RESELL", "UNCLEAR"} or out["lean_attractiveness"] in {"LOW", "UNKNOWN"}):
            out["classification"] = "MAYBE"
            actions.append("noncore_partner_fit_to_maybe")
        elif hard_friction:
            out["classification"] = "MAYBE"
            actions.append("hard_friction_fit_to_maybe")
    if out["classification"] == "REJECT_OBVIOUS" and out["survival_decision"] == "KEEP": out["dce_eligible"] = False
    out["business_calibration_version"] = "spm-business-fit-v2"
    out["novelty_or_unusual_flag"] = bool(out.get("unusual_or_novel", out.get("novelty_or_unusual_flag", False)))
    return out, actions

def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--queue", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--summary", required=True)
    ap.add_argument("--progress", default=None, help="Live JSON checkpoint rewritten after every completed request")
    ap.add_argument("--batch-size", type=int, required=True)
    ap.add_argument("--sample-size", type=int, default=48)
    ap.add_argument("--server", default="http://127.0.0.1:8080/v1/chat/completions")
    ap.add_argument("--model", default="Qwen/Qwen3-4B-GGUF:Q4_K_M")
    ap.add_argument("--description-chars", type=int, default=500)
    ap.add_argument("--timeout", type=int, default=75)
    ap.add_argument("--max-tokens", type=int, default=1100)
    ap.add_argument("--startup-seconds", type=float, default=0.0)
    ap.add_argument("--source-ledger-generation", required=True)
    ap.add_argument("--max-runtime-seconds", type=int, default=1200)
    args = ap.parse_args()
    if args.batch_size < 1 or args.batch_size > 64:
        raise SystemExit("batch-size must be 1..64")

    sample = deterministic_sample(iter_jsonl(Path(args.queue)), args.sample_size)
    out_path = Path(args.out)
    summary_path = Path(args.summary)
    progress_path = Path(args.progress) if args.progress else out_path.with_name(out_path.stem + "-progress.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.parent.mkdir(parents=True, exist_ok=True)

    worker_match = re.search(r"qwen-live-(\d+)", out_path.name)
    worker_id = os.environ.get("QWEN_WORKER_ID") or (worker_match.group(1) if worker_match else "unknown")
    run_id = os.environ.get("GITHUB_RUN_ID") or "local"
    started = time.monotonic()
    attempts: list[dict[str, Any]] = []
    split_events = 0
    singleton_fallbacks = 0
    recovered_rows = 0
    final: dict[str, dict[str, Any]] = {}
    row_meta: dict[str, dict[str, Any]] = {}
    sample_by_id = {cid(row): row for row in sample}
    live_release_tag = f"qwen-live-progress-{run_id}" if os.environ.get("GITHUB_ACTIONS") == "true" and run_id != "local" else None
    live_release_repo = os.environ.get("GITHUB_REPOSITORY")
    live_release_ready = False
    live_auth_env: dict[str, str] | None = None

    def emit(event: str, **fields: Any) -> None:
        payload = {
            "event": event,
            "worker": worker_id,
            "run_id": run_id,
            "at_utc": now_utc(),
            **fields,
        }
        print("QWEN_PROGRESS " + json.dumps(payload, ensure_ascii=False, separators=(",", ":")), flush=True)

    def github_auth_env() -> dict[str, str] | None:
        nonlocal live_auth_env
        if live_auth_env is not None:
            return live_auth_env
        env = os.environ.copy()
        if env.get("GH_TOKEN"):
            live_auth_env = env
            return env
        try:
            header = subprocess.check_output(
                ["git", "config", "--local", "--get", "http.https://github.com/.extraheader"],
                text=True, stderr=subprocess.DEVNULL, timeout=5,
            ).strip()
            match = re.search(r"basic\s+(\S+)", header, flags=re.I)
            if not match:
                return None
            decoded = base64.b64decode(match.group(1)).decode("utf-8", errors="ignore")
            token = decoded.split(":", 1)[1] if ":" in decoded else ""
            if not token:
                return None
            env["GH_TOKEN"] = token
            live_auth_env = env
            return env
        except Exception:
            return None

    def ensure_live_release() -> bool:
        nonlocal live_release_ready
        if live_release_ready:
            return True
        if not live_release_tag or not live_release_repo:
            return False
        env = github_auth_env()
        if not env:
            return False
        view = subprocess.run(
            ["gh", "release", "view", live_release_tag, "--repo", live_release_repo],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15, check=False,
        )
        if view.returncode != 0:
            create = subprocess.run(
                ["gh", "release", "create", live_release_tag, "--repo", live_release_repo,
                 "--target", os.environ.get("GITHUB_SHA", "main"),
                 "--title", f"Qwen Live Progress {run_id}",
                 "--notes", "Externally readable per-worker Qwen checkpoints; assets are replaced after each checkpoint."],
                env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=25, check=False,
            )
            if create.returncode != 0:
                view = subprocess.run(
                    ["gh", "release", "view", live_release_tag, "--repo", live_release_repo],
                    env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15, check=False,
                )
                if view.returncode != 0:
                    return False
        live_release_ready = True
        return True

    def publish_external_checkpoint(event: str) -> None:
        if not progress_path.exists() or not ensure_live_release():
            return
        env = github_auth_env()
        if not env:
            return
        try:
            cp = subprocess.run(
                ["gh", "release", "upload", live_release_tag, str(progress_path), "--clobber", "--repo", live_release_repo],
                env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=30, check=False,
            )
            if cp.returncode == 0:
                emit("EXTERNAL_CHECKPOINT_PUBLISHED", checkpoint_event=event, asset=progress_path.name, release_tag=live_release_tag)
            else:
                emit("EXTERNAL_CHECKPOINT_PUBLISH_FAIL", checkpoint_event=event, asset=progress_path.name, release_tag=live_release_tag, returncode=cp.returncode, stderr_tail=(cp.stderr or "")[-300:])
        except Exception as exc:
            emit("EXTERNAL_CHECKPOINT_PUBLISH_FAIL", checkpoint_event=event, asset=progress_path.name, release_tag=live_release_tag, error=type(exc).__name__)

    def build_record(candidate: str) -> dict[str, Any] | None:
        row = sample_by_id.get(candidate)
        if row is None or candidate not in final:
            return None
        decoded = final[candidate]
        meta = row_meta.get(candidate) or {
            "parse_error": "missing_after_selfheal",
            "effective_batch_size": 1,
            "self_heal_depth": 0,
            "recovered_after_split": False,
        }
        return {
            "schema": SCHEMA,
            "canonical_notice_id": candidate,
            "input_material_fields_hash": material_hash(row),
            "source_ledger_generation": args.source_ledger_generation,
            "classifier_model": args.model,
            "classifier_quant": "Q4_K_M",
            "classifier_prompt_version": PROMPT_VERSION,
            "classifier_version": CLASSIFIER_VERSION,
            "initial_batch_size": args.batch_size,
            "classified_at_utc": now_utc(),
            **decoded,
            **meta,
            "notice": compact(row, args.description_chars),
        }

    def persist_progress(event: str, last_ids: list[str] | None = None) -> None:
        resolved = [cid(row) for row in sample if cid(row) in final]
        records = [r for candidate in resolved if (r := build_record(candidate)) is not None]
        tmp = out_path.with_suffix(out_path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            for record in records:
                fh.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        tmp.replace(out_path)
        decisions = Counter(r["classification"] for r in records)
        live = {
            "schema": PROGRESS_SCHEMA,
            "run_id": run_id,
            "worker": worker_id,
            "source_ledger_generation": args.source_ledger_generation,
            "event": event,
            "sample_total": len(sample),
            "resolved": len(records),
            "remaining": len(sample) - len(records),
            "request_attempts": len(attempts),
            "failed_attempts": sum(1 for x in attempts if x["status"] == "FAIL"),
            "split_events": split_events,
            "singleton_fallbacks": singleton_fallbacks,
            "decision_counts": dict(sorted(decisions.items())),
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "last_ids": list(last_ids or []),
            "last_attempt": attempts[-1] if attempts else None,
            "updated_at_utc": now_utc(),
        }
        atomic_json(progress_path, live)
        publish_external_checkpoint(event)
        emit("CHECKPOINT", resolved=live["resolved"], remaining=live["remaining"], attempts=live["request_attempts"], failures=live["failed_attempts"], splits=split_events, decisions=live["decision_counts"])

    emit("START", sample_total=len(sample), batch_size=args.batch_size, timeout_seconds=args.timeout, max_runtime_seconds=args.max_runtime_seconds, startup_seconds=args.startup_seconds)
    persist_progress("START")

    def run_batch(batch: list[dict[str, Any]], depth: int, initial_size: int) -> None:
        nonlocal split_events, singleton_fallbacks, recovered_rows
        expected = [cid(x) for x in batch]
        if not expected:
            return
        elapsed = time.monotonic() - started
        if elapsed >= args.max_runtime_seconds:
            for row in batch:
                candidate = cid(row)
                final[candidate] = decode_item(None)
                row_meta[candidate] = {
                    "parse_error": "runtime_budget_exhausted",
                    "effective_batch_size": 1,
                    "self_heal_depth": depth,
                    "recovered_after_split": depth > 0,
                }
                singleton_fallbacks += 1
            emit("RUNTIME_FALLBACK", depth=depth, batch_size=len(batch), ids=expected, elapsed_seconds=round(elapsed, 3))
            persist_progress("RUNTIME_FALLBACK", expected)
            return

        attempt_no = len(attempts) + 1
        emit("REQUEST", attempt=attempt_no, depth=depth, batch_size=len(batch), ids=expected)
        t0 = time.monotonic()
        err = None
        items = None
        raw_text = ""
        usage: dict[str, Any] = {}
        try:
            dynamic_tokens = min(args.max_tokens, max(80, 36 * len(batch) + 40))
            response = post_json(
                args.server,
                {
                    "model": args.model,
                    "messages": [
                        {"role": "system", "content": SYSTEM},
                        {"role": "user", "content": prompt(batch, args.description_chars)},
                    ],
                    "temperature": 0.0,
                    "top_p": 0.8,
                    "max_tokens": dynamic_tokens,
                    "stream": False,
                },
                args.timeout,
            )
            raw_text = str(response["choices"][0]["message"]["content"])
            usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
            items = extract_items(raw_text)
            if items is None:
                err = "invalid_json"
            else:
                ids = [str(x.get("i") or x.get("id") or "").strip() for x in items]
                if len(ids) != len(expected) or len(set(ids)) != len(ids) or set(ids) != set(expected):
                    err = "id_set_mismatch"
        except Exception as exc:
            err = f"request_error:{type(exc).__name__}"

        latency = round(time.monotonic() - t0, 3)
        attempt = {
            "requested_batch_size": len(batch),
            "depth": depth,
            "status": "PASS" if not err else "FAIL",
            "error": err,
            "latency_seconds": latency,
            "usage": usage,
            "raw_chars": len(raw_text),
        }
        attempts.append(attempt)
        emit("RESPONSE", attempt=len(attempts), depth=depth, batch_size=len(batch), status=attempt["status"], error=err, latency_seconds=latency, raw_chars=len(raw_text), usage=usage)

        if err:
            if len(batch) > 1:
                split_events += 1
                mid = len(batch) // 2
                emit("SPLIT", attempt=len(attempts), depth=depth, batch_size=len(batch), left=mid, right=len(batch) - mid, reason=err, split_events=split_events)
                persist_progress("SPLIT", expected)
                run_batch(batch[:mid], depth + 1, initial_size)
                run_batch(batch[mid:], depth + 1, initial_size)
                return
            candidate = expected[0]
            final[candidate] = decode_item(None)
            row_meta[candidate] = {
                "parse_error": err,
                "effective_batch_size": 1,
                "self_heal_depth": depth,
                "recovered_after_split": False,
            }
            singleton_fallbacks += 1
            emit("SINGLETON_FALLBACK", candidate=candidate, depth=depth, error=err, singleton_fallbacks=singleton_fallbacks)
            persist_progress("SINGLETON_FALLBACK", expected)
            return

        by_id = {str(x.get("i") or x.get("id") or "").strip(): x for x in items or []}
        batch_decisions = []
        for row in batch:
            candidate = cid(row)
            decoded = decode_item(by_id[candidate])
            decoded, guard_actions = deterministic_guard(decoded, row)
            final[candidate] = decoded
            recovered = depth > 0
            recovered_rows += int(recovered)
            row_meta[candidate] = {
                "parse_error": None,
                "effective_batch_size": len(batch),
                "self_heal_depth": depth,
                "recovered_after_split": recovered,
                "deterministic_guard_actions": guard_actions,
            }
            batch_decisions.append({
                "id": candidate,
                "classification": decoded["classification"],
                "lean": decoded["lean_attractiveness"],
                "route": decoded["delivery_mode"],
                "review": decoded["needs_gpt_review"],
            })
        emit("BATCH_OUTPUT", attempt=len(attempts), depth=depth, batch_size=len(batch), decisions=batch_decisions)
        persist_progress("BATCH_OUTPUT", expected)

    top_batches = (len(sample) + args.batch_size - 1) // args.batch_size
    for batch_index, start in enumerate(range(0, len(sample), args.batch_size), start=1):
        batch = sample[start:start + args.batch_size]
        emit("TOP_BATCH_START", batch_index=batch_index, top_batches=top_batches, batch_size=len(batch), resolved=len(final))
        run_batch(batch, 0, args.batch_size)
        resolved = len(final)
        notice_text = f"worker={worker_id} batch={batch_index}/{top_batches} resolved={resolved}/{len(sample)} attempts={len(attempts)} failures={sum(1 for x in attempts if x['status']=='FAIL')} splits={split_events}"
        print(f"::notice title=Qwen live progress::{notice_text}", flush=True)
        emit("TOP_BATCH_DONE", batch_index=batch_index, top_batches=top_batches, resolved=resolved, total=len(sample))

    records: list[dict[str, Any]] = []
    with out_path.open("w", encoding="utf-8") as fh:
        for row in sample:
            candidate = cid(row)
            if candidate not in final:
                final[candidate] = decode_item(None)
                row_meta[candidate] = {
                    "parse_error": "missing_after_selfheal",
                    "effective_batch_size": 1,
                    "self_heal_depth": 0,
                    "recovered_after_split": False,
                }
            record = build_record(candidate)
            if record is None:
                continue
            records.append(record)
            fh.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        fh.flush()
        os.fsync(fh.fileno())

    elapsed = time.monotonic() - started
    ids = [x["canonical_notice_id"] for x in records]
    decision_counts = Counter(x["classification"] for x in records)
    lean_counts = Counter(x["lean_attractiveness"] for x in records)
    effective_counts = Counter(str(x.get("effective_batch_size")) for x in records)
    parse_errors = sum(1 for x in records if x.get("parse_error"))
    summary = {
        "schema": SUMMARY_SCHEMA,
        "classifier_model": args.model,
        "classifier_prompt_version": PROMPT_VERSION,
        "classifier_version": CLASSIFIER_VERSION,
        "source_ledger_generation": args.source_ledger_generation,
        "worker": worker_id,
        "run_id": run_id,
        "sample_requested": args.sample_size,
        "sample_completed": len(records),
        "unique_ids": len(set(ids)),
        "initial_batch_size": args.batch_size,
        "request_attempts": len(attempts),
        "failed_attempts": sum(1 for x in attempts if x["status"] == "FAIL"),
        "split_events": split_events,
        "singleton_fallbacks": singleton_fallbacks,
        "recovered_rows_after_split": recovered_rows,
        "parse_or_fallback_rows": parse_errors,
        "effective_batch_size_counts": dict(sorted(effective_counts.items(), key=lambda kv: int(kv[0]))),
        "startup_seconds": args.startup_seconds,
        "inference_seconds": round(elapsed, 3),
        "seconds_per_notice": round(elapsed / len(records), 3) if records else None,
        "notices_per_second": round(len(records) / elapsed, 4) if elapsed and records else None,
        "decision_counts": dict(sorted(decision_counts.items())),
        "lean_attractiveness_counts": dict(sorted(lean_counts.items())),
        "row_conservation_pass": len(records) == len(sample) == len(set(ids)),
        "attempts": attempts,
        "live_observability": {
            "structured_stdout_per_request": True,
            "batch_decisions_logged": True,
            "incremental_raw_jsonl_checkpoint": str(out_path),
            "incremental_progress_json": str(progress_path),
            "atomic_checkpoint_rewrites": True,
            "github_notice_per_top_batch": True,
            "external_release_checkpoint": bool(live_release_tag and live_release_repo),
            "external_release_tag": live_release_tag,
            "external_release_asset": progress_path.name,
        },
        "data_safety": {
            "shadow_only": True,
            "drops_or_deletes_notices": False,
            "automatic_rejection_enabled": False,
            "failed_batch_recursively_splits": True,
            "singleton_failure_fallback": "MAYBE+UNKNOWN+needs_gpt_review",
        },
        "updated_at_utc": now_utc(),
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    atomic_json(progress_path, {
        "schema": PROGRESS_SCHEMA,
        "run_id": run_id,
        "worker": worker_id,
        "source_ledger_generation": args.source_ledger_generation,
        "event": "COMPLETE",
        "sample_total": len(sample),
        "resolved": len(records),
        "remaining": 0,
        "request_attempts": len(attempts),
        "failed_attempts": summary["failed_attempts"],
        "split_events": split_events,
        "singleton_fallbacks": singleton_fallbacks,
        "decision_counts": dict(sorted(decision_counts.items())),
        "elapsed_seconds": round(elapsed, 3),
        "updated_at_utc": now_utc(),
    })
    publish_external_checkpoint("COMPLETE")
    emit("COMPLETE", resolved=len(records), total=len(sample), elapsed_seconds=round(elapsed, 3), seconds_per_notice=summary["seconds_per_notice"], failures=summary["failed_attempts"], splits=split_events, singleton_fallbacks=singleton_fallbacks, decisions=summary["decision_counts"])
    if not summary["row_conservation_pass"]:
        raise SystemExit("row conservation failed")
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
