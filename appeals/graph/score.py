"""Scoring: a run's rows against the reference answers, field by field.

Every scored field is compared with its value type's own rule, so a new
structured field is scored automatically. Free text is never scored.
"""
from collections import defaultdict
import json


def score_run(pipeline, store, run_id):
    types = {f.id: f.type for f in pipeline.fields} | {d.id: d.type for d in pipeline.derives}
    reference = defaultdict(dict)
    for r in store.rows('SELECT docket, field, value FROM reference_answers'):
        reference[r['docket']][r['field']] = json.loads(r['value'])
    rows = store.rows("""SELECT n.docket, n.value FROM run_records r JOIN node_records n ON n.key = r.key
                         WHERE r.run_id = ? AND r.node = 'row'""", (run_id,))
    tally = defaultdict(lambda: {'compared': 0, 'agree': 0})
    for row in rows:
        values = json.loads(row['value'])
        for field_id, expected in reference.get(row['docket'], {}).items():
            kind = types.get(field_id)
            if kind is None or not kind.scored:
                continue
            tally[field_id]['compared'] += 1
            tally[field_id]['agree'] += bool(kind.same(values.get(field_id), expected))
    return {'run': run_id, 'dockets': len(rows),
            'dockets_with_reference': sum(1 for r in rows if r['docket'] in reference),
            'fields': dict(tally)}
