"""The data dictionary a release carries: every table and column with its meaning, a profile of what the
data actually holds, query tips, and what changed since the last release.

Meanings, notes and options come from the graph description; profiles come
from the built tables; tips come from each column's type and profile. Nothing
here names a field. The dictionary is for readers of the data, so it says what
each answer means and never how the pipeline settled it.
"""
from appeals.graph.values import NOT_STATED
from appeals.release.read import FORMAT, built_on

NULLABLE = ('count', 'integer', 'text', 'name', 'date')
APPEALS = 'appeals in scope'
EVERYONE = 'all dockets, in scope or not'

FIXED_COLUMNS = {
    'appeals': {
        'docket': 'The docket number, such as 129-9-12 Vtec or 25-ENV-00114. One row per appeal.',
        'documents': 'How many published documents name this docket.',
        'first_posted': 'When the court posted the docket\'s first document.',
        'last_posted': 'When the court posted the docket\'s last document.',
    },
    'all_dockets': {
        'docket': 'The docket number, such as 129-9-12 Vtec or 25-ENV-00114. One row per docket.',
        'in_scope': 'Whether the docket is an appeal about new housing, the study\'s scope: true for the rows of '
                    'appeals. NULL when it could not be determined.',
        'documents': 'How many published documents name this docket.',
        'first_posted': 'When the court posted the docket\'s first document.',
        'last_posted': 'When the court posted the docket\'s last document.',
    },
    'documents': {
        'docket': 'The docket the document belongs to. A document naming several dockets appears once for each.',
        'document': 'Its number within the docket, in posting order: the document that quoted passages cite.',
        'title': 'The title in the court\'s listing.',
        'posted': 'When the court posted it.',
        'pages': 'Its number of pages.',
        'url': 'The PDF on the court\'s website.',
    },
    'docket_links': {
        'docket': 'An appeal.',
        'linked_docket': 'Another appeal that shares at least one document with it.',
        'shared_documents': 'How many documents the two share.',
    },
}
FIXED_COLUMNS['all_documents'] = FIXED_COLUMNS['documents']
FIXED_COLUMNS['all_docket_links'] = {**FIXED_COLUMNS['docket_links'], 'docket': 'A docket, in scope or not.',
                                     'linked_docket': 'Another docket that shares at least one document with it, in '
                                                      'scope or not. It may not be in this data at all.'}
TABLE_TEXT = {
    'appeals': ('one row per appeal in scope',
                'Every appeal of a town decision about new housing: the facts this data is about, one column per '
                'fact. Start here; every question is about these appeals unless it says otherwise.'),
    'documents': ('one row per appeal and document', 'The published decisions behind each appeal.'),
    'docket_links': ('one row per pair of appeals sharing a document',
                     'Appeals that share a decision often concern the same project. Use it to avoid counting the '
                     'same housing twice.'),
    'all_dockets': ('one row per docket the court published a decision in',
                    'Every docket, including those that are not appeals about new housing, which the study set aside. '
                    'Only the scope answers are recorded for those. Use it only for questions about dockets out of '
                    'scope or the court\'s whole caseload.'),
    'all_documents': ('one row per docket and document',
                      'The documents table for every docket, in scope or not. Use it only for dockets out of scope.'),
    'all_docket_links': ('one row per pair of dockets sharing a document',
                         'The docket_links table for every docket, in scope or not. Use it only for dockets out of '
                         'scope.'),
}
LONG_TEXT = {
    'set': ('one row per appeal and item', 'One answer for each item, since several items can apply to one appeal.'),
    'list': ('one row per listed item', 'A list, in the order the documents gave it.'),
    'counts': ('one row per appeal and option that occurs', 'Counts by option; options that don\'t occur have no row.'),
}


def _node_info(node, topics):
    info = {'field': node['id'], 'label': node.get('label', ''),
            'topic': topics.get(node.get('topic'), node.get('topic'))}
    if node.get('notes'):
        info['notes'] = node['notes']
    return info


def _q(name):
    return '"' + name.replace('"', '""') + '"'


def _scalar(con, sql, params=()):
    return con.execute(sql, params).fetchone()[0]


def _pairs(con, sql, params=()):
    return {('NULL' if k is None else str(k)): v for k, v in con.execute(sql, params).fetchall()}


def _profile(con, column, table, where='true'):
    """What a column actually holds over its table's rows."""
    c = _q(column.name)
    base = f'FROM {_q(table)} WHERE {where}'
    n = _scalar(con, f'SELECT count(*) {base}')
    known_sql = f'{c} IS NOT NULL' + (f" AND {c} <> '{NOT_STATED}'" if column.sql == 'VARCHAR' else '')
    known = _scalar(con, f'SELECT count(*) {base} AND {known_sql}')
    p = {'rows': n, 'known': known}
    if column.kind in ('one of', 'true or false', 'precision', 'item', 'option'):
        p['values'] = _pairs(con, f'SELECT {c}, count(*) {base} GROUP BY 1 ORDER BY 2 DESC, 1')
    elif column.sql == 'BIGINT':
        low, mid, high = con.execute(f'SELECT min({c}), median({c}), max({c}) {base}').fetchone()
        p.update(min=low, median=mid, max=high)
    elif column.kind == 'date':
        p.update(earliest=_scalar(con, f'SELECT min({c}) {base}'), latest=_scalar(con, f'SELECT max({c}) {base}'))
    elif column.kind == 'name':
        p['distinct'] = _scalar(con, f'SELECT count(DISTINCT {c}) {base}')
        p['most_common'] = _pairs(con, f'SELECT {c}, count(*) {base} AND {c} IS NOT NULL GROUP BY 1 '
                                       'ORDER BY 2 DESC, 1 LIMIT 10')
    elif column.kind == 'text':
        p['distinct'] = _scalar(con, f'SELECT count(DISTINCT {c}) {base}')
    return p


def _column_tips(column, profile, population):
    tips = []
    if column.options and NOT_STATED in column.options and column.kind == 'one of':
        tips.append('"not stated" means the documents were silent: report it separately, never as "no".')
    if column.kind in NULLABLE:
        tips.append('NULL means not stated.')
    if column.kind == 'date':
        tips.append(f'Text as precise as the documents allow (YYYY, YYYY-MM or YYYY-MM-DD). Check '
                    f'{column.name}_precision before comparing days, and CAST({column.name} AS DATE) only where it '
                    'is "day".')
    if column.kind == 'count of items':
        tips.append(f'The number of rows in {column.name[:-len("_count")]}: NULL when the list was never '
                    'established, 0 when it is empty.')
    if profile and profile['rows'] and column.kind not in ('precision', 'item', 'option', 'ordinal'):
        if profile['known'] / profile['rows'] < 0.5:
            tips.append(f'Known for only {profile["known"]} of {profile["rows"]} {population}.')
    return tips


def _wide(con, table, columns, layout, topics, population):
    out = []
    for c in columns:
        profile = _profile(con, c, table)
        out.append({**c.describe(), **_node_info(layout.nodes[c.node], topics), 'profile': profile,
                    'tips': _column_tips(c, profile, population)})
    return out


def tables(con, description, layout):
    """Every table in data.duckdb, described, with each column profiled."""
    in_scope = description.get('in_scope')
    topics = {t['id']: t['title'] for t in description.get('topics', [])}
    out = []

    grain, text = TABLE_TEXT['appeals']
    columns = [{'name': n, 'meaning': m} for n, m in FIXED_COLUMNS['appeals'].items()]
    columns += _wide(con, 'appeals', layout.wide, layout, topics, APPEALS)
    out.append({'name': 'appeals', 'grain': grain, 'description': text, 'population': APPEALS,
                'columns': columns})

    for t in layout.tables:
        node = layout.nodes[t.node]
        grain, text = LONG_TEXT[t.form]
        columns = [{'name': 'docket', 'meaning': 'The appeal.'}]
        for c in t.columns:
            profile = _profile(con, c, t.name) if c.kind not in ('ordinal',) else None
            entry = {**c.describe(), 'profile': profile} if profile else c.describe()
            if c.kind == 'ordinal':
                entry['meaning'] = 'The item\'s place in the list, from 1.'
            tips = _column_tips(c, profile, 'rows')
            if tips:
                entry['tips'] = tips
            columns.append(entry)
        tips = []
        if t.form == 'set':
            asked = next((n for n in description['nodes'] if n['id'] == node.get('from_scan')), None)
            if asked and asked['kind'] in ('question set', 'choice set'):
                columns[1]['options'] = {k: asked['options'].get(k, '') for k in columns[1]['options']}
            per_item = con.execute(f'SELECT item, answer, count(*) FROM {_q(t.name)} GROUP BY 1, 2 ORDER BY 1, 2').fetchall()
            profile = {}
            for item, answer, n in per_item:
                profile.setdefault(item, {})[answer] = n
            columns[1]['profile'] = {'by_item': profile}
            answer = 'yes' if 'yes' in (columns[2].get('options') or {}) else next(iter(columns[2].get('options') or {'…': ''}))
            tips.append(f"Count appeals by item and answer: COUNT(DISTINCT docket) ... WHERE item = '…' AND answer = "
                        f"'{answer}'. To filter appeals, use EXISTS (SELECT 1 FROM {t.name} s WHERE s.docket = a.docket "
                        f"AND s.item = '…' AND s.answer = '{answer}'). The answer column lists the options.")
        elif t.form == 'list':
            tips.append(f'Joining {t.name} to appeals repeats each appeal once per item: aggregate per appeal first, '
                        f'or filter with EXISTS. {t.name}_count on appeals is NULL when the list was never '
                        'established and 0 when it is empty.')
        else:
            tips.append('Options that don\'t occur have no row: a missing option means zero.')
        out.append({'name': t.name, 'grain': grain, 'description': f'{node.get("label", t.node)}. {text}',
                    **_node_info(node, topics), 'population': APPEALS, 'columns': columns, 'tips': tips})

    for name in ('documents', 'docket_links'):
        grain, text = TABLE_TEXT[name]
        out.append({'name': name, 'grain': grain, 'description': text, 'population': APPEALS,
                    'columns': [{'name': c, 'meaning': m} for c, m in FIXED_COLUMNS[name].items()]})

    grain, text = TABLE_TEXT['all_dockets']
    columns = [{'name': n, 'meaning': m} for n, m in FIXED_COLUMNS['all_dockets'].items()]
    columns[1]['profile'] = {'values': _pairs(con, 'SELECT in_scope, count(*) FROM all_dockets GROUP BY 1 ORDER BY 2 DESC')}
    if in_scope in layout.nodes:
        columns[1] = {**columns[1], 'type': 'BOOLEAN', **_node_info(layout.nodes[in_scope], topics)}
    columns += _wide(con, 'all_dockets', layout.scope(), layout, topics, EVERYONE)
    out.append({'name': 'all_dockets', 'grain': grain, 'description': text, 'population': EVERYONE,
                'columns': columns, 'out_of_scope': True})
    for name in ('all_documents', 'all_docket_links'):
        grain, text = TABLE_TEXT[name]
        out.append({'name': name, 'grain': grain, 'description': text, 'population': EVERYONE,
                    'columns': [{'name': c, 'meaning': m} for c, m in FIXED_COLUMNS[name].items()],
                    'out_of_scope': True})
    return out


def _columns(tables):
    return {f'{t["name"]}.{c["name"]}' for t in tables if isinstance(t['columns'], list) for c in t['columns']}


def changes(previous, description, tables_now):
    """What changed since the release that was current when this one was built, as (for readers, for whoever runs
    the pipeline). Readers get the columns added and removed; the pipeline's own changes stay internal."""
    if previous is None:
        return {'since': None, 'summary': 'This is the first release.'}, {'since': None}
    since = previous.get('version') or built_on(previous['created_at'])
    graph = previous.get('internal', previous)['graph']
    old = {n['id']: n for n in graph['nodes']}
    new = {n['id']: n for n in description['nodes']}
    changed = {nid: sorted(k for k in set(old[nid]) | set(new[nid]) if old[nid].get(k) != new[nid].get(k))
               for nid in set(old) & set(new) if old[nid] != new[nid]}
    internal = {'since': previous['id'], 'previous_graph': graph['hash'], 'graph': description['hash'],
                'nodes_added': sorted(set(new) - set(old)), 'nodes_removed': sorted(set(old) - set(new)),
                'nodes_changed': dict(sorted(changed.items())),
                'thresholds_changed': {k: [graph['thresholds'].get(k), v] for k, v in description['thresholds'].items()
                                       if graph['thresholds'].get(k) != v}}
    public = {'since': since}
    if previous.get('format') != FORMAT:
        public['summary'] = (f'The tables are reorganized since {since}: appeals is now the main table, holding only '
                             'appeals in scope, and the all_ tables hold every docket. Columns are not compared.')
        return public, internal
    before, after = _columns(previous['tables']), _columns(tables_now)
    public.update(columns_added=sorted(after - before), columns_removed=sorted(before - after))
    if graph['hash'] == description['hash']:
        public['summary'] = f'The same questions and definitions as {since}; only the data is new.'
    elif not (after - before or before - after):
        public['summary'] = f'The same tables and columns as {since}, with refinements to how answers are reached.'
    return public, internal
