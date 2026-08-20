from __future__ import annotations

import argparse
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

try:
    from final_verdict_guard import REQUIRED_GATES
except Exception:
    REQUIRED_GATES = [
        "entity_geography",
        "turnover_financial",
        "references_experience",
        "certifications_partner",
        "staffing_team",
        "insurance_bonds",
        "subcontracting_consortium",
        "deliverables_scope",
        "sla_onsite",
        "term_value",
        "award_criteria",
        "forms_signatures",
        "submission",
        "ip_data_security",
        "payment_tax",
    ]

LAYER_CONTRACT = "GPT_DCE_READ_LAYER_V1"
MAX_GATE_SNIPPETS = 6
MAX_GATE_SNIPPET_CHARS = 1200


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return default


def _md(value) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    return re.sub(r"\s+", " ", text)


def _slug(value: str, fallback: str = "document") -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value or "").strip("-._")
    return (value or fallback)[:90]


def _doc_text(candidate_root: Path, corpus: str, doc: dict) -> tuple[str, str]:
    deep = doc.get("deep_parser") or {}
    md_path = deep.get("markdown_path")
    if md_path:
        p = Path(str(md_path))
        if not p.is_absolute():
            p = candidate_root / p
        if p.is_file():
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
                if text.strip():
                    return text, str(deep.get("parser") or "deep_parser")
            except Exception:
                pass

    try:
        start = int(doc.get("corpus_start"))
        end = int(doc.get("corpus_end"))
    except Exception:
        return "", "none"
    if 0 <= start <= end <= len(corpus):
        return corpus[start:end], str(doc.get("kind") or "corpus")
    return "", "none"


def _source_link(doc_map: dict[str, str], source: str | None) -> str:
    if not source:
        return ""
    rel = doc_map.get(source)
    return f"[{Path(source).name}]({rel})" if rel else f"`{source}`"


def _deadline_authority(authority: dict) -> tuple[str, bool]:
    deadline = authority.get("deadline") if isinstance(authority, dict) else {}
    if not isinstance(deadline, dict):
        return "UNKNOWN", False
    return str(deadline.get("status") or "UNKNOWN"), bool(deadline.get("conflict"))


def build_candidate_layer(candidate_root: Path) -> dict:
    candidate = load_json(candidate_root / "candidate.json", {})
    manifest = load_json(candidate_root / "manifest.json", {})
    docs = load_json(candidate_root / "document_index.json", [])
    gates = load_json(candidate_root / "gate_snippets.json", {})
    evidence = load_json(candidate_root / "evidence_quality.json", {})
    authority = load_json(candidate_root / "authority_conflicts.json", {})
    corpus_path = candidate_root / "corpus.txt"
    corpus = corpus_path.read_text(encoding="utf-8", errors="replace") if corpus_path.is_file() else ""

    if not isinstance(docs, list):
        docs = []
    if not isinstance(gates, dict):
        gates = {}
    if not isinstance(evidence, dict):
        evidence = {}
    if not isinstance(authority, dict):
        authority = {}

    out = candidate_root / "gpt_read"
    tmp = candidate_root / ".gpt_read.tmp"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True, exist_ok=True)
    docs_dir = tmp / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)

    doc_map: dict[str, str] = {}
    doc_rows: list[dict] = []
    for idx, doc in enumerate(docs, 1):
        if not isinstance(doc, dict):
            continue
        source_path = str(doc.get("path") or doc.get("name") or f"document-{idx}")
        text, parser = _doc_text(candidate_root, corpus, doc)
        filename = f"{idx:03d}_{_slug(Path(source_path).stem)}.md"
        rel = f"docs/{filename}"
        doc_map[source_path] = rel
        front = [
            f"# {Path(source_path).name}",
            "",
            f"- Source path: `{source_path}`",
            f"- Source URL: {doc.get('source_url') or 'UNKNOWN'}",
            f"- SHA-256: `{doc.get('sha256') or 'UNKNOWN'}`",
            f"- Kind: `{doc.get('kind') or 'UNKNOWN'}`",
            f"- Selected parser: `{parser}`",
            f"- Extracted chars: {len(text)}",
            "",
            "> This Markdown is a navigation/readability layer. The downloaded original remains authoritative.",
            "",
            "## Extracted content",
            "",
            text.strip() or "_No extracted text available for this document._",
            "",
        ]
        (docs_dir / filename).write_text("\n".join(front), encoding="utf-8")
        doc_rows.append(
            {
                "index": idx,
                "source_path": source_path,
                "markdown_path": rel,
                "source_url": doc.get("source_url"),
                "sha256": doc.get("sha256"),
                "kind": doc.get("kind"),
                "parser": parser,
                "text_chars": len(text),
            }
        )

    cid = str(candidate.get("candidate_id") or manifest.get("candidate_id") or candidate_root.name)
    deadline_status, deadline_conflict = _deadline_authority(authority)
    brief = [
        f"# DCE Brief — {cid}",
        "",
        f"- Title: {_md(candidate.get('title')) or 'UNKNOWN'}",
        f"- Buyer: {_md(candidate.get('buyer')) or 'UNKNOWN'}",
        f"- Portal: {_md(manifest.get('portal') or candidate.get('portal') or candidate.get('source')) or 'UNKNOWN'}",
        f"- Deadline from candidate: {_md(candidate.get('deadline')) or 'UNKNOWN'}",
        f"- Deadline authority status: {deadline_status}",
        f"- Deadline conflict: {'YES' if deadline_conflict else 'NO'}",
        f"- Estimated value: {_md(candidate.get('estimated_value')) or 'UNKNOWN'} {_md(candidate.get('currency'))}".rstrip(),
        f"- Retrieval status: {_md(manifest.get('status')) or 'UNKNOWN'}",
        f"- Evidence quality: {_md(evidence.get('content_quality')) or 'UNKNOWN'}",
        f"- Gate readiness: {str(bool(evidence.get('gate_readiness'))).lower()}",
        f"- Extracted documents: {len(doc_rows)}",
        f"- Full corpus chars: {len(corpus)}",
        "",
        "## Scope text from candidate",
        "",
        str(candidate.get("description") or candidate.get("scope") or candidate.get("title") or "UNKNOWN").strip(),
        "",
        "## Authority warning",
        "",
        "If deadline/conflict metadata is unresolved, verify the current official portal before relying on the candidate deadline.",
        "",
    ]
    (tmp / "BRIEF.md").write_text("\n".join(brief), encoding="utf-8")

    index_lines = [
        "# DCE Document Index",
        "",
        "| # | Document | Kind | Parser | Chars | Provenance |",
        "|---:|---|---|---|---:|---|",
    ]
    for row in doc_rows:
        source = row["source_url"] or row["source_path"]
        index_lines.append(
            f"| {row['index']} | [{Path(row['source_path']).name}]({row['markdown_path']}) | "
            f"{row['kind'] or 'UNKNOWN'} | {row['parser']} | {row['text_chars']} | {_md(source)} |"
        )
    index_lines += [
        "",
        "The original downloaded files and `../corpus.txt` remain the exhaustive evidence fallback.",
        "",
    ]
    (tmp / "DCE_INDEX.md").write_text("\n".join(index_lines), encoding="utf-8")

    categories = gates.get("categories") if isinstance(gates.get("categories"), dict) else {}
    gate_names = gates.get("canonical_gate_names")
    if not isinstance(gate_names, list) or not gate_names:
        gate_names = list(REQUIRED_GATES)

    gate_json = {
        "contract": "GPT_DCE_GATE_NAV_V1",
        "candidate_id": cid,
        "gate_readiness": gates.get("gate_readiness"),
        "content_quality": gates.get("content_quality") or evidence.get("content_quality"),
        "warning": "Navigation evidence only. Missing snippets are UNKNOWN, never PASS.",
        "gates": {},
    }
    gate_md = [
        f"# Mandatory Gate Navigation — {cid}",
        "",
        "> Retrieval evidence only. This file does **not** decide PASS/FAIL. Zero snippets means UNKNOWN, never PASS.",
        "",
    ]
    for gate in gate_names:
        hits = categories.get(gate) if isinstance(categories, dict) else []
        hits = hits if isinstance(hits, list) else []
        simplified = []
        gate_md += [f"## {gate}", "", f"Evidence candidates: **{len(hits)}**", ""]
        if not hits:
            gate_md += ["_No snippet extracted. Status remains UNKNOWN until full-document review._", ""]
        for hit in hits[:MAX_GATE_SNIPPETS]:
            if not isinstance(hit, dict):
                continue
            source = str(hit.get("source") or "")
            snippet = str(hit.get("snippet") or "").strip()
            if len(snippet) > MAX_GATE_SNIPPET_CHARS:
                snippet = snippet[:MAX_GATE_SNIPPET_CHARS] + "…"
            simplified.append(
                {
                    "match": hit.get("match"),
                    "source": source or None,
                    "source_markdown": doc_map.get(source),
                    "source_url": hit.get("source_url"),
                    "source_sha256": hit.get("source_sha256"),
                    "snippet": snippet,
                }
            )
            link = _source_link(doc_map, source) or "unattributed corpus"
            gate_md += [
                f"- **Match:** `{_md(hit.get('match')) or 'n/a'}` · **Source:** {link}",
                "",
                f"  > {_md(snippet)}",
                "",
            ]
        gate_json["gates"][gate] = {
            "evidence_count": len(hits),
            "evidence": simplified,
            "review_status": "UNKNOWN",
        }

    (tmp / "GATES.md").write_text("\n".join(gate_md), encoding="utf-8")
    (tmp / "GATES.json").write_text(json.dumps(gate_json, ensure_ascii=False, indent=2), encoding="utf-8")

    readme = [
        f"# GPT DCE Read Layer — {cid}",
        "",
        "Use this folder as the fast navigation layer for the procurement pack.",
        "",
        "## Read order",
        "",
        "1. [BRIEF.md](BRIEF.md) — candidate/retrieval/deadline context.",
        "2. [GATES.md](GATES.md) — mandatory-gate evidence map; **not** a verdict.",
        "3. [DCE_INDEX.md](DCE_INDEX.md) — open only the documents needed for unresolved gates/scope.",
        "4. `../corpus.txt` — exhaustive extracted-text fallback.",
        "5. Original downloaded procurement files — final authority for ambiguous clauses/tables/signatures.",
        "",
        "## Non-negotiable evidence rule",
        "",
        "This layer is derivative. Never upgrade UNKNOWN to PASS because a Markdown file or snippet is silent.",
        "Resolve conflicts against authoritative DCE/original portal evidence before a final green verdict.",
        "",
    ]
    (tmp / "README.md").write_text("\n".join(readme), encoding="utf-8")

    layer_manifest = {
        "contract": LAYER_CONTRACT,
        "candidate_id": cid,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "document_count": len(doc_rows),
        "gate_count": len(gate_names),
        "gate_readiness": evidence.get("gate_readiness"),
        "evidence_quality": evidence.get("content_quality"),
        "deadline_authority_status": deadline_status,
        "deadline_conflict": deadline_conflict,
        "source_files": [
            "candidate.json",
            "manifest.json",
            "document_index.json",
            "corpus.txt",
            "gate_snippets.json",
            "evidence_quality.json",
            "authority_conflicts.json",
        ],
        "documents": doc_rows,
        "rule": "GPT-readable derivative only; original DCE and provenance sidecars remain authoritative.",
    }
    (tmp / "layer_manifest.json").write_text(
        json.dumps(layer_manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if out.exists():
        shutil.rmtree(out)
    tmp.rename(out)
    return {
        "candidate_id": cid,
        "root": str(candidate_root),
        "gpt_read_root": str(out),
        "documents": len(doc_rows),
        "gates": len(gate_names),
        "deadline_conflict": deadline_conflict,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="out")
    args = ap.parse_args()
    root = Path(args.root)
    candidate_roots = sorted(set(p.parent for p in root.rglob("manifest.json")))
    results = [build_candidate_layer(p) for p in candidate_roots]
    print(json.dumps({"contract": LAYER_CONTRACT, "candidates": len(results), "results": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
