"""Apply adjudicators' verdicts to the key: where an adjudicator ruled the key wrong ("pipeline" or "neither"), set
the key's answer to the adjudicator's. Values that can't be applied as given (lists, or an answer that doesn't fit
the field's type) are listed in adjudication/unapplied.json for the next labeling pass.

    uv run python scripts/answer-key/apply_adjudication.py
"""
import glob
import json
import sys
from pathlib import Path

from appeals.codebook import derived
from appeals.codebook import fields as F
from appeals.graph.values import Record

from keylib import KEY
FIELDS = {f.id: f for f in [*F.ALL, *derived.ALL]}     # the key also labels derived comparisons
SCOPE = ['proceeding', 'physical_change', 'housing_use', 'units_effect']
manifest = {m['docket']: m for m in json.loads((KEY / 'manifest.json').read_text())}
applied, unapplied = 0, []
FOLDER = sys.argv[1] if len(sys.argv) > 1 else 'adjudication'


def typed(kind, value):
    if isinstance(value, str) and value.isdigit():
        value = int(value)
    return value if not kind.validate(value, 'v') else None


for path in sorted(glob.glob(str(KEY / FOLDER / '*.json'))):
    if path.endswith(('.input.json', 'unapplied.json')):
        continue
    adj = json.loads(Path(path).read_text())
    slug = manifest[adj['docket']]['slug']
    label_path = KEY / 'labels' / f'{slug}.json'
    label = json.loads(label_path.read_text())
    changed = False
    for v in adj['verdicts']:
        if v['correct'] not in ('pipeline', 'neither') or v['field'] == 'in_scope':
            continue
        fid, _, item = v['field'].partition('.')
        f = FIELDS[fid]
        kind = f.type.fields[item] if item and isinstance(f.type, Record) else f.type
        value = typed(kind, v['answer'])
        where = label['scope'] if fid in SCOPE else (label.get('fields') or {})
        entry = where.get(fid)
        if value is None or entry is None:
            unapplied.append({'docket': adj['docket'], 'field': v['field'], 'answer': v['answer'], 'why': v['why']})
            continue
        if item:
            if not isinstance(entry['value'], dict):
                unapplied.append({'docket': adj['docket'], 'field': v['field'], 'answer': v['answer'], 'why': v['why']})
                continue
            entry['value'][item] = value
        else:
            entry['value'] = value
        entry['adjudicated'] = (entry.get('adjudicated') or []) + [{'item': item or None, 'why': v['why']}]
        applied += 1
        changed = True
    if changed:
        rule = derived.in_scope({k: label['scope'][k]['value'] for k in SCOPE})
        label['scope']['in_scope_by_rule'] = 'yes' if rule else 'no'
        label_path.write_text(json.dumps(label, indent=2, ensure_ascii=False))
(KEY / FOLDER / 'unapplied.json').write_text(json.dumps(unapplied, indent=1))
print(f'applied {applied}; {len(unapplied)} left for the labeling pass')
