"""Model endpoints: the decision model and the reasoning model, behind two small interfaces.

    DecisionModel.ask(state, questions, long_context) -> Reply(answers, exchange, cost)
    ReasoningModel.ask(system, base, history, prompt, returns) -> Reply(answer, exchange, cost)

A chained step's request replays the earlier steps' turns exactly as they were sent and received, then
appends its own question, so each request extends the one before it and a provider's prefix cache reuses it.

Reasoning replies must be JSON matching the step's value type. A reply that
doesn't parse or doesn't validate is sent back to the model with the errors,
up to `json_repairs` times, and every attempt is kept in the exchange.

Clients: TypeSafe (decision), Anthropic (Messages API) and OpenAI (Chat
Completions) for reasoning, and Fake versions of both for tests and previews.
A client speaks its API; the model's provider reads the token usage and
prices the call (appeals/providers). Keys stay in memory; nothing here logs them.
"""
import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re
import time

import httpx

from appeals.graph.values import NONE_FOUND, NOT_STATED, ListOf, OneOf, Quoted, Record, make_rng
from appeals.providers import unpriced


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

    def __init__(self, model):
        self.model = model
        self.limiter = Limiter(model.provider.concurrent, model.provider.per_minute)
        self.client = httpx.AsyncClient(timeout=600)

    def identity(self):
        return self.model.identity()

    async def ask(self, state, questions, long_context=False):
        """questions: {id: {'type': 'choice'|'yes_no', 'instructions', 'criteria'}}"""
        body = {'model': self.model.name, 'state': state, 'questions': {
            qid: {'type': 'noul' if q['type'] == 'yes_no' else q['type'], 'instructions': q['instructions'],
                  'criteria': q['criteria']} for qid, q in questions.items()}}
        headers = {'Authorization': f'Bearer {self.model.key}'}
        if long_context:
            headers['TypeSafe-Danger-Zone-Long-Context'] = 'true'
        async with self.limiter:
            sent_at = datetime.now(timezone.utc)
            data = await post_json(self.client, f'{self.model.provider.base_url.rstrip("/")}/systemone', headers, body)
        answers = {qid: self._distribution(questions[qid], data['answers'][qid]) for qid in questions}
        charge = self.model.charge(self.model.usage(data.get('usage')), sent_at)
        exchange = {'request': {**body, 'state': f'[docket text, {len(state)} characters]'},
                    'long_context': long_context, 'response': data, 'usage': data.get('usage'), 'priced': charge.basis}
        return Reply(answers, exchange, charge.usd)

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


def decision_model(model):
    """The client for a decision model (a providers.Model), chosen by its provider's API."""
    if model.provider.api == 'typesafe':
        return TypeSafeDecisions(model)
    raise ValueError(f'{model.ref}: no decision-model client for the {model.provider.api!r} API')


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
    """What follows every step's question: the reply's schema, the quoting rule, and what each option means."""
    schema = json.dumps(returns.schema(), indent=1)
    unquoted = f'"{NOT_STATED}" or "{NONE_FOUND}"' if f'"{NONE_FOUND}"' in schema else f'"{NOT_STATED}"'
    parts = ['Reply with a single JSON object and nothing else. It must match this JSON Schema exactly:', schema,
             f'Wherever the schema has "answer" and "quotes", give at least one quote for every answer other than '
             f'{unquoted}: an exact, continuous passage copied from the docket text, with its document number (doc) '
             f'and page number (page).']
    meanings = [f'{path}:\n' + '\n'.join(f'- {option}: {meaning}' for option, meaning in options.items())
                for path, options in option_meanings(returns)]
    if meanings:
        parts += ['What the options mean:', *meanings]
    return '\n\n'.join(parts)


TRIVIAL = {'Yes.', 'No.', 'The documents do not establish it.'}


def option_meanings(kind, path=()):
    """(field path, {option: meaning}) for each choice in a reply type, leaving out meanings that say nothing more
    than the option itself (a plain yes, no or "not stated")."""
    if isinstance(kind, Record):
        return [m for key, field in kind.fields.items() for m in option_meanings(field, (*path, key))]
    if isinstance(kind, ListOf):
        return option_meanings(kind.item, path)
    if isinstance(kind, Quoted):
        return option_meanings(kind.answer, path)
    if isinstance(kind, OneOf):
        told = {o: m for o, m in kind.options.items() if m not in TRIVIAL}
        return [(' → '.join(path), told)] if told else []
    return []


def repair_message(errors):
    listed = '\n'.join(f'- {e}' for e in errors[:20])
    return f'Your reply could not be used:\n\n{listed}\n\nReply again with only the corrected JSON object, matching the schema.'


@dataclass
class Completion:
    """One request's outcome: the reply text, token usage, cost, the API's stop reason, and
    whether the reply was cut off at the output limit."""
    text: str
    usage: dict
    cost: float
    stop: str | None
    truncated: bool


class ReasoningModel:
    """Shared behavior: build the conversation, ask, validate, send back errors, retry."""

    def __init__(self, settings):
        """settings: config.Reasoning, the model and how steps use it."""
        self.settings = settings
        self.model = settings.model
        self.limiter = Limiter(self.model.provider.concurrent, self.model.provider.per_minute)
        self.client = httpx.AsyncClient(timeout=900)

    def identity(self):
        return self.model.identity()

    async def ask(self, system, base, history, prompt, returns):
        """history: the turns of the earlier steps kept in context (chained steps), exactly as sent and received:
        a list of {"role": "user" | "assistant", "text": …}. The exchange's `turns` are this step's own, to be
        replayed after it.

        A reply that ran out of output tokens, or came back empty, is not a mistake the
        model can fix, so the same request is sent again unchanged, up to `resends` times.
        A reply that doesn't parse or validate is sent back with its errors, up to
        `json_repairs` times. Every attempt records the stop reason the API gave.
        """
        question = f'{prompt}\n\n{answer_instructions(returns)}'
        turns = [{'role': 'user', 'text': question}]
        attempts, cost, repairs, resends = [], 0.0, 0, 0
        while True:
            done = await self._complete(system, base, history, turns)
            cost += done.cost
            if done.truncated or not done.text.strip():
                resends += 1
                why = (f'the reply ran out of output tokens ({self.settings.max_output_tokens} allowed)'
                       if done.truncated else 'the reply was empty')
                attempts.append({'reply': done.text, 'usage': done.usage, 'stop': done.stop, 'resent': True,
                                 'truncated': done.truncated, 'errors': [why]})
                if resends > self.settings.resends:
                    return Reply(None, self._exchange(system, history, question, attempts), cost,
                                 error=f'no usable reply after {resends} resends ({why})')
                continue
            text = done.text
            try:
                value = parse_json(text)
                errors = returns.validate(value, '')
            except ValueError as error:
                value, errors = None, [str(error)]
            attempts.append({'reply': text, 'errors': errors, 'usage': done.usage, 'stop': done.stop})
            if not errors:
                return Reply(value, self._exchange(system, history, question, attempts,
                                                   turns + [{'role': 'assistant', 'text': text}]), cost)
            repairs += 1
            if repairs > self.settings.json_repairs:
                return Reply(None, self._exchange(system, history, question, attempts), cost,
                             error=f'no valid reply after {len(attempts)} attempts')
            turns += [{'role': 'assistant', 'text': text}, {'role': 'user', 'text': repair_message(errors)}]

    def _exchange(self, system, history, question, attempts, turns=None):
        return {'model': self.identity(), 'system': system, 'history': history, 'prompt': question,
                'attempts': attempts, 'turns': turns}

    def _cost(self, usage, sent_at):
        """The call's cost, priced by the model's provider; how it was priced is added to `usage`."""
        charge = self.model.charge(self.model.usage(usage), sent_at)
        usage['priced'] = charge.basis
        return charge.usd

    async def _complete(self, system, base, history, turns):
        """One request, returned as a Completion."""
        raise NotImplementedError


def _messages(base, turns):
    """The conversation as API messages: the base is the first content part of the first user turn."""
    messages, pending = [], [base]
    for turn in turns:
        if turn['role'] == 'user':
            messages.append({'role': 'user', 'content': pending + [{'type': 'text', 'text': turn['text']}]})
            pending = []
        else:
            messages.append({'role': 'assistant', 'content': turn['text']})
    return messages


class AnthropicReasoning(ReasoningModel):
    """The Messages API. The docket base is marked for prompt caching."""

    async def _complete(self, system, base, history, turns):
        cached = {'cache_control': {'type': 'ephemeral'}}
        messages = _messages({'type': 'text', 'text': base, **cached}, [*history, *turns])
        if history:              # a second cache point: the earlier steps' last reply (one message per turn)
            last = messages[len(history) - 1]
            last['content'] = [{'type': 'text', 'text': last['content'], **cached}]
        body = {'model': self.model.name, 'max_tokens': self.settings.max_output_tokens, 'system': system,
                'messages': messages}
        headers = {'x-api-key': self.model.key, 'anthropic-version': '2023-06-01'}
        async with self.limiter:
            sent_at = datetime.now(timezone.utc)
            data = await post_json(self.client, f'{self.model.provider.base_url.rstrip("/")}/v1/messages', headers, body)
        text = ''.join(block.get('text', '') for block in data.get('content', []) if block.get('type') == 'text')
        u = dict(data.get('usage') or {})
        cost = self._cost(u, sent_at)
        stop = data.get('stop_reason')
        return Completion(text, u, cost, stop, stop == 'max_tokens')


class OpenAIReasoning(ReasoningModel):
    """Chat Completions, as offered by OpenAI and most compatible providers.

    The base is always the first user content part, so providers with
    automatic prefix caching reuse it.
    """

    async def _complete(self, system, base, history, turns):
        messages = [{'role': 'system', 'content': system}, *_messages({'type': 'text', 'text': base}, [*history, *turns])]
        body = {'model': self.model.name, 'messages': messages, 'max_tokens': self.settings.max_output_tokens}
        headers = {'Authorization': f'Bearer {self.model.key}'}
        async with self.limiter:
            sent_at = datetime.now(timezone.utc)
            data = await post_json(self.client, f'{self.model.provider.base_url.rstrip("/")}/chat/completions', headers, body)
        choice = data['choices'][0] if data.get('choices') else {}
        text = (choice.get('message') or {}).get('content') or ''
        u = dict(data.get('usage') or {})
        cost = self._cost(u, sent_at)
        stop = choice.get('finish_reason')
        return Completion(text, u, cost, stop, stop == 'length')


class FakeReasoning(ReasoningModel):
    """Schema-valid made-up answers with real quotes from the docket text.

    Seeded by the prompt, so it is deterministic. About one reply in six is
    first sent malformed, to exercise the repair loop.
    """

    def __init__(self):
        from appeals.config import Reasoning
        super().__init__(Reasoning(unpriced('fake-reasoning')))

    async def _complete(self, system, base, history, turns):
        question = turns[0]['text']
        rng = make_rng(base[:2000], question[:400], len(turns))
        if len(turns) == 1 and rng.random() < 1 / 6:
            return Completion('{"answer": "unfinished', {'fake': True}, 0.0, 'stop', False)
        schema = json.loads(question.split('JSON Schema exactly:\n\n', 1)[1].split('\n\nWherever', 1)[0])
        pages = re.findall(r'<document n="(\d+)"[^>]*>|<page n="(\d+)" source="[a-z]+">\n(.*?)\n</page>', base, re.S)
        passages, doc = [], 1
        for d, page, text in pages:
            if d:
                doc = int(d)
            elif page:
                sentences = [s.strip() for s in re.split(r'(?<=[.;])\s+', ' '.join(text.split())) if 40 < len(s.strip()) < 220]
                passages += [(doc, int(page), s) for s in sentences[:6]]
        await asyncio.sleep(0)
        return Completion(json.dumps(_example(schema, rng, passages)), {'fake': True}, 0.0, 'stop', False)


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


def reasoning_model(settings):
    """The client for the reasoning model in `settings` (config.Reasoning), chosen by its provider's API."""
    api = settings.model.provider.api
    if api == 'anthropic':
        return AnthropicReasoning(settings)
    if api == 'openai':
        return OpenAIReasoning(settings)
    raise ValueError(f'{settings.model.ref}: no reasoning-model client for the {api!r} API')
