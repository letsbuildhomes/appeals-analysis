"""What every provider shares: the fields read from its file, token usage, prices and charges.

A provider file names its `kind`, the class that reads it. The class reads
the shared fields here, then its own `models` and any sections of its own,
and decides what a call costs.
"""
from dataclasses import dataclass, field
from datetime import date

# Read by every provider: (name, default); None means required. source, checked and notes document the file.
SHARED = {'kind': None, 'api': None, 'base_url': None, 'key_env': None, 'models': None,
          'concurrent': 8, 'per_minute': 600, 'source': '', 'checked': '', 'notes': ''}


@dataclass(frozen=True)
class Usage:
    """Token counts for one call. `input` excludes tokens read from or written to the cache."""
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0


@dataclass(frozen=True)
class Charge:
    usd: float
    basis: dict             # how it was priced, kept with the call: such as {'sent_at': ..., 'rate': 'off-peak'}


@dataclass(frozen=True)
class Rates:
    """Dollars per million tokens of each kind."""
    input: float
    output: float = 0.0
    cache_read: float = 0.0
    cache_write: float = 0.0

    def cost(self, usage):
        return (usage.input * self.input + usage.output * self.output
                + usage.cache_read * self.cache_read + usage.cache_write * self.cache_write) / 1e6

    @classmethod
    def read(cls, where, table, required=('input', 'output'), optional=('cache_read', 'cache_write')):
        """Rates from a table. A cache price left out is the input price, which overstates rather than understates."""
        check(where, table, required, optional)
        values = {k: number(f'{where}.{k}', v) for k, v in table.items()}
        for k in optional:
            values.setdefault(k, values['input'])
        return cls(**values)


@dataclass(frozen=True)
class Model:
    """One model at one provider, with the key to call it (kept only in memory)."""
    provider: 'Provider'
    name: str
    key: str = field(default='', repr=False)

    @property
    def ref(self):
        return f'{self.provider.id}/{self.name}'

    def identity(self):
        """What a run records about the model, and part of each stored result's key: everything but the key."""
        return {'format': self.provider.api, 'base_url': self.provider.base_url, 'model': self.name}

    def usage(self, raw):
        return self.provider.usage(self.name, raw)

    def charge(self, usage, sent_at):
        return self.provider.charge(self.name, usage, sent_at)


class Provider:
    """A provider read from `providers/<id>.json`. Subclasses read their models and price calls."""
    extra = {}              # sections a kind adds to the shared ones: (name, default), None for required

    def __init__(self, id, data, where=None):
        self.id = id
        where = where or id
        allowed = {**SHARED, **self.extra}
        check(where, data, [k for k, v in allowed.items() if v is None], [k for k, v in allowed.items() if v is not None])
        values = {k: data.get(k, default) for k, default in allowed.items()}
        self.api, self.base_url, self.key_env = values['api'], values['base_url'], values['key_env']
        self.concurrent, self.per_minute = int(values['concurrent']), int(values['per_minute'])
        if self.api not in READ_USAGE:
            raise ValueError(f'{where}: unknown api {self.api!r}; expected one of {", ".join(READ_USAGE)}')
        self.read(where, values)
        if not isinstance(values['models'], dict) or not values['models']:
            raise ValueError(f'{where}: models must list at least one model')
        self.models = {name: self.read_model(f'{where}: models.{name}', spec) for name, spec in values['models'].items()}

    def read(self, where, values):
        """Read the kind's own provider-level sections."""

    def read_model(self, where, spec):
        """A model's settings, in whatever form `charge` uses."""
        raise NotImplementedError

    def usage(self, model, raw):
        """Token counts from a response's usage, in the provider's API's standard fields."""
        return READ_USAGE[self.api](raw or {})

    def charge(self, model, usage, sent_at):
        raise NotImplementedError

    def warnings(self, today: date):
        """Problems with the provider's data worth reporting in `make doctor`."""
        return []


def _openai_usage(raw):
    cached = (raw.get('prompt_tokens_details') or {}).get('cached_tokens') or 0
    return Usage(raw.get('prompt_tokens', 0) - cached, raw.get('completion_tokens', 0), cached)


def _anthropic_usage(raw):
    return Usage(raw.get('input_tokens', 0), raw.get('output_tokens', 0),
                 raw.get('cache_read_input_tokens', 0), raw.get('cache_creation_input_tokens', 0))


READ_USAGE = {
    'openai': _openai_usage,
    'anthropic': _anthropic_usage,
    'typesafe': lambda raw: Usage(raw.get('input_tokens', 0)),
    'fake': lambda raw: Usage(),
    'test': lambda raw: Usage(),
}


def check(where, table, required, optional=()):
    """Raise ValueError for a table that isn't one, misses a required field or has one not listed."""
    if not isinstance(table, dict):
        raise ValueError(f'{where}: expected an object')
    missing = [k for k in required if k not in table]
    unknown = [k for k in table if k not in required and k not in optional]
    if missing:
        raise ValueError(f'{where}: missing {", ".join(missing)}')
    if unknown:
        raise ValueError(f'{where}: unknown field{"s" if len(unknown) > 1 else ""} {", ".join(unknown)}')


def number(where, value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ValueError(f'{where}: expected a number of dollars, 0 or more')
    return float(value)
