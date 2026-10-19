"""The codebook: docs/PIPELINE.md as code.

Files follow the layers, top to bottom, and each imports only from the files
above it: topics → questions → gates → steps → fields → derived. The fields and derived
values are the output: a general set of facts about each docket, for any question.
"""
from appeals.codebook import derived, fields, gates, questions, steps, topics
from appeals.codebook.conventions import CONVENTIONS, METHOD, RELIABILITY
from appeals.graph.nodes import Scan
from appeals.graph.pipeline import Pipeline


def build(thresholds):
    """The extraction graph, checked. Raises GraphError when it does not build."""
    return Pipeline(
        name='housing-appeals',
        description=('Appeals of Vermont town land-use decisions about new housing, heard by the Vermont '
                     'Superior Court, Environmental Division, as seen through its published decisions: '
                     'one row per appeal, every answer drawn from the decisions themselves.'),
        scan=Scan('scan', None, questions=questions.ALL),
        gates=gates.ALL,
        base=steps.base,
        steps=steps.ORDER,
        topics=topics.TOPICS,
        fields=fields.ALL,
        derives=derived.ALL,
        proceed=gates.PROCEED,
        thresholds=thresholds,
        in_scope=derived.IN_SCOPE.id,
        conventions=CONVENTIONS,
        method=METHOD,
        reliability=RELIABILITY,
    )
