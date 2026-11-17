"""VERITAS LINGUA launcher and once-per-day channel and group advertisements.

No Telegram requests at import. Existing bot tables and handlers are preserved.
Daily ads start disabled; a Super Owner enables them in the bot's private chat.
"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
import os
from pathlib import Path
import re
import sqlite3
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest, ChatMigrated, Forbidden, RetryAfter, TelegramError
from telegram.ext import (ApplicationHandlerStop, ChatMemberHandler, CommandHandler,
                          MessageHandler, filters)

LOG = logging.getLogger('veritas.lingua')
DEFAULT_URL = 'https://veritas-lingua-telefon-20261113.grittysardine4.chatgpt.site/'
STATE_KEY = 'veritas_lingua_bridge_v1'
JOB_NAME = 'veritas-lingua-daily-channels-v1'


def validate_url(value):
    value = value.strip()
    if not value:
        return ''
    u = urlsplit(value)
    if (u.scheme != 'https' or not u.hostname or u.username or u.password
            or any(c.isspace() for c in value) or len(value) > 2048
            or u.hostname in {'localhost', '127.0.0.1', '::1'}):
        raise ValueError('VL_PUBLIC_URL must be a public HTTPS URL without credentials')
    return value


def schedule(hour, tz):
    if not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]', hour):
        raise ValueError('Vaqt HH:MM shaklida bo‘lsin, masalan 19:00')
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError('Vaqt zonasi noto‘g‘ri; masalan America/New_York yoki Asia/Tashkent') from exc
    return hour, tz


@dataclass(frozen=True)
class Config:
    url: str = DEFAULT_URL
    hour: str = '19:00'
    tz: str = 'America/New_York'
    enabled: bool = False

    @classmethod
    def from_env(cls):
        hour, tz = schedule(os.getenv('VL_LINGUA_AD_TIME', '19:00'),
                            os.getenv('VL_LINGUA_AD_TZ', 'America/New_York'))
        return cls(validate_url(os.getenv('VL_PUBLIC_URL', DEFAULT_URL)), hour, tz,
                   os.getenv('VL_LINGUA_ADS_ENABLED', '0').lower() in {'1', 'true', 'on'})


def ad_text():
    # The current destination is a preview. Do not advertise live AI, SMS or prizes.
    return ('🌍 VERITAS LINGUA — til o‘rganishni o‘yinga aylantiring!\n\n'
            '📚 10 ta til uchun mashqlar\n'
            '🧩 So‘zlardan javob tuzish va til o‘yinlari\n'
            '🐰 Vito bilan London sarguzashti\n\n'
            'Hozir sinov versiyasi: natijalar shu brauzerda saqlanadi. '
            'Jonli AI va SMS hali ulanmagan.\n\n'
            '👇 Saytni ochib sinab ko‘ring:')


def keyboard(url):
    # Ordinary URL buttons work in channels as well as private/group chats.
    return InlineKeyboardMarkup([[InlineKeyboardButton('🌍 VERITAS LINGUA’ni ochish', url=url)]])


class Store:
    def __init__(self, db_path, config):
        self.path = str(db_path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS lingua_ad_settings (
                    id INTEGER PRIMARY KEY CHECK(id=1), enabled INTEGER NOT NULL,
                    hour TEXT NOT NULL, tz TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS lingua_ad_channels (
                    chat_id INTEGER PRIMARY KEY, title TEXT NOT NULL DEFAULT '',
                    enabled INTEGER NOT NULL DEFAULT 1, active INTEGER NOT NULL DEFAULT 1);
                CREATE TABLE IF NOT EXISTS lingua_ad_deliveries (
                    chat_id INTEGER NOT NULL, day TEXT NOT NULL, state TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 1, claimed_at INTEGER NOT NULL,
                    retry_at INTEGER NOT NULL DEFAULT 0, message_id INTEGER,
                    PRIMARY KEY(chat_id, day));
                CREATE TABLE IF NOT EXISTS lingua_ad_migrations (
                    old_id INTEGER PRIMARY KEY, new_id INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS lingua_ad_cooldown (
                    id INTEGER PRIMARY KEY CHECK(id=1), until_stamp INTEGER NOT NULL DEFAULT 0);
                INSERT OR IGNORE INTO lingua_ad_cooldown VALUES(1,0);
            ''')
            if 'chat_type' not in {r['name'] for r in db.execute('PRAGMA table_info(lingua_ad_channels)')}:
                db.execute("ALTER TABLE lingua_ad_channels ADD COLUMN chat_type TEXT NOT NULL DEFAULT 'channel'")
            db.execute('INSERT OR IGNORE INTO lingua_ad_settings VALUES(1,?,?,?)',
                       (int(config.enabled), config.hour, config.tz))

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def settings(self):
        with self.db() as db:
            return dict(db.execute('SELECT * FROM lingua_ad_settings WHERE id=1').fetchone())

    def cooling_down(self, stamp):
        with self.db() as db:
            return db.execute('SELECT until_stamp FROM lingua_ad_cooldown WHERE id=1').fetchone()[0] > stamp

    def defer(self, until_stamp):
        with self.db() as db:
            db.execute('UPDATE lingua_ad_cooldown SET until_stamp=MAX(until_stamp,?) WHERE id=1', (until_stamp,))

    def configure(self, *, enabled=None, hour=None, tz=None):
        with self.db() as db:
            if enabled is not None:
                db.execute('UPDATE lingua_ad_settings SET enabled=? WHERE id=1', (int(enabled),))
            if hour is not None:
                schedule(hour, tz)
                db.execute('UPDATE lingua_ad_settings SET hour=?,tz=? WHERE id=1', (hour, tz))

    def observe(self, chat_id, title='', *, active=True, enable=False, chat_type=None):
        if isinstance(chat_id, bool) or not isinstance(chat_id, int) or chat_id >= 0:
            return
        with self.db() as db:
            db.execute('''INSERT INTO lingua_ad_channels(chat_id,title,active) VALUES(?,?,?)
                ON CONFLICT(chat_id) DO UPDATE SET title=excluded.title,active=excluded.active''',
                       (chat_id, str(title or '')[:255], int(active)))
            if chat_type in {'channel', 'group', 'supergroup'}:
                db.execute('UPDATE lingua_ad_channels SET chat_type=? WHERE chat_id=?', (chat_type, chat_id))
            if enable:
                db.execute('UPDATE lingua_ad_channels SET enabled=1 WHERE chat_id=?', (chat_id,))

    def disable_channel(self, chat_id):
        with self.db() as db:
            return db.execute('UPDATE lingua_ad_channels SET enabled=0 WHERE chat_id=?', (chat_id,)).rowcount

    def channels(self):
        with self.db() as db:
            return [dict(r) for r in db.execute('SELECT * FROM lingua_ad_channels ORDER BY chat_id')]

    def seed_existing_channels(self):
        # Only channel references. Never import the bot's group or user tables.
        tables = ('rebus_channels', 'rebus_group_channels', 'book_channel_links',
                  'book_channel_games', 'rebuses')
        with self.db() as db:
            for table in tables:
                cols = {r['name'] for r in db.execute(f'PRAGMA table_info({table})')}
                if 'channel_id' not in cols:
                    continue
                for row in db.execute(f'SELECT DISTINCT channel_id FROM {table} WHERE channel_id<0'):
                    db.execute('INSERT OR IGNORE INTO lingua_ad_channels(chat_id) VALUES(?)', (row[0],))

    def seed_existing_chats(self):
        self.seed_existing_channels()
        with self.db() as db:
            cols = {r['name'] for r in db.execute('PRAGMA table_info(groups)')}
            if 'chat_id' in cols:
                db.execute("""INSERT OR IGNORE INTO lingua_ad_channels(chat_id,chat_type)
                              SELECT chat_id,'supergroup' FROM groups WHERE chat_id<0""")

    def migrate_chat(self, old_id, new_id):
        if old_id >= 0 or new_id >= 0 or old_id == new_id:
            return
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM lingua_ad_migrations WHERE old_id=?', (old_id,)).fetchone():
                return
            old = db.execute('SELECT * FROM lingua_ad_channels WHERE chat_id=?', (old_id,)).fetchone()
            if not old:
                return
            db.execute("""INSERT INTO lingua_ad_channels(chat_id,title,enabled,active,chat_type)
                          VALUES(?,?,?,?, 'supergroup') ON CONFLICT(chat_id) DO UPDATE
                          SET enabled=MIN(enabled,excluded.enabled)""",
                       (new_id, old['title'], old['enabled'], 1))
            db.execute("""INSERT INTO lingua_ad_deliveries
                          SELECT ?,day,state,attempts,claimed_at,retry_at,message_id
                          FROM lingua_ad_deliveries WHERE chat_id=?
                          ON CONFLICT(chat_id,day) DO UPDATE SET
                          state=CASE WHEN state='retry' THEN excluded.state ELSE state END,
                          attempts=MAX(attempts,excluded.attempts),
                          retry_at=MAX(retry_at,excluded.retry_at)""", (new_id, old_id))
            db.execute('INSERT INTO lingua_ad_migrations VALUES(?,?)', (old_id, new_id))
            db.execute('UPDATE lingua_ad_channels SET active=0,enabled=0 WHERE chat_id=?', (old_id,))

    def available(self, chat_id, day, stamp):
        with self.db() as db:
            row = db.execute('SELECT * FROM lingua_ad_deliveries WHERE chat_id=? AND day=?', (chat_id, day)).fetchone()
        return not row or (row['state'] == 'retry' and row['attempts'] < 3 and row['retry_at'] <= stamp)

    def claim(self, chat_id, day, stamp):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT until_stamp FROM lingua_ad_cooldown WHERE id=1').fetchone()[0] > stamp:
                return False
            if not db.execute('SELECT enabled FROM lingua_ad_settings WHERE id=1').fetchone()[0]:
                return False
            channel = db.execute('SELECT enabled,active FROM lingua_ad_channels WHERE chat_id=?', (chat_id,)).fetchone()
            if not channel or not channel['enabled'] or not channel['active']:
                return False
            row = db.execute('SELECT * FROM lingua_ad_deliveries WHERE chat_id=? AND day=?', (chat_id, day)).fetchone()
            if row:
                if row['state'] != 'retry' or row['attempts'] >= 3 or row['retry_at'] > stamp:
                    return False
                db.execute("UPDATE lingua_ad_deliveries SET state='claimed',attempts=attempts+1,claimed_at=? WHERE chat_id=? AND day=?",
                           (stamp, chat_id, day))
            else:
                db.execute("INSERT INTO lingua_ad_deliveries(chat_id,day,state,claimed_at) VALUES(?,?,'claimed',?)",
                           (chat_id, day, stamp))
            return True

    def outcome(self, chat_id, day, state, *, message_id=None, retry_at=0):
        with self.db() as db:
            db.execute('UPDATE lingua_ad_deliveries SET state=?,message_id=?,retry_at=? WHERE chat_id=? AND day=?',
                       (state, message_id, retry_at, chat_id, day))

    def counts(self, day):
        with self.db() as db:
            return dict(db.execute('SELECT state,COUNT(*) FROM lingua_ad_deliveries WHERE day=? GROUP BY state', (day,)))


class LinguaBridge:
    def __init__(self, db_path, super_owner_ids, config, *, clock=None, pause=asyncio.sleep):
        self.config = config
        self.store = Store(db_path, config)
        self.owners = frozenset(super_owner_ids)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.pause = pause
        self.lock = asyncio.Lock()

    def local_now(self, settings):
        return self.clock().astimezone(ZoneInfo(settings['tz']))

    @staticmethod
    def can_post(member):
        return member.status == 'creator' or (member.status == 'administrator' and getattr(member, 'can_post_messages', False) is True)

    @classmethod
    def can_send(cls, chat, member):
        if chat.type == 'channel':
            return cls.can_post(member)
        if chat.type not in {'group', 'supergroup'}:
            return False
        if member.status in {'creator', 'administrator'}:
            return True
        if member.status == 'restricted':
            return (getattr(member, 'is_member', False) is True
                    and getattr(member, 'can_send_messages', False) is True)
        return (member.status == 'member'
                and getattr(getattr(chat, 'permissions', None), 'can_send_messages', False) is True)

    def retry_stamp(self, error):
        delay = error.retry_after.total_seconds() if isinstance(error.retry_after, timedelta) else float(error.retry_after)
        return int(self.clock().timestamp()) + max(60, int(delay) + 1)

    async def verify_channel(self, bot, reference):
        chat = await bot.get_chat(reference)
        if chat.type not in {'channel', 'group', 'supergroup'}:
            raise ValueError('Faqat kanal yoki guruh qo‘shiladi; shaxsiy chat emas')
        member = await bot.get_chat_member(chat.id, bot.id)
        if not self.can_send(chat, member):
            raise ValueError('Bot kanal yoki guruhda xabar yozish huquqiga ega bo‘lishi kerak')
        return chat

    async def launcher(self, update, context):
        message = update.effective_message
        if message and self.config.url:
            await message.reply_text(ad_text(), reply_markup=keyboard(self.config.url),
                                     parse_mode=None, disable_web_page_preview=True)
        elif message:
            await message.reply_text('VERITAS LINGUA manzili hali sozlanmagan.')
        raise ApplicationHandlerStop

    async def track_membership(self, update, context):
        event = update.my_chat_member
        if event and event.chat.type in {'channel', 'group', 'supergroup'}:
            # Membership updates may omit default group permissions; verify them at send time.
            member = event.new_chat_member
            active = (self.can_post(member) if event.chat.type == 'channel' else
                      member.status in {'creator', 'administrator', 'member'} or
                      (member.status == 'restricted' and getattr(member, 'is_member', False)
                       and getattr(member, 'can_send_messages', False)))
            self.store.observe(event.chat.id, event.chat.title, active=active, chat_type=event.chat.type)

    async def track_channel_post(self, update, context):
        chat = update.effective_chat
        if update.channel_post and chat and chat.type == 'channel':
            self.store.observe(chat.id, chat.title)

    async def track_group(self, update, context):
        chat, msg = update.effective_chat, update.effective_message
        if chat and chat.type in {'group', 'supergroup'}:
            self.store.observe(chat.id, chat.title, chat_type=chat.type)
            if getattr(msg, 'migrate_to_chat_id', None):
                self.store.migrate_chat(chat.id, msg.migrate_to_chat_id)
            elif getattr(msg, 'migrate_from_chat_id', None):
                self.store.migrate_chat(msg.migrate_from_chat_id, chat.id)

    async def admin(self, update, context):
        msg, user, chat = update.effective_message, update.effective_user, update.effective_chat
        if not msg:
            raise ApplicationHandlerStop
        if not user or user.id not in self.owners or not chat or chat.type != 'private':
            await msg.reply_text('Bu boshqaruv faqat Super Ega bilan shaxsiy chatda ishlaydi.')
            raise ApplicationHandlerStop
        args = list(context.args or [])
        action = args[0].lower() if args else 'status'
        try:
            if action == 'on' and len(args) == 1:
                if not self.config.url:
                    raise ValueError('Avval VL_PUBLIC_URL manzilini sozlang')
                self.store.seed_existing_chats()
                self.store.configure(enabled=True)
            elif action == 'off' and len(args) == 1:
                self.store.configure(enabled=False)
            elif action == 'time' and len(args) in {2, 3}:
                old = self.store.settings()
                self.store.configure(hour=args[1], tz=args[2] if len(args) == 3 else old['tz'])
            elif action == 'preview' and len(args) == 1:
                if not self.config.url:
                    raise ValueError('VL_PUBLIC_URL manzili sozlanmagan')
                await msg.reply_text(ad_text(), reply_markup=keyboard(self.config.url),
                                     parse_mode=None, disable_web_page_preview=True)
                raise ApplicationHandlerStop
            elif action == 'add' and len(args) == 2:
                ref = args[1]
                if not re.fullmatch(r'-\d+|@[A-Za-z][A-Za-z0-9_]{4,31}', ref):
                    raise ValueError('Kanal/guruhni @username yoki manfiy kanal ID bilan yozing')
                channel = await self.verify_channel(context.bot, int(ref) if ref.startswith('-') else ref)
                self.store.observe(channel.id, channel.title, enable=True, chat_type=channel.type)
            elif action == 'remove' and len(args) == 2 and re.fullmatch(r'-\d+', args[1]):
                if not self.store.disable_channel(int(args[1])):
                    raise ValueError('Kanal/guruh ro‘yxatda topilmadi')
            elif action in {'channels', 'chats'} and len(args) == 1:
                rows = self.store.channels()
                lines = [f"{'✅' if r['enabled'] and r['active'] else '⏸'} {r['chat_id']} · {r['chat_type']} · {r['title'][:45]}" for r in rows]
                # Telegram's message limit; lists remain readable for large deployments.
                for start in range(0, len(lines), 20):
                    await msg.reply_text('\n'.join(lines[start:start+20]), parse_mode=None)
                if not lines:
                    await msg.reply_text('Hali kanal yoki guruh yo‘q. /lingua_ads add @kanal_username')
                raise ApplicationHandlerStop
            elif action != 'status' or len(args) > 1:
                raise ValueError('Buyruqlar: /lingua_ads status|on|off|preview|channels\n'
                                 '/lingua_ads time 19:00 America/New_York\n'
                                 '/lingua_ads add @kanal_username\n/lingua_ads remove -1001234567890')
            settings = self.store.settings()
            day = self.local_now(settings).date().isoformat()
            counts = self.store.counts(day)
            channels = self.store.channels()
            await msg.reply_text(
                f"📣 Lingua reklama: {'YOQILGAN' if settings['enabled'] else 'O‘CHIRILGAN'}\n"
                f"Har kuni {settings['hour']} · {settings['tz']}\n"
                f"Faol kanal va guruhlar: {sum(bool(r['enabled'] and r['active']) for r in channels)} / {len(channels)}\n"
                f"Bugun yuborildi: {counts.get('sent', 0)}\n"
                f"Kutilayotgan tekshiruv: {counts.get('claimed', 0) + counts.get('uncertain', 0)}\n"
                f"Xatolar: {counts.get('failed', 0)} · qayta kutish: {counts.get('retry', 0)}\n"
                'Har kanal va guruhga kuniga ko‘pi bilan bir muvaffaqiyatli post.\n'
                '/lingua_ads preview — reklamani shu yerda ko‘rish', parse_mode=None)
        except ValueError as exc:
            await msg.reply_text(str(exc), parse_mode=None)
        except TelegramError:
            await msg.reply_text('Chatni tekshirib bo‘lmadi. Botning kanal/guruhga kirish va yozish huquqini tekshiring.')
        raise ApplicationHandlerStop

    async def tick(self, context):
        if self.lock.locked() or not self.config.url:
            return
        async with self.lock:
            settings = self.store.settings()
            if not settings['enabled']:
                return
            local = self.local_now(settings)
            if local.strftime('%H:%M') < settings['hour'] or self.store.cooling_down(int(local.timestamp())):
                return
            self.store.seed_existing_chats()
            for row in self.store.channels():
                settings = self.store.settings()
                if not settings['enabled']:
                    break
                local = self.local_now(settings)
                if local.strftime('%H:%M') < settings['hour']:
                    break
                stamp, day = int(local.timestamp()), local.date().isoformat()
                if self.store.cooling_down(stamp):
                    break
                chat_id = row['chat_id']
                if not row['enabled'] or not row['active'] or not self.store.available(chat_id, day, stamp):
                    continue
                try:
                    channel = await self.verify_channel(context.bot, chat_id)
                except RetryAfter as exc:
                    self.store.defer(self.retry_stamp(exc))
                    break
                except ChatMigrated as exc:
                    self.store.migrate_chat(chat_id, exc.new_chat_id)
                    continue
                except (ValueError, Forbidden, BadRequest):
                    self.store.observe(chat_id, row['title'], active=False)
                    continue
                except TelegramError:
                    LOG.warning('Lingua channel permission check unavailable')
                    continue
                self.store.observe(chat_id, channel.title, chat_type=channel.type)
                # Permissions checks may span midnight or a schedule change.
                settings = self.store.settings()
                local = self.local_now(settings)
                if not settings['enabled'] or local.strftime('%H:%M') < settings['hour']:
                    break
                stamp, day = int(local.timestamp()), local.date().isoformat()
                # Claim commits BEFORE sending. Crash/timeout never causes a same-day resend.
                if not self.store.claim(chat_id, day, stamp):
                    continue
                try:
                    message = await context.bot.send_message(
                        chat_id=chat_id, text=ad_text(), reply_markup=keyboard(self.config.url),
                        parse_mode=None, disable_web_page_preview=True)
                except RetryAfter as exc:
                    retry_at = self.retry_stamp(exc)
                    self.store.defer(retry_at)
                    self.store.outcome(chat_id, day, 'retry', retry_at=retry_at)
                    break  # Respect Telegram's limit globally; next tick retries safely.
                except ChatMigrated as exc:
                    self.store.migrate_chat(chat_id, exc.new_chat_id)
                    continue  # Claimed day follows migration; avoid a duplicate after uncertain send.
                except (Forbidden, BadRequest):
                    self.store.outcome(chat_id, day, 'failed')
                    self.store.observe(chat_id, channel.title, active=False)
                except TelegramError:
                    self.store.outcome(chat_id, day, 'uncertain')
                    LOG.warning('Lingua delivery uncertain; same-day resend suppressed')
                else:
                    self.store.outcome(chat_id, day, 'sent', message_id=message.message_id)
                await self.pause(0.2)


def register_lingua_handlers(application, *, db_path, super_owner_ids):
    """Register once, after existing handlers and before run_polling()."""
    if STATE_KEY in application.bot_data:
        return application.bot_data[STATE_KEY]
    try:
        bridge = LinguaBridge(db_path, super_owner_ids, Config.from_env())
    except (ValueError, sqlite3.Error, OSError):
        LOG.exception('Lingua module disabled: check its configuration and writable DB path')
        return None  # Existing bot features can still start.
    application.bot_data[STATE_KEY] = bridge
    application.add_handler(CommandHandler('lingua', bridge.launcher), group=-30)
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(re.compile(r'^\*lingua(?:\s|$)', re.I)), bridge.launcher), group=-30)
    application.add_handler(CommandHandler('lingua_ads', bridge.admin), group=-30)
    application.add_handler(ChatMemberHandler(bridge.track_membership, ChatMemberHandler.MY_CHAT_MEMBER), group=-349)
    application.add_handler(MessageHandler(filters.UpdateType.CHANNEL_POST, bridge.track_channel_post), group=-348)
    application.add_handler(MessageHandler(filters.ChatType.GROUPS, bridge.track_group), group=-347)
    if application.job_queue:
        application.job_queue.run_repeating(bridge.tick, interval=60, first=20, name=JOB_NAME,
                                           job_kwargs={'max_instances': 1, 'coalesce': True})
    else:
        LOG.error('Lingua scheduler requires python-telegram-bot[job-queue]; launcher remains available')
    return bridge
