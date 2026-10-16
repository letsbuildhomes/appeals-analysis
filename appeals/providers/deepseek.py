"""DeepSeek: peak and off-peak prices, set by the time a call is sent.

    "peak": {"hours_utc": [[1, 4], [6, 10]], "weekdays": [1, 2, 3, 4, 5], "holidays": ["2026-01-01", ...]},
    "models": {"<name>": {"peak": {"input": 0.30, "output": 1.20, "cache_read": 0.006},
                          "off_peak": {"input": 0.15, "output": 0.60, "cache_read": 0.003}}}

Peak hours are UTC hours on the listed ISO weekdays (Monday is 1), except
the listed holidays; every other hour is off-peak. A year with no holidays
listed counts every weekday as a working day, so a missing calendar
overstates the cost rather than understating it.

DeepSeek bills a cache write as an ordinary cache-miss input token, so its
models have no cache-write price, and it reports cache hits in its own field.
"""
from datetime import date, timezone

from appeals.providers.base import Charge, Provider, Rates, Usage, check

RATE = {'required': ('input', 'output', 'cache_read'), 'optional': ()}


class DeepSeek(Provider):
    extra = {'peak': None}

    def read(self, where, values):
        peak = values['peak']
        check(f'{where}: peak', peak, ('hours_utc', 'weekdays', 'holidays'))
        self.hours = [(float(start), float(end)) for start, end in peak['hours_utc']]
        self.weekdays = {int(d) for d in peak['weekdays']}
        try:
            self.holidays = {date.fromisoformat(d) for d in peak['holidays']}
        except (TypeError, ValueError):
            raise ValueError(f'{where}: peak.holidays must be dates written YYYY-MM-DD') from None

    def read_model(self, where, spec):
        check(where, spec, ('peak', 'off_peak'))
        return {rate: Rates.read(f'{where}.{rate}', spec[rate], **RATE) for rate in ('peak', 'off_peak')}

    def usage(self, model, raw):
        raw = raw or {}
        hits = raw.get('prompt_cache_hit_tokens', 0)
        return Usage(raw.get('prompt_tokens', 0) - hits, raw.get('completion_tokens', 0), hits)

    def charge(self, model, usage, sent_at):
        rate = 'peak' if self.is_peak(sent_at) else 'off_peak'
        return Charge(self.models[model][rate].cost(usage),
                      {'sent_at': sent_at.isoformat(), 'rate': rate.replace('_', '-')})

    def is_peak(self, sent_at):
        utc = sent_at.astimezone(timezone.utc)
        if utc.isoweekday() not in self.weekdays or utc.date() in self.holidays:
            return False
        hour = utc.hour + utc.minute / 60 + utc.second / 3600
        return any(start <= hour < end for start, end in self.hours)

    def warnings(self, today):
        if any(d.year == today.year for d in self.holidays):
            return []
        return [f'off-peak calendar lists no holidays for {today.year}; those days are priced as peak']
