from __future__ import annotations

from pathlib import Path


def qi(x: str) -> str:
    return '"' + x.replace('"', '""') + '"'


def lit(x: str) -> str:
    return "'" + x.replace("'", "''") + "'"


def choose(cols: set[str], *names: str) -> str | None:
    m = {c.casefold(): c for c in cols}
    for n in names:
        if n.casefold() in m:
            return m[n.casefold()]
    return None


def relation(path: Path) -> str:
    p = lit(str(path))
    if path.suffix.lower() == '.parquet':
        return f"read_parquet({p})"
    return f"read_csv_auto({p}, header=true, all_varchar=true, sample_size=200000, ignore_errors=false, compression='auto')"


def cols_for(con, rel: str) -> set[str]:
    return {r[0] for r in con.execute(f"DESCRIBE SELECT * FROM {rel}").fetchall()}


def text_expr(c: str | None, default="''") -> str:
    return f"trim(cast({qi(c)} as varchar))" if c else default


def double_expr(c: str | None) -> str:
    return f"try_cast({qi(c)} as double)" if c else "NULL::DOUBLE"


def date_expr(c: str | None) -> str:
    return f"try_cast({qi(c)} as date)" if c else "NULL::DATE"


def route_case(source: str, proc: str, grain: str) -> str:
    if grain == 'AWARD_FIRST_PROCUREMENT':
        return "'AWARD_FIRST_EVIDENCE'"
    sl = f"lower(coalesce({source},''))"
    pl = f"lower(coalesce({proc},''))"
    return f"""
    CASE
      WHEN {sl}='quebec' THEN CASE
        WHEN {pl} LIKE '%gré à gré%' THEN 'DIRECT_NONCOMPETITIVE'
        WHEN {pl} LIKE '%invitation%' THEN 'LIMITED_INVITATION'
        WHEN ({pl} LIKE '%avis d’appel d’offres%' OR {pl} LIKE '%avis d''appel d''offres%') THEN 'OPEN_PUBLIC'
        ELSE 'UNKNOWN' END
      WHEN {sl}='canada federal' THEN CASE
        WHEN {pl}='competitive - open bidding' THEN 'OPEN_PUBLIC'
        WHEN {pl} IN ('competitive - traditional','competitive - selective tendering','competitive - limited tendering') THEN 'COMPETITIVE_OTHER'
        WHEN {pl}='advance contract award notice' OR {pl}='non-competitive' THEN 'DIRECT_NONCOMPETITIVE'
        ELSE 'UNKNOWN' END
      WHEN {sl}='france' THEN CASE
        WHEN {pl} LIKE 'ouvert/%' OR {pl}='ouvert/' THEN 'OPEN_PUBLIC'
        WHEN {pl} LIKE 'procedure_adapte/%' OR {pl}='procedure_adapte/' OR {pl} LIKE 'restreint/%' OR {pl}='restreint/' OR {pl} LIKE '%avec_pub_prealable%' OR {pl} LIKE 'dialogue_competitif/%' THEN 'COMPETITIVE_OTHER'
        WHEN {pl} LIKE '%sans_pub%' OR {pl} LIKE 'attribue_sans_pub%' THEN 'DIRECT_NONCOMPETITIVE'
        ELSE 'UNKNOWN' END
      WHEN {sl}='germany' THEN CASE
        WHEN {pl} IN ('de-open','open','us-open') THEN 'OPEN_PUBLIC'
        WHEN {pl} IN ('restricted','de-restricted-w-call','neg-w-call','de-comp-w-call','de-comp-neg-w-call','comp-tend','comp-dial','us-neg-w-call','us-res-tw') THEN 'COMPETITIVE_OTHER'
        WHEN {pl} IN ('neg-wo-call','de-restricted-wo-call','de-comp-wo-call','de-comp-neg-wo-call','oth-single','us-neg-wo-call','us-free-no-tw','us-res-no-tw') OR {pl} LIKE '%freihändige%' OR {pl} LIKE '%freihandige%' THEN 'DIRECT_NONCOMPETITIVE'
        ELSE 'UNKNOWN' END
      WHEN {sl}='ireland' THEN CASE
        WHEN {pl}='open procedure' THEN 'OPEN_PUBLIC'
        WHEN {pl} IN ('restricted procedure','competitive procedure with negotiation','simplified','competitive dialogue') THEN 'COMPETITIVE_OTHER'
        WHEN {pl} LIKE '%direct%' THEN 'DIRECT_NONCOMPETITIVE'
        ELSE 'UNKNOWN' END
      WHEN {pl} LIKE '%open%' OR {pl} LIKE '%ouvert%' THEN 'OPEN_PUBLIC'
      WHEN {pl} LIKE '%direct%' OR {pl} LIKE '%single%' OR {pl} LIKE '%non-competitive%' THEN 'DIRECT_NONCOMPETITIVE'
      WHEN {pl} LIKE '%restricted%' OR {pl} LIKE '%negotiat%' OR {pl} LIKE '%competitive%' THEN 'COMPETITIVE_OTHER'
      ELSE 'UNKNOWN'
    END
    """
