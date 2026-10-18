"""Layer 2: gates. Each is a condition over the scan's probabilities.

Threshold values live in config.toml under [thresholds].
"""
from appeals.codebook import topics
from appeals.codebook.questions import U1, U2, U3, G1, C1, C2, D1, U4, U5, D2, S1, S2, S3, S4
from appeals.graph.expr import Max, T
from appeals.graph.nodes import Gate

# Probability that the docket is a municipal appeal about new housing, from S1–S4.
IN_SCOPE = ((S1.p('municipal permit application') + S1.p('several, including a municipal permit application'))
            * (S3.p('yes') + S3.p('group or care housing'))
            * (1 - S2.p('authorize something already built') - S2.p('no physical change'))
            * Max(S4.p('adds') + S4.p('replaces'), S2.p('create building lots')))

scope = Gate('scope', topics.SCOPE, title='Possibly in scope',
    when=IN_SCOPE > T.scope,
    why='Possibly a municipal appeal about new housing: go on to the reasoning steps, where L1 checks scope with '
        'quotes before anything else runs. Low on purpose: the scan misses real cases, and L1 stops the rest.')

counts = Gate('counts', topics.UNITS, title='Any count in play',
    when=(U1.p('yes') >= T.counts) | (U2.p('yes') >= T.counts) | (U3.p('yes') >= T.counts)
         | (1 - U4.p('same') - U4.p('not stated') >= T.counts) | (1 - U5.p('same') - U5.p('not stated') >= T.counts),
    why='Some count is stated, or the court likely changed the number of units.')

grounds = Gate('grounds', topics.GROUNDS, title='Arguments may be stated',
    when=G1.p('yes') >= T.grounds,
    why='The documents may say what the appellant argued: confirm it, then follow up each kind of judgment standard '
        'the scan flags. Low on purpose, so a docket with arguments is rarely skipped.')

review = Gate('review', topics.COURT, title='Review standard stated',
    when=1 - C1.p('not stated') >= T.review,
    why='Quote how the court heard the appeal.')

final = Gate('final', topics.COURT, title='Final decision',
    when=C2.p('yes') >= T.final,
    why='A decision likely ended the docket: identify it, then date it.')

stay = Gate('stay', topics.STAY_DESIGN, title='Stay likely',
    when=D1.p('yes') >= T.stay,
    why='Confirm the stay and its dates.')

design = Gate('design', topics.STAY_DESIGN, title='Design change likely',
    when=D2.p('yes') >= T.design,
    why='Confirm and describe the court-imposed change.')

ALL = [scope, counts, grounds, review, final, stay, design]

# Whether a docket goes on to the reasoning steps at all.
PROCEED = scope.passed()
