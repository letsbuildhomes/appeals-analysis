"""Layer 4: fields, one settled value per docket each.

A field takes its step's answer when the step ran and its quote checks out,
otherwise the scan's most likely answer (when it has a scan question), and
otherwise "not stated". A `not_stated_if` rule overrides all of that when an
earlier answer makes the question moot. Codes refer to docs/PIPELINE.md.
"""
from appeals.codebook import questions as Q
from appeals.codebook import steps as L
from appeals.codebook import topics
from appeals.graph.expr import StepAnswer as A
from appeals.graph.expr import T
from appeals.graph.nodes import Field
from appeals.graph.values import NONE_FOUND, NOT_STATED, Count, DateValue, ListOf, Name, OneOf, Record, Text, YesNo
from appeals.ingest.dockets import filing_period


def _choice(question):
    return OneOf(question.options, not_stated=True)


def _items(question_set):
    return Record(**{key: YesNo(not_stated=True) for key in question_set.items})


def docket_number_filing(number):
    """The month (128-8-10 Vtec) or year (25-ENV-00114) the docket number says the appeal was filed."""
    return filing_period(number) or 'not stated'


# ---- Scope ---------------------------------------------------------------------------
proceeding = Field('proceeding', topics.SCOPE, label='Kind of proceeding',
                   type=_choice(Q.S1), scan=Q.S1, step=L.L1a, scan_if_unsure=True, path='proceeding',
                   notes=['Answered for every docket, so out-of-scope dockets say what they are.',
                          '"Several, including a municipal permit application" counts as in scope.',
                          'An appeal of a preliminary step on an application, such as sketch plan review, counts as a '
                          'municipal permit application even when the court holds the step was not appealable: those '
                          'appeals are in the study, and the grounds record why they were thrown out.'])
physical_change = Field('physical_change', topics.SCOPE, label='What the permission allows',
                        type=_choice(Q.S2), scan=Q.S2, step=L.L1b, scan_if_unsure=True, path='change',
                        notes=["'Authorize something already built' (after-the-fact permits) and 'no physical change' are out of scope."])
housing_use = Field('housing_use', topics.SCOPE, label='Used for housing',
                    type=_choice(Q.S3), scan=Q.S3, step=L.L1c, scan_if_unsure=True, path='housing',
                    notes=['"Group or care housing" (assisted living, nursing homes, dormitories, group homes) is in scope, '
                           'kept apart from "yes" so it can be left out. Its unit counts are "not stated" unless the '
                           'documents describe dwelling units.'])
units_effect = Field('units_effect', topics.SCOPE, label='Adds or replaces units',
                     type=_choice(Q.S4), scan=Q.S4, step=L.L1d, scan_if_unsure=True, path='units')

# ---- A · Which decisions -----------------------------------------------------------------
filing_date = Field('filing_date', topics.FILING, label='Filing date', type=DateValue(),
                    step=L.L2a, path='filing_date')
earliest_event = Field('earliest_event', topics.FILING, label='Earliest dated event', type=DateValue(),
                       step=L.L2b, path='earliest_event')
docket_filing = Field('docket_filing', topics.FILING, label='Filing month or year from the docket number',
                      type=DateValue(), from_docket=docket_number_filing,
                      notes=['Read by code from the docket number: 128-8-10 Vtec was filed in August 2010, 25-ENV-00114 in 2025.',
                             'A bound on the filing date (the appeal was filed by then), not the filing date itself.'])
municipality = Field('municipality', topics.TOWN, label='Municipality', type=L.TOWN, step=L.L3c, path='town',
                     notes=['One of Vermont\'s 256 towns, cities, gores and grants, written as the codebook lists them '
                            '(from the Census Bureau); a name shared by a city and a town says which, such as "Rutland City".',
                            'A village belongs to its town; the village is the place (place_within_town). A place that is '
                            'now its own city or town goes under its own name when the documents use it, whenever the '
                            'decision was made: "Essex Junction", a village of Essex until 2022, but "Essex" when the '
                            'documents say only Essex.'])
place_within_town = Field('place_within_town', topics.TOWN, label='Place within the town', type=Name(),
                          step=L.L3c, path='place',
                          notes=['A village or other named place within the town where the project is, such as Quechee in '
                                 'Hartford, when the documents name one.'])
units_added_proposed = Field('units_added_proposed', topics.UNITS, label='Units added: proposed', type=Count(),
                             step=L.L6a, path='proposed',
                             notes=['Units an earlier permit already approved and the project keeps unchanged are not '
                                    'counted, built or not: a revision of an approved development counts only the units '
                                    'it changes.'])
appeal_partial = Field('appeal_partial', topics.UNITS, label='Appeal covers only part', type=_choice(Q.U2),
                       scan=Q.U2, step=L.L6b, path='partial')
units_added_under_appeal = Field('units_added_under_appeal', topics.UNITS, label='Units added: under appeal',
                                 type=Count(), step=L.L6c, path='under_appeal')
housing_lots = Field('housing_lots', topics.UNITS, label='New housing lots', type=Count(),
                     step=L.L6d, path='lots')
permission_kinds = Field('permission_kinds', topics.KINDS, label='Kinds of permission', type=_items(Q.K1),
                         scan=Q.K1, steps=L.KINDS, path='at_issue')

# ---- B · Who appeals ---------------------------------------------------------------------
town_decision = Field('town_decision', topics.TOWN, label='Town\'s decision', type=_choice(Q.T1),
                      scan=Q.T1, step=L.L3a, path='decision',
                      notes=['One answer for the whole decision: the outcomes are exclusive. A deemed approval counts as approved.',
                             '"Approved" means the documents don\'t say the approval carried conditions, not that it had none: '
                             'decisions often never describe the town\'s conditions.'])
town_decision_date = Field('town_decision_date', topics.TOWN, label='Date of the town\'s decision',
                           type=DateValue(), step=L.L3b, path='decision_date',
                           notes=['The date of the municipal decision appealed in this docket; the written decision\'s date when the vote and the written decision differ.',
                                  'Starts the duration when no exact filing date is stated (duration).'])
appellants_named = Field('appellants_named', topics.APPELLANTS, label='All appellants named', type=_choice(Q.A1),
                         scan=Q.A1)
appellants = Field('appellants', topics.APPELLANTS, label='Appellants', type=ListOf(L.APPELLANT, not_stated=True),
                   step=L.L4a, path='appellants',
                   notes=['Only appellants with a verified quote are listed.',
                          '"Not stated" means the list was never established, which is different from an empty list.',
                          'A named group of neighbors counts as neighbors, not as an organization.'])
def lawyer_rows(item, answer):
    """One entry per lawyer who appeared for the appellant, or a single entry when none did."""
    kind = answer['representation']['answer']
    lawyers = answer['lawyers'] if kind == 'represented by a lawyer' else []
    entry = {'appellant': item['name'], 'representation': kind}
    return ([entry | {'lawyer': lawyer['name'], 'firm': lawyer['firm']} for lawyer in lawyers]
            or [entry | {'lawyer': NOT_STATED, 'firm': NOT_STATED}])


appellant_lawyers = Field('appellant_lawyers', topics.APPELLANTS, label='Appellants\' representation',
                          type=ListOf(L.APPELLANT_LAWYER, not_stated=True), step=L.L4b, path='representation',
                          per_item=lawyer_rows,
                          notes=['Asked one appellant at a time, for the first 10 appellants listed; appellant_mix '
                                 'gives how many there are in all.',
                                 'Represented means an attorney appeared for them at any point in the docket. A '
                                 'non-lawyer speaking for them is not representation.',
                                 'One entry per lawyer, so an appellant with two lawyers has two entries. Names and '
                                 'firms are as written; the same lawyer may be spelled differently across dockets.'])
units_added_town_approved = Field('units_added_town_approved', topics.UNITS, label='Units added: town approved',
                                  type=Count(), step=L.L6e, path='town_approved',
                                  notes=['0 when the town denied the application. When only part of the project is '
                                         'under appeal, only that part is counted, as in the court\'s count.'])

# ---- C · Grounds -------------------------------------------------------------------------
NO_ARGUMENTS = A('L7a', 'stated').in_(['no', NONE_FOUND]) | (Q.G1.p('yes') < T.grounds)
arguments_stated = Field('arguments_stated', topics.GROUNDS, label='Arguments stated', type=_choice(Q.G1),
                         scan=Q.G1, step=L.L7a, path='stated',
                         notes=['A procedural dismissal whose documents don\'t say what the appellant argued leaves the '
                                'judgment standards (G2) and conditions (G4) "not stated"; the other questions (G3) are '
                                'still answered.'])


def _per_group(kind):
    return Record(**{key: kind for key in Q.GROUPS})


GROUND_NOTES = [
    'One item per kind of judgment standard: ' + '; '.join(f'{k} = {v}' for k, v in Q.GROUP_NAMES.items()) + '.',
    'A judgment standard leaves the outcome to judgment, with no measurable test, and counts only where it is applied '
    'to this project. Disputes over measurable rules, the court\'s procedural discretion, equitable and constitutional '
    'claims, and impacts argued only for standing are not judgment standards; the other questions (G3) record them.',
    '"Decided, disputed" means a party contested whether the project meets the standard and the court ruled: that is '
    'what makes a standard central (judgment_central). A finding made only because the court runs through every criterion is '
    '"decided, not disputed".',
    'A kind the scan gave less than a 0.3 chance of being at issue gets no follow-up and keeps the scan\'s answer.']
judgment_grounds = Field('judgment_grounds', topics.GROUNDS, label='Judgment standards: how far each got',
                         type=_per_group(OneOf(Q.LEVELS, not_stated=True)), scan=Q.G2, steps=L.GROUND_STEPS,
                         path='level', not_stated_if=NO_ARGUMENTS, notes=GROUND_NOTES)
judgment_results = Field('judgment_results', topics.GROUNDS, label='Judgment standards: the court\'s result',
                         type=_per_group(OneOf(L.RESULTS, not_stated=True)), steps=L.GROUND_RESULTS, path='result',
                         vouched_by='level', vouchers=L.GROUND_STEPS, if_skipped='not decided', not_stated_if=NO_ARGUMENTS,
                         notes=['"Not stated" for a kind that got no follow-up (the scan saw it as not at issue).',
                                '"Met with conditions" only when a condition is aimed at that kind of standard.'])
judgment_conditions = Field('judgment_conditions', topics.GROUNDS, label='Judgment standards: dispute about a condition',
                            type=_per_group(YesNo(not_stated=True)), steps=L.GROUND_CONDITIONS, path='condition',
                            vouched_by='level', vouchers=L.GROUND_STEPS, if_skipped='no', not_stated_if=NO_ARGUMENTS,
                            notes=['Whether the dispute the court ruled on for that kind of standard was about a '
                                   'condition the municipality attached, or one a party asked the court to add, change '
                                   'or remove.',
                                   'Asked only when the level is "decided, disputed"; any other level reads "no".'])
relief_kind = Field('relief_kind', topics.GROUNDS, label='Kind of dimensional relief', type=OneOf(L.RELIEF_KINDS),
                    step=L.L8_relief_kind, path='kind', not_stated_if=NO_ARGUMENTS,
                    notes=['Only "statutory variance" is a variance in the legal sense (24 V.S.A. § 4469). Counts of '
                           'dimensional relief include bylaw waivers and planned-development modifications.'])
OTHER_NOTES = [
    'One item per other kind of question: ' + '; '.join(f'{k} = {v}' for k, v in Q.OTHER_NAMES.items()) + '.',
    'Several kinds can apply to one docket. With the judgment standards (G2) they show what an appeal turned on: '
    'for an appeal with no central judgment standard (judgment_central no), the kinds at "decided, disputed" are what it was about.',
    '"Decided, disputed" means a party contested the question and the court ruled on it.',
    'A kind the scan gave less than a 0.5 chance of being at issue gets no follow-up and keeps the scan\'s answer.',
    'Answered for every docket in scope, including those whose documents don\'t say what the appellant argued, '
    'such as an appeal dismissed as untimely before the merits.']
other_questions = Field('other_questions', topics.GROUNDS, label='Other questions: how far each got',
                        type=Record(**{key: OneOf(Q.OTHER_LEVELS, not_stated=True) for key in Q.OTHER_KINDS}),
                        scan=Q.G3, steps=L.OTHER_STEPS, path='level', notes=OTHER_NOTES)
conditions_challenged = Field('conditions_challenged', topics.GROUNDS, label='A condition was challenged',
                              type=_choice(Q.G4), scan=Q.G4, step=L.L7b, path='challenged', not_stated_if=NO_ARGUMENTS,
                              notes=['Challenges to whether a condition should be imposed or how strict it is, '
                                     'including opposing the removal of one. Not: whether one was met, what one means, '
                                     'or the applicant\'s own unopposed conditions.'])


def condition_challengers(item, answer):
    return [{'condition': item, 'challenged_by': answer['challenged_by']['answer']}]


def condition_outcome(item, answer):
    return [{'condition': item, 'outcome': answer['outcome']['answer']}]


conditions_challenged_by = Field('conditions_challenged_by', topics.GROUNDS, label='Who challenged each condition',
                                 type=ListOf(Record(condition=Text(), challenged_by=OneOf(L.CHALLENGERS)),
                                             not_stated=True),
                                 step=L.L7d, path='challenged_by', per_item=condition_challengers,
                                 notes=['Up to five conditions per docket; the condition is described in a few words.'])
conditions_outcome = Field('conditions_outcome', topics.GROUNDS, label='What the court did with each condition',
                           type=ListOf(Record(condition=Text(), outcome=OneOf(L.OUTCOMES)), not_stated=True),
                           step=L.L7e, path='outcome', per_item=condition_outcome,
                           notes=['Up to five conditions per docket. Match to conditions_challenged_by by the '
                                  'condition\'s description.'])

# ---- D · The court -----------------------------------------------------------------------
NOT_FINAL = A('L5a', 'final').in_(['no', NONE_FOUND])
review_standard = Field('review_standard', topics.COURT, label='Review standard', type=_choice(Q.C1),
                        scan=Q.C1, step=L.L10, path='standard')
final_decision = Field('final_decision', topics.COURT, label='A decision ends the docket', type=_choice(Q.C2),
                       scan=Q.C2, step=L.L5a, path='final',
                       notes=["The end of the case is the court's first decision that leaves nothing pending in this docket. Partial rulings don't end it, and later post-judgment proceedings don't extend it.",
                              'An outcome is never inferred from a ruling on a motion.'])
how_ended = Field('how_ended', topics.COURT, label='How the docket ended', type=_choice(Q.C3),
                  scan=Q.C3, step=L.L5b, path='ended', not_stated_if=NOT_FINAL)
court_result = Field('court_result', topics.COURT, label='What the court did', type=_choice(Q.C4),
                     scan=Q.C4, step=L.L5c, path='result',
                     not_stated_if=NOT_FINAL | A('L5b', 'ended').in_(['dismissed', 'settled', 'withdrawn']),
                     notes=['"Granted" means the documents don\'t say the court attached or kept conditions, not that '
                            'there were none.'])
dismissal_basis = Field('dismissal_basis', topics.COURT, label='Dismissal basis', type=_choice(Q.C5),
                        scan=Q.C5, step=L.L5d, path='dismissal_basis',
                        not_stated_if=NOT_FINAL | A('L5b', 'ended').in_(['decided on the merits', 'settled', 'withdrawn']))

# ---- E · How long ------------------------------------------------------------------------
final_decision_date = Field('final_decision_date', topics.COURT, label='Date of the first final decision',
                            type=DateValue(), step=L.L5e, path='final_decision_date')
latest_order_date = Field('latest_order_date', topics.COURT, label='Date of the latest order',
                          type=DateValue(), step=L.L5f, path='latest_order_date',
                          notes=['Filled only when no decision ends the docket. It bounds the end of the case from below; it is not the end.'])

# ---- F · Cost to housing -------------------------------------------------------------------
stayed = Field('stayed', topics.STAY_DESIGN, label='Court stayed the permit', type=_choice(Q.D1),
               scan=Q.D1, step=L.L11a, path='stayed',
               notes=['Only stays the court imposed.'])
stay_start = Field('stay_start', topics.STAY_DESIGN, label='Stay start', type=DateValue(), step=L.L11b, path='start')
stay_end = Field('stay_end', topics.STAY_DESIGN, label='Stay end', type=DateValue(), step=L.L11b, path='end')
units_vs_town = Field('units_vs_town', topics.UNITS, label='Units added vs the town\'s decision',
                      type=_choice(Q.U4), scan=Q.U4,
                      notes=['From the scan only: a direction with a probability, no quote.'])
units_vs_application = Field('units_vs_application', topics.UNITS, label='Units added vs the application',
                             type=_choice(Q.U5), scan=Q.U5,
                             notes=['From the scan only: a direction with a probability, no quote.'])
units_added_court_approved = Field('units_added_court_approved', topics.UNITS, label='Units added: court approved',
                                   type=Count(), step=L.L6f, path='court_approved',
                                   notes=['0 when the court denied the application. When only part of the project is '
                                          'under appeal, only that part is counted, as in the town\'s count.'])
design_changed = Field('design_changed', topics.STAY_DESIGN, label='Court changed size or design', type=_choice(Q.D2),
                       scan=Q.D2, step=L.L12a, path='changed',
                       notes=["Only changes the court imposed; changes the town made belong to the town's decision."])
design_change = Field('design_change', topics.STAY_DESIGN, label='The size or design change', type=Text(),
                      step=L.L12b, path='description',
                      notes=['Free text from the reasoning model, describing the change; never scored.'])

ALL = [proceeding, physical_change, housing_use, units_effect,
       filing_date, earliest_event, docket_filing, municipality, place_within_town, units_added_proposed, appeal_partial,
       units_added_under_appeal, housing_lots, permission_kinds,
       town_decision, town_decision_date, appellants_named, appellants, appellant_lawyers,
       units_added_town_approved,
       arguments_stated, judgment_grounds, judgment_results, judgment_conditions, relief_kind, other_questions,
       conditions_challenged, conditions_challenged_by, conditions_outcome,
       review_standard, final_decision, how_ended, court_result, dismissal_basis,
       final_decision_date, latest_order_date,
       stayed, stay_start, stay_end, units_vs_town, units_vs_application, units_added_court_approved,
       design_changed, design_change]
