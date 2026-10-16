"""The codebook: docs/PIPELINE.md as code.

Files follow the layers, top to bottom, and each imports only from the files
above it: questions → gates → steps → fields → derived → answers.
"""
from appeals.codebook import answers, derived, fields, gates, questions, steps
from appeals.graph.nodes import Scan
from appeals.graph.pipeline import Pipeline


def build(thresholds):
    """The extraction graph, checked. Raises GraphError when it does not build."""
    return Pipeline(
        name='housing-appeals',
        scan=Scan('scan', 'scope', questions=questions.ALL),
        gates=gates.ALL,
        base=steps.base,
        steps=steps.ORDER,
        fields=fields.ALL,
        derives=derived.ALL,
        answers=answers.ALL,
        proceed=gates.PROCEED,
        thresholds=thresholds,
        in_scope=derived.X1.id,
    )
