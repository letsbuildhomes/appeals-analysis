"""Layer 5: derived values, plain functions of settled fields.

Each function receives {input id: answer} and returns an answer. Their
source is what the dashboard shows, so keep them short and literal.
"""
import calendar
from datetime import date

from appeals.codebook import fields as F
from appeals.codebook import steps as L
from appeals.codebook import topics
from appeals.graph.nodes import Derive
from appeals.graph.values import (NOT_STATED, Boolean, Count, CountsBy, DateValue, Integer, OneOf, OrNotStated,
                                  Record, Text, YesNo)


def in_scope(v):
    return (v['proceeding'] in L.MUNICIPAL_PERMIT
            and v['housing_use'] == 'yes'
            and v['physical_change'] not in ('authorize something already built', 'no physical change')
            and (v['units_effect'] in ('adds', 'replaces') or v['physical_change'] == 'create building lots'))


def court_changed_outcome(v):
    town, ended, result = v['town_decision'], v['how_ended'], v['court_result']
    if ended == 'decided on the merits':
        same = {('approved', 'granted'), ('approved with conditions', 'granted with conditions'), ('denied', 'denied')}
        if (town, result) in same and v['units_vs_town'] in ('same', NOT_STATED):
            return 'no'
        return 'yes' if town != NOT_STATED and result != NOT_STATED else NOT_STATED
    if ended in ('dismissed', 'withdrawn'):
        return 'no'                     # the town's decision stands
    return NOT_STATED


def unit_change(v):
    court = v['units_added_court_approved']
    under_appeal = v['units_added_under_appeal']
    baseline = under_appeal if under_appeal != NOT_STATED else v['units_added_proposed']
    def diff(a, b):
        return a - b if isinstance(a, int) and isinstance(b, int) else NOT_STATED
    return {'vs_town': diff(court, v['units_added_town_approved']), 'vs_application': diff(court, baseline),
            'direction_vs_town': v['units_vs_town'], 'direction_vs_application': v['units_vs_application']}


def date_range(value):
    """The first and last day a YYYY, YYYY-MM or YYYY-MM-DD date could mean, and whether it names one day."""
    if not isinstance(value, str) or value == NOT_STATED:
        return None
    match [int(p) for p in value.split('-')]:
        case [year, month, day]:
            return date(year, month, day), date(year, month, day), True
        case [year, month]:
            return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1]), False
        case [year]:
            return date(year, 1, 1), date(year, 12, 31), False


def duration(v):
    """Days from filing to the end of the case, exact or at least.

    The start, in order of preference:
    1. A filing date stated to the day: closed.
    2. The town's decision, stated to the day: closed, and marked inferred. The appeal can't
       be filed before it, and the permit is in doubt from then on, so it stands in for the
       filing; it lengthens the duration by the days until the appeal was filed. It is not
       used when it falls after the latest day the appeal could have been filed.
    3. Otherwise the latest day the appeal could have been filed: a filing month or year,
       the earliest dated event and the docket number's month or year bound the filing from
       above, so they are open starts, and the earliest of them is used.
    The end is the first day the first final decision could fall on: closed when stated to
    the day. Without a final decision, the latest order is an open end, since the case went
    on. Any open end makes the duration "at least"; a start on or after the end leaves it
    unknown.
    """
    starts = []
    for name in ('filing_date', 'earliest_event', 'docket_filing'):
        known = date_range(v[name])
        if known:
            first, last, one_day = known
            starts.append({'date': last.isoformat(), 'bound': 'closed' if name == 'filing_date' and one_day else 'open',
                           'from': name, 'inferred': False})
    closed = [s for s in starts if s['bound'] == 'closed']
    latest = min((s['date'] for s in starts), default=None)
    town = date_range(v['town_decision_date'])
    if closed:
        start = closed[0]
    elif town and town[2] and (latest is None or town[0].isoformat() <= latest):
        start = {'date': town[0].isoformat(), 'bound': 'closed', 'from': 'town_decision_date', 'inferred': True}
    else:
        start = min(starts, key=lambda s: s['date'], default=None)
    end = None
    for name in ('final_decision_date', 'latest_order_date'):
        known = date_range(v[name])
        if known:
            first, last, one_day = known
            end = {'date': first.isoformat(),
                   'bound': 'closed' if name == 'final_decision_date' and one_day else 'open', 'from': name,
                   'inferred': False}
            break
    if start is None or end is None or end['date'] <= start['date']:
        return {'kind': 'unknown', 'days': NOT_STATED, 'start': start or NOT_STATED, 'end': end or NOT_STATED}
    days = (date.fromisoformat(end['date']) - date.fromisoformat(start['date'])).days
    exact = start['bound'] == 'closed' and end['bound'] == 'closed'
    return {'kind': 'exact' if exact else 'at least', 'days': days, 'start': start, 'end': end}


def last_permission(v):
    result = v['court_result']
    if result in ('granted', 'granted with conditions', 'denied'):
        return {'granted': 'allowed', 'granted with conditions': 'allowed with conditions', 'denied': 'denied'}[result]
    return {'approved': 'allowed', 'approved with conditions': 'allowed with conditions', 'denied': 'denied',
            'approved in part': 'allowed in part'}.get(v['town_decision'], NOT_STATED)


def appellant_mix(v):
    listed = v['appellants'] if isinstance(v['appellants'], list) else []
    lawyers = v['appellant_lawyers'] if isinstance(v['appellant_lawyers'], list) else []
    count = len(listed) if listed and v['appellants_named'] != 'no' else NOT_STATED
    roles, representation = {}, {}
    for a in listed:
        role = 'neighbor' if a.get('role') in NEIGHBORS else a.get('role')
        roles[role] = roles.get(role, 0) + 1
    first = {}
    for entry in lawyers:                              # one entry per lawyer: count each appellant once
        first.setdefault(entry.get('appellant'), entry.get('representation'))
    for kind in first.values():
        representation[kind] = representation.get(kind, 0) + 1
    return {'count': count, 'roles': roles, 'representation': representation, 'representation_of': len(first)}


IN_SCOPE = Derive('in_scope', topics.SCOPE, label='In scope', type=Boolean(),
                  inputs=[F.proceeding, F.physical_change, F.housing_use, F.units_effect], fn=in_scope,
                  notes=["True only for an appeal of a municipal body's decision on an application for permission (alone or with other decisions in the docket), for housing, that adds or replaces dwelling units or creates building lots, and is neither after the fact nor without physical change."])
COURT_CHANGED_OUTCOME = Derive('court_changed_outcome', topics.COURT, label='Court ended somewhere different from the town', type=YesNo(not_stated=True),
                               inputs=[F.town_decision, F.how_ended, F.court_result, F.units_vs_town], fn=court_changed_outcome,
                               notes=['"no" when a dismissal or withdrawal leaves the town\'s decision standing; a settlement leaves it "not stated".'])
UNIT_CHANGE = Derive('unit_change', topics.UNITS, label='Change in units added',
                     type=Record(vs_town=Integer(), vs_application=Integer(), direction_vs_town=F.units_vs_town.type,
                                 direction_vs_application=F.units_vs_application.type),
                     inputs=[F.units_added_court_approved, F.units_added_town_approved, F.units_added_proposed,
                             F.units_added_under_appeal, F.units_vs_town, F.units_vs_application], fn=unit_change,
                     notes=['Measured two ways: against what the town approved (vs_town) and against what the application proposed, or the part under appeal (vs_application). Positive means the court allowed more units.',
                            "The directions come from the scan and stand in when the counts aren't stated."])
DATE_BOUND = Record(date=DateValue(), bound=OneOf({'closed': 'Exact.', 'open': 'A bound only.'}), **{'from': Text()},
                    inferred=Boolean())
DURATION = Derive('duration', topics.COURT, label='Duration in days',
                  type=Record(kind=OneOf({'exact': 'Both ends are exact dates.',
                                          'at least': 'An end is only a bound, so the case lasted at least this many days.',
                                          'unknown': 'An end is missing, or the start is not before the end.'},
                                         not_stated=False),
                              days=Count(),
                              start=OrNotStated(DATE_BOUND), end=OrNotStated(DATE_BOUND)),
                  inputs=[F.filing_date, F.earliest_event, F.docket_filing, F.town_decision_date,
                          F.final_decision_date, F.latest_order_date],
                  fn=duration,
                  notes=['A duration is exact or a lower bound ("at least"). Keep them apart: averaging the two together understates durations.',
                         'A month or year counts as its latest possible day at the start and its earliest possible day at the end. The duration is unknown when an end is missing or the start is not before the end.',
                         'The end is never extended to today.',
                         "Without a filing date stated to the day, the duration starts at the town's decision when that is dated to the day: a closed start marked inferred (start.inferred). It lengthens the duration by the days until the appeal was filed, usually under 30, the appeal period. It is used even when the appeal was dismissed as untimely, since the permit was in doubt from the town's decision; filter on dismissal_basis to leave those out."])
LAST_PERMISSION = Derive('last_permission', topics.COURT, label='Last observed permission',
                         type=OneOf({'allowed': 'The project may go ahead as proposed.',
                                     'allowed with conditions': 'The project may go ahead with conditions.',
                                     'allowed in part': 'Part of the project may go ahead.',
                                     'denied': 'The project may not go ahead.'}),
                         inputs=[F.court_result, F.town_decision], fn=last_permission,
                         notes=["The court's result when it decided on the merits, otherwise the town's decision. It is not whether the appeal succeeded, and not whether anything was built."])
NEIGHBORS = ('individual neighbor', 'group of neighbors')
ROLE_MIX = {'neighbor': 'An individual neighbor or a group of neighbors.',
            **{k: v for k, v in L.ROLE.options.items() if k not in NEIGHBORS}}
APPELLANT_MIX = Derive('appellant_mix', topics.APPELLANTS, label='Appellant mix',
                       type=Record(count=Count(), roles=CountsBy(ROLE_MIX),
                                   representation=CountsBy(L.REPRESENTATION_KIND.options), representation_of=Count()),
                       inputs=[F.appellants_named, F.appellants, F.appellant_lawyers], fn=appellant_mix,
                       notes=['Groups of neighbors fold into "neighbor". The count is "not stated" when the documents don\'t name every appellant.',
                              'Representation is asked for the first 10 appellants only: representation_of says how many appellants the representation counts cover.'])


def judgment_central(v):
    levels = v['judgment_grounds']
    if levels == NOT_STATED:
        return NOT_STATED
    return 'yes' if 'decided, disputed' in levels.values() else 'no'


JUDGMENT_CENTRAL = Derive('judgment_central', topics.GROUNDS, label='A judgment standard was central',
                          type=YesNo(not_stated=True), inputs=[F.judgment_grounds], fn=judgment_central,
                          notes=['Central: a party contested whether the project meets a judgment standard, and the court ruled on '
                                 'it, in an interim or final decision. Any one kind of standard is enough.',
                                 'When the documents don\'t say what the appellant argued, "other questions only" can still be '
                                 'known (an appeal dismissed as untimely, say); otherwise it is "not stated".'])


def judgment_at_issue(v):
    levels = v['judgment_grounds']
    if levels == NOT_STATED:
        return NOT_STATED
    return 'yes' if any(level not in ('not at issue', NOT_STATED) for level in levels.values()) else 'no'


JUDGMENT_AT_ISSUE = Derive('judgment_at_issue', topics.GROUNDS, label='A judgment standard was at issue',
                           type=YesNo(not_stated=True), inputs=[F.judgment_grounds], fn=judgment_at_issue,
                           notes=['At issue: any kind of judgment standard got past "not at issue", including one only raised or set '
                                  'aside. Broader than central (judgment_central).'])


def what_was_central(v):
    judgment, other = v['judgment_grounds'], v['other_questions']
    if judgment != NOT_STATED and 'decided, disputed' in judgment.values():
        return 'a judgment standard'
    if other != NOT_STATED and 'decided, disputed' in other.values():
        return 'other questions only'
    return NOT_STATED if judgment == NOT_STATED else 'nothing'


WHAT_WAS_CENTRAL = Derive('what_was_central', topics.GROUNDS, label='What was central',
                          type=OneOf({'a judgment standard': 'At least one judgment standard was disputed and decided (judgment_central yes); '
                                               'other questions may have been too.',
                                      'other questions only': 'No judgment standard was central, but at least one other question '
                                                '(G3) was disputed and decided.',
                                      'nothing': 'Nothing was disputed and decided, such as an unopposed dismissal or a docket still '
                                   'pending.'}, not_stated=True),
                          inputs=[F.judgment_grounds, F.other_questions], fn=what_was_central,
                          notes=['For "other questions only", which ones were central is in other_questions.',
                                 'When the documents don\'t say what the appellant argued, "other questions only" can still be '
                                 'known (an appeal dismissed as untimely, say); otherwise it is "not stated".'])

ALL = [IN_SCOPE, COURT_CHANGED_OUTCOME, UNIT_CHANGE, DURATION, LAST_PERMISSION, APPELLANT_MIX, JUDGMENT_CENTRAL, JUDGMENT_AT_ISSUE, WHAT_WAS_CENTRAL]
