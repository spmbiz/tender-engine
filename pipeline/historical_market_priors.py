from __future__ import annotations

"""Historical Market Brain priors for LIVE tender retrieval ranking.

This layer is deliberately weak and pre-DCE only. Historical evidence may help
choose which live notices deserve scarce DCE retrieval compute, but it can never
satisfy an eligibility gate, alter evidence_quality, or create a final GREEN.

Country-scoped rules are fail-closed: when a country cannot be resolved, they do
not fire. A small set of deterministic candidate/source prefixes may be used to
recover country; no fuzzy geography inference is performed.
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

    # Deterministic recovery only. This prevents country-scoped historical priors
    # from leaking onto records whose discovery payload omitted a country field.
    cid = str(
        rec.get("candidate_id") or rec.get("id") or rec.get("notice_id") or
        rec.get("tender_id") or rec.get("ocid") or ""
    ).strip().upper()
    prefix_map = (
        ("US-SAM:", "USA"),
        ("IE:", "IRELAND"),
        ("FR:", "FRANCE"),
        ("DE:", "GERMANY"),
        ("UK:", "UNITED KINGDOM"),
        ("CF:", "UNITED KINGDOM"),
        ("CA:", "CANADA"),
        ("QC:", "CANADA - QUEBEC"),
        ("AU:", "AUSTRALIA"),
        ("NZ:", "NEW ZEALAND"),
        ("LU:", "LUXEMBOURG"),
    )
    for prefix, country in prefix_map:
        if cid.startswith(prefix):
            return country

    source = _norm(rec.get("source") or rec.get("source_name") or rec.get("portal"))
    # Exact canonical live-source identifiers are authoritative enough to recover
    # jurisdiction when the normalized notice omitted its country. TED is
    # intentionally absent because it is multi-country and must remain fail-closed.
    exact_source_map = {
        "sam.gov": "USA",
        "sam": "USA",
        "us_sam_bulk": "USA",
        "contracts finder": "UNITED KINGDOM",
        "uk_contracts_finder": "UNITED KINGDOM",
        "boamp": "FRANCE",
        "fr_boamp": "FRANCE",
        "de_doe": "GERMANY",
        "canadabuys": "CANADA",
        "ca_canadabuys": "CANADA",
        "seao": "CANADA - QUEBEC",
        "qc_seao": "CANADA - QUEBEC",
        "ireland_etenders": "IRELAND",
        "austender": "AUSTRALIA",
        "nz_gets": "NEW ZEALAND",
        "lux_pmp": "LUXEMBOURG",
        "ch_simap": "SWITZERLAND",
        "cz_zakazky_gov": "CZECHIA",
        "dk_udbud_public": "DENMARK",
        "es_placsp": "SPAIN",
        "fi_hilma": "FINLAND",
        "gr_khmdhs": "GREECE",
        "lv_iub": "LATVIA",
        "nl_tenderned_rss": "NETHERLANDS",
        "no_doffin": "NORWAY",
        "pl_bzp": "POLAND",
    }
    return exact_source_map.get(source, "")


def _cpv(rec: dict) -> str:
    raw = rec.get("cpv") or rec.get("cpv_code") or rec.get("main_cpv") or rec.get("cpv_or_category") or ""
    if isinstance(raw, list):
        raw = raw[0] if raw else ""
    digits = re.sub(r"\D", "", str(raw))
    return digits[:2] if len(digits) >= 2 else ""


def _buyer(rec: dict) -> str:
    return _norm(rec.get("buyer") or rec.get("buyer_name") or rec.get("authority"))


def _title_text(rec: dict) -> str:
    """Title/name only for high-precision lane rules.

    Micro-Niche v2 showed that description/scope fields can mention unrelated
    work and contaminate otherwise attractive historical cohorts. Rules may now
    opt into match_field=title to fail closed on that failure mode.
    """
    return _norm(rec.get("title") or rec.get("name") or "")


def _search_text(rec: dict) -> str:
    vals = []
    for key in (
        "title", "name", "description", "scope", "scope_summary", "summary",
        "cpv_description", "cpv_or_category", "category", "subcategory",
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


def _country_matches(rule_country: str, record_country: str) -> bool:
    """Strict country match with explicit aliases; missing country never matches."""
    if not rule_country:
        return True
    if not record_country:
        return False
    aliases = {
        "FRANCE": {"FRA", "FR", "FRANCE"},
        "GERMANY": {"DEU", "DE", "GERMANY"},
        "UNITED KINGDOM": {"GBR", "GB", "UK", "UNITED KINGDOM"},
        "IRELAND": {"IRL", "IE", "IRELAND"},
        "CANADA": {"CAN", "CA", "CANADA"},
        "CANADA - QUEBEC": {"CANADA - QUEBEC", "QUEBEC", "QC"},
        "USA": {"USA", "US", "UNITED STATES", "UNITED STATES OF AMERICA"},
        "AUSTRALIA": {"AUS", "AU", "AUSTRALIA"},
        "NEW ZEALAND": {"NZL", "NZ", "NEW ZEALAND"},
        "LUXEMBOURG": {"LUX", "LU", "LUXEMBOURG"},
    }
    allowed = aliases.get(rule_country, {rule_country})
    return record_country in allowed


def _lane_adjustment(rec: dict, priors: dict) -> tuple[int, list[str]]:
    broad_text = _search_text(rec)
    country = _country(rec)
    if not broad_text:
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
        if not _country_matches(rcountry, country):
            continue
        match_field = str(rule.get("match_field") or "search_text").strip().casefold()
        if match_field == "title":
            text = _title_text(rec)
        elif match_field in {"search_text", "broad", "all"}:
            text = broad_text
        else:
            continue
        if not text:
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
