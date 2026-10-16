import asyncio
from dataclasses import replace
from datetime import date
import json

import pytest

from appeals import config
from appeals.codebook import build as build_pipeline
from appeals.graph.endpoints import FakeDecisions, FakeReasoning
from appeals.graph.run import Runner
from appeals.ingest import dockets
from appeals.ingest.listing import Entry
from appeals.release import guide, read, schema
from appeals.release.build import BuildError, build
from appeals.release.read import QueryError, Releases
from appeals.store import Store

PAGE = """STATE OF VERMONT
SUPERIOR COURT                                   ENVIRONMENTAL DIVISION
                                                 Docket No. {dockets}
In re {title}
The Town of Stowe Development Review Board approved a {units}-unit residential building. Neighbors appealed the
approval to this Court. The appeal is heard de novo. This concludes the matter before the Court."""
DOCS = [('a', '12-1-20 Vtec', 'Maple Street Duplex', 2, date(2020, 6, 1)),
        ('b', '12-1-20 Vtec\n                                                 13-1-20 Vtec', 'Maple Street Joint', 2,
         date(2020, 9, 1)),
        ('c', '25-ENV-00114', 'Elm Street Apartments', 12, date(2025, 3, 1))]


def _store(tmp_path):
    store = Store(tmp_path / 'test.sqlite')
    for n, (key, numbers, title, units, posted) in enumerate(DOCS):
        sha = key * 64
        store.add_document(sha, 100, 1)
        store.add_download(f'https://example/media/{n}', f'https://example/{key}.pdf', sha, None)
        store.add_listing_entries([Entry('snap', 0, n, f'https://example/media/{n}', title, posted, 'Environmental',
                                         numbers.split()[0] + ' Vtec')])
        store.add_pages([(sha, 1, PAGE.format(dockets=numbers, title=title, units=units), 'native', 'usable', '',
                          'test')])
    dockets.assign_all(store, log=lambda *_: None)
    return store


def _run(store, tmp_path, tags=()):
    settings = replace(config.load(), data=tmp_path, budget_usd=1.0)
    runner = Runner(build_pipeline(settings.thresholds), store, settings, FakeDecisions(), FakeReasoning(),
                    log=lambda *_: None)
    numbers = [r['number'] for r in dockets.list_dockets(store)]
    return asyncio.run(runner.run(numbers, workers=2, tags=list(tags)))


@pytest.fixture
def released(tmp_path):
    store = _store(tmp_path)
    run_id = _run(store, tmp_path)
    releases = Releases(tmp_path / 'releases')
    meta = build(store, run_id, releases.root, test=True, log=lambda *_: None)
    releases.publish(meta['id'])
    return store, run_id, releases, releases.current()


# ---- layout ---------------------------------------------------------------------------

def test_every_value_type_has_a_place_in_the_tables():
    yes_no = {'type': 'one of', 'options': {'yes': '', 'no': ''}}
    nodes = [
        {'id': 'kind', 'kind': 'field', 'area': 'A', 'value_type': yes_no},
        {'id': 'when', 'kind': 'field', 'area': 'A', 'value_type': {'type': 'date'}},
        {'id': 'items', 'kind': 'field', 'area': 'A', 'value_type': {'type': 'record', 'fields': {'x': yes_no, 'y': yes_no}}},
        {'id': 'people', 'kind': 'field', 'area': 'B', 'value_type': {
            'type': 'list', 'not_stated': True, 'item': {'type': 'record', 'fields': {'name': {'type': 'name'},
                                                                                     'role': yes_no}}}},
        {'id': 'D', 'kind': 'derive', 'area': 'E', 'value_type': {'type': 'record', 'fields': {
            'days': {'type': 'count'}, 'start': {'type': 'or not stated', 'value': {'type': 'record', 'fields': {
                'date': {'type': 'date'}}}}, 'mix': {'type': 'counts by', 'options': {'a': '', 'b': ''}}}}},
    ]
    layout = schema.layout({'nodes': nodes})
    assert [c.name for c in layout.wide] == ['kind', 'when', 'when_precision', 'people_count', 'D_days',
                                             'D_start_date', 'D_start_date_precision']
    assert [(t.name, t.form, [c.name for c in t.columns]) for t in layout.tables] == [
        ('items', 'set', ['item', 'answer']), ('people', 'list', ['ordinal', 'name', 'role']),
        ('D_mix', 'counts', ['option', 'count'])]
    value = {'days': 'not stated', 'start': 'not stated', 'mix': {'a': 2}}
    assert [schema.cell(c, value) for c in layout.wide[4:]] == [None, None, None]
    assert schema.cell(layout.wide[1], '2020-06') == '2020-06' and schema.cell(layout.wide[2], '2020-06') == 'month'
    assert schema.long_rows(layout.tables[1], 'd', 'not stated') == []
    assert schema.long_rows(layout.tables[1], 'd', [{'name': 'Ann', 'role': 'yes'}]) == [('d', 1, 'Ann', 'yes')]


def test_a_type_without_a_rule_or_a_name_used_twice_stops_the_layout():
    with pytest.raises(schema.LayoutError, match='no release rule'):
        schema.layout({'nodes': [{'id': 'x', 'kind': 'field', 'area': 'A', 'value_type': {'type': 'mystery'}}]})
    with pytest.raises(schema.LayoutError, match='used twice'):
        schema.layout({'nodes': [{'id': 'status', 'kind': 'field', 'area': 'A', 'value_type': {'type': 'count'}}]})


def test_the_current_codebook_lays_out():
    pipeline = build_pipeline(config.load().thresholds)
    layout = schema.layout(pipeline.describe())
    nodes = {c.node for _, c in layout.columns()} | {t.node for t in layout.tables}
    assert pipeline.in_scope not in nodes                  # it is the fixed dockets.in_scope column
    assert nodes | {pipeline.in_scope} == {n.id for n in [*pipeline.fields, *pipeline.derives]}


# ---- building -------------------------------------------------------------------------

def test_a_release_describes_every_column_and_runs_every_example(released):
    store, run_id, releases, release = released
    meta = release.meta
    assert meta['run']['id'] == run_id and meta['population']['dockets'] == 3
    described = {(t['name'], c['name']) for t in meta['tables'] if isinstance(t['columns'], list)
                 for c in t['columns']}
    for table in [t['name'] for t in meta['tables'] if t['form'] != 'view']:
        actual = [r[0] for r in release.data.execute(f'DESCRIBE "{table}"').fetchall()]
        assert {(table, c) for c in actual} <= described, table
    examples = [e for a in meta['answers'] for e in a['examples']]
    assert examples and all('result' in e for e in examples)
    assert meta['conventions'] and meta['graph']['description']
    links = release.query('SELECT docket, linked_docket FROM docket_links ORDER BY 1')['rows']
    assert links == [['12-1-20 Vtec', '13-1-20 Vtec'], ['13-1-20 Vtec', '12-1-20 Vtec']]


def test_test_runs_need_test_and_releases_are_never_overwritten(tmp_path):
    store = _store(tmp_path)
    run_id = _run(store, tmp_path, tags=['scratch'])
    with pytest.raises(BuildError, match='tagged scratch.*fake models'):
        build(store, run_id, tmp_path / 'releases', log=lambda *_: None)
    first = build(store, run_id, tmp_path / 'releases', test=True, log=lambda *_: None)
    Releases(tmp_path / 'releases').publish(first['id'])
    second = build(store, run_id, tmp_path / 'releases', test=True, log=lambda *_: None)
    assert second['id'] != first['id'] and second['previous'] == first['id']
    assert second['changes']['columns_added'] == [] and 'Same pipeline' in second['changes']['summary']
    assert {r['id'] for r in Releases(tmp_path / 'releases').summaries()} == {first['id'], second['id']}


def test_a_value_that_breaks_its_declared_type_stops_the_build(tmp_path):
    store = _store(tmp_path)
    run_id = _run(store, tmp_path)
    key = store.value("SELECT key FROM run_records WHERE run_id = ? AND node = 'row' LIMIT 1", (run_id,))
    row = json.loads(store.value('SELECT value FROM node_records WHERE key = ?', (key,)))
    row['in_scope'] = 'yes'
    store.db.execute('UPDATE node_records SET value = ? WHERE key = ?', (json.dumps(row), key))
    with pytest.raises(BuildError, match='in_scope'):
        build(store, run_id, tmp_path / 'releases', test=True, log=lambda *_: None)


def test_a_changed_file_is_refused(released):
    *_, release = released
    with open(release.folder / 'evidence.duckdb', 'ab') as f:
        f.write(b'x')
    with pytest.raises(ValueError, match='does not match'):
        read.Release(release.folder)


# ---- reading --------------------------------------------------------------------------

@pytest.mark.parametrize('sql', [
    "SELECT * FROM read_csv('/etc/passwd')", 'SELECT 1; SELECT 2', 'DROP TABLE dockets', "ATTACH 'x.db' AS x",
    'SELECT * FROM evidence', "COPY dockets TO 'x.csv'", 'INSTALL httpfs', "SET memory_limit = '8GB'", ''])
def test_queries_read_only_the_release(released, sql):
    *_, release = released
    with pytest.raises(QueryError):
        release.query(sql)


def test_queries_are_bounded(released, monkeypatch):
    *_, release = released
    assert release.query('SELECT * FROM range(50)', max_rows=10)['truncation_reason'] == 'row limit'
    monkeypatch.setitem(read.LIMITS, 'seconds', 0.2)
    with pytest.raises(QueryError, match='longer than'):
        release.query('SELECT count(*) FROM range(10000000000) a, range(1000) b')


def test_docket_returns_quotes_for_a_few_dockets_only(released):
    *_, release = released
    out = release.docket(['12-1-20 Vtec', 'nope'], fields=['duration'])['dockets']
    assert out[0]['found'] and not out[1]['found']
    assert set(out[0]['answers']) >= {'docket', 'status', 'duration_kind', 'duration_days'}
    assert 'court_result' not in out[0]['answers']
    assert {'confidence', 'evidence', 'documents', 'linked_dockets'} <= set(out[0])
    assert out[0]['documents'][0]['url'] == 'https://example/a.pdf'
    with pytest.raises(QueryError):
        release.docket([f'd{i}' for i in range(11)])


def test_the_guide_explains_columns_and_the_pipeline(released):
    *_, releases, release = released
    o = guide.overview(release, releases.current_id())
    assert o['release']['current'] and len(o['research_questions']) == 7 and o['conventions']
    assert {c['area'] for c in guide.describe(release, 'E')['columns']} == {'E'}
    assert guide.describe(release, 'court_result')['columns'][0]['options']
    assert 'index' in guide.describe(release)
    d4 = guide.explain(release, 'D4')
    assert [n['id'] for n in d4['explains']] == ['court_result']
    assert {'D4', 'L9c', 'base'} <= {n['id'] for n in d4['upstream']}
    flow = guide.explain(release, 'pipeline')
    assert flow['steps_in_order'] and all(layer['what_happens'] for layer in flow['layers'])


# ---- serving --------------------------------------------------------------------------

def test_the_mcp_tools_answer_over_the_current_release(released):
    from mcp.shared.memory import create_connected_server_and_client_session
    from appeals.site.mcp import make_server
    *_, releases, release = released

    async def go():
        server = make_server(releases)
        async with create_connected_server_and_client_session(server._mcp_server) as client:
            tools = {t.name for t in (await client.list_tools()).tools}
            overview = (await client.call_tool('overview', {})).structuredContent
            counted = (await client.call_tool('query', {'sql': 'SELECT count(*) FROM dockets'})).structuredContent
            refused = await client.call_tool('query', {'sql': "SELECT * FROM read_csv('/etc/passwd')"})
            return tools, overview, counted, refused

    tools, overview, counted, refused = asyncio.run(go())
    assert tools == {'overview', 'describe', 'explain', 'query', 'docket'}
    assert overview['release']['id'] == release.id and counted['rows'] == [[3]] and refused.isError


def test_the_site_serves_everything_under_its_base_path(released):
    from starlette.testclient import TestClient
    from appeals.site.app import make_app
    *_, releases, release = released
    app = make_app(releases, '/appeals', 'Test', allowed_hosts=['testserver'])
    initialize = {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
        'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 'test', 'version': '0'}}}
    headers = {'Accept': 'application/json, text/event-stream'}
    with TestClient(app) as client:
        assert client.get('/appeals/healthz').json()['current_release'] == release.id
        assert 'Test' in client.get('/appeals/').text
        assert client.get('/appeals', follow_redirects=False).status_code == 307
        assert client.get(f'/appeals/api/releases/{release.id}').json()['release']['current']
        assert client.get('/appeals/api/releases/000000000000').status_code == 404
        answer = client.post('/appeals/mcp', json=initialize, headers=headers, follow_redirects=False)
        assert answer.status_code == 200 and answer.json()['result']['serverInfo']['name'] == 'Test'
        refused = client.post('/appeals/mcp', json=initialize, headers={**headers, 'Host': 'elsewhere.example'})
        assert refused.status_code == 421


def test_releases_carry_tags_and_can_be_deleted_except_the_current_one(tmp_path):
    store = _store(tmp_path)
    run_id = _run(store, tmp_path)
    releases = Releases(tmp_path / 'releases')
    kept = build(store, run_id, releases.root, test=True, tags=['preview'], log=lambda *_: None)
    other = build(store, run_id, releases.root, test=True, log=lambda *_: None)
    assert kept['tags'] == ['preview', 'test'] and other['tags'] == ['test']
    assert [r['id'] for r in releases.summaries(tag='preview')] == [kept['id']]
    releases.publish(kept['id'])
    releases.get(other['id'])                              # open, as a running server would hold it
    with pytest.raises(ValueError, match='is current'):
        releases.delete([kept['id']])
    releases.delete([other['id']])
    assert releases.ids() == [kept['id']] and releases.get(other['id']) is None


def test_a_password_guards_the_dashboard_but_not_mcp(released, monkeypatch):
    from starlette.testclient import TestClient
    from appeals.site import auth
    from appeals.site.app import make_app
    monkeypatch.setattr(auth, 'WRONG_PASSWORD_DELAY', 0)
    *_, releases, release = released
    app = make_app(releases, '/appeals', 'Test', allowed_hosts=['testserver'], password='open sesame')
    with TestClient(app) as client:
        for path in ('/appeals/', '/appeals/api/releases', f'/appeals/api/releases/{release.id}'):
            answer = client.get(path, follow_redirects=False)
            assert answer.status_code == 303 and answer.headers['location'] == '/appeals/login'
        assert client.get('/appeals/healthz').status_code == 200
        assert client.post('/appeals/mcp', json={}, headers={'Accept': 'application/json, text/event-stream'}
                           ).status_code != 303
        assert 'Wrong password' in client.post('/appeals/login', data={'password': 'nope'}).text
        assert 'appeals_site' not in client.cookies
        answer = client.post('/appeals/login', data={'password': 'open sesame'}, follow_redirects=False)
        assert answer.status_code == 303 and 'Max-Age=2592000' in answer.headers['set-cookie']
        assert client.get('/appeals/api/releases').status_code == 200
        assert 'Max-Age=2592000' in client.get('/appeals/').headers['set-cookie']      # renewed on each visit
    assert make_app(releases, '/appeals', 'Test', password='').__class__.__name__ == 'Starlette'
