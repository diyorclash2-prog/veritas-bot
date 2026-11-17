"""Bounded OpenAI transport for owner diagnostics and isolated coding sessions.

Credentials remain in the application. No generated code executes in this process.
"""
from __future__ import annotations

import os
import re

import httpx

API = 'https://api.openai.com/v1'
ASTRA = 'gpt-6-astra'


class AIUnavailable(RuntimeError):
    def __init__(self, code, status=None):
        self.code, self.status = code, status
        super().__init__(code)

    @property
    def user_message(self):
        return {
            'missing_key': 'OpenAI API kaliti sozlanmagan.',
            'authentication': 'OpenAI API kaliti yaroqsiz yoki bekor qilingan.',
            'permission': 'API kalitida ushbu model yoki agent xizmatiga ruxsat yo‘q.',
            'model_not_found': 'Tanlangan AI modeli bu API loyihasida mavjud emas.',
            'quota': 'OpenAI API krediti yoki xarajat limiti tugagan.',
            'rate_limit': 'OpenAI so‘rovlar limiti. Birozdan keyin qayta urinib ko‘ring.',
            'incomplete': 'AI javobni yakunlamadi; murojaat saqlangan.',
            'network': 'AI xizmatiga ulanish uzildi; murojaat saqlangan.',
            'invalid_response': 'AI javobi kutilgan formatda kelmadi.',
        }.get(self.code, 'AI xizmati so‘rovni bajara olmadi; murojaat saqlangan.')


def configured_model():
    # Model activation is an explicit deploy setting, not an implicit fallback.
    return os.getenv('VERITAS_SUPPORT_MODEL') or os.getenv('OPENAI_MODEL') or 'gpt-5.6-luna'


def api_error(response):
    try:
        error = response.json().get('error', {})
        code = error.get('code')
    except (ValueError, AttributeError):
        code = None
    if code in {'insufficient_quota', 'billing_hard_limit_reached'}:
        return AIUnavailable('quota', response.status_code)
    if code == 'model_not_found':
        return AIUnavailable('model_not_found', response.status_code)
    return AIUnavailable({401: 'authentication', 403: 'permission', 429: 'rate_limit'}.get(
        response.status_code, 'api_error'), response.status_code)


class OpenAITransport:
    def __init__(self, *, key=None, transport=None):
        self.key = key if key is not None else os.getenv('OPENAI_API_KEY', '').strip()
        self.transport = transport

    async def request(self, method, path, *, payload=None, agents=False, max_bytes=2_000_000, idempotency_key=None):
        if not self.key:
            raise AIUnavailable('missing_key')
        if not path.startswith('/') or '://' in path or '..' in path:
            raise ValueError('Invalid API path')
        headers = {'Authorization': 'Bearer ' + self.key}
        if agents:
            headers['OpenAI-Beta'] = 'agents=v1'
        if idempotency_key:
            headers['Idempotency-Key'] = idempotency_key
        try:
            async with httpx.AsyncClient(timeout=90, follow_redirects=False,
                                         transport=self.transport) as client:
                async with client.stream(method, API + path, headers=headers, json=payload) as response:
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > max_bytes:
                            raise AIUnavailable('invalid_response')
                    buffered = httpx.Response(response.status_code, content=bytes(body))
                    if not 200 <= response.status_code < 300:
                        raise api_error(buffered)
                    return buffered
        except httpx.HTTPError:
            # Do not retain exception text, request URLs, headers, or response bodies.
            raise AIUnavailable('network') from None

    async def json(self, method, path, **kwargs):
        response = await self.request(method, path, **kwargs)
        try:
            result = response.json()
            if not isinstance(result, dict):
                raise ValueError()
            return result
        except ValueError:
            raise AIUnavailable('invalid_response') from None

    async def respond(self, instructions, text, *, model=None, probe=False):
        model = model or configured_model()
        payload = {'model': model, 'store': False, 'instructions': instructions,
                   'input': text, 'max_output_tokens': 512 if probe else 4096}
        if model == ASTRA:
            payload['reasoning'] = {'effort': 'low' if probe else 'medium'}
        data = await self.json('POST', '/responses', payload=payload)
        if data.get('status') != 'completed':
            raise AIUnavailable('incomplete')
        try:
            answer = '\n'.join(p['text'] for item in data.get('output', [])
                               if item.get('type') == 'message'
                               for p in item.get('content', []) if p.get('type') == 'output_text').strip()
        except (TypeError, KeyError, AttributeError):
            raise AIUnavailable('invalid_response') from None
        if not answer:
            raise AIUnavailable('incomplete')
        return answer

    async def probe(self):
        answer = await self.respond('Reply with exactly ASTRA_CONNECTION_OK. Do not use tools.',
                                    'Connection test.', model=ASTRA, probe=True)
        return answer == 'ASTRA_CONNECTION_OK'


def api_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,160}', value):
        raise AIUnavailable('invalid_response')
    return value


class CodingSessions:
    def __init__(self, api=None):
        self.api = api or OpenAITransport()

    async def create(self, payload):
        # Persist the returned id before submitting any model task.
        payload = {k: v for k, v in payload.items() if k != 'input'}
        data = await self.api.json('POST', '/agents/sessions', agents=True, payload=payload)
        return api_id(data.get('id'))

    async def submit(self, session_id, text, submission_key):
        await self.api.request('POST', f'/agents/sessions/{api_id(session_id)}/events', agents=True,
            idempotency_key=submission_key, payload={'events': [{'type': 'agent.session.input.message',
            'input': [{'role': 'user', 'content': [{'type': 'input_text', 'text': text}]}]}]})

    async def state(self, session_id):
        return await self.api.json('GET', f'/agents/sessions/{api_id(session_id)}', agents=True)

    async def turn(self, session_id):
        data = await self.api.json('GET', f'/agents/sessions/{api_id(session_id)}/turns?limit=20', agents=True)
        return next((t for t in data.get('data', []) if t.get('subagent_id') is None), None)

    async def artifact(self, session_id, turn_id, path, *, max_bytes=250_000):
        session_id, turn_id = api_id(session_id), api_id(turn_id)
        data = await self.api.json('GET', f'/agents/sessions/{session_id}/artifacts?limit=100', agents=True)
        candidates = [a for a in data.get('data', []) if a.get('turn_id') == turn_id and a.get('path') == path]
        if len(candidates) != 1 or not isinstance(candidates[0].get('size_bytes'), int) or not 0 <= candidates[0]['size_bytes'] <= max_bytes:
            raise AIUnavailable('invalid_response')
        artifact_id = api_id(candidates[0]['id'])
        r = await self.api.request('GET', f'/agents/sessions/{session_id}/artifacts/{artifact_id}/content',
                                   agents=True, max_bytes=max_bytes)
        return r.content

    async def cancel(self, session_id):
        await self.api.request('POST', f'/agents/sessions/{api_id(session_id)}/events', agents=True,
                               payload={'events': [{'type': 'agent.session.input.cancel'}]})

    async def delete(self, session_id):
        try:
            await self.api.request('DELETE', f'/agents/sessions/{api_id(session_id)}', agents=True)
        except AIUnavailable as exc:
            if exc.status != 404:
                raise
