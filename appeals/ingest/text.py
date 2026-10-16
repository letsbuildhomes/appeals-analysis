"""Page text: the PDF's own text where it is usable, OCR where it is clearly better.

For each page:

1. Native text from Poppler's `pdftotext -layout`.
2. Usability. Enough clean native text is kept. A sparse or garbled page is
   rendered to measure its ink: nearly none makes it blank; visible content
   without enough text needs OCR; anything else is an OCR candidate.
3. OCR with Tesseract for pages that need it or are candidates.
4. Selection: usable native text wins. OCR wins when native text is missing or
   garbled, or OCR finds much more text. Weak OCR leaves the page unresolved.

Each page ends with one text (or none), its source, a status and the reason.
"""
from dataclasses import dataclass
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

CLEAR_TEXT = 80            # alphanumeric characters that make a page clearly usable
SHORT_TEXT = 20            # enough for a short page with no full-page image
BLANK_INK = 0.0005         # share of dark pixels below which a textless page is blank
INK_SCALE = 512            # long edge, in pixels, of the ink-check rendering
OCR_SCALE = 2200           # long edge for OCR
LARGE_IMAGE = 1000         # an embedded image this big on both sides is a page scan
OCR_MIN_CONFIDENCE = 45
ORIGIN = 'text-v1'


@dataclass
class PageText:
    page: int
    text: str
    source: str | None
    status: str
    reason: str


def metrics(text):
    """(alphanumeric characters, words, bad characters) of a text."""
    alnum = sum(c.isalnum() for c in text)
    words = len(re.findall(r'\b\w+\b', text))
    bad = text.count('�') + sum(ord(c) < 32 and c not in '\n\r\t\f' for c in text)
    return alnum, words, bad


def garbled(alnum, bad):
    return bad > max(5, alnum // 100)


def _run(args, timeout=120):
    result = subprocess.run(args, capture_output=True, timeout=timeout, check=False)
    if result.returncode:
        raise RuntimeError(f'{args[0]} failed: {result.stderr.decode(errors="replace")[-500:]}')
    return result.stdout


def tools_available():
    """Which external tools are installed: Poppler is required, Tesseract only for OCR."""
    return {tool: shutil.which(tool) is not None for tool in ('pdftotext', 'pdftoppm', 'pdfimages', 'pdfinfo', 'tesseract')}


def page_count(pdf):
    info = _run(['pdfinfo', str(pdf)]).decode(errors='replace')
    match = re.search(r'^Pages:\s+(\d+)', info, re.M)
    return int(match.group(1)) if match else 0


def native_pages(pdf):
    """Native text of every page, split on form feeds."""
    text = _run(['pdftotext', '-layout', '-enc', 'UTF-8', str(pdf), '-']).decode('utf-8', errors='replace')
    pages = text.split('\f')
    if pages and not pages[-1].strip():
        pages = pages[:-1]
    return pages


def ink_ratio(pdf, page):
    """Share of dark pixels on a small grayscale rendering of the page."""
    data = _run(['pdftoppm', '-f', str(page), '-l', str(page), '-scale-to', str(INK_SCALE), '-gray', str(pdf)])
    header = re.match(rb'P5\s+(\d+)\s+(\d+)\s+(\d+)\s', data)
    if not header:
        return None
    pixels = data[header.end():]
    return sum(p < 245 for p in pixels) / max(len(pixels), 1)


def large_images(pdf):
    """Pages with an embedded image at least LARGE_IMAGE pixels on both sides."""
    listing = _run(['pdfimages', '-list', str(pdf)]).decode(errors='replace').splitlines()[2:]
    pages = set()
    for line in listing:
        parts = line.split()
        if len(parts) >= 5 and parts[0].isdigit() and parts[3].isdigit() and parts[4].isdigit():
            if min(int(parts[3]), int(parts[4])) >= LARGE_IMAGE:
                pages.add(int(parts[0]))
    return pages


def usability(text, ink, scanned):
    """native_ok | blank | ocr_needed | ocr_candidate, with a reason."""
    alnum, _, bad = metrics(text)
    if garbled(alnum, bad):
        return 'ocr_candidate', 'suspicious native characters'
    if alnum >= CLEAR_TEXT:
        return 'native_ok', 'substantial native text'
    if alnum >= SHORT_TEXT and not scanned:
        return 'native_ok', 'short native text, no page scan'
    if ink is None:
        return 'ocr_candidate', 'sparse page could not be rendered'
    if alnum == 0 and ink < BLANK_INK:
        return 'blank', 'no text or visible marks'
    if alnum == 0 or scanned:
        return 'ocr_needed', 'visible content without enough native text'
    return 'ocr_candidate', 'short text with visible content'


def ocr_page(pdf, page):
    """(text, mean confidence) from Tesseract."""
    with tempfile.TemporaryDirectory() as tmp:
        stem = Path(tmp) / 'page'
        _run(['pdftoppm', '-f', str(page), '-l', str(page), '-scale-to', str(OCR_SCALE), '-gray', '-png',
              '-singlefile', str(pdf), str(stem)])
        image = stem.with_suffix('.png')
        text = _run(['tesseract', str(image), 'stdout', '-l', 'eng', '--psm', '3'], timeout=300).decode(errors='replace')
        tsv = _run(['tesseract', str(image), 'stdout', '-l', 'eng', '--psm', '3', 'tsv'], timeout=300).decode(errors='replace')
    confidences = [float(row.split('\t')[10]) for row in tsv.splitlines()[1:]
                   if len(row.split('\t')) > 11 and row.split('\t')[11].strip() and float(row.split('\t')[10]) >= 0]
    return text, (sum(confidences) / len(confidences) if confidences else None)


def word_coverage(ocr, native):
    """Share of OCR words also present in the native text."""
    ocr_words = re.findall(r'[a-z0-9]{2,}', ocr.casefold())
    native_words = set(re.findall(r'[a-z0-9]{2,}', native.casefold()))
    return sum(w in native_words for w in ocr_words) / len(ocr_words) if ocr_words else 0.0


def select(page, decision, native, ocr=None, confidence=None):
    """Choose one text for a page."""
    if decision == 'native_ok':
        return PageText(page, native, 'native', 'usable', 'native text is usable')
    if decision == 'blank':
        return PageText(page, '', None, 'blank', 'no text or visible marks')
    if ocr is None:
        return PageText(page, '', None, 'unresolved', 'OCR not available')
    o_alnum, o_words, o_bad = metrics(ocr)
    if o_alnum < 10 or o_words < 2 or confidence is None or confidence < OCR_MIN_CONFIDENCE or garbled(o_alnum, o_bad):
        return PageText(page, '', None, 'unresolved', 'OCR too weak')
    n_alnum, _, n_bad = metrics(native)
    if n_alnum < SHORT_TEXT or garbled(n_alnum, n_bad):
        return PageText(page, ocr, 'ocr', 'usable', 'native text missing or garbled')
    if o_alnum >= n_alnum + max(40, n_alnum // 2):
        return PageText(page, ocr, 'ocr', 'usable', 'OCR finds much more text')
    if o_alnum <= n_alnum * 1.25 and word_coverage(ocr, native) >= 0.75:
        return PageText(page, native, 'native', 'usable', 'OCR confirms native text')
    return PageText(page, '', None, 'unresolved', 'native and OCR text disagree')


def extract(pdf, ocr_enabled=True):
    """Every page of one PDF as PageText."""
    natives = native_pages(pdf)
    count = max(page_count(pdf), len(natives))
    natives += [''] * (count - len(natives))
    scans = large_images(pdf)
    pages = []
    for number, native in enumerate(natives, 1):
        alnum, _, bad = metrics(native)
        sparse = alnum < CLEAR_TEXT or garbled(alnum, bad)
        ink = ink_ratio(pdf, number) if sparse else None
        decision, _ = usability(native, ink, number in scans)
        ocr, confidence = (None, None)
        if decision in ('ocr_needed', 'ocr_candidate') and ocr_enabled:
            ocr, confidence = ocr_page(pdf, number)
        pages.append(select(number, decision, native, ocr, confidence))
    return pages


def extract_missing(settings, store, log=print):
    """Extract text for every stored document that has no pages yet."""
    todo = [r['sha256'] for r in store.rows(
        'SELECT d.sha256 FROM documents d WHERE NOT EXISTS (SELECT 1 FROM pages p WHERE p.sha256 = d.sha256) ORDER BY 1')]
    ocr_enabled = tools_available()['tesseract']
    if todo and not ocr_enabled:
        log('Tesseract is not installed: pages that need OCR will be marked unresolved.')
    for n, sha in enumerate(todo, 1):
        pages = extract(settings.pdfs / f'{sha}.pdf', ocr_enabled)
        with store.transaction():
            store.add_pages([(sha, p.page, p.text, p.source, p.status, p.reason, ORIGIN) for p in pages])
            store.set_document_pages(sha, len(pages))
        log(f'  {n}/{len(todo)} {sha[:12]}: {len(pages)} pages')
