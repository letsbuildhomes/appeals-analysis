"""Settings: config.toml, then .env and the environment, then command-line overrides.

Keys are read from the environment variable an endpoint names and are kept
only in memory. `Endpoint.public()` is what gets recorded with a run.
"""
from dataclasses import dataclass, field, fields, replace
from datetime import timezone
import os
from pathlib import Path
import tomllib

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
PRICES = ('input_per_mtok', 'output_per_mtok', 'cache_read_per_mtok', 'cache_write_per_mtok')


@dataclass(frozen=True)
class Endpoint:
    format: str
    base_url: str
    model: str
    key_env: str
    concurrent: int = 8
    per_minute: int = 600
    key: str = field(default='', repr=False)
    # prices in dollars per million tokens
    input_per_mtok: float = 0.0
    output_per_mtok: float = 0.0
    cache_read_per_mtok: float = 0.0
    cache_write_per_mtok: float = 0.0
    # decision model only
    long_context_tokens: int = 30000
    # reasoning model only
    max_output_tokens: int = 16000
    json_repairs: int = 2
    truncation_retries: int = 2
    # prices outside the provider's peak hours, and when those are; None when prices never change
    off_peak: dict | None = None

    def public(self):
        """What a run records about the endpoint: everything but the key."""
        return {'format': self.format, 'base_url': self.base_url, 'model': self.model}

    def prices(self, sent_at):
        """The rate that applies to a call sent at `sent_at` (an aware datetime), and its prices per million tokens."""
        if self.off_peak is None:
            return 'standard', {k: getattr(self, k) for k in PRICES}
        if self.is_peak(sent_at):
            return 'peak', {k: getattr(self, k) for k in PRICES}
        return 'off-peak', {k: self.off_peak[k] for k in PRICES}

    def is_peak(self, sent_at):
        """Peak hours are UTC hours on listed weekdays, except listed holidays.

        A year with no holidays listed counts every weekday as a working day,
        so a missing calendar overstates the cost rather than understating it.
        """
        o = self.off_peak
        utc = sent_at.astimezone(timezone.utc)
        if utc.isoweekday() not in o['peak_weekdays'] or utc.date() in o.get('holidays', []):
            return False
        hour = utc.hour + utc.minute / 60 + utc.second / 3600
        return any(start <= hour < end for start, end in o['peak_hours_utc'])

    def holidays_cover(self, year):
        """Whether the off-peak calendar lists holidays for `year` (always true without a calendar)."""
        return self.off_peak is None or any(d.year == year for d in self.off_peak.get('holidays', []))


@dataclass(frozen=True)
class Settings:
    data: Path
    listing_url: str
    user_agent: str
    pause_seconds: float
    decision: Endpoint
    reasoning: Endpoint
    workers: int
    budget_usd: float
    chars_per_token: float
    thresholds: dict

    @property
    def db(self):
        return self.data / 'appeals.sqlite'

    @property
    def pdfs(self):
        return self.data / 'pdfs'

    @property
    def listings(self):
        return self.data / 'listings'


def _endpoint(table):
    known = {f.name for f in fields(Endpoint)}
    values = {k: v for k, v in table.items() if k in known}
    return Endpoint(**values)


def load(config=ROOT / 'config.toml', env=ROOT / '.env', overrides=None):
    """Read settings. `overrides` maps dotted names ("reasoning.model", "workers") to values."""
    load_dotenv(env, override=False)
    raw = tomllib.loads(Path(config).read_text())
    paths, source, run = raw['paths'], raw['source'], raw['run']
    settings = Settings(
        data=(ROOT / paths['data']).resolve(),
        listing_url=source['listing_url'],
        user_agent=source['user_agent'],
        pause_seconds=float(source['pause_seconds']),
        decision=_endpoint(raw['decision']),
        reasoning=_endpoint(raw['reasoning']),
        workers=int(run['workers']),
        budget_usd=float(run['budget_usd']),
        chars_per_token=float(run['chars_per_token']),
        thresholds=dict(raw['thresholds']),
    )
    for name, value in (overrides or {}).items():
        if value is not None:
            settings = _override(settings, name, value)
    return replace(settings,
                   decision=replace(settings.decision, key=settings.decision.key or os.environ.get(settings.decision.key_env, '')),
                   reasoning=replace(settings.reasoning, key=settings.reasoning.key or os.environ.get(settings.reasoning.key_env, '')))


def _override(settings, name, value):
    if '.' in name:
        group, key = name.split('.', 1)
        endpoint = getattr(settings, group)
        kind = type(getattr(endpoint, key))
        return replace(settings, **{group: replace(endpoint, **{key: kind(value)})})
    kind = type(getattr(settings, name))
    return replace(settings, **{name: kind(value)})
