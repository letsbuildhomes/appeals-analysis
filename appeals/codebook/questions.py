"""Layer 1: the closed questions, all asked in one scan by the decision model.

Each question is self-contained: the decision model sees only its text and
options, never its ID. IDs and answer sets follow docs/PIPELINE.md.
"""

from appeals.codebook import topics
from appeals.graph.nodes import ChoiceSet, Question, YesNoSet

NOT_STATED = 'not stated'
NS = 'The documents do not establish it.'

# ---- Scope ---------------------------------------------------------------------------

S1 = Question('S1', topics.SCOPE,
    ask='What kind of proceeding is this docket? Answer for the decision appealed in this docket, even if the '
        'appellants mainly attack an earlier permit, and not for a sibling docket decided in the same decision.',
    options={'municipal permit application': 'An appeal of a decision by a municipal body or officer (such as a '
                 'development review board, planning commission, zoning board of adjustment or zoning '
                 'administrator) on an application for a permit or approval, such as a zoning permit, '
                 'subdivision, site plan or conditional use approval. This includes an appeal of a preliminary step '
                 'on such an application, such as sketch plan review, even if the court holds that step was not '
                 'appealable.',
             'several, including a municipal permit application': 'The docket covers more than one decision, and one '
                 'of them is a municipal decision on a permit application, such as a municipal appeal heard together '
                 'with an Act 250 or state permit appeal of the same project.',
             'municipal enforcement': 'A municipal notice of violation, enforcement action, or decision whether to '
                 'enforce.',
             'municipal bylaw or policy': 'The adoption or validity of a municipal bylaw, ordinance, plan or policy.',
             'other municipal decision': 'Another decision of a municipal body or officer.',
             'Act 250 permit': 'An Act 250 land use permit decision by a District Commission or the District '
                 'Coordinator.',
             'ANR stormwater permit': 'A stormwater permit decision by the Agency of Natural Resources (Department of '
                 'Environmental Conservation).',
             'ANR wastewater permit': 'A wastewater system or potable water supply permit decision by the Agency of '
                 'Natural Resources (Department of Environmental Conservation).',
             'other state permit or decision': 'Another permit or decision of a state agency, such as a wetland or '
                 'water quality permit.',
             'state enforcement': 'An enforcement action or order brought by a state agency or the Natural Resources '
                 'Board.',
             'other': 'Something else, including a proceeding that is not an appeal of a decision.',
             NOT_STATED: NS},
    why='The study covers appeals of municipal decisions on applications for permission. The other kinds show what '
        'the rest of the court\'s docket is, and the stormwater and wastewater permits are of separate interest.')

S2 = Question('S2', topics.SCOPE,
    ask='Physically, what would the permission at issue allow? If it would both create lots and build dwellings, '
        'answer that it builds (the lots are counted separately).',
    options={'build a new structure': 'Constructing a new building or structure.',
             'place a structure': 'Placing a structure, such as a mobile home.',
             'convert or renovate an existing building': 'Converting or substantially renovating an existing building.',
             'convert a non-residential use to housing': 'Turning all or part of a non-residential building or space, '
                                                         'such as an office, store or barn, into dwelling units, with or '
                                                         'without construction.',
             'create building lots': 'Subdividing land into building lots, or releasing a restriction (such as '
                                     'open space) so an existing lot becomes a building lot.',
             'authorize something already built': 'Approving, after the fact, something already built or done.',
             'no physical change': 'A change of use, occupancy or operations without construction that creates no '
                                   'dwelling units.',
             NOT_STATED: NS},
    why='Scope comes from what would be built, placed, converted or subdivided.')

S3 = Question('S3', topics.SCOPE,
    ask='Will the structure, building or lots at issue be used for housing, where people live?',
    options={'yes': 'The documents say the structure or lots are for housing in dwelling units, such as houses or '
                    'apartments. Lots in a residential district count unless the documents show another use, and a '
                    'project that is mostly another use counts if it adds at least one dwelling unit.',
             'group or care housing': 'Residents will live there, but in rooms or beds rather than dwelling units, '
                                      'such as assisted living, a nursing home, a dormitory or a group home.',
             'no': 'The use is not housing, such as commercial, industrial or accessory use, or a road, '
                   'right-of-way, utility or other work that only serves homes or house lots. Seasonal camps, '
                   'recreational vehicles and condominium hotels are not housing unless the documents describe them as '
                   'year-round dwellings.',
             NOT_STATED: NS},
    why='New housing must be explicit in the documents. Group and care housing is kept apart so it can be counted or '
        'left out.')

S4 = Question('S4', topics.SCOPE,
    ask='Does the project add dwelling units, replace existing dwelling units one for one, or neither? For group or '
        'care housing, count residents\' rooms or beds instead of dwelling units.',
    options={'adds': 'It adds one or more dwelling units (or, in group or care housing, residents\' rooms or beds), '
                     'such as a new house on land with no existing dwelling. An amendment adds only units beyond '
                     'those already approved.',
             'replaces': 'It replaces existing dwelling units, such as rebuilding a house or replacing a mobile home.',
             'neither': 'It neither adds nor replaces dwelling units, including a subdivision that only creates lots '
                        'with no dwellings proposed (its lots are counted separately).',
             NOT_STATED: NS},
    why='An addition that creates no unit is not new housing; a replacement is.')


# ---- A · Which decisions -------------------------------------------------------------

F1 = Question('F1', topics.FILING,
    ask='Does any document state the date this appeal was filed with the court (the notice of appeal)?',
    options={'yes': 'A document states when the appeal was filed.', 'no': 'No document states the filing date.'},
    why='The filing date starts the duration. When it is not stated, the earliest dated event is used instead.')

U1 = Question('U1', topics.UNITS,
    ask='Do the documents state how many new dwelling units the project would add? Existing units that would remain '
        'are not part of that number.',
    options={'yes': 'The number of dwelling units the project would add is stated, or can be read directly from '
                    'what the documents say is proposed.',
             'no': 'The documents do not say how many units the project would add.'},
    why='Units added are the measure of new housing. Decides whether the counts steps run.')

U2 = Question('U2', topics.UNITS,
    ask='Is the appeal limited to part of the proposal, such as some areas, phases or units?',
    options={'yes': 'Only part of the proposal is under appeal.', 'no': 'The whole proposal is under appeal.',
             NOT_STATED: NS},
    why='The units at stake may be fewer than the units proposed.')

U3 = Question('U3', topics.UNITS,
    ask='Do the documents state how many new building lots for housing the application would create?',
    options={'yes': 'A number of new housing lots is stated.', 'no': 'No number of new housing lots is stated.'},
    why='Subdivisions create housing capacity before any house is proposed.')

K1 = YesNoSet('K1', topics.KINDS,
    ask='Is this kind of municipal permission at issue in this appeal?',
    items={'subdivision': 'subdivision approval', 'site plan': 'site plan approval',
           'planned development': 'planned unit development or master plan approval',
           'conditional use': 'conditional use approval', 'variance': 'a variance (the statutory variance, not a waiver)',
           'zoning permit': 'a zoning or building permit',
           'other': 'another kind of permission, such as a waiver'},
    why='What kind of approval was appealed.')


# ---- B · Who appeals -------------------------------------------------------------------

T1 = Question('T1', topics.TOWN,
    ask='What did the municipal decision appealed to this court decide on the application? When several municipal '
        'bodies decided in turn, this is the last decision, the one appealed to the court.',
    options={'approved': 'Approved the application, and the documents don\'t say the approval carried conditions. A '
                         'deemed approval, where the municipality failed to decide in time, counts as approved.',
             'approved with conditions': 'Approved the application, and the documents say conditions were attached.',
             'approved in part': 'Approved part of the application and denied part, including a decision that granted '
                                 'one permission and denied another.',
             'denied': 'Denied the application in full.',
             NOT_STATED: NS},
    why='What the appeal is against. The outcomes are exclusive, so one question asks for one of them.')

A1 = Question('A1', topics.APPELLANTS,
    ask='Are all of the appellants in this docket named, rather than only "X, et al." or a similar unnamed group?',
    options={'yes': 'Every appellant is named.', 'no': 'Some appellants are not named.'},
    why='Whether the list of appellants can be complete.')


# ---- C · Grounds ----------------------------------------------------------------------
# The definitions here were settled by the grounds experiments (scored against a 46-docket answer key).

G1 = Question('G1', topics.GROUNDS,
    ask='Do the documents say what the appellant argued in this appeal?',
    options={'yes': 'The appellant\'s arguments are described.',
             'no': 'The documents do not say what the appellant argued, for example a dismissal on procedural grounds.'},
    why='Without stated arguments, the grounds are "not stated".')

JUDGMENT = ('Count only a standard the project must meet whose terms leave the outcome to judgment, with no '
            'measurable test such as a number, distance or list, and only where it is applied to this project, not '
            'merely quoted in a list of criteria. A dispute over whether a measurable rule was met does not count, nor '
            'does the court\'s own discretion over its procedure (such as reopening an appeal period), an equitable '
            'claim such as estoppel, a constitutional test such as a taking or due process, or an impact argued only to '
            'show standing.')

LEVELS = {
    'not at issue': 'Not argued, and not considered by the court.',
    'raised only': 'A party argued it; the court has not addressed it.',
    'taken up': 'The court treated it as open without deciding it, such as denying summary judgment over disputed '
                'facts or setting it for trial.',
    'decided, disputed': 'A party contested whether the project meets it, and the court ruled on it.',
    'decided, not disputed': 'The court ruled whether the project meets it, but no party contested it, such as a short '
                             'finding in a run through every criterion.',
    'set aside': 'The court declined to reach it, such as outside the questions on appeal, no standing, moot or '
                 'withdrawn.',
}
FURTHEST = ('If several standards or documents differ, answer for the furthest point reached, in this order: decided, '
            'disputed; decided, not disputed; taken up; set aside; raised only.')

GROUPS = {
    'character': 'the character of the area or neighborhood, or whether the project\'s scale, mass, density, design or '
                 'appearance fits its surroundings, including scenic and aesthetic effects. Not: landscaping, '
                 'screening or buffers (site design)',
    'historic': 'historic sites, buildings or districts',
    'neighbor': 'nuisance effects on neighbors, such as noise, lighting, odor, dust or vibration, or loss of privacy, '
                'light, air or sun',
    'traffic': 'traffic safety, congestion, road capacity, circulation, access or street layout, or the capacity of '
               'community facilities and services such as schools, fire protection, or municipal water and sewer',
    'water': 'the project\'s water supply or wastewater disposal, stormwater, drainage or erosion, flood hazards, or '
             'natural resources such as wetlands, streams, wildlife habitat, agricultural soils or forest',
    'site': 'site design standards: landscaping, screening, buffers, open-space set-asides, or the design criteria of a '
            'planned unit or residential development (such as clustering or efficient use of land). It does not include '
            'a subdivision\'s or project\'s layout in general, roads, driveways or access (traffic), drainage or '
            'stormwater (water and environment), lot dimensions or other measurable rules, or a waiver of a dimensional '
            'requirement. Count it only where the parties argued about the design standard itself, not merely because a '
            'subdivision or development it applies to was contested',
    'relief': 'dimensional relief: the criteria for a variance or a waiver of a dimensional requirement such as '
              'frontage, setback or lot size, judged by tests such as unnecessary hardship, no reasonable use of the '
              'property, or the minimum relief needed (a variance\'s "essential character" criterion counts as the '
              'character of the area instead)',
}
GROUP_NAMES = {'character': 'character and fit', 'historic': 'historic', 'neighbor': 'neighbor effects',
               'traffic': 'traffic and services', 'water': 'water and environment', 'site': 'site design',
               'relief': 'dimensional relief (variances and waivers)'}

G2 = ChoiceSet('G2', topics.GROUNDS,
    ask=f'The kind of standard: {{item}}. How far did this docket get with a standard of this kind? {JUDGMENT} '
        f'{FURTHEST}',
    items=GROUPS, options=LEVELS, null='not at issue',
    why='Which kinds of judgment standard each appeal turned on, and how far each got. "Decided, disputed" is what '
        'makes a standard central to the appeal.')

# The other kinds of question an appeal can turn on, asked like the judgment groups so a docket shows every
# kind it had. Distilled from 25 candidates and scored against a 46-docket answer key (the grounds
# experiments, v4–v6).
OTHER_LEVELS = {
    'not at issue': 'Not argued, and not considered by the court.',
    'raised only': 'A party argued it; the court has not addressed it.',
    'taken up': 'The court treated it as open without deciding it, such as denying summary judgment over disputed '
                'facts or setting it for trial.',
    'decided, disputed': 'A party contested it, and the court ruled on it.',
    'decided, not disputed': 'The court ruled on it, but no party contested it.',
    'set aside': 'The court declined to reach it, such as outside the questions on appeal, no standing, moot or '
                 'withdrawn.',
}

# Each kind is the question the court must answer, with examples of how a decision puts it (the project owner,
# October 2026: affirmative definitions with examples, rather than lists of exclusions).
OTHER_KINDS = {
    'measurable': 'measurable rules. The question: does the project meet a rule with a measurable test, such as a '
                  'setback, height limit, minimum lot size or frontage, density limit or required number of parking '
                  'spaces? It reads like: "the addition sits 18 feet from the side line where 25 are required"; "the '
                  'lot has 140 feet of frontage, short of the 200 the district requires". When the parties also '
                  'dispute how the rule is measured, the method is a question of allowed use and defined terms, and '
                  'whether the project meets the rule is still this kind',
    'meaning': 'allowed use and defined terms. The question: what do the words of the bylaw or a permit mean for this '
               'project? Such as whether the use is allowed in the district or which use category it falls in, what a '
               'defined term such as "dwelling unit", "structure" or "lot" covers, how a measurable rule is measured, '
               'what an earlier permit\'s condition says, or whether the bylaw must be read to include 24 V.S.A. '
               '§ 4412\'s required provisions. It reads like: "Neighbors argue a sober house is not a \'single-family '
               'dwelling\'"; "Applicant contends lot width is measured at the building line". It counts when a party '
               'argues for a reading of the words, so its level is never "decided, not disputed"',
    'nonconforming': 'nonconforming uses and structures. The question: may a use, structure or lot that predates the '
                     'current rules continue, expand or change? It reads like: "the duplex is a preexisting '
                     'nonconforming use that was never abandoned"; "the addition increases the degree of '
                     'nonconformity"',
    'process': 'municipal process. The question: did the town handle the application lawfully, in its notice, its '
               'hearing, its review of completeness, or its decision (the findings, the timing, a deemed approval)? It '
               'reads like: "the DRB failed to warn the hearing"; "the decision issued more than 45 days after the '
               'hearing closed, so the permit is deemed approved"; "the findings do not explain the denial"',
    'appeal': 'who can appeal. The question: can this appeal, or this appellant, be heard by this court? Such as an '
              'appellant\'s standing or party status, whether the notice of appeal was on time, or whether the '
              'decision appealed was final and within the court\'s jurisdiction, or whether the court can review the '
              'application as changed on appeal. It reads like: "Neighbors lack '
              'interested-person status"; "the notice of appeal was filed 31 days after the decision"; "the zoning '
              'administrator\'s letter was not an appealable decision". It concerns the appeal or an appellant as a '
              'whole; the court narrowing single questions in the Statement of Questions is the court managing the '
              'appeal',
    'earlier': 'earlier permits and approvals. The question: does an earlier permit or decision control what may be '
               'approved now? Such as vested rights, the binding effect of an unappealed permit or decision, a '
               'successive application for the same project, amending an earlier permit, compliance with an earlier '
               'permit\'s conditions, or whether a plat label or condition is specific enough to enforce. It reads '
               'like: "Applicant has vested rights under the 2004 bylaw"; "the unappealed 2006 variance is binding"; '
               '"the application is barred as a successive application". It counts when a party relies on the '
               'earlier permit or decision as settling something now',
    'property': 'property rights. The question: who owns the land or holds rights in it, such as title, the location '
                'or width of an easement or right-of-way, or a deed covenant or restriction, including when the court '
                'declines to decide it for lack of jurisdiction over private rights? It reads like: "Neighbors claim '
                'the driveway crosses their deeded right-of-way"; "the deed restricts the parcel to one dwelling"',
    'claims': 'constitutional and equitable claims. The question: does a constitutional or equitable claim against the '
              'municipality succeed, such as void for vagueness, a taking or exaction, due process, equal protection, '
              'discrimination under federal or state fair housing statutes, or estoppel? It reads like: "the bylaw\'s '
              '\'character of the area\' standard is unconstitutionally vague"; "the Town is estopped by its zoning '
              'administrator\'s assurances"',
    'permits': 'other permits. The question: is another permit needed, or was it obtained, such as Act 250, a state '
               'wastewater or water supply permit, or a state stormwater permit? It reads like: "the project cannot '
               'proceed without an Act 250 permit"; "Applicant has not obtained a state wastewater permit"',
}
OTHER_NAMES = {'measurable': 'measurable rules', 'meaning': 'allowed use and defined terms',
               'nonconforming': 'nonconforming uses and structures', 'process': 'municipal process',
               'appeal': 'who can appeal', 'earlier': 'earlier permits and approvals', 'property': 'property rights',
               'claims': 'constitutional and equitable claims', 'permits': 'other permits'}

G3 = ChoiceSet('G3', topics.GROUNDS,
    ask=f'The kind of question: {{item}}. How far did this docket get with a question of this kind? Count it only '
        f'for this docket\'s appeal. {FURTHEST}',
    items=OTHER_KINDS, options=OTHER_LEVELS, null='not at issue',
    why='Every other kind of question the appeal dealt with, so the appeals without a central judgment standard show '
        'what they turned on, and a docket can show several kinds at once.')

G4 = Question('G4', topics.GROUNDS,
    ask='Did a party challenge a condition the municipality attached to the permit, or ask the court to add, change or '
        'remove one, arguing whether it should be imposed or how strict it should be? A dispute over whether a '
        'condition was met, or what it means, does not count, nor do conditions an applicant offers that no party '
        'opposes; opposing the removal or relaxation of an existing condition counts.',
    options={'yes': 'Yes: a party challenged such a condition.', 'no': 'No.'},
    why='Conditions are how a board can approve a project and still burden it; this catches challenges that no '
        'group does.')


# ---- D · The court ---------------------------------------------------------------------

C1 = Question('C1', topics.COURT,
    ask='How did the Environmental Court hear this appeal of the municipal decision?',
    options={'de novo': 'The court heard the matter anew, taking its own evidence and deciding the application itself.',
             'on the record': 'The court reviewed the municipal record and findings (an on-the-record appeal).',
             NOT_STATED: NS},
    why='De novo review gives opponents a second full hearing.')

C2 = Question('C2', topics.COURT,
    ask='Do the documents include a decision of the Environmental Court that leaves nothing pending in this docket?',
    options={'yes': 'A decision ends the docket in this court: a final judgment, dismissal, approved settlement or '
                    'withdrawal. A decision on the merits that decides every issue ends it even if a judgment order is '
                    'still to be submitted. So does a remand to the municipal panel that the court enters as its '
                    'judgment, or says completes its proceedings, even if the town must act again or other matters '
                    'wait on the remand.',
             'no': 'Only interim rulings appear; something is still pending.'},
    why='The first final decision ends the duration.')

C3 = Question('C3', topics.COURT,
    ask='If a decision ended this docket, how did it end?',
    options={'decided on the merits': 'The court decided the appeal on its merits.',
             'dismissed': 'The appeal was dismissed without a decision on the merits.',
             'settled': 'The parties settled.', 'withdrawn': 'The appeal was withdrawn.',
             NOT_STATED: 'No decision ended the docket, or how it ended is not stated.'},
    why='What the court did.')

C4 = Question('C4', topics.COURT,
    ask='If the court decided the appeal on its merits, what did it do with the application?',
    options={'granted': 'Granted or approved it, and the documents don\'t say the court attached or kept conditions.',
             'granted with conditions': 'Granted or approved it, and the documents say the court attached or kept '
                                        'conditions.',
             'granted in part': 'Granted part of it and denied part, including granting one permission and denying '
                                'another.',
             'denied': 'Denied it.',
             'sent back': 'Sent it back (remanded) to the municipality to decide or reconsider something. A remand '
                          'only to issue the approvals the court ordered is "granted".',
             NOT_STATED: 'Not decided on the merits, or not stated.'},
    why='Compared with the town\'s decision, shows whether the appeal changed the outcome.')

C5 = Question('C5', topics.COURT,
    ask='If the appeal was dismissed, on what basis?',
    options={'standing': 'The appellant lacked standing.', 'timeliness': 'The appeal was late.',
             'jurisdiction': 'The court lacked jurisdiction.', 'mootness': 'The appeal was moot.',
             'other': 'Another basis.', NOT_STATED: 'Not dismissed, or no basis stated.'},
    why='How appeals end without a merits decision.')


# ---- F · Cost to housing -----------------------------------------------------------------

D1 = Question('D1', topics.STAY_DESIGN,
    ask='Did the court order construction stopped or stay the permit while the appeal was pending?',
    options={'yes': 'The court stopped construction or stayed the permit.', 'no': 'No such order appears.'},
    why='Whether the appeal paused the project by court order.')

U4 = Question('U4', topics.UNITS,
    ask='Compared with what the municipality approved, did the court\'s result change the number of new dwelling '
        'units the project would add?',
    options={'more': 'More units added than the municipality approved.', 'fewer': 'Fewer units added.',
             'same': 'The same number.', NOT_STATED: NS},
    why='The appeal\'s effect on the town\'s decision.')

U5 = Question('U5', topics.UNITS,
    ask='Compared with what the application proposed, did the court\'s result change the number of new dwelling '
        'units the project would add?',
    options={'more': 'More units added than proposed.', 'fewer': 'Fewer units added.', 'same': 'The same number.',
             NOT_STATED: NS},
    why='The appeal\'s effect on the original proposal.')

D2 = Question('D2', topics.STAY_DESIGN,
    ask='Did the court impose conditions that change the buildings\' size or design?',
    options={'yes': 'The court imposed such conditions.', 'no': 'It did not.'},
    why='Design changes the court imposed, short of denial.')


ALL = [S1, S2, S3, S4, F1, U1, U2, U3, K1, T1, A1, G1, G2, G3, G4, C1, C2, C3, C4, C5,
       D1, U4, U5, D2]
