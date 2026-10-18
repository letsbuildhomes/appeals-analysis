"""Expressions: conditions and small calculations written as objects, not functions.

An expression can evaluate itself against a docket's answers, print itself
as text for the dashboard, and list the nodes it reads (which become edges in
the graph). Build them with operators:

    P(G1, 'yes') >= T.grounds           P(S1, 'yes') * P(S4, 'yes')
    Is(G1, 'yes') & (… | …)             1 - P(S3, 'no physical change')
"""
import operator


class Context:
    """What expressions read: the scan, thresholds, gate outcomes and step results.

    `trace`, when a list, collects (text, value) for every leaf evaluated.
    """

    def __init__(self, scan=None, thresholds=None, gates=None, steps=None, trace=None):
        self.scan = scan or {}
        self.thresholds = thresholds or {}
        self.gates = gates or {}
        self.steps = steps or {}
        self.trace = trace

    def note(self, text, value):
        if self.trace is not None:
            self.trace.append({'term': text, 'value': value})
        return value


def wrap(value):
    return value if isinstance(value, Expr) else Const(value)


class Expr:
    def evaluate(self, ctx):
        raise NotImplementedError

    def text(self):
        raise NotImplementedError

    def refs(self):
        return set()

    def __and__(self, other):
        return And(self, wrap(other))

    def __or__(self, other):
        return Or(self, wrap(other))

    def __invert__(self):
        return Not(self)

    def __ge__(self, other):
        return Compare(self, '≥', wrap(other))

    def __gt__(self, other):
        return Compare(self, '>', wrap(other))

    def __le__(self, other):
        return Compare(self, '≤', wrap(other))

    def __lt__(self, other):
        return Compare(self, '<', wrap(other))

    def __mul__(self, other):
        return Arith(self, '×', wrap(other))

    def __add__(self, other):
        return Arith(self, '+', wrap(other))

    def __sub__(self, other):
        return Arith(self, '−', wrap(other))

    def __rsub__(self, other):
        return Arith(wrap(other), '−', self)

    def __rmul__(self, other):
        return Arith(wrap(other), '×', self)

    def __radd__(self, other):
        return Arith(wrap(other), '+', self)


class Const(Expr):
    def __init__(self, value):
        self.value = value

    def evaluate(self, ctx):
        return self.value

    def text(self):
        return repr(self.value) if isinstance(self.value, str) else f'{self.value:g}' if isinstance(self.value, float) else str(self.value)


def _id(node):
    return node if isinstance(node, str) else node.id


class P(Expr):
    """The scan's probability that a question's answer is `option`."""

    def __init__(self, question, option):
        self.question, self.option = _id(question), option

    def evaluate(self, ctx):
        return ctx.note(self.text(), round(ctx.scan.get(self.question, {}).get(self.option, 0.0), 4))

    def text(self):
        return f'P({self.question} = {self.option})'

    def refs(self):
        return {self.question}


class Is(Expr):
    """Whether the scan's most likely answer to a question is `option`."""

    def __init__(self, question, option):
        self.question, self.option = _id(question), option

    def evaluate(self, ctx):
        dist = ctx.scan.get(self.question, {})
        top = max(dist, key=dist.get) if dist else None
        return ctx.note(self.text(), top == self.option)

    def text(self):
        return f'{self.question} is {self.option}'

    def refs(self):
        return {self.question}


class Threshold(Expr):
    def __init__(self, name):
        self.name = name

    def evaluate(self, ctx):
        return ctx.note(self.text(), ctx.thresholds[self.name])

    def text(self):
        return f'T.{self.name}'


class _Thresholds:
    """`T.grounds` is the threshold named "grounds" in config.toml."""

    def __getattr__(self, name):
        return Threshold(name)


T = _Thresholds()


class Passed(Expr):
    """Whether a gate passed for this docket."""

    def __init__(self, gate):
        self.gate = _id(gate)

    def evaluate(self, ctx):
        return ctx.note(self.text(), bool(ctx.gates.get(self.gate, {}).get('passed')))

    def text(self):
        return f'gate {self.gate} passed'

    def refs(self):
        return {self.gate}


class StepAnswer(Expr):
    """A step's answer at a dotted path (the "answer" of a quoted value)."""

    def __init__(self, step, path):
        self.step, self.path = _id(step), path

    def evaluate(self, ctx):
        value = ctx.steps.get(self.step)
        for part in self.path.split('.'):
            value = value.get(part) if isinstance(value, dict) else None
        if isinstance(value, dict) and 'answer' in value:
            value = value['answer']
        return ctx.note(self.text(), value)

    def text(self):
        return f'{self.step}.{self.path}'

    def refs(self):
        return {self.step}

    def is_(self, value):
        return Compare(self, '=', Const(value))

    def in_(self, values):
        return In(self, list(values))


class In(Expr):
    def __init__(self, left, values):
        self.left, self.values = left, values

    def evaluate(self, ctx):
        return self.left.evaluate(ctx) in self.values

    def text(self):
        return f'{self.left.text()} in {self.values}'

    def refs(self):
        return self.left.refs()


OPS = {'≥': operator.ge, '>': operator.gt, '≤': operator.le, '<': operator.lt, '=': operator.eq,
       '×': operator.mul, '+': operator.add, '−': operator.sub}


class Compare(Expr):
    def __init__(self, left, op, right):
        self.left, self.op, self.right = left, op, right

    def evaluate(self, ctx):
        a, b = self.left.evaluate(ctx), self.right.evaluate(ctx)
        return a is not None and b is not None and OPS[self.op](a, b)

    def text(self):
        return f'{self.left.text()} {self.op} {self.right.text()}'

    def refs(self):
        return self.left.refs() | self.right.refs()


class Arith(Expr):
    def __init__(self, left, op, right):
        self.left, self.op, self.right = left, op, right

    def evaluate(self, ctx):
        return round(OPS[self.op](self.left.evaluate(ctx), self.right.evaluate(ctx)), 4)

    def text(self):
        def side(e):
            return f'({e.text()})' if isinstance(e, Arith) and e.op in '+−' and self.op == '×' else e.text()
        return f'{side(self.left)} {self.op} {side(self.right)}'

    def refs(self):
        return self.left.refs() | self.right.refs()


class Max(Expr):
    def __init__(self, *terms):
        self.terms = [wrap(t) for t in terms]

    def evaluate(self, ctx):
        return max(t.evaluate(ctx) for t in self.terms)

    def text(self):
        return f'max({", ".join(t.text() for t in self.terms)})'

    def refs(self):
        return set().union(*(t.refs() for t in self.terms))


class And(Expr):
    def __init__(self, *terms):
        self.terms = terms

    def evaluate(self, ctx):
        return all([t.evaluate(ctx) for t in self.terms])   # evaluate every term so the trace is complete

    def text(self):
        return ' and '.join(f'({t.text()})' if isinstance(t, Or) else t.text() for t in self.terms)

    def refs(self):
        return set().union(*(t.refs() for t in self.terms))


class Or(Expr):
    def __init__(self, *terms):
        self.terms = terms

    def evaluate(self, ctx):
        return any([t.evaluate(ctx) for t in self.terms])

    def text(self):
        return ' or '.join(f'({t.text()})' if isinstance(t, And) else t.text() for t in self.terms)

    def refs(self):
        return set().union(*(t.refs() for t in self.terms))


class Not(Expr):
    def __init__(self, term):
        self.term = term

    def evaluate(self, ctx):
        return not self.term.evaluate(ctx)

    def text(self):
        return f'not ({self.term.text()})'

    def refs(self):
        return self.term.refs()


class If(Expr):
    """Choose between two values, e.g. a step's prompt variant."""

    def __init__(self, condition, then, otherwise):
        self.condition, self.then, self.otherwise = condition, wrap(then), wrap(otherwise)

    def evaluate(self, ctx):
        return self.then.evaluate(ctx) if self.condition.evaluate(ctx) else self.otherwise.evaluate(ctx)

    def text(self):
        return f'if {self.condition.text()} then {self.then.text()} else {self.otherwise.text()}'

    def refs(self):
        return self.condition.refs()
