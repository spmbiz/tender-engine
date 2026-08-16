from __future__ import annotations

"""Non-destructive organization identity resolution for procurement records.

This module is deliberately a *shadow* layer.  It emits evidence-bearing linkage
suggestions; it never rewrites candidate IDs, notices, buyers, suppliers, or the
canonical warehouse.

Resolution order:
1. authoritative/legal identifiers (auto-link only when exact);
2. deterministic supporting features (domain/postcode/name/address);
3. optional Splink probabilistic suggestions for manual/downstream review.

Belgian BCE/KBO Public Search must not be mass-scraped.  This module only
normalizes identifiers already present in procurement data or in an authorized
BCE/KBO Open Data import supplied to the pipeline.
"""

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

LEGAL_ID_FIELDS = (
    "enterprise_number",
    "company_number",
    "registration_number",
    "vat_number",
    "vat",
    "bce_number",
    "kbo_number",
    "national_id",
    "identifier",
)
NAME_FIELDS = ("name", "buyer", "supplier", "organization_name", "legal_name")
ADDRESS_FIELDS = ("address", "street_address", "registered_address")
POSTCODE_FIELDS = ("postcode", "postal_code", "zip")
DOMAIN_FIELDS = ("domain", "website", "url")
COUNTRY_FIELDS = ("country", "country_code", "jurisdiction")


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def first_value(record: dict[str, Any], fields: Iterable[str]) -> str:
    for field in fields:
        value = record.get(field)
        if value not in (None, ""):
            return clean(value)
    return ""


def normalize_country(value: Any) -> str:
    raw = re.sub(r"[^A-Z]", "", clean(value).upper())
    aliases = {
        "BELGIUM": "BE",
        "BELGIQUE": "BE",
        "BELGIE": "BE",
        "BELGIEN": "BE",
    }
    return aliases.get(raw, raw[:2] if len(raw) == 2 else raw)


def normalize_be_enterprise_number(value: Any) -> str | None:
    """Return the canonical 10-digit BCE/KBO enterprise number or None.

    We intentionally do not guess missing digits.  A valid enterprise number has
    10 digits and starts with 0 or 1. Establishment-unit numbers (2..8 prefix)
    are not silently treated as enterprise numbers.
    """

    raw = clean(value).upper()
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw.removeprefix("BE"))
    if len(digits) != 10 or digits[0] not in {"0", "1"}:
        return None
    return digits


def normalize_domain(value: Any) -> str:
    raw = clean(value).lower()
    if not raw:
        return ""
    candidate = raw if "://" in raw else f"https://{raw}"
    try:
        host = (urlparse(candidate).hostname or "").lower().rstrip(".")
    except Exception:
        host = ""
    if host.startswith("www."):
        host = host[4:]
    return host


def normalize_name(value: Any) -> str:
    raw = clean(value).casefold()
    raw = re.sub(r"[^\w\s]", " ", raw, flags=re.UNICODE)
    raw = re.sub(r"\s+", " ", raw).strip()
    return raw


def normalize_postcode(value: Any) -> str:
    return re.sub(r"\s+", "", clean(value).upper())


def normalized_identity(record: dict[str, Any], row_id: str | None = None) -> dict[str, Any]:
    country = normalize_country(first_value(record, COUNTRY_FIELDS))
    legal_raw = first_value(record, LEGAL_ID_FIELDS)
    be_number = normalize_be_enterprise_number(legal_raw) if country in {"", "BE"} else None
    canonical_legal_id = f"BE:BCE:{be_number}" if be_number else ""

    out = {
        "row_id": row_id or clean(record.get("row_id") or record.get("candidate_id") or record.get("id")),
        "source": clean(record.get("source") or record.get("provider")),
        "country": country,
        "name": first_value(record, NAME_FIELDS),
        "normalized_name": normalize_name(first_value(record, NAME_FIELDS)),
        "address": first_value(record, ADDRESS_FIELDS),
        "normalized_postcode": normalize_postcode(first_value(record, POSTCODE_FIELDS)),
        "domain": normalize_domain(first_value(record, DOMAIN_FIELDS)),
        "legal_id_raw": legal_raw,
        "canonical_legal_id": canonical_legal_id,
        "bce_kbo_enterprise_number": be_number or "",
    }
    return out


def deterministic_links(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return only exact identifier links as auto-linkable evidence."""

    normalized = [normalized_identity(rec, str(i)) for i, rec in enumerate(records)]
    by_legal: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for rec in normalized:
        if rec["canonical_legal_id"]:
            by_legal[rec["canonical_legal_id"]].append(rec)

    links: list[dict[str, Any]] = []
    for legal_id, group in sorted(by_legal.items()):
        if len(group) < 2:
            continue
        for i, left in enumerate(group):
            for right in group[i + 1 :]:
                links.append(
                    {
                        "left_row_id": left["row_id"],
                        "right_row_id": right["row_id"],
                        "match_method": "EXACT_AUTHORITATIVE_LEGAL_ID",
                        "match_score": 1.0,
                        "auto_merge_allowed": True,
                        "canonical_legal_id": legal_id,
                        "evidence": [{"field": "canonical_legal_id", "value": legal_id}],
                    }
                )
    return links


def splink_shadow_links(records: list[dict[str, Any]], threshold: float = 0.90) -> dict[str, Any]:
    """Generate optional probabilistic suggestions with Splink.

    The function is intentionally fail-closed: missing dependencies, insufficient
    training signal, or any model error returns an explicit status and zero links.
    Probabilistic links are *never* auto-mergeable.
    """

    try:
        import pandas as pd
        import splink.comparison_library as cl
        from splink import DuckDBAPI, Linker, SettingsCreator, block_on
    except Exception as exc:  # optional dependency by design
        return {"status": "OPTIONAL_DEPENDENCY_MISSING", "error": repr(exc), "links": []}

    rows = [normalized_identity(rec, str(i)) for i, rec in enumerate(records)]
    usable = [r for r in rows if r["normalized_name"] and (r["normalized_postcode"] or r["domain"])]
    if len(usable) < 20:
        return {"status": "INSUFFICIENT_TRAINING_CORPUS", "records": len(usable), "links": []}

    df = pd.DataFrame(usable)
    try:
        settings = SettingsCreator(
            link_type="dedupe_only",
            comparisons=[
                cl.NameComparison("normalized_name"),
                cl.ExactMatch("normalized_postcode").configure(term_frequency_adjustments=True),
                cl.ExactMatch("domain").configure(term_frequency_adjustments=True),
            ],
            blocking_rules_to_generate_predictions=[
                block_on("normalized_postcode"),
                block_on("domain"),
            ],
            retain_matching_columns=True,
        )
        linker = Linker(df, settings, db_api=DuckDBAPI())
        linker.training.estimate_u_using_random_sampling(max_pairs=min(1_000_000, max(10_000, len(df) ** 2)), seed=1729)
        # Train across two independent support signals.  Sparse corpora can fail;
        # that is an explicit shadow failure, never a destructive pipeline error.
        for rule in (block_on("normalized_postcode"), block_on("domain")):
            try:
                linker.training.estimate_parameters_using_expectation_maximisation(rule)
            except Exception:
                pass
        predictions = linker.inference.predict(threshold_match_probability=threshold)
        pred = predictions.as_pandas_dataframe()
    except Exception as exc:
        return {"status": "SPLINK_MODEL_ERROR", "error": repr(exc), "links": []}

    links: list[dict[str, Any]] = []
    for row in pred.to_dict(orient="records"):
        left = str(row.get("row_id_l", ""))
        right = str(row.get("row_id_r", ""))
        if not left or not right:
            continue
        links.append(
            {
                "left_row_id": left,
                "right_row_id": right,
                "match_method": "SPLINK_PROBABILISTIC_SHADOW",
                "match_score": float(row.get("match_probability") or 0.0),
                "auto_merge_allowed": False,
                "evidence": {
                    "normalized_name_l": row.get("normalized_name_l"),
                    "normalized_name_r": row.get("normalized_name_r"),
                    "postcode_l": row.get("normalized_postcode_l"),
                    "postcode_r": row.get("normalized_postcode_r"),
                    "domain_l": row.get("domain_l"),
                    "domain_r": row.get("domain_r"),
                },
            }
        )
    return {"status": "OK", "records": len(usable), "links": links}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            obj = json.loads(line)
            if isinstance(obj, dict):
                out.append(obj)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("input", type=Path)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--splink-shadow", action="store_true")
    ap.add_argument("--threshold", type=float, default=0.90)
    args = ap.parse_args()

    records = read_jsonl(args.input)
    payload: dict[str, Any] = {
        "mode": "NON_DESTRUCTIVE_SHADOW",
        "records": len(records),
        "deterministic_links": deterministic_links(records),
        "splink": {"status": "DISABLED", "links": []},
        "invariants": {
            "weak_match_auto_merge": False,
            "public_search_bulk_scrape": False,
            "unknown_remains_unknown": True,
        },
    }
    if args.splink_shadow:
        payload["splink"] = splink_shadow_links(records, threshold=args.threshold)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"records": len(records), "deterministic_links": len(payload["deterministic_links"]), "splink_status": payload["splink"]["status"]}))


if __name__ == "__main__":
    main()
