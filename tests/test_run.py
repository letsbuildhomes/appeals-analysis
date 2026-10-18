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
    reused = store.value("SELECT min(reused) FROM run_records WHERE run_id = ? AND layer IN ('scan', 'steps') "
                         "AND node <> 'base'", (second,))
    assert reused in (1, None)


def test_deleting_runs_keeps_results_other_runs_use(tmp_path):
    store = _store(tmp_path)
    settings = replace(config.load(), data=tmp_path, budget_usd=1.0)
    pipeline = build(settings.thresholds)

    def run(tags):
        runner = Runner(pipeline, store, settings, FakeDecisions(), FakeReasoning(), log=lambda *_: None)
        return asyncio.run(runner.run(['12-1-20 Vtec'], workers=1, tags=tags))

    kept, scratch = run([]), run(['scratch'])
    assert [r['id'] for r in store.runs(tag='scratch')] == [scratch]
    records = store.value('SELECT count(*) FROM node_records')
    assert store.delete_runs([r['id'] for r in store.runs(tag='scratch')]) == 0     # all shared with the kept run
    assert [r['id'] for r in store.runs()] == [kept]
    assert store.value('SELECT count(*) FROM node_records') == records
    store.delete_runs([kept])
    assert store.value('SELECT count(*) FROM node_records') == 0
    assert store.value('SELECT count(*) FROM run_records') == 0


class _InScope(FakeDecisions):
    """Every question's first option at 0.95: an in-scope docket whose flagged items all run."""

    async def ask(self, state, questions, long_context=False):
        reply = await super().ask(state, questions, long_context)
        for qid, q in questions.items():
            options = ['yes', 'no'] if q['type'] == 'yes_no' else list(q['criteria'])
            reply.answer[qid] = {o: (0.95 if i == 0 else 0.05 / (len(options) - 1)) for i, o in enumerate(options)}
        return reply


def test_a_chained_request_replays_the_earlier_requests_exactly(tmp_path):
    import json
    store = _store(tmp_path)
    settings = replace(config.load(), data=tmp_path, budget_usd=1.0)
    runner = Runner(build(settings.thresholds), store, settings, _InScope(), FakeReasoning(), log=lambda *_: None)
    run_id = asyncio.run(runner.run(['12-1-20 Vtec'], workers=1))
    rows = store.db.execute('SELECT n.exchange FROM run_records r JOIN node_records n ON n.key = r.key '
                            'WHERE r.run_id = ? AND n.exchange IS NOT NULL', (run_id,)).fetchall()
    exchanges = [json.loads(r[0]) for r in rows if r[0]]
    sent = [e['history'] + e['turns'] for e in exchanges if e.get('turns')]
    chained = [e for e in exchanges if e.get('history')]
    assert len(chained) > 5
    assert all(e['history'] in sent for e in chained)       # each extends an earlier request and its reply, unchanged
