"""The Pipeline: collects the nodes, infers the edges, checks the graph and describes it.

Edges are never declared. They come from what each node reads (`refs()`),
which is exactly what the executor reads, so the drawing can't drift from the
behavior. `describe()` is the complete specification: prompts, options,
conditions, thresholds and derive source code. Its hash identifies the pipeline.
"""
from collections import defaultdict, deque
import hashlib
import json

from appeals.graph.nodes import LAYER_GUIDE, LAYERS, Base, ChoiceSet, Derive, Gate, Question, Scan, Step, YesNoSet
from appeals.graph.values import ListOf

class GraphError(Exception):
    pass


class Pipeline:
    def __init__(self, name, scan, gates, base, steps, fields, derives, proceed, thresholds, in_scope=None,
                 conventions=(), description='', topics=None, method=(), reliability=()):
        self.name = name
        self.description = description         # what the data is, in a sentence or two, for readers of it
        self.conventions = list(conventions)   # rules every answer follows, for readers of the data
        self.method = list(method)             # how the data was made, for readers of it
        self.reliability = list(reliability)   # how far to trust it, for readers of it
        self.scan = scan
        self.gates = gates
        self.base = base
        self.steps = steps            # in execution order
        self.topics = dict(topics or {})      # topic ID → title, in reading order
        self.fields = fields
        self.derives = derives
        self.proceed = proceed        # expression: does a docket go on to the reasoning steps?
        self.in_scope = in_scope      # derive ID that is True for dockets in scope; the row blanks the rest
        self.thresholds = dict(thresholds)
        self.nodes = {}
        for node in [scan, *scan.questions, *gates, base, *steps, *fields, *derives]:
            if node.id in self.nodes:
                raise GraphError(f'duplicate node ID {node.id}')
            self.nodes[node.id] = node
        for step in steps:
            step.confirms = self._confirms(step)
        self.edges = self._edges()
        problems = self.check()
        if problems:
            raise GraphError('the graph does not build:\n  ' + '\n  '.join(problems))

    def _confirms(self, step):
        """The scan questions a step checks: those its prompt states as claims or its condition reads."""
        refs = step.placeholders() | (step.only_if.refs() if step.only_if else set()) \
            | (step.choose.refs() if step.choose else set())
        stems = {self._node_for(r) for r in refs}
        return sorted(s for s in stems if isinstance(self.nodes.get(s), (Question, YesNoSet, ChoiceSet)))

    # ---- edges -----------------------------------------------------------------

    def _node_for(self, ref):
        """A reference to a set item ("G2.traffic") is an edge from the set ("G2")."""
        if ref in self.nodes:
            return ref
        stem = ref.split('.')[0]
        return stem if stem in self.nodes else None

    def _edges(self):
        edges, seen = [], set()
        for node in self.nodes.values():
            for ref in sorted(node.refs()):
                source = self._node_for(ref)
                if source is None or source == node.id:
                    continue
                kind = self._edge_kind(self.nodes[source], node)
                if (source, node.id) not in seen:
                    seen.add((source, node.id))
                    edges.append({'from': source, 'to': node.id, 'kind': kind})
        for question in self.scan.questions:
            edges.append({'from': question.id, 'to': 'scan', 'kind': 'asked'})
        return edges

    @staticmethod
    def _edge_kind(source, target):
        if isinstance(source, Step) and isinstance(target, Step):
            return 'chain' if source is target.after else 'condition'
        if isinstance(target, (Gate, Step)) and isinstance(source, (Question, YesNoSet, ChoiceSet, Gate)):
            return 'condition'
        if isinstance(source, Base):
            return 'base'
        return 'data'

    # ---- checks ----------------------------------------------------------------

    def check(self):
        problems = []
        for node in self.nodes.values():
            for ref in node.refs():
                if self._node_for(ref) is None:
                    problems.append(f'{node.id} refers to unknown {ref}')
        layer = {nid: n.layer for nid, n in self.nodes.items()}
        for e in self.edges:
            a, b = layer[e['from']], layer[e['to']]
            same_layer_ok = (e['kind'] in ('chain', 'asked', 'base') or isinstance(self.nodes[e['to']], Derive)
                             or isinstance(self.nodes[e['from']], Step) and isinstance(self.nodes[e['to']], Step))
            if a > b or (a == b and not same_layer_ok):
                problems.append(f'{e["from"]} ({LAYERS[a]}) feeds {e["to"]} ({LAYERS[b]}): data must flow down the layers')
        try:
            self.order()
        except GraphError as error:
            problems.append(str(error))
        reaches = self._reaches_output()
        for node in self.nodes.values():
            if isinstance(node, (Question, YesNoSet, ChoiceSet, Step)) and node.id not in reaches:
                problems.append(f'{node.id} feeds no fact or derived value')
        for node in self.nodes.values():
            if not isinstance(node, (Scan, Base)) and node.topic not in self.topics:
                problems.append(f'{node.id} names no known topic ({node.topic!r})')
        position = {s.id: i for i, s in enumerate(self.steps)}
        for step in self.steps:
            for ref in step.refs():
                if ref in position and position[ref] >= position[step.id]:
                    problems.append(f'{step.id} reads {ref}, which runs after it')
        for step in self.steps:
            if step.after is not None and step.after.for_each:
                problems.append(f'{step.id} follows {step.after.id}, a for-each step, which no step may follow')
            if step.for_each:
                source, path = step.for_each
                try:
                    listed = source.returns.at(path)
                except KeyError:
                    listed = None
                if not isinstance(listed, ListOf):
                    problems.append(f'{step.id} runs for each {source.id}.{path}, which is not a list')
                if '{item}' not in ''.join(step.templates().values()):
                    problems.append(f'{step.id} runs for each item but its prompt has no {{item}}')
        for f in self.fields:
            for_each = any(s.for_each for s in f.item_steps().values())
            if for_each != bool(f.per_item):
                problems.append(f'{f.id}: a field reads a for-each step exactly when it has per_item')
            for key, step in f.item_steps().items():
                for path, holder in ((f.path, step), (f.vouched_by, f.vouchers.get(key, step))):
                    if not path:
                        continue
                    try:
                        holder.returns.at(path)
                    except KeyError:
                        problems.append(f'{f.id} reads {holder.id}.{path}, which the step does not return')
        settled = {}
        for step in self.steps:
            if step.set_item is None:
                continue
            source, key = step.set_item
            if not isinstance(source, (YesNoSet, ChoiceSet)) or key not in source.items:
                problems.append(f'{step.id} settles {getattr(source, "id", source)}.{key}, which is not an item of a scan set')
            elif (source.id, key) in settled:
                problems.append(f'{step.id} and {settled[source.id, key]} both settle {source.id}.{key}')
            else:
                settled[source.id, key] = step.id
            if step.after is not None:
                problems.append(f'{step.id} settles a set item but follows {step.after.id}: a family\'s steps start '
                                'their own conversations')
        if self.in_scope is not None and self.in_scope not in {d.id for d in self.derives}:
            problems.append(f'in_scope names {self.in_scope}, which is not a derived value')
        for name in self._thresholds_used():
            if name not in self.thresholds:
                problems.append(f'threshold {name} is used but not set in config.toml')
        return problems

    def _reaches_output(self):
        """Every node from which a fact or a derived value can be reached: the pipeline's output."""
        forward = defaultdict(set)
        for e in self.edges:
            if e['kind'] != 'asked':
                forward[e['from']].add(e['to'])
        reached, queue = set(), deque(n.id for n in [*self.fields, *self.derives])
        backward = defaultdict(set)
        for a, targets in forward.items():
            for b in targets:
                backward[b].add(a)
        while queue:
            nid = queue.popleft()
            if nid in reached:
                continue
            reached.add(nid)
            queue.extend(backward[nid])
        return reached

    def _thresholds_used(self):
        names = set()

        def walk(expr):
            if expr is None:
                return
            if type(expr).__name__ == 'Threshold':
                names.add(expr.name)
            for value in vars(expr).values():
                for item in value if isinstance(value, (list, tuple)) else [value]:
                    if hasattr(item, 'evaluate'):
                        walk(item)

        for gate in self.gates:
            walk(gate.when)
        for step in self.steps:
            walk(step.only_if)
            walk(step.choose)
        for f in self.fields:
            walk(f.not_stated_if)
        walk(self.proceed)
        if self.steps:
            names |= {'check', 'sure'}                # steps word the scan's claims by them
        return names

    def order(self):
        """Node IDs in an order where every node comes after what it reads."""
        indegree = {nid: 0 for nid in self.nodes}
        forward = defaultdict(list)
        for e in self.edges:
            if e['kind'] == 'asked':
                continue
            forward[e['from']].append(e['to'])
            indegree[e['to']] += 1
        queue = deque(sorted((n for n, d in indegree.items() if d == 0), key=lambda n: self.nodes[n].layer))
        out = []
        while queue:
            nid = queue.popleft()
            out.append(nid)
            for target in forward[nid]:
                indegree[target] -= 1
                if indegree[target] == 0:
                    queue.append(target)
        if len(out) != len(self.nodes):
            raise GraphError('the graph has a cycle among: ' + ', '.join(n for n in self.nodes if n not in out))
        return out

    # ---- description -----------------------------------------------------------

    def describe(self):
        body = {
            'name': self.name,
            'description': self.description,
            'layers': LAYERS[1:],
            'layer_guide': LAYER_GUIDE,
            'thresholds': self.thresholds,
            'proceed': self.proceed.text(),
            'in_scope': self.in_scope,
            'conventions': self.conventions,
            'method': self.method,
            'reliability': self.reliability,
            'step_order': [s.id for s in self.steps],
            'topics': [{'id': t, 'title': title} for t, title in self.topics.items()],
            'nodes': [n.describe() for n in self.nodes.values()],
            'edges': self.edges,
        }
        return {'hash': _hash(body), **body}

    def hash(self):
        return self.describe()['hash']

    def summary(self):
        kinds = defaultdict(int)
        for n in self.nodes.values():
            kinds[n.kind] += 1
        questions = len(self.scan.flat())
        return (f'{self.name}: {questions} decision-model questions in one scan, {len(self.gates)} gates, '
                f'{len(self.steps)} reasoning steps, {len(self.fields)} fields, {len(self.derives)} derived, '
                f'{len(self.edges)} edges; every question and step feeds a fact or derived value.')


def _hash(body):
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()[:16]
