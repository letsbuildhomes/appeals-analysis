"""Model endpoints: the decision model and the reasoning model, behind two small interfaces.

    DecisionModel.ask(state, questions, long_context) -> Reply(answers, exchange, cost)
    ReasoningModel.ask(system, base, history, prompt, returns) -> Reply(answer, exchange, cost)

Reasoning replies must be JSON matching the step's value type. A reply that
doesn't parse or doesn't validate is sent back to the model with the errors,
up to `json_repairs` times, and every attempt is kept in the exchange.

Clients: TypeSafe (decision), Anthropic (Messages API) and OpenAI (Chat
Completions) for reasoning, and Fake versions of both for tests and previews.
Keys stay in memory; nothing here logs them.
"""
import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re
import time

import httpx

from appeals.graph.values import NOT_STATED, make_rng


class BudgetReached(Exception):
    pass


@dataclass
class Reply:
    answer: object
    exchange: dict
    cost: float = 0.0
    error: str | None = None


class Limiter:
    """At most `concurrent` requests in flight and `per_minute` started per minute."""

    def __init__(self, concurrent, per_minute):
        self.slots = asyncio.Semaphore(concurrent)
        self.interval = 60.0 / per_minute if per_minute else 0.0
        self.next_start = 0.0
        self.lock = asyncio.Lock()

    async def __aenter__(self):
        await self.slots.acquire()
        async with self.lock:
            now = time.monotonic()
            wait = self.next_start - now
            self.next_start = max(now, self.next_start) + self.interval
        if wait > 0:
            await asyncio.sleep(wait)

    async def __aexit__(self, *exc):
        self.slots.release()


async def post_json(client, url, headers, body, attempts=5):
    """POST with backoff on rate limits, overload and server errors."""
    for attempt in range(attempts):
        try:
            response = await client.post(url, headers=headers, json=body)
        except httpx.TransportError:
            if attempt == attempts - 1:
                raise
            await asyncio.sleep(2 ** attempt)
            continue
        if response.status_code in (408, 409, 429, 500, 502, 503, 504, 529) and attempt < attempts - 1:
            retry_after = response.headers.get('retry-after')
            await asyncio.sleep(float(retry_after) if retry_after and retry_after.isdigit() else 2 ** (attempt + 1))
            continue
        if response.status_code >= 400:
            raise RuntimeError(f'{url} returned {response.status_code}: {response.text[:400]}')
        return response.json()
    raise RuntimeError(f'{url}: gave up after {attempts} attempts')


# ---- decision model --------------------------------------------------------------------

class TypeSafeDecisions:
    """TypeSafe's System One API (Jev): closed questions answered with probabilities."""

    def __init__(self, endpoint):
        self.endpoint = endpoint
        self.limiter = Limiter(endpoint.concurrent, endpoint.per_minute)
        self.client = httpx.AsyncClient(timeout=600)

    def identity(self):
        return self.endpoint.public()

    async def ask(self, state, questions, long_context=False):
        """questions: {id: {'type': 'choice'|'yes_no', 'instructions', 'criteria'}}"""
        body = {'model': self.endpoint.model, 'state': state, 'questions': {
            qid: {'type': 'noul' if q['type'] == 'yes_no' else q['type'], 'instructions': q['instructions'],
                  'criteria': q['criteria']} for qid, q in questions.items()}}
        headers = {'Authorization': f'Bearer {self.endpoint.key}'}
        if long_context:
            headers['TypeSafe-Danger-Zone-Long-Context'] = 'true'
        async with self.limiter:
            data = await post_json(self.client, f'{self.endpoint.base_url.rstrip("/")}/systemone', headers, body)
        answers = {qid: self._distribution(questions[qid], data['answers'][qid]) for qid in questions}
        tokens = (data.get('usage') or {}).get('input_tokens', 0)
        cost = tokens * self.endpoint.input_per_mtok / 1e6
        exchange = {'request': {**body, 'state': f'[docket text, {len(state)} characters]'},
                    'long_context': long_context, 'response': data, 'usage': data.get('usage')}
        return Reply(answers, exchange, cost)

    @staticmethod
    def _distribution(question, answer):
        if question['type'] == 'yes_no':
            p = float(answer['noul'])
            return {'yes': round(p, 4), 'no': round(1 - p, 4)}
        probabilities = answer.get('probabilities')
        options = list(question['criteria'])
        if isinstance(probabilities, list):
            probabilities = dict(zip(options, probabilities))
        return {k: round(float(v), 4) for k, v in (probabilities or {answer['choice']: 1.0}).items()}


class FakeDecisions:
    """Deterministic made-up probabilities, seeded by the docket and question. For tests and previews."""

    def identity(self):
        return {'format': 'fake', 'base_url': '', 'model': 'fake-decisions'}

    async def ask(self, state, questions, long_context=False):
        answers = {}
        for qid, q in questions.items():
            rng = make_rng(state[:2000], qid)
            options = ['yes', 'no'] if q['type'] == 'yes_no' else list(q['criteria'])
            weights = [rng.random() ** 3 for _ in options]
            favored = 0 if rng.random() < 0.6 else rng.randrange(len(options))   # lean to the first option
            weights[favored] += 1.5
            total = sum(weights)
            answers[qid] = {o: round(w / total, 4) for o, w in zip(options, weights)}
        return Reply(answers, {'request': {'questions': list(questions)}, 'long_context': long_context,
                               'response': 'fake'}, 0.0)


def decision_model(endpoint):
    if endpoint.format == 'typesafe':
        return TypeSafeDecisions(endpoint)
    raise ValueError(f'unknown decision model format {endpoint.format!r}')


# ---- reasoning model ---------------------------------------------------------------------

JSON_BLOCK = re.compile(r'```(?:json)?\s*(.*?)```', re.S)


def parse_json(text):
    """The JSON object in a reply, allowing a fenced code block. Raises ValueError with a readable message."""
    candidate = text.strip()
    fenced = JSON_BLOCK.search(candidate)
    if fenced:
        candidate = fenced.group(1).strip()
    elif not candidate.startswith(('{', '[')):
        start = candidate.find('{')
        candidate = candidate[start:] if start >= 0 else candidate
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as error:
        raise ValueError(f'the reply is not valid JSON ({error.msg} at line {error.lineno}, column {error.colno})') from None


def answer_instructions(returns):
    return ('Reply with a single JSON object and nothing else. It must match this JSON Schema exactly:\n'
            + json.dumps(returns.schema(), indent=1)
            + f'\nEvery answer other than "{NOT_STATED}" needs at least one quote: an exact, continuous passage '
              'copied from the docket text, with its document number (doc) and page number (page).')


def repair_message(errors):
    listed = '\n'.join(f'- {e}' for e in errors[:20])
    return (f'Your reply could not be used:\n{listed}\n'
            'Reply again with only the corrected JSON object, matching the schema.')


class ReasoningModel:
    """Shared behavior: build the conversation, ask, validate, send back errors, retry."""

    def __init__(self, endpoint):
        self.endpoint = endpoint
        self.limiter = Limiter(endpoint.concurrent, endpoint.per_minute)
        self.client = httpx.AsyncClient(timeout=900)

    def identity(self):
        return self.endpoint.public()

    async def ask(self, system, base, history, prompt, returns):
        """history: earlier (prompt, reply) pairs kept in context (chained steps).

        A reply that ran out of output tokens is not the model's mistake, so the same
        request is sent again unchanged, up to `truncation_retries` times. A complete
        reply that doesn't parse or validate is sent back with its errors, up to
        `json_repairs` times.
        """
        question = f'{prompt}\n\n{answer_instructions(returns)}'
        turns = [{'role': 'user', 'text': question}]
        attempts, cost, repairs, truncations = [], 0.0, 0, 0
        while True:
            text, usage, step_cost, truncated = await self._complete(system, base, history, turns)
            cost += step_cost
            if truncated:
                truncations += 1
                attempts.append({'reply': text, 'usage': usage, 'truncated': True,
                                 'errors': [f'the reply ran out of output tokens '
                                            f'({self.endpoint.max_output_tokens} allowed)']})
                if truncations > self.endpoint.truncation_retries:
                    return Reply(None, self._exchange(system, history, question, attempts), cost,
                                 error=f'ran out of output tokens {truncations} times')
                continue
            try:
                value = parse_json(text)
                errors = returns.validate(value, '')
            except ValueError as error:
                value, errors = None, [str(error)]
            attempts.append({'reply': text, 'errors': errors, 'usage': usage})
            if not errors:
                return Reply(value, self._exchange(system, history, question, attempts), cost)
            repairs += 1
            if repairs > self.endpoint.json_repairs:
                return Reply(None, self._exchange(system, history, question, attempts), cost,
                             error=f'no valid reply after {len(attempts)} attempts')
            turns += [{'role': 'assistant', 'text': text}, {'role': 'user', 'text': repair_message(errors)}]

    def _exchange(self, system, history, question, attempts):
        return {'model': self.identity(), 'system': system, 'history': [{'prompt': p, 'reply': r} for p, r in history],
                'prompt': question, 'attempts': attempts}

    def _cost(self, usage, sent_at, tokens_in, tokens_out, cache_read=0, cache_write=0):
        """The call's cost at the prices in force when it was sent; the rate used is added to `usage`."""
        rate, p = self.endpoint.prices(sent_at)
        usage['priced'] = {'sent_at': sent_at.isoformat(), 'rate': rate}
        return (tokens_in * p['input_per_mtok'] + tokens_out * p['output_per_mtok']
                + cache_read * p['cache_read_per_mtok'] + cache_write * p['cache_write_per_mtok']) / 1e6

    async def _complete(self, system, base, history, turns):
        """One request. Returns (text, usage, cost, truncated), where truncated means the output limit was hit."""
        raise NotImplementedError


class AnthropicReasoning(ReasoningModel):
    """The Messages API. The docket base is marked for prompt caching."""

    async def _complete(self, system, base, history, turns):
        messages = []
        pending = [{'type': 'text', 'text': base, 'cache_control': {'type': 'ephemeral'}}]
        for prompt, reply in history:
            messages += [{'role': 'user', 'content': pending + [{'type': 'text', 'text': prompt}]},
                         {'role': 'assistant', 'content': reply}]
            pending = []
        for turn in turns:
            if turn['role'] == 'user':
                messages.append({'role': 'user', 'content': pending + [{'type': 'text', 'text': turn['text']}]})
                pending = []
            else:
                messages.append({'role': 'assistant', 'content': turn['text']})
        body = {'model': self.endpoint.model, 'max_tokens': self.endpoint.max_output_tokens, 'system': system,
                'messages': messages}
        headers = {'x-api-key': self.endpoint.key, 'anthropic-version': '2023-06-01'}
        async with self.limiter:
            sent_at = datetime.now(timezone.utc)
            data = await post_json(self.client, f'{self.endpoint.base_url.rstrip("/")}/v1/messages', headers, body)
        text = ''.join(block.get('text', '') for block in data.get('content', []) if block.get('type') == 'text')
        u = dict(data.get('usage') or {})
        cost = self._cost(u, sent_at, u.get('input_tokens', 0), u.get('output_tokens', 0),
                          u.get('cache_read_input_tokens', 0), u.get('cache_creation_input_tokens', 0))
        return text, u, cost, data.get('stop_reason') == 'max_tokens'


class OpenAIReasoning(ReasoningModel):
    """Chat Completions, as offered by OpenAI and most compatible providers.

    The base is always the first user content part, so providers with
    automatic prefix caching reuse it.
    """

    async def _complete(self, system, base, history, turns):
        messages = [{'role': 'system', 'content': system}]
        pending = [{'type': 'text', 'text': base}]
        for prompt, reply in history:
            messages += [{'role': 'user', 'content': pending + [{'type': 'text', 'text': prompt}]},
                         {'role': 'assistant', 'content': reply}]
            pending = []
        for turn in turns:
            if turn['role'] == 'user':
                messages.append({'role': 'user', 'content': pending + [{'type': 'text', 'text': turn['text']}]})
                pending = []
            else:
                messages.append({'role': 'assistant', 'content': turn['text']})
        body = {'model': self.endpoint.model, 'messages': messages, 'max_tokens': self.endpoint.max_output_tokens}
        headers = {'Authorization': f'Bearer {self.endpoint.key}'}
        async with self.limiter:
            sent_at = datetime.now(timezone.utc)
            data = await post_json(self.client, f'{self.endpoint.base_url.rstrip("/")}/chat/completions', headers, body)
        choice = data['choices'][0] if data.get('choices') else {}
        text = (choice.get('message') or {}).get('content') or ''
        u = dict(data.get('usage') or {})
        cached = ((u.get('prompt_tokens_details') or {}).get('cached_tokens')
                  or u.get('prompt_cache_hit_tokens', 0))            # DeepSeek's name for it
        cost = self._cost(u, sent_at, u.get('prompt_tokens', 0) - cached, u.get('completion_tokens', 0), cached)
        return text, u, cost, choice.get('finish_reason') == 'length'


class FakeReasoning(ReasoningModel):
    """Schema-valid made-up answers with real quotes from the docket text.

    Seeded by the prompt, so it is deterministic. About one reply in six is
    first sent malformed, to exercise the repair loop.
    """

    def __init__(self):
        from appeals.config import Endpoint
        super().__init__(Endpoint(format='fake', base_url='', model='fake-reasoning', key_env='', json_repairs=2,
                                  concurrent=64, per_minute=0))

    async def _complete(self, system, base, history, turns):
        question = turns[0]['text']
        rng = make_rng(base[:2000], question[:400], len(turns))
        if len(turns) == 1 and rng.random() < 1 / 6:
            return '{"answer": "unfinished', {'fake': True}, 0.0, False
        schema = json.loads(question.split('JSON Schema exactly:\n', 1)[1].rsplit('\nEvery answer', 1)[0])
        pages = re.findall(r'<document n="(\d+)"[^>]*>|<page n="(\d+)" source="[a-z]+">\n(.*?)\n</page>', base, re.S)
        passages, doc = [], 1
        for d, page, text in pages:
            if d:
                doc = int(d)
            elif page:
                sentences = [s.strip() for s in re.split(r'(?<=[.;])\s+', ' '.join(text.split())) if 40 < len(s.strip()) < 220]
                passages += [(doc, int(page), s) for s in sentences[:6]]
        await asyncio.sleep(0)
        return json.dumps(_example(schema, rng, passages)), {'fake': True}, 0.0, False


def _example(schema, rng, passages):
    """A value matching a JSON schema made by values.py, with quotes drawn from real passages."""
    if 'enum' in schema:
        return rng.choice(schema['enum'])
    if 'anyOf' in schema:
        choice = rng.choice(schema['anyOf'])
        if 'const' in choice:
            return choice['const']
        if choice.get('type') == 'integer':
            return rng.choice([1, 2, 3, 6, 12, 24])
        return f'20{rng.randint(5, 24):02d}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}'
    if schema.get('type') == 'object':
        props = schema['properties']
        if set(props) == {'answer', 'quotes'}:
            answer = _example(props['answer'], rng, passages)
            quotes = []
            if answer != NOT_STATED and passages:
                doc, page, text = rng.choice(passages)
                quotes = [{'doc': doc, 'page': page, 'quote': text}]
            return {'answer': answer, 'quotes': quotes}
        return {k: _example(v, rng, passages) for k, v in props.items()}
    if schema.get('type') == 'array':
        return [_example(schema['items'], rng, passages) for _ in range(rng.randint(1, 3))]
    if schema.get('type') == 'string':
        return 'A short description drawn from the decision.'
    return None


def reasoning_model(endpoint):
    if endpoint.format == 'anthropic':
        return AnthropicReasoning(endpoint)
    if endpoint.format == 'openai':
        return OpenAIReasoning(endpoint)
    raise ValueError(f'unknown reasoning model format {endpoint.format!r}')
