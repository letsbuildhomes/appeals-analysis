import asyncio
from dataclasses import replace
from datetime import date

from appeals import config
from appeals.codebook import build
from appeals.graph.endpoints import FakeDecisions, FakeReasoning
from appeals.graph.run import Runner
from appeals.ingest import dockets
from appeals.ingest.listing import Entry
from appeals.store import Store

PAGE = """STATE OF VERMONT
SUPERIOR COURT                                   ENVIRONMENTAL DIVISION
                                                 Docket No. 12-1-20 Vtec
In re Maple Street Duplex
The Town of Stowe Development Review Board approved a two-unit residential building. Neighbors appealed the
approval to this Court. The appeal is heard de novo. This concludes the matter before the Court."""


def _store(tmp_path):
    store = Store(tmp_path / 'test.sqlite')
    store.add_document('a' * 64, 100, 1)
    store.add_download('https://example/media/1', None, 'a' * 64, None)
    store.add_listing_entries([Entry('snap', 0, 0, 'https://example/media/1', 'Maple Street Duplex',
                                     date(2020, 6, 1), 'Environmental', '12-1-20 Vtec')])
    store.add_pages([('a' * 64, 1, PAGE, 'native', 'usable', '', 'test')])
    dockets.assign_all(store, log=lambda *_: None)
    return store


def test_docket_text_has_document_and_page_markers(tmp_path):
    store = _store(tmp_path)
    text = dockets.docket_text(store, '12-1-20 Vtec')
    assert text.text.startswith('<docket number="12-1-20 Vtec">\n<document n="1" title="Maple Street Duplex"')
    assert '<page n="1" source="native">' in text.text
    assert text.page_text(1, 1).strip().startswith('STATE OF VERMONT')


def test_a_run_stores_every_layer_and_reuses_unchanged_nodes(tmp_path):
    store = _store(tmp_path)
    settings = replace(config.load(), data=tmp_path, budget_usd=1.0)
    pipeline = build(settings.thresholds)
    runner = Runner(pipeline, store, settings, FakeDecisions(), FakeReasoning(), log=lambda *_: None)
    first = asyncio.run(runner.run(['12-1-20 Vtec'], workers=2))
    layers = {r['layer'] for r in store.rows('SELECT layer FROM run_records WHERE run_id = ?', (first,))}
    assert {'input', 'scan', 'plan', 'facts', 'derive', 'answers'} <= layers
    second = asyncio.run(Runner(pipeline, store, settings, FakeDecisions(), FakeReasoning(),
                                log=lambda *_: None).run(['12-1-20 Vtec'], workers=1))
    reused = store.value("SELECT min(r.reused) FROM run_records r JOIN node_records n ON n.key = r.key "
                         "WHERE r.run_id = ? AND r.layer IN ('scan', 'steps') AND r.node <> 'base' "
                         "AND json_extract(n.value, '$.skipped') IS NULL", (second,))     # model calls, not skips
    assert reused in (1, None)


def test_deleting_runs_keeps_every_stored_result(tmp_path):
    store = _store(tmp_path)
    settings = replace(config.load(), data=tmp_path, budget_usd=1.0)
    pipeline = build(settings.thresholds)

    def run(tags):
        runner = Runner(pipeline, store, settings, FakeDecisions(), FakeReasoning(), log=lambda *_: None)
        return asyncio.run(runner.run(['12-1-20 Vtec'], workers=1, tags=tags))

    kept, scratch = run([]), run(['scratch'])
    assert [r['id'] for r in store.runs(tag='scratch')] == [scratch]
    records = store.value('SELECT count(*) FROM node_records')
    store.delete_runs([r['id'] for r in store.runs(tag='scratch')])
    assert [r['id'] for r in store.runs()] == [kept]
    store.delete_runs([kept])
    assert store.value('SELECT count(*) FROM run_records') == 0
    assert store.value('SELECT count(*) FROM node_records') == records      # nothing paid for is lost
    assert store.unused_results()[0] == records
    assert store.prune_results() == records
    assert store.value('SELECT count(*) FROM node_records') == 0


class _InScope(FakeDecisions):
    """Every question's first option at 0.95: an in-scope docket whose flagged items all run."""

    async def ask(self, state, questions, long_context=False):
        reply = await super().ask(state, questions, long_context)
        for qid, q in questions.items():
            options = ['yes', 'no'] if q['type'] == 'yes_no' else list(q['criteria'])
            reply.answer[qid] = {o: (0.95 if i == 0 else 0.05 / (len(options) - 1)) for i, o in enumerate(options)}
        return reply


class _InScopeReasoning(FakeReasoning):
    """Made-up answers, except that the scope checks (L1) answer with each question's first option: in scope."""

    async def _complete(self, system, base, history, turns):
        import json
        from appeals.codebook import questions as Q
        reply = await super()._complete(system, base, history, turns)
        question = turns[0]['text']
        scope = [q for q in (Q.S1, Q.S2, Q.S3, Q.S4) if q.ask in question]
        if not scope or not reply.text.endswith('}'):
            return reply
        answer = json.loads(reply.text)
        key = next(iter(answer))
        answer[key]['answer'] = next(iter(scope[0].options))
        return reply.__class__(json.dumps(answer), reply.usage, reply.cost, reply.stop, reply.truncated)


def test_a_chained_request_replays_the_earlier_requests_exactly(tmp_path):
    import json
    store = _store(tmp_path)
    settings = replace(config.load(), data=tmp_path, budget_usd=1.0)
    runner = Runner(build(settings.thresholds), store, settings, _InScope(), _InScopeReasoning(), log=lambda *_: None)
    run_id = asyncio.run(runner.run(['12-1-20 Vtec'], workers=1))
    rows = store.db.execute('SELECT n.exchange FROM run_records r JOIN node_records n ON n.key = r.key '
                            'WHERE r.run_id = ? AND n.exchange IS NOT NULL', (run_id,)).fetchall()
    exchanges = [json.loads(r[0]) for r in rows if r[0]]
    sent = [e['history'] + e['turns'] for e in exchanges if e.get('turns')]
    chained = [e for e in exchanges if e.get('history')]
    assert len(chained) > 5
    assert all(e['history'] in sent for e in chained)       # each extends an earlier request and its reply, unchanged


def _layers(store, run_id):
    return {(r['layer'], r['node']) for r in store.rows('SELECT layer, node FROM run_records WHERE run_id = ?',
                                                        (run_id,))}


def test_a_run_can_stop_after_the_scan_and_a_later_run_reuses_it(tmp_path):
    store = _store(tmp_path)
    settings = replace(config.load(), data=tmp_path, budget_usd=1.0)
    pipeline = build(settings.thresholds)
    runner = Runner(pipeline, store, settings, _InScope(), FakeReasoning(), log=lambda *_: None)
    scanned = asyncio.run(runner.run(['12-1-20 Vtec'], workers=1, stop_after='scan'))
    assert {layer for layer, _ in _layers(store, scanned)} == {'input', 'scan', 'plan'}
    assert store.runs()[0]['status'] == 'stopped after scan'
    full = asyncio.run(Runner(pipeline, store, settings, _InScope(), FakeReasoning(),
                              log=lambda *_: None).run(['12-1-20 Vtec'], workers=1))
    assert store.value("SELECT reused FROM run_records WHERE run_id = ? AND layer = 'scan'", (full,)) == 1


def test_a_run_can_stop_after_a_step(tmp_path):
    store = _store(tmp_path)
    settings = replace(config.load(), data=tmp_path, budget_usd=1.0)
    pipeline = build(settings.thresholds)

    def steps(**kw):
        runner = Runner(pipeline, store, settings, _InScope(), FakeReasoning(), log=lambda *_: None)
        run_id = asyncio.run(runner.run(['12-1-20 Vtec'], workers=1, **kw))
        return run_id, {node.split('[')[0] for layer, node in _layers(store, run_id) if layer == 'steps'} - {'base'}

    _, everything = steps()
    ran = [s.id for s in pipeline.steps if s.id in everything]
    run_id, stopped = steps(stop_after=ran[2])
    assert stopped == set(ran[:3])
    assert not {layer for layer, _ in _layers(store, run_id)} & {'facts', 'derive', 'answers'}


def test_a_run_refuses_an_unknown_stopping_point(tmp_path):
    import pytest
    store = _store(tmp_path)
    settings = replace(config.load(), data=tmp_path, budget_usd=1.0)
    runner = Runner(build(settings.thresholds), store, settings, FakeDecisions(), FakeReasoning(), log=lambda *_: None)
    with pytest.raises(ValueError):
        asyncio.run(runner.run(['12-1-20 Vtec'], stop_after='L99'))
