"""Layer 1: the closed questions, all asked in one scan by the decision model.

Each question is self-contained: the decision model sees only its text and
options, never its ID. IDs and answer sets follow docs/PIPELINE.md.
"""
import re

from appeals.graph.nodes import Question, YesNoSet

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

def town_candidates(docket):
    """Municipalities named in the docket text as "Town of X", "City of X", "Village of X" or "X Development Review Board" (and similar boards)."""
    text = docket.text
    names = re.findall(r'\b(?:Town|City|Village) of ([A-Z][a-z]+(?:[ -][A-Z][a-z]+){0,2})', text)
    names += re.findall(r'\b([A-Z][a-z]+(?: [A-Z][a-z]+){0,2}) (?:Development Review Board|Planning Commission|'
                        r'Zoning Board of Adjustment|Zoning Administrator|Selectboard|City Council)', text)
    skip = {'The', 'In', 'Vermont', 'State', 'Superior', 'Environmental', 'Appeal', 'Appeals'}
    counts = {}
    for name in names:
        name = name.strip()
        if name.split()[0] not in skip:
            counts[name] = counts.get(name, 0) + 1
    ranked = sorted(counts, key=counts.get, reverse=True)[:40]
    options = {name: f'The project is in {name}.' for name in ranked}
    options[NOT_STATED] = NS
    return options


A1 = Question('A1', 'A',
    ask='Does any document state the date this appeal was filed with the court (the notice of appeal)?',
    options={'yes': 'A document states when the appeal was filed.', 'no': 'No document states the filing date.'},
    why='The filing date starts the duration. When it is not stated, the earliest dated event is used instead.')

A3 = Question('A3', 'A',
    ask='In which Vermont municipality is the project at issue located?',
    options_from=town_candidates,
    why='Where appeals happen.')

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
           'conditional use': 'conditional use approval', 'variance': 'a variance',
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

C1 = Question('C1', 'C',
    ask='Do the documents say what the appellant argued in this appeal?',
    options={'yes': 'The appellant\'s arguments are described.',
             'no': 'The documents do not say what the appellant argued, for example a dismissal on procedural grounds.'},
    why='Without stated arguments, the grounds are "not stated".')

C2 = Question('C2', 'C',
    ask='Does any argument in this appeal dispute how a judgment-based standard was applied, such as '
        'compatibility with the neighborhood, the character of the area, or the adequacy of something?',
    options={'yes': 'An argument disputes the application of a judgment-based standard.',
             'no': 'No argument does; the arguments concern fixed rules, facts, procedure or legal rights.'},
    why='Tests whether appeals turn on subjective standards.')

C3 = Question('C3', 'C',
    ask='Does any argument in this appeal challenge whether a judgment-based standard is valid, for example as too '
        'vague to be enforced?',
    options={'yes': 'An argument challenges the validity of such a standard.', 'no': 'No argument does.'},
    why='Challenging a standard itself differs from disputing how it was applied.')

C4 = Question('C4', 'C',
    ask='Did the court treat an argument about a judgment-based standard as a principal issue of the appeal?',
    options={'yes': 'It was a principal issue.', 'no': 'It was minor or absent.', NOT_STATED: NS},
    why='Whether discretion was central, not just present.')

C5 = YesNoSet('C5', 'C',
    ask='Did the appellant raise this issue in this appeal?',
    items={'traffic': 'traffic, access or parking', 'density': 'density or the number of units',
           'character': 'neighborhood character, appearance or aesthetics',
           'natural resources': 'wetlands, stormwater, wildlife or other natural resources',
           'noise or lighting': 'noise, lighting or other nuisance', 'dimensional': 'setbacks, height, lot size or other dimensional rules',
           'procedure': 'notice, hearing or other procedure', 'standing': 'standing or party status',
           'vested rights': 'vested rights or prior approvals', 'other': 'another issue'},
    why='Which issues appeals raise.')


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


ALL = [S1, S2, S3, S4, A1, A3, A4, A5, A6, A7, B1, B2, C1, C2, C3, C4, C5, D1, D2, D3, D4, D5,
       F1, F2, F3, F5]
