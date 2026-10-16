"""Layer 5: derived values, plain functions of settled fields.

Each function receives {input id: answer} and returns an answer. Their
source is what the dashboard shows, so keep them short and literal.
"""
import calendar
from datetime import date

from appeals.codebook import fields as F
from appeals.graph.nodes import Derive
from appeals.graph.values import NOT_STATED, Count, DateValue, OneOf, Record, Text, YesNo


def in_scope(v):
    return (v['municipal_body'] == 'yes'
            and v['action_kind'] == 'application for permission'
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
    parts = [int(p) for p in value.split('-')]
    year, month, day = parts + [None] * (3 - len(parts))
    if day:
        return date(year, month, day), date(year, month, day), True
    if month:
        return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1]), False
    return date(year, 1, 1), date(year, 12, 31), False


def duration(v):
    """Days from filing to the end of the case, exact or at least.

    Every start is the latest day the appeal could have been filed. A filing date stated to the
    day is a closed start. A month or year, the earliest dated event and the docket number's
    month or year only bound the filing from above, so they are open starts, and the earliest
    of them is used. The end is the first day the first final decision could fall on: closed
    when stated to the day. Without a final decision, the latest order is an open end, since
    the case went on. Any open end makes the duration "at least"; a start on or after the end
    leaves it unknown.
    """
    starts = []
    for name in ('filing_date', 'earliest_event', 'docket_filing'):
        known = date_range(v[name])
        if known:
            first, last, one_day = known
            starts.append({'date': last.isoformat(), 'bound': 'closed' if name == 'filing_date' and one_day else 'open',
                           'from': name})
    closed = [s for s in starts if s['bound'] == 'closed']
    start = closed[0] if closed else min(starts, key=lambda s: s['date'], default=None)
    end = None
    for name in ('final_decision_date', 'latest_order_date'):
        known = date_range(v[name])
        if known:
            first, last, one_day = known
            end = {'date': first.isoformat(),
                   'bound': 'closed' if name == 'final_decision_date' and one_day else 'open', 'from': name}
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
        role = 'neighbor' if a.get('role') in ('individual neighbor', 'group of neighbors') else a.get('role')
        roles[role] = roles.get(role, 0) + 1
    for a in lawyers:
        representation[a.get('representation')] = representation.get(a.get('representation'), 0) + 1
    return {'count': count, 'roles': roles, 'representation': representation}


X1 = Derive('X1', 'scope', code='X1', label='In scope', type=YesNo(),
            inputs=[F.municipal_body, F.action_kind, F.physical_change, F.housing_use, F.units_effect], fn=in_scope)
X2 = Derive('X2', 'D', code='X2', label='Court ended somewhere different from the town', type=YesNo(not_stated=True),
            inputs=[F.town_decision, F.how_ended, F.court_result, F.units_vs_town], fn=court_changed_outcome)
X3 = Derive('X3', 'F', code='X3', label='Change in units added',
            type=Record(vs_town=Count(), vs_application=Count(), direction_vs_town=Text(), direction_vs_application=Text()),
            inputs=[F.units_added_court_approved, F.units_added_town_approved, F.units_added_proposed,
                    F.units_added_under_appeal, F.units_vs_town, F.units_vs_application], fn=unit_change)
DATE_BOUND = Record(date=DateValue(), bound=OneOf({'closed': 'Exact.', 'open': 'A bound only.'}), **{'from': Text()})
X4 = Derive('X4', 'E', code='X4', label='Duration in days',
            type=Record(kind=OneOf({'exact': '', 'at least': '', 'unknown': ''}, not_stated=False), days=Count(),
                        start=DATE_BOUND, end=DATE_BOUND),
            inputs=[F.filing_date, F.earliest_event, F.docket_filing, F.final_decision_date, F.latest_order_date],
            fn=duration)
X5 = Derive('X5', 'F', code='X5', label='Last observed permission',
            type=OneOf({'allowed': '', 'allowed with conditions': '', 'allowed in part': '', 'denied': ''}),
            inputs=[F.court_result, F.town_decision], fn=last_permission)
X6 = Derive('X6', 'B', code='X6', label='Appellant mix', type=Record(count=Count(), roles=Text(), representation=Text()),
            inputs=[F.appellants_named, F.appellants, F.appellant_lawyers], fn=appellant_mix)

ALL = [X1, X2, X3, X4, X5, X6]
