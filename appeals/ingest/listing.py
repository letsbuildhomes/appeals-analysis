"""The court's opinions listing: crawl it into a snapshot folder, and parse saved pages.

A snapshot is a folder of the listing's HTML pages exactly as served
(`page_0000.html`, …). Parsing reads one entry per listed document: its title,
posting date, division, docket text and `/media/<id>` link. A posting date
outside the plausible range (appeals.dates) is dropped, and the entry's note
keeps the date as listed.
"""
from dataclasses import dataclass
from datetime import date, datetime, timezone
import html
from pathlib import Path
import re
import time

import httpx

from appeals import dates

ROW = re.compile(r'<article class="views-row[^"]*">(.*?)</article>', re.S)
LINK = re.compile(r'<a href="(/media/\d+)"[^>]*>(.*?)</a>', re.S)
POSTED = re.compile(r'<time datetime="(\d{4}-\d{2}-\d{2})')
DIVISION = re.compile(r'field-document-court-division">\s*<span class="field-content">(.*?)</span>', re.S)
DOCKET = re.compile(r'field-document-number">\s*<span class="field-content">(.*?)</span>', re.S)
SITE = 'https://www.vtcourts.gov'


@dataclass(frozen=True)
class Entry:
    snapshot: str
    page: int
    ordinal: int
    media_url: str
    title: str
    posted: date | None
    division: str
    docket: str | None
    note: str | None = None


def _text(fragment):
    return ' '.join(html.unescape(re.sub(r'<[^>]+>', ' ', fragment)).split())


def _posted(listed):
    """The posting date and a note: (date, None), or (None, why it was dropped) when it is implausible."""
    if listed is None:
        return None, None
    why = dates.problem(listed)
    return (None, f'posting date {listed} dropped: {why}') if why else (date.fromisoformat(listed), None)


def parse_page(markup, snapshot, page):
    """Entries on one listing page, in order."""
    entries = []
    for ordinal, row in enumerate(ROW.findall(markup)):
        link = LINK.search(row)
        if not link:
            continue
        posted = POSTED.search(row)
        division = DIVISION.search(row)
        docket = DOCKET.search(row)
        posted, note = _posted(posted.group(1) if posted else None)
        entries.append(Entry(
            snapshot=snapshot, page=page, ordinal=ordinal,
            media_url=SITE + link.group(1),
            title=_text(link.group(2)),
            posted=posted,
            division=_text(division.group(1)) if division else '',
            docket=_text(docket.group(1)) or None if docket else None,
            note=note,
        ))
    return entries


def has_next_page(markup):
    return 'pager__item--next' in markup


def read_snapshot(folder):
    """Every entry in a saved snapshot folder."""
    folder = Path(folder)
    entries = []
    for path in sorted(folder.glob('page_*.html')):
        page = int(path.stem.split('_')[1])
        entries.extend(parse_page(path.read_text(encoding='utf-8'), folder.name, page))
    return entries


def reparse_all(settings, store, log=print):
    """Parse every saved snapshot again into the store, so parser fixes reach entries already stored."""
    folders = sorted(p for p in settings.listings.iterdir() if p.is_dir()) if settings.listings.exists() else []
    entries = [e for folder in folders for e in read_snapshot(folder)]
    with store.transaction():
        store.add_listing_entries(entries)
    log(f'Listing: {len(entries)} entries from {len(folders)} snapshots, '
        f'{sum(e.note is not None for e in entries)} with a note')


def crawl(settings, max_pages=None):
    """Save the live listing into a new snapshot folder; return the folder.

    One request at a time with a pause between them; stops at the last page.
    """
    name = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    folder = settings.listings / name
    folder.mkdir(parents=True)
    headers = {'User-Agent': settings.user_agent}
    with httpx.Client(headers=headers, timeout=60, follow_redirects=True) as client:
        page = 0
        while max_pages is None or page < max_pages:
            url = settings.listing_url + (f'&page={page}' if page else '')
            response = _get(client, url)
            (folder / f'page_{page:04d}.html').write_text(response.text, encoding='utf-8')
            if not has_next_page(response.text):
                break
            page += 1
            time.sleep(settings.pause_seconds)
    return folder


def _get(client, url, attempts=4):
    """GET with backoff on rate limits and server errors; stop on anything else."""
    for attempt in range(attempts):
        response = client.get(url)
        if response.status_code in (429, 500, 502, 503, 504) and attempt < attempts - 1:
            time.sleep(min(int(response.headers.get('retry-after', 0) or 0) or 2 ** (attempt + 2), 300))
            continue
        response.raise_for_status()
        return response
    raise RuntimeError(f'Gave up on {url}')
