"""Layer 1: the closed questions, all asked in one scan by the decision model.

Each question is self-contained: the decision model sees only its text and
options, never its ID. IDs and answer sets follow docs/PIPELINE.md.
"""

from appeals.graph.nodes import ChoiceSet, Question, YesNoSet

NOT_STATED = 'not stated'
NS = 'The documents do not establish it.'

# ---- Scope ---------------------------------------------------------------------------

S1 = Question('S1', 'scope',
    ask='What kind of proceeding is this docket? Answer for the decision appealed in this docket.',
    options={'municipal permit application': 'An appeal of a decision by a municipal body or officer (such as a '
                 'development review board, planning commission, zoning board of adjustment or zoning '
                 'administrator) on an application for a permit or approval, such as a zoning permit, '
                 'subdivision, site plan or conditional use approval.',
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

S2 = Question('S2', 'scope',
    ask='Physically, what would the permission at issue allow?',
    options={'build a new structure': 'Constructing a new building or structure.',
             'place a structure': 'Placing a structure, such as a mobile home.',
             'convert or renovate an existing building': 'Converting or substantially renovating an existing building.',
             'create building lots': 'Subdividing land into building lots.',
             'authorize something already built': 'Approving, after the fact, something already built or done.',
             'no physical change': 'A change of use, occupancy or operations without construction.',
             NOT_STATED: NS},
    why='Scope comes from what would be built, placed, converted or subdivided.')

S3 = Question('S3', 'scope',
    ask='Will the structure, building or lots at issue be used for housing (dwelling units where people live)?',
    options={'yes': 'The documents say the structure or lots are for housing.',
             'no': 'The use is not housing, such as commercial, industrial or accessory use.',
             NOT_STATED: NS},
    why='New housing must be explicit in the documents.')

S4 = Question('S4', 'scope',
    ask='Does the project add dwelling units, replace existing dwelling units one for one, or neither?',
    options={'adds': 'It adds one or more dwelling units.',
             'replaces': 'It replaces existing dwelling units, such as rebuilding a house or replacing a mobile home.',
             'neither': 'It neither adds nor replaces dwelling units.',
             NOT_STATED: NS},
    why='An addition that creates no unit is not new housing; a replacement is.')


# ---- A · Which decisions -------------------------------------------------------------

A1 = Question('A1', 'A',
    ask='Does any document state the date this appeal was filed with the court (the notice of appeal)?',
    options={'yes': 'A document states when the appeal was filed.', 'no': 'No document states the filing date.'},
    why='The filing date starts the duration. When it is not stated, the earliest dated event is used instead.')

A4 = Question('A4', 'A',
    ask='Do the documents state how many new dwelling units the project would add? Existing units that would remain '
        'are not part of that number.',
    options={'yes': 'The number of dwelling units the project would add is stated, or can be read directly from '
                    'what the documents say is proposed.',
             'no': 'The documents do not say how many units the project would add.'},
    why='Units added are the measure of new housing. Decides whether the counts steps run.')

A5 = Question('A5', 'A',
    ask='Is the appeal limited to part of the proposal, such as some areas, phases or units?',
    options={'yes': 'Only part of the proposal is under appeal.', 'no': 'The whole proposal is under appeal.',
             NOT_STATED: NS},
    why='The units at stake may be fewer than the units proposed.')

A6 = Question('A6', 'A',
    ask='Do the documents state how many new building lots for housing the application would create?',
    options={'yes': 'A number of new housing lots is stated.', 'no': 'No number of new housing lots is stated.'},
    why='Subdivisions create housing capacity before any house is proposed.')

A7 = YesNoSet('A7', 'A',
    ask='Is this kind of municipal permission at issue in this appeal?',
    items={'subdivision': 'subdivision approval', 'site plan': 'site plan approval',
           'planned development': 'planned unit development or master plan approval',
           'conditional use': 'conditional use approval', 'variance': 'a variance (the statutory variance; a waiver is "other")',
           'zoning permit': 'a zoning or building permit', 'other': 'another kind of permission'},
    why='What kind of approval was appealed.')


# ---- B · Who appeals -------------------------------------------------------------------

B1 = Question('B1', 'B',
    ask='What did the municipal decision appealed to this court decide on the application? When several municipal '
        'bodies decided in turn, this is the last decision, the one appealed to the court.',
    options={'approved': 'Approved the application as proposed, without conditions. A deemed approval, where the '
                         'municipality failed to decide in time, counts as approved.',
             'approved with conditions': 'Approved the application with conditions attached.',
             'approved in part': 'Approved part of the application and denied part, including a decision that granted '
                                 'one permission and denied another.',
             'denied': 'Denied the application in full.',
             NOT_STATED: NS},
    why='What the appeal is against. The outcomes are exclusive, so one question asks for one of them.')

B2 = Question('B2', 'B',
    ask='Are all of the appellants in this docket named, rather than only "X, et al." or a similar unnamed group?',
    options={'yes': 'Every appellant is named.', 'no': 'Some appellants are not named.'},
    why='Whether the list of appellants can be complete.')


# ---- C · Grounds ----------------------------------------------------------------------
# The definitions here were settled by the grounds experiments (scored against a 46-docket answer key).

C1 = Question('C1', 'C',
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

C2 = ChoiceSet('C2', 'C',
    ask=f'How far did this docket get with a standard about {{item}}? {JUDGMENT} {FURTHEST}',
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

OTHER_KINDS = {
    'measurable': 'whether the project meets a rule with a measurable test, such as a setback, height limit, minimum '
                  'lot size or frontage, density limit or required number of parking spaces. If only the measuring '
                  'method is disputed, the method is allowed use and defined terms and compliance here is "decided, '
                  'disputed", even if the figures under the adopted method are agreed. Not: a variance or waiver from '
                  'such a rule, what the rule\'s words mean, or a number set by an earlier permit\'s condition (earlier permits '
                  'and approvals)',
    'meaning': 'what the words of the bylaw or a permit mean: whether the proposed use is allowed in the zoning district '
               'or which use category it falls in (permitted, conditional or prohibited), what a defined term such as '
               '"dwelling unit", "structure" or "lot" covers, how a measurable rule is to be measured when the parties '
               'dispute the method (such as whether lot width is taken at its narrowest point), or whether the bylaw '
               'must be read to include 24 V.S.A. § 4412\'s required provisions (such as for accessory dwelling '
               'units), under any version of the bylaw a party relies on. A disputed reading of an earlier permit\'s '
               'condition counts here, and whether it binds or is met under earlier permits and approvals. Count it '
               'only where a party argued about what the words mean, not where their meaning is clear and only '
               'whether the project meets them is disputed; a court only stating or applying a definition is "not at '
               'issue", so "decided, not disputed" never applies here. Not: whether the project meets a measurable '
               'rule (measurable rules), or meets a standard calling for judgment (the judgment groups)',
    'nonconforming': 'a nonconforming use, structure or lot: whether it may continue, expand or change',
    'process': 'the municipal process: notice of the application, hearing or decision, how the hearing was held, '
               'whether the application was complete, or a defect in the municipal decision itself, such as '
               'inadequate findings, a late decision or a deemed approval. Not: the court\'s own handling of the '
               'appeal or of its Statement of Questions, or a remand for the panel to look first (who can appeal)',
    'appeal': 'whether the appeal can be heard: an appellant\'s standing or party status, whether the appeal was filed '
              'on time, or the court\'s jurisdiction, such as whether the decision appealed was final, or whether it '
              'can review an application changed on appeal or a question the municipal panel never considered',
    'earlier': 'earlier permits and approvals: vested rights, the binding effect of an earlier permit or decision that '
               'was not appealed, whether a plat label or permit condition is specific enough to be enforced, a repeat '
               'application or a permit amendment, or compliance with an earlier permit or its conditions. Not: the '
               'finality of the decision under appeal because the appeal was late (who can appeal)',
    'property': 'a private property dispute: who owns the land or holds rights in it, such as title, the location or '
                'width of an easement or right-of-way, or a deed covenant or restriction. This includes a property '
                'question the court declines to decide because it lacks jurisdiction over private property rights. '
                'Not: whether the bylaw allows the project or its use (allowed use and defined terms), or whether the '
                'project meets a zoning rule',
    'claims': 'a constitutional or equitable claim against the municipality: a bylaw standard too vague to enforce '
              'constitutionally (void for vagueness), a taking or exaction, due process or equal protection, a claim of '
              'discrimination under federal or state fair housing statutes, or estoppel. Not: whether a permit '
              'condition or plat label is specific enough to bind (earlier permits and approvals)',
    'permits': 'whether another permit is needed or was obtained, such as Act 250, a state wastewater or water supply '
               'permit, or a state stormwater permit',
}
OTHER_NAMES = {'measurable': 'measurable rules', 'meaning': 'allowed use and defined terms',
               'nonconforming': 'nonconforming uses and structures', 'process': 'municipal process',
               'appeal': 'who can appeal', 'earlier': 'earlier permits and approvals', 'property': 'property rights',
               'claims': 'constitutional and equitable claims', 'permits': 'other permits'}

C3 = ChoiceSet('C3', 'C',
    ask=f'How far did this docket get with a question about {{item}}? Count it only for this docket\'s appeal. '
        f'{FURTHEST}',
    items=OTHER_KINDS, options=OTHER_LEVELS, null='not at issue',
    why='Every other kind of question the appeal dealt with, so the appeals without a central judgment standard show '
        'what they turned on, and a docket can show several kinds at once.')

C4 = Question('C4', 'C',
    ask='Did a party challenge a condition the municipality attached to the permit, or ask the court to add, change or '
        'remove one, arguing whether it should be imposed or how strict it should be? A dispute over whether a '
        'condition was met, or what it means, does not count, nor do conditions an applicant offers that no party '
        'opposes; opposing the removal or relaxation of an existing condition counts.',
    options={'yes': 'Yes: a party challenged such a condition.', 'no': 'No.'},
    why='Conditions are how a board can approve a project and still burden it; this catches challenges that no '
        'group does.')


# ---- D · The court ---------------------------------------------------------------------

D1 = Question('D1', 'D',
    ask='How did the Environmental Court hear this appeal of the municipal decision?',
    options={'de novo': 'The court heard the matter anew, taking its own evidence and deciding the application itself.',
             'on the record': 'The court reviewed the municipal record and findings (an on-the-record appeal).',
             NOT_STATED: NS},
    why='De novo review gives opponents a second full hearing.')

D2 = Question('D2', 'D',
    ask='Do the documents include a decision of the Environmental Court that leaves nothing pending in this docket?',
    options={'yes': 'A decision ends the docket in this court: a final judgment, dismissal, approved settlement or '
                    'withdrawal.',
             'no': 'Only interim rulings appear; something is still pending.'},
    why='The first final decision ends the duration.')

D3 = Question('D3', 'D',
    ask='If a decision ended this docket, how did it end?',
    options={'decided on the merits': 'The court decided the appeal on its merits.',
             'dismissed': 'The appeal was dismissed without a decision on the merits.',
             'settled': 'The parties settled.', 'withdrawn': 'The appeal was withdrawn.',
             NOT_STATED: 'No decision ended the docket, or how it ended is not stated.'},
    why='What the court did.')

D4 = Question('D4', 'D',
    ask='If the court decided the appeal on its merits, what did it do with the application?',
    options={'granted': 'Granted or approved it.', 'granted with conditions': 'Granted or approved it with conditions.',
             'denied': 'Denied it.', 'sent back': 'Sent it back (remanded) to the municipality.',
             NOT_STATED: 'Not decided on the merits, or not stated.'},
    why='Compared with the town\'s decision, shows whether the appeal changed the outcome.')

D5 = Question('D5', 'D',
    ask='If the appeal was dismissed, on what basis?',
    options={'standing': 'The appellant lacked standing.', 'timeliness': 'The appeal was late.',
             'jurisdiction': 'The court lacked jurisdiction.', 'mootness': 'The appeal was moot.',
             'other': 'Another basis.', NOT_STATED: 'Not dismissed, or no basis stated.'},
    why='How appeals end without a merits decision.')


# ---- F · Cost to housing -----------------------------------------------------------------

F1 = Question('F1', 'F',
    ask='Did the court order construction stopped or stay the permit while the appeal was pending?',
    options={'yes': 'The court stopped construction or stayed the permit.', 'no': 'No such order appears.'},
    why='Whether the appeal paused the project by court order.')

F2 = Question('F2', 'F',
    ask='Compared with what the municipality approved, did the court\'s result change the number of new dwelling '
        'units the project would add?',
    options={'more': 'More units added than the municipality approved.', 'fewer': 'Fewer units added.',
             'same': 'The same number.', NOT_STATED: NS},
    why='The appeal\'s effect on the town\'s decision.')

F3 = Question('F3', 'F',
    ask='Compared with what the application proposed, did the court\'s result change the number of new dwelling '
        'units the project would add?',
    options={'more': 'More units added than proposed.', 'fewer': 'Fewer units added.', 'same': 'The same number.',
             NOT_STATED: NS},
    why='The appeal\'s effect on the original proposal.')

F5 = Question('F5', 'F',
    ask='Did the court impose conditions that change the buildings\' size or design?',
    options={'yes': 'The court imposed such conditions.', 'no': 'It did not.'},
    why='Design changes the court imposed, short of denial.')


ALL = [S1, S2, S3, S4, A1, A4, A5, A6, A7, B1, B2, C1, C2, C3, C4, D1, D2, D3, D4, D5,
       F1, F2, F3, F5]
