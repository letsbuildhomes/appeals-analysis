"""What a release says about itself: an overview, column descriptions and pipeline explanations.

These read only a release's release.json, so they describe the pipeline that
made the release. The MCP tools and the public site's API serve them as they
are.
"""
from collections import deque

from appeals.release.read import LIMITS

HOW_TO_WORK = [
    'Read this overview first. Then use describe on the tables, topics or columns you need: it gives each '
    'column\'s meaning, options, notes, a profile of what the data holds, and query tips.',
    'Count appeals from the appeals view (in-scope dockets). Use dockets for the whole population, scope and '
    'failures. Always state the population you counted and how many were "not stated".',
    'Keep "not stated" (and NULL) separate from "no" and from zero. Report shares of known answers next to the '
    'number known.',
    'Before adding up units or lots across dockets, check docket_links: dockets that share a decision may describe '
    'the same project.',
    'To filter on how an answer was settled, join confidence on docket and field (source = \'step\' means a '
    'verified quote).',
    'Use explain to see how any column or value was produced: the questions asked, the gates and thresholds, the '
    'prompts, and the code that combines answers.',
    'Use docket to read a few dockets in full, with their quotes and document links. Quotes are evidence for '
    'individual cases, not for bulk analysis.',
    'Cite the release ID with any figure.',
]
SQL_NOTES = ('DuckDB SQL: one SELECT per query (WITH, FROM-first, SUMMARIZE and DESCRIBE work). Useful: median(), '
             'quantile_cont(x, 0.9), count(*) FILTER (WHERE …), GROUP BY ALL, EXISTS, date_diff(), list functions. '
             'Identifiers are case-insensitive.')


def _brief_release(release, current_id):
    m = release.meta
    endpoints = m['run'].get('endpoints') or {}
    return {'id': m['id'], 'current': m['id'] == current_id, 'created_at': m['created_at'],
            'run': m['run']['id'], 'run_finished_at': m['run']['finished_at'], 'graph': m['run']['graph_hash'],
            'models': {k: v.get('model') for k, v in endpoints.items()},
            'code': m.get('code')}


def overview(release, current_id):
    """Start here: what the data is, its population, its tables, the conventions and what changed."""
    m = release.meta
    graph = m['graph']
    return {
        'release': _brief_release(release, current_id),
        'what_this_is': graph.get('description', ''),
        'population': m['population'],
        'topics': [t['title'] for t in graph.get('topics', [])],
        'tables': [{'name': t['name'], 'grain': t['grain'], 'description': t['description'],
                    'rows': m['table_rows'].get(t['name'])} for t in m['tables']],
        'conventions': m['conventions'],
        'how_to_work': HOW_TO_WORK,
        'sql': SQL_NOTES,
        'limits': LIMITS,
        'changes_since_previous_release': m['changes'],
    }


# ---- describe ---------------------------------------------------------------------------

def _columns(release):
    """Every described column as (table, column entry)."""
    out = []
    for t in release.meta['tables']:
        if isinstance(t['columns'], list):
            out += [(t['name'], c) for c in t['columns']]
    return out


def index(release):
    """A compact map of every table and column, for finding what to describe."""
    out = []
    for t in release.meta['tables']:
        entry = {'table': t['name'], 'grain': t['grain'], 'description': t['description']}
        if isinstance(t['columns'], list):
            entry['columns'] = {c['name']: ' · '.join(x for x in (c.get('topic'), c.get('label') or c.get('meaning', ''))
                                                      if x)[:120] for c in t['columns']}
        else:
            entry['columns'] = t['columns']
        out.append(entry)
    return out


def describe(release, target=None, page=1, per_page=25):
    """Full descriptions of the columns a target names: a table, a topic (such as "Units added"), a field
    name, or column names (comma-separated). Without a target, a compact index of everything."""
    if not target:
        return {'release': release.id, 'index': index(release),
                'topics': [t['title'] for t in release.meta['graph'].get('topics', [])],
                'next': 'describe a table, a topic, a field name such as duration, or column names for detail'}
    wanted = [w.strip() for w in str(target).split(',') if w.strip()]
    tables = {t['name']: t for t in release.meta['tables']}
    matches, tables_out = [], []
    for w in wanted:
        key = w.casefold()
        if w in tables:
            t = tables[w]
            tables_out.append({k: v for k, v in t.items() if k != 'columns'})
            if isinstance(t['columns'], list):
                matches += [(w, c) for c in t['columns']]
            continue
        hits = [(tn, c) for tn, c in _columns(release)
                if c['name'].casefold() == key or str(c.get('node', '')).casefold() == key
                or str(c.get('topic', '')).casefold() == key]
        for t in tables.values():
            if t.get('node') and (t['node'].casefold() == key or str(t.get('topic', '')).casefold() == key):
                tables_out.append({k: v for k, v in t.items() if k != 'columns'})
        matches += hits
    seen, unique = set(), []
    for tn, c in matches:
        if (tn, c['name']) not in seen:
            seen.add((tn, c['name']))
            unique.append({'table': tn, **c})
    pages = max(1, -(-len(unique) // per_page))
    page = min(max(1, int(page)), pages)
    out = {'release': release.id, 'target': target, 'tables': tables_out,
           'columns': unique[(page - 1) * per_page:page * per_page], 'page': page, 'pages': pages}
    if not unique and not tables_out:
        out['hint'] = 'Nothing matched. Call describe with no target for the index of tables and columns.'
    return out


# ---- explain ----------------------------------------------------------------------------

def _trim(node):
    """A node's description without what only the executor needs."""
    return {k: v for k, v in node.items() if k not in ('schema',)}


def pipeline(release):
    """How the pipeline turns a docket into a row: layers, gates, steps in order, thresholds, and what it cost."""
    g = release.meta['graph']
    nodes = {n['id']: n for n in g['nodes']}
    layers = []
    for layer in g['layers']:
        members = [n for n in g['nodes'] if n['layer'] == layer]
        layers.append({'layer': layer, 'what_happens': g.get('layer_guide', {}).get(layer, ''),
                       'nodes': [{'id': n['id'], 'kind': n['kind'],
                                  'name': n.get('label') or n.get('title') or n.get('ask', '')[:100]}
                                 for n in members]})
    steps = []
    for sid in g['step_order']:
        s = nodes[sid]
        steps.append({'id': sid, 'title': s['title'], 'runs_when': s['when_text'], 'only_if': s['only_if'],
                      'after': s['after'], 'context': s['context'], 'confirms': s['confirms']})
    return {'release': release.id, 'pipeline': g['name'], 'graph': g['hash'], 'what_this_is': g.get('description'),
            'layers': layers,
            'gates': [{'id': n['id'], 'title': n['title'], 'condition': n['condition'], 'why': n['why']}
                      for n in g['nodes'] if n['kind'] == 'gate'],
            'proceeds_to_steps_when': g['proceed'], 'in_scope_value': g['in_scope'],
            'steps_in_order': steps, 'thresholds': g['thresholds'],
            'this_run': {k: release.meta['run'][k] for k in ('dockets_proceeding_to_steps',
                                                              'reasoning_calls_per_proceeding_docket', 'endpoints')},
            'next': 'explain a column, table or node ID (such as duration, L5a or the scan question C4) to trace it back'}


def _resolve(release, target):
    """The nodes a target names: a release column or table, else any node by ID."""
    g = release.meta['graph']
    key = target.casefold()
    for t in release.meta['tables']:
        if t['name'].casefold() == key and t.get('node'):
            return [t['node']]
        if isinstance(t['columns'], list):
            for c in t['columns']:
                if c['name'].casefold() == key and c.get('node'):
                    return [c['node']]
    return [n['id'] for n in g['nodes'] if n['id'].casefold() == key]


def explain(release, target='pipeline'):
    """How a value is produced: the node, and every node upstream of it, with prompts, options, conditions,
    thresholds and code; or the whole pipeline's flow."""
    if not target or target.strip().casefold() == 'pipeline':
        return pipeline(release)
    g = release.meta['graph']
    nodes = {n['id']: n for n in g['nodes']}
    found = _resolve(release, target.strip())
    if not found:
        return {'release': release.id, 'target': target,
                'hint': 'Nothing matched. Try "pipeline", a column or table name, or a node ID such as duration, L5a or C4.'}
    backward, forward = {}, {}
    for e in g['edges']:
        if e['kind'] == 'asked':                 # every question feeds the scan; don't expand them all
            continue
        backward.setdefault(e['to'], []).append(e['from'])
        forward.setdefault(e['from'], []).append(e['to'])
    upstream, queue = set(), deque(found)
    while queue:
        nid = queue.popleft()
        for source in backward.get(nid, []):
            if source not in upstream and source not in found:
                upstream.add(source)
                queue.append(source)
    order = {layer: i for i, layer in enumerate(g['layers'])}
    columns = [{'table': tn, 'column': c['name']} for tn, c in _columns(release) if c.get('node') in found]
    return {'release': release.id, 'target': target,
            'explains': [_trim(nodes[nid]) for nid in found],
            'in_release': columns,
            'how_it_flows': [g.get('layer_guide', {}).get(layer) for layer in g['layers']
                             if any(nodes[n]['layer'] == layer for n in upstream | set(found))],
            'upstream': [_trim(nodes[nid]) for nid in sorted(upstream, key=lambda n: (order[nodes[n]['layer']], n))],
            'used_by': sorted({t for nid in found for t in forward.get(nid, [])})}
