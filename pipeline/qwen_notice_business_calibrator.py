#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

CALIBRATION_VERSION = "spm-business-fit-v2"
CLASSIFIER_VERSION = "qwen3-4b-q4km-business-calibrated-v2"

CORE_LEAN = re.compile(
    r"\b(website|web ?app|web portal|application development|mobile app|animation|video production|"
    r"graphic design|content creation|copywriting|editorial|proofreading|translation|transcription|"
    r"printing?|brochures?|leaflets?|signage|promotional goods?|digitization|digitisation|scanning|"
    r"document management|e[- ]learning|training content|training materials?|media monitoring|"
    r"social media|communications strategy|digital marketing|market research|research services?|"
    r"surveys?|data processing|data entry|workflow automation|cms|hosting|web maintenance)\b", re.I
)
STRONG_CORE = re.compile(
    r"\b(website|web ?app|web portal|application development|mobile app|animation|video production|"
    r"graphic design|content creation|translation|transcription|printing?|digitization|digitisation|"
    r"scanning|e[- ]learning|media monitoring|social media|market research|surveys?)\b", re.I
)
PHYSICAL = re.compile(
    r"\b(parts?|spares?|equipment|supplies?|vehicle|truck|lorry|furniture|machinery|components?|"
    r"instruments?|devices?|valves?|generators?|blankets?|lighting|seating)\b", re.I
)
HEAVY = re.compile(
    r"\b(construction|civil works?|renovation|repair works?|building works?|roof|roads?|chiller|hvac|"
    r"heating|ventilation|air[- ]conditioning|mold (?:mitigation|remediation|abatement)|installation work)\b", re.I
)
REGULATED = re.compile(
    r"\b(controlled substance|prescription drug|pharmaceutical|narcotic|ammunition|firearms?|explosives?|"
    r"radioactive|nuclear material)\b", re.I
)
PERSONAL = re.compile(r"\bpersonal services? contract\b", re.I)
HARD_PERSONNEL = re.compile(
    r"\b(aviation security officer|armed security|security guard|guard services?|physician|nurse|medical staffing)\b", re.I
)
PATIENT_TRANSPORT = re.compile(r"\b(non[- ]?emergent patient transportation|patient transport|ambulance services?)\b", re.I)
INFO_ONLY = re.compile(
    r"\b(industry day|sources sought|request for information|special notice|award notice|contract award notice)\b", re.I
)


def notice_text(row: dict[str, Any]) -> tuple[dict[str, Any], str, str]:
    n = row.get("notice") if isinstance(row.get("notice"), dict) else {}
    title = str(n.get("title") or n.get("t") or "")
    desc = str(n.get("description") or n.get("d") or "")
    return n, title, f"{title} {desc}"


def parse_deadline(value: Any) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)
    except Exception:
        return None


def cap_lean(value: str, cap: str) -> str:
    order = {"UNKNOWN": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3}
    value = value if value in order else "UNKNOWN"
    return value if order[value] <= order[cap] else cap


def calibrate(row: dict[str, Any], now: dt.datetime) -> dict[str, Any]:
    out = dict(row)
    n, title, text = notice_text(row)
    before = {
        "classification": str(out.get("classification") or "MAYBE").upper(),
        "lean": str(out.get("lean_attractiveness") or "UNKNOWN").upper(),
        "route": str(out.get("delivery_mode") or "UNCLEAR").upper(),
    }
    classification = before["classification"]
    lean = before["lean"]
    route = before["route"]
    flags = list(out.get("friction_flags") or []) if isinstance(out.get("friction_flags"), list) else []
    actions: list[str] = []
    survival = "KEEP"
    dce_eligible = True

    core = bool(CORE_LEAN.search(text))
    strong_core = bool(STRONG_CORE.search(text))
    physical = bool(PHYSICAL.search(text))
    heavy = bool(HEAVY.search(text))
    regulated = bool(REGULATED.search(text)) or "REGULATED_GOODS" in flags
    personal = bool(PERSONAL.search(text))
    hard_personnel = bool(HARD_PERSONNEL.search(text))
    patient_transport = bool(PATIENT_TRANSPORT.search(text))
    info_only = bool(INFO_ONLY.search(title))

    deadline_raw = n.get("deadline") or n.get("deadline_utc") or n.get("e")
    deadline = parse_deadline(deadline_raw)
    if deadline is not None and deadline < now:
        classification = "REJECT_OBVIOUS"
        lean = "LOW"
        survival = "DROP"
        dce_eligible = False
        actions.append("expired_deadline_drop")

    if info_only:
        classification = "REJECT_OBVIOUS"
        lean = "LOW"
        survival = "DROP"
        dce_eligible = False
        route = "UNCLEAR"
        actions.append("information_only_not_dce")

    if (personal and hard_personnel) or patient_transport:
        classification = "REJECT_OBVIOUS"
        lean = "LOW"
        survival = "DROP"
        dce_eligible = False
        route = "UNCLEAR"
        if "LICENSED_PERSONNEL" not in flags and (personal or hard_personnel):
            flags.append("LICENSED_PERSONNEL")
        actions.append("hard_personnel_or_patient_transport_drop")
    elif personal and not core:
        classification = "REJECT_OBVIOUS"
        lean = "LOW"
        survival = "DROP"
        dce_eligible = False
        actions.append("personal_service_noncore_drop")

    if regulated and survival != "DROP":
        classification = "MAYBE"
        lean = "LOW"
        route = "BROKER_RESELL"
        dce_eligible = False
        if "REGULATED_GOODS" not in flags:
            flags.append("REGULATED_GOODS")
        actions.append("regulated_keep_but_no_dce")

    if physical and not core and survival != "DROP":
        if classification in {"STRONG_FIT", "FIT"}:
            classification = "MAYBE"
            actions.append("physical_fit_to_maybe")
        route = "BROKER_RESELL"
        lean = cap_lean(lean, "MEDIUM")
        actions.append("physical_broker_route")

    if heavy and not core and survival != "DROP":
        if classification in {"STRONG_FIT", "FIT"}:
            classification = "MAYBE"
            actions.append("heavy_fit_to_maybe")
        route = "SUBCONTRACTABLE"
        lean = cap_lean(lean, "LOW")
        if "ON_SITE_SPECIALIST" not in flags:
            flags.append("ON_SITE_SPECIALIST")
        actions.append("heavy_subcontract_low")

    hard_friction = bool({"LICENSED_PERSONNEL", "SECURITY_CLEARANCE", "REGULATED_GOODS"} & set(flags))
    if classification == "STRONG_FIT":
        if not strong_core or hard_friction:
            classification = "FIT" if core and not hard_friction else "MAYBE"
            actions.append("strong_requires_core_and_low_hard_friction")
        elif deadline is None:
            classification = "FIT"
            out["needs_gpt_review"] = True
            actions.append("strong_deadline_unverified_to_fit")

    if classification == "FIT" and survival != "DROP":
        if not core and (route in {"SUBCONTRACTABLE", "BROKER_RESELL", "UNCLEAR"} or lean in {"LOW", "UNKNOWN"}):
            classification = "MAYBE"
            actions.append("noncore_partner_fit_to_maybe")
        elif hard_friction:
            classification = "MAYBE"
            actions.append("hard_friction_fit_to_maybe")

    if classification == "REJECT_OBVIOUS" and survival == "KEEP":
        dce_eligible = False

    out["pre_calibration_classification"] = before["classification"]
    out["pre_calibration_lean_attractiveness"] = before["lean"]
    out["pre_calibration_delivery_mode"] = before["route"]
    out["classification"] = classification
    out["lean_attractiveness"] = lean
    out["delivery_mode"] = route
    out["friction_flags"] = flags
    out["survival_decision"] = survival
    out["dce_eligible"] = bool(dce_eligible)
    out["business_calibration_version"] = CALIBRATION_VERSION
    out["classifier_version"] = CLASSIFIER_VERSION
    out["novelty_or_unusual_flag"] = bool(out.get("novelty_or_unusual_flag", out.get("unusual_or_novel", False)))
    out["business_calibration_actions"] = actions
    out["business_calibration_applied"] = bool(actions or before["classification"] != classification)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Separate notice survival from SPM business attractiveness and DCE eligibility.")
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--summary", required=True)
    args = ap.parse_args()
    now = dt.datetime.now(dt.timezone.utc)
    rows: list[dict[str, Any]] = []
    with open(args.input, encoding="utf-8") as fh:
        for raw in fh:
            raw = raw.strip()
            if raw:
                rows.append(calibrate(json.loads(raw), now))
    Path(args.output).write_text("".join(json.dumps(x, ensure_ascii=False, separators=(",", ":")) + "\n" for x in rows), encoding="utf-8")
    summary = {
        "schema": "QWEN_SPM_BUSINESS_CALIBRATION_SUMMARY_V2",
        "calibration_version": CALIBRATION_VERSION,
        "classifier_version": CLASSIFIER_VERSION,
        "rows": len(rows),
        "classification_counts": dict(Counter(str(x.get("classification") or "UNKNOWN") for x in rows)),
        "survival_counts": dict(Counter(str(x.get("survival_decision") or "UNKNOWN") for x in rows)),
        "dce_eligible_counts": dict(Counter(str(bool(x.get("dce_eligible"))) for x in rows)),
        "rows_changed": sum(1 for x in rows if x.get("business_calibration_applied")),
        "policy": {
            "ledger_rows_deleted": False,
            "keep_is_not_fit": True,
            "drop_means_no_active_dce_not_data_deletion": True,
            "physical_and_heavy_default_to_maybe_not_fit": True,
            "strong_requires_core_low_friction_and_verified_deadline": True,
        },
    }
    Path(args.summary).write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
