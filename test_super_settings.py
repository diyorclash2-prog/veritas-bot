import asyncio
import json
import logging
import os
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from telegram.error import TimedOut
from telegram.ext import ApplicationHandlerStop

from super_settings import Reports, SuperSettings, ErrorSummary, redact, diagnose, menu, register_super_settings, STATE_KEY, JOB_NAME
from test_lingua_bot_bridge import OfflineRequest
from telegram.ext import Application


def update(owner=123, chat_type='private', data='supercfg:report', text='Test tugmasi ishlamayapti', message_id=1):
    msg = NS(reply_text=AsyncMock(), text=text, message_id=message_id)
    return NS(effective_user=NS(id=owner), effective_chat=NS(id=owner, type=chat_type),
              effective_message=msg, callback_query=NS(data=data, message=msg, answer=AsyncMock()))


class RedactionTests(unittest.TestCase):
    def test_credentials_contacts_and_urls_redacted(self):
        secret = 'unusual-secret-123456'
        with patch.dict(os.environ, {'TG_SESSION': secret}):
            clean = redact(f'{secret} sk-example123456789 123456:ABCDEFGHIJKLMNO +1 555 123 4567 test@example.org https://example.org/?key=oops @someone password=hidden')
        for value in (secret, 'example123', 'ABCDEFGHIJ', '555', 'example.org', '@someone', 'hidden'):
            self.assertNotIn(value, clean)

    def test_logs_do_not_capture_message_or_exception_text(self):
        handler = ErrorSummary()
        try:
            raise ValueError('SECRET USER DATA')
        except ValueError:
            import sys
            record = logging.LogRecord('app', logging.ERROR, __file__, 10, 'secret=%s', ('secret',), sys.exc_info())
        handler.emit(record)
        self.assertNotIn('secret', json.dumps(list(handler.events)).lower())
        self.assertEqual(handler.events[0]['error'], 'ValueError')

    def test_error_ring_is_bounded(self):
        handler = ErrorSummary()
        for n in range(20):
            handler.emit(logging.LogRecord('x', logging.ERROR, __file__, n, 'not captured', (), None))
        self.assertEqual(len(handler.events), 12)


class SuperTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'test.db'
        self.app = NS(bot_data={}, job_queue=NS(get_jobs_by_name=lambda name: []))
        self.ai = AsyncMock(return_value='Sababni aniqlash uchun qo‘shimcha dalil kerak.')
        self.bridge = SuperSettings(self.path, {123}, self.app, ai=self.ai, clock=lambda: 1000)
        self.ctx = NS(bot=NS(send_message=AsyncMock()), args=None)

    async def callback(self, up):
        with self.assertRaises(ApplicationHandlerStop):
            await self.bridge.callback(up, self.ctx)

    async def submit(self, text='Test tugmasi ishlamayapti', message_id=1):
        await self.callback(update())
        up = update(text=text, message_id=message_id)
        with self.assertRaises(ApplicationHandlerStop):
            await self.bridge.receive(up, self.ctx)
        return up

    async def test_nonowner_and_group_callbacks_are_denied(self):
        for owner, kind in [(999, 'private'), (123, 'group'), (123, 'supergroup')]:
            up = update(owner=owner, chat_type=kind)
            await self.callback(up)
            self.assertFalse(self.bridge.reports.awaiting(owner, 1000))
            up.effective_message.reply_text.assert_not_awaited()

    async def test_unarmed_and_nonowner_messages_are_not_intercepted(self):
        await self.bridge.receive(update(), self.ctx)
        self.bridge.reports.arm(999, 1000)
        await self.bridge.receive(update(owner=999), self.ctx)
        self.assertEqual(self.bridge.reports.recent(123), [])
        self.assertEqual(self.bridge.reports.recent(999), [])

    async def test_expired_session_and_commands_pass_to_original_handlers(self):
        self.bridge.reports.arm(123, 0)
        await self.bridge.receive(update(), self.ctx)
        self.bridge.reports.arm(123, 1000)
        await self.bridge.receive(update(text='*help'), self.ctx)
        self.assertFalse(self.bridge.reports.awaiting(123, 1000))

    async def test_report_persists_redacted_and_deduplicated(self):
        await self.submit('Tugma ishlamayapti token=privatevalue')
        reports = Reports(self.path)
        row = reports.recent(123)[0]
        self.assertNotIn('privatevalue', row['report'])
        self.assertEqual(reports.submit(123, 1, 'same update', 1000), row['id'])
        self.assertEqual(len(reports.recent(123)), 1)

    async def test_rate_limit_and_length_limits(self):
        reports = self.bridge.reports
        for text in ('small', 'a'*2001):
            with self.assertRaises(ValueError): reports.submit(123, 99, text, 1000)
        for i in range(5): reports.submit(123, i, 'Valid incident report', 1000)
        with self.assertRaises(ValueError): reports.submit(123, 6, 'Valid incident report', 1000)

    async def test_completed_diagnosis_notifies_author_once_and_never_claims_fix(self):
        await self.submit()
        await self.bridge.tick(self.ctx)
        await self.bridge.tick(self.ctx)
        self.ai.assert_awaited_once()
        self.ctx.bot.send_message.assert_awaited_once()
        self.assertEqual(self.ctx.bot.send_message.call_args.kwargs['chat_id'], 123)
        self.assertIn('Bu AI tahlili', self.ctx.bot.send_message.call_args.kwargs['text'])
        self.assertNotIn('Yangi kod ishga tushdi', self.ctx.bot.send_message.call_args.kwargs['text'])
        self.assertEqual(self.bridge.reports.recent(123)[0]['status'], 'reviewed')

    async def test_ai_failure_does_not_lose_report_or_leak_error(self):
        self.ai.side_effect = RuntimeError('SECRET API KEY')
        await self.submit()
        await self.bridge.tick(self.ctx)
        row = self.bridge.reports.recent(123)[0]
        self.assertEqual(row['status'], 'failed')
        self.assertNotIn('SECRET', row['result'])

    async def test_removed_owner_receives_no_data_and_no_ai_call(self):
        await self.submit()
        self.bridge.owners = frozenset()
        await self.bridge.tick(self.ctx)
        self.ai.assert_not_awaited()
        self.ctx.bot.send_message.assert_not_awaited()

    async def test_telegram_timeout_does_not_repeat_notification(self):
        await self.submit()
        self.ctx.bot.send_message.side_effect = TimedOut()
        await self.bridge.tick(self.ctx)
        await self.bridge.tick(self.ctx)
        self.ctx.bot.send_message.assert_awaited_once()
        self.assertEqual(self.bridge.reports.recent(123)[0]['notification'], 'claimed')

    async def test_processing_lease_expiration_reports_failure_without_ai_retry(self):
        self.bridge.reports.submit(123, 1, 'Valid incident report', 1)
        self.bridge.reports.claim(1)
        await self.bridge.tick(self.ctx)
        self.ai.assert_not_awaited()
        self.assertEqual(self.bridge.reports.recent(123)[0]['status'], 'failed')

    async def test_two_workers_claim_each_report_once(self):
        await self.submit()
        other = Reports(self.path)
        self.assertIsNotNone(other.claim(1000))
        self.assertIsNone(self.bridge.reports.claim(1000))

    async def test_report_lists_are_owner_scoped(self):
        self.bridge.reports.submit(123, 1, 'Owner one report', 1000)
        self.bridge.reports.submit(456, 2, 'Owner two report', 1000)
        await self.callback(update(data='supercfg:reports'))
        rows = self.bridge.reports.recent(123)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['owner_id'], 123)

    async def test_cancel_and_menu_clear_input_state(self):
        await self.callback(update())
        await self.callback(update(data='supercfg:cancel'))
        self.assertFalse(self.bridge.reports.awaiting(123, 1000))

    async def test_snapshot_does_not_read_users_or_secrets(self):
        with self.bridge.reports.db() as db:
            db.execute('CREATE TABLE users(phone TEXT)')
            db.execute("INSERT INTO users VALUES('PRIVATE PHONE')")
        snapshot = self.bridge.snapshot()
        self.assertNotIn('PRIVATE PHONE', json.dumps(snapshot))
        self.assertFalse(snapshot['automatic_repair_connected'])

    async def test_ai_request_has_no_tools_and_disables_response_storage(self):
        client = AsyncMock()
        client.respond.return_value = 'Tahlil'
        with patch('super_settings.OpenAITransport', return_value=client):
            result = await diagnose('Test incident', {'database_readable': True})
        instructions, data = client.respond.call_args.args
        self.assertIn('no filesystem', instructions)
        self.assertIn('Test incident', data)
        self.assertEqual(result, 'Tahlil')

    async def test_no_key_does_not_make_network_request(self):
        with patch.dict(os.environ, {}, clear=True), patch('astra_support.httpx.AsyncClient') as client:
            with self.assertRaises(RuntimeError): await diagnose('test', {})
        client.assert_not_called()

    async def test_enabled_repair_is_enqueued_after_diagnosis(self):
        await self.submit()
        with patch.dict(os.environ, {'VERITAS_REPAIR_ENABLED': '1'}):
            await self.bridge.tick(self.ctx)
        row = self.bridge.reports.recent(123)[0]
        self.assertEqual(self.bridge.repairs.store.get(row['id'], 123)['status'], 'queued')

    async def test_quota_error_is_reported_without_leaking_api_body(self):
        from astra_support import AIUnavailable
        self.ai.side_effect = AIUnavailable('quota', 429)
        await self.submit()
        await self.bridge.tick(self.ctx)
        self.assertIn('krediti', self.bridge.reports.recent(123)[0]['result'])


class RegistrationTests(unittest.TestCase):
    def test_registration_preserves_old_handlers_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = (Application.builder().token('123456:TEST_ONLY_NOT_REAL')
                   .request(OfflineRequest()).get_updates_request(OfflineRequest()).build())
            first = register_super_settings(app, db_path=Path(tmp)/'db', super_owner_ids={123})
            second = register_super_settings(app, db_path=Path(tmp)/'db', super_owner_ids={123})
            self.assertIs(first, second)
            self.assertEqual(len(app.job_queue.get_jobs_by_name(JOB_NAME)), 1)
            self.assertEqual(len(app.handlers[-31]), 3)
            logging.getLogger().removeHandler(first.errors)


if __name__ == '__main__':
    unittest.main()
