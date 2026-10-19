"""Compare two runs against the key as it stands now: what a change fixed, what it broke, and how much.

    uv run python scripts/answer-key/compare.py <before-run> <after-run> [--wash N]

Both runs are scored against today's key, so key corrections made between them don't count as pipeline changes.
Each answer moves one of four ways: fixed (wrong to right), broken (right to wrong), shifted (wrong to another
wrong answer) or unchanged. Net = fixed - broken.

- Scope is reported per docket and first, since a docket moving in or out of scope moves every field it has.
  Field answers on a docket that either run has out of scope are left out of the field counts.
- Cascades are damped by also counting units: one field on one docket counts as one unit, better if its errors
  fell and worse if they rose, so one docket with twenty knock-on answers counts once.
- Size is shown as the share of the before-run's errors closed, field by field.
- Each fixed or broken answer is marked "reviewed" when an adjudicator or a project owner's ruling set the key's
  answer. A break against an unreviewed key answer may be a key error.
- Unchanged steps are reused from the cache, so an answer should only move when one of its inputs (its steps
  or the scan) changed. Any other movement is listed as unexpected. A change to how facts are combined or derived
  also shows up here, as it should: check that it is the change you made.
- "Same meaning written two ways" (classify.py's conventions) counts as agreement.

Name each change and the fields it targets with --change, once per change, so the report can say what each one
did: --change "Unit comparisons=units_vs_town,units_vs_application" --change "Scope=scope". "scope" stands for
the four scope fields and in_scope. Fields no change names are the noise reading. Without --change, every field
is reported as untouched.

The report opens with the parts of the post-experiment assessment that code can produce (docs/IMPROVING.md):
the verdict, the change table, dockets that entered or left scope with what came with them, and the regressions
ranked by severity. Severity:
- high: a docket moved into or out of scope wrongly; a branch (one field on one docket) of 5 or more wrong
  answers, including on a docket newly in scope; a break against a reviewed key answer;
- medium: a branch of 2 to 4 broken answers, or any break in a field a change targeted;
- low: a single break in a field no change targeted.

Verdict, from the development dockets only (held back is reported, not used to decide). With --change, it counts
only the fields the changes target, plus every docket that moved into or out of scope; the untouched fields are
the noise reading and are named only if they move beyond the band. Without --change, it counts every field.
- net loss: more dockets moved wrongly than rightly, or net units below -N;
- net improvement: more dockets moved rightly than wrongly, or net units above N; "with a regression" when a
  counted field's net units are below -N;
- wash: otherwise.
N defaults to 8 units: chance alone has moved the whole key by +6, -6 and -5 net units (passes 4, the noise check
and 6b). Revisit it as more passes measure the noise. Writes compare-<before>-<after>.json beside the disagreements files.
"""
import json
import sys
from collections import defaultdict

from keylib import KEY, items, load_keys, reviewed, run_rows, SCOPE

from appeals import config
from appeals.codebook import build
from appeals.store import Store

args = [a for a in sys.argv[1:] if not a.startswith('--')]
WASH = int(sys.argv[sys.argv.index('--wash') + 1]) if '--wash' in sys.argv else 8
CHANGES = {}                                 # change name -> fields it targets
for i, arg in enumerate(sys.argv):
    if arg == '--change':
        name, _, targets = sys.argv[i + 1].partition('=')
        CHANGES[name] = [t.strip() for t in targets.split(',') if t.strip()]
args = [a for a in args if a not in {sys.argv[i + 1] for i, x in enumerate(sys.argv) if x in ('--change', '--wash')}]
before, after = args[0], args[1]
TARGETED = {f: name for name, fs in CHANGES.items() for f in fs}
settings = config.load()
pipeline = build(settings.thresholds)
types = {n.id: n.type for n in [*pipeline.fields, *pipeline.derives]}
CONVENTION = {('not decided', 'not stated'), ('no', 'not stated'), ('not stated', 'no')}
CONVENTION_FIELDS = {'judgment_results', 'judgment_conditions', 'permission_kinds'}


def right(field, want, got, same):
    return same or (field in CONVENTION_FIELDS and (str(want), str(got)) in CONVENTION)


def inputs(node_id):
    """The run_records nodes a field or derived value reads, through any fields it reads: its steps, and 'scan'
    for any scan question."""
    node = pipeline.nodes.get(node_id)
    if node is None or node.kind == 'step':
        return {node_id}
    if node.kind in ('field', 'derive'):
        return set().union(set(), *(inputs(r) for r in node.refs()))
    return {'scan'}


store = Store(settings.db, read_only=True)
rows = {r: run_rows(store, r) for r in (before, after)}
records = {}
for run in (before, after):
    recs = defaultdict(dict)
    for r in store.rows('SELECT docket, node, key FROM run_records WHERE run_id = ?', (run,)):
        recs[r['docket']][r['node'].split('[')[0]] = recs[r['docket']].get(r['node'].split('[')[0], '') + r['key']
    records[run] = recs

facts = {d: json.loads(v) for d, v in ((r['docket'], r['value']) for r in store.rows(
    """SELECT r.docket, n.value FROM run_records r JOIN node_records n ON n.key = r.key
       WHERE r.run_id = ? AND r.node = 'facts'""", (after,)))}


def source(docket, name):
    field, _, item = name.partition('.')
    src = (facts.get(docket, {}).get(field) or {}).get('source', 'derived')
    return src.get(item, '?') if isinstance(src, dict) else src


keys = load_keys()
entered = []                                 # dockets in scope after but not before, with their wrong answers
moves = []                                   # every answer that changed state or value
units = defaultdict(lambda: defaultdict(lambda: [0, 0]))   # split -> field -> [units better, units worse]
counts = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))   # split -> field -> tally
scope = defaultdict(list)
unexpected = []
for docket, (m, expected, label) in sorted(keys.items()):
    split = m['split']
    a, b = rows[before].get(docket), rows[after].get(docket)
    if a is None or b is None:
        unexpected.append({'docket': docket, 'field': '(row)', 'why': 'missing from a run'})
        continue
    hidden = not (a.get('in_scope') and b.get('in_scope'))
    if b.get('in_scope') and not a.get('in_scope'):
        wrong = [(name, w, g) for f, name, w, g, same in items(types, expected, b)
                 if f not in SCOPE and f != 'in_scope' and not right(f, w, g, same)]
        total = sum(1 for f, *_ in items(types, expected, b) if f not in SCOPE and f != 'in_scope')
        entered.append({'docket': docket, 'split': split, 'key_in': expected['in_scope'], 'answers': total,
                        'wrong': wrong})
    per_field = defaultdict(lambda: [0, 0])          # field -> [errors before, errors after]
    changed_inputs = {n for n in set(records[before][docket]) | set(records[after][docket])
                      if records[before][docket].get(n) != records[after][docket].get(n)}
    pairs = zip(items(types, expected, a), items(types, expected, b))
    for (field, name, want, ga, sa), (_, _, _, gb, sb) in pairs:
        ra, rb = right(field, want, ga, sa), right(field, want, gb, sb)
        if field != 'in_scope' and field not in SCOPE and hidden:
            continue
        if ga != gb and not (inputs(field) & changed_inputs):
            unexpected.append({'docket': docket, 'field': name, 'before': ga, 'after': gb})
        group = 'scope' if field in SCOPE or field == 'in_scope' else field
        move = ('fixed' if rb else 'shifted' if ga != gb else 'still wrong') if not ra else \
               ('broken' if not rb else 'unchanged')
        counts[split][group][move] += 1
        counts[split][group]['errors before'] += not ra
        counts[split][group]['errors after'] += not rb
        per_field[group][0] += not ra
        per_field[group][1] += not rb
        if move in ('fixed', 'broken', 'shifted'):
            item = name.partition('.')[2] or None
            moves.append({'docket': docket, 'split': split, 'field': name, 'move': move, 'key': want,
                          'before': ga, 'after': gb, 'reviewed': reviewed(label, field, item),
                          'source': source(docket, name)})
        if field == 'in_scope' and move in ('fixed', 'broken'):
            scope[split].append((move, docket, want))
    for group, (eb, ea) in per_field.items():
        units[split][group][0] += ea < eb
        units[split][group][1] += ea > eb


def table(split):
    out = [f'  {"field":26} {"errors":>9} {"fixed":>6} {"broken":>7} {"shifted":>8} {"net":>5} {"closed":>7}'
           f' {"units +/-":>10}  broken vs reviewed key']
    groups = sorted(counts[split], key=lambda g: (g != 'scope', -(counts[split][g]['fixed'] + counts[split][g]['broken'])))
    for g in groups:
        c, (ub, uw) = counts[split][g], units[split][g]
        if not (c['fixed'] or c['broken'] or c['shifted']):
            continue
        net = c['fixed'] - c['broken']
        closed = f'{net / c["errors before"]:+.0%}' if c['errors before'] else '-'
        rev = sum(1 for mv in moves if mv['split'] == split and mv['move'] == 'broken' and mv['reviewed']
                  and (mv['field'].split('.')[0] == g or g == 'scope' and mv['field'].split('.')[0] in SCOPE + ['in_scope']))
        out.append(f'  {g:26} {c["errors before"]:>4}->{c["errors after"]:<4} {c["fixed"]:>6} {c["broken"]:>7} '
                   f'{c["shifted"]:>8} {net:>+5} {closed:>7} {f"+{ub}/-{uw}":>10}  {rev}')
    tot = {k: sum(counts[split][g][k] for g in counts[split]) for k in ('fixed', 'broken', 'shifted', 'errors before',
                                                                          'errors after')}
    ub, uw = sum(u[0] for u in units[split].values()), sum(u[1] for u in units[split].values())
    out.append(f'  {"all":26} {tot["errors before"]:>4}->{tot["errors after"]:<4} {tot["fixed"]:>6} {tot["broken"]:>7} '
               f'{tot["shifted"]:>8} {tot["fixed"] - tot["broken"]:>+5} '
               f'{(tot["fixed"] - tot["broken"]) / max(1, tot["errors before"]):>+7.0%} {f"+{ub}/-{uw}":>10}')
    return out, ub - uw


def counted(group):
    """Whether a field counts toward the verdict: every field without --change, else only the targeted ones."""
    return not CHANGES or group in TARGETED


def verdict():
    """(verdict, net units counted, net units untouched) for the development dockets."""
    dev = units['development']
    net = sum(ub - uw for g, (ub, uw) in dev.items() if counted(g))
    noise = sum(ub - uw for g, (ub, uw) in dev.items() if not counted(g))
    right_moves = sum(1 for mv, *_ in scope['development'] if mv == 'fixed')
    wrong_moves = sum(1 for mv, *_ in scope['development'] if mv == 'broken')
    if wrong_moves > right_moves or net < -WASH:
        word = 'NET LOSS'
    elif right_moves > wrong_moves or net > WASH:
        worst = [g for g, (ub, uw) in dev.items() if counted(g) and ub - uw < -WASH]
        word = 'NET IMPROVEMENT' + (f', with a regression in {", ".join(worst)}' if worst else '')
    else:
        word = 'WASH'
    if CHANGES and abs(noise) > WASH:
        word += f'; untouched fields moved beyond the band ({noise:+} units): check for a bug or a missed target'
    return word, net, noise


def change_table(split):
    """One row per named change over the fields it targets, then the untouched fields (the noise reading)."""
    rows_out = ['| Change | Fields | Errors before → after | Fixed | Broken | Shifted | Net answers | Net units | Read |',
                '|---|---|---|---|---|---|---|---|---|']
    groups = list(CHANGES.items()) + [('Untouched (noise)', [g for g in counts[split] if g not in TARGETED])]
    for name, fs in groups:
        c = {k: sum(counts[split][g][k] for g in fs) for k in ('fixed', 'broken', 'shifted', 'errors before',
                                                               'errors after')}
        ub, uw = sum(units[split][g][0] for g in fs), sum(units[split][g][1] for g in fs)
        net_units = ub - uw
        if name == 'Untouched (noise)':
            read = f'chance alone: +{ub}/-{uw} units'
        else:
            read = ('real gain' if net_units > WASH else 'real loss' if net_units < -WASH else 'within noise')
        if 'scope' in fs:                    # a docket moving scope outweighs the field counts
            right_moves = sum(1 for mv, *_ in scope[split] if mv == 'fixed')
            wrong_moves = sum(1 for mv, *_ in scope[split] if mv == 'broken')
            if right_moves or wrong_moves:
                read += f'; dockets moved rightly {right_moves}, wrongly {wrong_moves} (see scope movement)'
        moved = [g for g in fs if counts[split][g]['fixed'] or counts[split][g]['broken'] or counts[split][g]['shifted']]
        shown = ', '.join(moved) if name == 'Untouched (noise)' else ', '.join(fs)
        rows_out.append(f'| {name} | {shown or "-"} | {c["errors before"]} → {c["errors after"]} | {c["fixed"]} | '
                        f'{c["broken"]} | {c["shifted"]} | {c["fixed"] - c["broken"]:+} | +{ub}/-{uw} | {read} |')
    return rows_out


def scope_section():
    out = ['| Split | Docket | Moved | Key says | Answers that came with it | Wrong among them | Biggest wrong branches |',
           '|---|---|---|---|---|---|---|']
    for split in ('development', 'held back'):
        for _, d, w in scope[split]:
            e = next((x for x in entered if x['docket'] == d), None)
            moved = 'into scope' if e else 'out of scope'
            if e:
                fam = defaultdict(int)
                for name, *_ in e['wrong']:
                    fam[family(name.split('.')[0])] += 1
                top = ', '.join(f'{f} ({n})' for f, n in sorted(fam.items(), key=lambda x: -x[1])[:3])
                out.append(f'| {split} | {d} | {moved} | {"in" if w else "out"} | {e["answers"]} | {len(e["wrong"])} | '
                           f'{top or "-"} |')
            else:
                out.append(f'| {split} | {d} | {moved} | {"in" if w else "out"} | - | - | - |')
    return out if len(out) > 2 else ['No docket moved into or out of scope.']


# Fields that answer one chain of questions, so one wrong turn shows up in several of them.
CHAINS = {'judgment standards': {'judgment_grounds', 'judgment_results', 'judgment_conditions'},
          'ending': {'final_decision', 'how_ended', 'court_result', 'dismissal_basis', 'final_decision_date',
                     'latest_order_date', 'outcome_changed_later'},
          'conditions challenged': {'conditions_challenged', 'conditions_challenged_by', 'conditions_outcome'},
          'appellants': {'appellants', 'appellant_lawyers'}}


def family(field):
    """A branch's field: fields on one chain of questions count together."""
    return next((name for name, fs in CHAINS.items() if field in fs), field)


def regressions():
    """Broken answers grouped by branch (docket x field), plus wrong branches on dockets newly in scope, ranked."""
    found = []
    for split in ('development', 'held back'):
        for mv, d, w in scope[split]:
            if mv == 'broken':
                found.append(('high', split, d, 'in_scope', 1, f'wrongly moved {"into" if not w else "out of"} scope',
                              TARGETED.get('scope', 'untouched'), source(d, 'units_effect')))
        branches = defaultdict(list)
        for m in moves:
            if m['split'] == split and m['move'] == 'broken' and m['field'].split('.')[0] not in SCOPE + ['in_scope']:
                branches[(m['docket'], family(m['field'].split('.')[0]))].append(m)
        for (d, f), ms in branches.items():
            n, rev = len(ms), any(m['reviewed'] for m in ms)
            target = TARGETED.get(ms[0]['field'].split('.')[0], 'untouched')
            sev = 'high' if n >= 5 or rev else 'medium' if n >= 2 or target != 'untouched' else 'low'
            what = '; '.join(f'{m["field"].partition(".")[2] or f}: {str(m["key"])[:22]} -> {str(m["after"])[:22]}'
                             for m in ms[:3]) + (' ...' if n > 3 else '') + (' [reviewed key]' if rev else '')
            found.append((sev, split, d, f, n, what, target, ', '.join(sorted({str(m['source']) for m in ms}))))
        for e in entered:
            if e['split'] != split or not e['key_in']:
                continue
            fam = defaultdict(list)
            for name, w, g in e['wrong']:
                fam[family(name.split('.')[0])].append((name, w, g))
            for f, ws in fam.items():
                if len(ws) >= 5:
                    found.append(('high', split, e['docket'], f, len(ws), f'newly in scope, branch wrong: '
                                  f'{ws[0][0]}: key {str(ws[0][1])[:20]} -> {str(ws[0][2])[:20]}',
                                  TARGETED.get(f, 'untouched'), source(e['docket'], ws[0][0])))
    rank = {'high': 0, 'medium': 1, 'low': 2}
    found.sort(key=lambda r: (rank[r[0]], r[1] != 'development', -r[4]))
    out = ['| Severity | Split | Docket | Field | Answers | What | Change | Source now |', '|---|---|---|---|---|---|---|---|']
    out += [f'| {s} | {sp} | {d} | {f} | {n} | {w} | {t} | {src} |' for s, sp, d, f, n, w, t, src in found]
    return out


lines = [f'{before} -> {after}, both scored against the key as it stands', '']
dev, dev_net = table('development')
held, held_net = table('held back')
word, counted_net, noise_net = verdict()
lines += [f'VERDICT (development): {word}  (net units {counted_net:+} in the fields counted'
          + (f', {noise_net:+} untouched' if CHANGES else '') + f'; wash band +/-{WASH})', '']
lines += ['CHANGE TABLE, development', ''] + change_table('development')
lines += ['', 'CHANGE TABLE, held back (report only)', ''] + change_table('held back')
lines += ['', 'SCOPE MOVEMENT', ''] + scope_section()
lines += ['', 'REGRESSIONS, ranked (the assessment adds a likely cause and a fix for each high and medium row)', '']
lines += regressions() + ['', 'DETAIL', '']
for split in ('development', 'held back'):
    sc = scope[split]
    lines.append(f'Scope, {split}: ' + ('; '.join(f'{mv} {d} (key {"in" if w else "out"})' for mv, d, w in sc)
                                         or 'no docket moved'))
lines += ['', 'Development (errors before->after; closed = net as a share of errors before; units = field x docket '
              'better/worse):'] + dev
lines += ['', 'Held back (report only):'] + held
lines += ['', 'Unexpected movement (answer changed though none of its inputs did): '
          + (str(len(unexpected)) if unexpected else 'none')]
lines += [f'  {u}' for u in unexpected[:20]]
for split in ('development', 'held back'):
    for kind in ('broken', 'fixed', 'shifted'):
        sel = [mv for mv in moves if mv['split'] == split and mv['move'] == kind]
        if sel:
            lines += ['', f'{kind.capitalize()}, {split} ({len(sel)}):']
            lines += [f'  {mv["docket"]:16} {mv["field"]:36} key {str(mv["key"])[:28]:28} | {str(mv["before"])[:24]}'
                      f' -> {str(mv["after"])[:24]}{"  [reviewed]" if mv["reviewed"] else ""}' for mv in sel]
print('\n'.join(lines))
(KEY / f'compare-{before}-{after}.json').write_text(json.dumps(
    {'before': before, 'after': after, 'wash': WASH, 'verdict': word, 'net_units': counted_net, 'untouched_net_units': noise_net,
     'held_back_net_units': held_net, 'counts': counts, 'units': units, 'scope': scope, 'moves': moves,
     'unexpected': unexpected}, indent=1, default=str))
