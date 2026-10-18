import asyncio

import pytest

from appeals.codebook import build
from appeals.config import Reasoning
from appeals.graph import expr as E
from appeals.graph import layers
from appeals.graph.endpoints import Completion, ReasoningModel, parse_json
from appeals.graph.nodes import Field, Gate, Question, Scan, Step, YesNoSet
from appeals.graph.pipeline import GraphError, Pipeline
from appeals.graph.values import NOT_STATED, Count, DateValue, OneOf, Quoted, Record, YesNo
from appeals.providers import unpriced

THRESHOLDS = {'scope_high': 0.7, 'scope_low': 0.2, 'counts': 0.5, 'grounds': 0.3, 'other_check': 0.5,
              'review': 0.5, 'final': 0.5, 'stay': 0.5, 'design': 0.5, 'check': 0.3, 'sure': 0.6}


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

def _tiny(extra_question=False, topics=None):
    topics = {'A': 'A'} if topics is None else topics
    q = Question('Q1', 'A', ask='?', yes_no=True)
    gate = Gate('g', 'A', title='g', when=q.p('yes') >= 0.5)
    f = Field('f', 'A', label='f', type=OneOf(q.options), scan=q)
    questions = [q, Question('Q2', 'A', ask='?', yes_no=True)] if extra_question else [q]
    return Pipeline('tiny', Scan('scan', None, questions=questions), [gate], _base(), [], [f], [], gate.passed(), {},
                    topics=topics)


def _base():
    from appeals.graph.nodes import Base
    return Base('base', None, framing='x')


def test_a_question_that_feeds_no_fact_fails_the_build():
    _tiny()
    with pytest.raises(GraphError, match='Q2 feeds no fact or derived value'):
        _tiny(extra_question=True)


def test_codebook_builds_and_every_question_feeds_a_fact():
    pipeline = build(THRESHOLDS)
    description = pipeline.describe()
    assert len(description['hash']) == 16
    assert {n['kind'] for n in description['nodes']} >= {'question', 'gate', 'step', 'field', 'derive'}
    assert pipeline.hash() == build(THRESHOLDS).hash()
    assert pipeline.hash() != build(THRESHOLDS | {'final': 0.6}).hash()     # thresholds are part of the identity


def test_every_node_names_a_known_topic():
    description = build(THRESHOLDS).describe()
    known = {t['id'] for t in description['topics']}
    assert {n['topic'] for n in description['nodes'] if n['kind'] not in ('scan', 'base')} == known
    _tiny()
    with pytest.raises(GraphError, match="Q1 names no known topic"):
        _tiny(topics={})


def _family(*items):
    """A pipeline whose steps each settle the given item of a two-item scan set."""
    s = YesNoSet('K', 'A', ask='{item}?', items={'a': 'a', 'b': 'b'})
    steps = [Step(f'S{i}', 'A', title=key, set_item=(s, key), prompt='?', returns=Record(x=Quoted(YesNo())))
             for i, key in enumerate(items)]
    fields = [Field(f'f{i}', 'A', label='f', type=YesNo(), step=step, path='x') for i, step in enumerate(steps)]
    return Pipeline('tiny', Scan('scan', None, questions=[s]), [], _base(), steps,
                    [Field('k', 'A', label='k', type=YesNo(), scan=s, steps={}), *fields], [], E.Const(True),
                    {'check': 0.3, 'sure': 0.6}, topics={'A': 'A'})


def test_a_step_settles_one_item_of_a_scan_set():
    description = _family('a', 'b').describe()
    assert {n['id']: n['set_item'] for n in description['nodes'] if n['kind'] == 'step'} == {
        'S0': {'set': 'K', 'item': 'a'}, 'S1': {'set': 'K', 'item': 'b'}}
    with pytest.raises(GraphError, match='S0 settles K.c, which is not an item of a scan set'):
        _family('c')
    with pytest.raises(GraphError, match='S1 and S0 both settle K.a'):
        _family('a', 'a')


def test_a_chain_keeps_its_whole_line_in_context_but_draws_one_edge_per_step():
    pipeline = build(THRESHOLDS)
    units_court = pipeline.nodes['L6f']
    assert [s.id for s in units_court.line()] == ['L6a', 'L6b', 'L6c', 'L6e']
    chain = {(e['from'], e['to']) for e in pipeline.edges if e['kind'] == 'chain'}
    assert chain == {(s.after.id, s.id) for s in pipeline.steps if s.after}
    assert ('L5c', 'L6f') in {(e['from'], e['to']) for e in pipeline.edges if e['kind'] == 'condition'}


def test_plan_skips_gated_steps():
    pipeline = build(THRESHOLDS)
    scan = {q.id: {o: (1.0 if i == 0 else 0.0) for i, o in enumerate(q.options)}
            for q in pipeline.scan.flat()}
    plan = layers.plan(pipeline, scan)
    assert plan['proceeds'] is True
    runs = {s['step']: s['runs'] for s in plan['steps']}
    assert runs['L1a'] is False          # scope confidently in: no scope check
    assert runs['L2a'] and runs['L3a'] and runs['L3b'] and runs['L4a']
    depends = {s['step'] for s in plan['steps'] if s.get('depends')}
    assert {'L2b', 'L5b', 'L5e', 'L5f'} <= depends          # decided by earlier answers, when the docket runs


class _Docket:
    text = 'Town of Stowe Development Review Board'


# ---- the JSON repair loop ---------------------------------------------------------------

class _Scripted(ReasoningModel):
    def __init__(self, replies):
        super().__init__(Reasoning(unpriced('m', api='test')))
        self.replies = list(replies)
        self.seen = []
        self.requests = []

    async def _complete(self, system, base, history, turns):
        self.seen.append(list(turns))
        self.requests.append([*history, *turns])
        reply = self.replies.pop(0)
        if reply is None:                             # None stands for a reply cut off at the output limit
            return Completion('{"n": ', {}, 0.0, 'length', True)
        return Completion(reply, {}, 0.0, 'stop', False)


def test_malformed_reply_is_sent_back_with_errors():
    model = _Scripted(['{"n": ', '{"n": -2}', '{"n": 3}'])
    reply = asyncio.run(model.ask('sys', 'base', [], 'How many?', Record(n=Count())))
    assert reply.answer == {'n': 3} and reply.error is None
    assert len(reply.exchange['attempts']) == 3
    repair = model.seen[1][-1]['text']
    assert 'not valid JSON' in repair
    assert 'n: expected a whole number' in model.seen[2][-1]['text']


def test_a_chained_request_extends_the_one_before_it_exactly():
    from appeals.graph.endpoints import _messages
    model = _Scripted(['{"n": ', '{"n": 3}', '{"n": 4}'])           # the first step needs one repair
    first = asyncio.run(model.ask('sys', 'base', [], 'How many?', Record(n=Count())))
    second = asyncio.run(model.ask('sys', 'base', first.exchange['turns'], 'And now?', Record(n=Count())))
    sent_first, sent_second = model.requests[1], model.requests[2]
    assert sent_second[:len(sent_first)] == sent_first                # the first step's last request, unchanged …
    assert sent_second[len(sent_first)] == {'role': 'assistant', 'text': '{"n": 3}'}   # … then its reply
    assert sent_second[-1]['text'].startswith('And now?') and len(sent_second) == len(sent_first) + 2
    base = {'type': 'text', 'text': 'base'}
    one, two = _messages(base, sent_first), _messages(base, sent_second)
    assert two[:len(one)] == one and second.answer == {'n': 4}


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
    assert reply.answer is None and 'no usable reply after 3 resends' in reply.error


def test_an_empty_reply_is_sent_again_unchanged():
    model = _Scripted(['', '  ', '{"n": 3}'])
    reply = asyncio.run(model.ask('sys', 'base', [], 'How many?', Record(n=Count())))
    assert reply.answer == {'n': 3} and [len(turns) for turns in model.seen] == [1, 1, 1]
    attempts = reply.exchange['attempts']
    assert attempts[0]['errors'] == ['the reply was empty'] and attempts[0]['resent'] and attempts[0]['stop'] == 'stop'


# ---- codebook rules ------------------------------------------------------------------------

def _facts(**answers):
    """Step results in the shape the executor stores: {step id: {"answer": …}}."""
    return {sid: {'answer': answer} for sid, answer in answers.items()}


def _quoted(value):
    return {'answer': value, 'quotes': [{'doc': 1, 'page': 1, 'quote': 'x', 'verified': True}]}


def test_a_moot_question_is_not_stated_whatever_the_scan_says():
    pipeline = build(THRESHOLDS)
    scan = {'C3': {'decided on the merits': 0.9, 'dismissed': 0.1}, 'C4': {'granted': 0.9, 'denied': 0.1}}
    steps = _facts(L5a={'final': _quoted('yes')}, L5b={'ended': _quoted('dismissed')})
    facts = layers.resolve(pipeline, scan, steps, '116-11-18 Vtec')
    assert facts['how_ended']['answer'] == 'dismissed'
    assert facts['court_result']['answer'] == NOT_STATED and facts['court_result']['source'] == 'rule'
    assert facts['docket_filing']['answer'] == '2018-11'


def test_set_items_come_from_their_own_steps():
    pipeline = build(THRESHOLDS)
    scan = {'K1.subdivision': {'yes': 0.8, 'no': 0.2}, 'K1.variance': {'yes': 0.7, 'no': 0.3}}
    steps = _facts(L3_subdivision={'at_issue': _quoted('no')})
    kinds = layers.resolve(pipeline, scan, steps)['permission_kinds']
    assert kinds['answer']['subdivision'] == 'no' and kinds['source']['subdivision'] == 'step'
    assert kinds['answer']['variance'] == 'yes' and kinds['source']['variance'] == 'scan'
    assert kinds['conflicts'] == ['subdivision']


def test_each_kind_of_judgment_standard_comes_from_its_own_step():
    pipeline = build(THRESHOLDS)
    scan = {'G1': {'yes': 0.9, 'no': 0.1},
            'G2.character': {'decided, disputed': 0.9, 'not at issue': 0.1},
            'G2.traffic': {'decided, not disputed': 0.95, 'not at issue': 0.05}}
    steps = _facts(L7a={'stated': _quoted('yes')}, L8_character={'level': _quoted('decided, not disputed')},
                   L8_character_result={'result': 'met'})
    steps['L8_character_condition'] = {'skipped': 'condition not met: …'}
    facts = layers.resolve(pipeline, scan, steps)
    grounds, results = facts['judgment_grounds'], facts['judgment_results']
    assert grounds['answer']['character'] == 'decided, not disputed' and grounds['source']['character'] == 'step'
    assert grounds['answer']['traffic'] == 'decided, not disputed' and grounds['source']['traffic'] == 'scan'
    assert grounds['conflicts'] == ['character']
    assert results['answer']['character'] == 'met' and results['answer']['traffic'] == NOT_STATED
    conditions = facts['judgment_conditions']['answer']
    assert conditions['character'] == 'no' and conditions['traffic'] == NOT_STATED
    derived = layers.derive(pipeline, facts)
    assert derived['judgment_central'] == 'no' and derived['judgment_at_issue'] == 'yes'


def test_a_result_skipped_for_an_undecided_level_is_not_decided():
    pipeline = build(THRESHOLDS)
    steps = _facts(L7a={'stated': _quoted('yes')}, L8_site={'level': _quoted('set aside')})
    steps['L8_site_result'] = {'skipped': 'condition not met: …'}
    steps['L8_site_condition'] = {'skipped': 'condition not met: …'}
    facts = layers.resolve(pipeline, {'G1': {'yes': 0.9}, 'G2.site': {'set aside': 0.8}}, steps)
    assert facts['judgment_results']['answer']['site'] == 'not decided'
    assert facts['judgment_conditions']['answer']['site'] == 'no'


def test_a_result_without_a_verified_level_is_not_used():
    pipeline = build(THRESHOLDS)
    unverified = {'answer': 'decided, disputed', 'quotes': [{'doc': 1, 'page': 1, 'quote': 'x', 'verified': False}]}
    steps = _facts(L7a={'stated': _quoted('yes')},
                   L8_water={'level': unverified}, L8_water_result={'result': 'not met'},
                   L8_water_condition={'condition': 'yes'})
    facts = layers.resolve(pipeline, {'G1': {'yes': 0.9}, 'G2.water': {'decided, disputed': 0.8}}, steps)
    assert facts['judgment_results']['answer']['water'] == NOT_STATED
    assert facts['judgment_conditions']['answer']['water'] == NOT_STATED
    assert facts['judgment_grounds']['answer']['water'] == 'decided, disputed'        # the scan's answer
    assert layers.derive(pipeline, facts)['judgment_central'] == 'yes'


def test_grounds_are_not_stated_when_no_arguments_are():
    pipeline = build(THRESHOLDS)
    facts = layers.resolve(pipeline, {'G1': {'yes': 0.1, 'no': 0.9}, 'G2.character': {'decided, disputed': 0.9}}, {})
    assert facts['judgment_grounds']['answer'] == NOT_STATED and facts['other_questions']['answer'] != NOT_STATED
    assert layers.derive(pipeline, facts)['judgment_central'] == NOT_STATED


def _duration(**dates):
    from appeals.codebook.derived import duration
    names = ('filing_date', 'earliest_event', 'docket_filing', 'town_decision_date', 'final_decision_date',
             'latest_order_date')
    return duration({name: dates.get(name, NOT_STATED) for name in names})


def test_duration_uses_the_latest_possible_start_and_marks_open_bounds():
    exact = _duration(filing_date='2015-03-02', final_decision_date='2015-09-10')
    assert exact['kind'] == 'exact' and exact['days'] == 192
    year_only = _duration(docket_filing='2015', final_decision_date='2016-03-01')
    assert year_only['kind'] == 'at least' and year_only['days'] == 61          # from 2015-12-31
    assert year_only['start'] == {'date': '2015-12-31', 'bound': 'open', 'from': 'docket_filing', 'inferred': False}
    assert _duration(docket_filing='2015', final_decision_date='2015-09-10')['kind'] == 'unknown'
    open_end = _duration(filing_date='2015-03-02', latest_order_date='2015-04-01')
    assert open_end['kind'] == 'at least' and open_end['end']['bound'] == 'open'


def test_duration_takes_the_tightest_of_several_open_starts():
    d = _duration(earliest_event='2018-12-04', docket_filing='2018-11', final_decision_date='2019-05-31')
    assert d['start']['date'] == '2018-11-30' and d['days'] == 182


def test_duration_starts_at_the_town_decision_when_no_exact_filing_date():
    tuggle = _duration(earliest_event='2019-05-31', docket_filing='2018-11', town_decision_date='2018-10-11',
                       final_decision_date='2019-05-31')
    assert tuggle['kind'] == 'exact' and tuggle['days'] == 232
    assert tuggle['start'] == {'date': '2018-10-11', 'bound': 'closed', 'from': 'town_decision_date', 'inferred': True}
    filed = _duration(filing_date='2018-11-05', town_decision_date='2018-10-11', final_decision_date='2019-05-31')
    assert filed['start']['from'] == 'filing_date' and not filed['start']['inferred']
    month_only = _duration(docket_filing='2018-11', town_decision_date='2018-10', final_decision_date='2019-05-31')
    assert month_only['start']['from'] == 'docket_filing'                    # a town decision to the month isn't used
    too_late = _duration(docket_filing='2018-11', town_decision_date='2019-01-15', final_decision_date='2019-05-31')
    assert too_late['start']['from'] == 'docket_filing'                       # after the filing: not this appeal's decision


IN_SCOPE_SCAN = {'S1': {'municipal permit application': 1.0}, 'S2': {'build a new structure': 1.0},
                 'S3': {'yes': 1.0}, 'S4': {'adds': 1.0}}


def test_flagged_items_get_a_prompt_for_how_sure_the_scan_was():
    pipeline = build(THRESHOLDS)
    scan = {**IN_SCOPE_SCAN, 'K1.subdivision': {'yes': 0.9, 'no': 0.1}, 'K1.variance': {'yes': 0.45, 'no': 0.55},
            'K1.site plan': {'yes': 0.2, 'no': 0.8}}
    steps = {s['step']: s for s in layers.plan(pipeline, scan)['steps']}
    assert steps['L3_subdivision']['runs'] and steps['L3_subdivision']['variant'] == 'scan fairly confident'
    assert steps['L3_variance']['runs'] and steps['L3_variance']['variant'] == 'scan uncertain'
    assert layers.claim(pipeline, {'T1': {'denied': 0.6, 'approved': 0.4}}, 'T1').startswith('What did the municipal decision')
    assert layers.claim(pipeline, {'T1': {'denied': 0.55, 'approved': 0.45}}, 'T1').endswith(
        'The scan answered "denied" and was uncertain.')


def test_the_base_states_every_scan_answer_and_a_step_repeats_only_its_own():
    pipeline = build(THRESHOLDS)
    scan = {**IN_SCOPE_SCAN, 'T1': {'denied': 0.9, 'approved': 0.1}, 'C1': {'de novo': 0.9},
            'K1.subdivision': {'yes': 0.9, 'no': 0.1}}
    base = pipeline.base.render('DOCKET', layers.claims(pipeline, scan))
    assert base.startswith(pipeline.base.framing.strip() + '\n\nDOCKET\n\n<scan>\n') and base.endswith('</scan>')
    assert '- How did the Environmental Court hear this appeal of the municipal decision? The scan answered "de novo"' in base
    assert 'Item: subdivision approval. The scan answered "yes" and was fairly confident.' in base
    assert 'T1' not in base                                                   # no question IDs
    prompt = layers.render_prompt(pipeline, pipeline.nodes['L3a'], '', scan)
    assert 'The scan answered "denied"' in prompt and 'How did the Environmental Court hear' not in prompt


def test_a_step_confirms_the_scan_questions_it_states_or_reads():
    pipeline = build(THRESHOLDS)
    confirms = {s.id: s.confirms for s in pipeline.steps}
    assert confirms['L6e'] == [] and confirms['L6f'] == ['U4', 'U5']
    assert confirms['L8_traffic'] == ['G2'] and confirms['L3_variance'] == ['K1']
    assert confirms['L7b'] == ['G4'] and confirms['L3b'] == []


def test_prompts_are_paragraphs_without_line_wrapping():
    pipeline = build(THRESHOLDS)
    for text in [pipeline.base.framing, *(t for s in pipeline.steps for t in s.templates().values())]:
        assert all('\n' not in paragraph for paragraph in text.split('\n\n')), text[:60]


def test_the_answer_instructions_say_what_each_option_means():
    from appeals.graph.endpoints import answer_instructions
    pipeline = build(THRESHOLDS)
    told = answer_instructions(pipeline.nodes['L8_relief_kind'].returns)
    assert 'What the options mean:' in told and '- bylaw waiver: A waiver of a dimensional requirement' in told
    roles = answer_instructions(pipeline.nodes['L4a'].returns)
    assert 'appellants → role:\n- applicant or owner:' in roles
    assert 'What the options mean' not in answer_instructions(Record(n=Quoted(YesNo())))   # a plain yes or no


def test_none_found_needs_no_quote_and_is_recorded_as_no():
    pipeline = build(THRESHOLDS)
    stayed = pipeline.nodes['L11a'].returns
    assert stayed.validate({'stayed': {'answer': 'none found', 'quotes': []}}, '') == []
    assert stayed.validate({'stayed': {'answer': 'no', 'quotes': []}}, '')          # a stated no still needs its quote
    scan = {**IN_SCOPE_SCAN, 'D1': {'yes': 0.7, 'no': 0.3}, 'K1.subdivision': {'yes': 0.8, 'no': 0.2}}
    steps = {'L11a': {'answer': {'stayed': {'answer': 'none found', 'quotes': []}}},
             'L3_subdivision': {'answer': {'at_issue': {'answer': 'none found', 'quotes': []}}}}
    facts = layers.resolve(pipeline, scan, steps)
    assert facts['stayed']['answer'] == 'no' and facts['stayed']['source'] == 'step' and facts['stayed']['conflict']
    assert facts['permission_kinds']['answer']['subdivision'] == 'no'
    assert facts['permission_kinds']['none_found'] == ['subdivision']
    town = pipeline.nodes['L3c'].returns                       # only a type that offers it may answer "none found"
    assert town.validate({'town': {'answer': 'none found', 'quotes': []}, 'place': {'answer': 'not stated', 'quotes': []}}, '')
    place = layers.resolve(pipeline, scan, {'L3c': {'answer': {'town': {'answer': 'not stated', 'quotes': []},
                                                               'place': {'answer': 'none found', 'quotes': []}}}})
    assert place['place_within_town']['answer'] == NOT_STATED


def test_a_scope_step_that_cannot_tell_neither_ends_the_chain_nor_takes_the_docket_out():
    pipeline = build(THRESHOLDS)
    unsure = {'housing': {'answer': 'not stated', 'quotes': []}}
    assert not layers.halts(pipeline.nodes['L1c'], {'L1c': unsure})
    assert layers.halts(pipeline.nodes['L1c'], {'L1c': {'housing': {'answer': 'no', 'quotes': []}}})
    scan = {**IN_SCOPE_SCAN, 'S3': {'yes': 0.86, 'no': 0.14}}
    facts = layers.resolve(pipeline, scan, {'L1c': {'answer': unsure}})
    assert facts['housing_use']['answer'] == 'yes' and facts['housing_use']['source'] == 'scan'
    assert layers.derive(pipeline, facts)['in_scope'] is True


def _runs(pipeline, scan, step_id, answers):
    """Whether a planned step runs, given earlier steps' answers."""
    entry = next(s for s in layers.plan(pipeline, scan)['steps'] if s['step'] == step_id)
    if not entry['runs'] or 'depends' not in entry:
        return entry['runs'], entry['variant']
    gates = layers.plan(pipeline, scan)['gates']
    return layers.condition_met(pipeline, pipeline.nodes[step_id], scan, gates, answers)[0], entry['variant']


def test_a_kind_of_judgment_standard_is_followed_up_when_it_may_be_at_issue():
    pipeline = build(THRESHOLDS)
    scan = {**IN_SCOPE_SCAN, 'G1': {'yes': 0.9, 'no': 0.1},
            'G2.character': {'decided, disputed': 0.9, 'not at issue': 0.1},
            'G2.traffic': {'not at issue': 0.55, 'raised only': 0.45},
            'G2.historic': {'not at issue': 0.9, 'raised only': 0.1},
}
    stated = {'L7a': {'stated': {'answer': 'yes', 'quotes': []}}}
    assert _runs(pipeline, scan, 'L8_character', stated) == (True, 'scan fairly confident')
    assert _runs(pipeline, scan, 'L8_traffic', stated) == (True, 'scan uncertain')
    assert _runs(pipeline, scan, 'L8_historic', stated)[0] is False
    assert _runs(pipeline, scan, 'L8_character', {'L7a': {'stated': {'answer': 'no', 'quotes': []}}})[0] is False
    prompt = layers.render_prompt(pipeline, pipeline.nodes['L8_character'], 'scan fairly confident', scan)
    assert prompt.startswith('The kind of standard: the character of the area')
    assert ('The scan judged that this docket dealt with this kind of standard, most likely at the level '
            '"decided, disputed".') in prompt


def test_other_questions_are_followed_up_at_a_higher_threshold():
    pipeline = build(THRESHOLDS)
    scan = {**IN_SCOPE_SCAN, 'G1': {'yes': 0.9},
            'G3.appeal': {'decided, disputed': 0.8, 'not at issue': 0.2},
            'G3.process': {'not at issue': 0.55, 'raised only': 0.45},     # at issue 0.45: below 0.5, no follow-up
            'G3.meaning': {'not at issue': 0.45, 'decided, disputed': 0.35, 'raised only': 0.2}}
    stated = {'L7a': {'stated': {'answer': 'yes', 'quotes': []}}}
    assert _runs(pipeline, scan, 'L9_appeal', stated) == (True, 'scan fairly confident')
    assert _runs(pipeline, scan, 'L9_process', stated)[0] is False
    assert _runs(pipeline, scan, 'L9_meaning', stated) == (True, 'scan uncertain')
    prompt = layers.render_prompt(pipeline, pipeline.nodes['L9_meaning'], 'scan uncertain', scan)
    assert 'unsure whether' in prompt and 'most likely at the level "decided, disputed")' in prompt


def test_what_was_central_reads_both_families():
    from appeals.codebook.derived import what_was_central
    quiet = {k: 'not at issue' for k in ('character', 'traffic')}
    assert what_was_central({'judgment_grounds': {**quiet, 'traffic': 'decided, disputed'},
                             'other_questions': {'appeal': 'decided, disputed'}}) == 'a judgment standard'
    assert what_was_central({'judgment_grounds': quiet, 'other_questions': {'appeal': 'decided, disputed'}}) == \
        'other questions only'
    assert what_was_central({'judgment_grounds': quiet, 'other_questions': {'appeal': 'decided, not disputed'}}) == 'nothing'
    assert what_was_central({'judgment_grounds': NOT_STATED, 'other_questions': {'appeal': 'decided, not disputed'}}) == NOT_STATED
    assert what_was_central({'judgment_grounds': NOT_STATED, 'other_questions': {'appeal': 'decided, disputed'}}) == \
        'other questions only'


def test_other_questions_run_when_no_arguments_are_stated():
    pipeline = build(THRESHOLDS)
    scan = {**IN_SCOPE_SCAN, 'G1': {'yes': 0.01, 'no': 0.99}, 'G3.appeal': {'decided, not disputed': 0.9}}
    assert _runs(pipeline, scan, 'L9_appeal', {}) == (True, 'scan fairly confident')
    assert not _runs(pipeline, scan, 'L7a', {})[0]                       # the grounds gate still holds


def test_the_kind_of_relief_is_asked_only_when_relief_was_at_issue():
    pipeline = build(THRESHOLDS)
    scan = {**IN_SCOPE_SCAN, 'G1': {'yes': 0.9}, 'G2.relief': {'decided, disputed': 0.8, 'not at issue': 0.2}}
    at_issue = {'L8_relief': {'level': {'answer': 'decided, disputed', 'quotes': []}}}
    assert _runs(pipeline, scan, 'L8_relief_kind', at_issue)[0] is True
    assert _runs(pipeline, scan, 'L8_relief_kind', {'L8_relief': {'level': {'answer': 'not at issue', 'quotes': []}}})[0] is False


def test_each_challenged_condition_gets_its_own_answers():
    pipeline = build(THRESHOLDS)
    steps = {'L7a': {'answer': {'stated': _quoted('yes')}},
             'L7d': {'answer': {'each': [{'item': 'a recreational easement', 'answer': {'challenged_by': _quoted('applicant or owner')}},
                                         {'item': 'a fence', 'answer': {'challenged_by': {'answer': 'municipality', 'quotes': []}}}]}},
             'L7e': {'answer': {'each': [{'item': 'a recreational easement', 'answer': {'outcome': _quoted('struck')}}]}}}
    facts = layers.resolve(pipeline, {'G1': {'yes': 0.9}}, steps)
    assert facts['conditions_challenged_by']['answer'] == [{'condition': 'a recreational easement',
                                                            'challenged_by': 'applicant or owner'}]
    assert facts['conditions_challenged_by']['dropped'] == 1
    assert facts['conditions_outcome']['answer'] == [{'condition': 'a recreational easement', 'outcome': 'struck'}]


def test_a_challenged_condition_needs_a_quote():
    kind = build(THRESHOLDS).nodes['L7c'].returns
    assert kind.validate({'conditions': [{'answer': 'a fence', 'quotes': []}]}, '') == [
        'conditions[0].quotes: an answer other than "not stated" needs at least one quote']


def test_an_out_of_scope_row_keeps_only_its_scope_values():
    pipeline = build(THRESHOLDS)
    facts = layers.resolve(pipeline, {'S1': {'municipal enforcement': 1.0},
                                      'T1': {'approved': 0.9, 'denied': 0.1}}, {}, '12-1-20 Vtec')
    derived = layers.derive(pipeline, facts)
    assert derived['in_scope'] is False and facts['town_decision']['answer'] == 'approved'      # the trace keeps it
    out = layers.row(pipeline, '12-1-20 Vtec', facts, derived)
    assert out['proceeding'] == 'municipal enforcement' and out['in_scope'] is False
    assert out['town_decision'] == 'out of scope' and out['last_permission'] == 'out of scope'


def test_a_docket_with_several_proceedings_counts_when_one_is_a_municipal_permit():
    pipeline = build(THRESHOLDS)
    scan = {'S1': {'several, including a municipal permit application': 0.9, 'Act 250 permit': 0.1},
            'S2': {'build a new structure': 1.0}, 'S3': {'yes': 1.0}, 'S4': {'adds': 1.0}}
    assert layers.plan(pipeline, scan)['gates']['scope']['passed']
    derived = layers.derive(pipeline, layers.resolve(pipeline, scan, {}, '12-1-20 Vtec'))
    assert derived['in_scope'] is True


def test_a_town_off_the_list_is_sent_back_with_the_names_meant():
    from appeals.codebook.steps import TOWN
    assert len(TOWN.names) == 256 and TOWN.validate('St. Johnsbury', 't') == [] and TOWN.validate(NOT_STATED, 't') == []
    assert 'you wrote "Saint Johnsbury"' in TOWN.validate('Saint Johnsbury', 't')[0]
    assert 'Did you mean "St. Johnsbury"?' in TOWN.validate('Saint Johnsbury', 't')[0]
    assert 'Did you mean "Rutland City" or "Rutland Town"?' in TOWN.validate('Rutland', 't')[0]
    assert 'Did you mean "Rutland City"?' in TOWN.validate('City of Rutland', 't')[0]
    assert 'as the state writes it' in TOWN.validate('Quechee', 't')[0]          # a village: no town to suggest
    quoted = Quoted(TOWN)
    assert 'needs at least one quote' in quoted.validate({'answer': 'Norwich', 'quotes': []}, 't')[0]
    model = _Scripted(['{"town": "Saint Johnsbury"}', '{"town": "St. Johnsbury"}'])
    reply = asyncio.run(model.ask('sys', 'base', [], 'Which town?', Record(town=TOWN)))
    assert reply.answer == {'town': 'St. Johnsbury'} and 'Did you mean "St. Johnsbury"?' in model.seen[1][-1]['text']


def test_lawyers_are_asked_per_appellant_and_become_one_entry_per_lawyer():
    pipeline = build(THRESHOLDS)
    step = pipeline.nodes['L4b']
    assert step.for_each == (pipeline.nodes['L4a'], 'appellants') and step.limit == 10
    assert step.item_text({'name': 'Lynne Stern', 'role': 'individual neighbor'}) == 'Lynne Stern (individual neighbor)'
    listed = [{'answer': {'name': 'Ann', 'role': 'individual neighbor'}, 'quotes': [{'verified': True}]},
              {'answer': {'name': 'Unquoted', 'role': 'other'}, 'quotes': [{'verified': False}]},
              {'answer': {'name': 'Bo', 'role': 'individual neighbor'}, 'quotes': [{'verified': True}]}]
    assert [i['name'] for i in layers.each_items(step, {'L4a': {'answer': {'appellants': listed}}})] == ['Ann', 'Bo']
    lawyered = {'representation': _quoted('represented by a lawyer'),
                'lawyers': [{'name': 'Kevin Candon', 'firm': 'not stated'}, {'name': 'Jo Roe', 'firm': 'Roe LLP'}]}
    steps = {'L4b': {'answer': {'each': [{'item': listed[0]['answer'], 'answer': lawyered},
                                         {'item': listed[2]['answer'],
                                          'answer': {'representation': _quoted('self-represented'), 'lawyers': []}}]},
                     'items': 2, 'asked': 2}}
    fact = layers.resolve(pipeline, {}, steps)['appellant_lawyers']
    assert [(e['appellant'], e['lawyer']) for e in fact['answer']] == [('Ann', 'Kevin Candon'), ('Ann', 'Jo Roe'),
                                                                      ('Bo', 'not stated')]
    from appeals.codebook.derived import appellant_mix
    mix = appellant_mix({'appellants': [listed[0]['answer'], listed[2]['answer']], 'appellants_named': 'yes',
                         'appellant_lawyers': fact['answer']})
    assert mix['representation'] == {'represented by a lawyer': 1, 'self-represented': 1} and mix['representation_of'] == 2


def test_dates_must_be_real_and_plausible():
    kind = DateValue()
    assert kind.validate('2019-05-31', 'd') == [] and kind.validate('2019', 'd') == [] and kind.validate(NOT_STATED, 'd') == []
    assert 'outside 1990' in kind.validate('0022-03-31', 'd')[0]
    assert 'not a calendar date' in kind.validate('2019-02-30', 'd')[0]
    assert 'not a calendar date' in kind.validate('2019-13', 'd')[0]
    assert 'expected YYYY' in kind.validate('31/05/2019', 'd')[0]


def test_a_court_upholding_a_partial_approval_did_not_change_the_outcome():
    from appeals.codebook.derived import court_changed_outcome, last_permission
    v = {'town_decision': 'approved in part', 'how_ended': 'decided on the merits', 'court_result': 'granted in part',
         'units_vs_town': 'same'}
    assert court_changed_outcome(v) == 'no'
    assert last_permission(v) == 'allowed in part'
    assert court_changed_outcome(v | {'court_result': 'granted'}) == 'yes'
