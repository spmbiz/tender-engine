from __future__ import annotations

"""Materialize French DECP historical award intelligence.

This lane is intentionally AWARD-first. It must never be merged into the live
NOTICE_FIRST_TENDER grain or used as proof that a current opportunity is easy.

The source is the consolidated French DECP Parquet published on data.gouv.fr.
We preserve the downloaded source snapshot, its SHA256, schema, source URL and
observed timestamp. Derived tables are compact Parquet facts:
  * awards.parquet                grain=AWARD
  * award_supplier_links.parquet  grain=AWARD_SUPPLIER_LINK
  * buyer_supplier_priors.parquet historical prior aggregates only
"""

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

DEFAULT_SOURCE_URL = "https://www.data.gouv.fr/api/1/datasets/r/9a4144c0-ee44-4dec-bee5-bbef38191d9a"
SOURCE_KEY = "FR_DECP_CONSOLIDATED"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(4 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, dest: Path, retries: int = 4) -> dict:
    try:
        import requests
    except Exception as exc:  # pragma: no cover - dependency gate
        raise RuntimeError("requests is required") from exc
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    last = None
    for attempt in range(retries):
        try:
            with requests.get(url, stream=True, timeout=(20, 180), allow_redirects=True, headers={"User-Agent": "Tender-Engine/4.0 DECP historical intelligence"}) as r:
                r.raise_for_status()
                with tmp.open("wb") as fh:
                    for chunk in r.iter_content(chunk_size=4 * 1024 * 1024):
                        if chunk:
                            fh.write(chunk)
                if tmp.stat().st_size < 1024:
                    raise RuntimeError(f"suspiciously small DECP payload: {tmp.stat().st_size} bytes")
                tmp.replace(dest)
                return {
                    "requested_url": url,
                    "resolved_url": r.url,
                    "bytes": dest.stat().st_size,
                    "etag": r.headers.get("ETag"),
                    "last_modified": r.headers.get("Last-Modified"),
                }
        except Exception as exc:
            last = exc
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass
            if attempt + 1 < retries:
                time.sleep(min(20, 2 ** attempt))
    raise RuntimeError(f"failed to download DECP source after {retries} attempts: {last!r}")


def q(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def lit(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def choose(columns: Iterable[str], *aliases: str) -> str | None:
    index = {c.casefold(): c for c in columns}
    for alias in aliases:
        if alias.casefold() in index:
            return index[alias.casefold()]
    return None


def expr(columns: list[str], aliases: tuple[str, ...], cast: str = "VARCHAR", default: str = "NULL") -> str:
    col = choose(columns, *aliases)
    if not col:
        return default
    if cast:
        return f"try_cast({q(col)} AS {cast})"
    return q(col)


def supplier_slots(columns: list[str]) -> list[dict[str, str | None]]:
    lower = {c.casefold(): c for c in columns}
    slots: list[dict[str, str | None]] = []
    # Consolidated DECP variants can be one-row-per-holder (singular) or expose
    # up to several titulaire_*_N columns. Support both without guessing.
    singular_id = choose(columns, "titulaire_id", "titulaire_siret")
    if singular_id:
        slots.append({
            "id": singular_id,
            "name": choose(columns, "titulaire_nom", "titulaire_denominationsociale", "titulaire_denomination_sociale"),
            "type": choose(columns, "titulaire_typeidentifiant", "titulaire_type_identifiant"),
        })
    for i in range(1, 11):
        sid = lower.get(f"titulaire_id_{i}")
        if not sid:
            continue
        slots.append({
            "id": sid,
            "name": lower.get(f"titulaire_denominationsociale_{i}") or lower.get(f"titulaire_nom_{i}"),
            "type": lower.get(f"titulaire_typeidentifiant_{i}"),
        })
    # deterministic de-duplication if singular aliases point at a numbered field
    seen = set()
    out = []
    for slot in slots:
        key = slot["id"]
        if key and key not in seen:
            seen.add(key)
            out.append(slot)
    return out


def sql_value(column: str | None, cast: str = "VARCHAR") -> str:
    return f"try_cast({q(column)} AS {cast})" if column else "NULL"


def current_predicate(columns: list[str]) -> str:
    current = choose(columns, "donneesActuelles", "donnees_actuelles")
    if current:
        c = q(current)
        return f"coalesce(try_cast({c} AS BOOLEAN), lower(try_cast({c} AS VARCHAR)) IN ('true','1','oui','yes')) = true"
    # Do not invent currentness when the source does not expose it.
    return "true"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=Path("historical/fr_decp"))
    ap.add_argument("--source-url", default=os.getenv("FR_DECP_SOURCE_URL", DEFAULT_SOURCE_URL))
    ap.add_argument("--source-path", type=Path, help="Use an already downloaded Parquet (tests/offline replay).")
    ap.add_argument("--keep-all-versions", action="store_true", help="Do not filter to donneesActuelles when that field exists.")
    args = ap.parse_args()

    try:
        import duckdb
    except Exception as exc:  # pragma: no cover - dependency gate
        raise SystemExit(f"duckdb dependency missing: {exc!r}")

    out = args.output
    out.mkdir(parents=True, exist_ok=True)
    observed_at = datetime.now(timezone.utc).isoformat()
    source = out / "source" / "fr_decp_source.parquet"
    if args.source_path:
        source.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(args.source_path, source)
        source_meta = {"requested_url": None, "resolved_url": str(args.source_path), "bytes": source.stat().st_size, "replay": True}
    else:
        source_meta = download(args.source_url, source)
    source_hash = sha256_file(source)

    con = duckdb.connect(database=":memory:")
    con.execute("PRAGMA threads=4")
    con.execute("PRAGMA memory_limit='5GB'")
    source_sql = lit(str(source))
    columns = [row[0] for row in con.execute(f"DESCRIBE SELECT * FROM read_parquet({source_sql})").fetchall()]
    if not columns:
        raise SystemExit("DECP Parquet has no columns")

    buyer_id = expr(columns, ("acheteur_id", "acheteur.id"))
    buyer_name = expr(columns, ("acheteur_nom", "acheteur.nom", "nom_acheteur"))
    market_id = expr(columns, ("id", "marche_id", "market_id"))
    uid_col = choose(columns, "uid")
    if uid_col:
        award_id = f"try_cast({q(uid_col)} AS VARCHAR)"
    else:
        award_id = f"concat_ws(':', coalesce({buyer_id}, 'UNKNOWN_BUYER'), coalesce({market_id}, 'UNKNOWN_MARKET'))"

    object_expr = expr(columns, ("objet", "object"))
    cpv_expr = expr(columns, ("codecpv", "codeCPV", "cpv"))
    procedure_expr = expr(columns, ("procedure", "procédure"))
    nature_expr = expr(columns, ("nature",))
    amount_expr = expr(columns, ("montant", "amount"), cast="DOUBLE")
    duration_expr = expr(columns, ("dureemois", "dureeMois", "duree_mois"), cast="INTEGER")
    notified_expr = expr(columns, ("datenotification", "dateNotification", "date_notification"), cast="DATE")
    published_expr = expr(columns, ("datepublicationdonnees", "datePublicationDonnees", "date_publication_donnees"), cast="TIMESTAMP")
    modification_expr = expr(columns, ("modification_id", "idmodification", "idModification"), cast="VARCHAR")
    predicate = "true" if args.keep_all_versions else current_predicate(columns)

    con.execute(f"CREATE VIEW src AS SELECT * FROM read_parquet({source_sql})")
    con.execute(f"""
        COPY (
          SELECT DISTINCT
            'AWARD' AS grain,
            {lit(SOURCE_KEY)} AS source,
            {award_id} AS award_id,
            {market_id} AS market_internal_id,
            {buyer_id} AS buyer_id,
            {buyer_name} AS buyer_name,
            {object_expr} AS object,
            {cpv_expr} AS cpv,
            {procedure_expr} AS procedure,
            {nature_expr} AS nature,
            {amount_expr} AS amount_eur,
            {duration_expr} AS duration_months,
            {notified_expr} AS notification_date,
            {published_expr} AS data_publication_date,
            {modification_expr} AS modification_id,
            {lit(args.source_url)} AS source_url,
            {lit(observed_at)} AS observed_at,
            {lit(source_hash)} AS source_sha256
          FROM src
          WHERE {predicate}
            AND {award_id} IS NOT NULL
        ) TO {lit(str(out / 'awards.parquet'))} (FORMAT PARQUET, COMPRESSION ZSTD)
    """)

    slots = supplier_slots(columns)
    if not slots:
        supplier_union = "SELECT NULL::VARCHAR award_id, NULL::VARCHAR supplier_id, NULL::VARCHAR supplier_name, NULL::VARCHAR supplier_id_type WHERE false"
    else:
        parts = []
        for slot in slots:
            sid = sql_value(slot["id"])
            sname = sql_value(slot["name"])
            stype = sql_value(slot["type"])
            parts.append(f"""
                SELECT DISTINCT
                  {award_id} AS award_id,
                  {sid} AS supplier_id,
                  {sname} AS supplier_name,
                  {stype} AS supplier_id_type,
                  {buyer_id} AS buyer_id,
                  {cpv_expr} AS cpv,
                  {amount_expr} AS amount_eur,
                  {notified_expr} AS notification_date
                FROM src
                WHERE {predicate} AND {award_id} IS NOT NULL
                  AND {sid} IS NOT NULL AND trim({sid}) NOT IN ('', 'CDL', 'NULL')
            """)
        supplier_union = " UNION ALL ".join(parts)

    con.execute(f"""
        COPY (
          SELECT DISTINCT
            'AWARD_SUPPLIER_LINK' AS grain,
            {lit(SOURCE_KEY)} AS source,
            award_id, supplier_id, supplier_name, supplier_id_type,
            buyer_id, cpv, amount_eur, notification_date,
            {lit(args.source_url)} AS source_url,
            {lit(observed_at)} AS observed_at,
            {lit(source_hash)} AS source_sha256
          FROM ({supplier_union})
        ) TO {lit(str(out / 'award_supplier_links.parquet'))} (FORMAT PARQUET, COMPRESSION ZSTD)
    """)

    con.execute(f"""
        COPY (
          SELECT
            buyer_id,
            supplier_id,
            any_value(supplier_name) AS supplier_name,
            cpv,
            count(DISTINCT award_id) AS historical_award_count,
            sum(amount_eur) FILTER (WHERE amount_eur IS NOT NULL) AS historical_amount_eur,
            median(amount_eur) FILTER (WHERE amount_eur IS NOT NULL) AS median_award_amount_eur,
            min(notification_date) AS first_notification_date,
            max(notification_date) AS last_notification_date,
            {lit('HISTORICAL_PRIOR_NOT_LIVE_PROOF')} AS semantics
          FROM read_parquet({lit(str(out / 'award_supplier_links.parquet'))})
          WHERE buyer_id IS NOT NULL AND supplier_id IS NOT NULL
          GROUP BY buyer_id, supplier_id, cpv
        ) TO {lit(str(out / 'buyer_supplier_priors.parquet'))} (FORMAT PARQUET, COMPRESSION ZSTD)
    """)

    counts = {}
    for name in ("awards", "award_supplier_links", "buyer_supplier_priors"):
        p = out / f"{name}.parquet"
        counts[name] = int(con.execute(f"SELECT count(*) FROM read_parquet({lit(str(p))})").fetchone()[0])

    schema_payload = {
        "source_columns": columns,
        "supplier_slots": slots,
        "current_filter": predicate,
        "source_key": SOURCE_KEY,
        "grains": ["AWARD", "AWARD_SUPPLIER_LINK"],
    }
    (out / "source_schema.json").write_text(json.dumps(schema_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    stats = {
        "status": "OK",
        "source": SOURCE_KEY,
        "grain": ["AWARD", "AWARD_SUPPLIER_LINK"],
        "generated_at": observed_at,
        "source_url": args.source_url,
        "source_resolved_url": source_meta.get("resolved_url"),
        "source_bytes": source.stat().st_size,
        "source_sha256": source_hash,
        "source_http": source_meta,
        "counts": counts,
        "supplier_slots_detected": len(slots),
        "kept_all_versions": bool(args.keep_all_versions),
        "semantics": "Historical award evidence and priors only. Never substitute for current notice eligibility, DCE gates, or live competition facts.",
    }
    (out / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
