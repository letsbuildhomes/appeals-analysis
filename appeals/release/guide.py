"""What a release says about itself: an overview and column descriptions.

These read only a release's release.json, never its `internal` section, so
they describe the data a reader can query: its version, what it covers, how it
was made and how far to trust it, and what each column means. How the
pipeline settled any one answer is not part of the release's public face. The
MCP tools and the public site's API serve these as they are.
"""
from appeals.release.read import LIMITS

HOW_TO_WORK = [
    'Read this overview first. Then use describe on the tables, topics or columns you need: it gives each '
    'column\'s meaning, options, notes, a profile of what the data holds, and query tips.',
    'Every question is about the appeals in scope unless it says otherwise: count from the appeals table and the '
    'tables that list their details. Reach for the all_ tables only when the question is about dockets out of '
    'scope or the court\'s whole caseload.',
    'Always say how many appeals you counted and how many were "not stated". Keep "not stated" (and NULL) separate '
    'from "no" and from zero, and give shares of the known answers next to the number known.',
    'Before adding up units or lots, check docket_links: appeals that share a decision may describe the same project.',
    'Use docket to read a few dockets in full, with the passages of the decisions behind each answer and links to '
    'the PDFs. It is for individual cases, not for bulk analysis.',
    'Present the answers as what the decisions show. For how the data was made and how reliable it is, use '
    'how_it_was_made and how_reliable here rather than speculating.',
    'Cite the version with any figure, such as "v0.0.1".',
]
SQL_NOTES = ('DuckDB SQL: one SELECT per query (WITH, FROM-first, SUMMARIZE and DESCRIBE work). Useful: median(), '
             'quantile_cont(x, 0.9), count(*) FILTER (WHERE …), GROUP BY ALL, EXISTS, date_diff(), list functions. '
             'Identifiers are case-insensitive.')


def _public(table):
    return not table.get('out_of_scope')


def version(release, current_id=None):
    """How readers name the data: its version and the day it was built."""
    out = {'version': release.version, 'built': release.built}
    if current_id is not None:
        out['current'] = release.id == current_id
    return out


def overview(release, current_id=None):
    """Start here: what the data is, what it covers, how it was made, how reliable it is, its tables and the
    conventions."""
    m = release.meta
    about = m['about']
    p = m['population']
    coverage = {'appeals_in_scope': p['in_scope'], 'dockets_read': p['dockets'], 'out_of_scope': p['out_of_scope']}
    if p.get('not_determined'):
        coverage['not_determined'] = p['not_determined']
    out = {
        'data': version(release, current_id),
        'what_this_is': about['description'],
        'coverage': coverage,
        'how_it_was_made': about['method'],
        'how_reliable': about['reliability'],
        'topics': about['topics'],
        'tables': [{'name': t['name'], 'grain': t['grain'], 'description': t['description'],
                    'rows': m['table_rows'].get(t['name'])} for t in m['tables'] if _public(t)],
        'out_of_scope_tables': [{'name': t['name'], 'description': t['description'],
                                 'rows': m['table_rows'].get(t['name'])} for t in m['tables'] if not _public(t)],
        'conventions': about['conventions'],
        'how_to_work': HOW_TO_WORK,
        'sql': SQL_NOTES,
        'limits': LIMITS,
        'changes_since_previous_version': m['changes'],
    }
    return {k: v for k, v in out.items() if v != []}       # a graph from before a statement existed lacks it


def _columns(release):
    """Every described column as (table, column entry)."""
    return [(t['name'], c) for t in release.meta['tables'] if isinstance(t['columns'], list) for c in t['columns']]


def index(release):
    """A compact map of every table and column, for finding what to describe."""
    out = []
    for t in release.meta['tables']:
        entry = {'table': t['name'], 'grain': t['grain'], 'description': t['description']}
        entry['columns'] = {c['name']: ' · '.join(x for x in (c.get('topic'), c.get('label') or c.get('meaning', ''))
                                                  if x)[:120] for c in t['columns']}
        out.append(entry)
    return out


def describe(release, target=None, page=1, per_page=25):
    """Full descriptions of the columns a target names: a table, a topic (such as "Units added"), a field
    name, or column names (comma-separated). Without a target, a compact index of everything. Columns of the
    all_ tables come up only when one is named, since questions are about appeals in scope by default."""
    if not target:
        return {'version': release.version, 'index': index(release), 'topics': release.meta['about']['topics'],
                'next': 'describe a table, a topic, a field name such as duration, or column names for detail'}
    wanted = [w.strip() for w in str(target).split(',') if w.strip()]
    tables = {t['name']: t for t in release.meta['tables']}
    matches, tables_out = [], []
    for w in wanted:
        key = w.casefold()
        if key in tables:
            t = tables[key]
            tables_out.append({k: v for k, v in t.items() if k not in ('columns', 'out_of_scope')})
            matches += [(key, c) for c in t['columns']]
            continue
        hits = [(tn, c) for tn, c in _columns(release) if _public(tables[tn])
                and (c['name'].casefold() == key or str(c.get('field', '')).casefold() == key
                     or str(c.get('topic', '')).casefold() == key)]
        for t in tables.values():
            if _public(t) and t.get('field') and (t['field'].casefold() == key
                                                   or str(t.get('topic', '')).casefold() == key):
                tables_out.append({k: v for k, v in t.items() if k != 'columns'})
        matches += hits
    seen, unique = set(), []
    for tn, c in matches:
        if (tn, c['name']) not in seen:
            seen.add((tn, c['name']))
            unique.append({'table': tn, **c})
    pages = max(1, -(-len(unique) // per_page))
    page = min(max(1, int(page)), pages)
    out = {'version': release.version, 'target': target, 'tables': tables_out,
           'columns': unique[(page - 1) * per_page:page * per_page], 'page': page, 'pages': pages}
    if not unique and not tables_out:
        out['hint'] = 'Nothing matched. Call describe with no target for the index of tables and columns.'
    return out
