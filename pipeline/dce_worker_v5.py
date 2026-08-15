from __future__ import annotations

import html
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

import dce_worker as base
import dce_worker_v2 as v2
import dce_worker_v3 as v3
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
    v4.cascade_public_adapter(candidate, out, manifest)


def adapter_ted_public_fast(candidate: dict, out: Path, manifest: dict):
    """Bounded HTTP-only fallback for previously unclassified TED public routes.

    This deliberately avoids Playwright so long-tail unknown portals cannot turn a
    320-candidate wave into hundreds of browser-minutes. Recognized portal families
    still use their richer adapters. Barriers stay explicit and no login is bypassed.
    """
    manifest.setdefault('dce_method_attempts', [])
    route = candidate.get('route') or {}
    detail_url = route.get('detail_url') or candidate.get('notice_url')
    if not isinstance(detail_url, str) or not detail_url.startswith(('http://', 'https://')):
        manifest['status'] = 'ROUTE_INCOMPLETE'
        return

    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Tender-Engine/5.3 public procurement research',
        'Accept': 'text/html,application/xhtml+xml,application/pdf,application/zip,*/*',
    })
    try:
        r = session.get(detail_url, timeout=30, allow_redirects=True)
    except Exception as exc:
        manifest['status'] = 'ERROR_RETRYABLE'
        manifest['error'] = repr(exc)
        manifest['dce_method_attempts'].append({'method': 'TED_PUBLIC_FAST_HTTP', 'url': detail_url, 'outcome': 'ERROR', 'error': repr(exc)[:500]})
        return

    ct = (r.headers.get('content-type') or '').lower()
    manifest['dce_method_attempts'].append({
        'method': 'TED_PUBLIC_FAST_HTTP',
        'url': detail_url,
        'resolved_url': r.url,
        'http_status': r.status_code,
        'content_type': r.headers.get('content-type'),
        'bytes': len(r.content),
    })

    if r.ok and r.content and base.looks_like_file(r):
        manifest['files'].append(base.persist_bytes(out, base.filename_from_response(r, 'download.bin'), r.content, r.url, r.headers.get('content-type')))
        manifest['status'] = 'DOWNLOADED_PUBLIC'
        return

    if r.status_code == 429 or r.status_code >= 500:
        manifest['status'] = 'ERROR_RETRYABLE'
        return

    raw = html.unescape(r.text if 'html' in ct or 'text/' in ct else '')
    text = re.sub(r'<script\b[^>]*>.*?</script>', ' ', raw, flags=re.I | re.S)
    text = re.sub(r'<style\b[^>]*>.*?</style>', ' ', text, flags=re.I | re.S)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', html.unescape(text)).strip()
    if text:
        (out / 'portal_page.txt').write_text(text[:1_000_000], encoding='utf-8')

    candidates = []
    for href in re.findall(r'href\s*=\s*[\"\']([^\"\']+)[\"\']', raw, re.I):
        absolute = urljoin(r.url, html.unescape(href))
        if absolute.startswith(('http://', 'https://')) and v3.FILE_OR_DOWNLOAD_RE.search(absolute):
            candidates.append(absolute)
    candidates = list(dict.fromkeys(candidates))[:25]
    manifest['public_document_candidates'] = candidates
    for url in candidates:
        rec = base.direct_download(url, out, session)
        manifest['dce_method_attempts'].append({'method': 'TED_PUBLIC_FAST_DOCUMENT', 'url': url, 'outcome': 'DOWNLOADED' if rec else 'NOT_FILE'})
        if rec:
            manifest['files'].append(rec)

    if manifest['files']:
        manifest['status'] = 'DOWNLOADED_PUBLIC'
    elif v3.CAPTCHA_RE.search(text):
        manifest['status'] = 'CAPTCHA_REQUIRED'
    elif r.status_code in (401, 403) or v3.AUTH_RE.search(text):
        manifest['status'] = 'AUTH_REQUIRED'
    else:
        manifest['status'] = 'GENERIC_PUBLIC_PAGE_UNRESOLVED'


base.ADAPTERS['GR_KHMDHS'] = adapter_greece_robust
base.ADAPTERS['GENERIC_EPPS'] = v2.optimized_epps
base.ADAPTERS['TED_PUBLIC_PAGE_FAST'] = adapter_ted_public_fast

if __name__ == '__main__':
    v2.main()
