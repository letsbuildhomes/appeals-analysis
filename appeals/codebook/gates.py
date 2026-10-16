"""Layer 2: gates. Each is a condition over the scan's probabilities.

Threshold values live in config.toml under [thresholds].
"""
from appeals.codebook.questions import A4, A5, A6, C1, C2, C3, D1, D2, F1, F2, F3, F5, S1, S2, S3, S4, S5
from appeals.graph.expr import Max, T
from appeals.graph.nodes import Gate

# Probability that the docket is a municipal appeal about new housing, from S1–S5.
IN_SCOPE = (S1.p('yes') * S2.p('application for permission') * S4.p('yes')
            * (1 - S3.p('authorize something already built') - S3.p('no physical change'))
            * Max(S5.p('adds') + S5.p('replaces'), S3.p('create building lots')))

scope = Gate('scope', 'scope', title='In scope',
    when=IN_SCOPE >= T.scope_high,
    why='Confidently a municipal appeal about new housing: go on to the reasoning steps.')

scope_check = Gate('scope_check', 'scope', title='Scope unclear',
    when=(IN_SCOPE > T.scope_low) & (IN_SCOPE < T.scope_high),
    why='Between the thresholds: L1 checks scope with quotes before anything else runs.')

counts = Gate('counts', 'A', title='Any count in play',
    when=(A4.p('yes') >= T.counts) | (A5.p('yes') >= T.counts) | (A6.p('yes') >= T.counts)
         | (1 - F2.p('same') - F2.p('not stated') >= T.counts) | (1 - F3.p('same') - F3.p('not stated') >= T.counts),
    why='Some count is stated, or the court likely changed the number of units.')

discretion = Gate('discretion', 'C', title='Discretion claimed',
    when=C1.is_('yes') & ((C2.p('yes') >= T.discretion) | (C3.p('yes') >= T.discretion)),
    why='The appeal likely turns on a judgment-based standard: ask for evidence or refutation.')

review = Gate('review', 'D', title='Review standard stated',
    when=1 - D1.p('not stated') >= T.review,
    why='Quote how the court heard the appeal.')

final = Gate('final', 'D', title='Final decision',
    when=D2.p('yes') >= T.final,
    why='A decision likely ended the docket: identify it, then date it.')

stay = Gate('stay', 'F', title='Stay likely',
    when=F1.p('yes') >= T.stay,
    why='Confirm the stay and its dates.')

design = Gate('design', 'F', title='Design change likely',
    when=F5.p('yes') >= T.design,
    why='Confirm and describe the court-imposed change.')

ALL = [scope, scope_check, counts, discretion, review, final, stay, design]

# Whether a docket goes on to the reasoning steps at all.
PROCEED = scope.passed() | scope_check.passed()
