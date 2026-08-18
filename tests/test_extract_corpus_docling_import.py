from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIPELINE = ROOT / "pipeline"
sys.path.insert(0, str(PIPELINE))

import extract_corpus


def test_docling_adapter_loads_when_pipeline_package_import_is_unavailable(monkeypatch):
    # DCE executes `python pipeline/extract_corpus.py`, so sibling-module import
    # must work even when `pipeline` is not importable as a package in a child.
    real_import = __import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "pipeline.docling_deep_parser":
            err = ModuleNotFoundError("No module named 'pipeline'")
            err.name = "pipeline"
            raise err
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", guarded_import)
    parse, should = extract_corpus._load_docling_adapter()
    assert callable(parse)
    assert callable(should)


def test_docling_adapter_does_not_mask_missing_dependency_inside_module(monkeypatch):
    real_import = __import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "pipeline.docling_deep_parser":
            err = ModuleNotFoundError("No module named 'some_dependency'")
            err.name = "some_dependency"
            raise err
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", guarded_import)
    try:
        extract_corpus._load_docling_adapter()
    except ModuleNotFoundError as exc:
        assert exc.name == "some_dependency"
    else:
        raise AssertionError("non-pipeline dependency error must not be silently masked")
