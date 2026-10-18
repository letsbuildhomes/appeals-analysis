"""Settings: config.toml and the provider files, then .env and the environment, then command-line overrides.

config.toml picks a model for each role as "provider/model" and sets how the
pipeline uses it. Each provider's address, key variable, limits and prices
are in `providers/<provider>.json` (see appeals/providers). Keys are read from
the environment variable the provider names and are kept only in memory.
"""
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
import tomllib

from dotenv import load_dotenv

from appeals import providers
from appeals.providers import Model

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Decision:
    """The decision model and how the scan uses it."""
    model: Model
    long_context_tokens: int = 28000          # dockets over this many estimated tokens use long-context mode


@dataclass(frozen=True)
class Reasoning:
    """The reasoning model and how steps use it."""
    model: Model
    max_output_tokens: int = 16000            # includes a thinking model's hidden reasoning
    json_repairs: int = 2                     # times a malformed reply is sent back for correction
    resends: int = 2                          # times a reply cut off at max_output_tokens, or empty, is sent again unchanged


@dataclass(frozen=True)
class Settings:
    data: Path
    listing_url: str
    user_agent: str
    pause_seconds: float
    decision: Decision
    reasoning: Reasoning
    workers: int
    budget_usd: float
    chars_per_token: float
    thresholds: dict
    site: dict = field(default_factory=dict)

    @property
    def db(self):
        return self.data / 'appeals.sqlite'

    @property
    def pdfs(self):
        return self.data / 'pdfs'

    @property
    def listings(self):
        return self.data / 'listings'

    @property
    def releases(self):
        return self.data / 'releases'


def load(config=ROOT / 'config.toml', env=ROOT / '.env', overrides=None, provider_files=ROOT / 'providers'):
    """Read settings. `overrides` maps dotted names ("reasoning.model", "reasoning.key", "workers") to values."""
    load_dotenv(env, override=False)
    raw = tomllib.loads(Path(config).read_text())
    overrides = {k: v for k, v in (overrides or {}).items() if v is not None}
    catalog = providers.load(provider_files)
    paths, source, run = raw['paths'], raw['source'], raw['run']
    settings = Settings(
        data=(ROOT / paths['data']).resolve(),
        listing_url=source['listing_url'],
        user_agent=source['user_agent'],
        pause_seconds=float(source['pause_seconds']),
        decision=_role(Decision, 'decision', raw['decision'], overrides, catalog),
        reasoning=_role(Reasoning, 'reasoning', raw['reasoning'], overrides, catalog),
        workers=int(run['workers']),
        budget_usd=float(run['budget_usd']),
        chars_per_token=float(run['chars_per_token']),
        thresholds=dict(raw['thresholds']),
        site=dict(raw.get('site', {})),
    )
    for name, value in overrides.items():
        if '.' not in name:
            settings = replace(settings, **{name: type(getattr(settings, name))(value)})
    return settings


def _role(kind, name, table, overrides, catalog):
    """A role's settings from its config.toml table and any overrides, with its model resolved."""
    table = {**table, **{k.split('.', 1)[1]: v for k, v in overrides.items() if k.startswith(f'{name}.')}}
    key = table.pop('key', None)
    known = {f.name for f in fields(kind)}
    unknown = [k for k in table if k not in known]
    if unknown:
        raise ValueError(f'config.toml [{name}]: unknown setting{"s" if len(unknown) > 1 else ""} {", ".join(unknown)}')
    if 'model' not in table:
        raise ValueError(f'config.toml [{name}]: missing model, written "provider/model"')
    model = providers.resolve(catalog, table.pop('model'), key)
    return kind(model=model, **{k: type(getattr(kind, k))(v) for k, v in table.items()})
