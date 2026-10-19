"""The key and a run's answers, item by item, shared by score.py and compare.py so both score the same way.

A per-group field (kinds, judgment standards, other questions) is compared item by item; every other field by its
codebook type's own rule. Fields other than scope are compared only where the key is in scope by the rule.
"""
import json
from pathlib import Path

from appeals.codebook import derived
from appeals.graph.values import Record

# The answer key's labels and texts stay under data/ (not in git); these scripts are in git.
KEY = Path(__file__).resolve().parents[2] / 'data' / 'answer-keys' / 'full-2026-10'
SCOPE = ['proceeding', 'physical_change', 'housing_use', 'units_effect']


def key_values(label):
    values = {k: label['scope'][k]['value'] for k in SCOPE}
    values['in_scope'] = derived.in_scope(values)
    if values['in_scope'] and label.get('fields'):
        values |= {k: v['value'] for k, v in label['fields'].items()}
    return values


def reviewed(label, field, item):
    """Whether an adjudicator or a project owner's ruling set the key's answer for this field (and item)."""
    entry = label['scope'].get(field) if field in SCOPE else (label.get('fields') or {}).get(field)
    marks = (entry or {}).get('adjudicated') or []
    return any(m.get('item') in (item, None) for m in marks)


def load_keys():
    """{docket: (manifest entry, key values, label)}"""
    keys = {}
    for m in json.loads((KEY / 'manifest.json').read_text()):
        label = json.loads((KEY / 'labels' / f'{m["slug"]}.json').read_text())
        keys[m['docket']] = (m, key_values(label), label)
    return keys


def run_rows(store, run_id):
    return {r['docket']: json.loads(r['value']) for r in store.rows(
        """SELECT r.docket, n.value FROM run_records r JOIN node_records n ON n.key = r.key
           WHERE r.run_id = ? AND r.node = 'row'""", (run_id,))}


def items(types, expected, row):
    """(field, item name, key answer, run answer, same) for every scored item of one docket."""
    for field, want in expected.items():
        got = row.get('in_scope') if field == 'in_scope' else row.get(field)
        kind = types.get(field)
        if field != 'in_scope' and (kind is None or not kind.scored):
            continue
        if isinstance(kind, Record) and isinstance(want, dict):
            parts = [(f'{field}.{k}', want.get(k), got.get(k) if isinstance(got, dict) else got, kind.fields[k])
                     for k in kind.fields]
        else:
            parts = [(field, want, got, kind)]
        for name, w, g, t in parts:
            yield field, name, w, g, (w == g) if t is None else bool(t.same(g, w))
