"""The rules every answer follows, for anyone reading the data.

Rulings about a single answer live as `notes` on its field, derived value or
answer instead. Both travel with the graph description into every release, so
the published data explains itself.
"""

CONVENTIONS = [
    # The unit of the data
    'One row per docket. A docket is one case number. Facts about another docket, even one decided in the same '
    'document, are not this docket\'s.',
    'A decision the court issued in several dockets belongs in full to each of them, so sibling dockets often '
    'describe the same project. Adding up units or lots across linked dockets counts the same housing more than once.',
    # What the answers mean
    '"Not stated" is a real answer: the documents were silent. It is different from "no", which needs the documents '
    'to say so. Report "not stated" separately; never count it as "no".',
    '"Out of scope" means the docket is not a municipal appeal about new housing, so it was not studied: only its '
    'scope answers are filled in. That is different from "not stated".',
    'Every answer except "not stated" has evidence when a reasoning step produced it: a short exact quotation with '
    'its document and page, checked by code against the page text. Answers taken from the scan have a probability '
    'instead of a quote.',
    'Answers are closed: one option from a fixed set, or a separate yes/no question per item when options can '
    'overlap. Dates, counts and names are the only open values.',
    'Dates are as precise as the documents allow: a day (YYYY-MM-DD), a month (YYYY-MM) or a year (YYYY).',
    'Units are units added: every count of dwelling units is the number of new units the project would create. '
    'Existing units that remain are not counted; a unit that replaces one removed counts as one.',
    'Stays and changes to the housing count only when the court imposed them. Changes the town made belong to the '
    'town\'s decision.',
    'Code combines answers into research answers (the derived values). No model does the combining.',
    # How the pipeline settles an answer
    'Each docket is first read by a decision model that answers every closed question at once with probabilities '
    '(the scan). Dockets likely in scope then go to a reasoning model, one small question at a time, and each reply '
    'must quote the documents. A reasoning answer with a verified quote overrides the scan; otherwise the scan\'s '
    'most likely answer stands.',
    'The scan\'s confidence shapes the prompts: a claim at or above the `sure` threshold is put to the reasoning '
    'model as "fairly confident", below it as "uncertain". An item of a yes/no set at or above `check` gets its own '
    'step; below `check` it is recorded as the scan\'s "no" with no step.',
    'Rules are composable tests, not lists of case types. Examples illustrate a rule but never decide it.',
    # What the source cannot show
    'The court\'s published decisions are the only source. Appeals that left no published decision are invisible.',
    'A missing final decision does not prove a case is still open.',
    'Nothing here shows whether homes were built, or whether an appeal delayed construction.',
    'Supreme Court proceedings are out of scope: a case ends at the Environmental Division\'s first final decision.',
]
