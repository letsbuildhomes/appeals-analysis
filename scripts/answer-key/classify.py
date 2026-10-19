"""Sort a run's disagreements with the key into scope-caused, convention and real, for adjudication.

scope-caused: the run or the key has the docket out of scope, so its other fields can't agree.
convention:   the two follow different conventions for an answer that means the same, such as "not stated"
              against "not decided" for a kind of standard that got no follow-up.
real:         everything else; these go to adjudication.

    uv run python scripts/answer-key/classify.py <run-id>
"""
import json
import sys
from collections import Counter, defaultdict

from keylib import KEY
run_id = sys.argv[1]
D = json.loads((KEY / f'disagreements-{run_id}.json').read_text())
SCOPE = {'in_scope', 'proceeding', 'physical_change', 'housing_use', 'units_effect'}
CONVENTION = {('not decided', 'not stated'), ('no', 'not stated'),           # no follow-up: result, condition
              ('not stated', 'no')}                                          # a kind item: "not stated" vs "no"
out_dockets = {d['docket'] for d in D if d['field'] == 'in_scope' or d['run'] == 'out of scope'}
# Disagreements an adjudicator already settled (same docket and field) are not reviewed again.
settled = set()
for path in (KEY / 'adjudication').glob('*.json'):
    if path.name.endswith('.input.json') or path.name == 'unapplied.json':
        continue
    adj = json.loads(path.read_text())
    settled |= {(adj['docket'], v['field']) for v in adj['verdicts']}


def kind(d):
    if (d['docket'], d['field']) in settled:
        return 'settled'
    if d['field'] in SCOPE:
        return 'real'
    if d['run'] == 'out of scope' or d['docket'] in out_dockets and d['field'] not in SCOPE:
        return 'scope-caused'
    field = d['field'].split('.')[0]
    if field in ('judgment_results', 'judgment_conditions', 'permission_kinds') and \
            (str(d['key']), str(d['run'])) in CONVENTION:
        return 'convention'
    return 'real'


groups = defaultdict(list)
for d in D:
    d['kind'] = kind(d)
    groups[d['kind']].append(d)
print({k: len(v) for k, v in groups.items()})
real = groups['real']
print('real by field:', Counter(d['field'].split('.')[0] for d in real).most_common())
by_docket = defaultdict(list)
for d in real:
    by_docket[d['docket']].append(d)
(KEY / f'real-{run_id}.json').write_text(json.dumps(by_docket, indent=1, default=str))
print(len(by_docket), 'dockets with real disagreements:',
      sorted((len(v), k) for k, v in by_docket.items())[::-1][:40])
