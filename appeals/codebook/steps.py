"""Layer 3: the Base and the reasoning steps, in the order they run.

Each step asks for one detail, with its evidence, and must reply with JSON of
its `returns` type; malformed replies are sent back for correction. Details
that depend on each other run as a chain: each step names the step it follows
(`after`), keeps the exchanges along that line in context, and runs only if
earlier answers call for it (`only_if`). Steps are numbered by chain, in the
order the chains run, and lettered by their order within a chain. A placeholder such as {B2} is filled with that question and
the scan's answer.
"""
import re

from appeals.codebook import gates as G
from appeals.codebook.questions import NOT_STATED, A7, B1, C5, D3, D4, D5, S1, S2, S3, S4, S5
from appeals.graph.expr import If, T
from appeals.graph.expr import StepAnswer as A
from appeals.graph.nodes import Base, Step
from appeals.graph.values import Count, DateValue, ListOf, Name, OneOf, Quoted, Record, Text, YesNo

base = Base('base', 'steps', framing="""
You are reading every published decision in one docket of the Vermont Superior Court, Environmental Division.
The decisions follow, in posting order, each marked <document n="…"> with its pages marked <page n="…">.
Answer only about this docket. A decision may also cover other dockets; use only what it says about this one.
Each question asks for one thing. Answer only that, briefly.
Quote exactly: copy a short continuous passage from the text, and cite its document and page numbers.
When the documents do not establish an answer, the answer is "not stated". "Not stated" is never the same as "no".
Never infer an outcome from a ruling on a motion.""")

QUOTE_IT = 'Answer from the documents, with a quote.'


def _choice(question):
    return Quoted(OneOf(question.options, not_stated=True))


def _yes_no():
    return Quoted(YesNo(not_stated=True))


def _slug(key):
    return re.sub(r'\W+', '_', key).strip('_')


def _bucket(probability):
    """Which prompt a flagged item gets: how sure the scan was that it is "yes"."""
    return If(probability >= T.sure, 'scan fairly confident', 'scan uncertain')


def _variants(claim, question):
    return {
        'scan fairly confident': f"""The scan was fairly confident that {claim}.
Confirm or refute it from the documents. Refuting it is a normal answer when the documents don't bear it out.
{question} {QUOTE_IT}""",
        'scan uncertain': f"""The scan was uncertain whether {claim}.
Decide from the documents. {question} {QUOTE_IT}"""}


# ---- Scope: one chain, halting as soon as the docket is out ------------------------------

L1a = Step('L1a', 'scope', title='Scope: municipal decision', when=G.scope_check,
    prompt=f"""The decision model was unsure whether this docket is a municipal appeal about new housing.
{{S1}}
{QUOTE_IT}""",
    returns=Record(S1=_choice(S1)), halt_unless=A('L1a', 'S1').is_('yes'), confirms=['S1'])

L1b = Step('L1b', 'scope', title='Scope: kind of action', when=G.scope_check, after=L1a,
    prompt=f"""{{S2}}
{QUOTE_IT}""",
    returns=Record(S2=_choice(S2)), halt_unless=A('L1b', 'S2').is_('application for permission'), confirms=['S2'])

L1c = Step('L1c', 'scope', title='Scope: physical change', when=G.scope_check, after=L1b,
    prompt=f"""{{S3}}
{QUOTE_IT}""",
    returns=Record(S3=_choice(S3)),
    halt_unless=~A('L1c', 'S3').in_(['authorize something already built', 'no physical change']), confirms=['S3'])

L1d = Step('L1d', 'scope', title='Scope: housing use', when=G.scope_check, after=L1c,
    prompt=f"""{{S4}}
{QUOTE_IT}""",
    returns=Record(S4=_choice(S4)), halt_unless=A('L1d', 'S4').is_('yes'), confirms=['S4'])

L1e = Step('L1e', 'scope', title='Scope: dwelling units', when=G.scope_check, after=L1d,
    prompt=f"""{{S5}}
{QUOTE_IT}""",
    returns=Record(S5=_choice(S5)),
    halt_unless=A('L1e', 'S5').in_(['adds', 'replaces']) | A('L1c', 'S3').is_('create building lots'),
    confirms=['S5'])


# ---- A · Filing date ---------------------------------------------------------------------

L2a = Step('L2a', 'A', title='Filing date',
    prompt="""{A1}
Give the date this appeal was filed with the Environmental Court (the notice of appeal), as precisely as a document
states it: YYYY-MM-DD, YYYY-MM or YYYY. Use only a date a document gives for the filing; never infer it from the
docket number or from other events. If no document states it, answer "not stated".""",
    returns=Record(filing_date=Quoted(DateValue())), confirms=['A1'])

L2b = Step('L2b', 'A', title='Earliest dated event', after=L2a,
    only_if=A('L2a', 'filing_date').in_([NOT_STATED, None]),
    prompt="""No filing date is stated. Give the date of the earliest dated event in the documents that shows this
appeal already existed, such as a motion, conference, hearing or order in this docket, as precisely as stated.
The municipal decision under appeal does not count, since it came before the appeal. Never use the docket number.""",
    returns=Record(earliest_event=Quoted(DateValue())), confirms=[])


# ---- B · The town's decision, then the kinds of permission at issue ----------------------

L3 = Step('L3', 'B', title='Town\'s decision',
    prompt=f"""{{B1}}
{QUOTE_IT}""",
    returns=Record(decision=_choice(B1)), confirms=['B1'])

KINDS = {key: Step(f'L3_{_slug(key)}', 'A', title=f'Permission: {key}',
    only_if=A7.p(key) >= T.check, choose=_bucket(A7.p(key)),
    variants=_variants(f'{meaning} is at issue in this appeal',
                       f'Is {meaning} part of the municipal decision being appealed?'),
    returns=Record(at_issue=_yes_no()), confirms=['A7'])
    for key, meaning in A7.items.items()}


# ---- B · Appellants, then who represented them -----------------------------------------------

ROLES = {'applicant or owner': 'The applicant or property owner seeking permission.',
         'individual neighbor': 'A neighbor or nearby owner or resident.',
         'group of neighbors': 'A named group of neighbors (counted as neighbors).',
         'other organization': 'An organization that is not a group of neighbors.',
         'municipality': 'The town or one of its bodies.',
         'state agency': 'A state agency.',
         'other': 'Someone else.'}
REPRESENTATION = {'represented by a lawyer': 'A lawyer appeared for them.',
                  'self-represented': 'The documents say they represented themselves.'}
ROLE = OneOf(ROLES)
REPRESENTATION_KIND = OneOf(REPRESENTATION)
APPELLANT = Record(name=Name(), role=ROLE)
APPELLANT_LAWYER = Record(name=Name(), representation=REPRESENTATION_KIND)

L4a = Step('L4a', 'B', title='Appellants',
    prompt="""List every appellant in this docket: whoever brought this appeal or a cross-appeal, not every party.
One entry per named person or organization (a couple is two entries). Give each one's name and who they are,
with a quote.
{B2}""",
    returns=Record(appellants=ListOf(Quoted(APPELLANT))), confirms=['B2'])

L4b = Step('L4b', 'B', title='Appellants\' lawyers', after=L4a,
    prompt="""For each appellant you listed, say whether a lawyer represented them, with a quote. Say
"self-represented" only when the documents say so, and "not stated" when they say neither.""",
    returns=Record(representation=ListOf(Quoted(APPELLANT_LAWYER))), confirms=[])


# ---- D, E · How the docket ended, then when (before the counts: the court's count needs the result) ----------------------------

L5a = Step('L5a', 'D', title='A final decision', when=G.final,
    prompt="""{D2}
Is there a decision of the Environmental Court that leaves nothing pending in this docket: a final judgment,
dismissal, approved settlement or withdrawal? Partial rulings do not count. If there is, quote the concluding
passage of the first such decision; later post-judgment proceedings do not change which decision was first.""",
    returns=Record(final=_yes_no()), confirms=['D2'])

FINAL = A('L5a', 'final').is_('yes')

L5b = Step('L5b', 'D', title='How the docket ended', when=G.final, after=L5a, only_if=FINAL,
    prompt=f"""How did that decision end this docket?
{{D3}}
{QUOTE_IT}""",
    returns=Record(ended=_choice(D3)), confirms=['D3'])

L5c = Step('L5c', 'D', title='What the court did', when=G.final, after=L5b,
    only_if=A('L5b', 'ended').is_('decided on the merits'),
    prompt=f"""In that decision, what did the court do with the application?
{{D4}}
{QUOTE_IT}""",
    returns=Record(result=_choice(D4)), confirms=['D4'])

L5d = Step('L5d', 'D', title='Dismissal basis', when=G.final, after=L5b,
    only_if=A('L5b', 'ended').is_('dismissed'),
    prompt=f"""On what basis did the court dismiss the appeal?
{{D5}}
{QUOTE_IT}""",
    returns=Record(dismissal_basis=_choice(D5)), confirms=['D5'])


# ---- … the end date, in the same chain --------------------------------------------------------------------

L5e = Step('L5e', 'E', title='Date of the final decision', after=L5a, only_if=FINAL,
    prompt="""Give the date of the decision you identified as the first that left nothing pending in this docket,
as precisely as stated (YYYY-MM-DD, YYYY-MM or YYYY), with a quote.""",
    returns=Record(final_decision_date=Quoted(DateValue())), confirms=[])

L5f = Step('L5f', 'E', title='Date of the latest order', after=L5a, only_if=~FINAL,
    prompt="""No decision appears to end this docket. Give the date of the latest dated order or decision in the
documents, as precisely as stated (YYYY-MM-DD, YYYY-MM or YYYY), with a quote.""",
    returns=Record(latest_order_date=Quoted(DateValue())), confirms=[])


# ---- A, B, F · Dwelling units added, one count at a time --------------------------------------

UNITS_ADDED = """Count only the new dwelling units the project would create. Existing units that would remain are not
counted, even when the documents give a total for the whole property or development. A unit that replaces one
removed counts as one. Never derive a number of units from lots or bedrooms."""

L6a = Step('L6a', 'A', title='Units added: proposed', when=G.counts,
    prompt=f"""{{A4}}
How many new dwelling units would the project add, as the application proposed it?
{UNITS_ADDED}""",
    returns=Record(proposed=Quoted(Count())), confirms=['A4'])

L6b = Step('L6b', 'A', title='Appeal covers only part', when=G.counts, after=L6a,
    prompt=f"""{{A5}}
{QUOTE_IT}""",
    returns=Record(partial=_yes_no()), confirms=['A5'])

L6c = Step('L6c', 'A', title='Units added: under appeal', when=G.counts, after=L6b,
    only_if=A('L6b', 'partial').is_('yes'),
    prompt=f"""How many new dwelling units are in the part of the project under appeal?
{UNITS_ADDED}""",
    returns=Record(under_appeal=Quoted(Count())), confirms=[])

L6d = Step('L6d', 'A', title='New housing lots', when=G.counts, after=L6a,
    prompt="""{A6}
How many new building lots for housing would the application create? Count only new lots, not the parcel being
divided.""",
    returns=Record(lots=Quoted(Count())), confirms=['A6'])

L6e = Step('L6e', 'B', title='Units added: town approved', when=G.counts, after=L6c,
    prompt=f"""How many new dwelling units did the municipal decision under appeal approve?
{UNITS_ADDED}
{{F2}}""",
    returns=Record(town_approved=Quoted(Count())), confirms=[])

L6f = Step('L6f', 'F', title='Units added: court approved', when=G.counts, after=L6e,
    only_if=A('L5c', 'result').in_(['granted', 'granted with conditions']),
    prompt=f"""How many new dwelling units did the court's decision ending this docket approve?
{UNITS_ADDED}
{{F3}}""",
    returns=Record(court_approved=Quoted(Count())), confirms=['F2', 'F3'])


# ---- C · Grounds: whether arguments are stated, then each claim about them ----------------------

L7a = Step('L7a', 'C', title='Arguments stated', when=G.discretion,
    prompt=f"""{{C1}}
{QUOTE_IT}""",
    returns=Record(stated=Quoted(YesNo(not_stated=False))), confirms=['C1'])

STATED = A('L7a', 'stated').is_('yes')

L7b = Step('L7b', 'C', title='Disputes applying a standard', when=G.discretion, after=L7a, only_if=STATED,
    prompt=f"""{{C2}}
A judgment-based standard is one that calls for judgment, such as compatibility with the neighborhood, the
character of the area, or adequacy. {QUOTE_IT}""",
    returns=Record(applied=_yes_no()), confirms=['C2'])

L7c = Step('L7c', 'C', title='Challenges a standard\'s validity', when=G.discretion, after=L7b,
    only_if=STATED,
    prompt=f"""{{C3}}
{QUOTE_IT}""",
    returns=Record(validity=_yes_no()), confirms=['C3'])

L7d = Step('L7d', 'C', title='Standard a principal issue', when=G.discretion, after=L7c,
    only_if=STATED,
    prompt=f"""{{C4}}
{QUOTE_IT}""",
    returns=Record(principal=_yes_no()), confirms=['C4'])

ISSUES = {key: Step(f'L8_{_slug(key)}', 'C', title=f'Issue: {key}',
    only_if=C5.p(key) >= T.check, choose=_bucket(C5.p(key)),
    variants=_variants(f'the appellant raised {meaning} as an issue in this appeal',
                       f'Did the appellant raise {meaning} as an issue in this appeal?'),
    returns=Record(raised=_yes_no()), confirms=['C5'])
    for key, meaning in C5.items.items()}


# ---- D · Review standard --------------------------------------------------------------------

L9 = Step('L9', 'D', title='Review standard', when=G.review,
    prompt="""{D1}
Quote the passage that establishes how the Environmental Court heard this appeal of the municipal decision.
"De novo" said of summary judgment, a question of law or the Supreme Court's review does not count.""",
    returns=Record(standard=Quoted(OneOf({'de novo': 'Heard anew.', 'on the record': 'Reviewed the municipal record.'}))),
    confirms=['D1'])


# ---- F · Stay, then its dates; design change, then what it was -----------------------------------

L10a = Step('L10a', 'F', title='Court stayed the permit', when=G.stay,
    prompt=f"""{{F1}}
Did the court itself stop construction or stay the permit in this docket? Stays ordered by the town do not count.
{QUOTE_IT}""",
    returns=Record(stayed=_yes_no()), confirms=['F1'])

L10b = Step('L10b', 'F', title='Stay dates', when=G.stay, after=L10a, only_if=A('L10a', 'stayed').is_('yes'),
    prompt="""Give the dates the court's stay started and ended, as precisely as stated (YYYY-MM-DD, YYYY-MM or
YYYY), each with a quote.""",
    returns=Record(start=Quoted(DateValue()), end=Quoted(DateValue())), confirms=[])

L11a = Step('L11a', 'F', title='Court changed size or design', when=G.design,
    prompt=f"""{{F5}}
Did the court itself impose conditions that change the buildings' size or design? Changes the municipality made do
not count. {QUOTE_IT}""",
    returns=Record(changed=_yes_no()), confirms=['F5'])

L11b = Step('L11b', 'F', title='The size or design change', when=G.design, after=L11a,
    only_if=A('L11a', 'changed').is_('yes'),
    prompt="""Describe the change the court imposed in one sentence, with a quote.""",
    returns=Record(description=Quoted(Text())), confirms=[])


ORDER = [L1a, L1b, L1c, L1d, L1e,
         L2a, L2b,
         L3, *KINDS.values(),
         L4a, L4b,
         L5a, L5b, L5c, L5d, L5e, L5f,
         L6a, L6b, L6c, L6d, L6e, L6f,
         L7a, L7b, L7c, L7d, *ISSUES.values(),
         L9,
         L10a, L10b, L11a, L11b]
