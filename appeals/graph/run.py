"""The executor: a pool of workers, each taking one docket through every layer.

For one docket, in order:
    input    the docket text
    scan     one decision-model request (long-context mode for long dockets)
    plan     gates evaluated; the steps to run
    steps    one reasoning thread on the docket's Base; planned steps in order
    facts    one settled value per field
    derive   derived values
    row      the research row

Every layer's output is stored under a key hashed from the node, its inputs
and the endpoint, so an unchanged node is never run twice and an interrupted
run resumes by running again. Workers share each endpoint's rate limiter;
the budget stops new model calls once it is spent.
"""
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import time
import traceback
import uuid

from appeals.graph import layers
from appeals.graph.endpoints import BudgetReached
from appeals.ingest.dockets import docket_text

SYSTEM = ('You read decisions of the Vermont Superior Court, Environmental Division, for a research project. '
          'Answer only from the docket text provided. Quote exactly. When the documents do not establish an '
          'answer, say "not stated".')


def key_of(*parts):
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:32]


class Runner:
    def __init__(self, pipeline, store, settings, decision, reasoning, log=print):
        self.pipeline = pipeline
        self.store = store
        self.settings = settings
        self.decision = decision
        self.reasoning = reasoning
        self.log = log
        self.spent = 0.0
        self.description = pipeline.describe()
        self.nodes = {n['id']: n for n in self.description['nodes']}

    # ---- the run -------------------------------------------------------------------

    async def run(self, numbers, workers=8, tags=()):
        run_id = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:4]
        graph_hash = self.description['hash']
        self.store.save_graph(graph_hash, self.description)
        endpoints = {'decision': self.decision.identity(), 'reasoning': self.reasoning.identity()}
        self.store.start_run(run_id, graph_hash, endpoints,
                             {'workers': workers, 'budget_usd': self.settings.budget_usd}, len(numbers),
                             datetime.now(timezone.utc), tags)
        queue = asyncio.Queue()
        for n in numbers:
            queue.put_nowait(n)
        stopped = asyncio.Event()
        done = {'ok': 0, 'failed': 0}

        async def worker():
            while not queue.empty() and not stopped.is_set():
                number = queue.get_nowait()
                try:
                    await self.docket(run_id, number)
                    done['ok'] += 1
                except BudgetReached:
                    stopped.set()
                    self.log(f'budget of ${self.settings.budget_usd:.2f} reached; stopping')
                except Exception as error:
                    done['failed'] += 1
                    self._save(run_id, number, 'error', 'error', key_of('error', run_id, number),
                               {'error': f'{type(error).__name__}: {error}', 'trace': traceback.format_exc()[-2000:]})
                    self.log(f'  {number}: failed: {error}')

        await asyncio.gather(*(worker() for _ in range(max(1, workers))))
        status = 'stopped at budget' if stopped.is_set() else 'finished'
        self.store.finish_run(run_id, status, round(self.spent, 4), datetime.now(timezone.utc))
        self.log(f'run {run_id} {status}: {done["ok"]} dockets done, {done["failed"]} failed, ${self.spent:.2f}')
        return run_id

    def _save(self, run_id, docket, layer, node, key, value, exchange=None, cost=0.0, seconds=0.0, reused=False):
        if not reused:
            self.store.save_record(key, docket, layer, node, value, exchange, cost, seconds)
        self.store.link_record(run_id, docket, layer, node, key, reused)

    def _charge(self, cost):
        self.spent += cost

    def _check_budget(self):
        if self.spent >= self.settings.budget_usd:
            raise BudgetReached()

    # ---- one docket ----------------------------------------------------------------

    async def docket(self, run_id, number):
        p = self.pipeline
        docket = docket_text(self.store, number)
        if docket is None:
            raise ValueError(f'no docket {number}')
        text_hash = key_of(docket.text)
        tokens = int(docket.chars / self.settings.chars_per_token)
        self._save(run_id, number, 'input', 'input', key_of('input', text_hash),
                   {'chars': docket.chars, 'tokens_estimate': tokens, 'text_hash': text_hash,
                    'documents': [{'n': d.n, 'title': d.title, 'posted': d.posted, 'pages': len(d.pages)}
                                  for d in docket.documents]})

        scan = await self._scan(run_id, number, docket, text_hash, tokens)

        plan = layers.plan(p, scan)
        self._save(run_id, number, 'plan', 'plan', key_of('plan', self.description['hash'], scan), plan)

        results = await self._steps(run_id, number, docket, text_hash, scan, plan) if plan['proceeds'] else {}

        facts = layers.resolve(p, scan, results, number)
        self._save(run_id, number, 'facts', 'facts', key_of('facts', self.description['hash'], number, scan, results),
                   facts)
        derived = layers.derive(p, facts)
        self._save(run_id, number, 'derive', 'derive', key_of('derive', self.description['hash'], facts), derived)
        row = layers.row(p, number, facts, derived)
        self._save(run_id, number, 'answers', 'row', key_of('row', self.description['hash'], number, facts, derived), row)
        self.log(f'  {number}: {plan["calls"]} reasoning calls, scan {"proceeds" if plan["proceeds"] else "stops"}')

    async def _scan(self, run_id, number, docket, text_hash, tokens):
        questions = {q.id: q.request(docket) for q in self.pipeline.scan.flat()}
        long_context = tokens > self.settings.decision.long_context_tokens
        key = key_of('scan', questions, text_hash, long_context, self.decision.identity())
        cached = self.store.cached_record(key)
        if cached:
            self._save(run_id, number, 'scan', 'scan', key, None, reused=True)
            return cached['value']
        self._check_budget()
        started = time.monotonic()
        reply = await self.decision.ask(docket.text, questions, long_context)
        self._charge(reply.cost)
        self._save(run_id, number, 'scan', 'scan', key, reply.answer, reply.exchange, reply.cost,
                   time.monotonic() - started)
        return reply.answer

    async def _steps(self, run_id, number, docket, text_hash, scan, plan):
        p = self.pipeline
        claims = layers.claims(p, scan)
        base = p.base.render(docket.text, claims)
        base_key = key_of('base', self.nodes['base'], text_hash, claims)
        self._save(run_id, number, 'steps', 'base', base_key,
                   {'chars': len(base), 'claims': claims, 'text_hash': text_hash})
        results, halted = {}, None
        for entry in plan['steps']:
            step = p.nodes[entry['step']]
            if not entry['runs']:
                continue
            if halted:
                results[step.id] = {'skipped': f'halted: {halted} found the docket out of scope'}
                self._save(run_id, number, 'steps', step.id, key_of('skip', base_key, step.id, halted), results[step.id])
                continue
            if entry.get('depends'):
                answers = {sid: r['answer'] for sid, r in results.items() if r.get('answer') is not None}
                met, terms = layers.condition_met(p, step, scan, plan['gates'], answers)
                if not met:
                    results[step.id] = {'skipped': f'condition not met: {step.only_if.text()}', 'terms': terms}
                    self._save(run_id, number, 'steps', step.id, key_of('skip', base_key, step.id, terms),
                               results[step.id])
                    continue
            prompt = layers.render_prompt(p, step, entry['variant'], scan)
            chain = [s for s in step.line() if results.get(s.id, {}).get('answer') is not None]
            history = [(results[s.id]['prompt'], results[s.id]['reply']) for s in chain]
            if step.for_each:
                result = await self._each(run_id, number, docket, base, base_key, step, entry, prompt, chain, history,
                                          results)
            else:
                result = await self._ask(run_id, number, docket, base, base_key, step, step.id, entry, prompt, chain,
                                         history)
            results[step.id] = result
            answers = {sid: r['answer'] for sid, r in results.items() if r.get('answer') is not None}
            if result.get('answer') is not None and layers.halts(step, answers):
                halted = step.id
        return results

    async def _ask(self, run_id, number, docket, base, base_key, step, node_id, entry, prompt, chain, history):
        """One reasoning call for a step (or one item of a for-each step), reused when cached."""
        key = key_of('step', self.nodes[step.id], base_key, prompt, history, self.reasoning.identity())
        cached = self.store.cached_record(key)
        if cached:
            self._save(run_id, number, 'steps', node_id, key, None, reused=True)
            return cached['value']
        self._check_budget()
        started = time.monotonic()
        reply = await self.reasoning.ask(SYSTEM, base, history, prompt, step.returns)
        self._charge(reply.cost)
        answer, checked, verified = (layers.verify_quotes(reply.answer, docket) if reply.answer is not None
                                     else (None, 0, 0))
        final_reply = reply.exchange['attempts'][-1]['reply']
        result = {'variant': entry['variant'], 'prompt': prompt, 'reply': final_reply, 'answer': answer,
                  'error': reply.error, 'attempts': len(reply.exchange['attempts']),
                  'quotes_checked': checked, 'quotes_verified': verified,
                  'chained_after': [s.id for s in chain]}
        self._save(run_id, number, 'steps', node_id, key, result, reply.exchange, reply.cost,
                   time.monotonic() - started)
        return result

    async def _each(self, run_id, number, docket, base, base_key, step, entry, template, chain, history, results):
        """A for-each step: one call per verified item of the earlier list, up to the step's limit.

        Each iteration is stored as its own record (L4b[1], L4b[2], …); the step's own record
        summarizes them, and its answer is {"each": [{"item": …, "answer": …}]}.
        """
        items = layers.each_items(step, results)
        asked = items[:step.limit] if step.limit else items
        each = []
        for i, item in enumerate(asked, 1):
            prompt = template.replace('{item}', step.item_text(item))
            one = await self._ask(run_id, number, docket, base, base_key, step, f'{step.id}[{i}]', entry, prompt,
                                  chain, history)
            each.append({'item': item, **one})
        result = {'variant': entry['variant'], 'items': len(items), 'asked': len(asked), 'each': each,
                  'answer': {'each': [{'item': e['item'], 'answer': e['answer']} for e in each
                                      if e.get('answer') is not None]},
                  'error': '; '.join(f'item {i}: {e["error"]}' for i, e in enumerate(each, 1) if e.get('error'))
                           or None,
                  'attempts': sum(e.get('attempts', 0) for e in each),
                  'quotes_checked': sum(e.get('quotes_checked', 0) for e in each),
                  'quotes_verified': sum(e.get('quotes_verified', 0) for e in each),
                  'chained_after': [s.id for s in chain]}
        self._save(run_id, number, 'steps', step.id, key_of('each', base_key, step.id, [e['prompt'] for e in each],
                                                             [e.get('reply') for e in each]), result)
        return result
