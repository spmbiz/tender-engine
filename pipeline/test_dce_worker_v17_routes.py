from __future__ import annotations

import os
import tempfile
from pathlib import Path

import dce_worker_v15 as v15
import dce_worker_v17 as v17

ATOM = b'''<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry><id>cache-test</id><title>Cache test</title></entry>
</feed>
'''


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        old = os.environ.get("DCE_SHARED_CACHE_DIR")
        os.environ["DCE_SHARED_CACHE_DIR"] = tmp
        try:
            url = "https://example.test/feed.atom"
            resolved = "https://example.test/final/feed.atom"
            assert v17._read_cache(url) is None
            v17._write_cache(url, ATOM, resolved)
            cached = v17._read_cache(url)
            assert cached is not None
            body, cached_resolved = cached
            assert body == ATOM
            assert cached_resolved == resolved

            payload_path, meta_path, lock_path = v17._cache_paths(url)
            assert payload_path.is_file()
            assert meta_path.is_file()
            assert lock_path.parent == Path(tmp) / "placsp-atom"

            # A corrupt payload is rejected and never treated as authoritative XML.
            payload_path.write_bytes(b"not xml")
            assert v17._read_cache(url) is None
        finally:
            if old is None:
                os.environ.pop("DCE_SHARED_CACHE_DIR", None)
            else:
                os.environ["DCE_SHARED_CACHE_DIR"] = old

    assert v15._resolve_from_atom is v17._resolve_from_atom_cached
    print({"placsp_cache": "validated_xml_only", "shared_lock": True, "status": "ok"})


if __name__ == "__main__":
    main()
