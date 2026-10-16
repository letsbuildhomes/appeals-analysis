"""Download each listed PDF once and store it under the SHA-256 of its bytes.

A listing entry whose media URL is already in `downloads` is skipped, so a new
snapshot fetches only new documents. Files land in `data/pdfs/<sha>.pdf`.
"""
from datetime import datetime, timezone
import hashlib
import time

import httpx

MAX_BYTES = 100 * 1024 * 1024


def sha256_of(data):
    return hashlib.sha256(data).hexdigest()


def store_pdf(settings, store, data):
    """Save PDF bytes under their hash and register the document. Returns the hash."""
    if not data.startswith(b'%PDF'):
        raise ValueError('not a PDF')
    if len(data) > MAX_BYTES:
        raise ValueError(f'PDF too large: {len(data)} bytes')
    sha = sha256_of(data)
    path = settings.pdfs / f'{sha}.pdf'
    if not path.exists():
        settings.pdfs.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    if store.value('SELECT count(*) FROM documents WHERE sha256 = ?', (sha,)) == 0:
        store.add_document(sha, len(data), None)
    return sha


def pending_media(store):
    """Media URLs listed in any snapshot but never downloaded."""
    return [r['media_url'] for r in store.rows(
        'SELECT DISTINCT e.media_url FROM listing_entries e '
        'LEFT JOIN downloads d ON d.media_url = e.media_url WHERE d.media_url IS NULL ORDER BY 1')]


def download_new(settings, store, limit=None, log=print):
    """Fetch every pending PDF, one at a time with a pause between requests."""
    todo = pending_media(store)[:limit]
    log(f'{len(todo)} PDFs to download')
    headers = {'User-Agent': settings.user_agent}
    with httpx.Client(headers=headers, timeout=120, follow_redirects=True) as client:
        for n, url in enumerate(todo, 1):
            response = client.get(url)
            if response.status_code == 403:
                raise RuntimeError('The court site refused the request (403); stopping.')
            response.raise_for_status()
            try:
                sha = store_pdf(settings, store, response.content)
            except ValueError as error:
                log(f'  skipped {url}: {error}')
                continue
            store.add_download(url, str(response.url), sha, datetime.now(timezone.utc))
            log(f'  {n}/{len(todo)} {sha[:12]} {url}')
            time.sleep(settings.pause_seconds)
