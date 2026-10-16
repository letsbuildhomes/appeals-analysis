"""Value types: what a question, step or field may answer.

Each type can describe itself (for the dashboard), state a JSON schema (sent
to the reasoning model), validate a reply (errors are sent back to the model),
compare two answers (for scoring) and make an example (for the fake model).
"Not stated" is a real answer for every type that allows it.
"""
import random
import re

NOT_STATED = 'not stated'
OUT_OF_SCOPE = 'out of scope'      # a research row's value for a docket we did not study
DATE = re.compile(r'^\d{4}(-\d{2}(-\d{2})?)?$')


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


class DateValue(ValueType):
    """A date as precise as the documents allow: YYYY, YYYY-MM or YYYY-MM-DD."""
    name = 'date'

    def schema(self):
        return {'anyOf': [{'type': 'string', 'pattern': DATE.pattern}, {'const': NOT_STATED}]}

    def validate(self, value, path):
        if value == NOT_STATED or (isinstance(value, str) and DATE.match(value)):
            return []
        return [f'{path}: expected a date as YYYY, YYYY-MM or YYYY-MM-DD, or "{NOT_STATED}"; got {value!r}']

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
    name = 'list'

    def __init__(self, item):
        self.item = item

    def describe(self):
        return {'type': self.name, 'item': self.item.describe()}

    def schema(self):
        return {'type': 'array', 'items': self.item.schema()}

    def validate(self, value, path):
        if not isinstance(value, list):
            return [f'{path}: expected a list']
        return [e for i, v in enumerate(value) for e in self.item.validate(v, f'{path}[{i}]')]

    def same(self, a, b):
        return isinstance(a, list) and isinstance(b, list) and len(a) == len(b)

    def example(self, rng):
        return [self.item.example(rng) for _ in range(rng.randint(1, 3))]


QUOTE = Record(doc=Count(), page=Count(), quote=Text())


class Quoted(ValueType):
    """An answer with the quotations that support it: {"answer": …, "quotes": [{"doc", "page", "quote"}]}.

    Every answer except "not stated" needs at least one quote.
    """
    name = 'quoted'

    def __init__(self, answer):
        self.answer = answer
        self.scored = answer.scored

    def describe(self):
        return {'type': self.name, 'answer': self.answer.describe()}

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
        if not quotes and value['answer'] != NOT_STATED and not isinstance(self.answer, Text):
            errors.append(f'{path}.quotes: an answer other than "{NOT_STATED}" needs at least one quote')
        return errors

    def same(self, a, b):
        return self.answer.same(a, b)

    def example(self, rng):
        return {'answer': self.answer.example(rng), 'quotes': []}


def make_rng(*seed):
    return random.Random('|'.join(map(str, seed)))
