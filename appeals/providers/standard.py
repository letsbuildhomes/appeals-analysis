"""Flat prices per token type, the same at every hour. Fits most providers.

    "models": {"<name>": {"input": 3.0, "output": 15.0, "cache_read": 0.3, "cache_write": 3.75}}

Prices are dollars per million tokens. A cache price left out is the input price.
"""
from appeals.providers.base import Charge, Provider, Rates


class Standard(Provider):
    def read_model(self, where, spec):
        return Rates.read(where, spec)

    def charge(self, model, usage, sent_at):
        return Charge(self.models[model].cost(usage), {'sent_at': sent_at.isoformat(), 'rate': 'standard'})
