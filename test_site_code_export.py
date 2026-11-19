import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock, patch

from telegram.ext import ApplicationHandlerStop
from shared_account import SharedAccount


class SiteCodeExportTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.bridge = SharedAccount.__new__(SharedAccount)
        self.bridge.site = 'https://site.example'
        self.bridge.games = 'https://games.example'
        self.bridge.account_key = 'test'
        self.bot = NS(id=4, send_document=AsyncMock(), send_message=AsyncMock(),
                      get_user_profile_photos=AsyncMock(return_value=NS(photos=[])))
        self.ctx = NS(bot=self.bot, user_data={})
        self.msg = NS(chat_id=7, from_user=NS(id=4), date=datetime.now(timezone.utc),
                      forward_origin=None, text='Lingua saytiga kirish kodi (5 daqiqa)\nABCD-EFGH-JKLM')
        self.update = NS(effective_chat=NS(id=7, type='private'), effective_user=NS(id=7,full_name='Test',username=''),
                         effective_message=NS(reply_text=AsyncMock()), callback_query=NS(from_user=NS(id=7),message=self.msg, answer=AsyncMock()))

    async def test_copy_and_file_contain_only_same_code(self):
        self.update.callback_query = None
        http = MagicMock()
        http.return_value.__aenter__.return_value.post = AsyncMock(return_value=NS(
            raise_for_status=lambda: None, status_code=200, json=lambda: {'code':'ABCDEFGHJKLM'}))
        with patch('shared_account.httpx.AsyncClient', http), self.assertRaises(ApplicationHandlerStop):
            await self.bridge.website(self.update,self.ctx)
        call = self.bot.send_message.await_args
        self.assertEqual(call.args[1],self.msg.text)
        rows = call.kwargs['reply_markup'].inline_keyboard
        self.assertEqual(rows[0][0].web_app.url,self.bridge.site)
        buttons = rows[1]
        self.assertEqual(buttons[0].copy_text.text,'ABCDEFGHJKLM')
        self.assertEqual(buttons[1].callback_data,'veritas_login_save')
        self.update.callback_query = NS(from_user=NS(id=7),message=self.msg,answer=AsyncMock())
        with self.assertRaises(ApplicationHandlerStop):
            await self.bridge.save_login_code(self.update,self.ctx)
        file = self.bot.send_document.await_args
        self.assertEqual(file.args,(7,))
        self.assertEqual(file.kwargs['filename'],'veritas-kirish-kodi.txt')
        self.assertEqual(file.kwargs['document'],b'ABCDEFGHJKLM\n')

    async def test_no_export_in_group_or_after_expiry(self):
        self.update.effective_chat.type='group'
        with self.assertRaises(ApplicationHandlerStop):
            await self.bridge.save_login_code(self.update,self.ctx)
        self.update.effective_chat.type='private'
        self.msg.date -= timedelta(minutes=6)
        with self.assertRaises(ApplicationHandlerStop):
            await self.bridge.save_login_code(self.update,self.ctx)
        self.bot.send_document.assert_not_awaited()
