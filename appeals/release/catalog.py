"""The data dictionary a release carries: every table and column with its meaning, a profile of what the
data actually holds, query tips, and what changed since the last release.

Meanings, notes and options come from the graph description; profiles come
from the built tables; tips come from each column's type and profile. Nothing
here names a field.
"""
from appeals.graph.nodes import SCOPE
from appeals.graph.values import NOT_STATED

NULLABLE = ('count', 'integer', 'text', 'name', 'date')

FIXED_COLUMNS = {
    'dockets': {
        'docket': 'The docket number, such as 129-9-12 Vtec or 25-ENV-00114. One row per docket.',
        'status': 'complete: the pipeline produced answers. failed: it hit an error, so the row has no answers. '
                  'not run: the run stopped before reaching it.',
        'failure': 'For a failed docket, the error\'s first line.',
        'in_scope': 'Whether the docket is in scope ({in_scope}). NULL when the docket has no answers.',
        'documents': 'How many published documents name this docket.',
        'first_posted': 'When the court posted the docket\'s first document.',
        'last_posted': 'When the court posted the docket\'s last document.',
    },
    'documents': {
        'docket': 'The docket the document belongs to. A document naming several dockets appears once for each.',
        'document': 'Its number within the docket, in posting order: the "document" that quotes cite.',
        'sha256': 'The hash of the PDF\'s bytes, the same for every docket it belongs to.',
        'title': 'The title in the court\'s listing.',
        'posted': 'When the court posted it.',
        'pages': 'Its number of pages.',
        'url': 'The PDF on the court\'s website.',
    },
    'docket_links': {
        'docket': 'A docket in this release.',
        'linked_docket': 'Another docket that shares at least one document with it. It may not be in this release.',
        'shared_documents': 'How many documents the two share.',
    },
    'confidence': {
        'docket': 'The docket.',
        'field': 'The field (a column, or a long table, named by its node ID).',
        'item': 'For a yes/no set, the item; NULL otherwise.',
        'source': 'Where the settled answer came from. step: a reasoning step with a verified quote. scan: the '
                  'decision model\'s most likely answer, with a probability and no quote. rule: a rule made it '
                  '"not stated" because an earlier answer made it moot. docket number: read by code from the '
                  'docket number. none: no source answered, so it is "not stated".',
        'probability': 'For a scan answer, the scan\'s probability for it. NULL otherwise.',
        'conflict': 'True when a reasoning step\'s verified answer overrode a different scan answer.',
    },
}
TABLE_TEXT = {
    'dockets': ('one row per docket the run covered',
                'Every docket, in scope or not, with one column per fact and derived value. Columns outside the '
                'scope topic are NULL for dockets out of scope: the pipeline did not study them.'),
    'appeals': ('one row per in-scope docket',
                'The dockets in scope (dockets WHERE in_scope), with the same columns. Start here for questions about appeals.'),
    'documents': ('one row per docket and document', 'The published decisions behind each docket.'),
    'docket_links': ('one row per pair of dockets sharing a document',
                     'Dockets that share a decision often concern the same project. Use it to avoid counting the '
                     'same housing twice.'),
    'confidence': ('one row per docket and field (and item, for a yes/no set)',
                   'Where each settled answer came from. Join on docket and field to keep only quoted answers, or '
                   'to see how sure the scan was.'),
}
LONG_TEXT = {
    'set': ('one row per docket and item',
            'A yes/no question asked separately for each item. Only dockets the row reports are listed.'),
    'list': ('one row per listed item', 'A list, in the order the documents gave it.'),
    'counts': ('one row per docket and option that occurs', 'Counts by option; options that don\'t occur have no row.'),
}


def _node_info(node, topics):
    info = {'node': node['id'], 'label': node.get('label', ''),
            'topic': topics.get(node.get('topic'), node.get('topic'))}
    if node['kind'] == 'field':
        info['how_settled'] = node.get('rule', '')
    else:
        info['how_settled'] = 'computed in code from ' + ', '.join(node.get('inputs', []))
    if node.get('notes'):
        info['notes'] = node['notes']
    return info


def _q(name):
    return '"' + name.replace('"', '""') + '"'


def _scalar(con, sql, params=()):
    return con.execute(sql, params).fetchone()[0]


def _pairs(con, sql, params=()):
    return {('NULL' if k is None else str(k)): v for k, v in con.execute(sql, params).fetchall()}


def _profile(con, column, table, where):
    """What a column actually holds over its population."""
    c = _q(column.name)
    base = f'FROM {_q(table)} WHERE {where}'
    n = _scalar(con, f'SELECT count(*) {base}')
    known_sql = f'{c} IS NOT NULL' + (f" AND {c} <> '{NOT_STATED}'" if column.sql == 'VARCHAR' else '')
    known = _scalar(con, f'SELECT count(*) {base} AND {known_sql}')
    p = {'population': n, 'known': known}
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


def _sources(con, node_id):
    rows = con.execute('SELECT source, count(*), count(*) FILTER (WHERE conflict) FROM confidence WHERE field = ? '
                       'GROUP BY 1 ORDER BY 2 DESC', [node_id]).fetchall()
    if not rows:
        return None
    return {'sources': {s: n for s, n, _ in rows}, 'conflicts': sum(c for *_, c in rows)}


def _column_tips(column, profile, population, confidence):
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
    if profile and profile['population'] and column.kind not in ('precision', 'item', 'option', 'ordinal'):
        share = profile['known'] / profile['population']
        if share < 0.5:
            tips.append(f'Known for only {profile["known"]} of {profile["population"]} {population}.')
    if confidence:
        total = sum(confidence['sources'].values())
        scan = confidence['sources'].get('scan', 0)
        if total and scan / total > 0.5:
            tips.append(f'{round(100 * scan / total)}% of these answers come from the scan alone, with a '
                        'probability and no quote. Join confidence (source = \'step\') to keep quoted answers only.')
    return tips


def tables(con, description, layout):
    """Every table in data.duckdb, described, with each column profiled."""
    in_scope = description.get('in_scope')
    in_scope_label = layout.nodes.get(in_scope, {}).get('label', '') if in_scope else ''
    confidence = {nid: _sources(con, nid) for nid, n in layout.nodes.items() if n['kind'] == 'field'}
    topics = {t['id']: t['title'] for t in description.get('topics', [])}
    out = []

    def population(node_id):
        if layout.nodes[node_id]['topic'] == SCOPE:
            return "status = 'complete'", 'complete dockets'
        return 'in_scope', 'dockets in scope'

    grain, text = TABLE_TEXT['dockets']
    columns = [{'name': name, 'meaning': meaning.format(in_scope=f'{in_scope}, {in_scope_label}' if in_scope else '')}
               for name, meaning in FIXED_COLUMNS['dockets'].items()]
    columns[1]['profile'] = {'values': _pairs(con, 'SELECT status, count(*) FROM dockets GROUP BY 1 ORDER BY 2 DESC')}
    columns[3]['profile'] = {'values': _pairs(con, 'SELECT in_scope, count(*) FROM dockets GROUP BY 1 ORDER BY 2 DESC')}
    if in_scope in layout.nodes:
        columns[3] = {**columns[3], 'type': 'BOOLEAN', **_node_info(layout.nodes[in_scope], topics)}
    for c in layout.wide:
        where, who = population(c.node)
        profile = _profile(con, c, 'dockets', where)
        conf = confidence.get(c.node) if c.kind not in ('precision',) else None
        entry = {**c.describe(), **_node_info(layout.nodes[c.node], topics), 'population': who, 'profile': profile,
                 'tips': _column_tips(c, profile, who, conf)}
        if conf and c.kind != 'count of items':
            entry['confidence'] = conf
        columns.append(entry)
    out.append({'name': 'dockets', 'form': 'docket', 'grain': grain, 'description': text, 'columns': columns,
                'tips': ['Use the appeals view for questions about appeals in scope; use dockets for the population and scope.']})
    grain, text = TABLE_TEXT['appeals']
    out.append({'name': 'appeals', 'form': 'view', 'grain': grain, 'description': text,
                'columns': 'the same as dockets',
                'tips': ['The scope columns also hold answers for dockets out of scope, in the dockets table.']})

    for t in layout.tables:
        node = layout.nodes[t.node]
        grain, text = LONG_TEXT[t.form]
        where, who = population(t.node)
        where = f'docket IN (SELECT docket FROM dockets WHERE {where})'
        columns = [{'name': 'docket', 'meaning': 'The docket.'}]
        for c in t.columns:
            profile = _profile(con, c, t.name, where) if c.kind not in ('ordinal',) else None
            entry = {**c.describe(), 'profile': profile} if profile else c.describe()
            tips = _column_tips(c, profile, who, None)
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
            tips.append(f"Count dockets with an item: COUNT(DISTINCT docket) ... WHERE answer = 'yes'. To filter "
                        f"appeals, use EXISTS (SELECT 1 FROM {t.name} s WHERE s.docket = a.docket AND s.item = '…' "
                        "AND s.answer = 'yes').")
        elif t.form == 'list':
            tips.append(f'Joining {t.name} to appeals repeats each docket once per item: aggregate per docket first, '
                        f'or filter with EXISTS. {t.name}_count on appeals is NULL when the list was never '
                        'established and 0 when it is empty.')
        else:
            tips.append('Options that don\'t occur have no row: a missing option means zero.')
        entry = {'name': t.name, 'form': t.form, 'node': t.node, 'grain': grain,
                 'description': f'{node.get("label", t.node)} ({node.get("code", "")}). {text}',
                 **_node_info(node, topics), 'population': who, 'columns': columns, 'tips': tips}
        if confidence.get(t.node):
            entry['confidence'] = confidence[t.node]
        out.append(entry)

    for name in ('documents', 'docket_links', 'confidence'):
        grain, text = TABLE_TEXT[name]
        out.append({'name': name, 'form': name, 'grain': grain, 'description': text,
                    'columns': [{'name': c, 'meaning': m} for c, m in FIXED_COLUMNS[name].items()]})
    return out


def changes(previous, description, tables_now):
    """What changed since the release that was current when this one was built."""
    if previous is None:
        return {'since': None, 'summary': 'This is the first release.'}

    def columns(tables):
        out = set()
        for t in tables:
            if isinstance(t['columns'], list):
                out |= {f'{t["name"]}.{c["name"]}' for c in t['columns']}
        return out

    before, after = columns(previous['tables']), columns(tables_now)
    old = {n['id']: n for n in previous['graph']['nodes']}
    new = {n['id']: n for n in description['nodes']}
    changed = {nid: sorted(k for k in set(old[nid]) | set(new[nid]) if old[nid].get(k) != new[nid].get(k))
               for nid in set(old) & set(new) if old[nid] != new[nid]}
    out = {'since': previous['id'], 'previous_graph': previous['graph']['hash'], 'graph': description['hash'],
           'columns_added': sorted(after - before), 'columns_removed': sorted(before - after),
           'nodes_added': sorted(set(new) - set(old)), 'nodes_removed': sorted(set(old) - set(new)),
           'nodes_changed': dict(sorted(changed.items())),
           'thresholds_changed': {k: [previous['graph']['thresholds'].get(k), v]
                                  for k, v in description['thresholds'].items()
                                  if previous['graph']['thresholds'].get(k) != v},
           'conventions_added': [c for c in description.get('conventions', [])
                                 if c not in previous['graph'].get('conventions', [])],
           'conventions_removed': [c for c in previous['graph'].get('conventions', [])
                                   if c not in description.get('conventions', [])]}
    if previous['graph']['hash'] == description['hash']:
        out['summary'] = 'Same pipeline as the previous release; only the run (and so the data) differs.'
    return out

