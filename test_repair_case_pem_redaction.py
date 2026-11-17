"""Regression coverage using synthetic, non-credential PEM bodies only."""
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from owner_conversation import OwnerConversation
from super_settings import Reports, redact


LABELS = ('RSA PRIVATE KEY', 'EC PRIVATE KEY', 'OPENSSH PRIVATE KEY',
          'ENCRYPTED PRIVATE KEY', 'PRIVATE KEY')
BODY = 'VERITAS_SYNTHETIC_KEY_BODY'


def pem(label, newline='\n'):
    return newline.join(('-----BEGIN ' + label + '-----', BODY,
                         'SYNTHETIC_SECOND_LINE', '-----END ' + label + '-----'))


class PemRedactionTests(unittest.TestCase):
    def test_complete_blocks_and_surrounding_text(self):
        with patch.dict(os.environ, {}, clear=True):
            for label in LABELS:
                for newline in ('\n', '\r\n'):
                    with self.subTest(label=label, newline=newline):
                        text = 'Before' + newline + pem(label, newline) + newline + 'After'
                        self.assertEqual(redact(text),
                                         'Before' + newline + '[YASHIRILDI]' + newline + 'After')
            reproduction = ('Before\n-----BEGIN RSA PRIVATE KEY-----\n' + BODY +
                            '\n-----END RSA PRIVATE KEY-----\nAfter')
            self.assertEqual(redact(reproduction), 'Before\n[YASHIRILDI]\nAfter')

    def test_multiple_blocks_do_not_consume_intervening_text(self):
        blocks = [pem(label, '\r\n' if i % 2 else '\n')
                  for i, label in enumerate(LABELS)]
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(redact('Before\n' + '\nOrdinary text\n'.join(blocks) + '\nAfter'),
                             'Before\n' + '\nOrdinary text\n'.join(
                                 ['[YASHIRILDI]'] * len(blocks)) + '\nAfter')

    def test_known_secret_cannot_break_pem_detection(self):
        with patch.dict(os.environ, {'TEST_API_KEY': 'RSA PRIVATE KEY'}, clear=True):
            self.assertEqual(redact('Before\n' + pem('RSA PRIVATE KEY') + '\nAfter'),
                             'Before\n[YASHIRILDI]\nAfter')

    def test_existing_redaction_and_nonprivate_pem_are_preserved(self):
        public = '-----BEGIN PUBLIC KEY-----\nSYNTHETIC_PUBLIC_BODY\n-----END PUBLIC KEY-----'
        with patch.dict(os.environ, {'TEST_API_KEY': 'synthetic-known-value'}, clear=True):
            text = (public + '\n' + pem('EC PRIVATE KEY') +
                    '\nsynthetic-known-value password=synthetic-password https://example.org')
            self.assertEqual(redact(text), public + '\n[YASHIRILDI]\n'
                             '[MAXFIY] [YASHIRILDI] [YASHIRILDI]')


class PemStorageTests(unittest.IsolatedAsyncioTestCase):
    async def test_reports_and_chat_redact_before_storage_ai_and_delivery(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            reports = Reports(Path(tmp) / 'test.db')
            text = 'Before\n' + pem('RSA PRIVATE KEY') + '\nAfter'
            expected = 'Before\n[YASHIRILDI]\nAfter'
            reports.submit(123, 1, text, 1000)
            self.assertEqual(reports.recent(123)[0]['report'], expected)

            answer = 'Reply\r\n' + pem('OPENSSH PRIVATE KEY', '\r\n') + '\r\nEnd'
            expected_answer = 'Reply\r\n[YASHIRILDI]\r\nEnd'
            ai = AsyncMock(return_value=answer)
            chat = OwnerConversation(reports, lambda: {123}, lambda: {},
                                     ai=ai, clock=lambda: 1000)
            chat.open(123)
            ident = chat.submit(123, 1, text)
            with reports.db() as db:
                row = db.execute('SELECT prompt FROM super_astra_turns WHERE id=?',
                                 (ident,)).fetchone()
            self.assertEqual(row['prompt'], expected)
            ai.assert_not_awaited()
            context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()))
            await chat.tick(context, None)
            ai.assert_awaited_once_with([{'role': 'user', 'content': expected}], {})
            self.assertEqual(chat.history(123), [
                {'role': 'user', 'content': expected},
                {'role': 'assistant', 'content': expected_answer}])
            context.bot.send_message.assert_awaited_once_with(
                chat_id=123, text='💬 Astra\n\n' + expected_answer,
                parse_mode=None, reply_markup=None)
            self.assertTrue(chat.awaiting(123))


if __name__ == '__main__':
    unittest.main()
