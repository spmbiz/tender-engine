from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tarfile
import zipfile
from pathlib import Path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def unpack_archive(path: Path) -> Path | None:
    out = path.parent / f"{path.stem}_unpacked"
    if out.exists() and any(out.iterdir()):
        return out
    out.mkdir(parents=True, exist_ok=True)
    try:
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as z:
                z.extractall(out)
            return out
        if tarfile.is_tarfile(path):
            with tarfile.open(path) as t:
                t.extractall(out)
            return out
        if path.suffix.lower() == ".7z" and shutil.which("7z"):
            subprocess.run(["7z", "x", "-y", str(path), f"-o{out}"], check=False, capture_output=True)
            if any(out.iterdir()):
                return out
    except Exception:
        return None
    try:
        out.rmdir()
    except Exception:
        pass
    return None


def recursive_unpack(files_root: Path, max_rounds: int = 5):
    seen = set()
    for _ in range(max_rounds):
        changed = False
        for p in list(files_root.rglob("*")):
            if not p.is_file() or p in seen:
                continue
            seen.add(p)
            if p.suffix.lower() in {".zip", ".7z", ".tar", ".gz", ".tgz"} or zipfile.is_zipfile(p):
                out = unpack_archive(p)
                if out:
                    changed = True
        if not changed:
            break


def extract_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception as exc:
        return f"[PDF_EXTRACTION_ERROR {exc!r}]"


def extract_docx(path: Path) -> str:
    try:
        from docx import Document

        doc = Document(str(path))
        chunks = [p.text for p in doc.paragraphs if p.text]
        for table in doc.tables:
            for row in table.rows:
                chunks.append(" | ".join(cell.text for cell in row.cells))
        return "\n".join(chunks)
    except Exception as exc:
        return f"[DOCX_EXTRACTION_ERROR {exc!r}]"


def extract_xlsx(path: Path) -> str:
    try:
        from openpyxl import load_workbook

        wb = load_workbook(path, read_only=True, data_only=True)
        chunks = []
        for ws in wb.worksheets:
            chunks.append(f"[SHEET {ws.title}]")
            for row in ws.iter_rows(values_only=True):
                vals = ["" if v is None else str(v) for v in row]
                if any(vals):
                    chunks.append(" | ".join(vals))
        return "\n".join(chunks)
    except Exception as exc:
        return f"[XLSX_EXTRACTION_ERROR {exc!r}]"


def extract_pptx(path: Path) -> str:
    try:
        from pptx import Presentation

        prs = Presentation(str(path))
        chunks = []
        for idx, slide in enumerate(prs.slides, 1):
            chunks.append(f"[SLIDE {idx}]")
            for shape in slide.shapes:
                if hasattr(shape, "text") and shape.text:
                    chunks.append(shape.text)
        return "\n".join(chunks)
    except Exception as exc:
        return f"[PPTX_EXTRACTION_ERROR {exc!r}]"


def extract_text(path: Path) -> tuple[str, str]:
    ext = path.suffix.lower()
    if ext == ".pdf":
        return "pdf", extract_pdf(path)
    if ext == ".docx":
        return "docx", extract_docx(path)
    if ext in {".xlsx", ".xlsm"}:
        return "xlsx", extract_xlsx(path)
    if ext == ".pptx":
        return "pptx", extract_pptx(path)
    if ext in {".txt", ".md", ".csv", ".json", ".xml", ".html", ".htm", ".rtf"}:
        try:
            return "text", path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            return "text", f"[TEXT_EXTRACTION_ERROR {exc!r}]"
    return "unsupported", ""


def process_candidate(root: Path):
    files_root = root / "files"
    if not files_root.exists():
        return None
    recursive_unpack(files_root)
    docs = []
    corpus_chunks = []
    for path in sorted(files_root.rglob("*")):
        if not path.is_file():
            continue
        kind, text = extract_text(path)
        rel = str(path.relative_to(root))
        rec = {
            "path": rel,
            "name": path.name,
            "size": path.stat().st_size,
            "sha256": sha256_file(path),
            "kind": kind,
            "text_chars": len(text),
        }
        docs.append(rec)
        if text:
            # Keep enough text for full GPT deep read while preventing pathological files from exploding artifacts.
            if len(text) > 1_500_000:
                text = text[:1_500_000] + "\n[TRUNCATED_AT_1_500_000_CHARS]"
            corpus_chunks.extend([f"\n===== FILE: {rel} =====\n", text, "\n"])
    corpus = "".join(corpus_chunks)
    (root / "document_index.json").write_text(json.dumps(docs, indent=2, ensure_ascii=False), encoding="utf-8")
    (root / "corpus.txt").write_text(corpus, encoding="utf-8")
    return {"root": str(root), "documents": len(docs), "corpus_chars": len(corpus)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="out")
    args = ap.parse_args()
    base = Path(args.root)
    results = []
    candidates = [p.parent for p in base.rglob("manifest.json")]
    for root in sorted(set(candidates)):
        rec = process_candidate(root)
        if rec:
            results.append(rec)
    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
