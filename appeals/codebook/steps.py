"""Layer 3: the Base and the reasoning steps, in the order they run.

Each step asks for one detail, with its evidence, and must reply with JSON of
its `returns` type; malformed replies are sent back for correction. Details
that depend on each other run as a chain: each step names the step it follows
(`after`), keeps the exchanges along that line in context, and runs only if
earlier answers call for it (`only_if`). Steps are numbered by chain, in the
order the chains run, and lettered by their order within a chain.

A placeholder such as {A1} is filled with that question and the scan's answer. The Base states every scan
answer as a claim; a step states again, through its placeholders, the claims it checks, before its question.

Prompts are written as paragraphs (`_paragraphs`), each one line of text, with a blank line between them and no
line breaks inside. What each answer option means is not repeated here: it follows every question, with the
reply's schema (endpoints.answer_instructions).
"""
import re

from appeals.codebook import gates as G
from appeals.codebook import towns
from appeals.codebook import topics
from appeals.codebook.questions import (FURTHEST, GROUP_NAMES, GROUPS, JUDGMENT, LEVELS, NOT_STATED, OTHER_KINDS,
                                       OTHER_LEVELS, OTHER_NAMES, K1, T1, G2, G3, G4, C1, C3, C4, C5, S1, S2, S3,
                                       S4)
from appeals.graph.expr import If, T
from appeals.graph.expr import StepAnswer as A
from appeals.graph.nodes import Base, Step
from appeals.graph.values import Count, DateValue, KnownName, ListOf, Name, OneOf, Quoted, Record, Text, YesNo


def _paragraphs(*paragraphs):
    return '\n\n'.join(paragraphs)


base = Base('base', None, framing=_paragraphs(
    'You are reading every published decision in one docket of the Vermont Superior Court, Environmental Division. '
    'The decisions follow, in posting order, each marked <document n="…"> with its pages marked <page n="…">. Answer '
    'only about this docket. A decision may also cover other dockets; use only what it says about this one.',
    'Answer only what each question asks, briefly. Quote exactly: copy a short continuous passage from the text, and '
    'cite its document and page numbers. When the documents do not establish an answer, the answer is "not stated". '
    '"Not stated" is never the same as "no". Never infer an outcome from a ruling on a motion.'))

QUOTE_IT = 'Answer from the documents, with a quote.'
CONFIRM = 'Confirm or refute it from the documents: refuting it is a normal answer when the documents don\'t bear it out.'


def _choice(question):
    return Quoted(OneOf(question.options, not_stated=True))


def _yes_none():
    """A yes/no question whose "no" can rest on the documents showing nothing: "none found" needs no quote."""
    return Quoted(YesNo(not_stated=True), none_found=True)


def _slug(key):
    return re.sub(r'\W+', '_', key).strip('_')


def _bucket(probability):
    """Which prompt a flagged item gets: how sure the scan was that it is "yes"."""
    return If(probability >= T.sure, 'scan fairly confident', 'scan uncertain')


def _variants(claim, question):
    return {
        'scan fairly confident': _paragraphs(f'The scan was fairly confident that {claim}. {CONFIRM}',
                                             f'{question} {QUOTE_IT}'),
        'scan uncertain': _paragraphs(f'The scan was uncertain whether {claim}. Decide from the documents.',
                                      f'{question} {QUOTE_IT}')}


# ---- Scope: one chain, halting as soon as the docket is out ------------------------------

MUNICIPAL_PERMIT = ['municipal permit application', 'several, including a municipal permit application']
# A step that can't tell ("not stated") doesn't end the chain: the scope fields then keep the scan's answer.

L1a = Step('L1a', topics.SCOPE, title='Scope: kind of proceeding', when=G.scope_check,
    prompt=_paragraphs(
        'The scan was unsure whether this docket is in the study: an appeal of a municipal decision on an application '
        'for new housing. This question and the ones after it check that.',
        '{S1}', QUOTE_IT),
    returns=Record(proceeding=_choice(S1)), halt_unless=A('L1a', 'proceeding').in_([*MUNICIPAL_PERMIT, NOT_STATED]))

L1b = Step('L1b', topics.SCOPE, title='Scope: physical change', when=G.scope_check, after=L1a,
    prompt=_paragraphs('{S2}', QUOTE_IT),
    returns=Record(change=_choice(S2)),
    halt_unless=~A('L1b', 'change').in_(['authorize something already built', 'no physical change']))

L1c = Step('L1c', topics.SCOPE, title='Scope: housing use', when=G.scope_check, after=L1b,
    prompt=_paragraphs('{S3}', QUOTE_IT),
    returns=Record(housing=_choice(S3)), halt_unless=A('L1c', 'housing').in_(['yes', NOT_STATED]))

L1d = Step('L1d', topics.SCOPE, title='Scope: dwelling units', when=G.scope_check, after=L1c,
    prompt=_paragraphs('{S4}', QUOTE_IT),
    returns=Record(units=_choice(S4)),
    halt_unless=A('L1d', 'units').in_(['adds', 'replaces', NOT_STATED]) | A('L1b', 'change').is_('create building lots'))


# ---- A · Filing date ---------------------------------------------------------------------

L2a = Step('L2a', topics.FILING, title='Filing date',
    prompt=_paragraphs(
        '{F1}',
        'Give the date this appeal was filed with the Environmental Court (the notice of appeal), as precisely as a '
        'document states it: YYYY-MM-DD, YYYY-MM or YYYY. Use only a date a document gives for the filing; never infer '
        'it from the docket number or from other events. If no document states it, answer "not stated".'),
    returns=Record(filing_date=Quoted(DateValue())))

L2b = Step('L2b', topics.FILING, title='Earliest dated event', after=L2a,
    only_if=A('L2a', 'filing_date').in_([NOT_STATED, None]),
    prompt='No filing date is stated. Give the date of the earliest dated event in the documents that shows this '
           'appeal already existed, such as a motion, conference, hearing or order in this docket, as precisely as '
           'stated. The municipal decision under appeal does not count, since it came before the appeal. Never use the '
           'docket number.',
    returns=Record(earliest_event=Quoted(DateValue())))


# ---- B · The town's decision, then the kinds of permission at issue ----------------------

L3a = Step('L3a', topics.TOWN, title='Town\'s decision',
    prompt=_paragraphs('{T1}', QUOTE_IT),
    returns=Record(decision=_choice(T1)))

L3b = Step('L3b', topics.TOWN, title='Date of the town\'s decision', after=L3a,
    prompt='Give the date of that municipal decision, the one appealed in this docket, as precisely as stated '
           '(YYYY-MM-DD, YYYY-MM or YYYY), with a quote. When the documents give both the date the body voted and the '
           'date it issued its written decision, give the written decision\'s date. If no document dates it, answer '
           '"not stated".',
    returns=Record(decision_date=Quoted(DateValue())))

TOWN = KnownName(towns.NAMES, 'Vermont towns and cities', suggest=towns.suggest)
SHARED_NAMES = '; '.join(f'"{n} City" or "{n} Town"' for n in towns.SHARED)

L3c = Step('L3c', topics.TOWN, title='Town and place', after=L3b,
    prompt=_paragraphs(
        'In which Vermont town or city is the project at issue located? Give its name as the State of Vermont writes '
        f'it, such as "St. Johnsbury". Where a city and a town share a name, say which: {SHARED_NAMES}.',
        'If the documents name a village or other place within that town or city where the project is, such as Quechee '
        'in Hartford, give it as the place; otherwise the place is "not stated".',
        'Answer both from the documents, each with a quote.'),
    returns=Record(town=Quoted(TOWN), place=Quoted(Name())))

# The step's own wording of a kind, where the scan's wording leans on the rest of its list.
KIND_WORDING = {
    'variance': 'a statutory variance (not a waiver of a dimensional requirement)',
    'other': 'another kind of permission (not subdivision, site plan, planned unit development or master plan, '
             'conditional use, variance, or zoning or building permit approval)',
}
KINDS = {key: Step(f'L3_{_slug(key)}', topics.KINDS, title=f'Permission: {key}',
    set_item=(K1, key), short_title=key,
    only_if=K1.p(key) >= T.check, choose=_bucket(K1.p(key)),
    variants=_variants(f'{KIND_WORDING.get(key, meaning)} is at issue in this appeal',
                       f'Is {KIND_WORDING.get(key, meaning)} part of the municipal decision being appealed?'),
    returns=Record(at_issue=_yes_none()))
    for key, meaning in K1.items.items()}


# ---- B · Appellants, then who represented them -----------------------------------------------

ROLES = {'applicant or owner': 'The applicant or property owner seeking permission.',
         'individual neighbor': 'A neighbor or nearby owner or resident.',
         'group of neighbors': 'A named group of neighbors (counted as neighbors).',
         'other organization': 'An organization that is not a group of neighbors.',
         'municipality': 'The town or one of its bodies.',
         'state agency': 'A state agency.',
         'other': 'Someone else.'}
REPRESENTATION = {'represented by a lawyer': 'An attorney appeared for them at some point in this docket.',
                  'self-represented': 'The documents say they represented themselves.'}
ROLE = OneOf(ROLES)
REPRESENTATION_KIND = OneOf(REPRESENTATION)
APPELLANT = Record(name=Name(), role=ROLE)
LAWYER = Record(name=Name(), firm=Name())
APPELLANT_LAWYER = Record(appellant=Name(), representation=REPRESENTATION_KIND, lawyer=Name(), firm=Name())

L4a = Step('L4a', topics.APPELLANTS, title='Appellants',
    prompt=_paragraphs(
        '{A1}',
        'List every appellant in this docket: whoever brought this appeal or a cross-appeal, not every party. One entry '
        'per named person or organization (a couple is two entries). Give each one\'s name and who they are, with a '
        'quote.'),
    returns=Record(appellants=ListOf(Quoted(APPELLANT))))

L4b = Step('L4b', topics.APPELLANTS, title='Each appellant\'s lawyers', after=L4a,
    for_each=(L4a, 'appellants'), item='{name} ({role})', limit=10,
    prompt=_paragraphs(
        'Was {item} represented by a lawyer at any point in this docket? Only an attorney counts: a spokesperson, '
        'neighbor or anyone else who is not a lawyer speaking for them does not. Answer "self-represented" only when '
        'the documents say they represented themselves, and "not stated" when the documents don\'t say.',
        'If a lawyer represented them, list every lawyer who appeared for them, with the law firm when stated '
        '(otherwise "not stated"), and quote the passage that shows it.'),
    returns=Record(representation=Quoted(REPRESENTATION_KIND), lawyers=ListOf(LAWYER)))


# ---- D, E · How the docket ended, then when (before the counts: the court's count needs the result) ----------------------------

L5a = Step('L5a', topics.COURT, title='A final decision', when=G.final,
    prompt=_paragraphs(
        '{C2}',
        'Is there a decision of the Environmental Court that leaves nothing pending in this docket: a final judgment, '
        'dismissal, approved settlement or withdrawal? Partial rulings do not count. If there is, quote the concluding '
        'passage of the first such decision; later post-judgment proceedings do not change which decision was first.'),
    returns=Record(final=_yes_none()))

FINAL = A('L5a', 'final').is_('yes')
FOR_THAT_DECISION = 'Answer for the decision you identified as the first to leave nothing pending, with a quote.'

L5b = Step('L5b', topics.COURT, title='How the docket ended', when=G.final, after=L5a, only_if=FINAL,
    prompt=_paragraphs('{C3}', FOR_THAT_DECISION),
    returns=Record(ended=_choice(C3)))

L5c = Step('L5c', topics.COURT, title='What the court did', when=G.final, after=L5b,
    only_if=A('L5b', 'ended').is_('decided on the merits'),
    prompt=_paragraphs('{C4}', FOR_THAT_DECISION),
    returns=Record(result=_choice(C4)))

L5d = Step('L5d', topics.COURT, title='Dismissal basis', when=G.final, after=L5b,
    only_if=A('L5b', 'ended').is_('dismissed'),
    prompt=_paragraphs('{C5}', FOR_THAT_DECISION),
    returns=Record(dismissal_basis=_choice(C5)))


# ---- … the end date, in the same chain --------------------------------------------------------------------

L5e = Step('L5e', topics.COURT, title='Date of the final decision', after=L5a, only_if=FINAL,
    prompt='Give the date of the decision you identified as the first that left nothing pending in this docket, as '
           'precisely as stated (YYYY-MM-DD, YYYY-MM or YYYY), with a quote.',
    returns=Record(final_decision_date=Quoted(DateValue())))

L5f = Step('L5f', topics.COURT, title='Date of the latest order', after=L5a, only_if=~FINAL,
    prompt='No decision appears to end this docket. Give the date of the latest dated order or decision in the '
           'documents, as precisely as stated (YYYY-MM-DD, YYYY-MM or YYYY), with a quote.',
    returns=Record(latest_order_date=Quoted(DateValue())))


# ---- A, B, F · Dwelling units added, one count at a time --------------------------------------

UNITS_ADDED = ('Count only the new dwelling units the project would create. Existing units that would remain are not '
               'counted, even when the documents give a total for the whole property or development, and neither '
               'are units an earlier permit already approved that the project keeps unchanged, built or not. A unit '
               'that replaces one removed counts as one. Never derive a number of units from lots or bedrooms.')

L6a = Step('L6a', topics.UNITS, title='Units added: proposed', when=G.counts,
    prompt=_paragraphs('{U1}', 'How many new dwelling units would the project add, as the application proposed it?',
                       UNITS_ADDED),
    returns=Record(proposed=Quoted(Count())))

L6b = Step('L6b', topics.UNITS, title='Appeal covers only part', when=G.counts, after=L6a,
    prompt=_paragraphs('{U2}', QUOTE_IT),
    returns=Record(partial=_yes_none()))

L6c = Step('L6c', topics.UNITS, title='Units added: under appeal', when=G.counts, after=L6b,
    only_if=A('L6b', 'partial').is_('yes'),
    prompt=_paragraphs('How many new dwelling units are in the part of the project under appeal?', UNITS_ADDED),
    returns=Record(under_appeal=Quoted(Count())))

L6d = Step('L6d', topics.UNITS, title='New housing lots', when=G.counts, after=L6a,
    prompt=_paragraphs('{U3}', 'How many new building lots for housing would the application create? Count only new '
                               'lots, not the parcel being divided.'),
    returns=Record(lots=Quoted(Count())))

# The town's and the court's counts are compared (unit_change), so both count the same thing: a denial approved no units,
# and when only part of the project is appealed, both count that part.
PART_ONLY = 'When only part of the project is under appeal, count only that part.'

L6e = Step('L6e', topics.UNITS, title='Units added: town approved', when=G.counts, after=L6c,
    prompt=_paragraphs('How many new dwelling units did the municipal decision under appeal approve? If it denied the '
                       f'application, the answer is 0, with a quote of the denial. {PART_ONLY}', UNITS_ADDED),
    returns=Record(town_approved=Quoted(Count())))

# The scan's two comparisons of the court's result belong with the court's count, not the town's.
L6f = Step('L6f', topics.UNITS, title='Units added: court approved', when=G.counts, after=L6e,
    only_if=A('L5c', 'result').in_(['granted', 'granted with conditions', 'denied']),
    prompt=_paragraphs('{U4}', '{U5}', 'How many new dwelling units did the court\'s decision ending this docket '
                                       'approve? If the court denied the application, the answer is 0, with a quote of '
                                       f'the denial. {PART_ONLY}', UNITS_ADDED),
    returns=Record(court_approved=Quoted(Count())))


# ---- C · Grounds: arguments stated, challenged conditions, each judgment standard, each other question ----

L7a = Step('L7a', topics.GROUNDS, title='Arguments stated', when=G.grounds,
    prompt=_paragraphs('{G1}', QUOTE_IT),
    returns=Record(stated=Quoted(YesNo(not_stated=False), none_found=True)))

STATED = A('L7a', 'stated').is_('yes')

# Challenged conditions, one question at a time: whether, which, then who and what the court did for each.
L7b = Step('L7b', topics.GROUNDS, title='Condition challenged', when=G.grounds, after=L7a,
    only_if=STATED & (G4.p('yes') >= T.check),
    prompt=_paragraphs('{G4}', QUOTE_IT),
    returns=Record(challenged=Quoted(YesNo(not_stated=False), none_found=True)))

L7c = Step('L7c', topics.GROUNDS, title='Which conditions', when=G.grounds, after=L7b,
    only_if=A('L7b', 'challenged').is_('yes'),
    prompt='List each condition attached to the permit that a party challenged (or asked the court to add, change or '
           'remove), as you described. For each, say in a few words what the condition requires, such as "a '
           'recreational easement to the town" or "no more than two building permits a year", with a quote showing the '
           'challenge.',
    returns=Record(conditions=ListOf(Quoted(Text(), quote_required=True))))

CHALLENGERS = {'applicant or owner': 'The applicant or property owner.',
               'neighbor or other appellant': 'A neighbor, a group of neighbors, or another party opposing the project.',
               'municipality': 'The town or one of its bodies.',
               'other': 'Someone else.'}
L7d = Step('L7d', topics.GROUNDS, title='Who challenged each condition', when=G.grounds, after=L7c,
    for_each=(L7c, 'conditions'), limit=5,
    prompt=f'Who challenged this condition: {{item}}? {QUOTE_IT}',
    returns=Record(challenged_by=Quoted(OneOf(CHALLENGERS))))

OUTCOMES = {'upheld': 'The court kept the condition as it was.',
            'struck': 'The court removed the condition.',
            'changed': 'The court changed the condition.',
            'added': 'The court added the condition a party asked for.',
            'refused': 'The court refused to add the condition a party asked for.',
            'not decided': 'The documents show no ruling on it.'}
L7e = Step('L7e', topics.GROUNDS, title='What the court did with each condition', when=G.grounds, after=L7c,
    for_each=(L7c, 'conditions'), limit=5,
    prompt=f'What did the court do with this condition: {{item}}? {QUOTE_IT}',
    returns=Record(outcome=Quoted(OneOf(OUTCOMES))))

# Each kind of judgment standard the scan flags: a chain of up to three calls, independent of the other kinds.
# How far it got comes first; the result only for a decided level; whether the dispute was about a condition
# only for "decided, disputed". A skipped result is "not decided" and a skipped condition "no" (see fields.py).
RESULTS = {'met': 'The court found the project meets the standard.',
           'met with conditions': 'Met, and the permit carries a condition aimed at this standard.',
           'partly met': 'Granted in part and denied in part, such as for some lots and not others.',
           'not met': 'The court found the project does not meet the standard.',
           'not decided': 'The level is not a decided level.'}
DECIDED_RESULTS = {k: v for k, v in RESULTS.items() if k != 'not decided'}
DECIDED = ['decided, disputed', 'decided, not disputed']
DECIDED_OR_OPEN = ['raised only', 'taken up', 'decided, disputed', 'decided, not disputed', 'set aside']
QUOTE_LEVEL = 'Quote the passage that best shows the level: for "decided, disputed", the dispute or the ruling.'


def _scan_level(placeholder, what):
    """The two ways of stating the scan's reading of a kind, by how sure it was that the kind is at issue."""
    return {
        'scan fairly confident': f'The scan judged that this docket dealt with this kind of {what}, most likely at the '
                                 f'level "{{{placeholder}}}". {CONFIRM}',
        'scan uncertain': f'The scan was unsure whether this docket dealt with this kind of {what} (if it did, most '
                          f'likely at the level "{{{placeholder}}}"). Decide from the documents.'}


def _group_prompt(key, scan):
    return _paragraphs(
        f'The kind of standard: {GROUPS[key]}.',
        scan,
        f'How far did this docket get with a standard of this kind? {JUDGMENT}',
        '"Disputed" means a party actually contested whether the project meets the standard, including an applicant '
        'appealing a denial on it; a finding the court made only because it runs through every criterion is not '
        f'disputed. {FURTHEST}',
        'A dispute over a condition counts under the group whose standard the condition serves (a challenged phasing '
        'deadline justified by the burden on municipal services is traffic and services).',
        QUOTE_LEVEL)


GROUP_SCAN = {key: _scan_level(f'G2.{key}', 'standard') for key in GROUPS}
GROUND_STEPS = {key: Step(f'L8_{key}', topics.GROUNDS, title=f'Grounds: {GROUP_NAMES[key]}', when=G.grounds,
    set_item=(G2, key), short_title=GROUP_NAMES[key],
    only_if=STATED & (G2.applies(key) >= T.check),
    choose=If(G2.applies(key) >= T.sure, 'scan fairly confident', 'scan uncertain'),
    variants={name: _group_prompt(key, scan) for name, scan in GROUP_SCAN[key].items()},
    returns=Record(level=Quoted(OneOf(LEVELS, not_stated=False))))
    for key in GROUPS}

GROUND_RESULTS = {key: Step(f'L8_{key}_result', topics.GROUNDS, title=f'Grounds: {GROUP_NAMES[key]}, result',
    short_title='result',
    when=G.grounds, after=GROUND_STEPS[key], only_if=A(f'L8_{key}', 'level').in_(DECIDED),
    prompt='What did the court decide about whether the project meets this kind of standard?',
    returns=Record(result=OneOf(DECIDED_RESULTS, not_stated=False)))
    for key in GROUPS}

GROUND_CONDITIONS = {key: Step(f'L8_{key}_condition', topics.GROUNDS, title=f'Grounds: {GROUP_NAMES[key]}, condition',
    short_title='condition',
    when=G.grounds, after=GROUND_RESULTS[key], only_if=A(f'L8_{key}', 'level').is_('decided, disputed'),
    prompt='Was the dispute over this kind of standard about a condition the municipality attached, or one a party '
           'asked the court to add, change or remove?',
    returns=Record(condition=YesNo(not_stated=False)))
    for key in GROUPS}

RELIEF_KINDS = {'statutory variance': 'A variance under 24 V.S.A. § 4469 and the bylaw\'s variance criteria '
                                      '(unique circumstances, hardship not created by the applicant, minimum relief).',
                'bylaw waiver': 'A waiver of a dimensional requirement that the town\'s bylaw allows (24 V.S.A. § 4414(8)).',
                'planned development modification': 'A change to dimensional standards approved as part of a planned unit '
                                                    'or residential development (24 V.S.A. § 4417).'}
L8_relief_kind = Step('L8_relief_kind', topics.GROUNDS, title='Kind of dimensional relief', short_title='kind',
    when=G.grounds,
    after=GROUND_STEPS['relief'], only_if=A('L8_relief', 'level').in_(DECIDED_OR_OPEN),
    prompt='Which kind of dimensional relief was this? Answer from the name and the test the documents use, with a '
           'quote.',
    returns=Record(kind=Quoted(OneOf(RELIEF_KINDS))))


# Each other kind of question the scan flags: one call, independent of the others. These flag more often than
# the judgment groups, so they follow up at a 0.5 chance of being at issue, which lost no case in the answer key.
# They run for every docket that proceeds, whether or not the appellant's arguments are stated: a docket
# dismissed before anyone argued the merits is exactly the kind "who can appeal" explains.

def _other_prompt(key, scan):
    return _paragraphs(
        f'The kind of question: {OTHER_KINDS[key]}.',
        scan,
        'How far did this docket get with a question of this kind? Count it only for this docket\'s appeal, not for a '
        f'sibling docket or a coordinated civil action decided in the same decision. {FURTHEST}',
        'A rule, permit or doctrine the decision only recites (background facts, the legal standard, a list of '
        'sections) is "not at issue". Whether the project meets a standard calling for judgment, and variances or '
        'waivers, are not this kind of question.',
        QUOTE_LEVEL)


OTHER_SCAN = {key: _scan_level(f'G3.{key}', 'question') for key in OTHER_KINDS}
OTHER_STEPS = {key: Step(f'L9_{key}', topics.GROUNDS, title=f'Other question: {OTHER_NAMES[key]}',
    set_item=(G3, key), short_title=OTHER_NAMES[key],
    only_if=G3.applies(key) >= T.other_check,
    choose=If(G3.applies(key) >= T.sure, 'scan fairly confident', 'scan uncertain'),
    variants={name: _other_prompt(key, scan) for name, scan in OTHER_SCAN[key].items()},
    returns=Record(level=Quoted(OneOf(OTHER_LEVELS, not_stated=False))))
    for key in OTHER_KINDS}


# ---- D · Review standard --------------------------------------------------------------------

L10 = Step('L10', topics.COURT, title='Review standard', when=G.review,
    prompt=_paragraphs(
        '{C1}',
        'Quote the passage that establishes how the Environmental Court heard this appeal of the municipal decision. '
        '"De novo" said of summary judgment, a question of law or the Supreme Court\'s review does not count.'),
    returns=Record(standard=_choice(C1)))


# ---- F · Stay, then its dates; design change, then what it was -----------------------------------

L11a = Step('L11a', topics.STAY_DESIGN, title='Court stayed the permit', when=G.stay,
    prompt=_paragraphs(
        '{D1}',
        'Did the court itself stop construction or stay the permit in this docket? Stays ordered by the town do not '
        f'count. {QUOTE_IT}'),
    returns=Record(stayed=_yes_none()))

L11b = Step('L11b', topics.STAY_DESIGN, title='Stay dates', when=G.stay, after=L11a, only_if=A('L11a', 'stayed').is_('yes'),
    prompt='Give the dates the court\'s stay started and ended, as precisely as stated (YYYY-MM-DD, YYYY-MM or YYYY), '
           'each with a quote.',
    returns=Record(start=Quoted(DateValue()), end=Quoted(DateValue())))

L12a = Step('L12a', topics.STAY_DESIGN, title='Court changed size or design', when=G.design,
    prompt=_paragraphs(
        '{D2}',
        'Did the court itself impose conditions that change the buildings\' size or design? Changes the municipality '
        f'made do not count. {QUOTE_IT}'),
    returns=Record(changed=_yes_none()))

L12b = Step('L12b', topics.STAY_DESIGN, title='The size or design change', when=G.design, after=L12a,
    only_if=A('L12a', 'changed').is_('yes'),
    prompt='Describe the change the court imposed in one sentence, with a quote.',
    returns=Record(description=Quoted(Text())))


ORDER = [L1a, L1b, L1c, L1d,
         L2a, L2b,
         L3a, L3b, L3c, *KINDS.values(),
         L4a, L4b,
         L5a, L5b, L5c, L5d, L5e, L5f,
         L6a, L6b, L6c, L6d, L6e, L6f,
         L7a, L7b, L7c, L7d, L7e,
         *(s for k in GROUND_STEPS for s in (GROUND_STEPS[k], GROUND_RESULTS[k], GROUND_CONDITIONS[k])),
         L8_relief_kind, *OTHER_STEPS.values(),
         L10,
         L11a, L11b, L12a, L12b]
