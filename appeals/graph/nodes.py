"""The building blocks of the extraction graph.

Every node is a plain declaration: its text, options, condition, template or
function. The executor has one generic behavior per kind of node, so what a
node says in the dashboard is all it does.

Layers (a node reads only from earlier layers, except where noted):
    1 scan    Question, YesNoSet, ChoiceSet (asked together by the Scan)
    2 plan    Gate
    3 steps   Base, Step (a step may chain after earlier steps)
    4 facts   Field
    5 derive  Derive (may read earlier derives)

The facts and derived values are the pipeline's output: one row per docket.
"""
from dataclasses import dataclass, field
import inspect
import re
import textwrap
from typing import Callable, ClassVar

from appeals.graph import expr as E
from appeals.graph.values import NOT_STATED, OneOf, Record, ValueType, YesNo

LAYERS = ['input', 'scan', 'plan', 'steps', 'facts', 'derive']
LAYER_GUIDE = {
    'input': 'The docket text: every document whose heading names the docket, in posting order, marked by document '
             'and page so quotes can cite them.',
    'scan': 'One decision-model request answers every closed question at once with probabilities. The questions '
            "can't see each other's answers. No quotes.",
    'plan': 'Gates are conditions over the scan\'s probabilities and the thresholds. They decide whether the docket '
            'goes on to the reasoning steps, and which steps run.',
    'steps': 'One reasoning-model call per step, each appending one small question to a shared Base (framing, the '
             'docket text and the scan\'s answers as claims to confirm or refute). Each reply is JSON of the step\'s '
             'type, with quotes that code checks against the cited page. A step may keep earlier steps\' exchanges '
             'in context (after) or run only if their answers call for it (only_if).',
    'facts': 'One settled value per field: the step\'s answer when its quote checks out, otherwise the scan\'s most '
             'likely answer, otherwise "not stated". A rule can make a field "not stated" when an earlier answer '
             'makes it moot.',
    'derive': 'Plain code combines settled fields into derived values, such as a duration in days. No model is '
              'involved; the source code is part of the description.',
}
SCOPE = 'scope'       # the topic whose values every docket's row reports, in scope or not
PLACEHOLDER = re.compile(r'\{([A-Z][A-Za-z0-9_]*(?:\.[a-z_]+)?)\}')


@dataclass(eq=False)
class Node:
    id: str
    topic: str | None             # what it's about (codebook/topics.py); None for the scan and the base
    kind: ClassVar[str] = 'node'
    layer: ClassVar[int] = 0

    def refs(self):
        """IDs of the nodes this node reads."""
        return set()

    def describe(self):
        return {'id': self.id, 'kind': self.kind, 'topic': self.topic, 'layer': LAYERS[self.layer]}


# ---- layer 1: the scan -----------------------------------------------------------

@dataclass(eq=False)
class Question(Node):
    """One closed question for the decision model.

    `options` maps each option to its meaning.
    """
    ask: str = ''
    options: dict = field(default_factory=dict)
    why: str = ''
    yes_no: bool = False
    kind: ClassVar[str] = 'question'
    layer: ClassVar[int] = 1

    def __post_init__(self):
        if self.yes_no and not self.options:
            self.options = {'yes': 'Yes.', 'no': 'No.'}

    def p(self, option):
        return E.P(self, option)

    def is_(self, option):
        return E.Is(self, option)

    def value_type(self):
        return OneOf(self.options, not_stated=False)

    def request(self, docket):
        """This question in the decision model's terms."""
        if self.yes_no:
            return {'type': 'yes_no', 'instructions': self.ask,
                    'criteria': {'true': self.options['yes'], 'false': self.options['no']}}
        return {'type': 'choice', 'instructions': self.ask, 'criteria': self.options}

    def describe(self):
        d = super().describe() | {'ask': self.ask, 'why': self.why,
                                  'question_type': 'yes/no' if self.yes_no else 'choice'}
        return d | {'options': self.options}


@dataclass(eq=False)
class YesNoSet(Node):
    """One prompt asked as a separate yes/no question per item (shown as one node)."""
    ask: str = ''
    items: dict = field(default_factory=dict)
    why: str = ''
    kind: ClassVar[str] = 'question set'
    layer: ClassVar[int] = 1

    def questions(self):
        return [Question(f'{self.id}.{key}', self.topic, ask=f'{self.ask} Item: {meaning}', yes_no=True,
                         options={'yes': f'Yes: {meaning}', 'no': f'No, not {key}.'}) for key, meaning in self.items.items()]

    def ids(self):
        return [f'{self.id}.{key}' for key in self.items]

    def p(self, key):
        """The scan's probability that one item is "yes"."""
        return E.P(f'{self.id}.{key}', 'yes')

    def describe(self):
        return super().describe() | {'ask': self.ask, 'why': self.why, 'question_type': f'yes/no ×{len(self.items)}',
                                     'options': self.items}


@dataclass(eq=False)
class ChoiceSet(Node):
    """One choice question asked separately per item, every item with the same options (shown as one node).

    `ask` contains {item}, replaced by each item's meaning. `null` names the option that means the item
    doesn't apply (such as "not at issue"); the chance an item applies is one minus its probability.
    """
    ask: str = ''
    items: dict = field(default_factory=dict)
    options: dict = field(default_factory=dict)
    null: str = ''
    why: str = ''
    kind: ClassVar[str] = 'choice set'
    layer: ClassVar[int] = 1

    def questions(self):
        return [Question(f'{self.id}.{key}', self.topic, ask=self.ask.format(item=meaning), options=self.options)
                for key, meaning in self.items.items()]

    def ids(self):
        return [f'{self.id}.{key}' for key in self.items]

    def p(self, key, option):
        """The scan's probability that one item's answer is `option`."""
        return E.P(f'{self.id}.{key}', option)

    def applies(self, key):
        """The scan's probability that one item applies: one minus the probability of `null`."""
        return 1 - self.p(key, self.null)

    def describe(self):
        return super().describe() | {'ask': self.ask, 'why': self.why,
                                     'question_type': f'choice ×{len(self.items)}',
                                     'options': self.items, 'choices': self.options, 'null': self.null}


@dataclass(eq=False)
class Scan(Node):
    """Every question, sent to the decision model in one request over the docket text."""
    questions: list = field(default_factory=list)
    kind: ClassVar[str] = 'scan'
    layer: ClassVar[int] = 1

    def flat(self):
        """Every individual Question, with sets expanded."""
        out = []
        for q in self.questions:
            out.extend(q.questions() if isinstance(q, (YesNoSet, ChoiceSet)) else [q])
        return out

    def describe(self):
        return super().describe() | {'questions': [q.id for q in self.questions]}


# ---- layer 2: the plan -----------------------------------------------------------

@dataclass(eq=False)
class Gate(Node):
    """A condition over the scan's answers. It passes or it doesn't."""
    title: str = ''
    when: E.Expr = None
    why: str = ''
    kind: ClassVar[str] = 'gate'
    layer: ClassVar[int] = 2

    def refs(self):
        return self.when.refs()

    def passed(self):
        return E.Passed(self)

    def describe(self):
        return super().describe() | {'title': self.title, 'condition': self.when.text(), 'why': self.why}


# ---- layer 3: steps --------------------------------------------------------------

@dataclass(eq=False)
class Base(Node):
    """The shared start of every reasoning-model call for a docket: framing, docket text, scan claims.

    Every scan answer is a claim here, not only those a step checks: the claims are a map of the docket that the
    steps lean on (dropping them, tried in October 2026, cost accuracy and doubled the grounds steps' reasoning).
    A step also states the claims it checks in its own question.
    """
    framing: str = ''
    kind: ClassVar[str] = 'base'
    layer: ClassVar[int] = 3

    def refs(self):
        return {'scan'}

    def render(self, docket_text, claims):
        return (f'{self.framing.strip()}\n\n{docket_text}\n\n<scan>\n'
                'The scan: the decision model\'s first reading of this docket. Each answer below, and each one a '
                'question repeats, is a claim to confirm or refute from the text, never to repeat without checking. '
                '"Fairly confident" and "uncertain" say how sure the scan was; a confident claim can still be wrong.'
                f'\n\n{claims}\n</scan>')

    def describe(self):
        return super().describe() | {'framing': self.framing.strip(),
                                     'includes': ['framing', 'the docket text', 'the scan\'s answers as claims']}


@dataclass(eq=False)
class Step(Node):
    """One reasoning-model call: a question appended to the Base, answered as JSON of type `returns`.

    `when` is the gate that must pass (None: every docket that proceeds).
    `only_if`: a further condition on the scan or on earlier steps' answers, checked just before
    the step would run; when false, the step is skipped.
    `variants` maps variant names to prompts, chosen by `choose`; otherwise `prompt`.
    `after`: the step this one follows in a chain. Its exchange, and the exchanges it kept in
    context, stay in context here, for each step on the line that ran.
    `halt_unless`: a condition on this step's answer; when false, later steps don't run.
    `for_each`: (step, path) of an earlier step's list. The step then runs once per item with a
    verified quote, at most `limit` times, with `{item}` in the prompt replaced by `item`
    filled from that item's answer, such as "{name} ({role})". Each iteration starts from the
    same context and doesn't see the others. No step may follow a for-each step.
    `set_item`: (scan set, item key) when the step settles one item of a scan set, such as (G2, 'water');
    the steps settling one set's items are a family, asked the same way and independent of each other.
    `short_title`: the step's name where its family or chain already says the rest, such as "water and
    environment" for "Grounds: water and environment", or "result" for a follow-up.
    """
    title: str = ''
    when: Gate | None = None
    only_if: E.Expr | None = None
    prompt: str = ''
    variants: dict = field(default_factory=dict)
    choose: E.Expr | None = None
    returns: Record = None
    after: 'Step | None' = None
    halt_unless: E.Expr | None = None
    confirms: list = field(default_factory=list)   # set by the pipeline: the scan questions it checks
    for_each: tuple | None = None
    item: str = ''
    limit: int | None = None
    set_item: tuple | None = None
    short_title: str = ''
    kind: ClassVar[str] = 'step'
    layer: ClassVar[int] = 3

    def templates(self):
        return self.variants or {'': self.prompt}

    def line(self):
        """The steps this one follows, from the start of its chain to the step just before it."""
        return [*self.after.line(), self.after] if self.after else []

    def placeholders(self):
        return {m for t in self.templates().values() for m in PLACEHOLDER.findall(t)}

    def refs(self):
        refs = {'base'} | self.placeholders()
        if self.when:
            refs.add(self.when.id)
        if self.choose:
            refs |= self.choose.refs()
        if self.only_if:
            refs |= self.only_if.refs()
        if self.after:
            refs.add(self.after.id)
        if self.for_each:
            refs.add(self.for_each[0].id)
        return refs

    def item_text(self, item):
        """The text that replaces {item} in the prompt, from one item's answer."""
        return self.item.format(**item) if isinstance(item, dict) else str(item)

    def describe(self):
        return super().describe() | {
            'title': self.title,
            'when': self.when.id if self.when else None,
            'when_text': self.when.when.text() if self.when else 'every docket that proceeds',
            'only_if': self.only_if.text() if self.only_if else None,
            'prompt': self.prompt or None,
            'variants': self.variants or None,
            'choose': self.choose.text() if self.choose else None,
            'returns': self.returns.describe(),
            'schema': self.returns.schema(),
            'after': self.after.id if self.after else None,
            'context': [s.id for s in self.line()],
            'halt_unless': self.halt_unless.text() if self.halt_unless else None,
            'confirms': self.confirms,
            'for_each': (f'{self.for_each[0].id}.{self.for_each[1]}' if self.for_each else None),
            'item': self.item or None, 'limit': self.limit,
            'set_item': {'set': self.set_item[0].id, 'item': self.set_item[1]} if self.set_item else None,
            'short_title': self.short_title or None,
        }


# ---- layer 4: facts --------------------------------------------------------------

@dataclass(eq=False)
class Field(Node):
    """One settled value per docket.

    Sources, in order: the step's answer at `path` (when the step ran and its
    quotes check out), then the scan's most likely answer to `scan`, then "not stated".
    A yes/no set takes each item from its own step: `steps` maps item keys to steps.
    `from_docket` instead computes the value from the docket number, in code.
    `per_item`, for a for-each step: a function (item, answer) turning one iteration into the
    field's list entries; `path` then names the quoted answer that must check out.
    `vouched_by`: for a value at `path` that is not quoted itself, the path of the quoted answer
    in the same step that must check out before the value is used, such as a result that rests
    on the ruling quoted for the level. `vouchers` maps item keys to the steps holding that quoted
    answer, when it is another step (one earlier in the chain); by default it is the item's own step.
    `if_skipped`: the value when the item's step was skipped because its condition was not met, provided
    its voucher checks out, such as "not decided" for a result asked only of a decided level.
    `not_stated_if`: a condition on earlier answers that makes the field "not stated"
    whatever the sources say, such as grounds when no arguments are stated.
    `scan_if_unsure`: when the step answers "not stated", keep the scan's answer instead, such as for scope,
    where a step that can't tell should not take a docket out of the study.
    `notes`: what a reader of the data must know to use the value correctly.
    """
    label: str = ''
    type: ValueType = None
    scan: Question | YesNoSet | ChoiceSet | None = None
    step: Step | None = None
    steps: dict = field(default_factory=dict)
    path: str | None = None
    from_docket: Callable | None = None
    per_item: Callable | None = None
    vouched_by: str | None = None
    vouchers: dict = field(default_factory=dict)
    if_skipped: str | None = None
    not_stated_if: E.Expr | None = None
    scan_if_unsure: bool = False
    notes: list = field(default_factory=list)
    kind: ClassVar[str] = 'field'
    layer: ClassVar[int] = 4

    def item_steps(self):
        """{item key or '': step} for every step this field reads."""
        return dict(self.steps) if self.steps else ({'': self.step} if self.step else {})

    def refs(self):
        refs = {s.id for s in self.item_steps().values()} | {s.id for s in self.vouchers.values()}
        if self.scan:
            refs.add(self.scan.id)
        if self.not_stated_if:
            refs |= self.not_stated_if.refs()
        return refs

    def describe(self):
        if self.from_docket:
            rule = 'computed from the docket number'
        elif self.per_item:
            rule = (f'one entry per {self.step.for_each[1]} item the step was asked about, from its answer '
                    f'when {self.path} has a verified quote')
        elif self.steps:
            fallback = ('else the scan\'s most likely answer' if isinstance(self.scan, ChoiceSet)
                        else 'else the scan\'s answer at the threshold' if self.scan else 'else "not stated"')
            voucher = (f'when {", ".join(s.id for s in self.vouchers.values())}.{self.vouched_by} has a verified quote'
                       if self.vouchers else f'when its {self.vouched_by} has a verified quote')
            quoted = voucher if self.vouched_by else 'with a verified quote'
            rule = f'each item: its step\'s answer {quoted} when the step ran, {fallback}'
            if self.if_skipped is not None:
                rule += f'; "{self.if_skipped}" when the step was skipped because its condition was not met'
        elif self.step and self.scan:
            rule = 'step answer with a verified quote, else the scan\'s most likely answer, else "not stated"'
        elif self.step:
            rule = 'step answer with a verified quote, else "not stated"'
        else:
            rule = 'the scan\'s most likely answer'
        if self.not_stated_if:
            rule += f'; "not stated" when {self.not_stated_if.text()}'
        d = super().describe() | {
            'label': self.label, 'value_type': self.type.describe(), 'scored': self.type.scored,
            'from_step': (', '.join(f'{s.id}.{self.path}' for s in self.steps.values()) if self.steps
                          else f'{self.step.id}.{self.path}' if self.step else None),
            'from_scan': self.scan.id if self.scan else None,
            'vouched_by': (', '.join(f'{s.id}.{self.vouched_by}' for s in self.vouchers.values())
                           if self.vouchers else self.vouched_by),
            'if_skipped': self.if_skipped,
            'not_stated_if': self.not_stated_if.text() if self.not_stated_if else None,
            'scan_if_unsure': self.scan_if_unsure,
            'rule': rule, 'notes': self.notes}
        if self.from_docket:
            d['source'] = textwrap.dedent(inspect.getsource(self.from_docket))
        if self.per_item:
            d['source'] = textwrap.dedent(inspect.getsource(self.per_item))
        return d


# ---- layer 5: derive -------------------------------------------------------------

@dataclass(eq=False)
class Derive(Node):
    """A plain function of settled fields: f({input id: answer}) → answer. Its source is shown in the dashboard.

    `notes`: what a reader of the data must know to use the value correctly.
    """
    label: str = ''
    type: ValueType = None
    inputs: list = field(default_factory=list)
    fn: Callable = None
    notes: list = field(default_factory=list)
    kind: ClassVar[str] = 'derive'
    layer: ClassVar[int] = 5

    def refs(self):
        return {n.id for n in self.inputs}

    def source(self):
        return textwrap.dedent(inspect.getsource(self.fn))

    def describe(self):
        return super().describe() | {'label': self.label, 'value_type': self.type.describe(),
                                     'scored': self.type.scored, 'inputs': [n.id for n in self.inputs],
                                     'source': self.source(), 'notes': self.notes}


__all__ = ['Node', 'Question', 'YesNoSet', 'ChoiceSet', 'Scan', 'Gate', 'Base', 'Step', 'Field', 'Derive',
           'LAYERS', 'NOT_STATED', 'YesNo', 'OneOf', 'Record']
