"""How stable the pipeline is: two runs of the same pipeline, the second with fresh steps, compared answer by answer.

    uv run python scripts/answer-key/noise.py <run> <fresh-run>

Both runs must share a graph hash, so every difference is chance. The report gives, by area, by field and by step:
how often an answer differs between the runs (flip rate), and how often it is right in one run and wrong in the
other (unstable correctness), with the dockets that move most. Field answers on a docket either run has out of
scope are left out, except for scope itself. Writes noise-<run>-<fresh-run>.json.
"""
import json
import sys
from collections import Counter, defaultdict

from keylib import KEY, SCOPE, items, load_keys, run_rows

from appeals import config
from appeals.codebook import build
from appeals.store import Store

a_run, b_run = sys.argv[1], sys.argv[2]
settings = config.load()
pipeline = build(settings.thresholds)
types = {n.id: n.type for n in [*pipeline.fields, *pipeline.derives]}
topic = {n.id: n.topic for n in [*pipeline.fields, *pipeline.derives, *pipeline.steps]}
topic['in_scope'] = 'scope'
CONVENTION = {('not decided', 'not stated'), ('no', 'not stated'), ('not stated', 'no')}
CONVENTION_FIELDS = {'judgment_results', 'judgment_conditions', 'permission_kinds'}
store = Store(settings.db, read_only=True)
hashes = {r['id']: r['graph_hash'] for r in store.rows('SELECT id, graph_hash FROM runs WHERE id IN (?, ?)',
                                                         (a_run, b_run))}
if len(set(hashes.values())) != 1:
    sys.exit(f'the runs have different graphs ({hashes}): differences would not be chance alone')


def right(field, want, got, same):
    return same or (field in CONVENTION_FIELDS and (str(want), str(got)) in CONVENTION)


def step_answers(run):
    """{docket: {step: comparable answer}} for every step that gave an answer; for-each items join their step."""
    out = defaultdict(dict)
    for r in store.rows("""SELECT r.docket, r.node, n.value FROM run_records r JOIN node_records n ON n.key = r.key
                           WHERE r.run_id = ? AND r.layer = 'steps' AND r.node != 'base'""", (run,)):
        value = json.loads(r['value']) if r['value'] else {}
        if '[' in r['node'] or 'answer' not in value or value.get('answer') is None:
            continue
        out[r['docket']][r['node']] = strip(value['answer'])
    return out


FREE_TEXT = {'question', 'description', 'item'}


def strip(value):
    """An answer without its quotes or free wording, so only what it decides is compared: a list of free-text items
    (such as challenged conditions) compares by length, names by their lowercase form."""
    if isinstance(value, dict):
        if 'answer' in value and 'quotes' in value:
            return strip(value['answer'])
        return {k: strip(v) for k, v in value.items() if k not in ('quotes', *FREE_TEXT)}
    if isinstance(value, list):
        inner = [strip(v) for v in value]
        if all(isinstance(v, str) for v in inner) and any(len(v.split()) > 4 for v in inner):
            return len(inner)                                      # free-text items: how many, not their wording
        return sorted(map(str, inner)) if all(isinstance(v, str) for v in inner) else inner
    return value.lower().strip() if isinstance(value, str) else value


keys = load_keys()
rows = {r: run_rows(store, r) for r in (a_run, b_run)}
by_field = defaultdict(Counter)            # field -> answers, differ, unstable (right in one run only)
by_docket = Counter()
per_docket_moves = defaultdict(list)
for docket, (_, expected, _) in sorted(keys.items()):
    a, b = rows[a_run].get(docket), rows[b_run].get(docket)
    if a is None or b is None:
        continue
    hidden = not (a.get('in_scope') and b.get('in_scope'))
    for (field, name, want, ga, sa), (_, _, _, gb, sb) in zip(items(types, expected, a), items(types, expected, b)):
        if hidden and field not in SCOPE and field != 'in_scope':
            continue
        c = by_field[field]
        c['answers'] += 1
        c['right both'] += right(field, want, ga, sa) and right(field, want, gb, sb)
        kind = types.get(field)
        item = name.partition('.')[2]
        kind = kind.fields[item] if item and hasattr(kind, 'fields') else kind
        if not (ga == gb or (kind is not None and kind.same(ga, gb))):
            c['differ'] += 1
            by_docket[docket] += 1
            per_docket_moves[docket].append(name)
        if right(field, want, ga, sa) != right(field, want, gb, sb):
            c['unstable'] += 1

steps = defaultdict(Counter)
sa, sb = step_answers(a_run), step_answers(b_run)
for docket in set(sa) | set(sb):
    for node in set(sa[docket]) | set(sb[docket]):
        family = node.split('_')[0] if node.startswith(('L8_', 'L9_', 'L3_')) else node
        family = {'L8': 'L8 (judgment standards)', 'L9': 'L9 (other questions)', 'L3': 'L3 kinds'}.get(family, family)
        c = steps[family]
        if node in sa[docket] and node in sb[docket]:
            c['both'] += 1
            c['differ'] += sa[docket][node] != sb[docket][node]
        else:
            c['one run only'] += 1


def pct(n, d):
    return f'{n / d:.0%}' if d else '-'


areas = defaultdict(Counter)
for field, c in by_field.items():
    areas[topic.get(field, '?')].update(c)
lines = [f'{a_run} vs {b_run} (same graph, fresh steps): every difference is chance', '',
         'BY AREA', '', '| Area | Answers | Differ | Flip rate | Right in one run only | Right in both |',
         '|---|---|---|---|---|---|']
for area, c in sorted(areas.items(), key=lambda x: -x[1]['differ'] / max(1, x[1]['answers'])):
    lines.append(f'| {pipeline.topics.get(area, area)} | {c["answers"]} | {c["differ"]} | {pct(c["differ"], c["answers"])} '
                 f'| {c["unstable"]} | {pct(c["right both"], c["answers"])} |')
lines += ['', 'BY FIELD (fields with any difference)', '',
          '| Field | Answers | Differ | Flip rate | Right in one run only |', '|---|---|---|---|---|']
for field, c in sorted(by_field.items(), key=lambda x: (-x[1]['differ'] / max(1, x[1]['answers']), -x[1]['differ'])):
    if c['differ']:
        lines.append(f'| {field} | {c["answers"]} | {c["differ"]} | {pct(c["differ"], c["answers"])} | {c["unstable"]} |')
lines += ['', 'BY STEP (answers compared without quotes; "one run only": the step ran in one run, so an earlier '
              'answer differed)', '', '| Step | Ran in both | Differ | Flip rate | Ran in one run only |',
          '|---|---|---|---|---|']
for family, c in sorted(steps.items(), key=lambda x: (-x[1]['differ'] / max(1, x[1]['both']), x[0])):
    lines.append(f'| {family} | {c["both"]} | {c["differ"]} | {pct(c["differ"], c["both"])} | {c["one run only"]} |')
lines += ['', 'DOCKETS THAT MOVED MOST', '', '| Docket | Answers that differ | Fields |', '|---|---|---|']
for docket, n in by_docket.most_common(12):
    fields = Counter(name.split('.')[0] for name in per_docket_moves[docket])
    lines.append(f'| {docket} | {n} | {", ".join(f"{f} ({k})" for f, k in fields.most_common(4))} |')
print('\n'.join(lines))
(KEY / f'noise-{a_run}-{b_run}.json').write_text(json.dumps(
    {'runs': [a_run, b_run], 'by_field': by_field, 'by_step': steps, 'by_docket': by_docket,
     'moves': per_docket_moves}, indent=1, default=str))
