"""Dockets: which documents belong to which docket number, and each docket's text.

A docket is a case. A document belongs to every docket its heading names; a
decision issued in several dockets belongs in full to each of them. The
rules (docs/PIPELINE.md, "Dockets"):

1. Heading dockets: the numbers after a "Docket No." or "Case No." label in
   the first 3,000 characters of page 1, only when the label begins a column
   of the caption, and not when the line reads on as a sentence (a citation).
2. Listing fallback: a document whose heading names no docket uses its
   listing entry's docket. A listing docket the heading doesn't name never
   makes a docket; it is flagged.
3. Flags, never changes: a heading docket one digit away from the listing's,
   or one filed after the document was posted.
"""
from dataclasses import dataclass
import json
import re

CAPTION_WINDOW = 3000
CONTINUATION_LINES = 4          # lines below a label that may continue its column of numbers

DOCKET = re.compile(
    r"\b(?:(\d{1,3})\s*[-/]\s*(\d{1,2})\s*[-/]\s*(\d{2})[\s}|]*-?[\s}|]*V\s*[a-z]{2,3}\b"   # 128-8-10 Vtec
    r"|(\d{2})\s*-?\s*(ENV|CC|EC|AP)\s*-?\s*(\d{2,6})\b"                                   # 25-ENV-00114
    r"|eo\s*(\d{2})-(\d{2,4})\b)", re.I)                                                   # Supreme Court
LABEL = re.compile(r"(?:Docket|Case)\s+Nos?\.?\s*:?", re.I)
DASHES = re.compile('[‐-―−­﹣－]')
COLUMN_BREAK = re.compile(r"[}|{]| {3,}|\t")


# ---- reading docket numbers ------------------------------------------------

def _normalized(match):
    if match[1]:
        return f'{int(match[1])}-{int(match[2])}-{match[3]} Vtec'
    if match[4]:
        return f'{match[4]}-{match[5].upper()}-{int(match[6]):05d}'
    return f'eo{match[7]}-{int(match[8]):03d}'


def clean(text):
    """Dash variants as hyphens, and OCR damage in docket numbers undone."""
    text = DASHES.sub('-', (text or '').replace(' ', ' '))
    text = re.sub(r'(V\s*tec)(?=\d)', r'\1 ', text, flags=re.I)                     # "Vtec1" footnote markers
    return re.sub(r'\b(\d{2}\s*-?\s*(?:ENV|CC|EC|AP)\s*-?\s*)([0-9Oo]{5})\b',       # letter O for zero
                  lambda m: m[1] + m[2].replace('O', '0').replace('o', '0'), text, flags=re.I)


def dockets_in(text):
    """Every docket-shaped string in a text, normalized, first-seen order."""
    seen = {}
    for match in DOCKET.finditer(clean(text)):
        seen.setdefault(_normalized(match))
    return list(seen)


def is_trial_court(docket):
    """The Environmental Division's own numbers, not the Supreme Court's."""
    return not docket.startswith('eo') and '-AP-' not in docket


# ---- rule 1: heading dockets ------------------------------------------------

def _column(lines, index, label):
    """The rest of the label's line, and the following lines from the label's column."""
    parts = [lines[index][label.end():]]
    for line in lines[index + 1:index + 1 + CONTINUATION_LINES]:
        if LABEL.search(line):
            break
        parts.append(line[max(0, label.start() - 2):])
    return '\n'.join(parts)


def _numbers_after_label(segment):
    """Docket numbers at the start of a segment; stops at other words. Returns (dockets, end)."""
    found, end = [], 0
    for match in DOCKET.finditer(segment):
        gap = segment[end:match.start()]
        if end == 0 and gap.strip(' \t\r\n|{}:'):
            break
        # a parenthetical note between stacked numbers belongs to the caption
        if end and re.search(r'[A-Za-z]{3,}', re.sub(r'Docket|Nos?\b|and|\([^()]*\)', '', gap)):
            break
        found.append(_normalized(match))
        end = match.end()
    return found, end


def _reads_as_sentence(segment, end, previous_line, at_margin):
    """A citation: words follow the numbers in the same column, or (at the left margin)
    the previous line ends mid-sentence with a comma."""
    line_end = segment.find('\n')
    line_end = len(segment) if line_end < 0 else line_end
    rest = segment[end:line_end] if end <= line_end else ''
    rest = re.split(r' {3,}|\t|[}|]', rest)[0]
    if re.search(r'[A-Za-z]{3,}', re.sub(r'\bV\s*tec\b|\band\b|\bNos?\b', '', rest, flags=re.I)):
        return True
    return at_margin and previous_line.rstrip().endswith(',')


def heading_dockets(page_one):
    """Rule 1: the dockets a document's heading names."""
    lines = clean((page_one or '')[:CAPTION_WINDOW]).splitlines()
    seen = {}
    for index, line in enumerate(lines):
        for label in LABEL.finditer(line):
            if COLUMN_BREAK.split(line[:label.start()])[-1].strip():
                continue                                    # the label is inside running text
            if re.search(r'Supreme\s+Court\s*$', line[:label.start()], re.I):
                continue
            segment = _column(lines, index, label)
            found, end = _numbers_after_label(segment)
            previous = next((prior for prior in reversed(lines[:index]) if prior.strip()), '')
            at_margin = not line[:label.start()].strip() and label.start() < 8
            if found and _reads_as_sentence(segment, end, previous, at_margin):
                continue
            for docket in found:
                if is_trial_court(docket):
                    seen.setdefault(docket)
    return list(seen)


# ---- rules 2 and 3: membership and flags ------------------------------------

def filing_year(docket):
    """The year a docket number encodes."""
    if m := re.fullmatch(r'\d+-\d+-(\d\d) Vtec', docket):
        year = int(m[1])
        return 2000 + year if year < 70 else 1900 + year
    if m := re.fullmatch(r'(\d\d)-[A-Z]+-\d+', docket):
        return 2000 + int(m[1])
    return None


def filing_period(docket):
    """When a docket number says the appeal was filed: "YYYY-MM" for 128-8-10 Vtec (sequence-month-year),
    "YYYY" for 25-ENV-00114 (year-ENV-sequence), else None."""
    year = filing_year(docket)
    if year is None:
        return None
    if m := re.fullmatch(r'\d+-(\d+)-\d\d Vtec', docket):
        month = int(m[1])
        return f'{year}-{month:02d}' if 1 <= month <= 12 else str(year)
    return str(year)


def _one_part_apart(a, b):
    na, nb = re.findall(r'\d+', a), re.findall(r'\d+', b)
    same_shape = re.sub(r'\d+', '#', a) == re.sub(r'\d+', '#', b)
    return same_shape and len(na) == len(nb) and sum(x != y for x, y in zip(na, nb)) == 1


def assign(page_one, listing_text, posted_year):
    """A document's dockets [(docket, basis)] and flags, from its page 1 and listing dockets."""
    heading = heading_dockets(page_one)
    listing = [d for d in dockets_in(listing_text or '') if is_trial_court(d)]
    flags = []
    if heading:
        dockets = [(d, 'heading') for d in heading]
        for d in listing:
            if d not in heading:
                near = [h for h in heading if _one_part_apart(h, d)]
                flags.append(f'typo_like:{d}~{near[0]}' if near else f'listing_only:{d}')
    elif listing:
        dockets = [(d, 'listing') for d in listing]
        flags.append('no_heading_docket')
    else:
        dockets = []
        flags.append('no_docket')
    for docket, _ in dockets:
        year = filing_year(docket)
        if year and posted_year and year > posted_year:
            flags.append(f'filed_after_posting:{docket}')
    return dockets, flags


def assign_all(store, log=print):
    """Recompute every document's dockets from page 1 and its listing entries."""
    docs = store.rows("""
        SELECT i.sha256, i.posted, i.listing_dockets, p.text AS page_one
        FROM document_info i LEFT JOIN pages p ON p.sha256 = i.sha256 AND p.page = 1""")
    with store.transaction():
        for doc in docs:
            listing = '; '.join(json.loads(doc['listing_dockets'] or '[]'))
            year = int(doc['posted'][:4]) if doc['posted'] else None
            dockets, flags = assign(doc['page_one'] or '', listing, year)
            if not dockets:
                dockets = [(f'pdf-{doc["sha256"][:12]}', 'none')]   # a document with no docket stands alone
            store.set_document_dockets(doc['sha256'], dockets, flags)
    count = store.value('SELECT count(DISTINCT docket) FROM document_dockets')
    log(f'{len(docs)} documents in {count} dockets')


# ---- docket text -------------------------------------------------------------

@dataclass
class DocketDocument:
    n: int
    sha256: str
    title: str
    posted: str
    dockets: list
    pages: list            # [{'page', 'text', 'source', 'status'}]


@dataclass
class DocketText:
    number: str
    documents: list
    text: str

    @property
    def chars(self):
        return len(self.text)

    def page_text(self, doc, page):
        for d in self.documents:
            if d.n == doc:
                for p in d.pages:
                    if p['page'] == page:
                        return p['text']
        return None


def _attr(value):
    return str(value).replace('&', '&amp;').replace('"', '&quot;')


def render(number, documents):
    parts = [f'<docket number="{_attr(number)}">']
    for d in documents:
        parts.append(f'<document n="{d.n}" title="{_attr(d.title)}" posted="{d.posted}" '
                     f'dockets="{_attr("; ".join(d.dockets))}">')
        for p in d.pages:
            if p['status'] == 'usable':
                parts.append(f'<page n="{p["page"]}" source="{p["source"]}">\n{p["text"].rstrip()}\n</page>')
            else:
                parts.append(f'<page n="{p["page"]}" status="{p["status"]}">[No selected text: {p["status"]}]</page>')
        parts.append('</document>')
    parts.append('</docket>')
    return '\n'.join(parts)


def docket_text(store, number):
    """The docket's documents in posting order (then hash), rendered with document and page markers."""
    docs = store.rows("""
        SELECT i.sha256, i.title, i.posted,
               (SELECT json_group_array(docket ORDER BY docket) FROM document_dockets x WHERE x.sha256 = i.sha256)
               AS dockets
        FROM document_dockets dd JOIN document_info i ON i.sha256 = dd.sha256
        WHERE dd.docket = ? ORDER BY i.posted NULLS LAST, i.sha256""", (number,))
    if not docs:
        return None
    documents = []
    for n, doc in enumerate(docs, 1):
        pages = store.rows('SELECT page, text, source, status FROM pages WHERE sha256 = ? ORDER BY page', (doc['sha256'],))
        documents.append(DocketDocument(n, doc['sha256'], doc['title'] or '', doc['posted'] or '',
                                        json.loads(doc['dockets'] or '[]') or [number], pages))
    return DocketText(number, documents, render(number, documents))


def list_dockets(store, search=None, limit=None):
    """Dockets with their document count, first and last posting dates and characters of text."""
    sql = """
        SELECT dd.docket AS number, count(*) AS documents, min(i.posted) AS first_posted, max(i.posted) AS last_posted,
               sum((SELECT sum(length(text)) FROM pages p WHERE p.sha256 = dd.sha256)) AS chars,
               (SELECT i2.title FROM document_dockets d2 JOIN document_info i2 ON i2.sha256 = d2.sha256
                WHERE d2.docket = dd.docket ORDER BY i2.posted NULLS LAST LIMIT 1) AS title
        FROM document_dockets dd JOIN document_info i ON i.sha256 = dd.sha256
        {where} GROUP BY dd.docket ORDER BY min(i.posted) DESC, dd.docket {limit}"""
    params = ()
    where = ''
    if search:
        where = 'WHERE dd.docket LIKE ? OR i.title LIKE ?'           # case-insensitive in SQLite
        params = (f'%{search}%', f'%{search}%')
    return store.rows(sql.format(where=where, limit=f'LIMIT {int(limit)}' if limit else ''), params)
