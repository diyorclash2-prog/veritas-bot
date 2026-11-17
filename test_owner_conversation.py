import asyncio
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, patch
from telegram.error import TimedOut
from telegram.ext import ApplicationHandlerStop
from owner_conversation import OwnerConversation, converse, JOB_NAME
from super_settings import SuperSettings, menu
from test_super_settings import update


class OwnerChatTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.now = 10000
        self.app = NS(bot_data={},job_queue=NS(get_jobs_by_name=lambda name:[]))
        self.bridge = SuperSettings(Path(self.tmp.name)/'db',{123,456},self.app,clock=lambda:self.now)
        self.chat = self.bridge.chat
        self.chat.ai = AsyncMock(return_value='Ha, tushundim. Davom eting.')
        self.ctx = NS(bot=NS(send_message=AsyncMock()),args=None)

    async def callback(self, action, **kwargs):
        up = update(data='supercfg:'+action,**kwargs)
        with self.assertRaises(ApplicationHandlerStop): await self.bridge.callback(up,self.ctx)
        return up

    async def send(self, text='Qanday ishlaydi?', **kwargs):
        up = update(text=text,**kwargs)
        with self.assertRaises(ApplicationHandlerStop): await self.bridge.receive(up,self.ctx)
        return up

    async def test_chat_and_command_buttons_are_present(self):
        data = [b.callback_data for row in menu().inline_keyboard for b in row]
        for action in ('chat','report','chat_history','chat_clear','cancel'):
            self.assertIn('supercfg:'+action,data)

    async def test_callback_denies_nonowners_and_groups(self):
        for owner,kind in ((999,'private'),(123,'group'),(123,'supergroup')):
            up = await self.callback('chat',owner=owner,chat_type=kind)
            self.assertFalse(self.chat.awaiting(owner))
            up.effective_message.reply_text.assert_not_awaited()

    async def test_receive_passes_through_without_private_owner_session(self):
        self.chat.open(123)
        for owner,kind in ((999,'private'),(123,'group'),(456,'private')):
            await self.bridge.receive(update(owner=owner,chat_type=kind),self.ctx)
        self.chat.ai.assert_not_awaited()

    async def test_receiving_is_nonblocking_and_worker_replies_only_to_author(self):
        await self.callback('chat'); await self.send()
        self.chat.ai.assert_not_awaited()
        await self.bridge.chat_tick(self.ctx)
        self.ctx.bot.send_message.assert_awaited_once()
        self.assertEqual(self.ctx.bot.send_message.call_args.kwargs['chat_id'],123)
        self.assertIsNone(self.ctx.bot.send_message.call_args.kwargs['parse_mode'])
        self.assertTrue(self.chat.awaiting(123))

    async def test_followup_has_private_previous_context(self):
        self.chat.open(456); self.chat.submit(456,1,'OTHER OWNER CONTEXT')
        await self.bridge.chat_tick(self.ctx)
        await self.callback('chat'); await self.send('Birinchi savolim',message_id=1)
        await self.bridge.chat_tick(self.ctx)
        await self.send('Shuni tushuntiring',message_id=2)
        await self.bridge.chat_tick(self.ctx)
        history,snapshot = self.chat.ai.call_args.args
        self.assertEqual(len(history),3)
        self.assertIn('Birinchi savolim',json.dumps(history))
        self.assertNotIn('OTHER OWNER',json.dumps(history))

    async def test_secrets_redacted_before_storage_and_response(self):
        with patch.dict(os.environ,{'API_KEY':'secret-value-for-chat-test'}):
            await self.callback('chat')
            await self.send('token=hidden secret-value-for-chat-test +1 555 123 4567')
            self.chat.ai.return_value='secret-value-for-chat-test token=other'
            await self.bridge.chat_tick(self.ctx)
            rendered=json.dumps(self.chat.history(123))
            for value in ('hidden','secret-value-for-chat-test','555','other'):
                self.assertNotIn(value,rendered)

    async def test_chat_does_not_enqueue_repairs_even_when_enabled(self):
        await self.callback('chat'); await self.send('Botni tuzat va main ga joyla')
        with patch.dict(os.environ,{'VERITAS_AUTOREPAIR_ENABLED':'1'}):
            await self.bridge.chat_tick(self.ctx)
        self.assertEqual(self.bridge.reports.recent(123),[])
        with self.bridge.reports.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM super_remote_outbox').fetchone()[0],0)

    async def test_command_button_switches_from_chat_to_durable_task(self):
        await self.callback('chat'); await self.callback('report')
        self.assertFalse(self.chat.awaiting(123))
        await self.send('Reklama tugmasidagi yozuvni tekshirib tuzat')
        self.assertEqual(len(self.bridge.reports.recent(123)),1)
        self.chat.ai.assert_not_awaited()

    async def test_chat_button_cancels_task_input(self):
        await self.callback('report'); await self.callback('chat')
        self.assertFalse(self.bridge.reports.awaiting(123,self.now))

    async def test_cancel_original_commands_and_session_expiration(self):
        await self.callback('chat'); await self.callback('cancel')
        self.assertFalse(self.chat.awaiting(123))
        await self.callback('chat')
        await self.bridge.receive(update(text='*help'),self.ctx)
        self.assertFalse(self.chat.awaiting(123))
        self.chat.open(123); self.now+=1801
        await self.bridge.receive(update(),self.ctx)
        self.chat.ai.assert_not_awaited()

    async def test_restart_preserves_queue_and_deduplicates_update(self):
        self.chat.open(123)
        ident=self.chat.submit(123,1,'Savolim bor')
        reopened=OwnerConversation(self.bridge.reports,lambda:{123},lambda:{},clock=lambda:self.now,ai=self.chat.ai)
        self.assertEqual(reopened.submit(123,1,'Savolim bor'),ident)
        await reopened.tick(self.ctx,menu()); await reopened.tick(self.ctx,menu())
        self.chat.ai.assert_awaited_once()

    async def test_concurrent_queued_turn_and_length_are_limited(self):
        self.chat.open(123)
        for text in (' ', 'a'*2001):
            with self.assertRaises(ValueError): self.chat.submit(123,1,text)
        self.chat.submit(123,1,'Savolim bor')
        with self.assertRaises(ValueError): self.chat.submit(123,2,'Yana savol')

    async def test_history_is_bounded_and_old_history_expires(self):
        self.chat.open(123)
        for n in range(8):
            self.chat.submit(123,n,'Savol '+str(n)); await self.chat.tick(self.ctx,menu())
        self.assertEqual(len(self.chat.history(123)),12)
        self.now+=86401
        self.assertEqual(self.chat.history(123),[])

    async def test_hourly_limit_is_persistent(self):
        self.chat.open(123)
        for n in range(20):
            self.chat.submit(123,n,'Savol '+str(n)); await self.chat.tick(self.ctx,menu())
        with self.assertRaisesRegex(ValueError,'soatlik'): self.chat.submit(123,21,'Yana savol')

    async def test_clear_history_is_owner_scoped(self):
        for owner in (123,456):
            self.chat.open(owner); self.chat.submit(owner,1,'Savolim bor'); await self.chat.tick(self.ctx,menu())
        await self.callback('chat_clear')
        self.assertEqual(self.chat.history(123),[])
        self.assertEqual(len(self.chat.history(456)),2)

    async def test_revoked_owner_never_gets_ai_or_notification(self):
        self.chat.open(123); self.chat.submit(123,1,'Savolim bor')
        self.bridge.owners=frozenset()
        await self.chat.tick(self.ctx,menu())
        self.chat.ai.assert_not_awaited(); self.ctx.bot.send_message.assert_not_awaited()

    async def test_timeout_delivery_is_not_duplicated_and_history_remains(self):
        self.chat.open(123); self.chat.submit(123,1,'Savolim bor')
        self.ctx.bot.send_message.side_effect=TimedOut()
        await self.chat.tick(self.ctx,menu()); await self.chat.tick(self.ctx,menu())
        self.ctx.bot.send_message.assert_awaited_once()
        self.assertEqual(len(self.chat.history(123)),2)

    async def test_api_error_is_sanitized_and_does_not_retry_paid_request(self):
        self.chat.open(123); self.chat.submit(123,1,'Savolim bor')
        self.chat.ai.side_effect=RuntimeError('PRIVATE RESPONSE')
        await self.chat.tick(self.ctx,menu()); await self.chat.tick(self.ctx,menu())
        self.chat.ai.assert_awaited_once()
        self.assertNotIn('PRIVATE',self.ctx.bot.send_message.call_args.kwargs['text'])

    async def test_interrupted_processing_reports_failure_without_retry(self):
        self.chat.open(123); ident=self.chat.submit(123,1,'Savolim bor')
        with self.bridge.reports.db() as db:
            db.execute("UPDATE super_astra_turns SET status='processing',started=? WHERE id=?",(self.now-181,ident))
        await self.chat.tick(self.ctx,menu())
        self.chat.ai.assert_not_awaited()
        self.assertIn('uzildi',self.ctx.bot.send_message.call_args.kwargs['text'])

    async def test_conversation_prompt_explicitly_has_no_execution_tools(self):
        api=AsyncMock(); api.respond.return_value='Javob'
        with patch('owner_conversation.OpenAITransport',return_value=api):
            self.assertEqual(await converse([{'role':'user','content':'Salom'}],{}),'Javob')
        instructions,payload=api.respond.call_args.args
        self.assertIn('no filesystem',instructions)
        self.assertIn('Buyruq / tuzatish',instructions)
        self.assertIn('Salom',payload)


if __name__=='__main__': unittest.main()
