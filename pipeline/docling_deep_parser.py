from __future__ import annotations

"""Optional Docling deep parser for hard DCE documents.

The native extractors remain the fast path.  This module is an additive fallback
that writes evidence sidecars and never deletes or replaces source documents.
"""

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

SUPPORTED = {".pdf", ".docx", ".pptx", ".html", ".htm", ".md", ".png", ".jpg", ".jpeg", ".tiff", ".tif"}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_with_docling(path: Path, output_dir: Path) -> dict[str, Any]:
    record: dict[str, Any] = {
        "source_path": str(path),
        "source_sha256": sha256_file(path),
        "parser": "docling",
        "status": "UNKNOWN",
        "markdown_path": None,
        "json_path": None,
        "text_chars": 0,
    }
    if path.suffix.lower() not in SUPPORTED:
        record["status"] = "UNSUPPORTED_FORMAT"
        return record

    try:
        from docling.document_converter import DocumentConverter
    except Exception as exc:
        record["status"] = "OPTIONAL_DEPENDENCY_MISSING"
        record["error"] = repr(exc)
        return record

    try:
        converter = DocumentConverter()
        result = converter.convert(path, raises_on_error=False)
        document = getattr(result, "document", None)
        if document is None:
            record["status"] = "CONVERSION_FAILED"
            record["conversion_status"] = str(getattr(result, "status", "UNKNOWN"))
            return record

        markdown = document.export_to_markdown()
        structured = document.export_to_dict()
        output_dir.mkdir(parents=True, exist_ok=True)
        stem = f"{path.stem}.{record['source_sha256'][:12]}"
        md_path = output_dir / f"{stem}.docling.md"
        json_path = output_dir / f"{stem}.docling.json"
        md_path.write_text(markdown, encoding="utf-8")
        json_path.write_text(json.dumps(structured, ensure_ascii=False, indent=2), encoding="utf-8")
        record.update(
            {
                "status": "DOWNLOADED_SOURCE_PARSED",
                "conversion_status": str(getattr(result, "status", "SUCCESS")),
                "markdown_path": str(md_path),
                "json_path": str(json_path),
                "text_chars": len(markdown),
            }
        )
        return record
    except Exception as exc:
        record["status"] = "PARSER_ERROR"
        record["error"] = repr(exc)
        return record


def should_deep_parse(kind: str, text_chars: int, mode: str = "auto", min_chars: int = 800) -> bool:
    """Keep native extraction cheap; deep-parse only low-yield supported docs by default."""

    if mode == "off":
        return False
    if mode == "always":
        return kind in {"pdf", "docx", "pptx"}
    if mode != "auto":
        raise ValueError(f"unknown Docling mode: {mode}")
    return kind in {"pdf", "docx", "pptx"} and text_chars < min_chars


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("input", type=Path)
    ap.add_argument("--output-dir", type=Path, required=True)
    args = ap.parse_args()
    result = parse_with_docling(args.input, args.output_dir)
    print(json.dumps(result, ensure_ascii=False))
    if result["status"] == "PARSER_ERROR":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
