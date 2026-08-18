from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    p = ROOT / path
    text = p.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"anchor missing in {path}: {old[:120]!r}")
    if text.count(old) != 1:
        raise SystemExit(f"anchor not unique in {path}: {old[:120]!r}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


# TED: request and persist authoritative buyer country from the Search API.
replace_once(
    "pipeline/discover_ted.py",
    '    "buyer-name",\n    "publication-date",',
    '    "buyer-name",\n    "buyer-country",\n    "publication-date",',
)
replace_once(
    "pipeline/discover_ted.py",
    '            buyer = scalar(first_field(item, "buyer-name"))\n            desc = scalar(first_field(item, "description-proc")) or ""',
    '            buyer = scalar(first_field(item, "buyer-name"))\n            buyer_country = scalar(first_field(item, "buyer-country"))\n            desc = scalar(first_field(item, "description-proc")) or ""',
)
replace_once(
    "pipeline/discover_ted.py",
    '                "buyer": str(buyer or "") or None,\n                "deadline": deadline,',
    '                "buyer": str(buyer or "") or None,\n                "country": str(buyer_country or "") or None,\n                "deadline": deadline,',
)

# Snapshot: national portals have deterministic source jurisdictions. Use them
# only when the record itself has no country; never overwrite explicit evidence.
replace_once(
    "pipeline/build_live_world_snapshot.py",
    'URL_KEYS = (\n    "url", "notice_url", "tender_url", "source_url", "publication_url", "documents_url",\n    "document_url", "dce_url", "buyer_url", "links", "attachments", "documents"\n)\n',
    'URL_KEYS = (\n    "url", "notice_url", "tender_url", "source_url", "publication_url", "documents_url",\n    "document_url", "dce_url", "buyer_url", "links", "attachments", "documents"\n)\n\nSOURCE_COUNTRY_FALLBACK = {\n    "IE": "IE", "UK": "GB", "UK_PCS_OCDS": "GB", "UK_FTS_OCDS": "GB",\n    "FR": "FR", "DE": "DE", "CA": "CA", "QC": "CA", "US_SAM": "US",\n    "AU": "AU", "AU_AUSTENDER": "AU", "NZ": "NZ", "PL": "PL", "DK": "DK",\n    "NL": "NL", "FI": "FI", "BE": "BE", "LU": "LU", "CY": "CY", "MT": "MT",\n    "ES_PLACSP": "ES", "PT_BASE_OPEN": "PT", "GR_KHMDHS": "GR", "LV_IUB": "LV",\n    "CH_SIMAP": "CH", "NO_DOFFIN": "NO", "CZ_ZAKAZKY_GOV": "CZ",\n    "SI_EJN": "SI", "SK_UVO": "SK", "EE_RHR": "EE", "LT_CVP_API": "LT",\n    "ZA_ETENDERS_OCDS": "ZA",\n}\n',
)
replace_once(
    "pipeline/build_live_world_snapshot.py",
    '    row = {\n        "candidate_id": cid,\n        "source_family": source_family(rec, cid),\n        "source": scalar_or_compact(first(rec, SOURCE_KEYS), 300),\n        "country": scalar_or_compact(first(rec, COUNTRY_KEYS), 120),',
    '    family = source_family(rec, cid)\n    explicit_country = scalar_or_compact(first(rec, COUNTRY_KEYS), 120)\n    row = {\n        "candidate_id": cid,\n        "source_family": family,\n        "source": scalar_or_compact(first(rec, SOURCE_KEYS), 300),\n        "country": explicit_country or SOURCE_COUNTRY_FALLBACK.get(family),',
)

# Qwen rich context: raise the safe minimum and preserve both head and tail of
# long descriptions. Critical scope/constraint language often appears at the end.
replace_once(
    "pipeline/qwen_notice_batch_selfheal_rich.py",
    'MIN_CONTEXT_CHARS = max(900, int(os.getenv("QWEN_RICH_MIN_CONTEXT_CHARS", "1600")))',
    'MIN_CONTEXT_CHARS = max(1200, int(os.getenv("QWEN_RICH_MIN_CONTEXT_CHARS", "2200")))',
)
replace_once(
    "pipeline/qwen_notice_batch_selfheal_rich.py",
    'def compact_text(value, limit: int) -> str:\n    if value in (None, "", [], {}):\n        return ""\n    if isinstance(value, (dict, list)):\n        try:\n            text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))\n        except Exception:\n            text = str(value)\n    else:\n        text = str(value)\n    text = " ".join(text.split())\n    return text[:limit]\n',
    'def compact_text(value, limit: int, *, preserve_tail: bool = False) -> str:\n    if value in (None, "", [], {}):\n        return ""\n    if isinstance(value, (dict, list)):\n        try:\n            text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))\n        except Exception:\n            text = str(value)\n    else:\n        text = str(value)\n    text = " ".join(text.split())\n    if len(text) <= limit:\n        return text\n    if preserve_tail and limit >= 240:\n        head = max(120, int(limit * 0.65))\n        tail = max(80, limit - head - 3)\n        return text[:head] + " … " + text[-tail:]\n    return text[:limit]\n',
)
replace_once(
    "pipeline/qwen_notice_batch_selfheal_rich.py",
    '    primary = compact_text(n.get("description"), max(500, budget // 2))',
    '    primary = compact_text(n.get("description"), max(700, budget // 2), preserve_tail=True)',
)
replace_once(
    "pipeline/qwen_notice_batch_selfheal_rich.py",
    '    for label, key in (\n        ("LOTS", "lots"),\n        ("ELIGIBILITY", "notice_eligibility"),\n        ("AWARD", "award_criteria"),\n        ("SUBCONTRACT", "subcontracting"),\n    ):',
    '    for label, key in (\n        ("ELIGIBILITY", "notice_eligibility"),\n        ("SUBCONTRACT", "subcontracting"),\n        ("LOTS", "lots"),\n        ("AWARD", "award_criteria"),\n    ):',
)

# Make changes to rich/core files themselves observable by the live classifier.
replace_once(
    ".github/workflows/qwen-live-classification.yml",
    "      - 'pipeline/qwen_notice_batch_selfheal.py'\n      - 'pipeline/qwen_notice_post_guard.py'",
    "      - 'pipeline/qwen_notice_batch_selfheal.py'\n      - 'pipeline/qwen_notice_batch_selfheal_rich.py'\n      - 'pipeline/qwen_notice_batch_selfheal_core.py'\n      - 'pipeline/qwen_notice_post_guard.py'",
)
replace_once(
    ".github/workflows/qwen-live-classification.yml",
    "            --description-chars 500 \\",
    "            --description-chars 2200 \\",
)

print("recall hardening p1 patch applied")
