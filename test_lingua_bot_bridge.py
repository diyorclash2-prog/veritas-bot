"""Offline tests: no live Telegram calls, tokens, phone numbers or user databases."""
import asyncio
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, patch

from telegram import Chat, ChatMemberAdministrator, ChatMemberMember, ChatMemberOwner, User
from telegram.error import BadRequest, Forbidden, RetryAfter, TimedOut
from telegram.ext import Application, ApplicationHandlerStop, CommandHandler
from telegram.request import BaseRequest

from lingua_bot_bridge import (Config, LinguaBridge, Store, DEFAULT_URL, STATE_KEY, JOB_NAME,
                               ad_text, keyboard, register_lingua_handlers, schedule, validate_url)


def fake_bot():
    async def chat(ref):
        return NS(id=ref if isinstance(ref, int) else -100000001, title='Test channel', type='channel')
    return NS(id=900001, get_chat=AsyncMock(side_effect=chat),
              get_chat_member=AsyncMock(return_value=NS(status='administrator', can_post_messages=True)),
              send_message=AsyncMock(return_value=NS(message_id=42)))


def fake_update(user_id=100001, chat_type='private'):
    return NS(effective_message=NS(reply_text=AsyncMock()), effective_user=NS(id=user_id),
              effective_chat=NS(id=user_id, type=chat_type), my_chat_member=None, channel_post=None)


class ConfigurationTests(unittest.TestCase):
    def test_public_https_link(self):
        self.assertEqual(validate_url('  https://example.org/lingua?x=1  '), 'https://example.org/lingua?x=1')

    def test_unsafe_links_rejected(self):
        for url in ('http://example.org', 'javascript:alert(1)', 'https://u:p@example.org',
                    'https://localhost', 'https://127.0.0.1', 'https://[::1]', 'https://a b.org'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_url(url)

    def test_empty_url_disables_launcher(self):
        self.assertEqual(validate_url(''), '')

    def test_invalid_schedule(self):
        for hour, tz in [('24:00', 'UTC'), ('1:20', 'UTC'), ('19:65', 'UTC'), ('19:00', 'Not/AZone')]:
            with self.subTest(hour=hour, tz=tz), self.assertRaises(ValueError):
                schedule(hour, tz)

    def test_environment_defaults_and_override(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(Config.from_env(), Config())
        with patch.dict(os.environ, {'VL_PUBLIC_URL': 'https://example.org', 'VL_LINGUA_AD_TIME': '20:30',
                                     'VL_LINGUA_AD_TZ': 'Asia/Tashkent', 'VL_LINGUA_ADS_ENABLED': '1'}, clear=True):
            self.assertEqual(Config.from_env(), Config('https://example.org', '20:30', 'Asia/Tashkent', True))

    def test_advertisement_uses_current_account(self):
        self.assertIn('profilingizga kiring', ad_text())
        self.assertNotIn('shu brauzerda', ad_text())
        self.assertLess(len(ad_text()), 4096)

    def test_channel_compatible_url_button(self):
        button = keyboard(DEFAULT_URL).inline_keyboard[0][0]
        self.assertEqual(button.url, DEFAULT_URL)
        self.assertIsNone(button.web_app)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'test.sqlite3'
        self.store = Store(self.path, Config(enabled=True))

    def test_existing_data_is_preserved_and_only_channel_references_seeded(self):
        with sqlite3.connect(self.path) as db:
            db.executescript('''
                CREATE TABLE users(user_id INTEGER, points INTEGER);
                INSERT INTO users VALUES(123,500);
                CREATE TABLE groups(chat_id INTEGER);
                INSERT INTO groups VALUES(-999);
                CREATE TABLE rebus_channels(channel_id INTEGER);
                INSERT INTO rebus_channels VALUES(-1001),(-1001),(0),(123);
                CREATE TABLE book_channel_links(channel_id INTEGER);
                INSERT INTO book_channel_links VALUES(-1002),(-1001);
                CREATE TABLE rebuses(id INTEGER);
            ''')
        self.store.seed_existing_channels()
        self.store.seed_existing_channels()
        self.assertEqual({r['chat_id'] for r in self.store.channels()}, {-1001, -1002})
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute('SELECT * FROM users').fetchall(), [(123, 500)])
            self.assertEqual(db.execute('SELECT * FROM groups').fetchall(), [(-999,)])

    def test_opt_out_survives_activity_and_rediscovery(self):
        self.store.observe(-1001, 'Original')
        self.store.disable_channel(-1001)
        self.store.observe(-1001, 'Renamed')
        self.store.seed_existing_channels()
        self.assertEqual(self.store.channels()[0]['enabled'], 0)
        self.store.observe(-1001, 'Renamed', enable=True)
        self.assertEqual(self.store.channels()[0]['enabled'], 1)

    def test_config_survives_restart_and_new_environment(self):
        self.store.configure(enabled=False, hour='21:45', tz='Asia/Tashkent')
        reloaded = Store(self.path, Config(enabled=True))
        self.assertEqual((reloaded.settings()['enabled'], reloaded.settings()['hour'], reloaded.settings()['tz']),
                         (0, '21:45', 'Asia/Tashkent'))

    def test_positive_ids_and_bools_ignored(self):
        for value in (1, 0, True, '-123'):
            self.store.observe(value)
        self.assertEqual(self.store.channels(), [])

    def test_claim_is_exclusive_across_instances(self):
        self.store.observe(-1001)
        other = Store(self.path, Config())
        self.assertTrue(self.store.claim(-1001, '2026-11-16', 500))
        self.assertFalse(other.claim(-1001, '2026-11-16', 501))
        self.assertTrue(other.claim(-1001, '2026-11-17', 502))

    def test_claim_checks_current_opt_out_and_global_off(self):
        self.store.observe(-1001)
        self.store.configure(enabled=False)
        self.assertFalse(self.store.claim(-1001, '2026-11-16', 500))
        self.store.configure(enabled=True)
        self.store.disable_channel(-1001)
        self.assertFalse(self.store.claim(-1001, '2026-11-16', 500))

    def test_global_cooldown_is_persistent_and_not_shortened(self):
        self.store.observe(-1001)
        self.store.defer(2000)
        self.store.defer(1000)
        reloaded = Store(self.path, Config())
        self.assertTrue(reloaded.cooling_down(1999))
        self.assertFalse(reloaded.claim(-1001, '2026-11-16', 1999))
        self.assertTrue(reloaded.claim(-1001, '2026-11-16', 2000))


class BridgeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'test.sqlite3'
        self.now = datetime(2026, 11, 17, 0, 1, tzinfo=timezone.utc)  # Nov 16, 19:01 New York
        self.config = Config(enabled=True)
        self.bridge = self.new_bridge()
        self.bot = fake_bot()
        self.context = NS(bot=self.bot, args=[])
        self.bridge.store.observe(-1001, 'Channel one')

    def new_bridge(self):
        return LinguaBridge(self.path, {100001}, self.config, clock=lambda: self.now, pause=AsyncMock())

    async def admin(self, *args, user_id=100001, chat_type='private'):
        update = fake_update(user_id, chat_type)
        self.context.args = args
        with self.assertRaises(ApplicationHandlerStop):
            await self.bridge.admin(update, self.context)
        return update.effective_message.reply_text

    async def test_before_scheduled_time_does_not_send(self):
        self.now = self.now.replace(hour=23, minute=59) - timedelta(days=1)
        await self.bridge.tick(self.context)
        self.bot.send_message.assert_not_awaited()

    async def test_once_per_day_after_restart_then_next_day(self):
        await self.bridge.tick(self.context)
        await self.bridge.tick(self.context)
        await self.new_bridge().tick(self.context)
        self.assertEqual(self.bot.send_message.await_count, 1)
        self.now += timedelta(days=1)
        await self.new_bridge().tick(self.context)
        self.assertEqual(self.bot.send_message.await_count, 2)

    async def test_missed_days_do_not_create_backlog(self):
        self.now += timedelta(days=20)
        await self.bridge.tick(self.context)
        self.bot.send_message.assert_awaited_once()

    async def test_disabled_by_default(self):
        bridge = LinguaBridge(Path(self.tmp.name) / 'default.sqlite3', {100001}, Config(), pause=AsyncMock())
        bridge.store.observe(-1001)
        await bridge.tick(self.context)
        self.bot.send_message.assert_not_awaited()

    async def test_empty_url_blocks_send(self):
        bridge = LinguaBridge(self.path, {100001}, Config(url=''), clock=lambda: self.now, pause=AsyncMock())
        await bridge.tick(self.context)
        self.bot.send_message.assert_not_awaited()

    async def test_two_workers_claim_one_delivery(self):
        await asyncio.gather(self.bridge.tick(self.context), self.new_bridge().tick(self.context))
        self.bot.send_message.assert_awaited_once()

    async def test_overlapping_tick_in_same_worker_is_skipped(self):
        async with self.bridge.lock:
            await self.bridge.tick(self.context)
        self.bot.send_message.assert_not_awaited()

    async def test_uncertain_timeout_is_not_retried(self):
        self.bot.send_message.side_effect = TimedOut()
        await self.bridge.tick(self.context)
        await self.new_bridge().tick(self.context)
        self.bot.send_message.assert_awaited_once()
        self.assertEqual(self.bridge.store.counts('2026-11-16'), {'uncertain': 1})

    async def test_crash_after_claim_suppresses_same_day_retry(self):
        self.bridge.store.claim(-1001, '2026-11-16', int(self.now.timestamp()))
        await self.new_bridge().tick(self.context)
        self.bot.send_message.assert_not_awaited()

    async def test_retry_after_blocks_all_channels_and_survives_restart(self):
        self.bridge.store.observe(-1002)
        self.bot.send_message.side_effect = [RetryAfter(600), NS(message_id=42), NS(message_id=43)]
        await self.bridge.tick(self.context)
        self.assertEqual(self.bot.send_message.await_count, 1)
        self.now += timedelta(seconds=60)
        await self.new_bridge().tick(self.context)
        self.assertEqual(self.bot.send_message.await_count, 1)
        self.now += timedelta(seconds=542)
        await self.new_bridge().tick(self.context)
        self.assertEqual(self.bot.send_message.await_count, 3)
        self.assertEqual(self.bridge.store.counts('2026-11-16'), {'sent': 2})

    async def test_retry_after_permission_check_blocks_entire_batch(self):
        self.bridge.store.observe(-1002)
        self.bot.get_chat.side_effect = RetryAfter(timedelta(seconds=300))
        await self.bridge.tick(self.context)
        self.now += timedelta(seconds=60)
        await self.new_bridge().tick(self.context)
        self.assertEqual(self.bot.get_chat.await_count, 1)
        self.bot.send_message.assert_not_awaited()

    async def test_rate_limit_retries_are_bounded(self):
        self.bot.send_message.side_effect = RetryAfter(1)
        for _ in range(5):
            await self.bridge.tick(self.context)
            self.now += timedelta(seconds=61)
        self.assertEqual(self.bot.send_message.await_count, 3)

    async def test_forbidden_deactivates_one_channel_and_continues(self):
        self.bridge.store.observe(-1002)
        self.bot.send_message.side_effect = [Forbidden('No access'), NS(message_id=43)]
        await self.bridge.tick(self.context)
        self.assertEqual(self.bot.send_message.await_count, 2)
        self.assertEqual(self.bridge.store.channels()[0]['active'], 0)
        self.assertEqual(self.bridge.store.counts('2026-11-16'), {'failed': 1, 'sent': 1})

    async def test_invalid_permission_skips_channel(self):
        self.bot.get_chat_member.return_value = NS(status='administrator', can_post_messages=False)
        await self.bridge.tick(self.context)
        self.bot.send_message.assert_not_awaited()
        self.assertEqual(self.bridge.store.channels()[0]['active'], 0)

    async def test_group_reference_now_receives_ad_once(self):
        self.bot.get_chat.side_effect = None
        self.bot.get_chat.return_value = NS(id=-1001, type='supergroup', title='Group')
        await self.bridge.tick(self.context)
        await self.new_bridge().tick(self.context)
        self.bot.send_message.assert_awaited_once()

    async def test_private_chat_reference_is_still_rejected(self):
        self.bot.get_chat.side_effect = None
        self.bot.get_chat.return_value = NS(id=123, type='private', title='Private')
        await self.bridge.tick(self.context)
        self.bot.send_message.assert_not_awaited()

    async def test_member_group_permissions_and_removed_membership(self):
        for status, permission, expected in [('member', True, 1), ('member', False, 0),
                                              ('left', True, 0), ('kicked', True, 0)]:
            with self.subTest(status=status, permission=permission):
                self.bridge.store.observe(-1001)
                self.bot.get_chat.side_effect = None
                self.bot.get_chat.return_value = NS(id=-1001, type='group', title='Group',
                                                    permissions=NS(can_send_messages=permission))
                self.bot.get_chat_member.return_value = NS(status=status)
                self.bot.send_message.reset_mock()
                self.now += timedelta(days=1)
                await self.bridge.tick(self.context)
                self.assertEqual(self.bot.send_message.await_count, expected)

    async def test_restricted_group_requires_membership_and_permission(self):
        group = NS(type='supergroup')
        for joined in (True, False):
            for permission in (True, False):
                member = NS(status='restricted', is_member=joined, can_send_messages=permission)
                self.assertEqual(self.bridge.can_send(group, member), joined and permission)

    async def test_all_existing_groups_seeded_and_opt_out_preserved(self):
        with self.bridge.store.db() as db:
            db.executescript("CREATE TABLE groups(chat_id INTEGER); INSERT INTO groups VALUES(-55),(-66),(123);")
        self.bridge.store.seed_existing_chats()
        self.bridge.store.disable_channel(-55)
        self.bridge.store.seed_existing_chats()
        rows = {r['chat_id']: r for r in self.bridge.store.channels()}
        self.assertEqual(set(rows), {-1001, -55, -66})
        self.assertEqual(rows[-55]['enabled'], 0)
        self.assertEqual(rows[-66]['chat_type'], 'supergroup')

    async def test_group_observation_does_not_stop_existing_handlers(self):
        update = fake_update()
        update.effective_chat = NS(id=-44, type='group', title='Group')
        await self.bridge.track_group(update, self.context)
        self.assertIn(-44, {r['chat_id'] for r in self.bridge.store.channels()})
        update.my_chat_member = NS(chat=update.effective_chat, new_chat_member=NS(status='left'))
        await self.bridge.track_membership(update, self.context)
        rows = {r['chat_id']: r for r in self.bridge.store.channels()}
        self.assertEqual(rows[-44]['active'], 0)

    async def test_group_migration_preserves_delivered_day_and_opt_out(self):
        self.bridge.store.claim(-1001, '2026-11-16', 1)
        self.bridge.store.outcome(-1001, '2026-11-16', 'sent')
        self.bridge.store.disable_channel(-1001)
        self.bridge.store.migrate_chat(-1001, -1009)
        self.bridge.store.migrate_chat(-1001, -1009)
        rows = {r['chat_id']: r for r in self.bridge.store.channels()}
        self.assertEqual(rows[-1009]['enabled'], 0)
        self.assertEqual(rows[-1001]['active'], 0)
        self.bridge.store.observe(-1009, enable=True)
        self.assertFalse(self.bridge.store.claim(-1009, '2026-11-16', 2))

    async def test_repeated_migration_does_not_disable_enabled_destination(self):
        self.bridge.store.migrate_chat(-1001, -1009)
        self.bridge.store.migrate_chat(-1001, -1009)
        rows = {r['chat_id']: r for r in self.bridge.store.channels()}
        self.assertEqual(rows[-1009]['enabled'], 1)

    async def test_migration_merges_old_sent_with_new_retry_without_duplicate(self):
        self.bridge.store.observe(-1009)
        for chat in (-1001, -1009):
            self.bridge.store.claim(chat, '2026-11-16', 1)
        self.bridge.store.outcome(-1001, '2026-11-16', 'sent')
        self.bridge.store.outcome(-1009, '2026-11-16', 'retry', retry_at=2)
        self.bridge.store.migrate_chat(-1001, -1009)
        self.assertFalse(self.bridge.store.claim(-1009, '2026-11-16', 5))

    async def test_legacy_schema_migration_keeps_delivery_history(self):
        legacy = Path(self.tmp.name) / 'old.sqlite3'
        with sqlite3.connect(legacy) as db:
            db.executescript("""CREATE TABLE lingua_ad_channels(chat_id INTEGER PRIMARY KEY,title TEXT,enabled INTEGER,active INTEGER);
                INSERT INTO lingua_ad_channels VALUES(-88,'Old',0,1);""")
        store = Store(legacy, Config())
        self.assertEqual(store.channels()[0]['enabled'], 0)
        self.assertEqual(store.channels()[0]['chat_type'], 'channel')
        Store(legacy, Config())

    async def test_midnight_during_verification_waits_for_new_days_schedule(self):
        self.now = datetime(2026, 11, 17, 4, 59, 59, tzinfo=timezone.utc)
        async def verify(*args):
            self.now += timedelta(seconds=2)
            return NS(status='administrator', can_post_messages=True)
        self.bot.get_chat_member.side_effect = verify
        await self.bridge.tick(self.context)
        self.bot.send_message.assert_not_awaited()
        self.assertEqual(self.bridge.store.counts('2026-11-16'), {})

    async def test_dst_repeated_hour_does_not_duplicate(self):
        self.bridge.store.configure(hour='01:00', tz='America/New_York')
        self.now = datetime(2026, 11, 1, 5, 30, tzinfo=timezone.utc)
        await self.bridge.tick(self.context)
        self.now += timedelta(hours=1)
        await self.new_bridge().tick(self.context)
        self.bot.send_message.assert_awaited_once()

    async def test_opt_out_during_verification_prevents_send(self):
        async def revoke(*args):
            self.bridge.store.disable_channel(-1001)
            return NS(status='administrator', can_post_messages=True)
        self.bot.get_chat_member.side_effect = revoke
        await self.bridge.tick(self.context)
        self.bot.send_message.assert_not_awaited()

    async def test_launcher_sends_url_and_stops_other_handlers(self):
        update = fake_update()
        with self.assertRaises(ApplicationHandlerStop):
            await self.bridge.launcher(update, self.context)
        kwargs = update.effective_message.reply_text.call_args.kwargs
        self.assertEqual(kwargs['reply_markup'].inline_keyboard[0][0].url, DEFAULT_URL)
        self.assertIsNone(kwargs['parse_mode'])

    async def test_non_owner_cannot_enable_or_modify_settings(self):
        self.bridge.store.configure(enabled=False)
        for command in [('on',), ('time', '01:00', 'UTC'), ('add', '@example'), ('remove', '-1001')]:
            await self.admin(*command, user_id=999999)
        self.assertEqual(self.bridge.store.settings()['enabled'], 0)
        self.assertEqual(self.bridge.store.settings()['hour'], '19:00')
        self.assertEqual(self.bridge.store.channels()[0]['enabled'], 1)
        self.bot.get_chat.assert_not_awaited()

    async def test_owner_group_control_is_denied(self):
        self.bridge.store.configure(enabled=False)
        await self.admin('on', chat_type='group')
        self.assertEqual(self.bridge.store.settings()['enabled'], 0)

    async def test_owner_controls_and_preview_do_not_broadcast(self):
        await self.admin('off')
        self.assertEqual(self.bridge.store.settings()['enabled'], 0)
        await self.admin('on')
        await self.admin('time', '20:30', 'Asia/Tashkent')
        self.assertEqual(self.bridge.store.settings()['hour'], '20:30')
        self.assertEqual(self.bridge.store.settings()['tz'], 'Asia/Tashkent')
        reply = await self.admin('preview')
        self.assertIn('profilingizga kiring', reply.call_args.args[0])
        self.bot.send_message.assert_not_awaited()

    async def test_add_remove_and_reenable_channel(self):
        await self.admin('add', '@example')
        self.assertIn(-100000001, {r['chat_id'] for r in self.bridge.store.channels()})
        await self.admin('remove', '-100000001')
        self.assertEqual(self.bridge.store.channels()[0]['enabled'], 0)
        await self.admin('add', '-100000001')
        self.assertEqual(self.bridge.store.channels()[0]['enabled'], 1)

    async def test_channel_listing_is_chunked(self):
        for number in range(100):
            self.bridge.store.observe(-200000 - number, '🧩' * 255)
        replies = await self.admin('channels')
        self.assertGreater(replies.await_count, 1)
        for call in replies.call_args_list:
            self.assertLessEqual(len(call.args[0].encode('utf-16-le')) // 2, 4096)

    async def test_invalid_admin_inputs_leave_settings_unchanged(self):
        initial = self.bridge.store.settings()
        for command in [('time', '25:30'), ('time', '20:00', 'No/Zone'), ('add', '123'), ('unknown',)]:
            await self.admin(*command)
        self.assertEqual(self.bridge.store.settings(), initial)

    async def test_channel_membership_tracks_permissions_without_reenabling_opt_out(self):
        update = fake_update()
        update.my_chat_member = NS(chat=NS(id=-1002, type='channel', title='Tracked'),
                                   new_chat_member=NS(status='administrator', can_post_messages=True))
        await self.bridge.track_membership(update, self.context)
        self.bridge.store.disable_channel(-1002)
        update.my_chat_member.new_chat_member = NS(status='left')
        await self.bridge.track_membership(update, self.context)
        row = self.bridge.store.channels()[0]
        self.assertEqual((row['enabled'], row['active']), (0, 0))

    async def test_channel_post_discovers_channel_but_group_post_does_not(self):
        update = fake_update()
        update.channel_post = object()
        update.effective_chat = NS(id=-1002, type='channel', title='Discovered')
        await self.bridge.track_channel_post(update, self.context)
        update.effective_chat = NS(id=-1003, type='supergroup', title='Ignored')
        await self.bridge.track_channel_post(update, self.context)
        self.assertEqual({r['chat_id'] for r in self.bridge.store.channels()}, {-1001, -1002})


class OfflineRequest(BaseRequest):
    @property
    def read_timeout(self):
        return 5.0

    async def initialize(self):
        pass

    async def shutdown(self):
        pass

    async def do_request(self, *args, **kwargs):
        raise AssertionError('Network requests are forbidden in this test suite')


class RegistrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'test.sqlite3'
        # This syntactically valid dummy token is never initialized or sent anywhere.
        self.app = (Application.builder().token('123456:TEST_ONLY_NOT_REAL')
                    .request(OfflineRequest()).get_updates_request(OfflineRequest()).build())

    def test_real_ptb_registration_preserves_handlers_and_is_idempotent(self):
        previous = CommandHandler('start', AsyncMock())
        self.app.add_handler(previous)
        with patch.dict(os.environ, {}, clear=True):
            bridge = register_lingua_handlers(self.app, db_path=self.path, super_owner_ids={100001})
            again = register_lingua_handlers(self.app, db_path=self.path, super_owner_ids={100001})
        self.assertIs(bridge, again)
        self.assertIs(self.app.bot_data[STATE_KEY], bridge)
        self.assertIn(previous, self.app.handlers[0])
        self.assertEqual(len(self.app.handlers[-30]), 3)
        self.assertEqual(len(self.app.job_queue.get_jobs_by_name(JOB_NAME)), 1)

    def test_bad_config_keeps_existing_bot_available(self):
        with patch.dict(os.environ, {'VL_PUBLIC_URL': 'http://example.org'}), self.assertLogs('veritas.lingua', level='ERROR'):
            result = register_lingua_handlers(self.app, db_path=self.path, super_owner_ids={100001})
        self.assertIsNone(result)
        self.assertNotIn(STATE_KEY, self.app.bot_data)

    def test_actual_telegram_membership_objects(self):
        user = User(123, 'Synthetic', is_bot=True)
        self.assertTrue(LinguaBridge.can_post(ChatMemberOwner(user, is_anonymous=False)))
        self.assertFalse(LinguaBridge.can_post(ChatMemberMember(user)))
        admin = ChatMemberAdministrator(user, is_anonymous=False, can_be_edited=False,
            can_manage_chat=True, can_delete_messages=False, can_manage_video_chats=False,
            can_restrict_members=False, can_promote_members=False, can_change_info=False,
            can_invite_users=False, can_post_stories=False, can_edit_stories=False,
            can_delete_stories=False, can_post_messages=True)
        self.assertTrue(LinguaBridge.can_post(admin))


if __name__ == '__main__':
    unittest.main()
