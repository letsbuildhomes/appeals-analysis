import asyncio

import pytest

from appeals.codebook import build
from appeals.config import Endpoint
from appeals.graph import expr as E
from appeals.graph import layers
from appeals.graph.endpoints import ReasoningModel, parse_json
from appeals.graph.nodes import Answer, Field, Gate, Question, Scan
from appeals.graph.pipeline import GraphError, Pipeline
from appeals.graph.values import NOT_STATED, Count, DateValue, OneOf, Quoted, Record

THRESHOLDS = {'scope_high': 0.7, 'scope_low': 0.2, 'counts': 0.5, 'discretion': 0.5, 'review': 0.5,
              'final': 0.5, 'stay': 0.5, 'design': 0.5, 'check': 0.3, 'sure': 0.8}


# ---- values -------------------------------------------------------------------------

def test_quoted_answer_needs_a_quote():
    kind = Quoted(OneOf({'yes': '', 'no': ''}))
    assert kind.validate({'answer': 'yes', 'quotes': []}, 'x') == ['x.quotes: an answer other than "not stated" needs at least one quote']
    assert kind.validate({'answer': NOT_STATED, 'quotes': []}, 'x') == []
    assert kind.validate({'answer': 'maybe', 'quotes': []}, 'x')[0].startswith("x.answer: 'maybe' is not one of")


def test_record_reports_missing_and_extra_keys():
    kind = Record(a=Count(), b=DateValue())
    errors = kind.validate({'a': -1, 'c': 1}, '')
    assert 'b: missing' in errors and 'c: not expected' in errors
    assert any(e.startswith('a: expected a whole number') for e in errors)


def test_parse_json_accepts_a_fenced_block():
    assert parse_json('Here:\n```json\n{"a": 1}\n```') == {'a': 1}
    with pytest.raises(ValueError):
        parse_json('{"a": ')


# ---- expressions ---------------------------------------------------------------------

def test_expression_evaluates_traces_and_prints():
    q = Question('Q1', 'A', ask='?', yes_no=True)
    rule = (q.p('yes') >= E.T.limit) & q.is_('yes')
    trace = []
    ctx = E.Context(scan={'Q1': {'yes': 0.8, 'no': 0.2}}, thresholds={'limit': 0.6}, trace=trace)
    assert rule.evaluate(ctx) is True
    assert rule.text() == 'P(Q1 = yes) ≥ T.limit and Q1 is yes'
    assert {t['term'] for t in trace} == {'P(Q1 = yes)', 'T.limit', 'Q1 is yes'}
    assert rule.refs() == {'Q1'}


# ---- the pipeline checks itself -------------------------------------------------------

def _tiny(answer_parts=True):
    q = Question('Q1', 'A', ask='?', yes_no=True)
    gate = Gate('g', 'A', title='g', when=q.p('yes') >= 0.5)
    f = Field('f', 'A', label='f', type=OneOf(q.options), scan=q)
    answers = [Answer('ans', 'A', title='a', parts=[f] if answer_parts else [])]
    return Pipeline('tiny', Scan('scan', 'A', questions=[q]), [gate], _base(), [], [f], [], answers,
                    gate.passed(), {})


def _base():
    from appeals.graph.nodes import Base
    return Base('base', 'steps', framing='x')


def test_a_field_that_reaches_no_answer_fails_the_build():
    _tiny()
    with pytest.raises(GraphError, match='reaches no Answer'):
        _tiny(answer_parts=False)


def test_codebook_builds_and_every_question_reaches_an_answer():
    pipeline = build(THRESHOLDS)
    description = pipeline.describe()
    assert len(description['hash']) == 16
    assert {n['kind'] for n in description['nodes']} >= {'question', 'gate', 'step', 'field', 'derive', 'answer'}
    assert pipeline.hash() == build(THRESHOLDS).hash()
    assert pipeline.hash() != build(THRESHOLDS | {'final': 0.6}).hash()     # thresholds are part of the identity


def test_plan_skips_gated_steps():
    pipeline = build(THRESHOLDS)
    scan = {q.id: {o: (1.0 if i == 0 else 0.0) for i, o in enumerate(q.request(_Docket()).get('criteria', {'yes': 1, 'no': 0}) if q.options_from else q.options)}
            for q in pipeline.scan.flat()}
    plan = layers.plan(pipeline, scan)
    assert plan['proceeds'] is True
    runs = {s['step']: s['runs'] for s in plan['steps']}
    assert runs['L1a'] is False          # scope confidently in: no scope check
    assert runs['L2a'] and runs['L3'] and runs['L4a']
    depends = {s['step'] for s in plan['steps'] if s.get('depends')}
    assert {'L2b', 'L9b', 'L10a', 'L10b'} <= depends          # decided by earlier answers, when the docket runs


class _Docket:
    text = 'Town of Stowe Development Review Board'


# ---- the JSON repair loop ---------------------------------------------------------------

class _Scripted(ReasoningModel):
    def __init__(self, replies):
        super().__init__(Endpoint(format='test', base_url='', model='m', key_env='', json_repairs=2, per_minute=0))
        self.replies = list(replies)
        self.seen = []

    async def _complete(self, system, base, history, turns):
        self.seen.append(list(turns))
        reply = self.replies.pop(0)
        truncated = reply is None                     # None stands for a reply cut off at the output limit
        return (reply or '{"n": '), {}, 0.0, truncated


def test_malformed_reply_is_sent_back_with_errors():
    model = _Scripted(['{"n": ', '{"n": -2}', '{"n": 3}'])
    reply = asyncio.run(model.ask('sys', 'base', [], 'How many?', Record(n=Count())))
    assert reply.answer == {'n': 3} and reply.error is None
    assert len(reply.exchange['attempts']) == 3
    repair = model.seen[1][-1]['text']
    assert 'not valid JSON' in repair
    assert 'n: expected a whole number' in model.seen[2][-1]['text']


def test_gives_up_after_the_repair_limit():
    model = _Scripted(['nope', 'nope', 'nope'])
    reply = asyncio.run(model.ask('sys', 'base', [], 'How many?', Record(n=Count())))
    assert reply.answer is None and 'no valid reply' in reply.error


def test_a_reply_cut_off_at_the_output_limit_is_sent_again_unchanged():
    model = _Scripted([None, None, '{"n": 3}'])
    reply = asyncio.run(model.ask('sys', 'base', [], 'How many?', Record(n=Count())))
    assert reply.answer == {'n': 3} and reply.error is None
    assert [len(turns) for turns in model.seen] == [1, 1, 1]          # no repair messages were added
    assert [a.get('truncated', False) for a in reply.exchange['attempts']] == [True, True, False]


def test_gives_up_after_the_truncation_limit():
    model = _Scripted([None, None, None])
    reply = asyncio.run(model.ask('sys', 'base', [], 'How many?', Record(n=Count())))
    assert reply.answer is None and 'ran out of output tokens 3 times' in reply.error


# ---- codebook rules ------------------------------------------------------------------------

def _facts(**answers):
    """Step results in the shape the executor stores: {step id: {"answer": …}}."""
    return {sid: {'answer': answer} for sid, answer in answers.items()}


def _quoted(value):
    return {'answer': value, 'quotes': [{'doc': 1, 'page': 1, 'quote': 'x', 'verified': True}]}


def test_a_moot_question_is_not_stated_whatever_the_scan_says():
    pipeline = build(THRESHOLDS)
    scan = {'D3': {'decided on the merits': 0.9, 'dismissed': 0.1}, 'D4': {'granted': 0.9, 'denied': 0.1}}
    steps = _facts(L9a={'final': _quoted('yes')}, L9b={'ended': _quoted('dismissed')})
    facts = layers.resolve(pipeline, scan, steps, '116-11-18 Vtec')
    assert facts['how_ended']['answer'] == 'dismissed'
    assert facts['court_result']['answer'] == NOT_STATED and facts['court_result']['source'] == 'rule'
    assert facts['docket_filing']['answer'] == '2018-11'


def test_set_items_come_from_their_own_steps():
    pipeline = build(THRESHOLDS)
    scan = {'C5.traffic': {'yes': 0.8, 'no': 0.2}, 'C5.density': {'yes': 0.7, 'no': 0.3}}
    steps = _facts(L7_traffic={'raised': _quoted('no')})
    issues = layers.resolve(pipeline, scan, steps)['issues_raised']
    assert issues['answer']['traffic'] == 'no' and issues['source']['traffic'] == 'step'
    assert issues['answer']['density'] == 'yes' and issues['source']['density'] == 'scan'
    assert issues['conflicts'] == ['traffic']


def _duration(**dates):
    from appeals.codebook.derived import duration
    names = ('filing_date', 'earliest_event', 'docket_filing', 'final_decision_date', 'latest_order_date')
    return duration({name: dates.get(name, NOT_STATED) for name in names})


def test_duration_uses_the_latest_possible_start_and_marks_open_bounds():
    exact = _duration(filing_date='2015-03-02', final_decision_date='2015-09-10')
    assert exact['kind'] == 'exact' and exact['days'] == 192
    year_only = _duration(docket_filing='2015', final_decision_date='2016-03-01')
    assert year_only['kind'] == 'at least' and year_only['days'] == 61          # from 2015-12-31
    assert year_only['start'] == {'date': '2015-12-31', 'bound': 'open', 'from': 'docket_filing'}
    assert _duration(docket_filing='2015', final_decision_date='2015-09-10')['kind'] == 'unknown'
    open_end = _duration(filing_date='2015-03-02', latest_order_date='2015-04-01')
    assert open_end['kind'] == 'at least' and open_end['end']['bound'] == 'open'


def test_duration_takes_the_tightest_of_several_open_starts():
    d = _duration(earliest_event='2018-12-04', docket_filing='2018-11', final_decision_date='2019-05-31')
    assert d['start']['date'] == '2018-11-30' and d['days'] == 182


def test_flagged_items_get_a_prompt_for_how_sure_the_scan_was():
    pipeline = build(THRESHOLDS)
    scan = {'S1': {'yes': 1.0}, 'S2': {'application for permission': 1.0}, 'S3': {'build a new structure': 1.0},
            'S4': {'yes': 1.0}, 'S5': {'adds': 1.0},
            'C5.traffic': {'yes': 0.9, 'no': 0.1}, 'C5.density': {'yes': 0.45, 'no': 0.55},
            'C5.character': {'yes': 0.2, 'no': 0.8}}
    steps = {s['step']: s for s in layers.plan(pipeline, scan)['steps']}
    assert steps['L7_traffic']['runs'] and steps['L7_traffic']['variant'] == 'scan fairly confident'
    assert steps['L7_density']['runs'] and steps['L7_density']['variant'] == 'scan uncertain'
    assert not steps['L7_character']['runs']
    prompt = layers.render_prompt(pipeline, pipeline.nodes['L7_density'], 'scan uncertain', scan)
    assert prompt.startswith('The scan was uncertain whether the appellant raised density')
    assert 'B1 (What did the municipal decision' in layers.claim(pipeline, {'B1': {'denied': 0.6, 'approved': 0.4}}, 'B1')
    assert layers.claim(pipeline, {'B1': {'denied': 0.6, 'approved': 0.4}}, 'B1').endswith('scan: denied, uncertain')


def test_an_out_of_scope_row_keeps_only_its_scope_values():
    pipeline = build(THRESHOLDS)
    facts = layers.resolve(pipeline, {'S1': {'yes': 1.0}, 'S2': {'enforcement or violation notice': 1.0},
                                      'B1': {'approved': 0.9, 'denied': 0.1}}, {}, '12-1-20 Vtec')
    derived = layers.derive(pipeline, facts)
    assert derived['X1'] is False and facts['town_decision']['answer'] == 'approved'      # the trace keeps it
    out = layers.row(pipeline, '12-1-20 Vtec', facts, derived)
    assert out['action_kind'] == 'enforcement or violation notice' and out['X1'] is False
    assert out['town_decision'] == 'out of scope' and out['X5'] == 'out of scope'


def test_dates_must_be_real_and_plausible():
    kind = DateValue()
    assert kind.validate('2019-05-31', 'd') == [] and kind.validate('2019', 'd') == [] and kind.validate(NOT_STATED, 'd') == []
    assert 'outside 1990' in kind.validate('0022-03-31', 'd')[0]
    assert 'not a calendar date' in kind.validate('2019-02-30', 'd')[0]
    assert 'not a calendar date' in kind.validate('2019-13', 'd')[0]
    assert 'expected YYYY' in kind.validate('31/05/2019', 'd')[0]
