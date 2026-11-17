"""Private owner commands reach the durable repair worker, not conversational AI."""
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, patch

from telegram.error import TimedOut
from telegram.ext import ApplicationHandlerStop
from super_settings import SuperSettings
from test_super_settings import update


COMMAND = 'Qayta tekshir va xatolarini tuzatib tekshir va deploy qil'


class NaturalOwnerCommandTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'bot.db'
        self.app = NS(bot_data={}, job_queue=None, running=False)
        self.ai = AsyncMock(side_effect=AssertionError('No advisory call for a repair'))
        self.bridge = SuperSettings(self.path, {123}, self.app, ai=self.ai, clock=lambda:1000)
        self.bridge.chat.ai = AsyncMock()
        self.ctx = NS(bot=NS(send_message=AsyncMock()))
        env = patch.dict(os.environ, {'VERITAS_AUTOREPAIR_ENABLED':'1',
                                     'VERITAS_MAINTAINER_URL':'http://maintainer.railway.internal'})
        env.start()
        self.addCleanup(env.stop)

    async def receive_task(self, text=COMMAND, message_id=1):
        up = update(text=text, message_id=message_id)
        with self.assertRaises(ApplicationHandlerStop):
            await self.bridge.receive(up, self.ctx)
        return up

    def chat_count(self):
        with self.bridge.reports.db() as db:
            return db.execute('SELECT COUNT(*) FROM super_astra_turns').fetchone()[0]

    async def test_plain_command_reaches_remote_repair_without_button_or_chat_ai(self):
        up = await self.receive_task()
        self.assertIn('Murojaat #1 saqlandi', up.effective_message.reply_text.call_args.args[0])
        await self.bridge.tick(self.ctx)
        remote = AsyncMock(side_effect=[{'ok':True,'id':1},
            {'ok':True,'status':'ci','message':'Mustaqil testlar ishlayapti'}])
        with patch('maintainer_client.request', new=remote):
            await self.bridge.remote_tick(self.ctx)
        self.assertEqual(remote.call_args_list[0].args[0], '/jobs')
        self.assertIn(COMMAND, remote.call_args_list[0].args[1]['report'])
        self.assertEqual(self.bridge.reports.recent(123)[0]['status'], 'repairing')
        self.ai.assert_not_awaited()
        self.bridge.chat.ai.assert_not_awaited()
        self.assertEqual(self.chat_count(), 0)

    async def test_explicit_command_takes_priority_over_active_astra_chat(self):
        self.bridge.chat.open(123)
        await self.receive_task('Botni tuzat va main ga joyla')
        self.assertFalse(self.bridge.chat.awaiting(123))
        self.assertEqual(self.chat_count(), 0)
        self.assertEqual(len(self.bridge.reports.recent(123)), 1)

    async def test_command_variants_are_accepted(self):
        for n, text in enumerate(('Botni tekshirib tuzating.',
                                  'Botni to‘g‘rilab ber',
                                  'Botni tuzatib ishga tushir!',
                                  'Qayta tekshirib DEPLOY QILING, iltimos')):
            with self.subTest(text=text):
                await self.receive_task(text, n+1)
        self.assertEqual(len(self.bridge.reports.recent(123)), 4)

    async def test_nonowners_groups_and_revoked_owners_cannot_trigger_repairs(self):
        for owner, kind in ((999,'private'), (123,'group'), (123,'supergroup'), (123,'channel')):
            up = update(owner=owner, chat_type=kind, text=COMMAND)
            await self.bridge.receive(up, self.ctx)
            up.effective_message.reply_text.assert_not_awaited()
        self.bridge.owners = frozenset()
        await self.bridge.receive(update(text=COMMAND), self.ctx)
        self.assertEqual(self.bridge.reports.recent(123), [])
        self.assertEqual(self.bridge.reports.recent(999), [])

    async def test_questions_negations_examples_and_unrelated_text_are_not_tasks(self):
        for text in ('Salom', 'Botda xato chiqyapti', '*help', '/start', None,
                     'Deploy nima?', 'Botni qanday tuzat va deploy qil',
                     'Botni tuzat va deploy qilma', 'Botni tuzatmang, deploy qiling',
                     'Botni to‘g‘rilamang, deploy qiling',
                     'Botni tuzat, main ga joylama', 'Botni tuzat va deploy qil demadim',
                     'Misol: botni tuzat va deploy qil',
                     '"Botni tuzat va deploy qil"', '`Botni tuzat va deploy qil`',
                     'Botni tuzat va deploy qil deb yozdim', 'Matnimni tuzat',
                     'Botni tuzat va deploy qil?'):
            with self.subTest(text=text):
                up = update(text=text)
                await self.bridge.receive(up, self.ctx)
                up.effective_message.reply_text.assert_not_awaited()
        self.assertEqual(self.bridge.reports.recent(123), [])

    async def test_ordinary_question_stays_in_active_chat(self):
        self.bridge.chat.open(123)
        up = await self.receive_task('Botni qanday deploy qilish mumkin?')
        self.assertIn('Astra javob', up.effective_message.reply_text.call_args.args[0])
        self.assertTrue(self.bridge.chat.awaiting(123))
        self.assertEqual(self.bridge.reports.recent(123), [])
        self.assertEqual(self.chat_count(), 1)

    async def test_forwarded_or_quoted_messages_need_explicit_report_mode(self):
        for attr in ('forward_origin', 'quote'):
            up = update(text=COMMAND)
            setattr(up.effective_message, attr, NS())
            await self.bridge.receive(up, self.ctx)
            up.effective_message.reply_text.assert_not_awaited()
        self.assertEqual(self.bridge.reports.recent(123), [])

    async def test_replayed_update_remains_one_task_after_restart(self):
        await self.receive_task()
        self.bridge = SuperSettings(self.path, {123}, self.app, ai=self.ai, clock=lambda:1010)
        await self.receive_task()
        await self.bridge.tick(self.ctx)
        await self.bridge.tick(self.ctx)
        self.assertEqual(len(self.bridge.reports.recent(123)), 1)
        with self.bridge.reports.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM super_remote_outbox').fetchone()[0], 1)

    async def test_monthly_spending_replaces_daily_report_count_for_remote_repairs(self):
        for n in range(5):
            await self.receive_task(message_id=n+1)
        accepted = await self.receive_task(message_id=6)
        self.assertIn('Murojaat #6 saqlandi', accepted.effective_message.reply_text.call_args.args[0])
        with self.bridge.reports.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM super_incidents').fetchone()[0],6)

    async def test_feature_commands_reach_repair_worker(self):
        for n,text in enumerate(('Zakovatda javoblarni qabul qilishni yaxshila',
                                 'Menyuga yordam tugmasini qo‘sh',
                                 'Reklama matnini o‘zgartir',
                                 'Botga xarajatlar hisobini qo‘shib ber')):
            await self.receive_task(text,message_id=n+1)
        self.assertEqual(len(self.bridge.reports.recent(123)),4)
        self.bridge.chat.ai.assert_not_awaited()

    async def test_negated_feature_edits_are_not_authorization(self):
        for text in ('Tugmani o‘zgartirma, deploy qil', 'Reklamani qo‘shmang, botni tekshirib tuzat',
                     'Menyuni almashtirma, botni tuzat'):
            await self.bridge.receive(update(text=text),self.ctx)
        self.assertEqual(self.bridge.reports.recent(123),[])

    async def test_plain_command_redacts_secrets_before_persistence(self):
        await self.receive_task('token=synthetic-secret Botni tuzat va deploy qil')
        self.assertNotIn('synthetic-secret', self.bridge.reports.recent(123)[0]['report'])

    async def test_ack_timeout_still_stops_legacy_handlers_and_keeps_task(self):
        up = update(text=COMMAND)
        up.effective_message.reply_text.side_effect = TimedOut()
        with self.assertRaises(ApplicationHandlerStop):
            await self.bridge.receive(up, self.ctx)
        self.assertEqual(len(self.bridge.reports.recent(123)), 1)
        self.assertEqual(self.chat_count(), 0)

    async def test_button_based_reports_still_accept_freeform_descriptions(self):
        self.bridge.reports.arm(123, 1000)
        await self.receive_task('Test tugmasi ishlamayapti')
        self.assertFalse(self.bridge.reports.awaiting(123, 1000))
        self.assertEqual(len(self.bridge.reports.recent(123)), 1)


if __name__ == '__main__':
    unittest.main()
