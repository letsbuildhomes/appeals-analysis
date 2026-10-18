"""Value types: what a question, step or field may answer.

Each type can describe itself (for the dashboard), state a JSON schema (sent
to the reasoning model), validate a reply (errors are sent back to the model),
compare two answers (for scoring) and make an example (for the fake model).
"Not stated" is a real answer for every type that allows it.
"""
import difflib
import random

from appeals import dates

NOT_STATED = 'not stated'
OUT_OF_SCOPE = 'out of scope'      # a research row's value for a docket we did not study
NONE_FOUND = 'none found'          # a step's "no" that rests on the documents showing nothing, so has no quote


class ValueType:
    scored = True
    name = 'value'

    def describe(self):
        return {'type': self.name}

    def schema(self):
        raise NotImplementedError

    def validate(self, value, path):
        """A list of readable errors; empty when the value is valid."""
        raise NotImplementedError

    def same(self, a, b):
        return a == b

    def example(self, rng):
        raise NotImplementedError


class OneOf(ValueType):
    """One option from a fixed set. `options` maps each option to its meaning."""
    name = 'one of'

    def __init__(self, options, not_stated=True):
        self.options = dict(options)
        if not_stated and NOT_STATED not in self.options:
            self.options[NOT_STATED] = 'The documents do not establish it.'

    def describe(self):
        return {'type': self.name, 'options': self.options}

    def schema(self):
        return {'enum': list(self.options)}

    def validate(self, value, path):
        if value not in self.options:
            return [f'{path}: {value!r} is not one of {list(self.options)}']
        return []

    def example(self, rng):
        return rng.choice(list(self.options))


def YesNo(not_stated=False, yes='Yes.', no='No.'):
    return OneOf({'yes': yes, 'no': no}, not_stated=not_stated)


class Count(ValueType):
    name = 'count'

    def schema(self):
        return {'anyOf': [{'type': 'integer', 'minimum': 0}, {'const': NOT_STATED}]}

    def validate(self, value, path):
        if value == NOT_STATED or (isinstance(value, int) and not isinstance(value, bool) and value >= 0):
            return []
        return [f'{path}: expected a whole number of at least 0, or "{NOT_STATED}"; got {value!r}']

    def example(self, rng):
        return rng.choice([NOT_STATED, 1, 2, 4, 12, 24])


class Integer(ValueType):
    """A whole number that may be negative, such as a difference between two counts."""
    name = 'integer'

    def schema(self):
        return {'anyOf': [{'type': 'integer'}, {'const': NOT_STATED}]}

    def validate(self, value, path):
        if value == NOT_STATED or (isinstance(value, int) and not isinstance(value, bool)):
            return []
        return [f'{path}: expected a whole number, or "{NOT_STATED}"; got {value!r}']

    def example(self, rng):
        return rng.choice([NOT_STATED, -2, 0, 3])


class Boolean(ValueType):
    """True or false, computed in code; never "not stated"."""
    name = 'true or false'

    def schema(self):
        return {'type': 'boolean'}

    def validate(self, value, path):
        return [] if isinstance(value, bool) else [f'{path}: expected true or false; got {value!r}']

    def example(self, rng):
        return rng.choice([True, False])


class DateValue(ValueType):
    """A date as precise as the documents allow: YYYY, YYYY-MM or YYYY-MM-DD, a real calendar date within
    the plausible years (appeals.dates)."""
    name = 'date'

    def schema(self):
        return {'anyOf': [{'type': 'string', 'pattern': dates.DATE.pattern}, {'const': NOT_STATED}]}

    def validate(self, value, path):
        if value == NOT_STATED:
            return []
        why = dates.problem(value)
        if why:
            return [f'{path}: {why}, or "{NOT_STATED}"; got {value!r}']
        return []

    def example(self, rng):
        return rng.choice([NOT_STATED, f'20{rng.randint(5, 24):02d}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}'])


class Text(ValueType):
    """Free text. Never scored."""
    name = 'text'
    scored = False

    def schema(self):
        return {'type': 'string'}

    def validate(self, value, path):
        return [] if isinstance(value, str) else [f'{path}: expected text; got {value!r}']

    def example(self, rng):
        return 'An example description.'


class Name(Text):
    """A proper name, such as a town. Scored ignoring case and spacing."""
    name = 'name'
    scored = True

    def same(self, a, b):
        norm = lambda s: ' '.join(str(s).casefold().split())
        return norm(a) == norm(b)

    def example(self, rng):
        return rng.choice(['Burlington', 'Stowe', 'South Burlington', NOT_STATED])


class KnownName(Name):
    """A name from a fixed list too long to show the model, such as a state's towns.

    The list is not in the prompt or the schema; code checks each answer against it. A name not on
    it is sent back with the closest names on the list, as `suggest(value)` finds them (by
    default, the nearest spellings). It describes itself as a name carrying its list, so a release
    stores it like any other name.
    """
    def __init__(self, names, what, suggest=None):
        self.names = list(names)
        self.known = set(self.names)
        self.what = what
        self.suggest = suggest or (lambda value: difflib.get_close_matches(value, self.names, n=3, cutoff=0.75))

    def describe(self):
        return {'type': self.name, 'known': {'of': self.what, 'names': self.names}}

    def validate(self, value, path):
        if value == NOT_STATED or value in self.known:
            return []
        if not isinstance(value, str):
            return [f'{path}: expected the name of {self.what}; got {value!r}']
        close = [c for c in self.suggest(value) if c in self.known]
        if close:
            quoted = [f'"{c}"' for c in close]
            options = quoted[0] if len(quoted) == 1 else f'{", ".join(quoted[:-1])} or {quoted[-1]}'
            return [f'{path}: you wrote "{value}", which is not on the official list of {self.what}. '
                    f'Did you mean {options}?']
        return [f'{path}: "{value}" is not on the official list of {self.what}. '
                f'Give the name as the state writes it, or "{NOT_STATED}".']

    def same(self, a, b):
        return a == b

    def example(self, rng):
        return rng.choice([*self.names[:5], NOT_STATED])


class Record(ValueType):
    """An object with these fields, all required."""
    name = 'record'

    def __init__(self, **fields):
        self.fields = fields

    def describe(self):
        return {'type': self.name, 'fields': {k: v.describe() for k, v in self.fields.items()}}

    def schema(self):
        return {'type': 'object', 'properties': {k: v.schema() for k, v in self.fields.items()},
                'required': list(self.fields), 'additionalProperties': False}

    def validate(self, value, path):
        if not isinstance(value, dict):
            return [f'{path or "reply"}: expected an object with keys {list(self.fields)}']
        errors = [f'{path}.{k}: missing' if path else f'{k}: missing' for k in self.fields if k not in value]
        errors += [f'{path}.{k}: not expected' if path else f'{k}: not expected' for k in value if k not in self.fields]
        for key, kind in self.fields.items():
            if key in value:
                errors += kind.validate(value[key], f'{path}.{key}' if path else key)
        return errors

    def example(self, rng):
        return {k: v.example(rng) for k, v in self.fields.items()}

    def at(self, path):
        """The value type at a dotted path."""
        kind = self
        for part in path.split('.'):
            kind = kind.fields[part]
        return kind


class ListOf(ValueType):
    """A list of items. With `not_stated`, the whole list may be "not stated": the list was never
    established, which is different from an empty list."""
    name = 'list'

    def __init__(self, item, not_stated=False):
        self.item = item
        self.not_stated = not_stated

    def describe(self):
        return {'type': self.name, 'item': self.item.describe()} | ({'not_stated': True} if self.not_stated else {})

    def schema(self):
        listed = {'type': 'array', 'items': self.item.schema()}
        return {'anyOf': [listed, {'const': NOT_STATED}]} if self.not_stated else listed

    def validate(self, value, path):
        if self.not_stated and value == NOT_STATED:
            return []
        if not isinstance(value, list):
            return [f'{path}: expected a list' + (f', or "{NOT_STATED}"' if self.not_stated else '')]
        return [e for i, v in enumerate(value) for e in self.item.validate(v, f'{path}[{i}]')]

    def same(self, a, b):
        return isinstance(a, list) and isinstance(b, list) and len(a) == len(b)

    def example(self, rng):
        return [self.item.example(rng) for _ in range(rng.randint(1, 3))]


class OrNotStated(ValueType):
    """A value of another type, or "not stated" as a whole, such as a date bound that wasn't found."""
    name = 'or not stated'

    def __init__(self, value):
        self.value = value
        self.scored = value.scored

    def describe(self):
        return {'type': self.name, 'value': self.value.describe()}

    def schema(self):
        return {'anyOf': [self.value.schema(), {'const': NOT_STATED}]}

    def validate(self, value, path):
        return [] if value == NOT_STATED else self.value.validate(value, path)

    def example(self, rng):
        return rng.choice([NOT_STATED, self.value.example(rng)])


class CountsBy(ValueType):
    """How many of something fall under each option: {option: count}, listing only options that occur."""
    name = 'counts by'

    def __init__(self, options):
        self.options = dict(options)

    def describe(self):
        return {'type': self.name, 'options': self.options}

    def schema(self):
        return {'type': 'object', 'additionalProperties': {'type': 'integer', 'minimum': 0},
                'propertyNames': {'enum': list(self.options)}}

    def validate(self, value, path):
        if not isinstance(value, dict):
            return [f'{path}: expected an object of counts by option']
        errors = [f'{path}: {k!r} is not one of {list(self.options)}' for k in value if k not in self.options]
        errors += [f'{path}.{k}: expected a whole number of at least 0; got {v!r}' for k, v in value.items()
                   if not isinstance(v, int) or isinstance(v, bool) or v < 0]
        return errors

    def example(self, rng):
        return {k: rng.randint(1, 3) for k in rng.sample(list(self.options), min(2, len(self.options)))}


QUOTE = Record(doc=Count(), page=Count(), quote=Text())


class Quoted(ValueType):
    """An answer with the quotations that support it: {"answer": …, "quotes": [{"doc", "page", "quote"}]}.

    Every answer except "not stated" needs at least one quote, except free text, which needs one only
    when `quote_required` says so (such as a challenged condition, whose quote is its evidence).
    `none_found`, for a yes/no question: adds the answer "none found", a "no" that rests on the documents
    showing nothing rather than on a passage saying so, and so needs no quote. A field records it as "no".
    """
    name = 'quoted'

    def __init__(self, answer, quote_required=None, none_found=False):
        if none_found:
            answer = OneOf({**answer.options, NONE_FOUND: 'The documents show nothing of the kind, so no passage can '
                            'show the answer. Answer "no" only with a passage that says so.'}, not_stated=False)
        self.answer = answer
        self.none_found = none_found
        self.scored = answer.scored
        self.quote_required = type(answer) is not Text if quote_required is None else quote_required

    def describe(self):
        return {'type': self.name, 'answer': self.answer.describe()} | ({'none_found': True} if self.none_found else {})

    def schema(self):
        return {'type': 'object', 'required': ['answer', 'quotes'], 'additionalProperties': False,
                'properties': {'answer': self.answer.schema(),
                               'quotes': {'type': 'array', 'items': QUOTE.schema()}}}

    def validate(self, value, path):
        if not isinstance(value, dict) or set(value) != {'answer', 'quotes'}:
            return [f'{path}: expected {{"answer": …, "quotes": [{{"doc", "page", "quote"}}]}}']
        errors = self.answer.validate(value['answer'], f'{path}.answer')
        quotes = value['quotes']
        if not isinstance(quotes, list):
            return errors + [f'{path}.quotes: expected a list']
        for i, q in enumerate(quotes):
            errors += QUOTE.validate(q, f'{path}.quotes[{i}]')
        unquoted = (NOT_STATED, NONE_FOUND) if self.none_found else (NOT_STATED,)
        if not quotes and value['answer'] not in unquoted and self.quote_required:
            errors.append(f'{path}.quotes: an answer other than "{NOT_STATED}" needs at least one quote')
        return errors

    def same(self, a, b):
        return self.answer.same(a, b)

    def example(self, rng):
        return {'answer': self.answer.example(rng), 'quotes': []}


def make_rng(*seed):
    return random.Random('|'.join(map(str, seed)))


def from_description(d):
    """The value type a `describe()` dict came from, so stored graphs can validate values without the codebook."""
    simple = {'count': Count, 'integer': Integer, 'true or false': Boolean, 'date': DateValue, 'text': Text, 'name': Name}
    kind = d['type']
    if kind == 'name' and 'known' in d:
        return KnownName(d['known']['names'], d['known']['of'])
    if kind in simple:
        return simple[kind]()
    if kind == 'one of':
        return OneOf(d['options'], not_stated=False)
    if kind == 'counts by':
        return CountsBy(d['options'])
    if kind == 'record':
        return Record(**{k: from_description(v) for k, v in d['fields'].items()})
    if kind == 'list':
        return ListOf(from_description(d['item']), not_stated=d.get('not_stated', False))
    if kind == 'or not stated':
        return OrNotStated(from_description(d['value']))
    if kind == 'quoted':
        return Quoted(from_description(d['answer']), none_found=d.get('none_found', False))
    raise ValueError(f'unknown value type {kind!r}')
