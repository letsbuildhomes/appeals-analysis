"""Model providers: one JSON file each in `providers/`, read by the class its `kind` names.

    load(folder)            -> {provider id: Provider}
    resolve(catalog, ref)   -> Model, for a ref such as "deepseek/deepseek-flash"

Each kind decides its own file layout beyond the shared fields, how to read
a response's token usage, and what a call costs. See base.py for the
interface and the kind modules for their layouts.
"""
import json
import os
from pathlib import Path

from appeals.providers.base import Charge, Model, Provider, Rates, Usage
from appeals.providers.deepseek import DeepSeek
from appeals.providers.standard import Standard
from appeals.providers.typesafe import TypeSafe

__all__ = ['Charge', 'Model', 'Provider', 'Rates', 'Usage', 'KINDS', 'load', 'resolve', 'unpriced']

KINDS = {'standard': Standard, 'deepseek': DeepSeek, 'typesafe': TypeSafe}


def load(folder):
    """Every provider in `folder`, keyed by file name. Raises ValueError for a file that doesn't check out."""
    catalog = {}
    for path in sorted(Path(folder).glob('*.json')):
        where = f'providers/{path.name}'
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError as error:
            raise ValueError(f'{where}: not valid JSON ({error.msg} at line {error.lineno})') from None
        kind = data.get('kind') if isinstance(data, dict) else None
        if kind not in KINDS:
            raise ValueError(f'{where}: kind must be one of {", ".join(KINDS)}, not {kind!r}')
        catalog[path.stem] = KINDS[kind](path.stem, data, where)
    return catalog


def resolve(catalog, ref, key=None):
    """The model `ref` ("provider/model") names, with its key from `key` or the provider's environment variable."""
    provider_id, _, name = str(ref).partition('/')
    if provider_id not in catalog:
        raise ValueError(f'unknown provider {provider_id!r} in {ref!r}; providers: {", ".join(catalog) or "none"}')
    provider = catalog[provider_id]
    if name not in provider.models:
        raise ValueError(f'{provider_id} has no model {name!r}; models: {", ".join(provider.models)}')
    return Model(provider, name, key or os.environ.get(provider.key_env, ''))


def unpriced(name, api='fake', concurrent=64, per_minute=0):
    """A free model at no real provider, for fake and scripted clients."""
    provider = Standard(api, {'kind': 'standard', 'api': api, 'base_url': '', 'key_env': '', 'concurrent': concurrent,
                              'per_minute': per_minute, 'models': {name: {'input': 0, 'output': 0}}})
    return Model(provider, name)
