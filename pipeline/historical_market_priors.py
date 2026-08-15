from __future__ import annotations

"""Historical Market Brain priors for LIVE tender retrieval ranking.

This layer is deliberately weak and pre-DCE only. Historical evidence may help
choose which live notices deserve scarce DCE retrieval compute, but it can never
satisfy an eligibility gate, alter evidence_quality, or create a final GREEN.

Supported compact JSON contract::

  {
    "contract": "TENDER_MARKET_BRAIN_PRIORS_V1",
    "status": "READY",
    "country_cpv": {"FRA|72": {"sample_size": 123, "priority_bonus": 4}},
    "buyers": {"fra|buyer": {"sample_size": 19, "priority_bonus": 3}},
    "lane_rules": [
      {
        "lane": "Website / CMS build or redesign",
        "country": "GERMANY",
        "sample_size": 230,
        "priority_bonus": 5,
        "patterns": ["website", "webseite"],
        "negative_patterns": ["hardware"]
      }
    ]
  }

Lane rules are allowed only when the JSON has already passed upstream semantic QA.
The live engine does not infer or promote historical lanes by itself.
"""

import json
import re
from pathlib import Path
from typing import Any

CONTRACT = "TENDER_MARKET_BRAIN_PRIORS_V1"
MAX_COUNTRY_CPV_BONUS = 8
MAX_BUYER_BONUS = 6
MAX_LANE_BONUS = 6
MAX_TOTAL_BONUS = 12
MIN_SAMPLE = 8


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def _country(rec: dict) -> str:
    for key in ("country", "country_code", "buyer_country"):
        value = str(rec.get(key) or "").strip().upper()
        if value:
            return value
    return ""


def _cpv(rec: dict) -> str:
    raw = rec.get("cpv") or rec.get("cpv_code") or rec.get("main_cpv") or ""
    if isinstance(raw, list):
        raw = raw[0] if raw else ""
    digits = re.sub(r"\D", "", str(raw))
    return digits[:2] if len(digits) >= 2 else ""


def _buyer(rec: dict) -> str:
    return _norm(rec.get("buyer") or rec.get("buyer_name") or rec.get("authority"))


def _search_text(rec: dict) -> str:
    vals = []
    for key in (
        "title", "name", "description", "scope", "scope_summary", "summary",
        "cpv_description", "category", "subcategory",
    ):
        value = rec.get(key)
        if isinstance(value, list):
            vals.extend(str(x) for x in value if x is not None)
        elif value is not None:
            vals.append(str(value))
    return _norm(" ".join(vals))


def load(path: str | Path = "control/historical_market_priors.json") -> dict:
    p = Path(path)
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, dict) or data.get("contract") != CONTRACT or data.get("status") != "READY":
        return {}
    return data


def _lane_adjustment(rec: dict, priors: dict) -> tuple[int, list[str]]:
    text = _search_text(rec)
    country = _country(rec)
    if not text:
        return 0, []
    best = 0
    reason = ""
    for rule in priors.get("lane_rules") or []:
        if not isinstance(rule, dict):
            continue
        n = int(rule.get("sample_size") or 0)
        if n < MIN_SAMPLE:
            continue
        decision = str(rule.get("decision") or "PROMOTE_CORE").upper()
        if decision not in {"PROMOTE_CORE", "PROMOTE_BROKER"}:
            continue
        rcountry = str(rule.get("country") or "").strip().upper()
        if rcountry and country and rcountry not in {country, country.replace(" ", "_"), country.replace("_", " ")}:
            # Accept a few canonical synonyms without allowing arbitrary fuzzy matching.
            aliases = {
                "FRANCE": {"FRA", "FR", "FRANCE"},
                "GERMANY": {"DEU", "DE", "GERMANY"},
                "UNITED KINGDOM": {"GBR", "GB", "UK", "UNITED KINGDOM"},
                "IRELAND": {"IRL", "IE", "IRELAND"},
                "CANADA": {"CAN", "CA", "CANADA", "CANADA - QUEBEC"},
                "CANADA - QUEBEC": {"CANADA - QUEBEC", "QUEBEC", "QC"},
            }
            allowed = aliases.get(rcountry, {rcountry})
            if country not in allowed:
                continue
        pats = [str(x) for x in (rule.get("patterns") or []) if str(x).strip()]
        negs = [str(x) for x in (rule.get("negative_patterns") or []) if str(x).strip()]
        if not pats:
            continue
        try:
            if not any(re.search(p, text, re.I) for p in pats):
                continue
            if any(re.search(p, text, re.I) for p in negs):
                continue
        except re.error:
            continue
        raw = int(round(float(rule.get("priority_bonus") or 0)))
        bonus = max(-MAX_LANE_BONUS, min(MAX_LANE_BONUS, raw))
        # Never stack multiple overlapping lane rules on one notice; use the strongest.
        if abs(bonus) > abs(best):
            best = bonus
            reason = f"{bonus:+d}:historical-lane:{rule.get('lane','UNKNOWN')}(n={n})"
    return best, ([reason] if reason else [])


def adjustment(rec: dict, priors: dict | None) -> tuple[int, list[str]]:
    if not priors:
        return 0, []
    delta = 0
    reasons: list[str] = []
    country = _country(rec)
    cpv = _cpv(rec)

    if country and cpv:
        row = ((priors.get("country_cpv") or {}).get(f"{country}|{cpv}") or {})
        n = int(row.get("sample_size") or 0)
        if n >= MIN_SAMPLE:
            raw = int(round(float(row.get("priority_bonus") or 0)))
            bonus = max(-MAX_COUNTRY_CPV_BONUS, min(MAX_COUNTRY_CPV_BONUS, raw))
            delta += bonus
            if bonus:
                reasons.append(f"{bonus:+d}:historical-country-cpv(n={n})")

    buyer = _buyer(rec)
    if country and buyer:
        row = ((priors.get("buyers") or {}).get(f"{country.casefold()}|{buyer}") or {})
        n = int(row.get("sample_size") or 0)
        if n >= MIN_SAMPLE:
            raw = int(round(float(row.get("priority_bonus") or 0)))
            bonus = max(-MAX_BUYER_BONUS, min(MAX_BUYER_BONUS, raw))
            delta += bonus
            if bonus:
                reasons.append(f"{bonus:+d}:historical-buyer(n={n})")

    lane_bonus, lane_reasons = _lane_adjustment(rec, priors)
    delta += lane_bonus
    reasons.extend(lane_reasons)

    return max(-MAX_TOTAL_BONUS, min(MAX_TOTAL_BONUS, delta)), reasons
