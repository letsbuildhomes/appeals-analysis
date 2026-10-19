"""Score a pipeline run against the key, and list every disagreement for adjudication.

Scope (the four scope fields and in_scope) is scored on every docket. The other fields are scored only where the
key is in scope by the rule, since the pipeline fills them only for dockets it finds in scope. A per-group field
(kinds, judgment standards, other questions) is scored item by item; every other field by its codebook type's own
rule. Development and held-back dockets are reported apart.

    uv run python scripts/answer-key/score.py <run-id> [--load]
--load also writes the key into the store's reference_answers table (source "full-2026-10"), replacing any rows
from an earlier load, so `appeals score` and the dashboard see it.
"""
import json
import sys
from collections import defaultdict

from keylib import KEY, items, load_keys, run_rows

from appeals import config
from appeals.codebook import build
from appeals.store import Store

SOURCE = 'full-2026-10'
run_id = sys.argv[1]
settings = config.load()
pipeline = build(settings.thresholds)
types = {n.id: n.type for n in [*pipeline.fields, *pipeline.derives]}
keys = {d: (m, vals) for d, (m, vals, _) in load_keys().items()}

if '--load' in sys.argv:
    store = Store(settings.db)
    with store.transaction():
        store.db.execute('DELETE FROM reference_answers WHERE source = ?', (SOURCE,))
        store.db.executemany('INSERT OR REPLACE INTO reference_answers (docket, field, value, quotes, source) '
                             'VALUES (?, ?, ?, ?, ?)',
                             [(d, f, json.dumps(v), '[]', SOURCE) for d, (_, vals) in keys.items() for f, v in vals.items()])
    print(f'loaded {sum(len(v) for _, v in keys.values())} reference answers for {len(keys)} dockets')

store = Store(settings.db, read_only=True)
rows = run_rows(store, run_id)
tally = defaultdict(lambda: defaultdict(lambda: [0, 0]))      # split -> field -> [agree, compared]
disagreements = []
for docket, (m, expected) in sorted(keys.items()):
    row = rows.get(docket)
    if row is None:
        disagreements.append({'docket': docket, 'field': '(row)', 'key': 'labeled', 'run': 'no row in this run'})
        continue
    for field, name, w, g, same in items(types, expected, row):
        cell = tally[m['split']][field]
        cell[0] += same
        cell[1] += 1
        if not same:
            disagreements.append({'docket': docket, 'split': m['split'], 'field': name, 'key': w, 'run': g})

(KEY / f'disagreements-{run_id}.json').write_text(json.dumps(disagreements, indent=1, default=str))
for split in ('development', 'held back'):
    print(f'\n{split}:')
    for field, (agree, n) in sorted(tally[split].items(), key=lambda x: x[1][0] / max(1, x[1][1])):
        print(f'  {field:28} {agree:3}/{n:<3} {agree / n:.0%}')
print(f'\n{len(disagreements)} disagreements written to disagreements-{run_id}.json')
