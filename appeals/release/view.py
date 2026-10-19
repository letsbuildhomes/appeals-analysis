"""A docket as a reader sees it on its own page: plain labels and values, grouped by topic, each with the
passages of the decisions behind it.

Like the rest of the release code this reads the release's data dictionary
rather than naming fields, so a new field shows up on the page by itself. The
exceptions are presentation only: HEADLINE picks the few facts shown first,
and duration and unit changes, whose columns only make sense together, are
written out as sentences when they are present.
"""
import re

from appeals.graph.values import NOT_STATED
from appeals.release.read import QueryError, docket_slug

HEADLINE = ['municipality', 'town_decision', 'court_result', 'how_ended', 'units_added_proposed',
            'units_added_court_approved', 'duration']
QUIET = {'no', 'not at issue', 'not decided', 'none', NOT_STATED}     # set items that say nothing happened
MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October',
          'November', 'December']


def page_address(base_url, version, number):
    """Where a docket's page lives: {base_url}/{version}/{slug}."""
    return f'{base_url.rstrip("/")}/{version}/{docket_slug(number)}'


def say_date(value, precision='day'):
    """2007-07-18 as July 18, 2007; a month as June 2004; a year as 2004."""
    if not value:
        return None
    parts = str(value)[:10].split('-')
    try:
        if precision == 'year' or len(parts) == 1:
            return parts[0]
        month = MONTHS[int(parts[1]) - 1]
        if precision == 'month' or len(parts) == 2:
            return f'{month} {parts[0]}'
        return f'{month} {int(parts[2])}, {parts[0]}'
    except (ValueError, IndexError):
        return str(value)


def _years(days):
    if days < 60:
        return None
    if days < 365:
        return f'about {round(days / 30.4)} months'
    years = days / 365.25
    return 'about 1 year' if years < 1.5 else f'about {years:.1f}'.rstrip('0').rstrip('.') + ' years'


def _sentence(text):
    text = str(text)
    return text[:1].upper() + text[1:]


def _lower(text):
    text = str(text or '')
    return text[:1].lower() + text[1:] if text[1:2].islower() else text


def _known(value):
    return value is not None and value != NOT_STATED


def _item_labels(notes):
    """Short names for a set's items, from the note that lists them ("character = character and fit; …")."""
    for note in notes or []:
        pairs = re.findall(r'(\w+) = ([^;]+?)(?:;|\.$|$)', note)
        if len(pairs) >= 2:
            return {k: v.strip() for k, v in pairs}
    return {}


def _heading(name):
    return _sentence(name.replace('_', ' '))


class _Dictionary:
    """The release's data dictionary, indexed for building a page."""

    def __init__(self, release):
        self.tables = {t['name']: t for t in release.meta['tables']}
        appeals = self.tables['appeals']['columns']
        self.columns = {c['name']: c for c in appeals}
        self.fields = {}                                  # field -> its columns on appeals, in order
        for c in appeals:
            if c.get('field'):
                self.fields.setdefault(c['field'], []).append(c)
        self.long = {}                                    # field -> its long tables
        for t in release.meta['tables']:
            if t.get('field') and not t.get('out_of_scope'):
                self.long.setdefault(t['field'], []).append(t)
        self.topics = release.meta['about']['topics']

    def label(self, field):
        cols = self.fields.get(field) or []
        if cols:
            return cols[0].get('label') or _heading(field)
        tables = self.long.get(field) or []
        return tables[0].get('label') if tables else _heading(field)

    def topic(self, field):
        cols = self.fields.get(field) or self.long.get(field) or [{}]
        return cols[0].get('topic')

    def column_label(self, name):
        c = self.columns.get(name)
        return c.get('label') if c and c.get('label') else _heading(name)


def _plain(text):
    """Reader text without references to column names, such as "(judgment_central yes)"."""
    return re.sub(r' \((?:[a-z]+_[a-z_]+)(?: [a-z]+)?\)', '', text)


def _value(column, value):
    """A column's value for reading: {value, meaning, known}."""
    if not _known(value):
        return {'value': 'Not stated', 'known': False}
    out = {'known': True}
    if isinstance(value, bool):
        out['value'] = 'Yes' if value else 'No'
    elif isinstance(value, int):
        out['value'] = f'{value:,}'
    else:
        out['value'] = _sentence(value)
    meaning = (column.get('options') or {}).get(value) if isinstance(value, str) else None
    if meaning and meaning.rstrip('.').casefold() != str(value).casefold():     # not just "No." for no
        out['meaning'] = _plain(meaning)
    return out


def _duration(d, answers):
    kind, days = answers.get('duration_kind'), answers.get('duration_days')
    if days is None or kind in (None, 'unknown', NOT_STATED):
        return {'value': 'Not known', 'known': False,
                'meaning': 'An end of the case is missing from the decisions, so its length is not known.'}

    def end(side):
        date = say_date(answers.get(f'duration_{side}_date'), answers.get(f'duration_{side}_date_precision'))
        source = answers.get(f'duration_{side}_from')
        source = _lower(d.column_label(source)) if source else None
        inferred = ', inferred' if answers.get(f'duration_{side}_inferred') else ''
        return f'{date} ({source}{inferred})' if source else date

    spoken = f'{days:,} days' + (f' ({_years(days)})' if _years(days) else '')
    out = {'value': f'At least {spoken}' if kind == 'at least' else spoken, 'known': True,
           'detail': f'From {end("start")} to {end("end")}.', 'days': days, 'bound': kind}
    meaning = (d.columns.get('duration_kind', {}).get('options') or {}).get(kind)
    if meaning:
        out['meaning'] = meaning
    return out


def _unit_change(answers):
    parts, known = [], False
    for side, against in (('town', "the town's decision"), ('application', 'the application')):
        n = answers.get(f'unit_change_vs_{side}')
        direction = answers.get(f'unit_change_direction_vs_{side}')
        if n is not None:
            known = True
            parts.append(f'{n:+,} against {against}' if n else f'no change against {against}')
        elif _known(direction):
            known = True
            parts.append(f'{direction} than {against}' if direction != 'same' else f'same as {against}')
    if not known:
        return {'value': 'Not stated', 'known': False}
    return {'value': _sentence('; '.join(parts)), 'known': True,
            'meaning': 'Units the court approved, compared with the town and with the application. Positive means '
                       'the court allowed more.'}


def _appellant_mix(answers, lists):
    n = answers.get('appellant_mix_count')
    roles = _counts(None, lists.get('appellant_mix_roles') or [])
    lawyers = _counts(None, lists.get('appellant_mix_representation') or [])
    if n is None and not roles:
        return {'value': 'Not stated', 'known': False}
    out = {'value': (f'{n:,} appellant{"s" if n != 1 else ""}' if n is not None else 'Not every appellant named')
           + (f': {roles}' if roles else ''), 'known': True,
           'meaning': 'Who appealed, with groups of neighbors counted as neighbors.'}
    of = answers.get('appellant_mix_representation_of')
    if lawyers:
        out['detail'] = f'Representation{f" (of {of:,} appellants asked about)" if of else ""}: {lawyers}.'
    return out


def _generic(d, field, columns, answers):
    """A field's columns as one value: the main column, its date precision, and any other columns as details."""
    main = next((c for c in columns if c['name'] == field), columns[0])
    precision = answers.get(f'{main["name"]}_precision') if f'{main["name"]}_precision' in d.columns else None
    raw = answers.get(main['name'])
    if precision is not None or (f'{main["name"]}_precision' in d.columns and raw is None):
        out = {'value': say_date(raw, precision) or 'Not stated', 'known': raw is not None, 'date': raw,
               'precision': precision}
    else:
        out = _value(main, raw)
    extra = [c for c in columns if c is not main and c['name'] != f'{main["name"]}_precision'
             and not c['name'].endswith('_count')]
    details = [f'{_heading(c["name"].removeprefix(field + "_"))}: {_value(c, answers.get(c["name"]))["value"]}'
               for c in extra if _known(answers.get(c['name']))]
    if details:
        out['detail'] = '; '.join(details) + '.'
    return out


def _counts(table, rows):
    """A counts-by-option table as one line: "2 applicant or owner, 1 neighbor"."""
    return ', '.join(f'{r["count"]:,} {r["option"]}' if r.get('count') is not None else f'{r["option"]} (count '
                     'not stated)' for r in rows)


def _list(table, rows):
    """A list table: its columns (without the docket and ordinal) and rows of readable values."""
    columns = [c for c in table['columns'] if c['name'] not in ('docket', 'ordinal')]
    return {'columns': [_heading(c['name']) for c in columns],
            'rows': [[_value(c, r.get(c['name']))['value'] for c in columns] for r in rows]}


def _sets(tables, lists):
    """Yes/no or choice sets that share their items (such as the judgment standards: how far each got, the result,
    a condition) as one grid: a row per item that something happened to, and the quiet items named apart."""
    labels = {}
    for t in tables:
        labels.update(_item_labels(t.get('notes')))
    answers = {t['name']: {r['item']: r['answer'] for r in lists.get(t['name'], [])} for t in tables}
    items = list(dict.fromkeys(i for t in tables for i in answers[t['name']]))
    meanings = {}
    for t in tables:
        meanings.update((t['columns'][1].get('options') or {}) if len(t['columns']) > 1 else {})
    first = answers[tables[0]['name']]
    active = [i for i in items if first.get(i) not in QUIET]
    quiet = [i for i in items if first.get(i) in QUIET]
    short = lambda t: t['label'].split(': ', 1)[-1] if ': ' in t['label'] else t['label']   # noqa: E731
    return {'kind': 'grid', 'columns': [_sentence(short(t)) for t in tables],
            'rows': [{'item': _sentence(labels.get(i, i)), 'meaning': _plain(meanings.get(i) or ''),
                      'answers': [_sentence(answers[t['name']].get(i) or '—') for t in tables]} for i in active],
            'quiet': [labels.get(i, i) for i in quiet],
            'quiet_answer': first.get(quiet[0]) if quiet else None}


def _quotes(quotes, field):
    seen, out = set(), []
    for q in quotes:
        key = (q['document'], q['page'], q['quote'])
        if q['field'] == field and key not in seen:
            seen.add(key)
            out.append({'document': q['document'], 'page': q['page'], 'quote': q['quote']})
    return out


def docket_page(release, number, current_id=None, base_url=''):
    """Everything a docket's page shows, or a {'found': False} entry."""
    try:
        entry = release.docket([number])['dockets'][0]
    except QueryError:
        return {'found': False, 'docket': number}
    head = {'version': release.version, 'built': release.built, 'current': release.id == current_id,
            'release': release.id, 'has_pages': release.has_pages()}
    if not entry['found']:
        return {**head, 'found': False, 'docket': number}
    d = _Dictionary(release)
    answers, lists, quotes = entry['answers'], entry.get('lists', {}), entry['quotes']
    documents = entry['documents']
    title = next((doc['title'] for doc in documents if doc.get('title')), None)

    facts = {}                       # field -> its fact, in column order, then the long tables' fields
    for field, columns in d.fields.items():
        if not any(c['name'] in answers for c in columns):
            continue
        if field in d.long and all(c['name'].endswith('_count') for c in columns):
            continue                                       # the list itself is shown instead of its count
        if field == 'duration':
            shown = _duration(d, answers)
        elif field == 'unit_change':
            shown = _unit_change(answers)
        elif field == 'appellant_mix':
            shown = _appellant_mix(answers, lists)
        else:
            shown = _generic(d, field, columns, answers)
        counts = [t for t in d.long.get(field, []) if lists.get(t['name'])]   # counts by option, as lines
        if counts and field != 'appellant_mix':
            shown['detail'] = ' · '.join(filter(None, [shown.get('detail'), *(_counts(t, lists[t['name']])
                                                                             for t in counts)]))
        facts[field] = {'field': field, 'label': d.label(field), **shown, 'quotes': _quotes(quotes, field)}

    blocks = {}                      # field -> a list or grid block
    for field, tables in d.long.items():
        present = [t for t in tables if t['name'] in lists]
        if not present or field in facts:
            continue
        kinds = {len(t['columns']) for t in present}
        if all([c['name'] for c in t['columns']][1:3] == ['item', 'answer'] for t in present) and kinds == {3}:
            continue                                       # sets are gathered below, by topic
        rows = lists[present[0]['name']]
        blocks[field] = {'field': field, 'label': d.label(field), 'kind': 'list', **_list(present[0], rows),
                         'empty': not rows, 'quotes': _quotes(quotes, field),
                         'count': answers.get(f'{field}_count')}
        if answers.get(f'{field}_count') is None and not rows:
            blocks[field]['not_stated'] = True

    sets = [t for t in d.tables.values() if t.get('field') and not t.get('out_of_scope') and t['name'] in lists
            and [c['name'] for c in t['columns']][1:3] == ['item', 'answer']]
    by_items = {}
    for t in sets:
        by_items.setdefault((d.topic(t['field']), tuple(r['item'] for r in lists[t['name']])), []).append(t)
    for tables in by_items.values():
        field = tables[0]['field']
        label = tables[0]['label'].split(':')[0] if len(tables) > 1 else tables[0]['label']
        quoted = list({(q['document'], q['page'], q['quote']): q for t in tables
                       for q in _quotes(quotes, t['field'])}.values())
        blocks[field] = {'field': field, 'label': label, **_sets(tables, lists), 'quotes': quoted}

    sections = []
    for topic in d.topics:
        fields = [f for f in [*d.fields, *d.long] if d.topic(f) == topic]
        items = [facts.get(f) or blocks.get(f) for f in dict.fromkeys(fields) if f in facts or f in blocks]
        if items:
            sections.append({'topic': topic, 'items': items})

    headline = [{'field': f, 'label': facts[f]['label'], 'value': facts[f]['value'], 'known': facts[f]['known']}
                for f in HEADLINE if f in facts]
    out = {**head, 'found': True, 'docket': entry['docket'], 'slug': docket_slug(entry['docket']),
           'in_scope': entry['in_scope'], 'note': entry.get('note'), 'title': title,
           'headline': headline, 'sections': sections, 'timeline': _timeline(d, answers, documents),
           'documents': documents,
           'linked': [{**link, 'slug': docket_slug(link['linked_docket'])} for link in entry['linked_dockets']]}
    if base_url:
        out['address'] = page_address(base_url, release.version, entry['docket'])
    return out


def _timeline(d, answers, documents):
    """The dated events, oldest first: each dated fact, and each document as it was posted."""
    events = []
    for field, columns in d.fields.items():
        main = next((c for c in columns if c['name'] == field), None)
        if main is None or f'{field}_precision' not in d.columns or not answers.get(field):
            continue
        events.append({'date': str(answers[field]), 'precision': answers.get(f'{field}_precision'),
                       'say': say_date(answers[field], answers.get(f'{field}_precision')), 'label': d.label(field),
                       'kind': 'fact'})
    for doc in documents:
        if doc.get('posted'):
            events.append({'date': str(doc['posted']), 'precision': 'day', 'say': say_date(doc['posted']),
                           'label': f'Document {doc["document"]} posted', 'kind': 'document',
                           'document': doc['document']})
    return sorted(events, key=lambda e: (e['date'], e['kind'] != 'fact'))


def appeals_list(release):
    """Every appeal in scope with the few facts a list shows, for finding a docket's page."""
    wanted = [c for c in ('municipality', 'town_decision', 'court_result', 'how_ended')
              if c in {col['name'] for t in release.meta['tables'] if t['name'] == 'appeals' for col in t['columns']}]
    picks = ''.join(f', a.{c}' for c in wanted)
    rows = release._rows(release.data, f"""
        SELECT a.docket, a.first_posted, a.last_posted, a.documents{picks},
               (SELECT title FROM documents d WHERE d.docket = a.docket AND title IS NOT NULL
                ORDER BY document LIMIT 1) AS title
        FROM appeals a ORDER BY a.last_posted DESC NULLS LAST, a.docket""", [])
    return {'version': release.version, 'built': release.built, 'columns': wanted,
            'appeals': [{**r, 'slug': docket_slug(r['docket'])} for r in rows]}
