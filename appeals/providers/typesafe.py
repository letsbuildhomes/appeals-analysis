"""TypeSafe: input tokens only.

    "models": {"<name>": {"input": 0.042}}
"""
from appeals.providers.base import Charge, Provider, Rates


class TypeSafe(Provider):
    def read_model(self, where, spec):
        return Rates.read(where, spec, required=('input',), optional=())

    def charge(self, model, usage, sent_at):
        return Charge(self.models[model].cost(usage), {'sent_at': sent_at.isoformat(), 'rate': 'standard'})
