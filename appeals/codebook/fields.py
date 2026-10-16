"""Layer 4: fields, one settled value per docket each.

A field takes its step's answer when the step ran and its quote checks out,
otherwise the scan's most likely answer (when it has a scan question), and
otherwise "not stated". A `not_stated_if` rule overrides all of that when an
earlier answer makes the question moot. Codes refer to docs/PIPELINE.md.
"""
from appeals.codebook import questions as Q
from appeals.codebook import steps as L
from appeals.graph.expr import StepAnswer as A
from appeals.graph.nodes import Field
from appeals.graph.values import Count, DateValue, ListOf, Name, OneOf, Record, Text, YesNo
from appeals.ingest.dockets import filing_period


def _choice(question):
    return OneOf(question.options, not_stated=True)


def _items(question_set):
    return Record(**{key: YesNo(not_stated=True) for key in question_set.items})


def docket_number_filing(number):
    """The month (128-8-10 Vtec) or year (25-ENV-00114) the docket number says the appeal was filed."""
    return filing_period(number) or 'not stated'


# ---- Scope ---------------------------------------------------------------------------
municipal_body = Field('municipal_body', 'scope', code='S1', label='Appeal of a municipal body or officer',
                       type=_choice(Q.S1), scan=Q.S1, step=L.L1a, path='S1')
action_kind = Field('action_kind', 'scope', code='S2', label='Kind of municipal action',
                    type=_choice(Q.S2), scan=Q.S2, step=L.L1b, path='S2')
physical_change = Field('physical_change', 'scope', code='S3', label='What the permission allows',
                        type=_choice(Q.S3), scan=Q.S3, step=L.L1c, path='S3',
                        notes=["'Authorize something already built' (after-the-fact permits) and 'no physical change' are out of scope."])
housing_use = Field('housing_use', 'scope', code='S4', label='Used for housing',
                    type=_choice(Q.S4), scan=Q.S4, step=L.L1d, path='S4')
units_effect = Field('units_effect', 'scope', code='S5', label='Adds or replaces units',
                     type=_choice(Q.S5), scan=Q.S5, step=L.L1e, path='S5')

# ---- A · Which decisions -----------------------------------------------------------------
filing_date = Field('filing_date', 'A', code='A1', label='Filing date', type=DateValue(),
                    step=L.L2a, path='filing_date')
earliest_event = Field('earliest_event', 'A', code='A2', label='Earliest dated event', type=DateValue(),
                       step=L.L2b, path='earliest_event')
docket_filing = Field('docket_filing', 'A', code='A2', label='Filing month or year from the docket number',
                      type=DateValue(), from_docket=docket_number_filing,
                      notes=['Read by code from the docket number: 128-8-10 Vtec was filed in August 2010, 25-ENV-00114 in 2025.',
                             'A bound on the filing date (the appeal was filed by then), not the filing date itself.'])
municipality = Field('municipality', 'A', code='A3', label='Municipality', type=Name(), scan=Q.A3,
                     notes=['One of the Vermont municipalities named in the documents, chosen by the scan; it has no quote.'])
units_added_proposed = Field('units_added_proposed', 'A', code='A4', label='Units added: proposed', type=Count(),
                             step=L.L5a, path='proposed')
appeal_partial = Field('appeal_partial', 'A', code='A5', label='Appeal covers only part', type=_choice(Q.A5),
                       scan=Q.A5, step=L.L5b, path='partial')
units_added_under_appeal = Field('units_added_under_appeal', 'A', code='A5', label='Units added: under appeal',
                                 type=Count(), step=L.L5c, path='under_appeal')
housing_lots = Field('housing_lots', 'A', code='A6', label='New housing lots', type=Count(),
                     step=L.L5d, path='lots')
permission_kinds = Field('permission_kinds', 'A', code='A7', label='Kinds of permission', type=_items(Q.A7),
                         scan=Q.A7, steps=L.KINDS, path='at_issue')

# ---- B · Who appeals ---------------------------------------------------------------------
town_decision = Field('town_decision', 'B', code='B1', label='Town\'s decision', type=_choice(Q.B1),
                      scan=Q.B1, step=L.L3, path='decision',
                      notes=['One answer for the whole decision: the outcomes are exclusive. A deemed approval counts as approved.'])
appellants_named = Field('appellants_named', 'B', code='B2', label='All appellants named', type=_choice(Q.B2),
                         scan=Q.B2)
appellants = Field('appellants', 'B', code='B3', label='Appellants', type=ListOf(L.APPELLANT, not_stated=True),
                   step=L.L4a, path='appellants',
                   notes=['Only appellants with a verified quote are listed.',
                          '"Not stated" means the list was never established, which is different from an empty list.',
                          'A named group of neighbors counts as neighbors, not as an organization.'])
appellant_lawyers = Field('appellant_lawyers', 'B', code='B4', label='Appellants\' representation',
                          type=ListOf(L.APPELLANT_LAWYER, not_stated=True), step=L.L4b, path='representation')
units_added_town_approved = Field('units_added_town_approved', 'B', code='B5', label='Units added: town approved',
                                  type=Count(), step=L.L5e, path='town_approved')

# ---- C · Grounds -------------------------------------------------------------------------
NO_ARGUMENTS = A('L6a', 'stated').is_('no')
arguments_stated = Field('arguments_stated', 'C', code='C1', label='Arguments stated', type=_choice(Q.C1),
                         scan=Q.C1, step=L.L6a, path='stated',
                         notes=['A procedural dismissal whose documents don\'t say what the appellant argued leaves the grounds (C1–C5) "not stated".'])
disputes_application = Field('disputes_application', 'C', code='C2', label='Disputes applying a judgment standard',
                             type=_choice(Q.C2), scan=Q.C2, step=L.L6b, path='applied', not_stated_if=NO_ARGUMENTS)
challenges_validity = Field('challenges_validity', 'C', code='C3', label='Challenges a standard\'s validity',
                            type=_choice(Q.C3), scan=Q.C3, step=L.L6c, path='validity', not_stated_if=NO_ARGUMENTS)
principal_issue = Field('principal_issue', 'C', code='C4', label='Judgment standard a principal issue',
                        type=_choice(Q.C4), scan=Q.C4, step=L.L6d, path='principal', not_stated_if=NO_ARGUMENTS)
issues_raised = Field('issues_raised', 'C', code='C5', label='Issues raised', type=_items(Q.C5),
                      scan=Q.C5, steps=L.ISSUES, path='raised')

# ---- D · The court -----------------------------------------------------------------------
NOT_FINAL = A('L9a', 'final').is_('no')
review_standard = Field('review_standard', 'D', code='D1', label='Review standard', type=_choice(Q.D1),
                        scan=Q.D1, step=L.L8, path='standard')
final_decision = Field('final_decision', 'D', code='D2', label='A decision ends the docket', type=_choice(Q.D2),
                       scan=Q.D2, step=L.L9a, path='final',
                       notes=["The end of the case is the court's first decision that leaves nothing pending in this docket. Partial rulings don't end it, and later post-judgment proceedings don't extend it.",
                              'An outcome is never inferred from a ruling on a motion.'])
how_ended = Field('how_ended', 'D', code='D3', label='How the docket ended', type=_choice(Q.D3),
                  scan=Q.D3, step=L.L9b, path='ended', not_stated_if=NOT_FINAL)
court_result = Field('court_result', 'D', code='D4', label='What the court did', type=_choice(Q.D4),
                     scan=Q.D4, step=L.L9c, path='result',
                     not_stated_if=NOT_FINAL | A('L9b', 'ended').in_(['dismissed', 'settled', 'withdrawn']))
dismissal_basis = Field('dismissal_basis', 'D', code='D5', label='Dismissal basis', type=_choice(Q.D5),
                        scan=Q.D5, step=L.L9d, path='dismissal_basis',
                        not_stated_if=NOT_FINAL | A('L9b', 'ended').in_(['decided on the merits', 'settled', 'withdrawn']))

# ---- E · How long ------------------------------------------------------------------------
final_decision_date = Field('final_decision_date', 'E', code='E1', label='Date of the first final decision',
                            type=DateValue(), step=L.L10a, path='final_decision_date')
latest_order_date = Field('latest_order_date', 'E', code='E2', label='Date of the latest order',
                          type=DateValue(), step=L.L10b, path='latest_order_date',
                          notes=['Filled only when no decision ends the docket. It bounds the end of the case from below; it is not the end.'])

# ---- F · Cost to housing -------------------------------------------------------------------
stayed = Field('stayed', 'F', code='F1', label='Court stayed the permit', type=_choice(Q.F1),
               scan=Q.F1, step=L.L11a, path='stayed',
               notes=['Only stays the court imposed.'])
stay_start = Field('stay_start', 'F', code='F1', label='Stay start', type=DateValue(), step=L.L11b, path='start')
stay_end = Field('stay_end', 'F', code='F1', label='Stay end', type=DateValue(), step=L.L11b, path='end')
units_vs_town = Field('units_vs_town', 'F', code='F2', label='Units added vs the town\'s decision',
                      type=_choice(Q.F2), scan=Q.F2,
                      notes=['From the scan only: a direction with a probability, no quote.'])
units_vs_application = Field('units_vs_application', 'F', code='F3', label='Units added vs the application',
                             type=_choice(Q.F3), scan=Q.F3,
                             notes=['From the scan only: a direction with a probability, no quote.'])
units_added_court_approved = Field('units_added_court_approved', 'F', code='F4', label='Units added: court approved',
                                   type=Count(), step=L.L5f, path='court_approved')
design_changed = Field('design_changed', 'F', code='F5', label='Court changed size or design', type=_choice(Q.F5),
                       scan=Q.F5, step=L.L12a, path='changed',
                       notes=["Only changes the court imposed; changes the town made belong to the town's decision."])
design_change = Field('design_change', 'F', code='F5', label='The size or design change', type=Text(),
                      step=L.L12b, path='description',
                      notes=['Free text from the reasoning model, describing the change; never scored.'])

ALL = [municipal_body, action_kind, physical_change, housing_use, units_effect,
       filing_date, earliest_event, docket_filing, municipality, units_added_proposed, appeal_partial,
       units_added_under_appeal, housing_lots, permission_kinds,
       town_decision, appellants_named, appellants, appellant_lawyers,
       units_added_town_approved,
       arguments_stated, disputes_application, challenges_validity, principal_issue, issues_raised,
       review_standard, final_decision, how_ended, court_result, dismissal_basis,
       final_decision_date, latest_order_date,
       stayed, stay_start, stay_end, units_vs_town, units_vs_application, units_added_court_approved,
       design_changed, design_change]
