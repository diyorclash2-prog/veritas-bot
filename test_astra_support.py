import json
import os
import unittest
from unittest.mock import patch, AsyncMock

import httpx

from astra_support import ASTRA, AIUnavailable, OpenAITransport, CodingSessions, api_id


class TransportTests(unittest.IsolatedAsyncioTestCase):
    def make(self, status=200, data=None, body=None):
        self.requests = []
        def handle(request):
            self.requests.append(request)
            return httpx.Response(status, json=data) if body is None else httpx.Response(status, content=body)
        return OpenAITransport(key='synthetic-key', transport=httpx.MockTransport(handle))

    async def test_astra_probe_uses_requested_model_without_tools_or_storage(self):
        api = self.make(data={'status': 'completed', 'output': [{'type': 'message', 'content': [
            {'type': 'output_text', 'text': 'ASTRA_CONNECTION_OK'}]}]})
        self.assertTrue(await api.probe())
        payload = json.loads(self.requests[0].content)
        self.assertEqual(payload['model'], ASTRA)
        self.assertEqual(payload['reasoning'], {'effort': 'low'})
        self.assertEqual(payload['max_output_tokens'], 512)
        self.assertFalse(payload['store'])
        self.assertNotIn('tools', payload)

    async def test_diagnosis_has_reasoning_budget_and_preserves_model_scope(self):
        api = self.make(data={'status': 'completed', 'output': [{'type': 'message', 'content': [
            {'type': 'output_text', 'text': 'Tahlil'}]}]})
        with patch.dict(os.environ, {'VERITAS_SUPPORT_MODEL': ASTRA, 'OPENAI_MODEL': 'other-chat-model'}):
            self.assertEqual(await api.respond('instructions', 'report'), 'Tahlil')
        payload = json.loads(self.requests[0].content)
        self.assertEqual(payload['reasoning'], {'effort': 'medium'})
        self.assertEqual(payload['max_output_tokens'], 4096)
        self.assertNotIn('temperature', payload)

    async def test_api_errors_are_classified_without_private_body(self):
        for status, code, expected in [(401, 'invalid_api_key', 'authentication'),
                                      (403, 'permission_denied', 'permission'),
                                      (404, 'model_not_found', 'model_not_found'),
                                      (429, 'insufficient_quota', 'quota'),
                                      (429, 'rate_limit_exceeded', 'rate_limit'),
                                      (500, 'unknown', 'api_error')]:
            with self.subTest(status=status, code=code):
                api = self.make(status=status, data={'error': {'code': code, 'message': 'PRIVATE VALUE'}})
                with self.assertRaises(AIUnavailable) as caught:
                    await api.probe()
                self.assertEqual(caught.exception.code, expected)
                self.assertNotIn('PRIVATE', str(caught.exception) + caught.exception.user_message)

    async def test_incomplete_empty_and_invalid_responses_are_rejected(self):
        for data in ({'status': 'incomplete'}, {'status': 'completed', 'output': []}, []):
            with self.assertRaises(AIUnavailable):
                await self.make(data=data).probe()

    async def test_network_error_does_not_leak_request(self):
        def handle(request):
            raise httpx.ReadTimeout('PRIVATE KEY', request=request)
        api = OpenAITransport(key='synthetic-key', transport=httpx.MockTransport(handle))
        with self.assertRaises(AIUnavailable) as caught:
            await api.probe()
        self.assertEqual(caught.exception.code, 'network')
        self.assertNotIn('PRIVATE', str(caught.exception))

    async def test_rejects_cross_origin_and_path_traversal(self):
        api = self.make(data={})
        for path in ('https://attacker.invalid', '/../secret', '//https://attacker.invalid'):
            with self.assertRaises(ValueError):
                await api.json('GET', path)
        self.assertEqual(self.requests, [])

    async def test_response_size_limit(self):
        with self.assertRaises(AIUnavailable):
            await self.make(body=b'x'*101).request('GET', '/test', max_bytes=100)

    async def test_missing_key_does_not_call_network(self):
        api = self.make(data={})
        api.key = ''
        with self.assertRaises(AIUnavailable) as caught:
            await api.probe()
        self.assertEqual(caught.exception.code, 'missing_key')
        self.assertFalse(self.requests)

    async def test_redirect_is_not_followed(self):
        api = self.make(status=302, data={})
        with self.assertRaises(AIUnavailable):
            await api.probe()
        self.assertEqual(len(self.requests), 1)


class SessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_session_is_saved_before_any_task_is_sent(self):
        transport = AsyncMock()
        transport.json.return_value = {'id': 'session_test'}
        api = CodingSessions(transport)
        self.assertEqual(await api.create({'agent': {'model': ASTRA}, 'input': 'task'}), 'session_test')
        self.assertNotIn('input', transport.json.call_args.kwargs['payload'])
        transport.request.assert_not_called()

    async def test_submission_reuses_idempotency_key(self):
        transport = AsyncMock()
        api = CodingSessions(transport)
        await api.submit('session_test', 'task', 'submission_1')
        await api.submit('session_test', 'task', 'submission_1')
        self.assertEqual(transport.request.call_args_list[0], transport.request.call_args_list[1])
        self.assertEqual(transport.request.call_args.kwargs['idempotency_key'], 'submission_1')

    async def test_artifact_requires_matching_turn_and_exact_path(self):
        transport = AsyncMock()
        transport.json.return_value = {'data': [{'id': 'artifact', 'turn_id': 'old_turn',
                'path': '/workspace/outputs/repair.json', 'size_bytes': 10}]}
        api = CodingSessions(transport)
        with self.assertRaises(AIUnavailable):
            await api.artifact('session_test', 'new_turn', '/workspace/outputs/repair.json')
        transport.request.assert_not_called()

    async def test_oversized_artifact_is_not_downloaded(self):
        transport = AsyncMock()
        transport.json.return_value = {'data': [{'id': 'artifact', 'turn_id': 'turn',
                'path': '/workspace/outputs/repair.json', 'size_bytes': 3_000_000}]}
        with self.assertRaises(AIUnavailable):
            await CodingSessions(transport).artifact('session_test', 'turn', '/workspace/outputs/repair.json')
        transport.request.assert_not_called()

    def test_resource_identifiers_cannot_change_api_path(self):
        for value in ('../sessions', 'abc?x=1', 'https://evil', '', None):
            with self.assertRaises(AIUnavailable):
                api_id(value)


if __name__ == '__main__':
    unittest.main()
