"""Check labels: the shape, every value against its codebook type, the scope rule, and every quote on its page.

Quotes are checked as the pipeline checks them (appeals.graph.layers.verify_quotes). A quote that fails is also
looked for on every page of the docket, to tell a wrong page number from words that aren't in the text.

    uv run python scripts/answer-key/check_labels.py [labels-dir] [slug ...]
Writes a JSON report per label next to it (<slug>.check.json) and prints one line per label.
"""
import json
import sys

from appeals import config
from appeals.codebook import derived
from appeals.codebook import fields as F
from appeals.graph.layers import _norm
from appeals.ingest import dockets
from appeals.store import Store

from keylib import KEY
FIELDS = {f.id: f for f in [*F.ALL, *derived.ALL]}     # the key also labels derived comparisons
IDS = json.loads((KEY / 'fields.json').read_text())
labels_dir = KEY / (sys.argv[1] if len(sys.argv) > 1 else 'labels')
only = set(sys.argv[2:])
manifest = {m['slug']: m for m in json.loads((KEY / 'manifest.json').read_text())}
store = Store(config.load().db, read_only=True)


def in_scope(s):
    """The pipeline's own scope rule, applied to the label's four scope answers."""
    return derived.in_scope({k: s[k]['value'] for k in IDS['scope']})


def check(slug):
    path = labels_dir / f'{slug}.json'
    problems, quotes = [], {'checked': 0, 'found': 0, 'wrong_page': 0, 'missing': []}
    try:
        label = json.loads(path.read_text())
    except (OSError, ValueError) as error:
        return {'slug': slug, 'problems': [f'unreadable: {error}'], 'quotes': quotes}
    docket = dockets.docket_text(store, manifest[slug]['docket'])
    pages = [(d.n, p) for d in docket.documents for p in range(1, len(d.pages) + 1)]

    def quote_ok(q, where):
        if not isinstance(q, dict) or not {'doc', 'page', 'quote'} <= set(q):
            problems.append(f'{where}: a quote is not {{"doc", "page", "quote"}}')
            return
        quotes['checked'] += 1
        text = _norm(str(q['quote']))
        if text and text in _norm(docket.page_text(q['doc'], q['page']) or ''):
            quotes['found'] += 1
        elif text and any(text in _norm(docket.page_text(d, p) or '') for d, p in pages):
            quotes['wrong_page'] += 1
        else:
            quotes['missing'].append(f'{where}: {str(q["quote"])[:80]}')

    def entry(fid, e, where):
        if not isinstance(e, dict) or 'value' not in e:
            problems.append(f'{where}: expected {{"value", "quotes", "note"}}')
            return
        problems.extend(FIELDS[fid].type.validate(e['value'], where))
        for q in e.get('quotes') or []:
            quote_ok(q, where)

    if label.get('docket') != manifest[slug]['docket']:
        problems.append(f'docket is {label.get("docket")!r}, expected {manifest[slug]["docket"]!r}')
    scope = label.get('scope') or {}
    for fid in IDS['scope']:
        entry(fid, scope.get(fid), f'scope.{fid}')
    rule = None
    if not problems:
        rule = in_scope(scope)
        if scope.get('in_scope_by_rule') != ('yes' if rule else 'no'):
            problems.append(f'in_scope_by_rule is {scope.get("in_scope_by_rule")!r} but the answers give '
                            f'{"yes" if rule else "no"}')
    if not isinstance(scope.get('this_docket'), str) or not scope['this_docket'].strip():
        problems.append('scope.this_docket: missing (one or two sentences on which decision this docket appeals)')
    judgment = (scope.get('new_housing_in_your_judgment') or {}).get('value')
    if judgment not in ('yes', 'no', 'unsure'):
        problems.append(f'new_housing_in_your_judgment is {judgment!r}')
    wants_fields = rule or judgment in ('yes', 'unsure')
    fields = label.get('fields')
    if fields is None:
        if wants_fields:
            problems.append('fields is null, but the docket is in scope by the rule or the labeler\'s judgment')
    elif not isinstance(fields, dict):
        problems.append('fields is neither null nor an object')
    else:
        for fid in sorted(set(IDS['full']) - set(fields)):
            problems.append(f'fields.{fid}: missing')
        for fid in sorted(set(fields) - set(IDS['full'])):
            problems.append(f'fields.{fid}: not expected')
        for fid in IDS['full']:
            if fid in fields:
                entry(fid, fields[fid], f'fields.{fid}')
    return {'slug': slug, 'docket': manifest[slug]['docket'], 'in_scope_by_rule': rule, 'judgment': judgment,
            'has_fields': isinstance(fields, dict), 'problems': problems, 'quotes': quotes}


slugs = sorted(only or {p.stem for p in labels_dir.glob('*.json') if not p.stem.endswith('.check')})
bad = 0
for slug in slugs:
    report = check(slug)
    (labels_dir / f'{slug}.check.json').write_text(json.dumps(report, indent=1))
    q = report['quotes']
    ok = not report['problems'] and not q['missing']
    bad += not ok
    print(f'{"ok " if ok else "BAD"} {slug:16} scope={report.get("in_scope_by_rule")!s:5} judgment={report.get("judgment")!s:6} '
          f'quotes {q["found"]}/{q["checked"]} (+{q["wrong_page"]} wrong page, {len(q["missing"])} missing) '
          f'problems {len(report["problems"])}')
print(f'{len(slugs) - bad} of {len(slugs)} clean')
