from pipeline.docling_deep_parser import should_deep_parse


def test_docling_auto_only_targets_low_yield_supported_documents():
    assert should_deep_parse("pdf", 0, mode="auto", min_chars=800) is True
    assert should_deep_parse("docx", 799, mode="auto", min_chars=800) is True
    assert should_deep_parse("pdf", 800, mode="auto", min_chars=800) is False
    assert should_deep_parse("xlsx", 0, mode="auto", min_chars=800) is False


def test_docling_off_preserves_native_only_path():
    assert should_deep_parse("pdf", 0, mode="off") is False


def test_docling_always_still_limits_to_supported_document_kinds():
    assert should_deep_parse("pptx", 10000, mode="always") is True
    assert should_deep_parse("text", 0, mode="always") is False
