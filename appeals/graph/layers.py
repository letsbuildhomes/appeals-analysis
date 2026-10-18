"""The layers between the scan and the research row, as pure functions.

Each layer reads only the records above it and returns one plain record:

    ScanResult  {question id: {option: probability}}
    Plan        gate outcomes (with the numbers used), whether the docket proceeds,
                and the steps to run with their variants
    StepResult  per step: prompt, reply, parsed answer, quote checks
    Facts       {field id: {answer, quotes, source, probability, conflict}}
    Derived     {derive id: answer}
    Row         the flat research row

The executor (run.py) calls these in order and stores what they return.
"""
import re

from appeals.graph import expr as E
from appeals.graph.nodes import ChoiceSet, YesNoSet
from appeals.graph.values import NONE_FOUND, NOT_STATED, OUT_OF_SCOPE, ListOf


# ---- scan -> base and step prompts -----------------------------------------------------------

def top(dist):
    return max(dist, key=dist.get) if dist else None


def confidence(pipeline, dist, best):
    """How sure the scan was of its answer, in words: its probability against the `sure` threshold."""
    return 'fairly confident' if dist.get(best, 0) >= pipeline.thresholds['sure'] else 'uncertain'


def _answered(pipeline, ask, dist):
    """A scan question and its answer, in words: the question, then what the scan answered and how sure it was."""
    best = top(dist)
    ask = ask if ask.rstrip().endswith(('.', '?')) else f'{ask.rstrip()}.'
    return f'{ask} The scan answered "{best}" and was {confidence(pipeline, dist, best)}.' if best else ask


def claims(pipeline, scan):
    """The scan's answers as a list, one question per line, for the Base."""
    return '\n'.join(f'- {_answered(pipeline, q.ask, scan[q.id])}' for q in pipeline.scan.flat() if scan.get(q.id))


def claim(pipeline, scan, ref):
    """One placeholder in a step prompt: the scan's question and its answer, in words (no question IDs)."""
    node = pipeline.nodes.get(ref)
    if isinstance(node, YesNoSet):
        flagged = [k for k in node.items if scan.get(f'{node.id}.{k}', {}).get('yes', 0) >= pipeline.thresholds['check']]
        return f'{node.ask} The scan flagged: {", ".join(flagged) or "none"}.'
    if isinstance(node, ChoiceSet):
        read = '; '.join(f'{k}: {top(scan.get(f"{node.id}.{k}", {}))}' for k in node.items)
        return f'The scan read: {read}.'
    dist = scan.get(ref, {})
    owner = pipeline.nodes.get(ref.split('.')[0])
    if isinstance(owner, ChoiceSet):            # the step asks the question itself: name the likeliest answer that applies
        best = top({k: v for k, v in dist.items() if k != owner.null})
        return best or 'no answer'
    question = next((q for q in pipeline.scan.flat() if q.id == ref), None)
    return _answered(pipeline, question.ask if question else ref, dist)


# ---- plan ----------------------------------------------------------------------------

def plan(pipeline, scan):
    """Evaluate every gate, decide whether the docket proceeds, and list the steps to run.

    A step's `only_if` is settled here when it reads only the scan; one that reads
    earlier steps' answers is marked `depends` and checked just before the step runs.
    """
    gates = {}
    for gate in pipeline.gates:
        trace = []
        ctx = E.Context(scan=scan, thresholds=pipeline.thresholds, gates=gates, trace=trace)
        gates[gate.id] = {'passed': bool(gate.when.evaluate(ctx)), 'condition': gate.when.text(), 'terms': trace}
    ctx = E.Context(scan=scan, thresholds=pipeline.thresholds, gates=gates, trace=[])
    proceeds = bool(pipeline.proceed.evaluate(ctx))
    step_ids = {s.id for s in pipeline.steps}
    steps = []
    for step in pipeline.steps:
        runs = proceeds and (step.when is None or gates[step.when.id]['passed'])
        reason = 'runs' if runs else 'docket does not proceed' if not proceeds else f'gate {step.when.id} did not pass'
        entry = {'step': step.id, 'runs': runs, 'variant': '', 'reason': reason}
        if runs and step.only_if is not None:
            if step.only_if.refs() & step_ids:
                entry['depends'] = step.only_if.text()
            else:
                trace = []
                ok = bool(step.only_if.evaluate(E.Context(scan=scan, thresholds=pipeline.thresholds, gates=gates,
                                                          trace=trace)))
                entry.update(runs=ok, terms=trace, reason='runs' if ok else f'condition not met: {step.only_if.text()}')
        if entry['runs'] and step.choose is not None:
            entry['variant'] = step.choose.evaluate(E.Context(scan=scan, thresholds=pipeline.thresholds, gates=gates))
        steps.append(entry)
    return {'gates': gates, 'proceeds': proceeds, 'proceed_condition': pipeline.proceed.text(),
            'proceed_terms': ctx.trace, 'steps': steps,
            'calls': sum(s['runs'] for s in steps)}


def condition_met(pipeline, step, scan, gates, answers):
    """Whether a step's `only_if` holds, given earlier steps' answers. Returns (met, trace)."""
    trace = []
    ctx = E.Context(scan=scan, thresholds=pipeline.thresholds, gates=gates, steps=answers, trace=trace)
    return bool(step.only_if.evaluate(ctx)), trace


# ---- steps ---------------------------------------------------------------------------

def render_prompt(pipeline, step, variant, scan):
    """The exact question appended to the Base for this step."""
    template = step.templates()[variant or '']
    body = re.sub(r'\{([A-Z][A-Za-z0-9_]*(?:\.[a-z_]+)?)\}', lambda m: claim(pipeline, scan, m.group(1)), template)
    return body.strip()


def _norm(text):
    text = text.replace('’', "'").replace('‘', "'").replace('“', '"').replace('”', '"')
    return ' '.join(re.sub(r'[^\w\s\'".,;:()-]', ' ', text.casefold()).split())


def verify_quotes(value, docket):
    """Mark each {"doc", "page", "quote"} in a step's answer as verified when the quote is on that page.

    Returns (value with "verified" added to each quote, checked, verified).
    """
    counts = {'checked': 0, 'verified': 0}

    def walk(node):
        if isinstance(node, dict):
            if {'doc', 'page', 'quote'} <= set(node):
                page = docket.page_text(node['doc'], node['page']) or ''
                ok = bool(node['quote'].strip()) and _norm(node['quote']) in _norm(page)
                counts['checked'] += 1
                counts['verified'] += ok
                return {**node, 'verified': ok}
            return {k: walk(v) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    return walk(value), counts['checked'], counts['verified']


def halts(step, answers):
    """Whether a step's answer stops the later steps (its halt_unless is false). `answers`: every answer so far."""
    if step.halt_unless is None:
        return False
    return not step.halt_unless.evaluate(E.Context(steps=answers))


def each_items(step, results):
    """The items a for-each step runs over: the earlier list's entries whose quotes check out, in order."""
    source, path = step.for_each
    listed = _at(results.get(source.id, {}).get('answer'), path)
    return [entry['answer'] for entry in listed if _quoted_ok(entry)] if isinstance(listed, list) else []


# ---- facts ---------------------------------------------------------------------------

def _at(value, path):
    for part in path.split('.'):
        value = value.get(part) if isinstance(value, dict) else None
    return value


def _quoted_ok(item, none_found=False):
    """A quoted answer counts when it is "not stated" (or "none found", where its type offers it), or has a
    verified quote."""
    unquoted = (NOT_STATED, NONE_FOUND) if none_found else (NOT_STATED,)
    return isinstance(item, dict) and 'answer' in item and (
        item['answer'] in unquoted or any(q.get('verified') for q in item.get('quotes', [])))


def _offers_none_found(step, path):
    """Whether a step's answer at `path` may be "none found" (a yes/no type that offers it)."""
    try:
        return bool(step and getattr(step.returns.at(path), 'none_found', False))
    except (KeyError, AttributeError):
        return False


def _settled(item, none_found):
    """A step's answer as a field records it: "none found", where offered, is a "no" that no passage shows."""
    return 'no' if none_found and item['answer'] == NONE_FOUND else item['answer']


def _scan_answer(scan, question):
    dist = scan.get(question.id, {})
    best = top(dist)
    return best, dist.get(best)


def resolve(pipeline, scan, steps, number=None):
    """One settled value per field: the step's verified answer, else the scan's, else "not stated"."""
    answers = {sid: r.get('answer') for sid, r in steps.items() if r.get('answer') is not None}
    facts = {}
    for f in pipeline.fields:
        if f.from_docket:
            facts[f.id] = {'answer': f.from_docket(number) if number else NOT_STATED, 'quotes': [],
                           'source': 'docket number', 'probability': None, 'conflict': False}
        elif f.per_item:
            facts[f.id] = _resolve_each(f, steps)
        elif f.steps:
            facts[f.id] = _resolve_set(f, scan, steps)
        else:
            facts[f.id] = _resolve_one(f, scan, steps)
        if f.not_stated_if is not None:
            trace = []
            if f.not_stated_if.evaluate(E.Context(scan=scan, thresholds=pipeline.thresholds, steps=answers,
                                                  trace=trace)):
                facts[f.id] = {'answer': NOT_STATED, 'quotes': [], 'source': 'rule', 'probability': None,
                               'conflict': False, 'note': f'not stated because {f.not_stated_if.text()}',
                               'overridden': facts[f.id]['answer']}
    return facts


def _resolve_one(f, scan, steps):
    step_value = None
    if f.step and steps.get(f.step.id, {}).get('answer') is not None:
        step_value = _at(steps[f.step.id]['answer'], f.path)
    scan_answer, probability = _scan_answer(scan, f.scan) if f.scan else (None, None)
    fact = {'answer': NOT_STATED, 'quotes': [], 'source': 'none', 'probability': None, 'conflict': False}
    offered = _offers_none_found(f.step, f.path)
    if isinstance(f.type, ListOf) and isinstance(step_value, list):
        items = [{**i, 'ok': _quoted_ok(i)} for i in step_value]
        fact.update(answer=[i['answer'] for i in items if i['ok']], quotes=[q for i in items for q in i['quotes']],
                    source='step', dropped=sum(not i['ok'] for i in items))
    elif _quoted_ok(step_value, offered) and not (f.scan_if_unsure and step_value['answer'] == NOT_STATED
                                                   and scan_answer is not None):
        answer = _settled(step_value, offered)
        fact.update(answer=answer, quotes=step_value['quotes'], source='step')
        if answer != step_value['answer']:
            fact['note'] = 'none found: the documents show nothing of the kind'
        fact['conflict'] = scan_answer is not None and scan_answer != answer and answer != NOT_STATED
        if scan_answer is not None:
            fact['scan_answer'], fact['probability'] = scan_answer, probability
    elif isinstance(step_value, (str, int)) and not isinstance(step_value, bool):
        fact.update(answer=step_value, source='step')            # unquoted text, e.g. a description
    elif scan_answer is not None:
        fact.update(answer=scan_answer, source='scan', probability=probability)
        if isinstance(step_value, dict) and step_value.get('answer') == NOT_STATED:
            fact['note'] = 'the step answered "not stated", so the scan\'s answer stands'
        elif step_value is not None:
            fact['note'] = 'step answer not used: no verified quote'
    return fact


def _resolve_each(f, steps):
    """A field over a for-each step: per_item's entries for every item whose answer at `path` checks out."""
    result = steps.get(f.step.id, {})
    if result.get('answer') is None:
        return {'answer': NOT_STATED, 'quotes': [], 'source': 'none', 'probability': None, 'conflict': False}
    answer, quotes, dropped = [], [], 0
    for e in result['answer']['each']:
        quoted = _at(e['answer'], f.path)
        if _quoted_ok(quoted):
            answer += f.per_item(e['item'], e['answer'])
            quotes += quoted['quotes']
        else:
            dropped += 1
    return {'answer': answer, 'quotes': quotes, 'source': 'step', 'probability': None, 'conflict': False,
            'dropped': dropped, 'items': result.get('items'), 'asked': result.get('asked')}


def _set_scan_answer(f, scan, key):
    """A set item's answer from the scan: "yes" at even odds for a yes/no set, the most likely option for a
    choice set, and "not stated" when the field has no scan question."""
    dist = scan.get(f'{f.scan.id}.{key}', {}) if f.scan else {}
    if isinstance(f.scan, ChoiceSet):
        return top(dist) or NOT_STATED
    if isinstance(f.scan, YesNoSet):
        return 'yes' if dist.get('yes', 0) >= 0.5 else 'no'
    return NOT_STATED


def _resolve_set(f, scan, steps):
    """Each item from its own step when that step ran with a verified quote, else the scan's answer."""
    answer, quotes, sources, conflicts, none_found = {}, [], {}, [], []
    for key in (f.scan.items if f.scan else f.steps):
        scan_answer = _set_scan_answer(f, scan, key)
        step = f.steps.get(key)
        value = steps.get(step.id, {}).get('answer') if step else None
        item = _at(value, f.path)
        if f.vouched_by:                      # a plain value resting on a quoted answer in the same step
            voucher = _at(value, f.vouched_by)
            item = {'answer': item, 'quotes': voucher['quotes']} if item is not None and _quoted_ok(voucher) else None
        offered = _offers_none_found(step, f.path) and not f.vouched_by
        if _quoted_ok(item, offered):
            answer[key], sources[key] = _settled(item, offered), 'step'
            if answer[key] != item['answer']:
                none_found.append(key)
            quotes += item['quotes']
            if f.scan and answer[key] not in (scan_answer, NOT_STATED):
                conflicts.append(key)
        else:
            answer[key], sources[key] = scan_answer, ('scan' if f.scan else 'none')
    fact = {'answer': answer, 'quotes': quotes, 'source': sources, 'probability': None, 'conflict': bool(conflicts),
            'conflicts': conflicts}
    if none_found:
        fact['none_found'] = none_found          # items whose "no" rests on the documents showing nothing
    return fact


# ---- derive and row --------------------------------------------------------------------

def derive(pipeline, facts):
    derived = {}
    for d in pipeline.derives:
        values = {n.id: (facts[n.id]['answer'] if n.id in facts else derived.get(n.id)) for n in d.inputs}
        try:
            derived[d.id] = d.fn(values)
        except Exception as error:                     # a derive bug must not lose the docket
            derived[d.id] = {'error': f'{type(error).__name__}: {error}'}
    return derived


def row(pipeline, docket, facts, derived):
    """The flat research row: one column per field and derived value.

    When the docket is out of scope, every value outside the scope area reads
    "out of scope": we did not study it, which is different from the documents
    being silent. Facts and derived values keep everything, for the trace.
    """
    in_scope = pipeline.in_scope is None or derived.get(pipeline.in_scope) is True
    out = {'docket': docket}
    for f in pipeline.fields:
        out[f.id] = facts[f.id]['answer'] if in_scope or f.area == 'scope' else OUT_OF_SCOPE
    for d in pipeline.derives:
        out[d.id] = derived.get(d.id) if in_scope or d.area == 'scope' else OUT_OF_SCOPE
    return out
