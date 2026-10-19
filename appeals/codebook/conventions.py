"""What readers of the data are told: the rules every answer follows, how the data was made, and how far to
trust it.

All three are written for someone using the data, not for whoever runs the pipeline: they say what an answer
means, never how a particular question, threshold or model produced it (PIPELINE.md covers that). Rulings
about a single answer live as `notes` on its field, derived value or answer instead, in the same plain terms.
Everything here travels with the graph description into every release, so the published data explains itself.
"""

CONVENTIONS = [
    # The unit of the data
    'One row per docket. A docket is one case number. Facts about another docket, even one decided in the same '
    'document, are not this docket\'s.',
    'A decision the court issued in several dockets belongs in full to each of them, so sibling dockets often '
    'describe the same project. Adding up units or lots across linked dockets counts the same housing more than once.',
    # What the answers mean
    '"Not stated" is a real answer: the documents were silent. It is different from "no". Report "not stated" '
    'separately; never count it as "no".',
    'A "no" means the documents say so, or, for whether something happened (such as a stay, a challenged condition, '
    'a design change or a final decision), that the documents show nothing of the kind.',
    'Most answers are one option from a fixed list, or a separate yes or no for each item when several can apply. '
    'Dates, counts, names and short descriptions are the only open values.',
    'Dates are as precise as the documents allow: a day (YYYY-MM-DD), a month (YYYY-MM) or a year (YYYY).',
    'Units are units added: every count of dwelling units is the number of new units the project would create. '
    'Existing units that remain are not counted, nor units an earlier permit already approved that the project '
    'keeps unchanged; a unit that replaces one removed counts as one.',
    'Stays and changes to the housing count only when the court imposed them. Changes the town made belong to the '
    'town\'s decision.',
    # What the source cannot show
    'The court\'s published decisions are the only source. Appeals that left no published decision are invisible.',
    'A missing final decision does not prove a case is still open.',
    'Nothing here shows whether homes were built, or whether an appeal delayed construction.',
    'Supreme Court proceedings are not followed: a case ends at the Environmental Division\'s first final decision.',
]

# How the data was made, in a few sentences: enough to say where an answer comes from, no more.
METHOD = [
    'The source is every decision the Environmental Division has posted on the Vermont courts\' website since '
    '2000, with the text read from each PDF, grouped by docket number.',
    'AI models read every docket. A first read sorted out which dockets are appeals of town decisions about new '
    'housing. For those appeals, a second model answered one small question at a time, and had to point to the '
    'passage of the decision each answer rests on; code checked every passage against the decision\'s text.',
    'Code, not a model, combined the answers into the facts published here, such as durations and changes in units.',
    'Dockets that are not appeals about new housing were set aside after the first read: only whether they are in '
    'scope, and why, is recorded for them.',
]

# How far to trust the data, in a reader's terms: which answers are firm and which less so. Keep it in line with
# the latest scoring (docs/IMPROVING.md, "Where things stand"), but don't cite the answer key itself.
RELIABILITY = [
    'The headline facts are the most reliable: whether a case is in scope, the town\'s decision, who appealed, how '
    'and when the case ended, and the unit counts. The finer points of the arguments, such as how far each kind of '
    'standard or question got and which conditions were challenged, are less certain.',
    'Figures over many appeals are sound. Any single answer can still be wrong, so read a docket\'s passages before '
    'relying on one case.',
]
