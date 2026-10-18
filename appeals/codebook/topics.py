"""The topics: what each question, gate, step, fact and derived value is about, in reading order.

Every node in the codebook names one. A topic gathers the conversations about one subject with the scan
questions that open them and the facts they settle, so the dashboard draws one row per topic and the case
page groups a docket's facts by them. Topics only organize reading: they don't change what runs, except that
the scope topic's facts and derived values are reported for every docket, in scope or not.
"""
from appeals.graph.nodes import SCOPE

FILING = 'filing'
TOWN = 'town'
KINDS = 'kinds'
APPELLANTS = 'appellants'
GROUNDS = 'grounds'
COURT = 'court'
UNITS = 'units'
STAY_DESIGN = 'stay_design'

TOPICS = {
    SCOPE: 'Scope',
    FILING: 'Filing dates',
    TOWN: 'The town\'s decision',
    KINDS: 'Kinds of permission',
    APPELLANTS: 'Appellants and their lawyers',
    GROUNDS: 'Arguments and grounds',
    COURT: 'The court\'s decision',
    UNITS: 'Units added',
    STAY_DESIGN: 'Stay and design change',
}
