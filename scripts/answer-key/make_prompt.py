"""Write the labeling prompt for the full answer key from the codebook.

Every question, option, definition and field note comes from appeals.codebook, so the key and the pipeline
can't drift apart. The edge cases (edge_cases.md, next to the prompt) and the output format are written by hand.

    uv run python scripts/answer-key/make_prompt.py v1
"""
import json
import sys

from appeals.codebook import derived as D
from appeals.codebook import fields as F
from appeals.codebook import questions as Q
from appeals.codebook import steps as L

from keylib import KEY
VERSION = sys.argv[1] if len(sys.argv) > 1 else 'v1'


def options(opts, code=True):
    return '\n'.join(f'  - `{k}`: {v}' if code else f'  - {k}: {v}' for k, v in opts.items())


def notes(field):
    return ''.join(f'\n  - Note: {n}' for n in field.notes)


def question(q):
    """A scan question as the pipeline asks it, with its options."""
    return f'{q.ask}\n{options(q.options)}'


def field(f, ask, opts=None, extra=''):
    """One field's section: its ID, label, question, options and notes."""
    body = f'### `{f.id}`: {f.label}\n\n{ask}'
    if opts:
        body += f'\n{options(opts)}'
    if extra:
        body += f'\n\n{extra}'
    if f.notes:
        body += '\n' + notes(f)
    return body


DATE = 'A date: `YYYY-MM-DD`, `YYYY-MM` or `YYYY`, as precisely as a document states it, or `"not stated"`.'
COUNT = 'A whole number (0 or more), or `"not stated"`.'

SCOPE = '\n\n'.join([
    field(F.proceeding, question(Q.S1)),
    field(F.physical_change, question(Q.S2)),
    field(F.housing_use, question(Q.S3)),
    field(F.units_effect, question(Q.S4)),
])

IN_SCOPE = """The pipeline's rule, which you apply to your four answers:

> In scope = `proceeding` is `municipal permit application` or `several, including a municipal permit application`,
> and `housing_use` is `yes` or `group or care housing`, and `physical_change` is not `authorize something already built` or
> `no physical change`, and (`units_effect` is `adds` or `replaces`, or `physical_change` is `create building lots`).

Record the result as `in_scope_by_rule` (`yes` or `no`).

Then, separately, give your own judgment as `new_housing_in_your_judgment` (`yes`, `no` or `unsure`) with a
one-sentence note: is this docket an appeal of a town decision about new housing, in the study's sense? The study
covers appeals of municipal land-use decisions where the permission at issue lets someone build, place or convert a
structure that will contain dwelling units (or group or care housing), or create lots for housing. Enforcement, changes of occupancy, accessory
work, permits for something already built, and state permits (Act 250, Agency of Natural Resources) are out of scope.
If your judgment differs from the rule, say why in the note: those disagreements are what this key is most for.

**Unclear scope.** When the definitions don't settle whether this docket is in the study (a kind of housing they
don't settle, or doubt over which decision this docket appeals or what it allows), your judgment is `unsure`, not
`no`, whatever the rule says. Give your best answers to the four scope questions, say in the note what the
question is, and answer every field in Step 2, so the key has them whichever way the question is decided."""

TOPIC_SECTIONS = {
    'Filing dates': [
        field(F.filing_date, f'{Q.F1.ask} {L.L2a.prompt.split(chr(10) + chr(10))[1]}', extra=DATE),
        field(F.earliest_event, 'Only when `filing_date` is "not stated": ' + L.L2b.prompt
              + ' Otherwise "not stated".', extra=DATE),
    ],
    "The town's decision": [
        field(F.town_decision, question(Q.T1)),
        field(F.town_decision_date, L.L3b.prompt, extra=DATE),
        field(F.municipality, L.L3c.prompt.split('\n\n')[0],
              extra='Use the official spelling (for example "St. Johnsbury", "Rutland City", "Barre Town").'),
        field(F.place_within_town, L.L3c.prompt.split('\n\n')[1],
              extra='A name, or `"not stated"`.'),
    ],
    'Kinds of permission': [
        field(F.permission_kinds,
              f'{Q.K1.ask} Answer `yes`, `no` or `"not stated"` for each kind, as an object with these keys:\n'
              + '\n'.join(f'  - `{k}`: {L.KIND_WORDING.get(k, m)}' for k, m in Q.K1.items.items())
              + '\n\nA kind is at issue when it is part of the municipal decision being appealed. Several can be `yes`.'),
    ],
    'Appellants and their lawyers': [
        field(F.appellants_named, question(Q.A1)),
        field(F.appellants, L.L4a.prompt.split('\n\n')[1] + '\n\nEach entry is `{"name": ..., "role": ...}`, '
              'with `role` one of:\n' + options(L.ROLES)
              + '\n\nThe value is a list, or `"not stated"` if the documents never say who appealed.'),
        field(F.appellant_lawyers,
              'For each of the first 10 appellants listed: ' + L.L4b.prompt.replace('{item}', 'the appellant')
              + '\n\nEach entry is `{"appellant": ..., "representation": ..., "lawyer": ..., "firm": ...}`, '
              'one entry per lawyer (an appellant with two lawyers has two entries). `representation` is one of:\n'
              + options(L.REPRESENTATION | {'not stated': 'The documents do not say.'})
              + '\n\nWhen an appellant had no lawyer or it is not stated, give one entry for them with `lawyer` and '
              '`firm` both `"not stated"`. A firm not named is `"not stated"`.'),
    ],
    "The court's decision": [
        field(F.review_standard, question(Q.C1) + '\n\n' + L.L10.prompt.split('\n\n')[1]),
        field(F.final_decision, question(Q.C2) + '\n\n' + L.L5a.prompt.split('\n\n')[1]),
        field(F.how_ended, 'Only when `final_decision` is `yes` (otherwise "not stated"), for that first decision: '
              + question(Q.C3)),
        field(F.court_result, 'Only when `how_ended` is `decided on the merits` (otherwise "not stated"): '
              + question(Q.C4)),
        field(F.dismissal_basis, 'Only when `how_ended` is `dismissed` (otherwise "not stated"): ' + question(Q.C5)),
        field(F.final_decision_date, 'Only when `final_decision` is `yes` (otherwise "not stated"): ' + L.L5e.prompt,
              extra=DATE),
        field(F.outcome_changed_later, 'Only when `final_decision` is `yes` (otherwise "not stated"): '
              + L.L5g.prompt + ' Answer `yes` or `no`.'),
        field(F.latest_order_date, 'Only when `final_decision` is `no` (otherwise "not stated"): ' + L.L5f.prompt,
              extra=DATE),
    ],
    'Units added': [
        field(F.units_added_proposed, f'{Q.U1.ask}\n\nHow many new dwelling units would the project add, as the '
              f'application proposed it? {L.UNITS_ADDED}', extra=COUNT),
        field(F.appeal_partial, question(Q.U2)),
        field(F.units_added_under_appeal, 'Only when `appeal_partial` is `yes` (otherwise "not stated"): '
              + L.L6c.prompt.replace('\n\n', ' '), extra=COUNT),
        field(F.housing_lots, f'{Q.U3.ask} ' + L.L6d.prompt.split('\n\n')[1], extra=COUNT),
        field(F.units_added_town_approved, L.L6e.prompt.replace('\n\n', ' '), extra=COUNT),
        field(F.units_added_court_approved, 'Only when `court_result` is `granted`, `granted with conditions`, '
              '`granted in part` or `denied` (otherwise "not stated"): '
              + L.L6f.prompt.split('\n\n')[2], extra=COUNT),
        field(D.UNITS_VS_TOWN, question(Q.U4)),
        field(D.UNITS_VS_APPLICATION, question(Q.U5)),
    ],
    'Arguments and grounds': [
        field(F.arguments_stated, question(Q.G1)),
        field(F.judgment_grounds,
              'For each kind of judgment standard below: how far did this docket get with a standard of this kind? '
              f'{Q.JUDGMENT}\n\n"Disputed" means a party actually contested whether the project meets the standard, '
              'including an applicant appealing a denial on it; a finding the court made only because it runs through '
              f'every criterion is not disputed. {Q.FURTHEST} A dispute over a condition counts under the group whose '
              'standard the condition serves.\n\nThe kinds (object keys):\n'
              + '\n'.join(f'  - `{k}` ({Q.GROUP_NAMES[k]}): {v}' for k, v in Q.GROUPS.items())
              + '\n\nThe levels:\n' + options(Q.LEVELS)
              + '\n\nIf `arguments_stated` is `no`, every kind is "not stated".'),
        field(F.judgment_results,
              'For each kind whose level is `decided, disputed` or `decided, not disputed`: what did the court decide '
              'about whether the project meets this kind of standard? Any other level is `not decided`. Same keys.\n'
              + options(L.RESULTS) + '\n\nIf `arguments_stated` is `no`, every kind is "not stated".'),
        field(F.judgment_conditions,
              'For each kind whose level is `decided, disputed`: ' + L.GROUND_CONDITIONS['character'].prompt
              + ' Answer `yes` or `no`; any other level is `no`. Same keys. If `arguments_stated` is `no`, every '
              'kind is "not stated".'),
        field(F.relief_kind,
              'Only when the `relief` kind\'s level is anything but `not at issue` (otherwise "not stated"): '
              + L.L8_relief_kind.prompt, opts=L.RELIEF_KINDS),
        field(F.other_questions,
              'For each other kind of question below: how far did this docket get with a question of this kind? '
              'Count it only for this docket\'s appeal, not for a sibling docket or a coordinated civil action '
              f'decided in the same decision. {Q.FURTHEST} A rule, permit or doctrine the decision only recites '
              '(background facts, the legal standard, a list of sections) is "not at issue". Whether the project '
              'meets a standard calling for judgment, and variances or waivers, are not this kind of question.\n\n'
              'The kinds (object keys):\n'
              + '\n'.join(f'  - `{k}` ({Q.OTHER_NAMES[k]}): {v}' for k, v in Q.OTHER_KINDS.items())
              + '\n\nThe levels:\n' + options(Q.OTHER_LEVELS)
              + '\n\nAnswered even when `arguments_stated` is `no`.'),
        field(F.conditions_challenged, question(Q.G4) + '\n\nIf `arguments_stated` is `no`, "not stated".'),
        field(F.conditions_challenged_by,
              'When `conditions_challenged` is `yes`: ' + L.L7c.prompt + ' For each (up to five), who challenged it. '
              'Each entry is `{"condition": ..., "challenged_by": ...}`, with `challenged_by` one of:\n'
              + options(L.CHALLENGERS)
              + '\n\nAn empty list `[]` when `conditions_challenged` is `no`; "not stated" when it is "not stated".'),
        field(F.conditions_outcome,
              'The same conditions, in the same order: what did the court do with each? Each entry is '
              '`{"condition": ..., "outcome": ...}`, with `outcome` one of:\n' + options(L.OUTCOMES)
              + '\n\n`[]` or "not stated" as for `conditions_challenged_by`.'),
    ],
    'Stay and design change': [
        field(F.stayed, question(Q.D1) + '\n\n' + L.L11a.prompt.split('\n\n')[1].replace(' Answer from the documents, with a quote.', '')),
        field(F.stay_start, 'Only when `stayed` is `yes` (otherwise "not stated"): the date the court\'s stay started.',
              extra=DATE),
        field(F.stay_end, 'Only when `stayed` is `yes` (otherwise "not stated"): the date it ended.', extra=DATE),
        field(F.design_changed, question(Q.D2) + '\n\n' + L.L12a.prompt.split('\n\n')[1].replace(' Answer from the documents, with a quote.', '')),
    ],
}

# The key labels the derived unit comparisons in place of the quoted answers they fall back on.
FIELD_IDS = [f.id.removesuffix('_stated') if f.id.startswith('units_vs_') else f.id
             for f in F.ALL if f.id not in ('docket_filing', 'design_change')]
SCOPE_IDS = ['proceeding', 'physical_change', 'housing_use', 'units_effect']
FULL_IDS = [i for i in FIELD_IDS if i not in SCOPE_IDS]

EXAMPLE = {
    'docket': '<docket number>',
    'scope': {
        'proceeding': {'value': 'municipal permit application', 'quotes': [{'doc': 1, 'page': 1, 'quote': '<exact words>'}],
                       'note': ''},
        'physical_change': {'value': '…', 'quotes': ['…'], 'note': ''},
        'housing_use': {'value': '…', 'quotes': ['…'], 'note': ''},
        'units_effect': {'value': '…', 'quotes': ['…'], 'note': ''},
        'in_scope_by_rule': 'yes | no',
        'new_housing_in_your_judgment': {'value': 'yes | no | unsure', 'note': '<one sentence>'},
        'this_docket': '<which municipal decision this docket appeals, who appealed it, and how it differs from its siblings>',
    },
    'fields': {fid: {'value': '…', 'quotes': ['…'], 'note': ''} for fid in FULL_IDS[:2]} | {'…': '…'},
    'doubts': '<anything you were unsure about, or an empty string>',
}

edge_cases = (KEY / 'edge_cases.md').read_text().strip()

prompt = f"""<!-- Generated by scripts/make_prompt.py ({VERSION}) from appeals.codebook and edge_cases.md. Don't edit by hand. -->

# Labeling one docket for the answer key

You are making a hand-checked answer key for a research project on appeals of Vermont town land-use decisions to
the Vermont Superior Court, Environmental Division. An automated pipeline answers the questions below for every
docket; your labels are the truth it will be scored against. Be accurate, not generous, and never guess: when the
documents don't establish an answer, the answer is `"not stated"`, which is never the same as `"no"`.

## The docket text

The file you are given holds every published decision in one docket, in posting order. Each decision is marked
`<document n="…" title="…">` and each page `<page n="…">`. **Read the whole file, every page, before answering.**
Long files must be read in parts (use offsets) until you reach the end.

A decision may also cover other dockets (sibling dockets, or a coordinated civil or enforcement action with a
different number). Each `<document>` tag lists the dockets that decision covers, and your task names this docket's
siblings. Answer only about this docket's appeal. A decision the court issued in several dockets belongs in full
to each of them, but an argument, ruling or fact that concerns only another docket is not this docket's.

**Anchor this docket first.** Before answering, work out which municipal decision this docket appeals, who
appealed it, and, if it has siblings, how its appeal differs from theirs. Write that as `this_docket` (one or two
sentences) and answer every question for that appeal. When an answer rests on a passage the court wrote about a
sibling docket, or about several dockets together, so that it isn't clear the passage concerns this docket's
appeal, add `"from_sibling": true` to that answer's entry and say why in its note.

## Step 1: scope (every docket)

Answer these four questions for every docket.

{SCOPE}

{IN_SCOPE}

## Step 2: everything else (only if in scope)

If `in_scope_by_rule` is `yes` **or** `new_housing_in_your_judgment` is `yes` or `unsure`, answer every field below,
including for a docket whose scope is unclear. Otherwise set `fields` to `null` and stop after scope.

{(chr(10) * 2).join(f'## {topic}{chr(10)}{chr(10)}' + (chr(10) * 2).join(sections) for topic, sections in TOPIC_SECTIONS.items())}

## Edge cases

{edge_cases}

## Quotes

Every answer needs at least one quote, except `"not stated"`, an empty list, and a `no` that rests on the documents
showing nothing of the kind (no stay, no challenged condition, no design change, no final decision). A quote is
words copied exactly from one page of the text, 5 to 40 words, with the document and page numbers from the
`<document n>` and `<page n>` markers. Don't join text from two pages into one quote, and don't fix spelling or
punctuation. For an object field (kinds, judgment standards, other questions) quote each item that isn't `no`,
`not at issue`, `not decided` or "not stated", and start that quote's `note` with the item's key. For a list,
every entry needs a quote that shows it: one quote may cover several entries, but each entry's name must appear in
a quote (a long list of appellants usually needs several). Pick the passage that best shows the answer.

## Output

Write one JSON object, exactly this shape, to the label file you are given, and nothing else in that file:

```json
{json.dumps(EXAMPLE, indent=2, ensure_ascii=False)}
```

- `scope` holds the four scope fields, each `{{"value", "quotes", "note"}}`, plus the two scope judgments and
  `this_docket`.
- Any field's entry may add `"from_sibling": true`, as described under "Anchor this docket first".
- `fields` is `null` for an out-of-scope docket, otherwise an object with exactly these keys, each
  `{{"value", "quotes", "note"}}`: {', '.join(f'`{i}`' for i in FULL_IDS)}.
- Each quote is `{{"doc": <n>, "page": <n>, "quote": "<exact words>"}}` (plus `"note"` for an item, as above).
- A `note` is optional: at most one sentence, for an answer that needs explaining.
- Values use the option names exactly as written above, including `"not stated"`.
- `doubts`: anything you were unsure about, especially where the definitions didn't fit this docket. Be honest;
  doubts show where the key itself is weakest.
"""

out = KEY / f'prompt-{VERSION}.md'
out.write_text(prompt)
(KEY / 'fields.json').write_text(json.dumps({'scope': SCOPE_IDS, 'full': FULL_IDS}, indent=1))
print(f'{out}: {len(prompt):,} characters, about {len(prompt) // 4:,} tokens')
