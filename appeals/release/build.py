"""Build a release: one finished run, frozen into files a server can publish.

A release is a folder under data/releases/<id>/:

    data.duckdb      the data tables (what the `query` tool and the dashboard read)
    evidence.duckdb  every quote behind the answers, read one docket at a time
    release.json     identity and provenance, the run's graph description, the data
                     dictionary with each column's profile and query tips

Everything about the tables comes from the run's stored graph description, not
from today's codebook, so a release always describes the pipeline that made it.
The store is only read. A release folder is never changed once written.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

import duckdb

from appeals.graph.values import OUT_OF_SCOPE, from_description
from appeals.ingest.dockets import docket_documents
from appeals.release import catalog, schema
from appeals.release.read import Release, Releases, _sha256, connect

FORMAT = 'appeals-release-1'


class BuildError(Exception):
    pass


def build(store, run_id, root, test=False, tags=(), log=print):
    """Write a new release from run `run_id` under `root`; return its release.json.

    `tags` label the release, such as "preview", for listing and deleting. A release built with `test` from a run
    that isn't a production run is also tagged "test".
    """
    run = next((r for r in store.runs() if r['id'] == run_id), None)
    if run is None:
        raise BuildError(f'no run {run_id}')
    problems = _test_run_problems(run)
    if problems and not test:
        raise BuildError(f'run {run_id} is not a production run: {"; ".join(problems)}. '
                         'Use --test to build a release from it anyway.')
    tags = sorted(set(tags) | ({'test'} if problems else set()))
    raw = store.value('SELECT description FROM graphs WHERE hash = ?', (run['graph_hash'],))
    if raw is None:
        raise BuildError(f'the graph {run["graph_hash"]} that run {run_id} used is not stored')
    description = json.loads(raw)
    try:
        layout = schema.layout(description)
    except schema.LayoutError as error:
        raise BuildError(str(error)) from None

    records = _records(store, run_id)
    _validate(description, layout, records)
    log(f'run {run_id}: {len(records)} dockets on graph {run["graph_hash"]}')

    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix='.building-', dir=root))
    try:
        counts = _write_data(store, description, layout, records, folder)
        _write_evidence(records, folder)
        meta = _meta(run, description, layout, counts, records, folder, Releases(root), tags)
        (folder / 'release.json').write_text(json.dumps(meta, indent=1, default=str))
        Release(folder)                                  # opens, checks hashes and the lockdown
        target = root / meta['id']
        if target.exists():
            raise BuildError(f'release {meta["id"]} already exists')
        os.replace(folder, target)
    finally:
        if folder.exists():
            shutil.rmtree(folder)
    log(f'release {meta["id"]} written to {target}')
    return meta


def _test_run_problems(run):
    endpoints = json.loads(run['endpoints']) if isinstance(run['endpoints'], str) else run['endpoints'] or {}
    problems = []
    if run['status'] != 'finished':
        problems.append(f'its status is "{run["status"]}"')
    if 'scratch' in (run['tags'] or []):
        problems.append('it is tagged scratch')
    if any(e.get('format') == 'fake' for e in endpoints.values()):
        problems.append('it used the fake models')
    return problems


def _records(store, run_id):
    """{docket: {'row', 'facts', 'error', 'plan', 'input'}} for every docket the run covered."""
    out = {}
    for r in store.rows("""SELECT r.docket, r.node, n.value FROM run_records r JOIN node_records n ON n.key = r.key
                           WHERE r.run_id = ? AND r.node IN ('row', 'facts', 'error', 'plan', 'input')""", (run_id,)):
        out.setdefault(r['docket'], {})[r['node']] = json.loads(r['value']) if r['value'] else None
    for docket in store.rows('SELECT DISTINCT docket FROM run_records WHERE run_id = ?', (run_id,)):
        out.setdefault(docket['docket'], {})
    return dict(sorted(out.items()))


def _status(record):
    if record.get('row') is not None:
        return 'complete'
    return 'failed' if record.get('error') else 'not run'


def _validate(description, layout, records):
    """Every value must match its declared type; the release's tables depend on it."""
    types = {nid: from_description(node['value_type']) for nid, node in layout.nodes.items()}
    in_scope = description.get('in_scope')
    problems = []
    for docket, record in records.items():
        row = record.get('row')
        if row is None:
            continue
        if in_scope and not isinstance(row.get(in_scope), bool):
            problems.append(f'{docket}: the in-scope value {in_scope} is {row.get(in_scope)!r}, not true or false')
        for nid, kind in types.items():
            if nid not in row:
                problems.append(f'{docket}: the row has no {nid}')
            elif row[nid] != OUT_OF_SCOPE:
                problems += [f'{docket}: {e}' for e in kind.validate(row[nid], nid)]
    if problems:
        shown = '\n  '.join(problems[:20])
        more = f'\n  … and {len(problems) - 20} more' if len(problems) > 20 else ''
        raise BuildError(f'{len(problems)} values don\'t match their declared types:\n  {shown}{more}')


# ---- data.duckdb ------------------------------------------------------------------------

def _insert(con, folder, table, columns, rows):
    """Bulk-load rows through a temporary JSON-lines file (much faster than row-by-row inserts)."""
    if not rows:
        return
    names = [n for n, _ in columns]
    path = folder / f'.{table}.ndjson'
    with path.open('w') as f:
        for row in rows:
            f.write(json.dumps(dict(zip(names, row)), default=str) + '\n')
    spec = '{' + ', '.join(f"'{n}': '{t}'" for n, t in columns) + '}'
    con.execute(f'INSERT INTO "{table}" SELECT * FROM read_json(?, format = \'newline_delimited\', '
                f'columns = {spec})', [str(path)])
    path.unlink()


def _create(con, table, columns):
    con.execute(f'CREATE TABLE "{table}" (' + ', '.join(f'"{n}" {t}' for n, t in columns) + ')')


def _write_data(store, description, layout, records, folder):
    con = duckdb.connect(str(folder / 'data.duckdb'))
    try:
        in_scope = description.get('in_scope')
        urls = {r['sha256']: r['url'] for r in store.rows(
            'SELECT sha256, min(coalesce(final_url, media_url)) AS url FROM downloads GROUP BY sha256')}
        documents, posted, count = [], {}, {}
        for docket in records:
            docs = docket_documents(store, docket)
            documents += [(docket, d['n'], d['sha256'], d['title'], d['posted'], d['pages'], urls.get(d['sha256']))
                          for d in docs]
            posted[docket] = sorted(d['posted'] for d in docs if d['posted'])
            count[docket] = len(docs)

        fixed = [('docket', 'VARCHAR'), ('status', 'VARCHAR'), ('failure', 'VARCHAR'), ('in_scope', 'BOOLEAN'),
                 ('documents', 'BIGINT'), ('first_posted', 'DATE'), ('last_posted', 'DATE')]
        assert [n for n, _ in fixed] == schema.DOCKET_COLUMNS
        _create(con, 'dockets', fixed + [(c.name, c.sql) for c in layout.wide])
        rows, long = [], {t.name: [] for t in layout.tables}
        for docket, record in records.items():
            row, status = record.get('row'), _status(record)
            error = (record.get('error') or {}).get('error')
            dates = posted[docket]
            values = [schema.cell(c, row[c.node]) if row else None for c in layout.wide]
            rows.append([docket, status, error.splitlines()[0][:300] if error else None,
                         row.get(in_scope) if row and in_scope else None,
                         count[docket], dates[0] if dates else None,
                         dates[-1] if dates else None,
                         *values])
            if row:
                for t in layout.tables:
                    long[t.name] += schema.long_rows(t, docket, row[t.node])
        _insert(con, folder, 'dockets', fixed + [(c.name, c.sql) for c in layout.wide], rows)
        con.execute('CREATE VIEW appeals AS SELECT * FROM dockets WHERE in_scope')
        for t in layout.tables:
            columns = [('docket', 'VARCHAR')] + [(c.name, c.sql) for c in t.columns]
            _create(con, t.name, columns)
            _insert(con, folder, t.name, columns, long[t.name])

        doc_columns = [('docket', 'VARCHAR'), ('document', 'BIGINT'), ('sha256', 'VARCHAR'), ('title', 'VARCHAR'),
                       ('posted', 'DATE'), ('pages', 'BIGINT'), ('url', 'VARCHAR')]
        _create(con, 'documents', doc_columns)
        _insert(con, folder, 'documents', doc_columns, documents)

        link_columns = [('docket', 'VARCHAR'), ('linked_docket', 'VARCHAR'), ('shared_documents', 'BIGINT')]
        links = [(r['a'], r['b'], r['n']) for r in store.rows("""
            SELECT a.docket AS a, b.docket AS b, count(*) AS n FROM document_dockets a
            JOIN document_dockets b ON b.sha256 = a.sha256 AND b.docket <> a.docket
            GROUP BY a.docket, b.docket ORDER BY 1, 2""") if r['a'] in records]
        _create(con, 'docket_links', link_columns)
        _insert(con, folder, 'docket_links', link_columns, links)

        confidence_columns = [('docket', 'VARCHAR'), ('field', 'VARCHAR'), ('item', 'VARCHAR'), ('source', 'VARCHAR'),
                              ('probability', 'DOUBLE'), ('conflict', 'BOOLEAN')]
        _create(con, 'confidence', confidence_columns)
        _insert(con, folder, 'confidence', confidence_columns, _confidence(layout, records))
        counts = {name: con.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0]
                  for name in ['dockets', *long, 'documents', 'docket_links', 'confidence']}
        counts['appeals'] = con.execute('SELECT count(*) FROM appeals').fetchone()[0]
        con.execute('CHECKPOINT')
        return counts
    finally:
        con.close()


def _reported(record, nid):
    """Whether a docket's row reports a node: the scope area always, the rest only when in scope."""
    row = record.get('row')
    return row is not None and row.get(nid) != OUT_OF_SCOPE


def _confidence(layout, records):
    """One row per docket and field (and item, for a yes/no set): where the settled answer came from."""
    fields = [nid for nid, n in layout.nodes.items() if n['kind'] == 'field']
    rows = []
    for docket, record in records.items():
        facts = record.get('facts') or {}
        for nid in fields:
            fact = facts.get(nid)
            if fact is None or not _reported(record, nid):
                continue
            if isinstance(fact.get('source'), dict):     # a yes/no set: a source per item
                conflicts = set(fact.get('conflicts') or [])
                rows += [(docket, nid, item, source, None, item in conflicts)
                         for item, source in fact['source'].items()]
            else:
                rows.append((docket, nid, None, fact.get('source'), fact.get('probability'), bool(fact.get('conflict'))))
    return rows


# ---- evidence.duckdb --------------------------------------------------------------------

def _write_evidence(records, folder):
    con = duckdb.connect(str(folder / 'evidence.duckdb'))
    try:
        columns = [('docket', 'VARCHAR'), ('field', 'VARCHAR'), ('document', 'BIGINT'), ('page', 'BIGINT'),
                   ('quote', 'VARCHAR'), ('verified', 'BOOLEAN')]
        _create(con, 'evidence', columns)
        rows = []
        for docket, record in records.items():
            for nid, fact in (record.get('facts') or {}).items():
                if not _reported(record, nid):
                    continue
                for q in fact.get('quotes') or []:
                    rows.append((docket, nid, q.get('doc'), q.get('page'), q.get('quote'), bool(q.get('verified'))))
        _insert(con, folder, 'evidence', columns, rows)
        con.execute('CHECKPOINT')
    finally:
        con.close()


# ---- release.json -----------------------------------------------------------------------

def _git():
    root = Path(__file__).resolve().parents[2]
    try:
        commit = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=root, capture_output=True, text=True,
                                check=True).stdout.strip()
        dirty = bool(subprocess.run(['git', 'status', '--porcelain'], cwd=root, capture_output=True, text=True,
                                    check=True).stdout.strip())
        return {'commit': commit, 'uncommitted_changes': dirty}
    except (OSError, subprocess.CalledProcessError):
        return None


def _run_summary(run, records):
    plans = [r['plan'] for r in records.values() if r.get('plan')]
    calls = sorted(p['calls'] for p in plans if p.get('proceeds'))
    endpoints = json.loads(run['endpoints']) if isinstance(run['endpoints'], str) else run['endpoints']
    return {'id': run['id'], 'status': run['status'], 'started_at': run['started_at'],
            'finished_at': run['finished_at'], 'cost_usd': run['cost_usd'], 'tags': run['tags'],
            'endpoints': endpoints, 'graph_hash': run['graph_hash'],
            'dockets_proceeding_to_steps': len(calls),
            'reasoning_calls_per_proceeding_docket': ({'min': calls[0], 'median': calls[len(calls) // 2],
                                                       'max': calls[-1]} if calls else None)}


def _meta(run, description, layout, counts, records, folder, releases, tags):
    statuses = [_status(r) for r in records.values()]
    population = {'dockets': len(records), 'complete': statuses.count('complete'),
                  'failed': statuses.count('failed'), 'not_run': statuses.count('not run'),
                  'in_scope': counts['appeals'], 'out_of_scope': statuses.count('complete') - counts['appeals']}
    con = connect(folder / 'data.duckdb')
    try:
        tables = catalog.tables(con, description, layout)
    finally:
        con.close()
    previous = releases.current()
    files = {name: _sha256(folder / name) for name in ('data.duckdb', 'evidence.duckdb')}
    created = datetime.now(timezone.utc)
    identity = [FORMAT, run['id'], run['graph_hash'], files, created.isoformat()]
    return {
        'id': hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:12],
        'format': FORMAT,
        'tags': tags,
        'created_at': created.isoformat(),
        'files': files,
        'run': _run_summary(run, records),
        'code': _git(),
        'population': population,
        'table_rows': counts,
        'tables': tables,
        'conventions': description.get('conventions', []),
        'previous': previous.id if previous else None,
        'changes': catalog.changes(previous.meta if previous else None, description, tables),
        'graph': description,
    }
