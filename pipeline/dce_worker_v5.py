from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

import requests

import dce_worker as base
import dce_worker_v2 as v2
import dce_worker_v4 as v4  # registers the full v4 adapter set first


def _gr_filename(resp: requests.Response, candidate: dict) -> str:
    cd = resp.headers.get('content-disposition') or ''
    m = re.search(r'filename\*?=(?:UTF-8\'\'|\")?([^\";]+)', cd, re.I)
    if m:
        name = m.group(1).strip().strip('"')
        if name:
            return base.safe_name(name)
    path_name = Path(urlparse(resp.url).path).name
    if path_name and '.' in path_name:
        return base.safe_name(path_name)
    notice_id = str(candidate.get('notice_id') or (candidate.get('route') or {}).get('reference_number') or 'khmdhs')
    return base.safe_name(f'{notice_id}.pdf')


def _gr_public_fetch(url: str, candidate: dict, out: Path, manifest: dict) -> bool:
    session = requests.Session()
    # This UA/Accept combination is deliberately the same anonymous public shape
    # that the successful canary diagnostic used. No authentication is attempted.
    session.headers.update({
        'User-Agent': 'Tender-Engine/5.2 public procurement research',
        'Accept': 'application/pdf,application/zip,application/octet-stream,*/*',
    })
    try:
        r = session.get(url, timeout=90, allow_redirects=True)
        ct = (r.headers.get('content-type') or '').lower()
        cd = (r.headers.get('content-disposition') or '').lower()
        prefix = bytes(r.content[:8]) if r.content else b''
        fileish = bool(
            r.ok and r.content and (
                'attachment' in cd
                or 'application/pdf' in ct
                or 'application/zip' in ct
                or 'application/octet-stream' in ct
                or prefix.startswith(b'%PDF-')
                or prefix.startswith(b'PK\x03\x04')
            )
        )
        attempt = {
            'method': 'GR_KHMDHS_PUBLIC_ATTACHMENT',
            'url': url,
            'resolved_url': r.url,
            'http_status': r.status_code,
            'content_type': r.headers.get('content-type'),
            'content_disposition': r.headers.get('content-disposition'),
            'bytes': len(r.content),
            'magic': prefix.hex(),
            'outcome': 'FILE_CONFIRMED' if fileish else 'NOT_FILE',
        }
        manifest.setdefault('dce_method_attempts', []).append(attempt)
        if not fileish:
            return False
        rec = base.persist_bytes(
            out,
            _gr_filename(r, candidate),
            r.content,
            r.url,
            r.headers.get('content-type'),
        )
        manifest['files'].append(rec)
        return True
    except Exception as exc:
        manifest.setdefault('dce_method_attempts', []).append({
            'method': 'GR_KHMDHS_PUBLIC_ATTACHMENT',
            'url': url,
            'outcome': 'ERROR',
            'error': repr(exc),
        })
        return False


def adapter_greece_robust(candidate: dict, out: Path, manifest: dict):
    manifest.setdefault('dce_method_attempts', [])
    route = candidate.get('route') or {}
    urls = []
    for u in route.get('document_urls') or []:
        if isinstance(u, str) and u.startswith(('http://', 'https://')):
            urls.append(u)
    notice_id = str(candidate.get('notice_id') or '').strip()
    if notice_id:
        canonical = f'https://cerpp.eprocurement.gov.gr/khmdhs-opendata/notice/attachment/{notice_id}'
        if canonical not in urls:
            urls.append(canonical)
    for url in urls:
        if _gr_public_fetch(url, candidate, out, manifest):
            manifest['status'] = 'DOWNLOADED_PUBLIC'
            return
    # Keep the v4 public-page cascade as a second method rather than giving up.
    v4.cascade_public_adapter(candidate, out, manifest)


base.ADAPTERS['GR_KHMDHS'] = adapter_greece_robust

if __name__ == '__main__':
    v2.main()
