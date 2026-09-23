# =========================================================
# VERITAS BOT V7
# PART 1 — IMPORTS & CONFIGURATION
# =========================================================

import os
import re
import json
import time
import random
import sqlite3
import logging
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional, Any


# =========================================================
# TELEGRAM
# =========================================================

from telegram import (
    Update,
    User,
    Chat,
    Message,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ChatPermissions,
    LabeledPrice,
)


from telegram.constants import (
    ParseMode,
    ChatType,
)


from telegram.error import (
    TelegramError,
    BadRequest,
    Forbidden,
    RetryAfter,
)


from telegram.ext import (
    Application,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    PreCheckoutQueryHandler,
    ChatMemberHandler,
    filters,
)


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    format=(
        "%(asctime)s | "
        "%(levelname)s | "
        "%(name)s | "
        "%(message)s"
    ),
    level=logging.INFO,
)

logger = logging.getLogger("VeritasBot")


# =========================================================
# ENVIRONMENT
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN topilmadi. "
        "Railway Variables ichiga BOT_TOKEN qo'shing."
    )


# =========================================================
# DATABASE
# =========================================================

DB_PATH = os.getenv(
    "DB_PATH",
    "veritas.db"
)


# =========================================================
# BOT VERSION
# =========================================================

BOT_NAME = "VeritasBot"

BOT_VERSION = "7.0"

BOT_FULL_NAME = f"{BOT_NAME} v{BOT_VERSION}"


# =========================================================
# SUPER OWNERS
# =========================================================
#
# Railway Variables:
#
# SUPER_OWNER_IDS=123456789,987654321
#
# shaklida yoziladi.
#
# Kod ichiga Telegram ID yozish shart emas.
# =========================================================

def load_super_owner_ids():
    raw = os.getenv(
        "SUPER_OWNER_IDS",
        ""
    )

    result = set()

    for value in raw.split(","):
        value = value.strip()

        if not value:
            continue

        try:
            result.add(int(value))
        except ValueError:
            logger.warning(
                "Noto'g'ri SUPER_OWNER_ID: %s",
                value
            )

    return result


SUPER_OWNER_IDS = load_super_owner_ids()


def is_super_owner_id(
    user_id: int
) -> bool:

    return user_id in SUPER_OWNER_IDS


# =========================================================
# LANGUAGES
# =========================================================

SUPPORTED_LANGUAGES = {
    "uz": "🇺🇿 O'zbekcha",
    "ru": "🇷🇺 Русский",
    "en": "🇬🇧 English",
}

DEFAULT_LANGUAGE = "uz"


# =========================================================
# V7 SUBSCRIPTION SETTINGS
# =========================================================

DEFAULT_DEMO_DAYS = 7

DEFAULT_V7_DAYS = 7

DEFAULT_V7_PRICE = 100


# =========================================================
# TELEGRAM PREMIUM
# =========================================================
#
# Telegram Bot API:
#
# 3 oy  = 1000 Stars
# 6 oy  = 1500 Stars
# 12 oy = 2500 Stars
#
# =========================================================

PREMIUM_OPTIONS = {
    3: 1000,
    6: 1500,
    12: 2500,
}


# =========================================================
# INTERNAL REWARD SETTINGS
# =========================================================

DAILY_TOP_REWARDS = {
    1: 25,
    2: 15,
    3: 10,
}

WEEKLY_TOP_REWARD = 100


# =========================================================
# WARN SYSTEM
# =========================================================

MAX_WARNS = 3


# =========================================================
# FLOOD PROTECTION
# =========================================================

FLOOD_MESSAGE_LIMIT = 7

FLOOD_SECONDS = 5

FLOOD_MUTE_SECONDS = 60


# =========================================================
# CALLBACK PREFIXES
# =========================================================

CALLBACK_SUPER = "super:"
CALLBACK_USER = "user:"
CALLBACK_GROUP = "group:"
CALLBACK_PREMIUM = "premium:"
CALLBACK_GIFT = "gift:"
CALLBACK_PAYMENT = "payment:"
CALLBACK_REWARD = "reward:"
CALLBACK_LIBRARY = "library:"


# =========================================================
# PAYMENT CURRENCY
# =========================================================

STARS_CURRENCY = "XTR"


# =========================================================
# TEMPORARY USER STATES
# =========================================================
#
# Bu dictlar faqat qisqa vaqtli dialoglar uchun.
# Asosiy ma'lumotlar SQLite'da saqlanadi.
#
# =========================================================

USER_STATES = {}

FLOOD_CACHE = {}

PENDING_PREMIUM = {}

PENDING_GIFTS = {}

PENDING_REWARDS = {}

PENDING_REFUNDS = {}


# =========================================================
# DATE / TIME HELPERS
# =========================================================

def utc_now():
    return datetime.now(timezone.utc)


def utc_timestamp():
    return int(time.time())


def iso_now():
    return utc_now().isoformat()


def days_from_now(
    days: int
):
    return (
        utc_now()
        + timedelta(days=days)
    ).isoformat()


# =========================================================
# SAFE INTEGER
# =========================================================

def safe_int(
    value,
    default=0
):

    try:
        return int(value)

    except (
        TypeError,
        ValueError
    ):
        return default


# =========================================================
# SAFE TEXT
# =========================================================

def clean_text(
    value: Any
) -> str:

    if value is None:
        return ""

    return str(value).strip()


# =========================================================
# USER DISPLAY NAME
# =========================================================

def user_display_name(
    user: Optional[User]
) -> str:

    if not user:
        return "Noma'lum"

    if user.username:
        return f"@{user.username}"

    if user.full_name:
        return user.full_name

    return str(user.id)


# =========================================================
# DATABASE CONNECTION
# =========================================================

def db_connect():

    conn = sqlite3.connect(
        DB_PATH,
        timeout=30,
        check_same_thread=False
    )

    conn.row_factory = sqlite3.Row

    conn.execute(
        "PRAGMA foreign_keys = ON"
    )

    conn.execute(
        "PRAGMA journal_mode = WAL"
    )

    return conn


# =========================================================
# DATABASE EXECUTE HELPER
# =========================================================

def db_execute(
    sql: str,
    params=(),
    *,
    fetchone=False,
    fetchall=False,
):

    conn = db_connect()

    try:

        cursor = conn.execute(
            sql,
            params
        )

        result = None

        if fetchone:
            result = cursor.fetchone()

        elif fetchall:
            result = cursor.fetchall()

        conn.commit()

        return result

    finally:

        conn.close()


# =========================================================
# DATABASE TRANSACTION HELPER
# =========================================================

def db_transaction(
    statements
):

    conn = db_connect()

    try:

        cursor = conn.cursor()

        for sql, params in statements:

            cursor.execute(
                sql,
                params
            )

        conn.commit()

    except Exception:

        conn.rollback()
        raise

    finally:

        conn.close()


# =========================================================
# SUPER OWNER CHECK
# =========================================================

async def require_super_owner(
    update: Update
) -> bool:

    user = update.effective_user

    if (
        not user
        or not is_super_owner_id(user.id)
    ):

        if update.callback_query:

            await update.callback_query.answer(
                "⛔ Bu bo'lim faqat Super Ega uchun.",
                show_alert=True
            )

        elif update.effective_message:

            await update.effective_message.reply_text(
                "⛔ Bu bo'lim faqat Super Ega uchun."
            )

        return False

    return True


# =========================================================
# ERROR TEXT
# =========================================================

def error_text(
    error: Exception
) -> str:

    return (
        f"{type(error).__name__}: "
        f"{error}"
    )


# =========================================================
# BASIC ERROR LOGGER
# =========================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE
):

    error = context.error

    logger.exception(
        "VERITAS ERROR: %s",
        error
    )


# =========================================================
# STARTUP MESSAGE
# =========================================================

def startup_log():

    logger.info(
        "%s ishga tushmoqda...",
        BOT_FULL_NAME
    )

    logger.info(
        "Super Egalar soni: %s",
        len(SUPER_OWNER_IDS)
    )


# =========================================================
# END PART 1
# =========================================================
# =========================================================
# VERITAS BOT V7
# PART 2 — DATABASE CORE
# =========================================================


def table_columns(
    conn,
    table_name: str
):
    rows = conn.execute(
        f"PRAGMA table_info({table_name})"
    ).fetchall()

    return {
        row["name"]
        for row in rows
    }


def add_column_if_missing(
    conn,
    table_name: str,
    column_name: str,
    definition: str
):
    columns = table_columns(
        conn,
        table_name
    )

    if column_name not in columns:

        conn.execute(
            f"""
            ALTER TABLE {table_name}
            ADD COLUMN {column_name} {definition}
            """
        )


# =========================================================
# INITIALIZE DATABASE
# =========================================================

def init_database():

    conn = db_connect()

    try:

        cursor = conn.cursor()

        # =================================================
        # USERS
        # =================================================

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS users (

                user_id INTEGER PRIMARY KEY,

                username TEXT,

                first_name TEXT,

                last_name TEXT,

                language TEXT
                    NOT NULL
                    DEFAULT 'uz',

                internal_balance INTEGER
                    NOT NULL
                    DEFAULT 0,

                xp INTEGER
                    NOT NULL
                    DEFAULT 0,

                level INTEGER
                    NOT NULL
                    DEFAULT 1,

                title TEXT,

                is_blocked INTEGER
                    NOT NULL
                    DEFAULT 0,

                created_at TEXT
                    NOT NULL,

                updated_at TEXT
                    NOT NULL,

                last_seen_at TEXT
            )
            """
        )


        # =================================================
        # GROUPS
        # =================================================

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS groups (

                chat_id INTEGER PRIMARY KEY,

                title TEXT,

                username TEXT,

                owner_id INTEGER,

                language TEXT
                    NOT NULL
                    DEFAULT 'uz',

                is_active INTEGER
                    NOT NULL
                    DEFAULT 1,

                welcome_enabled INTEGER
                    NOT NULL
                    DEFAULT 1,

                goodbye_enabled INTEGER
                    NOT NULL
                    DEFAULT 1,

                anti_link_enabled INTEGER
                    NOT NULL
                    DEFAULT 0,

                anti_flood_enabled INTEGER
                    NOT NULL
                    DEFAULT 1,

                warns_enabled INTEGER
                    NOT NULL
                    DEFAULT 1,

                gifts_enabled INTEGER
                    NOT NULL
                    DEFAULT 1,

                premium_enabled INTEGER
                    NOT NULL
                    DEFAULT 1,

                rewards_enabled INTEGER
                    NOT NULL
                    DEFAULT 1,

                library_enabled INTEGER
                    NOT NULL
                    DEFAULT 1,

                welcome_text TEXT,

                goodbye_text TEXT,

                created_at TEXT
                    NOT NULL,

                updated_at TEXT
                    NOT NULL
            )
            """
        )


        # =================================================
        # GROUP MEMBERS
        # =================================================

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS group_members (

                chat_id INTEGER
                    NOT NULL,

                user_id INTEGER
                    NOT NULL,

                message_count INTEGER
                    NOT NULL
                    DEFAULT 0,

                daily_messages INTEGER
                    NOT NULL
                    DEFAULT 0,

                weekly_messages INTEGER
                    NOT NULL
                    DEFAULT 0,

                xp INTEGER
                    NOT NULL
                    DEFAULT 0,

                level INTEGER
                    NOT NULL
                    DEFAULT 1,

                last_message_at TEXT,

                joined_at TEXT,

                PRIMARY KEY (
                    chat_id,
                    user_id
                )
            )
            """
        )


        # =================================================
        # GROUP MODERATORS
        # =================================================

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS group_moderators (

                chat_id INTEGER
                    NOT NULL,

                user_id INTEGER
                    NOT NULL,

                added_by INTEGER,

                can_ban INTEGER
                    NOT NULL
                    DEFAULT 1,

                can_mute INTEGER
                    NOT NULL
                    DEFAULT 1,

                can_warn INTEGER
                    NOT NULL
                    DEFAULT 1,

                can_delete INTEGER
                    NOT NULL
                    DEFAULT 1,

                created_at TEXT
                    NOT NULL,

                PRIMARY KEY (
                    chat_id,
                    user_id
                )
            )
            """
        )


        # =================================================
        # SUBSCRIPTIONS
        # =================================================

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS subscriptions (

                chat_id INTEGER PRIMARY KEY,

                plan TEXT
                    NOT NULL
                    DEFAULT 'DEMO',

                status TEXT
                    NOT NULL
                    DEFAULT 'ACTIVE',

                started_at TEXT
                    NOT NULL,

                expires_at TEXT,

                granted_by INTEGER,

                price_stars INTEGER
                    NOT NULL
                    DEFAULT 0,

                updated_at TEXT
                    NOT NULL
            )
            """
        )


        # =================================================
        # INTERNAL BALANCE LEDGER
        # =================================================

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS balance_transactions (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                user_id INTEGER
                    NOT NULL,

                amount INTEGER
                    NOT NULL,

                transaction_type TEXT
                    NOT NULL,

                reference TEXT,

                description TEXT,

                created_by INTEGER,

                created_at TEXT
                    NOT NULL
            )
            """
        )


        # =================================================
        # TELEGRAM STAR PAYMENTS
        # =================================================

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS star_payments (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                user_id INTEGER
                    NOT NULL,

                telegram_payment_charge_id TEXT
                    UNIQUE,

                provider_payment_charge_id TEXT,

                invoice_payload TEXT
                    NOT NULL,

                amount INTEGER
                    NOT NULL,

                currency TEXT
                    NOT NULL
                    DEFAULT 'XTR',

                status TEXT
                    NOT NULL
                    DEFAULT 'PAID',

                created_at TEXT
                    NOT NULL,

                refunded_at TEXT
            )
            """
        )


        # =================================================
        # GENERAL TRANSACTIONS
        # =================================================

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS transactions (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                user_id INTEGER,

                chat_id INTEGER,

                transaction_type TEXT
                    NOT NULL,

                amount INTEGER
                    NOT NULL
                    DEFAULT 0,

                currency TEXT
                    NOT NULL
                    DEFAULT 'XTR',

                status TEXT
                    NOT NULL
                    DEFAULT 'SUCCESS',

                reference TEXT,

                description TEXT,

                metadata TEXT,

                created_by INTEGER,

                created_at TEXT
                    NOT NULL
            )
            """
        )


        # =================================================
        # PREMIUM GIFTS
        # =================================================

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS premium_gifts (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                recipient_user_id INTEGER
                    NOT NULL,

                month_count INTEGER
                    NOT NULL,

                star_count INTEGER
                    NOT NULL,

                text TEXT,

                status TEXT
                    NOT NULL
                    DEFAULT 'PENDING',

                requested_by INTEGER,

                error_message TEXT,

                created_at TEXT
                    NOT NULL,

                completed_at TEXT
            )
            """
        )


        # =================================================
        # TELEGRAM GIFTS
        # =================================================

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS telegram_gifts (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                recipient_user_id INTEGER
                    NOT NULL,

                gift_id TEXT
                    NOT NULL,

                star_count INTEGER
                    NOT NULL
                    DEFAULT 0,

                text TEXT,

                status TEXT
                    NOT NULL
                    DEFAULT 'PENDING',

                requested_by INTEGER,

                error_message TEXT,

                created_at TEXT
                    NOT NULL,

                completed_at TEXT
            )
            """
        )


        # =================================================
        # USER REWARDS
        # =================================================

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS user_rewards (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                user_id INTEGER
                    NOT NULL,

                chat_id INTEGER,

                reward_type TEXT
                    NOT NULL,

                reward_value TEXT,

                star_value INTEGER
                    NOT NULL
                    DEFAULT 0,

                reason TEXT,

                status TEXT
                    NOT NULL
                    DEFAULT 'GRANTED',

                granted_by INTEGER,

                created_at TEXT
                    NOT NULL
            )
            """
        )


        # =================================================
        # WARNS
        # =================================================

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS warns (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                chat_id INTEGER
                    NOT NULL,

                user_id INTEGER
                    NOT NULL,

                moderator_id INTEGER,

                reason TEXT,

                active INTEGER
                    NOT NULL
                    DEFAULT 1,

                created_at TEXT
                    NOT NULL
            )
            """
        )


        # =================================================
        # BLACKLIST
        # =================================================

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS blacklist (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                chat_id INTEGER
                    NOT NULL,

                word TEXT
                    NOT NULL,

                created_by INTEGER,

                created_at TEXT
                    NOT NULL,

                UNIQUE (
                    chat_id,
                    word
                )
            )
            """
        )


        # =================================================
        # FILTERS
        # =================================================

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS custom_filters (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                chat_id INTEGER
                    NOT NULL,

                trigger_text TEXT
                    NOT NULL,

                response_text TEXT
                    NOT NULL,

                created_by INTEGER,

                created_at TEXT
                    NOT NULL,

                UNIQUE (
                    chat_id,
                    trigger_text
                )
            )
            """
        )


        # =================================================
        # NOTES
        # =================================================

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS notes (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                chat_id INTEGER
                    NOT NULL,

                note_name TEXT
                    NOT NULL,

                note_text TEXT
                    NOT NULL,

                created_by INTEGER,

                created_at TEXT
                    NOT NULL,

                UNIQUE (
                    chat_id,
                    note_name
                )
            )
            """
        )


        # =================================================
        # GROUP RULES
        # =================================================

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS group_rules (

                chat_id INTEGER PRIMARY KEY,

                rules_text TEXT,

                updated_by INTEGER,

                updated_at TEXT
            )
            """
        )


        # =================================================
        # APPROVED USERS
        # =================================================

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS approved_users (

                chat_id INTEGER
                    NOT NULL,

                user_id INTEGER
                    NOT NULL,

                approved_by INTEGER,

                created_at TEXT
                    NOT NULL,

                PRIMARY KEY (
                    chat_id,
                    user_id
                )
            )
            """
        )


        # =================================================
        # REPORTS
        # =================================================

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS reports (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                chat_id INTEGER
                    NOT NULL,

                reporter_id INTEGER
                    NOT NULL,

                reported_user_id INTEGER,

                message_id INTEGER,

                reason TEXT,

                status TEXT
                    NOT NULL
                    DEFAULT 'OPEN',

                created_at TEXT
                    NOT NULL,

                resolved_at TEXT,

                resolved_by INTEGER
            )
            """
        )


        # =================================================
        # LIBRARY
        # =================================================

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS library_books (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                title TEXT
                    NOT NULL,

                author TEXT,

                description TEXT,

                file_id TEXT,

                file_type TEXT,

                language TEXT
                    NOT NULL
                    DEFAULT 'uz',

                added_by INTEGER,

                active INTEGER
                    NOT NULL
                    DEFAULT 1,

                created_at TEXT
                    NOT NULL
            )
            """
        )


        # =================================================
        # GIVEAWAYS
        # =================================================

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS giveaways (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                chat_id INTEGER
                    NOT NULL,

                created_by INTEGER
                    NOT NULL,

                title TEXT,

                reward_type TEXT
                    NOT NULL,

                reward_value TEXT,

                winner_count INTEGER
                    NOT NULL
                    DEFAULT 1,

                required_channel TEXT,

                status TEXT
                    NOT NULL
                    DEFAULT 'ACTIVE',

                ends_at TEXT,

                created_at TEXT
                    NOT NULL,

                completed_at TEXT
            )
            """
        )


        # =================================================
        # GIVEAWAY PARTICIPANTS
        # =================================================

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS giveaway_participants (

                giveaway_id INTEGER
                    NOT NULL,

                user_id INTEGER
                    NOT NULL,

                joined_at TEXT
                    NOT NULL,

                PRIMARY KEY (
                    giveaway_id,
                    user_id
                )
            )
            """
        )


        # =================================================
        # GIVEAWAY WINNERS
        # =================================================

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS giveaway_winners (

                giveaway_id INTEGER
                    NOT NULL,

                user_id INTEGER
                    NOT NULL,

                selected_at TEXT
                    NOT NULL,

                reward_sent INTEGER
                    NOT NULL
                    DEFAULT 0,

                PRIMARY KEY (
                    giveaway_id,
                    user_id
                )
            )
            """
        )


        # =================================================
        # PROMO CHANNELS
        # =================================================

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS promo_channels (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                chat_id INTEGER
                    UNIQUE,

                username TEXT,

                title TEXT,

                active INTEGER
                    NOT NULL
                    DEFAULT 1,

                created_at TEXT
                    NOT NULL
            )
            """
        )


        # =================================================
        # SETTINGS
        # =================================================

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS bot_settings (

                setting_key TEXT PRIMARY KEY,

                setting_value TEXT,

                updated_by INTEGER,

                updated_at TEXT
            )
            """
        )


        # =================================================
        # AUDIT LOG
        # =================================================

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_log (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                actor_id INTEGER,

                action TEXT
                    NOT NULL,

                target_user_id INTEGER,

                target_chat_id INTEGER,

                details TEXT,

                created_at TEXT
                    NOT NULL
            )
            """
        )


        # =================================================
        # COMPATIBILITY MIGRATIONS
        # =================================================

        add_column_if_missing(
            conn,
            "users",
            "internal_balance",
            "INTEGER NOT NULL DEFAULT 0"
        )

        add_column_if_missing(
            conn,
            "users",
            "xp",
            "INTEGER NOT NULL DEFAULT 0"
        )

        add_column_if_missing(
            conn,
            "users",
            "level",
            "INTEGER NOT NULL DEFAULT 1"
        )

        add_column_if_missing(
            conn,
            "groups",
            "gifts_enabled",
            "INTEGER NOT NULL DEFAULT 1"
        )

        add_column_if_missing(
            conn,
            "groups",
            "premium_enabled",
            "INTEGER NOT NULL DEFAULT 1"
        )

        add_column_if_missing(
            conn,
            "groups",
            "rewards_enabled",
            "INTEGER NOT NULL DEFAULT 1"
        )

        add_column_if_missing(
            conn,
            "groups",
            "library_enabled",
            "INTEGER NOT NULL DEFAULT 1"
        )


        # =================================================
        # INDEXES
        # =================================================

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_transactions_user
            ON transactions(user_id)
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_transactions_chat
            ON transactions(chat_id)
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_rewards_user
            ON user_rewards(user_id)
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_warns_chat_user
            ON warns(chat_id, user_id)
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_members_activity
            ON group_members(
                chat_id,
                message_count
            )
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_audit_created
            ON audit_log(created_at)
            """
        )

        conn.commit()

        logger.info(
            "Veritas V7 database tayyor."
        )

    except Exception:

        conn.rollback()

        logger.exception(
            "Database yaratishda xato."
        )

        raise

    finally:

        conn.close()


# =========================================================
# REGISTER / UPDATE USER
# =========================================================

def ensure_user(
    user: Optional[User]
):

    if not user:
        return

    now = iso_now()

    conn = db_connect()

    try:

        existing = conn.execute(
            """
            SELECT user_id
            FROM users
            WHERE user_id = ?
            """,
            (user.id,)
        ).fetchone()

        if existing:

            conn.execute(
                """
                UPDATE users
                SET
                    username = ?,
                    first_name = ?,
                    last_name = ?,
                    updated_at = ?,
                    last_seen_at = ?
                WHERE user_id = ?
                """,
                (
                    user.username,
                    user.first_name,
                    user.last_name,
                    now,
                    now,
                    user.id,
                )
            )

        else:

            conn.execute(
                """
                INSERT INTO users (
                    user_id,
                    username,
                    first_name,
                    last_name,
                    language,
                    internal_balance,
                    xp,
                    level,
                    is_blocked,
                    created_at,
                    updated_at,
                    last_seen_at
                )
                VALUES (
                    ?, ?, ?, ?,
                    ?, 0, 0, 1, 0,
                    ?, ?, ?
                )
                """,
                (
                    user.id,
                    user.username,
                    user.first_name,
                    user.last_name,
                    DEFAULT_LANGUAGE,
                    now,
                    now,
                    now,
                )
            )

        conn.commit()

    finally:

        conn.close()


# =========================================================
# REGISTER / UPDATE GROUP
# =========================================================

def ensure_group(
    chat: Optional[Chat],
    owner_id: Optional[int] = None
):

    if not chat:
        return

    if chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP,
    ):
        return

    now = iso_now()

    conn = db_connect()

    try:

        existing = conn.execute(
            """
            SELECT chat_id
            FROM groups
            WHERE chat_id = ?
            """,
            (chat.id,)
        ).fetchone()

        if existing:

            conn.execute(
                """
                UPDATE groups
                SET
                    title = ?,
                    username = ?,
                    is_active = 1,
                    updated_at = ?
                WHERE chat_id = ?
                """,
                (
                    chat.title,
                    chat.username,
                    now,
                    chat.id,
                )
            )

        else:

            conn.execute(
                """
                INSERT INTO groups (
                    chat_id,
                    title,
                    username,
                    owner_id,
                    language,
                    created_at,
                    updated_at
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    chat.id,
                    chat.title,
                    chat.username,
                    owner_id,
                    DEFAULT_LANGUAGE,
                    now,
                    now,
                )
            )

            # Yangi guruhga avtomatik 7 kun demo.

            conn.execute(
                """
                INSERT OR IGNORE INTO subscriptions (
                    chat_id,
                    plan,
                    status,
                    started_at,
                    expires_at,
                    price_stars,
                    updated_at
                )
                VALUES (
                    ?, 'DEMO', 'ACTIVE',
                    ?, ?, 0, ?
                )
                """,
                (
                    chat.id,
                    now,
                    days_from_now(
                        DEFAULT_DEMO_DAYS
                    ),
                    now,
                )
            )

        conn.commit()

    finally:

        conn.close()


# =========================================================
# GET USER
# =========================================================

def get_user_record(
    user_id: int
):

    return db_execute(
        """
        SELECT *
        FROM users
        WHERE user_id = ?
        """,
        (user_id,),
        fetchone=True
    )


# =========================================================
# GET GROUP
# =========================================================

def get_group_record(
    chat_id: int
):

    return db_execute(
        """
        SELECT *
        FROM groups
        WHERE chat_id = ?
        """,
        (chat_id,),
        fetchone=True
    )


# =========================================================
# INTERNAL BALANCE
# =========================================================

def get_internal_balance(
    user_id: int
) -> int:

    row = get_user_record(
        user_id
    )

    if not row:
        return 0

    return safe_int(
        row["internal_balance"]
    )


def change_internal_balance(
    user_id: int,
    amount: int,
    transaction_type: str,
    description: str = "",
    reference: str = "",
    created_by: Optional[int] = None,
):

    now = iso_now()

    conn = db_connect()

    try:

        conn.execute(
            "BEGIN IMMEDIATE"
        )

        row = conn.execute(
            """
            SELECT internal_balance
            FROM users
            WHERE user_id = ?
            """,
            (user_id,)
        ).fetchone()

        if not row:

            raise ValueError(
                "Foydalanuvchi bazada topilmadi."
            )

        current_balance = safe_int(
            row["internal_balance"]
        )

        new_balance = (
            current_balance
            + int(amount)
        )

        if new_balance < 0:

            raise ValueError(
                "Balans yetarli emas."
            )

        conn.execute(
            """
            UPDATE users
            SET
                internal_balance = ?,
                updated_at = ?
            WHERE user_id = ?
            """,
            (
                new_balance,
                now,
                user_id,
            )
        )

        conn.execute(
            """
            INSERT INTO balance_transactions (
                user_id,
                amount,
                transaction_type,
                reference,
                description,
                created_by,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                amount,
                transaction_type,
                reference,
                description,
                created_by,
                now,
            )
        )

        conn.commit()

        return new_balance

    except Exception:

        conn.rollback()
        raise

    finally:

        conn.close()


# =========================================================
# TRANSACTION LOG
# =========================================================

def add_transaction(
    *,
    transaction_type: str,
    user_id: Optional[int] = None,
    chat_id: Optional[int] = None,
    amount: int = 0,
    currency: str = "XTR",
    status: str = "SUCCESS",
    reference: str = "",
    description: str = "",
    metadata: Optional[dict] = None,
    created_by: Optional[int] = None,
):

    metadata_text = None

    if metadata is not None:

        metadata_text = json.dumps(
            metadata,
            ensure_ascii=False
        )

    db_execute(
        """
        INSERT INTO transactions (
            user_id,
            chat_id,
            transaction_type,
            amount,
            currency,
            status,
            reference,
            description,
            metadata,
            created_by,
            created_at
        )
        VALUES (
            ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?
        )
        """,
        (
            user_id,
            chat_id,
            transaction_type,
            amount,
            currency,
            status,
            reference,
            description,
            metadata_text,
            created_by,
            iso_now(),
        )
    )


# =========================================================
# AUDIT LOG
# =========================================================

def audit(
    action: str,
    *,
    actor_id: Optional[int] = None,
    target_user_id: Optional[int] = None,
    target_chat_id: Optional[int] = None,
    details: str = "",
):

    db_execute(
        """
        INSERT INTO audit_log (
            actor_id,
            action,
            target_user_id,
            target_chat_id,
            details,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            actor_id,
            action,
            target_user_id,
            target_chat_id,
            details,
            iso_now(),
        )
    )


# =========================================================
# SETTINGS
# =========================================================

def set_setting(
    key: str,
    value: str,
    updated_by: Optional[int] = None,
):

    db_execute(
        """
        INSERT INTO bot_settings (
            setting_key,
            setting_value,
            updated_by,
            updated_at
        )
        VALUES (?, ?, ?, ?)

        ON CONFLICT(setting_key)
        DO UPDATE SET

            setting_value =
                excluded.setting_value,

            updated_by =
                excluded.updated_by,

            updated_at =
                excluded.updated_at
        """,
        (
            key,
            value,
            updated_by,
            iso_now(),
        )
    )


def get_setting(
    key: str,
    default=None
):

    row = db_execute(
        """
        SELECT setting_value
        FROM bot_settings
        WHERE setting_key = ?
        """,
        (key,),
        fetchone=True
    )

    if not row:
        return default

    return row["setting_value"]


# =========================================================
# USER LANGUAGE
# =========================================================

def get_user_language(
    user_id: int
):

    row = get_user_record(
        user_id
    )

    if not row:
        return DEFAULT_LANGUAGE

    language = row["language"]

    if language not in SUPPORTED_LANGUAGES:
        return DEFAULT_LANGUAGE

    return language


def set_user_language(
    user_id: int,
    language: str
):

    if language not in SUPPORTED_LANGUAGES:

        raise ValueError(
            "Qo'llab-quvvatlanmaydigan til."
        )

    db_execute(
        """
        UPDATE users
        SET
            language = ?,
            updated_at = ?
        WHERE user_id = ?
        """,
        (
            language,
            iso_now(),
            user_id,
        )
    )


# =========================================================
# SUBSCRIPTION STATUS
# =========================================================

def get_subscription(
    chat_id: int
):

    return db_execute(
        """
        SELECT *
        FROM subscriptions
        WHERE chat_id = ?
        """,
        (chat_id,),
        fetchone=True
    )


def subscription_is_active(
    chat_id: int
) -> bool:

    row = get_subscription(
        chat_id
    )

    if not row:
        return False

    if row["status"] != "ACTIVE":
        return False

    expires_at = row["expires_at"]

    if not expires_at:
        return True

    try:

        expires = datetime.fromisoformat(
            expires_at
        )

        if expires.tzinfo is None:
            expires = expires.replace(
                tzinfo=timezone.utc
            )

        return expires > utc_now()

    except ValueError:

        return False


# =========================================================
# GRANT SUBSCRIPTION
# =========================================================

def grant_subscription(
    chat_id: int,
    *,
    plan: str,
    days: Optional[int],
    granted_by: Optional[int],
    price_stars: int = 0,
):

    now = iso_now()

    expires_at = None

    if days is not None:

        expires_at = days_from_now(
            days
        )

    conn = db_connect()

    try:

        conn.execute(
            """
            INSERT INTO subscriptions (
                chat_id,
                plan,
                status,
                started_at,
                expires_at,
                granted_by,
                price_stars,
                updated_at
            )
            VALUES (
                ?, ?, 'ACTIVE',
                ?, ?, ?, ?, ?
            )

            ON CONFLICT(chat_id)
            DO UPDATE SET

                plan =
                    excluded.plan,

                status =
                    'ACTIVE',

                started_at =
                    excluded.started_at,

                expires_at =
                    excluded.expires_at,

                granted_by =
                    excluded.granted_by,

                price_stars =
                    excluded.price_stars,

                updated_at =
                    excluded.updated_at
            """,
            (
                chat_id,
                plan,
                now,
                expires_at,
                granted_by,
                price_stars,
                now,
            )
        )

        conn.commit()

    finally:

        conn.close()

    audit(
        "SUBSCRIPTION_GRANTED",
        actor_id=granted_by,
        target_chat_id=chat_id,
        details=(
            f"plan={plan}; "
            f"days={days}; "
            f"price={price_stars}"
        )
    )


# =========================================================
# DATABASE READY
# =========================================================

startup_log()
init_database()


# =========================================================
# END PART 2
# =========================================================
# =========================================================
# VERITAS BOT V7
# PART 3 — TELEGRAM STARS & PAYMENTS
# =========================================================


# =========================================================
# TOP-UP OPTIONS
# =========================================================

TOPUP_OPTIONS = (
    50,
    100,
    250,
    500,
    1000,
)


# =========================================================
# TOP-UP MENU
# =========================================================

def topup_keyboard():

    rows = []

    for amount in TOPUP_OPTIONS:

        rows.append(
            [
                InlineKeyboardButton(
                    f"⭐ {amount}",
                    callback_data=f"payment:topup:{amount}"
                )
            ]
        )

    rows.append(
        [
            InlineKeyboardButton(
                "⬅️ Orqaga",
                callback_data="user:wallet"
            )
        ]
    )

    return InlineKeyboardMarkup(rows)


# =========================================================
# WALLET MENU
# =========================================================

def wallet_keyboard():

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "➕ Hisobni to'ldirish",
                    callback_data="payment:topup"
                )
            ],
            [
                InlineKeyboardButton(
                    "📜 Tranzaksiyalar",
                    callback_data="payment:history"
                )
            ],
            [
                InlineKeyboardButton(
                    "🔄 Yangilash",
                    callback_data="user:wallet"
                )
            ],
            [
                InlineKeyboardButton(
                    "⬅️ Kabinet",
                    callback_data="user:home"
                )
            ]
        ]
    )


# =========================================================
# USER WALLET
# =========================================================

async def show_user_wallet(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    if not user:
        return

    ensure_user(user)

    balance = get_internal_balance(
        user.id
    )

    text = (
        "💰 VERITAS HISOBI\n\n"
        f"👤 {user_display_name(user)}\n\n"
        f"⭐ Balans: {balance} Stars\n\n"
        "Bu balans Veritas ichidagi xizmatlar, "
        "V7 obuna va mukofot tizimida ishlatiladi."
    )

    if update.callback_query:

        query = update.callback_query

        await query.answer()

        await query.edit_message_text(
            text=text,
            reply_markup=wallet_keyboard()
        )

    elif update.effective_message:

        await update.effective_message.reply_text(
            text,
            reply_markup=wallet_keyboard()
        )


# =========================================================
# TOP-UP MENU
# =========================================================

async def show_topup_menu(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    if not user:
        return

    ensure_user(user)

    text = (
        "⭐ HISOBNI TO'LDIRISH\n\n"
        "Telegram Stars orqali Veritas "
        "balansingizni to'ldirishingiz mumkin.\n\n"
        "Miqdorni tanlang:"
    )

    if update.callback_query:

        query = update.callback_query

        await query.answer()

        await query.edit_message_text(
            text=text,
            reply_markup=topup_keyboard()
        )

    else:

        await update.effective_message.reply_text(
            text,
            reply_markup=topup_keyboard()
        )


# =========================================================
# CREATE STAR INVOICE
# =========================================================

async def create_star_topup_invoice(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    amount: int
):

    user = update.effective_user

    if not user:
        return

    ensure_user(user)

    if amount not in TOPUP_OPTIONS:

        if update.callback_query:

            await update.callback_query.answer(
                "❌ Noto'g'ri miqdor.",
                show_alert=True
            )

        return

    payload = (
        f"veritas_topup:"
        f"{user.id}:"
        f"{amount}:"
        f"{utc_timestamp()}"
    )

    try:

        if update.callback_query:
            await update.callback_query.answer()

        await context.bot.send_invoice(
            chat_id=user.id,

            title="Veritas Stars",

            description=(
                f"Veritas hisobini "
                f"{amount} ⭐ ga to'ldirish"
            ),

            payload=payload,

            provider_token="",

            currency=STARS_CURRENCY,

            prices=[
                LabeledPrice(
                    label="Veritas Stars",
                    amount=amount
                )
            ]
        )

        audit(
            "STAR_INVOICE_CREATED",
            actor_id=user.id,
            target_user_id=user.id,
            details=(
                f"amount={amount}; "
                f"payload={payload}"
            )
        )

    except TelegramError as exc:

        logger.exception(
            "Stars invoice yaratishda xato."
        )

        await context.bot.send_message(
            chat_id=user.id,
            text=(
                "❌ To'lov oynasini yaratib "
                "bo'lmadi.\n\n"
                f"Xato: {error_text(exc)}"
            )
        )


# =========================================================
# PRE-CHECKOUT
# =========================================================

async def pre_checkout_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.pre_checkout_query

    if not query:
        return

    payload = query.invoice_payload or ""

    if not payload.startswith(
        "veritas_topup:"
    ):

        await query.answer(
            ok=False,
            error_message=(
                "Bu to'lov Veritas tomonidan "
                "tasdiqlanmadi."
            )
        )

        return

    parts = payload.split(":")

    if len(parts) != 4:

        await query.answer(
            ok=False,
            error_message=(
                "To'lov ma'lumotlari noto'g'ri."
            )
        )

        return

    try:

        payload_user_id = int(parts[1])
        payload_amount = int(parts[2])

    except ValueError:

        await query.answer(
            ok=False,
            error_message=(
                "To'lov ma'lumotlari buzilgan."
            )
        )

        return

    if query.from_user.id != payload_user_id:

        await query.answer(
            ok=False,
            error_message=(
                "Bu invoice boshqa "
                "foydalanuvchiga tegishli."
            )
        )

        return

    if query.currency != STARS_CURRENCY:

        await query.answer(
            ok=False,
            error_message=(
                "Faqat Telegram Stars "
                "qabul qilinadi."
            )
        )

        return

    if query.total_amount != payload_amount:

        await query.answer(
            ok=False,
            error_message=(
                "To'lov summasi mos kelmadi."
            )
        )

        return

    if payload_amount not in TOPUP_OPTIONS:

        await query.answer(
            ok=False,
            error_message=(
                "Bu to'lov miqdori "
                "qo'llab-quvvatlanmaydi."
            )
        )

        return

    await query.answer(
        ok=True
    )


# =========================================================
# SUCCESSFUL PAYMENT
# =========================================================

async def successful_payment_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    message = update.effective_message
    user = update.effective_user

    if (
        not message
        or not user
        or not message.successful_payment
    ):
        return

    payment = message.successful_payment

    payload = payment.invoice_payload or ""

    if not payload.startswith(
        "veritas_topup:"
    ):
        return

    ensure_user(user)

    parts = payload.split(":")

    if len(parts) != 4:

        logger.error(
            "Noto'g'ri successful payment payload: %s",
            payload
        )

        return

    try:

        payload_user_id = int(parts[1])
        payload_amount = int(parts[2])

    except ValueError:

        logger.error(
            "Payment payload parse error: %s",
            payload
        )

        return

    if payload_user_id != user.id:
        return

    if payment.currency != STARS_CURRENCY:
        return

    if payment.total_amount != payload_amount:
        return

    telegram_charge_id = (
        payment.telegram_payment_charge_id
    )

    provider_charge_id = (
        payment.provider_payment_charge_id
        or ""
    )

    now = iso_now()

    conn = db_connect()

    try:

        conn.execute(
            "BEGIN IMMEDIATE"
        )

        # Bir payment ikki marta balansga
        # tushib qolishining oldini oladi.

        existing = conn.execute(
            """
            SELECT id
            FROM star_payments
            WHERE telegram_payment_charge_id = ?
            """,
            (telegram_charge_id,)
        ).fetchone()

        if existing:

            conn.rollback()

            await message.reply_text(
                "ℹ️ Bu to'lov oldin "
                "hisobga o'tkazilgan."
            )

            return

        row = conn.execute(
            """
            SELECT internal_balance
            FROM users
            WHERE user_id = ?
            """,
            (user.id,)
        ).fetchone()

        if not row:

            conn.rollback()
            return

        old_balance = safe_int(
            row["internal_balance"]
        )

        new_balance = (
            old_balance
            + payload_amount
        )

        conn.execute(
            """
            INSERT INTO star_payments (
                user_id,
                telegram_payment_charge_id,
                provider_payment_charge_id,
                invoice_payload,
                amount,
                currency,
                status,
                created_at
            )
            VALUES (
                ?, ?, ?, ?, ?,
                ?, 'PAID', ?
            )
            """,
            (
                user.id,
                telegram_charge_id,
                provider_charge_id,
                payload,
                payload_amount,
                payment.currency,
                now,
            )
        )

        conn.execute(
            """
            UPDATE users
            SET
                internal_balance = ?,
                updated_at = ?
            WHERE user_id = ?
            """,
            (
                new_balance,
                now,
                user.id,
            )
        )

        conn.execute(
            """
            INSERT INTO balance_transactions (
                user_id,
                amount,
                transaction_type,
                reference,
                description,
                created_by,
                created_at
            )
            VALUES (
                ?, ?, 'STAR_TOPUP',
                ?, ?, ?, ?
            )
            """,
            (
                user.id,
                payload_amount,
                telegram_charge_id,
                "Telegram Stars orqali hisob to'ldirildi",
                user.id,
                now,
            )
        )

        conn.execute(
            """
            INSERT INTO transactions (
                user_id,
                transaction_type,
                amount,
                currency,
                status,
                reference,
                description,
                created_by,
                created_at
            )
            VALUES (
                ?,
                'STAR_TOPUP',
                ?,
                'XTR',
                'SUCCESS',
                ?,
                ?,
                ?,
                ?
            )
            """,
            (
                user.id,
                payload_amount,
                telegram_charge_id,
                "Telegram Stars orqali to'lov",
                user.id,
                now,
            )
        )

        conn.commit()

    except Exception:

        conn.rollback()

        logger.exception(
            "Successful payment bazaga "
            "yozishda xato."
        )

        await message.reply_text(
            "⚠️ To'lov qabul qilindi, "
            "ammo bazaga yozishda xato yuz berdi. "
            "Administratorga murojaat qiling."
        )

        return

    finally:

        conn.close()

    audit(
        "STAR_TOPUP_SUCCESS",
        actor_id=user.id,
        target_user_id=user.id,
        details=(
            f"amount={payload_amount}; "
            f"charge={telegram_charge_id}"
        )
    )

    await message.reply_text(
        (
            "✅ TO'LOV MUVAFFAQIYATLI\n\n"
            f"➕ {payload_amount} ⭐\n"
            f"💰 Yangi balans: {new_balance} ⭐"
        ),
        reply_markup=wallet_keyboard()
    )


# =========================================================
# PAYMENT HISTORY
# =========================================================

def get_user_transactions(
    user_id: int,
    limit: int = 10
):

    return db_execute(
        """
        SELECT *
        FROM transactions
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (
            user_id,
            limit
        ),
        fetchall=True
    )


async def show_payment_history(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    if not user:
        return

    ensure_user(user)

    rows = get_user_transactions(
        user.id,
        10
    )

    lines = [
        "📜 SO'NGGI TRANZAKSIYALAR",
        ""
    ]

    if not rows:

        lines.append(
            "Hozircha tranzaksiyalar yo'q."
        )

    else:

        for row in rows:

            amount = safe_int(
                row["amount"]
            )

            transaction_type = (
                row["transaction_type"]
            )

            status = row["status"]

            created = row["created_at"]

            lines.append(
                f"• {transaction_type}\n"
                f"  ⭐ {amount} | {status}\n"
                f"  🕒 {created}"
            )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "⬅️ Hisob",
                    callback_data="user:wallet"
                )
            ]
        ]
    )

    if update.callback_query:

        await update.callback_query.answer()

        await update.callback_query.edit_message_text(
            "\n\n".join(lines),
            reply_markup=keyboard
        )

    else:

        await update.effective_message.reply_text(
            "\n\n".join(lines),
            reply_markup=keyboard
        )


# =========================================================
# BOT REAL TELEGRAM STARS BALANCE
# =========================================================

async def get_real_bot_star_balance(
    context: ContextTypes.DEFAULT_TYPE
):

    return await context.bot.get_my_star_balance()


async def show_real_bot_star_balance(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not await require_super_owner(update):
        return

    try:

        star_balance = (
            await get_real_bot_star_balance(
                context
            )
        )

        amount = getattr(
            star_balance,
            "amount",
            0
        )

        nanostar_amount = getattr(
            star_balance,
            "nanostar_amount",
            0
        )

        text = (
            "⭐ BOTNING TELEGRAM STARS BALANSI\n\n"
            f"⭐ Stars: {amount}\n"
        )

        if nanostar_amount:
            text += (
                f"🔹 Nanostars: "
                f"{nanostar_amount}\n"
            )

    except TelegramError as exc:

        text = (
            "❌ Telegram Stars balansini "
            "olib bo'lmadi.\n\n"
            f"{error_text(exc)}"
        )

    if update.callback_query:

        await update.callback_query.answer()

        await update.callback_query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🔄 Yangilash",
                            callback_data=(
                                "super:real_star_balance"
                            )
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "⬅️ Super Ega",
                            callback_data="super:home"
                        )
                    ]
                ]
            )
        )

    else:

        await update.effective_message.reply_text(
            text
        )


# =========================================================
# REFUND LOOKUP
# =========================================================

def get_star_payment_by_charge(
    telegram_charge_id: str
):

    return db_execute(
        """
        SELECT *
        FROM star_payments
        WHERE telegram_payment_charge_id = ?
        """,
        (telegram_charge_id,),
        fetchone=True
    )


# =========================================================
# REFUND TELEGRAM STARS PAYMENT
# =========================================================

async def refund_star_payment(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    actor_id: int,
    telegram_charge_id: str
):

    if not is_super_owner_id(
        actor_id
    ):

        raise PermissionError(
            "Faqat Super Ega refund qila oladi."
        )

    payment = get_star_payment_by_charge(
        telegram_charge_id
    )

    if not payment:

        raise ValueError(
            "To'lov topilmadi."
        )

    if payment["status"] == "REFUNDED":

        raise ValueError(
            "Bu to'lov oldin qaytarilgan."
        )

    user_id = safe_int(
        payment["user_id"]
    )

    amount = safe_int(
        payment["amount"]
    )

    # Avval ichki balansni tekshiramiz.
    # Aks holda foydalanuvchi Starsni
    # ishlatib bo'lgach pulni qaytarish mumkin.

    internal_balance = (
        get_internal_balance(
            user_id
        )
    )

    if internal_balance < amount:

        raise ValueError(
            "Refund qilib bo'lmaydi: "
            "foydalanuvchining Veritas balansida "
            "yetarli Stars qolmagan."
        )

    # Telegram'da real refund.

    result = (
        await context.bot.refund_star_payment(
            user_id=user_id,
            telegram_payment_charge_id=(
                telegram_charge_id
            )
        )
    )

    if not result:

        raise RuntimeError(
            "Telegram refundni tasdiqlamadi."
        )

    now = iso_now()

    conn = db_connect()

    try:

        conn.execute(
            "BEGIN IMMEDIATE"
        )

        # Telegram qaytargan Stars ichki
        # balansdan ham olib tashlanadi.

        current = conn.execute(
            """
            SELECT internal_balance
            FROM users
            WHERE user_id = ?
            """,
            (user_id,)
        ).fetchone()

        current_balance = safe_int(
            current["internal_balance"]
        )

        if current_balance < amount:

            raise ValueError(
                "Refunddan keyingi balans "
                "tekshiruvi muvaffaqiyatsiz."
            )

        new_balance = (
            current_balance
            - amount
        )

        conn.execute(
            """
            UPDATE users
            SET
                internal_balance = ?,
                updated_at = ?
            WHERE user_id = ?
            """,
            (
                new_balance,
                now,
                user_id,
            )
        )

        conn.execute(
            """
            UPDATE star_payments
            SET
                status = 'REFUNDED',
                refunded_at = ?
            WHERE telegram_payment_charge_id = ?
            """,
            (
                now,
                telegram_charge_id,
            )
        )

        conn.execute(
            """
            INSERT INTO balance_transactions (
                user_id,
                amount,
                transaction_type,
                reference,
                description,
                created_by,
                created_at
            )
            VALUES (
                ?, ?, 'STAR_REFUND',
                ?, ?, ?, ?
            )
            """,
            (
                user_id,
                -amount,
                telegram_charge_id,
                "Telegram Stars to'lovi qaytarildi",
                actor_id,
                now,
            )
        )

        conn.execute(
            """
            INSERT INTO transactions (
                user_id,
                transaction_type,
                amount,
                currency,
                status,
                reference,
                description,
                created_by,
                created_at
            )
            VALUES (
                ?,
                'STAR_REFUND',
                ?,
                'XTR',
                'SUCCESS',
                ?,
                ?,
                ?,
                ?
            )
            """,
            (
                user_id,
                -amount,
                telegram_charge_id,
                "Telegram Stars refund",
                actor_id,
                now,
            )
        )

        conn.commit()

    except Exception:

        conn.rollback()

        # Telegram refund muvaffaqiyatli bo'lgan
        # bo'lishi mumkin, shuning uchun bu xato
        # albatta logda qolishi kerak.

        logger.critical(
            "Telegram refund bajarildi, "
            "lekin lokal DB yangilanmadi. "
            "charge=%s",
            telegram_charge_id
        )

        raise

    finally:

        conn.close()

    audit(
        "STAR_PAYMENT_REFUNDED",
        actor_id=actor_id,
        target_user_id=user_id,
        details=(
            f"amount={amount}; "
            f"charge={telegram_charge_id}"
        )
    )

    return {
        "user_id": user_id,
        "amount": amount,
        "new_balance": new_balance,
    }


# =========================================================
# PAYMENT CALLBACK ROUTER
# =========================================================

async def payment_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    if not query:
        return

    data = query.data or ""

    if data == "payment:topup":

        await show_topup_menu(
            update,
            context
        )

        return

    if data.startswith(
        "payment:topup:"
    ):

        try:

            amount = int(
                data.rsplit(
                    ":",
                    1
                )[1]
            )

        except ValueError:

            await query.answer(
                "❌ Noto'g'ri summa.",
                show_alert=True
            )

            return

        await create_star_topup_invoice(
            update,
            context,
            amount
        )

        return

    if data == "payment:history":

        await show_payment_history(
            update,
            context
        )

        return


# =========================================================
# END PART 3
# =========================================================
# =========================================================
# VERITAS BOT V7
# PART 4 — TELEGRAM PREMIUM & GIFTS
# =========================================================


# =========================================================
# PREMIUM MENU
# =========================================================

def premium_month_keyboard(
    recipient_user_id: int
):

    rows = []

    for months, stars in PREMIUM_OPTIONS.items():

        rows.append(
            [
                InlineKeyboardButton(
                    f"💎 {months} oy — {stars} ⭐",
                    callback_data=(
                        f"premium:select:"
                        f"{recipient_user_id}:"
                        f"{months}"
                    )
                )
            ]
        )

    rows.append(
        [
            InlineKeyboardButton(
                "❌ Bekor qilish",
                callback_data="super:rewards"
            )
        ]
    )

    return InlineKeyboardMarkup(rows)


# =========================================================
# PREMIUM CONFIRMATION
# =========================================================

def premium_confirm_keyboard(
    recipient_user_id: int,
    months: int
):

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Premium yuborish",
                    callback_data=(
                        f"premium:confirm:"
                        f"{recipient_user_id}:"
                        f"{months}"
                    )
                )
            ],
            [
                InlineKeyboardButton(
                    "❌ Bekor qilish",
                    callback_data="super:rewards"
                )
            ]
        ]
    )


# =========================================================
# PREMIUM PREVIEW
# =========================================================

async def show_premium_confirmation(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    recipient_user_id: int,
    months: int
):

    if not await require_super_owner(update):
        return

    query = update.callback_query

    if not query:
        return

    stars = PREMIUM_OPTIONS.get(
        months
    )

    if not stars:

        await query.answer(
            "❌ Premium muddati noto'g'ri.",
            show_alert=True
        )

        return

    try:

        chat = await context.bot.get_chat(
            recipient_user_id
        )

        recipient_name = (
            chat.full_name
            or chat.username
            or str(recipient_user_id)
        )

    except TelegramError:

        recipient_name = str(
            recipient_user_id
        )

    PENDING_PREMIUM[
        query.from_user.id
    ] = {
        "recipient_user_id":
            recipient_user_id,

        "months":
            months,

        "stars":
            stars,
    }

    text = (
        "💎 TELEGRAM PREMIUM\n\n"
        f"👤 Qabul qiluvchi: "
        f"{recipient_name}\n"
        f"🆔 ID: {recipient_user_id}\n\n"
        f"📅 Muddat: {months} oy\n"
        f"⭐ Narxi: {stars} Stars\n\n"
        "⚠️ Tasdiqlasangiz, Telegram "
        "botning haqiqiy Stars balansidan "
        "ushbu summani yechadi."
    )

    await query.answer()

    await query.edit_message_text(
        text=text,
        reply_markup=(
            premium_confirm_keyboard(
                recipient_user_id,
                months
            )
        )
    )


# =========================================================
# SEND REAL TELEGRAM PREMIUM
# =========================================================

async def send_real_telegram_premium(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    recipient_user_id: int,
    months: int,
    requested_by: int,
    gift_text: str = (
        "🎁 VeritasBot'dan "
        "Telegram Premium sovg'asi!"
    ),
):

    if not is_super_owner_id(
        requested_by
    ):

        raise PermissionError(
            "Faqat Super Ega "
            "Premium yubora oladi."
        )

    stars = PREMIUM_OPTIONS.get(
        months
    )

    if not stars:

        raise ValueError(
            "Premium faqat "
            "3, 6 yoki 12 oyga beriladi."
        )

    # ---------------------------------------------
    # Botning real Telegram Stars balansini tekshirish
    # ---------------------------------------------

    star_balance = (
        await context.bot.get_my_star_balance()
    )

    real_balance = safe_int(
        getattr(
            star_balance,
            "amount",
            0
        )
    )

    if real_balance < stars:

        raise ValueError(
            "Botning Telegram Stars "
            "balansi yetarli emas.\n"
            f"Kerak: {stars} ⭐\n"
            f"Mavjud: {real_balance} ⭐"
        )

    now = iso_now()

    conn = db_connect()

    try:

        cursor = conn.execute(
            """
            INSERT INTO premium_gifts (
                recipient_user_id,
                month_count,
                star_count,
                text,
                status,
                requested_by,
                created_at
            )
            VALUES (
                ?, ?, ?, ?,
                'PENDING',
                ?, ?
            )
            """,
            (
                recipient_user_id,
                months,
                stars,
                gift_text,
                requested_by,
                now,
            )
        )

        premium_record_id = (
            cursor.lastrowid
        )

        conn.commit()

    finally:

        conn.close()

    try:

        # =========================================
        # HAQIQIY TELEGRAM PREMIUM
        # =========================================

        result = (
            await context.bot
            .gift_premium_subscription(
                user_id=recipient_user_id,
                month_count=months,
                star_count=stars,
                text=gift_text
            )
        )

        if result is False:

            raise RuntimeError(
                "Telegram Premium "
                "yuborishni tasdiqlamadi."
            )

    except Exception as exc:

        db_execute(
            """
            UPDATE premium_gifts
            SET
                status = 'FAILED',
                error_message = ?
            WHERE id = ?
            """,
            (
                error_text(exc),
                premium_record_id,
            )
        )

        add_transaction(
            transaction_type=(
                "TELEGRAM_PREMIUM"
            ),
            user_id=recipient_user_id,
            amount=-stars,
            status="FAILED",
            description=(
                f"{months} oylik "
                "Telegram Premium"
            ),
            metadata={
                "months": months,
                "record_id":
                    premium_record_id,
            },
            created_by=requested_by,
        )

        audit(
            "PREMIUM_GIFT_FAILED",
            actor_id=requested_by,
            target_user_id=(
                recipient_user_id
            ),
            details=(
                f"months={months}; "
                f"stars={stars}; "
                f"error={error_text(exc)}"
            )
        )

        raise

    completed_at = iso_now()

    db_execute(
        """
        UPDATE premium_gifts
        SET
            status = 'SUCCESS',
            completed_at = ?
        WHERE id = ?
        """,
        (
            completed_at,
            premium_record_id,
        )
    )

    db_execute(
        """
        INSERT INTO user_rewards (
            user_id,
            reward_type,
            reward_value,
            star_value,
            reason,
            status,
            granted_by,
            created_at
        )
        VALUES (
            ?,
            'TELEGRAM_PREMIUM',
            ?,
            ?,
            ?,
            'GRANTED',
            ?,
            ?
        )
        """,
        (
            recipient_user_id,
            f"{months}_MONTHS",
            stars,
            (
                f"{months} oylik "
                "Telegram Premium"
            ),
            requested_by,
            completed_at,
        )
    )

    add_transaction(
        transaction_type=(
            "TELEGRAM_PREMIUM"
        ),
        user_id=recipient_user_id,
        amount=-stars,
        status="SUCCESS",
        description=(
            f"{months} oylik "
            "Telegram Premium yuborildi"
        ),
        metadata={
            "months": months,
            "record_id":
                premium_record_id,
        },
        created_by=requested_by,
    )

    audit(
        "PREMIUM_GIFT_SUCCESS",
        actor_id=requested_by,
        target_user_id=recipient_user_id,
        details=(
            f"months={months}; "
            f"stars={stars}"
        )
    )

    return {
        "recipient_user_id":
            recipient_user_id,

        "months":
            months,

        "stars":
            stars,

        "record_id":
            premium_record_id,
    }


# =========================================================
# PREMIUM CONFIRM CALLBACK
# =========================================================

async def confirm_premium_gift(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    recipient_user_id: int,
    months: int
):

    if not await require_super_owner(update):
        return

    query = update.callback_query

    if not query:
        return

    await query.answer(
        "⏳ Premium yuborilmoqda..."
    )

    try:

        result = (
            await send_real_telegram_premium(
                context,
                recipient_user_id=(
                    recipient_user_id
                ),
                months=months,
                requested_by=(
                    query.from_user.id
                ),
            )
        )

        PENDING_PREMIUM.pop(
            query.from_user.id,
            None
        )

        await query.edit_message_text(
            (
                "✅ TELEGRAM PREMIUM "
                "YUBORILDI\n\n"
                f"👤 User ID: "
                f"{recipient_user_id}\n"
                f"💎 Premium: "
                f"{result['months']} oy\n"
                f"⭐ Sarflandi: "
                f"{result['stars']} Stars"
            ),
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "⬅️ Mukofotlar",
                            callback_data=(
                                "super:rewards"
                            )
                        )
                    ]
                ]
            )
        )

    except Exception as exc:

        logger.exception(
            "Premium yuborishda xato."
        )

        await query.edit_message_text(
            (
                "❌ PREMIUM YUBORILMADI\n\n"
                f"{error_text(exc)}"
            ),
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "⬅️ Orqaga",
                            callback_data=(
                                "super:rewards"
                            )
                        )
                    ]
                ]
            )
        )


# =========================================================
# AVAILABLE TELEGRAM GIFTS
# =========================================================

async def get_available_telegram_gifts(
    context: ContextTypes.DEFAULT_TYPE
):

    gifts = (
        await context.bot
        .get_available_gifts()
    )

    return getattr(
        gifts,
        "gifts",
        []
    )


# =========================================================
# GIFT MENU
# =========================================================

async def show_gift_selection(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    recipient_user_id: int
):

    if not await require_super_owner(update):
        return

    query = update.callback_query

    try:

        gifts = (
            await get_available_telegram_gifts(
                context
            )
        )

    except TelegramError as exc:

        if query:

            await query.answer()

            await query.edit_message_text(
                (
                    "❌ Telegram Gift "
                    "ro'yxatini olib bo'lmadi.\n\n"
                    f"{error_text(exc)}"
                )
            )

        return

    if not gifts:

        if query:

            await query.answer(
                "Hozir mavjud Gift yo'q.",
                show_alert=True
            )

        return

    rows = []

    # Menyuni juda kattalashtirmaslik
    # uchun dastlabki 20 Gift.

    for gift in gifts[:20]:

        gift_id = str(
            getattr(
                gift,
                "id",
                ""
            )
        )

        star_count = safe_int(
            getattr(
                gift,
                "star_count",
                0
            )
        )

        if not gift_id:
            continue

        rows.append(
            [
                InlineKeyboardButton(
                    f"🎁 {star_count} ⭐",
                    callback_data=(
                        f"gift:select:"
                        f"{recipient_user_id}:"
                        f"{gift_id}"
                    )
                )
            ]
        )

    rows.append(
        [
            InlineKeyboardButton(
                "⬅️ Mukofotlar",
                callback_data="super:rewards"
            )
        ]
    )

    text = (
        "🎁 TELEGRAM GIFT\n\n"
        f"👤 User ID: "
        f"{recipient_user_id}\n\n"
        "Yuboriladigan Giftni tanlang:"
    )

    if query:

        await query.answer()

        await query.edit_message_text(
            text,
            reply_markup=(
                InlineKeyboardMarkup(rows)
            )
        )


# =========================================================
# FIND GIFT
# =========================================================

async def find_available_gift(
    context: ContextTypes.DEFAULT_TYPE,
    gift_id: str
):

    gifts = (
        await get_available_telegram_gifts(
            context
        )
    )

    for gift in gifts:

        current_id = str(
            getattr(
                gift,
                "id",
                ""
            )
        )

        if current_id == str(gift_id):
            return gift

    return None


# =========================================================
# GIFT CONFIRM MENU
# =========================================================

async def show_gift_confirmation(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    recipient_user_id: int,
    gift_id: str
):

    if not await require_super_owner(update):
        return

    query = update.callback_query

    if not query:
        return

    try:

        gift = await find_available_gift(
            context,
            gift_id
        )

    except TelegramError as exc:

        await query.answer(
            error_text(exc),
            show_alert=True
        )

        return

    if not gift:

        await query.answer(
            "❌ Gift topilmadi.",
            show_alert=True
        )

        return

    stars = safe_int(
        getattr(
            gift,
            "star_count",
            0
        )
    )

    PENDING_GIFTS[
        query.from_user.id
    ] = {
        "recipient_user_id":
            recipient_user_id,

        "gift_id":
            gift_id,

        "stars":
            stars,
    }

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Gift yuborish",
                    callback_data=(
                        f"gift:confirm:"
                        f"{recipient_user_id}:"
                        f"{gift_id}"
                    )
                )
            ],
            [
                InlineKeyboardButton(
                    "❌ Bekor qilish",
                    callback_data="super:rewards"
                )
            ]
        ]
    )

    await query.answer()

    await query.edit_message_text(
        (
            "🎁 GIFTNI TASDIQLASH\n\n"
            f"👤 User ID: "
            f"{recipient_user_id}\n"
            f"🎁 Gift ID: "
            f"{gift_id}\n"
            f"⭐ Narxi: "
            f"{stars} Stars\n\n"
            "Tasdiqlasangiz Gift "
            "Telegram orqali yuboriladi."
        ),
        reply_markup=keyboard
    )


# =========================================================
# SEND REAL TELEGRAM GIFT
# =========================================================

async def send_real_telegram_gift(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    recipient_user_id: int,
    gift_id: str,
    requested_by: int,
    gift_text: str = (
        "🎁 VeritasBot'dan sovg'a!"
    ),
):

    if not is_super_owner_id(
        requested_by
    ):

        raise PermissionError(
            "Faqat Super Ega "
            "Gift yubora oladi."
        )

    gift = await find_available_gift(
        context,
        gift_id
    )

    if not gift:

        raise ValueError(
            "Telegram Gift topilmadi "
            "yoki endi mavjud emas."
        )

    stars = safe_int(
        getattr(
            gift,
            "star_count",
            0
        )
    )

    # ---------------------------------------------
    # Real Stars balans
    # ---------------------------------------------

    star_balance = (
        await context.bot.get_my_star_balance()
    )

    real_balance = safe_int(
        getattr(
            star_balance,
            "amount",
            0
        )
    )

    if real_balance < stars:

        raise ValueError(
            "Botning Stars balansi "
            "yetarli emas.\n"
            f"Kerak: {stars} ⭐\n"
            f"Mavjud: {real_balance} ⭐"
        )

    now = iso_now()

    conn = db_connect()

    try:

        cursor = conn.execute(
            """
            INSERT INTO telegram_gifts (
                recipient_user_id,
                gift_id,
                star_count,
                text,
                status,
                requested_by,
                created_at
            )
            VALUES (
                ?, ?, ?, ?,
                'PENDING',
                ?, ?
            )
            """,
            (
                recipient_user_id,
                gift_id,
                stars,
                gift_text,
                requested_by,
                now,
            )
        )

        record_id = cursor.lastrowid

        conn.commit()

    finally:

        conn.close()

    try:

        # =========================================
        # HAQIQIY TELEGRAM GIFT
        # =========================================

        result = (
            await context.bot.send_gift(
                user_id=recipient_user_id,
                gift_id=gift_id,
                text=gift_text
            )
        )

        if result is False:

            raise RuntimeError(
                "Telegram Gift yuborishni "
                "tasdiqlamadi."
            )

    except Exception as exc:

        db_execute(
            """
            UPDATE telegram_gifts
            SET
                status = 'FAILED',
                error_message = ?
            WHERE id = ?
            """,
            (
                error_text(exc),
                record_id,
            )
        )

        add_transaction(
            transaction_type=(
                "TELEGRAM_GIFT"
            ),
            user_id=recipient_user_id,
            amount=-stars,
            status="FAILED",
            description=(
                f"Telegram Gift: {gift_id}"
            ),
            metadata={
                "gift_id": gift_id,
                "record_id": record_id,
            },
            created_by=requested_by,
        )

        audit(
            "TELEGRAM_GIFT_FAILED",
            actor_id=requested_by,
            target_user_id=(
                recipient_user_id
            ),
            details=(
                f"gift_id={gift_id}; "
                f"error={error_text(exc)}"
            )
        )

        raise

    completed_at = iso_now()

    db_execute(
        """
        UPDATE telegram_gifts
        SET
            status = 'SUCCESS',
            completed_at = ?
        WHERE id = ?
        """,
        (
            completed_at,
            record_id,
        )
    )

    db_execute(
        """
        INSERT INTO user_rewards (
            user_id,
            reward_type,
            reward_value,
            star_value,
            reason,
            status,
            granted_by,
            created_at
        )
        VALUES (
            ?,
            'TELEGRAM_GIFT',
            ?,
            ?,
            ?,
            'GRANTED',
            ?,
            ?
        )
        """,
        (
            recipient_user_id,
            gift_id,
            stars,
            "Telegram Gift",
            requested_by,
            completed_at,
        )
    )

    add_transaction(
        transaction_type=(
            "TELEGRAM_GIFT"
        ),
        user_id=recipient_user_id,
        amount=-stars,
        status="SUCCESS",
        description=(
            f"Telegram Gift yuborildi: "
            f"{gift_id}"
        ),
        metadata={
            "gift_id": gift_id,
            "record_id": record_id,
        },
        created_by=requested_by,
    )

    audit(
        "TELEGRAM_GIFT_SUCCESS",
        actor_id=requested_by,
        target_user_id=recipient_user_id,
        details=(
            f"gift_id={gift_id}; "
            f"stars={stars}"
        )
    )

    return {
        "recipient_user_id":
            recipient_user_id,

        "gift_id":
            gift_id,

        "stars":
            stars,

        "record_id":
            record_id,
    }


# =========================================================
# CONFIRM REAL GIFT
# =========================================================

async def confirm_telegram_gift(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    recipient_user_id: int,
    gift_id: str
):

    if not await require_super_owner(update):
        return

    query = update.callback_query

    if not query:
        return

    await query.answer(
        "⏳ Gift yuborilmoqda..."
    )

    try:

        result = (
            await send_real_telegram_gift(
                context,
                recipient_user_id=(
                    recipient_user_id
                ),
                gift_id=gift_id,
                requested_by=(
                    query.from_user.id
                ),
            )
        )

        PENDING_GIFTS.pop(
            query.from_user.id,
            None
        )

        await query.edit_message_text(
            (
                "✅ TELEGRAM GIFT YUBORILDI\n\n"
                f"👤 User ID: "
                f"{recipient_user_id}\n"
                f"🎁 Gift: "
                f"{result['gift_id']}\n"
                f"⭐ Sarflandi: "
                f"{result['stars']} Stars"
            ),
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "⬅️ Mukofotlar",
                            callback_data=(
                                "super:rewards"
                            )
                        )
                    ]
                ]
            )
        )

    except Exception as exc:

        logger.exception(
            "Telegram Gift yuborishda xato."
        )

        await query.edit_message_text(
            (
                "❌ GIFT YUBORILMADI\n\n"
                f"{error_text(exc)}"
            ),
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "⬅️ Orqaga",
                            callback_data=(
                                "super:rewards"
                            )
                        )
                    ]
                ]
            )
        )


# =========================================================
# PREMIUM CALLBACK ROUTER
# =========================================================

async def premium_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    if not query:
        return

    data = query.data or ""

    if data.startswith(
        "premium:select:"
    ):

        parts = data.split(":")

        if len(parts) != 4:
            return

        try:

            recipient_user_id = int(
                parts[2]
            )

            months = int(
                parts[3]
            )

        except ValueError:

            await query.answer(
                "❌ Ma'lumot noto'g'ri.",
                show_alert=True
            )

            return

        await show_premium_confirmation(
            update,
            context,
            recipient_user_id,
            months
        )

        return

    if data.startswith(
        "premium:confirm:"
    ):

        parts = data.split(":")

        if len(parts) != 4:
            return

        try:

            recipient_user_id = int(
                parts[2]
            )

            months = int(
                parts[3]
            )

        except ValueError:

            await query.answer(
                "❌ Ma'lumot noto'g'ri.",
                show_alert=True
            )

            return

        await confirm_premium_gift(
            update,
            context,
            recipient_user_id,
            months
        )


# =========================================================
# GIFT CALLBACK ROUTER
# =========================================================

async def gift_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    if not query:
        return

    data = query.data or ""

    if data.startswith(
        "gift:select:"
    ):

        parts = data.split(
            ":",
            3
        )

        if len(parts) != 4:
            return

        try:

            recipient_user_id = int(
                parts[2]
            )

        except ValueError:

            await query.answer(
                "❌ User ID noto'g'ri.",
                show_alert=True
            )

            return

        gift_id = parts[3]

        await show_gift_confirmation(
            update,
            context,
            recipient_user_id,
            gift_id
        )

        return

    if data.startswith(
        "gift:confirm:"
    ):

        parts = data.split(
            ":",
            3
        )

        if len(parts) != 4:
            return

        try:

            recipient_user_id = int(
                parts[2]
            )

        except ValueError:

            await query.answer(
                "❌ User ID noto'g'ri.",
                show_alert=True
            )

            return

        gift_id = parts[3]

        await confirm_telegram_gift(
            update,
            context,
            recipient_user_id,
            gift_id
        )


# =========================================================
# END PART 4
# =========================================================
# =========================================================
# VERITAS BOT V7
# PART 5 — SUPER OWNER REWARDS PANEL
# =========================================================


# =========================================================
# SUPER REWARDS MAIN MENU
# =========================================================

def super_rewards_keyboard():

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "💎 Telegram Premium",
                    callback_data="super:reward_premium"
                )
            ],
            [
                InlineKeyboardButton(
                    "🎁 Telegram Gift",
                    callback_data="super:reward_gift"
                )
            ],
            [
                InlineKeyboardButton(
                    "⭐ Veritas Stars berish",
                    callback_data="super:reward_stars"
                )
            ],
            [
                InlineKeyboardButton(
                    "📜 Mukofotlar tarixi",
                    callback_data="super:reward_history"
                )
            ],
            [
                InlineKeyboardButton(
                    "⭐ Bot Stars balansi",
                    callback_data="super:real_star_balance"
                )
            ],
            [
                InlineKeyboardButton(
                    "⬅️ Super Ega",
                    callback_data="super:home"
                )
            ]
        ]
    )


# =========================================================
# SHOW REWARDS PANEL
# =========================================================

async def show_super_rewards(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not await require_super_owner(update):
        return

    text = (
        "🎁 MUKOFOTLAR\n\n"
        "Bu bo'lim orqali foydalanuvchiga:\n\n"
        "💎 Telegram Premium\n"
        "🎁 Telegram Gift\n"
        "⭐ Veritas Stars\n\n"
        "berishingiz mumkin.\n\n"
        "Premium va Telegram Gift botning "
        "haqiqiy Telegram Stars balansidan "
        "sarflanadi."
    )

    if update.callback_query:

        query = update.callback_query

        await query.answer()

        await query.edit_message_text(
            text,
            reply_markup=(
                super_rewards_keyboard()
            )
        )

    elif update.effective_message:

        await update.effective_message.reply_text(
            text,
            reply_markup=(
                super_rewards_keyboard()
            )
        )


# =========================================================
# ASK USER ID
# =========================================================

async def ask_reward_user_id(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    reward_type: str
):

    if not await require_super_owner(update):
        return

    user = update.effective_user

    if not user:
        return

    USER_STATES[user.id] = {
        "state": "WAIT_REWARD_USER_ID",
        "reward_type": reward_type,
    }

    names = {
        "premium": "💎 Telegram Premium",
        "gift": "🎁 Telegram Gift",
        "stars": "⭐ Veritas Stars",
    }

    title = names.get(
        reward_type,
        "🎁 Mukofot"
    )

    text = (
        f"{title}\n\n"
        "Mukofot oladigan foydalanuvchining "
        "Telegram ID raqamini yuboring.\n\n"
        "Masalan:\n"
        "123456789\n\n"
        "❗ Foydalanuvchi oldin bot bilan "
        "aloqa qilgan bo'lishi tavsiya etiladi."
    )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "❌ Bekor qilish",
                    callback_data="super:rewards"
                )
            ]
        ]
    )

    if update.callback_query:

        await update.callback_query.answer()

        await update.callback_query.edit_message_text(
            text,
            reply_markup=keyboard
        )

    else:

        await update.effective_message.reply_text(
            text,
            reply_markup=keyboard
        )


# =========================================================
# VERIFY TARGET USER
# =========================================================

async def resolve_reward_target(
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int
):

    try:

        chat = await context.bot.get_chat(
            user_id
        )

        name = (
            getattr(chat, "full_name", None)
            or getattr(chat, "username", None)
            or str(user_id)
        )

        username = getattr(
            chat,
            "username",
            None
        )

        return {
            "exists": True,
            "user_id": user_id,
            "name": name,
            "username": username,
        }

    except TelegramError:

        # Foydalanuvchi bazada mavjud
        # bo'lishi mumkin.

        row = get_user_record(
            user_id
        )

        if row:

            name = (
                row["first_name"]
                or row["username"]
                or str(user_id)
            )

            return {
                "exists": True,
                "user_id": user_id,
                "name": name,
                "username": row["username"],
            }

        return {
            "exists": False,
            "user_id": user_id,
            "name": str(user_id),
            "username": None,
        }


# =========================================================
# HANDLE REWARD USER ID
# =========================================================

async def handle_reward_user_id(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user
    message = update.effective_message

    if not user or not message:
        return False

    state = USER_STATES.get(
        user.id
    )

    if not state:
        return False

    if (
        state.get("state")
        != "WAIT_REWARD_USER_ID"
    ):
        return False

    if not is_super_owner_id(user.id):

        USER_STATES.pop(
            user.id,
            None
        )

        return True

    text = (
        message.text or ""
    ).strip()

    try:

        target_user_id = int(text)

    except ValueError:

        await message.reply_text(
            "❌ Telegram ID faqat "
            "raqamlardan iborat bo'lishi kerak.\n\n"
            "Masalan: 123456789"
        )

        return True

    if target_user_id <= 0:

        await message.reply_text(
            "❌ User ID noto'g'ri."
        )

        return True

    target = (
        await resolve_reward_target(
            context,
            target_user_id
        )
    )

    if not target["exists"]:

        await message.reply_text(
            (
                "❌ Bu foydalanuvchini "
                "topa olmadim.\n\n"
                "Foydalanuvchi avval "
                "VeritasBot'ga /start "
                "yuborsin, keyin qayta urinib ko'ring."
            )
        )

        return True

    reward_type = state.get(
        "reward_type"
    )

    USER_STATES.pop(
        user.id,
        None
    )

    if reward_type == "premium":

        await message.reply_text(
            (
                "💎 TELEGRAM PREMIUM\n\n"
                f"👤 {target['name']}\n"
                f"🆔 {target_user_id}\n\n"
                "Premium muddatini tanlang:"
            ),
            reply_markup=(
                premium_month_keyboard(
                    target_user_id
                )
            )
        )

        return True

    if reward_type == "gift":

        # Gift menyusi callback uchun
        # yozilgani sababli bu yerda
        # alohida message versiyasi.

        try:

            gifts = (
                await get_available_telegram_gifts(
                    context
                )
            )

        except Exception as exc:

            await message.reply_text(
                (
                    "❌ Telegram Gift ro'yxatini "
                    "olib bo'lmadi.\n\n"
                    f"{error_text(exc)}"
                )
            )

            return True

        if not gifts:

            await message.reply_text(
                "ℹ️ Hozir yuborish uchun "
                "Telegram Gift mavjud emas."
            )

            return True

        rows = []

        for gift in gifts[:20]:

            gift_id = str(
                getattr(
                    gift,
                    "id",
                    ""
                )
            )

            stars = safe_int(
                getattr(
                    gift,
                    "star_count",
                    0
                )
            )

            if not gift_id:
                continue

            rows.append(
                [
                    InlineKeyboardButton(
                        f"🎁 {stars} ⭐",
                        callback_data=(
                            f"gift:select:"
                            f"{target_user_id}:"
                            f"{gift_id}"
                        )
                    )
                ]
            )

        rows.append(
            [
                InlineKeyboardButton(
                    "❌ Bekor qilish",
                    callback_data="super:rewards"
                )
            ]
        )

        await message.reply_text(
            (
                "🎁 TELEGRAM GIFT\n\n"
                f"👤 {target['name']}\n"
                f"🆔 {target_user_id}\n\n"
                "Giftni tanlang:"
            ),
            reply_markup=(
                InlineKeyboardMarkup(rows)
            )
        )

        return True

    if reward_type == "stars":

        USER_STATES[user.id] = {
            "state":
                "WAIT_REWARD_STARS_AMOUNT",

            "target_user_id":
                target_user_id,

            "target_name":
                target["name"],
        }

        await message.reply_text(
            (
                "⭐ VERITAS STARS\n\n"
                f"👤 {target['name']}\n"
                f"🆔 {target_user_id}\n\n"
                "Beriladigan Stars "
                "miqdorini yozing.\n\n"
                "Masalan: 100"
            ),
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "❌ Bekor qilish",
                            callback_data=(
                                "super:rewards"
                            )
                        )
                    ]
                ]
            )
        )

        return True

    return True


# =========================================================
# VERITAS STARS CONFIRM KEYBOARD
# =========================================================

def reward_stars_confirm_keyboard(
    target_user_id: int,
    amount: int
):

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Stars berish",
                    callback_data=(
                        f"reward:stars_confirm:"
                        f"{target_user_id}:"
                        f"{amount}"
                    )
                )
            ],
            [
                InlineKeyboardButton(
                    "❌ Bekor qilish",
                    callback_data="super:rewards"
                )
            ]
        ]
    )


# =========================================================
# HANDLE STAR AMOUNT
# =========================================================

async def handle_reward_stars_amount(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user
    message = update.effective_message

    if not user or not message:
        return False

    state = USER_STATES.get(
        user.id
    )

    if not state:
        return False

    if (
        state.get("state")
        != "WAIT_REWARD_STARS_AMOUNT"
    ):
        return False

    if not is_super_owner_id(user.id):

        USER_STATES.pop(
            user.id,
            None
        )

        return True

    try:

        amount = int(
            (message.text or "").strip()
        )

    except ValueError:

        await message.reply_text(
            "❌ Miqdorni raqam bilan yozing.\n"
            "Masalan: 100"
        )

        return True

    if amount <= 0:

        await message.reply_text(
            "❌ Miqdor 0 dan katta "
            "bo'lishi kerak."
        )

        return True

    # Tasodifan juda katta miqdor
    # kiritilishining oldini olamiz.

    if amount > 1_000_000:

        await message.reply_text(
            "❌ Bir martada maksimal "
            "1 000 000 Veritas Stars."
        )

        return True

    target_user_id = safe_int(
        state.get(
            "target_user_id"
        )
    )

    target_name = state.get(
        "target_name"
    ) or str(target_user_id)

    USER_STATES.pop(
        user.id,
        None
    )

    await message.reply_text(
        (
            "⭐ STARS BERISHNI TASDIQLANG\n\n"
            f"👤 {target_name}\n"
            f"🆔 {target_user_id}\n"
            f"⭐ Miqdor: {amount}\n\n"
            "Bu Veritas ichki balansiga "
            "qo'shiladi."
        ),
        reply_markup=(
            reward_stars_confirm_keyboard(
                target_user_id,
                amount
            )
        )
    )

    return True


# =========================================================
# GIVE VERITAS STARS
# =========================================================

async def grant_veritas_stars(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    target_user_id: int,
    amount: int
):

    if not await require_super_owner(update):
        return

    query = update.callback_query

    if not query:
        return

    if amount <= 0:

        await query.answer(
            "❌ Miqdor noto'g'ri.",
            show_alert=True
        )

        return

    target = get_user_record(
        target_user_id
    )

    if not target:

        await query.answer(
            "❌ Foydalanuvchi bazada yo'q.",
            show_alert=True
        )

        return

    try:

        new_balance = (
            change_internal_balance(
                target_user_id,
                amount,
                "ADMIN_REWARD",
                description=(
                    "Super Ega tomonidan "
                    "Veritas Stars berildi"
                ),
                reference=(
                    f"reward:{utc_timestamp()}"
                ),
                created_by=(
                    query.from_user.id
                ),
            )
        )

        db_execute(
            """
            INSERT INTO user_rewards (
                user_id,
                reward_type,
                reward_value,
                star_value,
                reason,
                status,
                granted_by,
                created_at
            )
            VALUES (
                ?,
                'VERITAS_STARS',
                ?,
                ?,
                ?,
                'GRANTED',
                ?,
                ?
            )
            """,
            (
                target_user_id,
                str(amount),
                amount,
                (
                    "Super Ega tomonidan "
                    "Stars mukofoti"
                ),
                query.from_user.id,
                iso_now(),
            )
        )

        add_transaction(
            transaction_type="ADMIN_REWARD",
            user_id=target_user_id,
            amount=amount,
            status="SUCCESS",
            description=(
                "Veritas Stars mukofoti"
            ),
            created_by=query.from_user.id,
        )

        audit(
            "VERITAS_STARS_GRANTED",
            actor_id=query.from_user.id,
            target_user_id=target_user_id,
            details=f"amount={amount}"
        )

    except Exception as exc:

        logger.exception(
            "Stars mukofoti berishda xato."
        )

        await query.answer(
            error_text(exc),
            show_alert=True
        )

        return

    await query.answer(
        "✅ Stars berildi."
    )

    await query.edit_message_text(
        (
            "✅ VERITAS STARS BERILDI\n\n"
            f"👤 User ID: {target_user_id}\n"
            f"⭐ Berildi: {amount}\n"
            f"💰 Yangi balans: "
            f"{new_balance} ⭐"
        ),
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🎁 Mukofotlar",
                        callback_data="super:rewards"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "⬅️ Super Ega",
                        callback_data="super:home"
                    )
                ]
            ]
        )
    )

    # Foydalanuvchiga ham xabar yuborishga
    # harakat qilamiz.

    try:

        await context.bot.send_message(
            chat_id=target_user_id,
            text=(
                "🎁 SIZGA MUKOFOT BERILDI\n\n"
                f"⭐ +{amount} Veritas Stars\n"
                f"💰 Balansingiz: "
                f"{new_balance} ⭐"
            )
        )

    except TelegramError:

        # User botni bloklagan bo'lishi mumkin.
        pass


# =========================================================
# REWARD HISTORY
# =========================================================

async def show_reward_history(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not await require_super_owner(update):
        return

    rows = db_execute(
        """
        SELECT *
        FROM user_rewards
        ORDER BY id DESC
        LIMIT 20
        """,
        fetchall=True
    )

    lines = [
        "📜 MUKOFOTLAR TARIXI",
        ""
    ]

    if not rows:

        lines.append(
            "Hozircha mukofot yo'q."
        )

    else:

        for row in rows:

            reward_type = (
                row["reward_type"]
            )

            user_id = row["user_id"]

            value = (
                row["reward_value"]
                or "-"
            )

            stars = safe_int(
                row["star_value"]
            )

            created = row["created_at"]

            lines.append(
                (
                    f"🎁 {reward_type}\n"
                    f"👤 {user_id}\n"
                    f"📦 {value}\n"
                    f"⭐ {stars}\n"
                    f"🕒 {created}"
                )
            )

    text = "\n\n".join(lines)

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "⬅️ Mukofotlar",
                    callback_data="super:rewards"
                )
            ]
        ]
    )

    if update.callback_query:

        await update.callback_query.answer()

        await update.callback_query.edit_message_text(
            text,
            reply_markup=keyboard
        )

    else:

        await update.effective_message.reply_text(
            text,
            reply_markup=keyboard
        )


# =========================================================
# SUPER REWARD CALLBACK
# =========================================================

async def super_reward_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    if not query:
        return

    if not await require_super_owner(update):
        return

    data = query.data or ""

    if data == "super:rewards":

        USER_STATES.pop(
            query.from_user.id,
            None
        )

        await show_super_rewards(
            update,
            context
        )

        return

    if data == "super:reward_premium":

        await ask_reward_user_id(
            update,
            context,
            "premium"
        )

        return

    if data == "super:reward_gift":

        await ask_reward_user_id(
            update,
            context,
            "gift"
        )

        return

    if data == "super:reward_stars":

        await ask_reward_user_id(
            update,
            context,
            "stars"
        )

        return

    if data == "super:reward_history":

        await show_reward_history(
            update,
            context
        )

        return

    if data == "super:real_star_balance":

        await show_real_bot_star_balance(
            update,
            context
        )

        return


# =========================================================
# REWARD CALLBACK
# =========================================================

async def reward_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    if not query:
        return

    data = query.data or ""

    if data.startswith(
        "reward:stars_confirm:"
    ):

        parts = data.split(":")

        if len(parts) != 4:
            return

        try:

            target_user_id = int(
                parts[2]
            )

            amount = int(
                parts[3]
            )

        except ValueError:

            await query.answer(
                "❌ Ma'lumot noto'g'ri.",
                show_alert=True
            )

            return

        await grant_veritas_stars(
            update,
            context,
            target_user_id,
            amount
        )


# =========================================================
# REWARD TEXT STATE ROUTER
# =========================================================

async def reward_state_router(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    if not user:
        return False

    state = USER_STATES.get(
        user.id
    )

    if not state:
        return False

    current_state = state.get(
        "state"
    )

    if current_state == "WAIT_REWARD_USER_ID":

        return await handle_reward_user_id(
            update,
            context
        )

    if (
        current_state
        == "WAIT_REWARD_STARS_AMOUNT"
    ):

        return await handle_reward_stars_amount(
            update,
            context
        )

    return False


# =========================================================
# END PART 5
# =========================================================
# =========================================================
# VERITAS BOT V7
# PART 6 — PERSONAL CABINET
# =========================================================


# =========================================================
# MAIN CABINET KEYBOARD
# =========================================================

def user_cabinet_keyboard(
    user_id: int
):

    rows = [
        [
            InlineKeyboardButton(
                "👤 Profil",
                callback_data="user:profile"
            ),
            InlineKeyboardButton(
                "💰 Hisob",
                callback_data="user:wallet"
            )
        ],
        [
            InlineKeyboardButton(
                "🏢 Mening guruhlarim",
                callback_data="user:groups"
            )
        ],
        [
            InlineKeyboardButton(
                "💎 V7 obuna",
                callback_data="user:subscription"
            ),
            InlineKeyboardButton(
                "🎁 Mukofotlarim",
                callback_data="user:rewards"
            )
        ],
        [
            InlineKeyboardButton(
                "📚 Kutubxona",
                callback_data="user:library"
            ),
            InlineKeyboardButton(
                "🌐 Til",
                callback_data="user:language"
            )
        ],
        [
            InlineKeyboardButton(
                "➕ Botni guruhga qo'shish",
                url=(
                    "https://t.me/"
                    f"{BOT_USERNAME}"
                    "?startgroup=true"
                )
            )
        ]
    ]

    if is_super_owner_id(user_id):

        rows.append(
            [
                InlineKeyboardButton(
                    "👑 Super Ega",
                    callback_data="super:home"
                )
            ]
        )

    return InlineKeyboardMarkup(rows)


# =========================================================
# START COMMAND
# =========================================================

async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user
    chat = update.effective_chat

    if not user:
        return

    ensure_user(user)

    # /start guruhda yozilsa kabinetni
    # shaxsiy chatda ochishni taklif qiladi.

    if (
        chat
        and chat.type
        in (
            ChatType.GROUP,
            ChatType.SUPERGROUP,
        )
    ):

        ensure_group(
            chat,
            owner_id=user.id
        )

        me = await context.bot.get_me()

        await update.effective_message.reply_text(
            "👤 Veritas shaxsiy kabinetini "
            "ochish uchun pastdagi tugmani bosing.",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🤖 Kabinetni ochish",
                            url=(
                                f"https://t.me/"
                                f"{me.username}"
                                "?start=cabinet"
                            )
                        )
                    ]
                ]
            )
        )

        return

    await show_user_home(
        update,
        context
    )


# =========================================================
# USER HOME
# =========================================================

async def show_user_home(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    if not user:
        return

    ensure_user(user)

    row = get_user_record(
        user.id
    )

    balance = safe_int(
        row["internal_balance"]
        if row else 0
    )

    level = safe_int(
        row["level"]
        if row else 1,
        1
    )

    text = (
        "🏠 VERITAS SHAXSIY KABINET\n\n"
        f"👤 {user_display_name(user)}\n"
        f"🆔 {user.id}\n"
        f"⭐ Balans: {balance}\n"
        f"🏅 Daraja: {level}\n\n"
        "Kerakli bo'limni tanlang:"
    )

    keyboard = user_cabinet_keyboard(
        user.id
    )

    if update.callback_query:

        query = update.callback_query

        await query.answer()

        try:

            await query.edit_message_text(
                text,
                reply_markup=keyboard
            )

        except BadRequest:

            pass

    else:

        await update.effective_message.reply_text(
            text,
            reply_markup=keyboard
        )


# =========================================================
# PROFILE
# =========================================================

async def show_user_profile(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    if not user:
        return

    ensure_user(user)

    row = get_user_record(
        user.id
    )

    if not row:
        return

    xp = safe_int(
        row["xp"]
    )

    level = safe_int(
        row["level"],
        1
    )

    balance = safe_int(
        row["internal_balance"]
    )

    title = (
        row["title"]
        or "A'zo"
    )

    language = (
        SUPPORTED_LANGUAGES.get(
            row["language"],
            "🇺🇿 O'zbekcha"
        )
    )

    text = (
        "👤 PROFIL\n\n"
        f"👤 Ism: {user.full_name}\n"
        f"🆔 ID: {user.id}\n"
        f"🏷 Username: "
        f"{('@' + user.username) if user.username else 'yo‘q'}\n\n"
        f"🏅 Daraja: {level}\n"
        f"✨ XP: {xp}\n"
        f"🎖 Unvon: {title}\n"
        f"⭐ Balans: {balance}\n"
        f"🌐 Til: {language}"
    )

    await update.callback_query.answer()

    await update.callback_query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "⬅️ Kabinet",
                        callback_data="user:home"
                    )
                ]
            ]
        )
    )


# =========================================================
# USER GROUPS
# =========================================================

def get_user_groups(
    user_id: int
):

    # Guruh egasi yoki Veritas moderatori
    # bo'lgan guruhlarni chiqaradi.

    return db_execute(
        """
        SELECT DISTINCT
            g.chat_id,
            g.title,
            g.username,
            g.owner_id,
            g.is_active
        FROM groups g

        LEFT JOIN group_moderators gm
            ON gm.chat_id = g.chat_id

        WHERE
            g.owner_id = ?
            OR gm.user_id = ?

        ORDER BY g.title COLLATE NOCASE
        """,
        (
            user_id,
            user_id
        ),
        fetchall=True
    )


async def show_user_groups(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    if not user:
        return

    rows = get_user_groups(
        user.id
    )

    keyboard_rows = []

    if rows:

        for row in rows[:30]:

            title = (
                row["title"]
                or str(row["chat_id"])
            )

            keyboard_rows.append(
                [
                    InlineKeyboardButton(
                        f"🏢 {title[:40]}",
                        callback_data=(
                            f"group:open:"
                            f"{row['chat_id']}"
                        )
                    )
                ]
            )

        text = (
            "🏢 MENING GURUHLARIM\n\n"
            f"Jami: {len(rows)} ta\n\n"
            "Boshqarish uchun guruhni tanlang."
        )

    else:

        text = (
            "🏢 MENING GURUHLARIM\n\n"
            "Hozircha siz boshqaradigan "
            "Veritas guruhi topilmadi.\n\n"
            "Botni guruhingizga qo'shing va "
            "unga administrator huquqlarini bering."
        )

    me = await context.bot.get_me()

    keyboard_rows.append(
        [
            InlineKeyboardButton(
                "➕ Botni guruhga qo'shish",
                url=(
                    f"https://t.me/"
                    f"{me.username}"
                    "?startgroup=true"
                )
            )
        ]
    )

    keyboard_rows.append(
        [
            InlineKeyboardButton(
                "⬅️ Kabinet",
                callback_data="user:home"
            )
        ]
    )

    await update.callback_query.answer()

    await update.callback_query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(
            keyboard_rows
        )
    )


# =========================================================
# USER SUBSCRIPTION LIST
# =========================================================

async def show_user_subscriptions(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    if not user:
        return

    rows = db_execute(
        """
        SELECT
            g.chat_id,
            g.title,
            s.plan,
            s.status,
            s.expires_at,
            s.price_stars

        FROM groups g

        LEFT JOIN subscriptions s
            ON s.chat_id = g.chat_id

        LEFT JOIN group_moderators gm
            ON gm.chat_id = g.chat_id

        WHERE
            g.owner_id = ?
            OR gm.user_id = ?

        GROUP BY g.chat_id

        ORDER BY g.title COLLATE NOCASE
        """,
        (
            user.id,
            user.id
        ),
        fetchall=True
    )

    lines = [
        "💎 V7 OBUNA",
        ""
    ]

    keyboard_rows = []

    if not rows:

        lines.append(
            "Obuna boshqarish uchun "
            "avval VeritasBot'ni "
            "guruhingizga qo'shing."
        )

    else:

        for row in rows:

            title = (
                row["title"]
                or str(row["chat_id"])
            )

            plan = (
                row["plan"]
                or "YO'Q"
            )

            status = (
                row["status"]
                or "INACTIVE"
            )

            expires = (
                row["expires_at"]
                or "Cheklanmagan"
            )

            lines.append(
                f"🏢 {title}\n"
                f"💎 {plan}\n"
                f"📌 {status}\n"
                f"⏳ {expires}"
            )

            keyboard_rows.append(
                [
                    InlineKeyboardButton(
                        f"💎 {title[:32]}",
                        callback_data=(
                            f"user:subscription_group:"
                            f"{row['chat_id']}"
                        )
                    )
                ]
            )

    keyboard_rows.append(
        [
            InlineKeyboardButton(
                "⬅️ Kabinet",
                callback_data="user:home"
            )
        ]
    )

    await update.callback_query.answer()

    await update.callback_query.edit_message_text(
        "\n\n".join(lines),
        reply_markup=InlineKeyboardMarkup(
            keyboard_rows
        )
    )


# =========================================================
# SUBSCRIPTION GROUP
# =========================================================

async def show_subscription_group(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int
):

    user = update.effective_user
    query = update.callback_query

    if not user or not query:
        return

    group = get_group_record(
        chat_id
    )

    if not group:

        await query.answer(
            "❌ Guruh topilmadi.",
            show_alert=True
        )

        return

    # Foydalanuvchi ushbu guruhni
    # boshqarish huquqiga ega ekanini tekshiramiz.

    allowed = (
        safe_int(group["owner_id"])
        == user.id
    )

    if not allowed:

        moderator = db_execute(
            """
            SELECT 1
            FROM group_moderators
            WHERE
                chat_id = ?
                AND user_id = ?
            """,
            (
                chat_id,
                user.id
            ),
            fetchone=True
        )

        allowed = bool(moderator)

    if (
        not allowed
        and not is_super_owner_id(user.id)
    ):

        await query.answer(
            "⛔ Bu guruhni boshqara olmaysiz.",
            show_alert=True
        )

        return

    subscription = get_subscription(
        chat_id
    )

    if subscription:

        plan = subscription["plan"]
        status = subscription["status"]

        expires = (
            subscription["expires_at"]
            or "Cheklanmagan"
        )

    else:

        plan = "YO'Q"
        status = "INACTIVE"
        expires = "-"

    text = (
        "💎 GURUH OBUNASI\n\n"
        f"🏢 {group['title']}\n"
        f"🆔 {chat_id}\n\n"
        f"💎 Tarif: {plan}\n"
        f"📌 Holat: {status}\n"
        f"⏳ Tugash: {expires}\n\n"
        f"💳 7 kun V7: "
        f"{DEFAULT_V7_PRICE} ⭐"
    )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    f"💎 7 kun — "
                    f"{DEFAULT_V7_PRICE} ⭐",
                    callback_data=(
                        f"user:buy_v7:{chat_id}"
                    )
                )
            ],
            [
                InlineKeyboardButton(
                    "⬅️ Obunalar",
                    callback_data="user:subscription"
                )
            ]
        ]
    )

    await query.answer()

    await query.edit_message_text(
        text,
        reply_markup=keyboard
    )


# =========================================================
# BUY V7 USING INTERNAL BALANCE
# =========================================================

async def buy_v7_subscription(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int
):

    user = update.effective_user
    query = update.callback_query

    if not user or not query:
        return

    ensure_user(user)

    group = get_group_record(
        chat_id
    )

    if not group:

        await query.answer(
            "❌ Guruh topilmadi.",
            show_alert=True
        )

        return

    allowed = (
        safe_int(group["owner_id"])
        == user.id
    )

    if not allowed:

        moderator = db_execute(
            """
            SELECT 1
            FROM group_moderators
            WHERE
                chat_id = ?
                AND user_id = ?
            """,
            (
                chat_id,
                user.id
            ),
            fetchone=True
        )

        allowed = bool(moderator)

    if (
        not allowed
        and not is_super_owner_id(user.id)
    ):

        await query.answer(
            "⛔ Ruxsat yo'q.",
            show_alert=True
        )

        return

    balance = get_internal_balance(
        user.id
    )

    if balance < DEFAULT_V7_PRICE:

        await query.answer(
            (
                "❌ Balans yetarli emas.\n"
                f"Kerak: {DEFAULT_V7_PRICE} ⭐\n"
                f"Mavjud: {balance} ⭐"
            ),
            show_alert=True
        )

        return

    try:

        new_balance = (
            change_internal_balance(
                user.id,
                -DEFAULT_V7_PRICE,
                "V7_PURCHASE",
                description=(
                    f"{chat_id} guruh uchun "
                    "7 kunlik V7"
                ),
                reference=(
                    f"v7:{chat_id}:"
                    f"{utc_timestamp()}"
                ),
                created_by=user.id,
            )
        )

        grant_subscription(
            chat_id,
            plan="V7",
            days=DEFAULT_V7_DAYS,
            granted_by=user.id,
            price_stars=DEFAULT_V7_PRICE,
        )

        add_transaction(
            transaction_type="V7_PURCHASE",
            user_id=user.id,
            chat_id=chat_id,
            amount=-DEFAULT_V7_PRICE,
            currency="XTR",
            status="SUCCESS",
            description="7 kunlik Veritas V7",
            created_by=user.id,
        )

        audit(
            "V7_PURCHASED",
            actor_id=user.id,
            target_user_id=user.id,
            target_chat_id=chat_id,
            details=(
                f"price={DEFAULT_V7_PRICE}; "
                f"days={DEFAULT_V7_DAYS}"
            )
        )

    except Exception as exc:

        logger.exception(
            "V7 sotib olishda xato."
        )

        await query.answer(
            error_text(exc),
            show_alert=True
        )

        return

    await query.answer(
        "✅ V7 faollashtirildi.",
        show_alert=True
    )

    await query.edit_message_text(
        (
            "✅ V7 FAOLLASHTIRILDI\n\n"
            f"🏢 {group['title']}\n"
            f"💎 Muddat: "
            f"{DEFAULT_V7_DAYS} kun\n"
            f"⭐ To'landi: "
            f"{DEFAULT_V7_PRICE}\n"
            f"💰 Qolgan balans: "
            f"{new_balance} ⭐"
        ),
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🏢 Guruh",
                        callback_data=(
                            f"group:open:{chat_id}"
                        )
                    )
                ],
                [
                    InlineKeyboardButton(
                        "⬅️ Kabinet",
                        callback_data="user:home"
                    )
                ]
            ]
        )
    )


# =========================================================
# MY REWARDS
# =========================================================

async def show_my_rewards(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    if not user:
        return

    rows = db_execute(
        """
        SELECT *
        FROM user_rewards
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT 20
        """,
        (user.id,),
        fetchall=True
    )

    lines = [
        "🎁 MENING MUKOFOTLARIM",
        ""
    ]

    if not rows:

        lines.append(
            "Hozircha mukofot yo'q."
        )

    else:

        for row in rows:

            reward_type = (
                row["reward_type"]
            )

            value = (
                row["reward_value"]
                or "-"
            )

            stars = safe_int(
                row["star_value"]
            )

            lines.append(
                f"🎁 {reward_type}\n"
                f"📦 {value}\n"
                f"⭐ Qiymati: {stars}\n"
                f"🕒 {row['created_at']}"
            )

    await update.callback_query.answer()

    await update.callback_query.edit_message_text(
        "\n\n".join(lines),
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "⬅️ Kabinet",
                        callback_data="user:home"
                    )
                ]
            ]
        )
    )


# =========================================================
# LANGUAGE MENU
# =========================================================

def language_keyboard():

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🇺🇿 O'zbekcha",
                    callback_data="user:setlang:uz"
                )
            ],
            [
                InlineKeyboardButton(
                    "🇷🇺 Русский",
                    callback_data="user:setlang:ru"
                )
            ],
            [
                InlineKeyboardButton(
                    "🇬🇧 English",
                    callback_data="user:setlang:en"
                )
            ],
            [
                InlineKeyboardButton(
                    "⬅️ Kabinet",
                    callback_data="user:home"
                )
            ]
        ]
    )


async def show_language_menu(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.callback_query.answer()

    await update.callback_query.edit_message_text(
        (
            "🌐 TIL / ЯЗЫК / LANGUAGE\n\n"
            "Kerakli tilni tanlang:"
        ),
        reply_markup=language_keyboard()
    )


async def change_user_language_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    language: str
):

    user = update.effective_user
    query = update.callback_query

    if not user or not query:
        return

    if language not in SUPPORTED_LANGUAGES:

        await query.answer(
            "❌ Til topilmadi.",
            show_alert=True
        )

        return

    ensure_user(user)

    set_user_language(
        user.id,
        language
    )

    await query.answer(
        "✅ Til saqlandi.",
        show_alert=True
    )

    await show_user_home(
        update,
        context
    )


# =========================================================
# LIBRARY PLACEHOLDER ENTRY
# =========================================================
#
# Kutubxonaning to'liq qidiruv va
# kitob boshqaruvi keyingi qismda ulanadi.
# =========================================================

async def show_library_home(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    rows = db_execute(
        """
        SELECT
            id,
            title,
            author
        FROM library_books
        WHERE active = 1
        ORDER BY id DESC
        LIMIT 10
        """,
        fetchall=True
    )

    keyboard_rows = []

    if rows:

        for row in rows:

            author = (
                row["author"]
                or "Muallif noma'lum"
            )

            keyboard_rows.append(
                [
                    InlineKeyboardButton(
                        (
                            f"📖 "
                            f"{row['title'][:35]}"
                        ),
                        callback_data=(
                            f"library:book:"
                            f"{row['id']}"
                        )
                    )
                ]
            )

        text = (
            "📚 VERITAS KUTUBXONASI\n\n"
            "Kitobni tanlang:"
        )

    else:

        text = (
            "📚 VERITAS KUTUBXONASI\n\n"
            "Hozircha kutubxonaga "
            "kitob qo'shilmagan."
        )

    keyboard_rows.append(
        [
            InlineKeyboardButton(
                "🔎 Qidirish",
                callback_data="library:search"
            )
        ]
    )

    keyboard_rows.append(
        [
            InlineKeyboardButton(
                "⬅️ Kabinet",
                callback_data="user:home"
            )
        ]
    )

    await update.callback_query.answer()

    await update.callback_query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(
            keyboard_rows
        )
    )


# =========================================================
# USER CALLBACK ROUTER
# =========================================================

async def user_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    if not query:
        return

    user = update.effective_user

    if user:
        ensure_user(user)

    data = query.data or ""

    if data == "user:home":

        await show_user_home(
            update,
            context
        )
        return

    if data == "user:profile":

        await show_user_profile(
            update,
            context
        )
        return

    if data == "user:wallet":

        await show_user_wallet(
            update,
            context
        )
        return

    if data == "user:groups":

        await show_user_groups(
            update,
            context
        )
        return

    if data == "user:subscription":

        await show_user_subscriptions(
            update,
            context
        )
        return

    if data.startswith(
        "user:subscription_group:"
    ):

        try:

            chat_id = int(
                data.rsplit(
                    ":",
                    1
                )[1]
            )

        except ValueError:

            await query.answer(
                "❌ Guruh ID noto'g'ri.",
                show_alert=True
            )
            return

        await show_subscription_group(
            update,
            context,
            chat_id
        )
        return

    if data.startswith(
        "user:buy_v7:"
    ):

        try:

            chat_id = int(
                data.rsplit(
                    ":",
                    1
                )[1]
            )

        except ValueError:

            await query.answer(
                "❌ Guruh ID noto'g'ri.",
                show_alert=True
            )
            return

        await buy_v7_subscription(
            update,
            context,
            chat_id
        )
        return

    if data == "user:rewards":

        await show_my_rewards(
            update,
            context
        )
        return

    if data == "user:language":

        await show_language_menu(
            update,
            context
        )
        return

    if data.startswith(
        "user:setlang:"
    ):

        language = data.rsplit(
            ":",
            1
        )[1]

        await change_user_language_callback(
            update,
            context,
            language
        )
        return

    if data == "user:library":

        await show_library_home(
            update,
            context
        )
        return


# =========================================================
# BOT USERNAME HOLDER
# =========================================================
#
# main() ishga tushganda haqiqiy username
# shu global o'zgaruvchiga yoziladi.
# =========================================================

BOT_USERNAME = "VeritasBot"


# =========================================================
# END PART 6
# =========================================================
# =========================================================
# VERITAS BOT V7
# PART 7 — GROUP MANAGEMENT & MODERATION
# =========================================================


# =========================================================
# PERMISSIONS
# =========================================================

async def telegram_admin_check(
    context,
    chat_id,
    user_id
):
    try:
        member = await context.bot.get_chat_member(
            chat_id,
            user_id
        )

        return member.status in (
            "creator",
            "administrator",
        )

    except TelegramError:
        return False


async def veritas_moderator_check(
    context,
    chat_id,
    user_id
):
    if is_super_owner_id(user_id):
        return True

    if await telegram_admin_check(
        context,
        chat_id,
        user_id
    ):
        return True

    row = db_execute(
        """
        SELECT 1
        FROM group_moderators
        WHERE chat_id = ?
          AND user_id = ?
        """,
        (
            chat_id,
            user_id
        ),
        fetchone=True
    )

    return bool(row)


async def can_manage_group(
    context,
    chat_id,
    user_id
):
    if is_super_owner_id(user_id):
        return True

    group = get_group_record(chat_id)

    if group:
        if safe_int(group["owner_id"]) == user_id:
            return True

    return await veritas_moderator_check(
        context,
        chat_id,
        user_id
    )


async def target_is_protected(
    context,
    chat_id,
    user_id
):
    if is_super_owner_id(user_id):
        return True

    return await telegram_admin_check(
        context,
        chat_id,
        user_id
    )


# =========================================================
# BOT ADMIN CHECK
# =========================================================

async def bot_is_group_admin(
    context,
    chat_id
):
    try:
        me = await context.bot.get_me()

        member = await context.bot.get_chat_member(
            chat_id,
            me.id
        )

        return member.status in (
            "creator",
            "administrator",
        )

    except TelegramError:
        return False


# =========================================================
# GROUP PANEL
# =========================================================

def group_panel_keyboard(
    chat_id
):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🛡 Moderatsiya",
                    callback_data=(
                        f"group:moderation:{chat_id}"
                    )
                )
            ],
            [
                InlineKeyboardButton(
                    "⚠️ Warnlar",
                    callback_data=(
                        f"group:warns:{chat_id}"
                    )
                ),
                InlineKeyboardButton(
                    "👮 Moderatorlar",
                    callback_data=(
                        f"group:mods:{chat_id}"
                    )
                )
            ],
            [
                InlineKeyboardButton(
                    "⚙️ Sozlamalar",
                    callback_data=(
                        f"group:settings:{chat_id}"
                    )
                )
            ],
            [
                InlineKeyboardButton(
                    "📊 Faollik",
                    callback_data=(
                        f"group:activity:{chat_id}"
                    )
                )
            ],
            [
                InlineKeyboardButton(
                    "💎 V7 obuna",
                    callback_data=(
                        f"user:subscription_group:"
                        f"{chat_id}"
                    )
                )
            ],
            [
                InlineKeyboardButton(
                    "⬅️ Guruhlarim",
                    callback_data="user:groups"
                )
            ]
        ]
    )


async def show_group_panel(
    update,
    context,
    chat_id
):
    query = update.callback_query
    user = update.effective_user

    if not query or not user:
        return

    if not await can_manage_group(
        context,
        chat_id,
        user.id
    ):
        await query.answer(
            "⛔ Bu guruhni boshqarish huquqingiz yo'q.",
            show_alert=True
        )
        return

    group = get_group_record(chat_id)

    if not group:
        await query.answer(
            "❌ Guruh bazada topilmadi.",
            show_alert=True
        )
        return

    subscription = get_subscription(chat_id)

    if subscription:
        plan = subscription["plan"]
        status = subscription["status"]
    else:
        plan = "YO'Q"
        status = "INACTIVE"

    bot_admin = await bot_is_group_admin(
        context,
        chat_id
    )

    text = (
        "🏢 GURUH BOSHQARUVI\n\n"
        f"📌 {group['title']}\n"
        f"🆔 {chat_id}\n\n"
        f"🤖 Bot admin: "
        f"{'✅' if bot_admin else '❌'}\n"
        f"💎 Tarif: {plan}\n"
        f"📡 Holat: {status}\n\n"
        "Kerakli bo'limni tanlang."
    )

    await query.answer()

    await query.edit_message_text(
        text,
        reply_markup=group_panel_keyboard(
            chat_id
        )
    )


# =========================================================
# MODERATION PANEL
# =========================================================

def moderation_keyboard(
    chat_id
):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🔨 Ban",
                    callback_data=(
                        f"group:action:ban:{chat_id}"
                    )
                ),
                InlineKeyboardButton(
                    "🚪 Kick",
                    callback_data=(
                        f"group:action:kick:{chat_id}"
                    )
                )
            ],
            [
                InlineKeyboardButton(
                    "🔇 Mute",
                    callback_data=(
                        f"group:action:mute:{chat_id}"
                    )
                ),
                InlineKeyboardButton(
                    "🔊 Unmute",
                    callback_data=(
                        f"group:action:unmute:{chat_id}"
                    )
                )
            ],
            [
                InlineKeyboardButton(
                    "⚠️ Warn",
                    callback_data=(
                        f"group:action:warn:{chat_id}"
                    )
                ),
                InlineKeyboardButton(
                    "✅ Unwarn",
                    callback_data=(
                        f"group:action:unwarn:{chat_id}"
                    )
                )
            ],
            [
                InlineKeyboardButton(
                    "🧹 Clear warns",
                    callback_data=(
                        f"group:action:clearwarns:{chat_id}"
                    )
                )
            ],
            [
                InlineKeyboardButton(
                    "🔓 Unban",
                    callback_data=(
                        f"group:action:unban:{chat_id}"
                    )
                )
            ],
            [
                InlineKeyboardButton(
                    "⬅️ Guruh",
                    callback_data=(
                        f"group:open:{chat_id}"
                    )
                )
            ]
        ]
    )


async def show_moderation_panel(
    update,
    context,
    chat_id
):
    query = update.callback_query
    user = update.effective_user

    if not query or not user:
        return

    if not await can_manage_group(
        context,
        chat_id,
        user.id
    ):
        await query.answer(
            "⛔ Ruxsat yo'q.",
            show_alert=True
        )
        return

    await query.answer()

    await query.edit_message_text(
        (
            "🛡 MODERATSIYA\n\n"
            "Amalni tanlang.\n\n"
            "Keyingi bosqichda foydalanuvchi "
            "Telegram ID raqamini kiritasiz."
        ),
        reply_markup=moderation_keyboard(
            chat_id
        )
    )


# =========================================================
# MODERATION STATE
# =========================================================

async def start_moderation_action(
    update,
    context,
    action,
    chat_id
):
    query = update.callback_query
    user = update.effective_user

    if not query or not user:
        return

    if not await can_manage_group(
        context,
        chat_id,
        user.id
    ):
        await query.answer(
            "⛔ Ruxsat yo'q.",
            show_alert=True
        )
        return

    USER_STATES[user.id] = {
        "state": "WAIT_MODERATION_USER_ID",
        "action": action,
        "chat_id": chat_id,
    }

    names = {
        "ban": "🔨 Ban",
        "kick": "🚪 Kick",
        "mute": "🔇 Mute",
        "unmute": "🔊 Unmute",
        "warn": "⚠️ Warn",
        "unwarn": "✅ Unwarn",
        "clearwarns": "🧹 Clear warns",
        "unban": "🔓 Unban",
    }

    await query.answer()

    await query.edit_message_text(
        (
            f"{names.get(action, action)}\n\n"
            "Foydalanuvchining Telegram ID "
            "raqamini yuboring.\n\n"
            "Masalan:\n"
            "123456789"
        ),
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "❌ Bekor qilish",
                        callback_data=(
                            f"group:moderation:{chat_id}"
                        )
                    )
                ]
            ]
        )
    )


# =========================================================
# WARN FUNCTIONS
# =========================================================

def active_warn_count(
    chat_id,
    user_id
):
    row = db_execute(
        """
        SELECT COUNT(*) AS total
        FROM warns
        WHERE chat_id = ?
          AND user_id = ?
          AND active = 1
        """,
        (
            chat_id,
            user_id
        ),
        fetchone=True
    )

    if not row:
        return 0

    return safe_int(row["total"])


def add_warn(
    chat_id,
    user_id,
    moderator_id,
    reason="Ogohlantirish"
):
    db_execute(
        """
        INSERT INTO warns (
            chat_id,
            user_id,
            moderator_id,
            reason,
            active,
            created_at
        )
        VALUES (?, ?, ?, ?, 1, ?)
        """,
        (
            chat_id,
            user_id,
            moderator_id,
            reason,
            iso_now()
        )
    )

    return active_warn_count(
        chat_id,
        user_id
    )


def remove_one_warn(
    chat_id,
    user_id
):
    row = db_execute(
        """
        SELECT id
        FROM warns
        WHERE chat_id = ?
          AND user_id = ?
          AND active = 1
        ORDER BY id DESC
        LIMIT 1
        """,
        (
            chat_id,
            user_id
        ),
        fetchone=True
    )

    if not row:
        return False

    db_execute(
        """
        UPDATE warns
        SET active = 0
        WHERE id = ?
        """,
        (row["id"],)
    )

    return True


def clear_user_warns(
    chat_id,
    user_id
):
    db_execute(
        """
        UPDATE warns
        SET active = 0
        WHERE chat_id = ?
          AND user_id = ?
          AND active = 1
        """,
        (
            chat_id,
            user_id
        )
    )


# =========================================================
# MUTE PERMISSIONS
# =========================================================

def muted_permissions():
    return ChatPermissions(
        can_send_messages=False,
        can_send_audios=False,
        can_send_documents=False,
        can_send_photos=False,
        can_send_videos=False,
        can_send_video_notes=False,
        can_send_voice_notes=False,
        can_send_polls=False,
        can_send_other_messages=False,
        can_add_web_page_previews=False,
        can_invite_users=False,
    )


def normal_member_permissions():
    return ChatPermissions(
        can_send_messages=True,
        can_send_audios=True,
        can_send_documents=True,
        can_send_photos=True,
        can_send_videos=True,
        can_send_video_notes=True,
        can_send_voice_notes=True,
        can_send_polls=True,
        can_send_other_messages=True,
        can_add_web_page_previews=True,
        can_invite_users=True,
    )


# =========================================================
# EXECUTE MODERATION
# =========================================================

async def execute_moderation_action(
    context,
    *,
    chat_id,
    target_user_id,
    moderator_id,
    action
):
    if await target_is_protected(
        context,
        chat_id,
        target_user_id
    ):
        raise PermissionError(
            "Guruh egasi, administrator yoki "
            "Super Ega ustida bu amal bajarilmaydi."
        )

    if action == "ban":
        await context.bot.ban_chat_member(
            chat_id=chat_id,
            user_id=target_user_id,
            revoke_messages=True
        )

        audit(
            "USER_BANNED",
            actor_id=moderator_id,
            target_user_id=target_user_id,
            target_chat_id=chat_id
        )

        return "🔨 Foydalanuvchi ban qilindi."

    if action == "kick":
        await context.bot.ban_chat_member(
            chat_id=chat_id,
            user_id=target_user_id
        )

        await context.bot.unban_chat_member(
            chat_id=chat_id,
            user_id=target_user_id,
            only_if_banned=True
        )

        audit(
            "USER_KICKED",
            actor_id=moderator_id,
            target_user_id=target_user_id,
            target_chat_id=chat_id
        )

        return (
            "🚪 Foydalanuvchi guruhdan chiqarildi."
        )

    if action == "unban":
        await context.bot.unban_chat_member(
            chat_id=chat_id,
            user_id=target_user_id,
            only_if_banned=True
        )

        audit(
            "USER_UNBANNED",
            actor_id=moderator_id,
            target_user_id=target_user_id,
            target_chat_id=chat_id
        )

        return "🔓 Ban olib tashlandi."

    if action == "mute":
        until_date = (
            utc_now()
            + timedelta(hours=1)
        )

        await context.bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=target_user_id,
            permissions=muted_permissions(),
            until_date=until_date
        )

        audit(
            "USER_MUTED",
            actor_id=moderator_id,
            target_user_id=target_user_id,
            target_chat_id=chat_id,
            details="1 hour"
        )

        return "🔇 Foydalanuvchi 1 soatga mute qilindi."

    if action == "unmute":
        await context.bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=target_user_id,
            permissions=normal_member_permissions()
        )

        audit(
            "USER_UNMUTED",
            actor_id=moderator_id,
            target_user_id=target_user_id,
            target_chat_id=chat_id
        )

        return "🔊 Mute olib tashlandi."

    if action == "warn":
        warns = add_warn(
            chat_id,
            target_user_id,
            moderator_id
        )

        audit(
            "USER_WARNED",
            actor_id=moderator_id,
            target_user_id=target_user_id,
            target_chat_id=chat_id,
            details=f"warns={warns}"
        )

        if warns >= MAX_WARNS:
            await context.bot.ban_chat_member(
                chat_id=chat_id,
                user_id=target_user_id,
                revoke_messages=True
            )

            clear_user_warns(
                chat_id,
                target_user_id
            )

            audit(
                "AUTO_BAN_MAX_WARNS",
                actor_id=moderator_id,
                target_user_id=target_user_id,
                target_chat_id=chat_id,
                details=f"limit={MAX_WARNS}"
            )

            return (
                f"⛔ {MAX_WARNS} ta warn yig'ildi.\n"
                "Foydalanuvchi avtomatik ban qilindi."
            )

        return (
            "⚠️ Warn berildi.\n"
            f"Warnlar: {warns}/{MAX_WARNS}"
        )

    if action == "unwarn":
        removed = remove_one_warn(
            chat_id,
            target_user_id
        )

        if not removed:
            return "ℹ️ Faol warn topilmadi."

        warns = active_warn_count(
            chat_id,
            target_user_id
        )

        audit(
            "USER_UNWARNED",
            actor_id=moderator_id,
            target_user_id=target_user_id,
            target_chat_id=chat_id
        )

        return (
            "✅ Bitta warn olib tashlandi.\n"
            f"Qoldi: {warns}/{MAX_WARNS}"
        )

    if action == "clearwarns":
        clear_user_warns(
            chat_id,
            target_user_id
        )

        audit(
            "USER_WARNS_CLEARED",
            actor_id=moderator_id,
            target_user_id=target_user_id,
            target_chat_id=chat_id
        )

        return "🧹 Barcha warnlar tozalandi."

    raise ValueError(
        "Noma'lum moderatsiya amali."
    )


# =========================================================
# HANDLE MODERATION USER ID
# =========================================================

async def handle_moderation_user_id(
    update,
    context
):
    user = update.effective_user
    message = update.effective_message

    if not user or not message:
        return False

    state = USER_STATES.get(user.id)

    if not state:
        return False

    if (
        state.get("state")
        != "WAIT_MODERATION_USER_ID"
    ):
        return False

    chat_id = safe_int(
        state.get("chat_id")
    )

    action = state.get("action")

    if not await can_manage_group(
        context,
        chat_id,
        user.id
    ):
        USER_STATES.pop(
            user.id,
            None
        )

        await message.reply_text(
            "⛔ Guruhni boshqarish huquqingiz yo'q."
        )

        return True

    try:
        target_user_id = int(
            (message.text or "").strip()
        )

    except ValueError:
        await message.reply_text(
            "❌ Telegram ID raqam bo'lishi kerak."
        )
        return True

    if target_user_id <= 0:
        await message.reply_text(
            "❌ Telegram ID noto'g'ri."
        )
        return True

    USER_STATES.pop(
        user.id,
        None
    )

    try:
        result = await execute_moderation_action(
            context,
            chat_id=chat_id,
            target_user_id=target_user_id,
            moderator_id=user.id,
            action=action
        )

    except Exception as exc:
        logger.exception(
            "Moderatsiya amalida xato."
        )

        await message.reply_text(
            (
                "❌ Amal bajarilmadi.\n\n"
                f"{error_text(exc)}\n\n"
                "Botning guruhda administrator "
                "huquqlari borligini tekshiring."
            )
        )

        return True

    await message.reply_text(
        result,
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🛡 Moderatsiya",
                        callback_data=(
                            f"group:moderation:{chat_id}"
                        )
                    )
                ],
                [
                    InlineKeyboardButton(
                        "⬅️ Guruh",
                        callback_data=(
                            f"group:open:{chat_id}"
                        )
                    )
                ]
            ]
        )
    )

    return True


# =========================================================
# DELETE COMMAND
# =========================================================

async def delete_command(
    update,
    context
):
    chat = update.effective_chat
    user = update.effective_user
    message = update.effective_message

    if (
        not chat
        or not user
        or not message
    ):
        return

    if chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        return

    if not await can_manage_group(
        context,
        chat.id,
        user.id
    ):
        return

    reply = message.reply_to_message

    if not reply:
        await message.reply_text(
            "❗ O'chiriladigan xabarga reply qilib "
            "/del yozing."
        )
        return

    try:
        await context.bot.delete_message(
            chat_id=chat.id,
            message_id=reply.message_id
        )

        try:
            await message.delete()
        except TelegramError:
            pass

        audit(
            "MESSAGE_DELETED",
            actor_id=user.id,
            target_user_id=(
                reply.from_user.id
                if reply.from_user
                else None
            ),
            target_chat_id=chat.id,
            details=(
                f"message_id={reply.message_id}"
            )
        )

    except TelegramError as exc:
        await message.reply_text(
            f"❌ Xabar o'chirilmadi:\n{exc}"
        )


# =========================================================
# APPROVED USERS
# =========================================================

def approve_user(
    chat_id,
    user_id,
    approved_by
):
    db_execute(
        """
        INSERT OR REPLACE INTO approved_users (
            chat_id,
            user_id,
            approved_by,
            created_at
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            chat_id,
            user_id,
            approved_by,
            iso_now()
        )
    )


def unapprove_user(
    chat_id,
    user_id
):
    db_execute(
        """
        DELETE FROM approved_users
        WHERE chat_id = ?
          AND user_id = ?
        """,
        (
            chat_id,
            user_id
        )
    )


def user_is_approved(
    chat_id,
    user_id
):
    row = db_execute(
        """
        SELECT 1
        FROM approved_users
        WHERE chat_id = ?
          AND user_id = ?
        """,
        (
            chat_id,
            user_id
        ),
        fetchone=True
    )

    return bool(row)


# =========================================================
# MODERATOR LIST
# =========================================================

async def show_group_moderators(
    update,
    context,
    chat_id
):
    query = update.callback_query
    user = update.effective_user

    if not query or not user:
        return

    if not await can_manage_group(
        context,
        chat_id,
        user.id
    ):
        await query.answer(
            "⛔ Ruxsat yo'q.",
            show_alert=True
        )
        return

    rows = db_execute(
        """
        SELECT *
        FROM group_moderators
        WHERE chat_id = ?
        ORDER BY created_at DESC
        """,
        (chat_id,),
        fetchall=True
    )

    lines = [
        "👮 VERITAS MODERATORLARI",
        ""
    ]

    if not rows:
        lines.append(
            "Ichki moderatorlar hali qo'shilmagan."
        )

    else:
        for row in rows:
            lines.append(
                f"👤 {row['user_id']}"
            )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "➕ Moderator qo'shish",
                    callback_data=(
                        f"group:addmod:{chat_id}"
                    )
                )
            ],
            [
                InlineKeyboardButton(
                    "➖ Moderator o'chirish",
                    callback_data=(
                        f"group:delmod:{chat_id}"
                    )
                )
            ],
            [
                InlineKeyboardButton(
                    "⬅️ Guruh",
                    callback_data=(
                        f"group:open:{chat_id}"
                    )
                )
            ]
        ]
    )

    await query.answer()

    await query.edit_message_text(
        "\n".join(lines),
        reply_markup=keyboard
    )


# =========================================================
# GROUP CALLBACK ROUTER
# =========================================================

async def group_callback(
    update,
    context
):
    query = update.callback_query

    if not query:
        return

    data = query.data or ""

    if data.startswith("group:open:"):
        try:
            chat_id = int(
                data.rsplit(":", 1)[1]
            )
        except ValueError:
            return

        await show_group_panel(
            update,
            context,
            chat_id
        )
        return

    if data.startswith(
        "group:moderation:"
    ):
        try:
            chat_id = int(
                data.rsplit(":", 1)[1]
            )
        except ValueError:
            return

        await show_moderation_panel(
            update,
            context,
            chat_id
        )
        return

    if data.startswith(
        "group:action:"
    ):
        parts = data.split(":")

        if len(parts) != 4:
            return

        action = parts[2]

        try:
            chat_id = int(parts[3])
        except ValueError:
            return

        await start_moderation_action(
            update,
            context,
            action,
            chat_id
        )
        return

    if data.startswith(
        "group:mods:"
    ):
        try:
            chat_id = int(
                data.rsplit(":", 1)[1]
            )
        except ValueError:
            return

        await show_group_moderators(
            update,
            context,
            chat_id
        )
        return


# =========================================================
# MODERATION STATE ROUTER
# =========================================================

async def moderation_state_router(
    update,
    context
):
    user = update.effective_user

    if not user:
        return False

    state = USER_STATES.get(user.id)

    if not state:
        return False

    if (
        state.get("state")
        == "WAIT_MODERATION_USER_ID"
    ):
        return await handle_moderation_user_id(
            update,
            context
        )

    return False


# =========================================================
# END PART 7
# =========================================================
# =========================================================
# VERITAS BOT V7
# PART 8 — AUTOMATIC GROUP PROTECTION
# =========================================================


# =========================================================
# LINK DETECTION
# =========================================================

LINK_PATTERN = re.compile(
    r"(?i)"
    r"("
    r"https?://\S+"
    r"|www\.\S+"
    r"|t\.me/\S+"
    r"|telegram\.me/\S+"
    r"|telegram\.dog/\S+"
    r")"
)


def contains_link(
    text: str
) -> bool:

    if not text:
        return False

    return bool(
        LINK_PATTERN.search(text)
    )


# =========================================================
# GROUP SETTING
# =========================================================

def get_group_setting(
    chat_id: int,
    column: str,
    default=0
):

    allowed_columns = {
        "welcome_enabled",
        "goodbye_enabled",
        "anti_link_enabled",
        "anti_flood_enabled",
        "warns_enabled",
        "gifts_enabled",
        "premium_enabled",
        "rewards_enabled",
        "library_enabled",
    }

    if column not in allowed_columns:
        return default

    row = db_execute(
        f"""
        SELECT {column}
        FROM groups
        WHERE chat_id = ?
        """,
        (chat_id,),
        fetchone=True
    )

    if not row:
        return default

    return safe_int(
        row[column],
        default
    )


def set_group_setting(
    chat_id: int,
    column: str,
    enabled: bool
):

    allowed_columns = {
        "welcome_enabled",
        "goodbye_enabled",
        "anti_link_enabled",
        "anti_flood_enabled",
        "warns_enabled",
        "gifts_enabled",
        "premium_enabled",
        "rewards_enabled",
        "library_enabled",
    }

    if column not in allowed_columns:

        raise ValueError(
            "Noto'g'ri guruh sozlamasi."
        )

    db_execute(
        f"""
        UPDATE groups
        SET
            {column} = ?,
            updated_at = ?
        WHERE chat_id = ?
        """,
        (
            1 if enabled else 0,
            iso_now(),
            chat_id,
        )
    )


# =========================================================
# BLACKLIST CACHE-LESS CHECK
# =========================================================

def get_blacklist_words(
    chat_id: int
):

    rows = db_execute(
        """
        SELECT word
        FROM blacklist
        WHERE chat_id = ?
        ORDER BY id ASC
        """,
        (chat_id,),
        fetchall=True
    )

    return [
        clean_text(row["word"]).lower()
        for row in rows
        if clean_text(row["word"])
    ]


def contains_blacklisted_word(
    chat_id: int,
    text: str
):

    if not text:
        return None

    normalized = text.casefold()

    words = get_blacklist_words(
        chat_id
    )

    for word in words:

        if word.casefold() in normalized:
            return word

    return None


# =========================================================
# MEDIA LOCK SETTINGS
# =========================================================
#
# Media locklar bot_settings jadvalida
# guruh bo'yicha alohida saqlanadi.
#
# Masalan:
#
# media_lock:-100123:photo = 1
# media_lock:-100123:video = 0
# =========================================================

MEDIA_TYPES = {
    "photo",
    "video",
    "audio",
    "voice",
    "document",
    "sticker",
    "animation",
    "video_note",
    "poll",
}


def media_setting_key(
    chat_id: int,
    media_type: str
):

    return (
        f"media_lock:"
        f"{chat_id}:"
        f"{media_type}"
    )


def media_is_locked(
    chat_id: int,
    media_type: str
) -> bool:

    if media_type not in MEDIA_TYPES:
        return False

    value = get_setting(
        media_setting_key(
            chat_id,
            media_type
        ),
        "0"
    )

    return str(value) == "1"


def set_media_lock(
    chat_id: int,
    media_type: str,
    locked: bool,
    updated_by: int
):

    if media_type not in MEDIA_TYPES:

        raise ValueError(
            "Noma'lum media turi."
        )

    set_setting(
        media_setting_key(
            chat_id,
            media_type
        ),
        "1" if locked else "0",
        updated_by
    )


# =========================================================
# DETECT MESSAGE MEDIA
# =========================================================

def detect_media_type(
    message: Message
):

    if message.photo:
        return "photo"

    if message.video:
        return "video"

    if message.audio:
        return "audio"

    if message.voice:
        return "voice"

    if message.document:
        return "document"

    if message.sticker:
        return "sticker"

    if message.animation:
        return "animation"

    if message.video_note:
        return "video_note"

    if message.poll:
        return "poll"

    return None


# =========================================================
# SAFE DELETE
# =========================================================

async def safe_delete_message(
    message: Message
):

    try:

        await message.delete()

        return True

    except TelegramError:

        return False


# =========================================================
# USER EXEMPTION
# =========================================================

async def protection_exempt(
    context,
    chat_id: int,
    user_id: int
):

    if is_super_owner_id(user_id):
        return True

    if user_is_approved(
        chat_id,
        user_id
    ):
        return True

    if await telegram_admin_check(
        context,
        chat_id,
        user_id
    ):
        return True

    return False


# =========================================================
# ANTI FLOOD
# =========================================================

def register_flood_message(
    chat_id: int,
    user_id: int
):

    now = time.monotonic()

    key = (
        chat_id,
        user_id
    )

    timestamps = FLOOD_CACHE.get(
        key,
        []
    )

    minimum_time = (
        now
        - FLOOD_SECONDS
    )

    timestamps = [
        stamp
        for stamp in timestamps
        if stamp >= minimum_time
    ]

    timestamps.append(now)

    FLOOD_CACHE[key] = timestamps

    return len(timestamps)


def clear_flood_cache(
    chat_id: int,
    user_id: int
):

    FLOOD_CACHE.pop(
        (
            chat_id,
            user_id
        ),
        None
    )


async def apply_flood_mute(
    context,
    chat_id: int,
    user_id: int
):

    until_date = (
        utc_now()
        + timedelta(
            seconds=FLOOD_MUTE_SECONDS
        )
    )

    await context.bot.restrict_chat_member(
        chat_id=chat_id,
        user_id=user_id,
        permissions=muted_permissions(),
        until_date=until_date
    )


# =========================================================
# ANTI LINK
# =========================================================

async def process_anti_link(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user

    if (
        not message
        or not chat
        or not user
    ):
        return False

    if not get_group_setting(
        chat.id,
        "anti_link_enabled",
        0
    ):
        return False

    if await protection_exempt(
        context,
        chat.id,
        user.id
    ):
        return False

    text = (
        message.text
        or message.caption
        or ""
    )

    if not contains_link(text):
        return False

    deleted = await safe_delete_message(
        message
    )

    audit(
        "ANTI_LINK_TRIGGERED",
        actor_id=user.id,
        target_user_id=user.id,
        target_chat_id=chat.id,
        details=(
            f"deleted={deleted}"
        )
    )

    try:

        warning = (
            await context.bot.send_message(
                chat_id=chat.id,
                text=(
                    f"🔗 {user_display_name(user)}, "
                    "guruhda havola yuborish "
                    "taqiqlangan."
                )
            )
        )

        context.job_queue.run_once(
            delete_warning_job,
            5,
            data={
                "chat_id": chat.id,
                "message_id":
                    warning.message_id,
            }
        )

    except TelegramError:

        pass

    return True


# =========================================================
# BLACKLIST PROTECTION
# =========================================================

async def process_blacklist(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user

    if (
        not message
        or not chat
        or not user
    ):
        return False

    if await protection_exempt(
        context,
        chat.id,
        user.id
    ):
        return False

    text = (
        message.text
        or message.caption
        or ""
    )

    matched_word = (
        contains_blacklisted_word(
            chat.id,
            text
        )
    )

    if not matched_word:
        return False

    deleted = await safe_delete_message(
        message
    )

    audit(
        "BLACKLIST_TRIGGERED",
        actor_id=user.id,
        target_user_id=user.id,
        target_chat_id=chat.id,
        details=(
            f"word={matched_word}; "
            f"deleted={deleted}"
        )
    )

    try:

        warning = (
            await context.bot.send_message(
                chat_id=chat.id,
                text=(
                    f"🚫 {user_display_name(user)}, "
                    "taqiqlangan so'z ishlatildi."
                )
            )
        )

        context.job_queue.run_once(
            delete_warning_job,
            5,
            data={
                "chat_id": chat.id,
                "message_id":
                    warning.message_id,
            }
        )

    except TelegramError:

        pass

    return True


# =========================================================
# MEDIA LOCK
# =========================================================

async def process_media_lock(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user

    if (
        not message
        or not chat
        or not user
    ):
        return False

    media_type = detect_media_type(
        message
    )

    if not media_type:
        return False

    if not media_is_locked(
        chat.id,
        media_type
    ):
        return False

    if await protection_exempt(
        context,
        chat.id,
        user.id
    ):
        return False

    deleted = await safe_delete_message(
        message
    )

    audit(
        "MEDIA_LOCK_TRIGGERED",
        actor_id=user.id,
        target_user_id=user.id,
        target_chat_id=chat.id,
        details=(
            f"type={media_type}; "
            f"deleted={deleted}"
        )
    )

    return True


# =========================================================
# FLOOD PROTECTION
# =========================================================

async def process_anti_flood(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user

    if (
        not message
        or not chat
        or not user
    ):
        return False

    if not get_group_setting(
        chat.id,
        "anti_flood_enabled",
        1
    ):
        return False

    if await protection_exempt(
        context,
        chat.id,
        user.id
    ):
        return False

    count = register_flood_message(
        chat.id,
        user.id
    )

    if count < FLOOD_MESSAGE_LIMIT:
        return False

    clear_flood_cache(
        chat.id,
        user.id
    )

    try:

        await apply_flood_mute(
            context,
            chat.id,
            user.id
        )

        audit(
            "ANTI_FLOOD_MUTE",
            actor_id=user.id,
            target_user_id=user.id,
            target_chat_id=chat.id,
            details=(
                f"messages={count}; "
                f"seconds={FLOOD_SECONDS}; "
                f"mute={FLOOD_MUTE_SECONDS}"
            )
        )

        try:

            warning = (
                await context.bot.send_message(
                    chat_id=chat.id,
                    text=(
                        f"🚨 {user_display_name(user)} "
                        "juda tez xabar yubordi.\n"
                        f"🔇 {FLOOD_MUTE_SECONDS} "
                        "soniyaga mute qilindi."
                    )
                )
            )

            context.job_queue.run_once(
                delete_warning_job,
                8,
                data={
                    "chat_id":
                        chat.id,

                    "message_id":
                        warning.message_id,
                }
            )

        except TelegramError:

            pass

        return True

    except TelegramError as exc:

        logger.warning(
            "Anti-flood mute xatosi: %s",
            exc
        )

        return False


# =========================================================
# DELETE TEMPORARY WARNING JOB
# =========================================================

async def delete_warning_job(
    context: ContextTypes.DEFAULT_TYPE
):

    data = context.job.data or {}

    chat_id = data.get(
        "chat_id"
    )

    message_id = data.get(
        "message_id"
    )

    if (
        not chat_id
        or not message_id
    ):
        return

    try:

        await context.bot.delete_message(
            chat_id=chat_id,
            message_id=message_id
        )

    except TelegramError:

        pass


# =========================================================
# BLACKLIST ADMIN FUNCTIONS
# =========================================================

def add_blacklist_word(
    chat_id: int,
    word: str,
    created_by: int
):

    word = clean_text(
        word
    ).casefold()

    if not word:

        raise ValueError(
            "Bo'sh so'z qo'shib bo'lmaydi."
        )

    conn = db_connect()

    try:

        conn.execute(
            """
            INSERT OR IGNORE INTO blacklist (
                chat_id,
                word,
                created_by,
                created_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                chat_id,
                word,
                created_by,
                iso_now(),
            )
        )

        conn.commit()

    finally:

        conn.close()


def remove_blacklist_word(
    chat_id: int,
    word: str
):

    db_execute(
        """
        DELETE FROM blacklist
        WHERE
            chat_id = ?
            AND LOWER(word) = LOWER(?)
        """,
        (
            chat_id,
            clean_text(word)
        )
    )


# =========================================================
# MEDIA SETTINGS KEYBOARD
# =========================================================

def media_locks_keyboard(
    chat_id: int
):

    names = {
        "photo": "🖼 Rasm",
        "video": "🎬 Video",
        "audio": "🎵 Audio",
        "voice": "🎙 Voice",
        "document": "📄 Fayl",
        "sticker": "😀 Sticker",
        "animation": "🎞 GIF",
        "video_note": "⭕ Video note",
        "poll": "📊 So'rovnoma",
    }

    rows = []

    for media_type, title in names.items():

        locked = media_is_locked(
            chat_id,
            media_type
        )

        icon = (
            "🔒"
            if locked
            else "🔓"
        )

        rows.append(
            [
                InlineKeyboardButton(
                    f"{icon} {title}",
                    callback_data=(
                        f"group:media_toggle:"
                        f"{chat_id}:"
                        f"{media_type}"
                    )
                )
            ]
        )

    rows.append(
        [
            InlineKeyboardButton(
                "⬅️ Sozlamalar",
                callback_data=(
                    f"group:settings:{chat_id}"
                )
            )
        ]
    )

    return InlineKeyboardMarkup(
        rows
    )


# =========================================================
# GROUP SETTINGS PANEL
# =========================================================

async def show_group_settings(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int
):

    query = update.callback_query
    user = update.effective_user

    if not query or not user:
        return

    if not await can_manage_group(
        context,
        chat_id,
        user.id
    ):

        await query.answer(
            "⛔ Ruxsat yo'q.",
            show_alert=True
        )

        return

    anti_link = bool(
        get_group_setting(
            chat_id,
            "anti_link_enabled",
            0
        )
    )

    anti_flood = bool(
        get_group_setting(
            chat_id,
            "anti_flood_enabled",
            1
        )
    )

    welcome = bool(
        get_group_setting(
            chat_id,
            "welcome_enabled",
            1
        )
    )

    goodbye = bool(
        get_group_setting(
            chat_id,
            "goodbye_enabled",
            1
        )
    )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    (
                        "🔗 Anti-link: "
                        + (
                            "✅"
                            if anti_link
                            else "❌"
                        )
                    ),
                    callback_data=(
                        f"group:toggle:"
                        f"{chat_id}:"
                        "anti_link_enabled"
                    )
                )
            ],
            [
                InlineKeyboardButton(
                    (
                        "🚨 Anti-flood: "
                        + (
                            "✅"
                            if anti_flood
                            else "❌"
                        )
                    ),
                    callback_data=(
                        f"group:toggle:"
                        f"{chat_id}:"
                        "anti_flood_enabled"
                    )
                )
            ],
            [
                InlineKeyboardButton(
                    (
                        "👋 Welcome: "
                        + (
                            "✅"
                            if welcome
                            else "❌"
                        )
                    ),
                    callback_data=(
                        f"group:toggle:"
                        f"{chat_id}:"
                        "welcome_enabled"
                    )
                )
            ],
            [
                InlineKeyboardButton(
                    (
                        "🚪 Goodbye: "
                        + (
                            "✅"
                            if goodbye
                            else "❌"
                        )
                    ),
                    callback_data=(
                        f"group:toggle:"
                        f"{chat_id}:"
                        "goodbye_enabled"
                    )
                )
            ],
            [
                InlineKeyboardButton(
                    "🔒 Media lock",
                    callback_data=(
                        f"group:media:{chat_id}"
                    )
                )
            ],
            [
                InlineKeyboardButton(
                    "🚫 Blacklist",
                    callback_data=(
                        f"group:blacklist:{chat_id}"
                    )
                )
            ],
            [
                InlineKeyboardButton(
                    "⬅️ Guruh",
                    callback_data=(
                        f"group:open:{chat_id}"
                    )
                )
            ]
        ]
    )

    await query.answer()

    await query.edit_message_text(
        (
            "⚙️ GURUH SOZLAMALARI\n\n"
            "Kerakli himoya tizimini "
            "yoqing yoki o'chiring."
        ),
        reply_markup=keyboard
    )


# =========================================================
# TOGGLE GROUP SETTING
# =========================================================

async def toggle_group_setting(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    setting_name: str
):

    query = update.callback_query
    user = update.effective_user

    if not query or not user:
        return

    if not await can_manage_group(
        context,
        chat_id,
        user.id
    ):

        await query.answer(
            "⛔ Ruxsat yo'q.",
            show_alert=True
        )

        return

    current = bool(
        get_group_setting(
            chat_id,
            setting_name,
            0
        )
    )

    set_group_setting(
        chat_id,
        setting_name,
        not current
    )

    audit(
        "GROUP_SETTING_CHANGED",
        actor_id=user.id,
        target_chat_id=chat_id,
        details=(
            f"{setting_name}="
            f"{int(not current)}"
        )
    )

    await query.answer(
        "✅ Sozlama yangilandi."
    )

    await show_group_settings(
        update,
        context,
        chat_id
    )


# =========================================================
# MEDIA LOCK PANEL
# =========================================================

async def show_media_locks(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int
):

    query = update.callback_query
    user = update.effective_user

    if not query or not user:
        return

    if not await can_manage_group(
        context,
        chat_id,
        user.id
    ):

        await query.answer(
            "⛔ Ruxsat yo'q.",
            show_alert=True
        )

        return

    await query.answer()

    await query.edit_message_text(
        (
            "🔒 MEDIA LOCK\n\n"
            "🔒 = bloklangan\n"
            "🔓 = ruxsat berilgan\n\n"
            "O'zgartirish uchun "
            "tugmani bosing."
        ),
        reply_markup=(
            media_locks_keyboard(
                chat_id
            )
        )
    )


# =========================================================
# TOGGLE MEDIA
# =========================================================

async def toggle_media_lock(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    media_type: str
):

    query = update.callback_query
    user = update.effective_user

    if not query or not user:
        return

    if not await can_manage_group(
        context,
        chat_id,
        user.id
    ):
        return

    current = media_is_locked(
        chat_id,
        media_type
    )

    set_media_lock(
        chat_id,
        media_type,
        not current,
        user.id
    )

    audit(
        "MEDIA_LOCK_CHANGED",
        actor_id=user.id,
        target_chat_id=chat_id,
        details=(
            f"{media_type}="
            f"{int(not current)}"
        )
    )

    await query.answer(
        "✅ Yangilandi."
    )

    await show_media_locks(
        update,
        context,
        chat_id
    )


# =========================================================
# BLACKLIST PANEL
# =========================================================

async def show_blacklist_panel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int
):

    query = update.callback_query
    user = update.effective_user

    if not query or not user:
        return

    if not await can_manage_group(
        context,
        chat_id,
        user.id
    ):
        return

    words = get_blacklist_words(
        chat_id
    )

    if words:

        preview = "\n".join(
            f"• {word}"
            for word in words[:30]
        )

    else:

        preview = (
            "Taqiqlangan so'zlar yo'q."
        )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "➕ So'z qo'shish",
                    callback_data=(
                        f"group:blacklist_add:"
                        f"{chat_id}"
                    )
                )
            ],
            [
                InlineKeyboardButton(
                    "➖ So'z o'chirish",
                    callback_data=(
                        f"group:blacklist_del:"
                        f"{chat_id}"
                    )
                )
            ],
            [
                InlineKeyboardButton(
                    "⬅️ Sozlamalar",
                    callback_data=(
                        f"group:settings:{chat_id}"
                    )
                )
            ]
        ]
    )

    await query.answer()

    await query.edit_message_text(
        (
            "🚫 BLACKLIST\n\n"
            f"{preview}"
        ),
        reply_markup=keyboard
    )


# =========================================================
# START BLACKLIST EDIT
# =========================================================

async def start_blacklist_edit(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    action: str
):

    query = update.callback_query
    user = update.effective_user

    if not query or not user:
        return

    if not await can_manage_group(
        context,
        chat_id,
        user.id
    ):
        return

    USER_STATES[user.id] = {
        "state": "WAIT_BLACKLIST_WORD",
        "chat_id": chat_id,
        "action": action,
    }

    if action == "add":

        text = (
            "➕ BLACKLIST\n\n"
            "Taqiqlanadigan so'z yoki "
            "iborani yuboring."
        )

    else:

        text = (
            "➖ BLACKLIST\n\n"
            "O'chiriladigan so'z yoki "
            "iborani yuboring."
        )

    await query.answer()

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "❌ Bekor qilish",
                        callback_data=(
                            f"group:blacklist:"
                            f"{chat_id}"
                        )
                    )
                ]
            ]
        )
    )


# =========================================================
# HANDLE BLACKLIST WORD
# =========================================================

async def handle_blacklist_word(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user
    message = update.effective_message

    if not user or not message:
        return False

    state = USER_STATES.get(
        user.id
    )

    if not state:
        return False

    if (
        state.get("state")
        != "WAIT_BLACKLIST_WORD"
    ):
        return False

    chat_id = safe_int(
        state.get("chat_id")
    )

    action = state.get(
        "action"
    )

    if not await can_manage_group(
        context,
        chat_id,
        user.id
    ):

        USER_STATES.pop(
            user.id,
            None
        )

        return True

    word = clean_text(
        message.text
    )

    if not word:

        await message.reply_text(
            "❌ So'z yuboring."
        )

        return True

    if len(word) > 100:

        await message.reply_text(
            "❌ Maksimal uzunlik 100 belgi."
        )

        return True

    if action == "add":

        add_blacklist_word(
            chat_id,
            word,
            user.id
        )

        result_text = (
            f"✅ Blacklistga qo'shildi:\n"
            f"{word}"
        )

        audit(
            "BLACKLIST_WORD_ADDED",
            actor_id=user.id,
            target_chat_id=chat_id,
            details=word
        )

    else:

        remove_blacklist_word(
            chat_id,
            word
        )

        result_text = (
            f"✅ Blacklistdan o'chirildi:\n"
            f"{word}"
        )

        audit(
            "BLACKLIST_WORD_REMOVED",
            actor_id=user.id,
            target_chat_id=chat_id,
            details=word
        )

    USER_STATES.pop(
        user.id,
        None
    )

    await message.reply_text(
        result_text,
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🚫 Blacklist",
                        callback_data=(
                            f"group:blacklist:"
                            f"{chat_id}"
                        )
                    )
                ]
            ]
        )
    )

    return True


# =========================================================
# AUTOMATIC GROUP PROTECTION ROUTER
# =========================================================

async def process_group_protection(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    chat = update.effective_chat
    user = update.effective_user
    message = update.effective_message

    if (
        not chat
        or not user
        or not message
    ):
        return False

    if chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP,
    ):
        return False

    if user.is_bot:
        return False

    ensure_user(user)
    ensure_group(chat)

    # 1. Media lock

    if await process_media_lock(
        update,
        context
    ):
        return True

    # 2. Blacklist

    if await process_blacklist(
        update,
        context
    ):
        return True

    # 3. Anti-link

    if await process_anti_link(
        update,
        context
    ):
        return True

    # 4. Anti-flood

    if await process_anti_flood(
        update,
        context
    ):
        return True

    return False


# =========================================================
# EXTENDED GROUP CALLBACK
# =========================================================

async def group_protection_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    if not query:
        return

    data = query.data or ""

    if data.startswith(
        "group:settings:"
    ):

        try:

            chat_id = int(
                data.rsplit(
                    ":",
                    1
                )[1]
            )

        except ValueError:

            return

        await show_group_settings(
            update,
            context,
            chat_id
        )

        return

    if data.startswith(
        "group:toggle:"
    ):

        parts = data.split(
            ":",
            3
        )

        if len(parts) != 4:
            return

        try:

            chat_id = int(
                parts[2]
            )

        except ValueError:

            return

        setting_name = parts[3]

        await toggle_group_setting(
            update,
            context,
            chat_id,
            setting_name
        )

        return

    if data.startswith(
        "group:media_toggle:"
    ):

        parts = data.split(
            ":",
            3
        )

        if len(parts) != 4:
            return

        try:

            chat_id = int(
                parts[2]
            )

        except ValueError:

            return

        media_type = parts[3]

        await toggle_media_lock(
            update,
            context,
            chat_id,
            media_type
        )

        return

    if data.startswith(
        "group:media:"
    ):

        try:

            chat_id = int(
                data.rsplit(
                    ":",
                    1
                )[1]
            )

        except ValueError:

            return

        await show_media_locks(
            update,
            context,
            chat_id
        )

        return

    if data.startswith(
        "group:blacklist_add:"
    ):

        try:

            chat_id = int(
                data.rsplit(
                    ":",
                    1
                )[1]
            )

        except ValueError:

            return

        await start_blacklist_edit(
            update,
            context,
            chat_id,
            "add"
        )

        return

    if data.startswith(
        "group:blacklist_del:"
    ):

        try:

            chat_id = int(
                data.rsplit(
                    ":",
                    1
                )[1]
            )

        except ValueError:

            return

        await start_blacklist_edit(
            update,
            context,
            chat_id,
            "delete"
        )

        return

    if data.startswith(
        "group:blacklist:"
    ):

        try:

            chat_id = int(
                data.rsplit(
                    ":",
                    1
                )[1]
            )

        except ValueError:

            return

        await show_blacklist_panel(
            update,
            context,
            chat_id
        )

        return


# =========================================================
# PROTECTION STATE ROUTER
# =========================================================

async def protection_state_router(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    if not user:
        return False

    state = USER_STATES.get(
        user.id
    )

    if not state:
        return False

    if (
        state.get("state")
        == "WAIT_BLACKLIST_WORD"
    ):

        return await handle_blacklist_word(
            update,
            context
        )

    return False


# =========================================================
# END PART 8
# =========================================================
# =========================================================
# VERITAS BOT V7
# PART 9 — WELCOME, RULES, NOTES, FILTERS & REPORTS
# =========================================================


# =========================================================
# TEXT HELPERS
# =========================================================

def format_group_template(
    template: str,
    *,
    user: Optional[User] = None,
    chat: Optional[Chat] = None
):

    text = template or ""

    replacements = {
        "{name}": (
            user_display_name(user)
            if user else ""
        ),
        "{first_name}": (
            user.first_name
            if user and user.first_name
            else ""
        ),
        "{username}": (
            f"@{user.username}"
            if user and user.username
            else ""
        ),
        "{user_id}": (
            str(user.id)
            if user else ""
        ),
        "{group}": (
            chat.title
            if chat and chat.title
            else ""
        ),
        "{chat_id}": (
            str(chat.id)
            if chat else ""
        ),
    }

    for key, value in replacements.items():
        text = text.replace(
            key,
            value
        )

    return text


# =========================================================
# WELCOME
# =========================================================

async def welcome_new_members(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    message = update.effective_message
    chat = update.effective_chat

    if not message or not chat:
        return

    if chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP,
    ):
        return

    ensure_group(chat)

    if not get_group_setting(
        chat.id,
        "welcome_enabled",
        1
    ):
        return

    group = get_group_record(
        chat.id
    )

    custom_text = None

    if group:
        custom_text = group[
            "welcome_text"
        ]

    for member in (
        message.new_chat_members or []
    ):

        if member.is_bot:
            continue

        ensure_user(member)

        if custom_text:

            text = format_group_template(
                custom_text,
                user=member,
                chat=chat
            )

        else:

            text = (
                f"👋 Xush kelibsiz, "
                f"{user_display_name(member)}!\n\n"
                f"🏢 {chat.title}\n"
                "Guruh qoidalariga rioya "
                "qilishingizni so'raymiz."
            )

        try:

            await message.reply_text(
                text
            )

        except TelegramError:

            pass

        audit(
            "MEMBER_JOINED",
            actor_id=member.id,
            target_user_id=member.id,
            target_chat_id=chat.id
        )


# =========================================================
# GOODBYE
# =========================================================

async def goodbye_member(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    message = update.effective_message
    chat = update.effective_chat

    if not message or not chat:
        return

    member = message.left_chat_member

    if not member:
        return

    if member.is_bot:
        return

    ensure_group(chat)

    if not get_group_setting(
        chat.id,
        "goodbye_enabled",
        1
    ):
        return

    group = get_group_record(
        chat.id
    )

    custom_text = None

    if group:
        custom_text = group[
            "goodbye_text"
        ]

    if custom_text:

        text = format_group_template(
            custom_text,
            user=member,
            chat=chat
        )

    else:

        text = (
            f"👋 {user_display_name(member)} "
            "guruhni tark etdi."
        )

    try:

        await message.reply_text(
            text
        )

    except TelegramError:

        pass

    audit(
        "MEMBER_LEFT",
        actor_id=member.id,
        target_user_id=member.id,
        target_chat_id=chat.id
    )


# =========================================================
# RULES
# =========================================================

def get_group_rules(
    chat_id: int
):

    row = db_execute(
        """
        SELECT rules_text
        FROM group_rules
        WHERE chat_id = ?
        """,
        (chat_id,),
        fetchone=True
    )

    if not row:
        return None

    return row["rules_text"]


def save_group_rules(
    chat_id: int,
    text: str,
    updated_by: int
):

    now = iso_now()

    db_execute(
        """
        INSERT INTO group_rules (
            chat_id,
            rules_text,
            updated_by,
            updated_at
        )
        VALUES (?, ?, ?, ?)

        ON CONFLICT(chat_id)
        DO UPDATE SET
            rules_text = excluded.rules_text,
            updated_by = excluded.updated_by,
            updated_at = excluded.updated_at
        """,
        (
            chat_id,
            text,
            updated_by,
            now
        )
    )


async def rules_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    chat = update.effective_chat

    if not chat:
        return

    if chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP,
    ):
        return

    rules = get_group_rules(
        chat.id
    )

    if not rules:

        await update.effective_message.reply_text(
            "📜 Bu guruh uchun "
            "qoidalar hali yozilmagan."
        )

        return

    await update.effective_message.reply_text(
        "📜 GURUH QOIDALARI\n\n"
        + rules
    )


async def setrules_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    chat = update.effective_chat
    user = update.effective_user
    message = update.effective_message

    if (
        not chat
        or not user
        or not message
    ):
        return

    if chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP,
    ):
        return

    if not await can_manage_group(
        context,
        chat.id,
        user.id
    ):

        await message.reply_text(
            "⛔ Qoidalarni faqat "
            "guruh boshqaruvchisi "
            "o'zgartira oladi."
        )

        return

    text = " ".join(
        context.args
    ).strip()

    if not text:

        await message.reply_text(
            "❗ Foydalanish:\n"
            "/setrules Guruh qoidalari..."
        )

        return

    if len(text) > 3500:

        await message.reply_text(
            "❌ Qoidalar juda uzun."
        )

        return

    save_group_rules(
        chat.id,
        text,
        user.id
    )

    audit(
        "RULES_UPDATED",
        actor_id=user.id,
        target_chat_id=chat.id
    )

    await message.reply_text(
        "✅ Guruh qoidalari saqlandi."
    )


# =========================================================
# NOTES
# =========================================================

def normalize_note_name(
    name: str
):

    name = clean_text(
        name
    ).lower()

    name = name.lstrip(
        "#/"
    )

    return name[:64]


def save_note(
    chat_id: int,
    name: str,
    content: str,
    created_by: int
):

    name = normalize_note_name(
        name
    )

    if not name:
        raise ValueError(
            "Note nomi bo'sh."
        )

    if not content:
        raise ValueError(
            "Note matni bo'sh."
        )

    db_execute(
        """
        INSERT INTO notes (
            chat_id,
            name,
            content,
            created_by,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?)

        ON CONFLICT(chat_id, name)
        DO UPDATE SET
            content = excluded.content,
            created_by = excluded.created_by,
            updated_at = excluded.updated_at
        """,
        (
            chat_id,
            name,
            content,
            created_by,
            iso_now(),
            iso_now()
        )
    )


def get_note(
    chat_id: int,
    name: str
):

    return db_execute(
        """
        SELECT *
        FROM notes
        WHERE chat_id = ?
          AND name = ?
        """,
        (
            chat_id,
            normalize_note_name(name)
        ),
        fetchone=True
    )


def delete_note(
    chat_id: int,
    name: str
):

    db_execute(
        """
        DELETE FROM notes
        WHERE chat_id = ?
          AND name = ?
        """,
        (
            chat_id,
            normalize_note_name(name)
        )
    )


async def save_note_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    chat = update.effective_chat
    user = update.effective_user
    message = update.effective_message

    if (
        not chat
        or not user
        or not message
    ):
        return

    if not await can_manage_group(
        context,
        chat.id,
        user.id
    ):
        return

    if len(context.args) < 2:

        await message.reply_text(
            "❗ Foydalanish:\n"
            "/save note_nomi Matn"
        )

        return

    name = context.args[0]

    content = " ".join(
        context.args[1:]
    ).strip()

    save_note(
        chat.id,
        name,
        content,
        user.id
    )

    audit(
        "NOTE_SAVED",
        actor_id=user.id,
        target_chat_id=chat.id,
        details=normalize_note_name(name)
    )

    await message.reply_text(
        f"✅ #{normalize_note_name(name)} "
        "saqlandi."
    )


async def get_note_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    chat = update.effective_chat
    message = update.effective_message

    if not chat or not message:
        return

    if not context.args:

        await message.reply_text(
            "❗ Foydalanish:\n"
            "/get note_nomi"
        )

        return

    note = get_note(
        chat.id,
        context.args[0]
    )

    if not note:

        await message.reply_text(
            "❌ Note topilmadi."
        )

        return

    await message.reply_text(
        note["content"]
    )


async def notes_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    chat = update.effective_chat
    message = update.effective_message

    if not chat or not message:
        return

    rows = db_execute(
        """
        SELECT name
        FROM notes
        WHERE chat_id = ?
        ORDER BY name COLLATE NOCASE
        LIMIT 100
        """,
        (chat.id,),
        fetchall=True
    )

    if not rows:

        await message.reply_text(
            "📝 Saqlangan notes yo'q."
        )

        return

    text = (
        "📝 NOTES\n\n"
        + "\n".join(
            f"• #{row['name']}"
            for row in rows
        )
    )

    await message.reply_text(
        text
    )


async def clear_note_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    chat = update.effective_chat
    user = update.effective_user
    message = update.effective_message

    if (
        not chat
        or not user
        or not message
    ):
        return

    if not await can_manage_group(
        context,
        chat.id,
        user.id
    ):
        return

    if not context.args:

        await message.reply_text(
            "❗ Foydalanish:\n"
            "/clear note_nomi"
        )

        return

    name = normalize_note_name(
        context.args[0]
    )

    delete_note(
        chat.id,
        name
    )

    audit(
        "NOTE_DELETED",
        actor_id=user.id,
        target_chat_id=chat.id,
        details=name
    )

    await message.reply_text(
        f"🗑 #{name} o'chirildi."
    )


# =========================================================
# #NOTE TRIGGER
# =========================================================

async def process_note_trigger(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    chat = update.effective_chat
    message = update.effective_message

    if not chat or not message:
        return False

    text = (
        message.text or ""
    ).strip()

    if not text.startswith("#"):
        return False

    name = text.split(
        maxsplit=1
    )[0]

    name = normalize_note_name(
        name
    )

    if not name:
        return False

    note = get_note(
        chat.id,
        name
    )

    if not note:
        return False

    await message.reply_text(
        note["content"]
    )

    return True


# =========================================================
# CUSTOM FILTERS
# =========================================================

def normalize_filter_trigger(
    trigger: str
):

    return clean_text(
        trigger
    ).casefold()[:100]


def save_custom_filter(
    chat_id: int,
    trigger: str,
    response: str,
    created_by: int
):

    trigger = normalize_filter_trigger(
        trigger
    )

    if not trigger:
        raise ValueError(
            "Filter trigger bo'sh."
        )

    if not response:
        raise ValueError(
            "Filter javobi bo'sh."
        )

    db_execute(
        """
        INSERT INTO custom_filters (
            chat_id,
            trigger_text,
            response_text,
            created_by,
            created_at
        )
        VALUES (?, ?, ?, ?, ?)

        ON CONFLICT(chat_id, trigger_text)
        DO UPDATE SET
            response_text = excluded.response_text,
            created_by = excluded.created_by
        """,
        (
            chat_id,
            trigger,
            response,
            created_by,
            iso_now()
        )
    )


def delete_custom_filter(
    chat_id: int,
    trigger: str
):

    db_execute(
        """
        DELETE FROM custom_filters
        WHERE chat_id = ?
          AND trigger_text = ?
        """,
        (
            chat_id,
            normalize_filter_trigger(
                trigger
            )
        )
    )


async def filter_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    chat = update.effective_chat
    user = update.effective_user
    message = update.effective_message

    if (
        not chat
        or not user
        or not message
    ):
        return

    if not await can_manage_group(
        context,
        chat.id,
        user.id
    ):
        return

    raw = (
        message.text or ""
    )

    parts = raw.split(
        maxsplit=2
    )

    if len(parts) < 3:

        await message.reply_text(
            "❗ Foydalanish:\n"
            "/filter salom Assalomu alaykum!"
        )

        return

    trigger = parts[1]
    response = parts[2]

    save_custom_filter(
        chat.id,
        trigger,
        response,
        user.id
    )

    audit(
        "FILTER_SAVED",
        actor_id=user.id,
        target_chat_id=chat.id,
        details=trigger
    )

    await message.reply_text(
        f"✅ Filter saqlandi:\n"
        f"{trigger}"
    )


async def stop_filter_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    chat = update.effective_chat
    user = update.effective_user
    message = update.effective_message

    if (
        not chat
        or not user
        or not message
    ):
        return

    if not await can_manage_group(
        context,
        chat.id,
        user.id
    ):
        return

    if not context.args:

        await message.reply_text(
            "❗ Foydalanish:\n"
            "/stopfilter trigger"
        )

        return

    trigger = context.args[0]

    delete_custom_filter(
        chat.id,
        trigger
    )

    audit(
        "FILTER_DELETED",
        actor_id=user.id,
        target_chat_id=chat.id,
        details=trigger
    )

    await message.reply_text(
        "🗑 Filter o'chirildi."
    )


async def filters_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    chat = update.effective_chat
    message = update.effective_message

    if not chat or not message:
        return

    rows = db_execute(
        """
        SELECT trigger_text
        FROM custom_filters
        WHERE chat_id = ?
        ORDER BY trigger_text COLLATE NOCASE
        LIMIT 100
        """,
        (chat.id,),
        fetchall=True
    )

    if not rows:

        await message.reply_text(
            "🔎 Custom filterlar yo'q."
        )

        return

    await message.reply_text(
        "🔎 FILTERLAR\n\n"
        + "\n".join(
            f"• {row['trigger_text']}"
            for row in rows
        )
    )


async def process_custom_filters(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    chat = update.effective_chat
    message = update.effective_message

    if not chat or not message:
        return False

    text = clean_text(
        message.text
        or message.caption
        or ""
    ).casefold()

    if not text:
        return False

    rows = db_execute(
        """
        SELECT
            trigger_text,
            response_text
        FROM custom_filters
        WHERE chat_id = ?
        """,
        (chat.id,),
        fetchall=True
    )

    for row in rows:

        trigger = (
            row["trigger_text"]
            or ""
        ).casefold()

        if (
            trigger
            and trigger in text
        ):

            try:

                await message.reply_text(
                    row["response_text"]
                )

            except TelegramError:

                pass

            return True

    return False


# =========================================================
# REPORT
# =========================================================

async def report_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    chat = update.effective_chat
    user = update.effective_user
    message = update.effective_message

    if (
        not chat
        or not user
        or not message
    ):
        return

    if chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP,
    ):
        return

    target_message = (
        message.reply_to_message
    )

    if (
        not target_message
        or not target_message.from_user
    ):

        await message.reply_text(
            "❗ Shikoyat qilinadigan "
            "xabarga reply qilib "
            "/report yozing."
        )

        return

    target_user = (
        target_message.from_user
    )

    if target_user.id == user.id:

        await message.reply_text(
            "❌ O'zingizga report "
            "bera olmaysiz."
        )

        return

    reason = " ".join(
        context.args
    ).strip()

    if not reason:
        reason = "Sabab ko'rsatilmagan"

    now = iso_now()

    conn = db_connect()

    try:

        cursor = conn.execute(
            """
            INSERT INTO reports (
                chat_id,
                reporter_id,
                reported_user_id,
                message_id,
                reason,
                status,
                created_at
            )
            VALUES (
                ?, ?, ?, ?, ?,
                'OPEN',
                ?
            )
            """,
            (
                chat.id,
                user.id,
                target_user.id,
                target_message.message_id,
                reason,
                now
            )
        )

        report_id = (
            cursor.lastrowid
        )

        conn.commit()

    finally:

        conn.close()

    audit(
        "USER_REPORTED",
        actor_id=user.id,
        target_user_id=target_user.id,
        target_chat_id=chat.id,
        details=(
            f"report_id={report_id}; "
            f"reason={reason}"
        )
    )

    await message.reply_text(
        (
            "🚨 REPORT QABUL QILINDI\n\n"
            f"🆔 Report: #{report_id}\n"
            f"👤 Shikoyat qilindi: "
            f"{user_display_name(target_user)}\n"
            f"📝 Sabab: {reason}\n\n"
            "Moderatorlarga xabar berildi."
        )
    )

    # Telegram adminlar ro'yxatini olib,
    # ularga shaxsiy xabar yuborishga urinadi.

    try:

        admins = (
            await context.bot.get_chat_administrators(
                chat.id
            )
        )

        for admin in admins:

            admin_user = admin.user

            if admin_user.is_bot:
                continue

            try:

                await context.bot.send_message(
                    chat_id=admin_user.id,
                    text=(
                        "🚨 VERITAS REPORT\n\n"
                        f"🏢 {chat.title}\n"
                        f"🆔 Report: #{report_id}\n"
                        f"👤 Reporter: "
                        f"{user_display_name(user)} "
                        f"({user.id})\n"
                        f"⚠️ User: "
                        f"{user_display_name(target_user)} "
                        f"({target_user.id})\n"
                        f"📝 Sabab: {reason}"
                    )
                )

            except TelegramError:

                pass

    except TelegramError:

        pass


# =========================================================
# REPORTS LIST
# =========================================================

async def show_group_reports(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int
):

    query = update.callback_query
    user = update.effective_user

    if not query or not user:
        return

    if not await can_manage_group(
        context,
        chat_id,
        user.id
    ):

        await query.answer(
            "⛔ Ruxsat yo'q.",
            show_alert=True
        )

        return

    rows = db_execute(
        """
        SELECT *
        FROM reports
        WHERE chat_id = ?
        ORDER BY id DESC
        LIMIT 20
        """,
        (chat_id,),
        fetchall=True
    )

    lines = [
        "🚨 REPORTLAR",
        ""
    ]

    if not rows:

        lines.append(
            "Reportlar yo'q."
        )

    else:

        for row in rows:

            lines.append(
                (
                    f"#{row['id']} | "
                    f"{row['status']}\n"
                    f"👤 {row['reported_user_id']}\n"
                    f"📝 {row['reason']}"
                )
            )

    await query.answer()

    await query.edit_message_text(
        "\n\n".join(lines),
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "⬅️ Guruh",
                        callback_data=(
                            f"group:open:{chat_id}"
                        )
                    )
                ]
            ]
        )
    )


# =========================================================
# NORMAL GROUP CONTENT ROUTER
# =========================================================

async def process_group_content(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    chat = update.effective_chat
    user = update.effective_user

    if not chat or not user:
        return False

    if chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP,
    ):
        return False

    # Himoya tizimi birinchi ishlaydi.

    blocked = await process_group_protection(
        update,
        context
    )

    if blocked:
        return True

    # #note

    if await process_note_trigger(
        update,
        context
    ):
        return True

    # Custom filters

    if await process_custom_filters(
        update,
        context
    ):
        return True

    return False


# =========================================================
# END PART 9
# =========================================================
# =========================================================
# VERITAS BOT V7
# PART 10 — ACTIVITY, XP, LEVELS & REWARDS
# =========================================================


# =========================================================
# LEVEL SYSTEM
# =========================================================

def calculate_level(xp: int) -> int:
    xp = max(0, safe_int(xp))

    # Har keyingi level uchun talab oshib boradi.
    # 0 XP = Level 1
    return max(
        1,
        int((xp / 100) ** 0.5) + 1
    )


def level_title(level: int) -> str:
    level = max(1, safe_int(level, 1))

    if level >= 50:
        return "👑 Afsona"

    if level >= 40:
        return "💎 Ustoz"

    if level >= 30:
        return "🏆 Yetakchi"

    if level >= 20:
        return "🔥 Faol"

    if level >= 10:
        return "⭐ Ishtirokchi"

    if level >= 5:
        return "🌱 Rivojlanuvchi"

    return "👤 A'zo"


# =========================================================
# REGISTER ACTIVITY
# =========================================================

def register_member_activity(
    chat_id: int,
    user: User
):
    if not user:
        return

    ensure_user(user)

    now = iso_now()

    conn = db_connect()

    try:
        row = conn.execute(
            """
            SELECT
                message_count,
                daily_messages,
                weekly_messages,
                xp
            FROM group_members
            WHERE chat_id = ?
              AND user_id = ?
            """,
            (
                chat_id,
                user.id
            )
        ).fetchone()

        if not row:
            conn.execute(
                """
                INSERT INTO group_members (
                    chat_id,
                    user_id,
                    message_count,
                    daily_messages,
                    weekly_messages,
                    xp,
                    level,
                    last_message_at,
                    joined_at
                )
                VALUES (
                    ?, ?, 1, 1, 1,
                    1, 1, ?, ?
                )
                """,
                (
                    chat_id,
                    user.id,
                    now,
                    now
                )
            )

            group_xp = 1

        else:
            group_xp = (
                safe_int(row["xp"])
                + 1
            )

            group_level = calculate_level(
                group_xp
            )

            conn.execute(
                """
                UPDATE group_members
                SET
                    message_count =
                        message_count + 1,
                    daily_messages =
                        daily_messages + 1,
                    weekly_messages =
                        weekly_messages + 1,
                    xp = ?,
                    level = ?,
                    last_message_at = ?
                WHERE chat_id = ?
                  AND user_id = ?
                """,
                (
                    group_xp,
                    group_level,
                    now,
                    chat_id,
                    user.id
                )
            )

        global_row = conn.execute(
            """
            SELECT xp
            FROM users
            WHERE user_id = ?
            """,
            (user.id,)
        ).fetchone()

        global_xp = (
            safe_int(global_row["xp"])
            if global_row
            else 0
        ) + 1

        global_level = calculate_level(
            global_xp
        )

        title = level_title(
            global_level
        )

        conn.execute(
            """
            UPDATE users
            SET
                xp = ?,
                level = ?,
                title = ?,
                last_seen_at = ?,
                updated_at = ?
            WHERE user_id = ?
            """,
            (
                global_xp,
                global_level,
                title,
                now,
                now,
                user.id
            )
        )

        conn.commit()

    finally:
        conn.close()


# =========================================================
# ACTIVITY MESSAGE PROCESSOR
# =========================================================

async def process_activity(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    chat = update.effective_chat
    user = update.effective_user
    message = update.effective_message

    if (
        not chat
        or not user
        or not message
    ):
        return False

    if chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP,
    ):
        return False

    if user.is_bot:
        return False

    # Service xabarlarni hisoblamaymiz.
    if (
        message.new_chat_members
        or message.left_chat_member
    ):
        return False

    register_member_activity(
        chat.id,
        user
    )

    return False


# =========================================================
# MY ACTIVITY
# =========================================================

async def activity_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    chat = update.effective_chat
    user = update.effective_user
    message = update.effective_message

    if (
        not chat
        or not user
        or not message
    ):
        return

    if chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP,
    ):
        await message.reply_text(
            "ℹ️ Faollik statistikasi "
            "guruh ichida ishlaydi."
        )
        return

    row = db_execute(
        """
        SELECT *
        FROM group_members
        WHERE chat_id = ?
          AND user_id = ?
        """,
        (
            chat.id,
            user.id
        ),
        fetchone=True
    )

    if not row:
        await message.reply_text(
            "📊 Siz uchun hali "
            "faollik statistikasi yo'q."
        )
        return

    await message.reply_text(
        (
            "📊 SIZNING FAOLLIGINGIZ\n\n"
            f"💬 Jami xabar: "
            f"{safe_int(row['message_count'])}\n"
            f"☀️ Bugun: "
            f"{safe_int(row['daily_messages'])}\n"
            f"📅 Bu hafta: "
            f"{safe_int(row['weekly_messages'])}\n"
            f"✨ XP: "
            f"{safe_int(row['xp'])}\n"
            f"🏅 Level: "
            f"{safe_int(row['level'], 1)}"
        )
    )


# =========================================================
# TOP LIST HELPERS
# =========================================================

def get_daily_top(
    chat_id: int,
    limit: int = 10
):
    return db_execute(
        """
        SELECT
            gm.user_id,
            gm.daily_messages,
            gm.xp,
            gm.level,
            u.first_name,
            u.username
        FROM group_members gm

        LEFT JOIN users u
            ON u.user_id = gm.user_id

        WHERE gm.chat_id = ?
          AND gm.daily_messages > 0

        ORDER BY
            gm.daily_messages DESC,
            gm.xp DESC

        LIMIT ?
        """,
        (
            chat_id,
            limit
        ),
        fetchall=True
    )


def get_weekly_top(
    chat_id: int,
    limit: int = 10
):
    return db_execute(
        """
        SELECT
            gm.user_id,
            gm.weekly_messages,
            gm.xp,
            gm.level,
            u.first_name,
            u.username
        FROM group_members gm

        LEFT JOIN users u
            ON u.user_id = gm.user_id

        WHERE gm.chat_id = ?
          AND gm.weekly_messages > 0

        ORDER BY
            gm.weekly_messages DESC,
            gm.xp DESC

        LIMIT ?
        """,
        (
            chat_id,
            limit
        ),
        fetchall=True
    )


def activity_name(row):
    if row["first_name"]:
        return row["first_name"]

    if row["username"]:
        return f"@{row['username']}"

    return str(row["user_id"])


# =========================================================
# DAILY TOP
# =========================================================

async def daily_top_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    chat = update.effective_chat
    message = update.effective_message

    if not chat or not message:
        return

    if chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP,
    ):
        return

    rows = get_daily_top(
        chat.id,
        10
    )

    lines = [
        "☀️ BUGUNGI TOP",
        ""
    ]

    if not rows:
        lines.append(
            "Bugun hali faollik yo'q."
        )

    else:
        medals = {
            1: "🥇",
            2: "🥈",
            3: "🥉",
        }

        for index, row in enumerate(
            rows,
            start=1
        ):
            icon = medals.get(
                index,
                f"{index}."
            )

            lines.append(
                (
                    f"{icon} "
                    f"{activity_name(row)} — "
                    f"{safe_int(row['daily_messages'])} "
                    "xabar"
                )
            )

    await message.reply_text(
        "\n".join(lines)
    )


# =========================================================
# WEEKLY TOP
# =========================================================

async def weekly_top_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    chat = update.effective_chat
    message = update.effective_message

    if not chat or not message:
        return

    if chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP,
    ):
        return

    rows = get_weekly_top(
        chat.id,
        10
    )

    lines = [
        "📅 HAFTALIK TOP",
        ""
    ]

    if not rows:
        lines.append(
            "Bu hafta hali faollik yo'q."
        )

    else:
        medals = {
            1: "🥇",
            2: "🥈",
            3: "🥉",
        }

        for index, row in enumerate(
            rows,
            start=1
        ):
            icon = medals.get(
                index,
                f"{index}."
            )

            lines.append(
                (
                    f"{icon} "
                    f"{activity_name(row)} — "
                    f"{safe_int(row['weekly_messages'])} "
                    "xabar"
                )
            )

    await message.reply_text(
        "\n".join(lines)
    )


# =========================================================
# *GIVE COMMAND
# =========================================================
#
# Reply qilib:
#
# *give 25
# *give 50
# *give 100
#
# Faqat Super Ega yoki guruh boshqaruvchisi.
# Bu VERITAS ICHKI STARS.
# =========================================================

async def star_give_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user

    if (
        not message
        or not chat
        or not user
    ):
        return False

    text = (
        message.text or ""
    ).strip()

    match = re.fullmatch(
        r"\*give\s+(25|50|100)",
        text,
        flags=re.IGNORECASE
    )

    if not match:
        return False

    if chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP,
    ):
        await message.reply_text(
            "❌ *give guruhda ishlaydi."
        )
        return True

    if not await can_manage_group(
        context,
        chat.id,
        user.id
    ):
        await message.reply_text(
            "⛔ Sizda Stars berish "
            "huquqi yo'q."
        )
        return True

    reply = message.reply_to_message

    if (
        not reply
        or not reply.from_user
    ):
        await message.reply_text(
            "❗ Foydalanuvchi xabariga "
            "reply qilib yozing:\n\n"
            "*give 25\n"
            "*give 50\n"
            "*give 100"
        )
        return True

    target = reply.from_user

    if target.is_bot:
        await message.reply_text(
            "❌ Botga Stars berib bo'lmaydi."
        )
        return True

    amount = int(
        match.group(1)
    )

    ensure_user(target)

    try:
        new_balance = change_internal_balance(
            target.id,
            amount,
            "GROUP_GIVE",
            description=(
                f"{chat.title} guruhida "
                "berilgan mukofot"
            ),
            reference=(
                f"give:{chat.id}:"
                f"{message.message_id}"
            ),
            created_by=user.id
        )

        db_execute(
            """
            INSERT INTO user_rewards (
                user_id,
                reward_type,
                reward_value,
                star_value,
                reason,
                status,
                granted_by,
                created_at
            )
            VALUES (
                ?,
                'VERITAS_STARS',
                ?,
                ?,
                ?,
                'GRANTED',
                ?,
                ?
            )
            """,
            (
                target.id,
                str(amount),
                amount,
                (
                    f"{chat.title} "
                    "guruh mukofoti"
                ),
                user.id,
                iso_now()
            )
        )

        audit(
            "GROUP_STARS_GIVEN",
            actor_id=user.id,
            target_user_id=target.id,
            target_chat_id=chat.id,
            details=f"amount={amount}"
        )

    except Exception as exc:
        logger.exception(
            "*give xatosi"
        )

        await message.reply_text(
            f"❌ {error_text(exc)}"
        )
        return True

    await message.reply_text(
        (
            "🎁 MUKOFOT BERILDI\n\n"
            f"👤 {user_display_name(target)}\n"
            f"⭐ +{amount} Veritas Stars\n"
            f"💰 Balans: {new_balance} ⭐"
        )
    )

    return True


# =========================================================
# DAILY REWARDS
# =========================================================

async def distribute_daily_rewards(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int
):
    rows = get_daily_top(
        chat_id,
        3
    )

    if not rows:
        return []

    results = []

    for position, row in enumerate(
        rows,
        start=1
    ):
        amount = DAILY_TOP_REWARDS.get(
            position
        )

        if not amount:
            continue

        user_id = safe_int(
            row["user_id"]
        )

        try:
            new_balance = (
                change_internal_balance(
                    user_id,
                    amount,
                    "DAILY_ACTIVITY_REWARD",
                    description=(
                        f"{chat_id} guruh "
                        f"kunlik TOP-{position}"
                    ),
                    reference=(
                        f"daily:{chat_id}:"
                        f"{utc_timestamp()}:"
                        f"{position}"
                    ),
                    created_by=None
                )
            )

            db_execute(
                """
                INSERT INTO user_rewards (
                    user_id,
                    reward_type,
                    reward_value,
                    star_value,
                    reason,
                    status,
                    granted_by,
                    created_at
                )
                VALUES (
                    ?,
                    'DAILY_TOP',
                    ?,
                    ?,
                    ?,
                    'GRANTED',
                    NULL,
                    ?
                )
                """,
                (
                    user_id,
                    f"TOP-{position}",
                    amount,
                    (
                        f"Kunlik TOP-{position} "
                        f"| chat={chat_id}"
                    ),
                    iso_now()
                )
            )

            results.append(
                {
                    "position": position,
                    "user_id": user_id,
                    "amount": amount,
                    "balance": new_balance,
                }
            )

        except Exception:
            logger.exception(
                "Kunlik mukofot xatosi: "
                "chat=%s user=%s",
                chat_id,
                user_id
            )

    return results


# =========================================================
# WEEKLY REWARD
# =========================================================

async def distribute_weekly_reward(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int
):
    rows = get_weekly_top(
        chat_id,
        1
    )

    if not rows:
        return None

    winner = rows[0]

    user_id = safe_int(
        winner["user_id"]
    )

    amount = WEEKLY_TOP_REWARD

    try:
        new_balance = (
            change_internal_balance(
                user_id,
                amount,
                "WEEKLY_ACTIVITY_REWARD",
                description=(
                    f"{chat_id} guruh "
                    "haftalik TOP-1"
                ),
                reference=(
                    f"weekly:{chat_id}:"
                    f"{utc_timestamp()}"
                ),
                created_by=None
            )
        )

        db_execute(
            """
            INSERT INTO user_rewards (
                user_id,
                reward_type,
                reward_value,
                star_value,
                reason,
                status,
                granted_by,
                created_at
            )
            VALUES (
                ?,
                'WEEKLY_TOP',
                'TOP-1',
                ?,
                ?,
                'GRANTED',
                NULL,
                ?
            )
            """,
            (
                user_id,
                amount,
                (
                    "Haftalik TOP-1 "
                    f"| chat={chat_id}"
                ),
                iso_now()
            )
        )

        return {
            "user_id": user_id,
            "amount": amount,
            "balance": new_balance,
        }

    except Exception:
        logger.exception(
            "Haftalik mukofot xatosi."
        )

        return None


# =========================================================
# RESET DAILY COUNTERS
# =========================================================

def reset_daily_activity(
    chat_id: int
):
    db_execute(
        """
        UPDATE group_members
        SET daily_messages = 0
        WHERE chat_id = ?
        """,
        (chat_id,)
    )


# =========================================================
# RESET WEEKLY COUNTERS
# =========================================================

def reset_weekly_activity(
    chat_id: int
):
    db_execute(
        """
        UPDATE group_members
        SET weekly_messages = 0
        WHERE chat_id = ?
        """,
        (chat_id,)
    )


# =========================================================
# DAILY REWARD JOB
# =========================================================

async def daily_reward_job(
    context: ContextTypes.DEFAULT_TYPE
):
    groups = db_execute(
        """
        SELECT chat_id
        FROM groups
        WHERE is_active = 1
          AND rewards_enabled = 1
        """,
        fetchall=True
    )

    for group in groups:
        chat_id = safe_int(
            group["chat_id"]
        )

        try:
            results = (
                await distribute_daily_rewards(
                    context,
                    chat_id
                )
            )

            if results:
                lines = [
                    "🎁 KUNLIK FAOLLIK MUKOFOTI",
                    ""
                ]

                for result in results:
                    lines.append(
                        (
                            f"TOP-{result['position']} "
                            f"— {result['user_id']} "
                            f"— +{result['amount']} ⭐"
                        )
                    )

                try:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text="\n".join(lines)
                    )
                except TelegramError:
                    pass

            reset_daily_activity(
                chat_id
            )

        except Exception:
            logger.exception(
                "Daily reward job: %s",
                chat_id
            )


# =========================================================
# WEEKLY REWARD JOB
# =========================================================

async def weekly_reward_job(
    context: ContextTypes.DEFAULT_TYPE
):
    groups = db_execute(
        """
        SELECT chat_id
        FROM groups
        WHERE is_active = 1
          AND rewards_enabled = 1
        """,
        fetchall=True
    )

    for group in groups:
        chat_id = safe_int(
            group["chat_id"]
        )

        try:
            winner = (
                await distribute_weekly_reward(
                    context,
                    chat_id
                )
            )

            if winner:
                try:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=(
                            "🏆 HAFTALIK G'OLIB\n\n"
                            f"👤 ID: "
                            f"{winner['user_id']}\n"
                            f"🎁 Mukofot: "
                            f"{winner['amount']} ⭐"
                        )
                    )
                except TelegramError:
                    pass

            reset_weekly_activity(
                chat_id
            )

        except Exception:
            logger.exception(
                "Weekly reward job: %s",
                chat_id
            )


# =========================================================
# GROUP ACTIVITY PANEL
# =========================================================

async def show_group_activity_panel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int
):
    query = update.callback_query
    user = update.effective_user

    if not query or not user:
        return

    if not await can_manage_group(
        context,
        chat_id,
        user.id
    ):
        await query.answer(
            "⛔ Ruxsat yo'q.",
            show_alert=True
        )
        return

    daily = get_daily_top(
        chat_id,
        5
    )

    weekly = get_weekly_top(
        chat_id,
        5
    )

    lines = [
        "📊 GURUH FAOLLIGI",
        "",
        "☀️ Bugungi TOP:"
    ]

    if daily:
        for index, row in enumerate(
            daily,
            start=1
        ):
            lines.append(
                (
                    f"{index}. "
                    f"{activity_name(row)} — "
                    f"{row['daily_messages']}"
                )
            )
    else:
        lines.append("—")

    lines.extend(
        [
            "",
            "📅 Haftalik TOP:"
        ]
    )

    if weekly:
        for index, row in enumerate(
            weekly,
            start=1
        ):
            lines.append(
                (
                    f"{index}. "
                    f"{activity_name(row)} — "
                    f"{row['weekly_messages']}"
                )
            )
    else:
        lines.append("—")

    await query.answer()

    await query.edit_message_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "⬅️ Guruh",
                        callback_data=(
                            f"group:open:{chat_id}"
                        )
                    )
                ]
            ]
        )
    )


# =========================================================
# ACTIVITY CALLBACK
# =========================================================

async def activity_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query

    if not query:
        return

    data = query.data or ""

    if data.startswith(
        "group:activity:"
    ):
        try:
            chat_id = int(
                data.rsplit(
                    ":",
                    1
                )[1]
            )
        except ValueError:
            return

        await show_group_activity_panel(
            update,
            context,
            chat_id
        )


# =========================================================
# END PART 10
# =========================================================
# =========================================================
# VERITAS BOT V7
# PART 11 — SUPER OWNER CONTROL CENTER
# =========================================================


# =========================================================
# SUPER OWNER MAIN KEYBOARD
# =========================================================

def super_owner_keyboard():

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "👤 Foydalanuvchilar",
                    callback_data="super:users"
                ),
                InlineKeyboardButton(
                    "👥 Guruhlar",
                    callback_data="super:groups"
                )
            ],
            [
                InlineKeyboardButton(
                    "💳 Tranzaksiyalar",
                    callback_data="super:transactions"
                ),
                InlineKeyboardButton(
                    "🎁 Mukofotlar",
                    callback_data="super:rewards"
                )
            ],
            [
                InlineKeyboardButton(
                    "📚 Kutubxona",
                    callback_data="super:library"
                ),
                InlineKeyboardButton(
                    "📊 Statistika",
                    callback_data="super:stats"
                )
            ],
            [
                InlineKeyboardButton(
                    "⚙️ Super Sozlamalar",
                    callback_data="super:settings"
                )
            ],
            [
                InlineKeyboardButton(
                    "🔎 ID orqali kabinet",
                    callback_data="super:find_user"
                ),
                InlineKeyboardButton(
                    "📋 Audit log",
                    callback_data="super:audit"
                )
            ],
            [
                InlineKeyboardButton(
                    "⭐ Bot Stars balansi",
                    callback_data="super:real_star_balance"
                )
            ],
            [
                InlineKeyboardButton(
                    "⬅️ Shaxsiy kabinet",
                    callback_data="user:home"
                )
            ]
        ]
    )


# =========================================================
# SUPER OWNER HOME
# =========================================================

async def show_super_home(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    if not user:
        return

    if not is_super_owner_id(
        user.id
    ):

        if update.callback_query:

            await update.callback_query.answer(
                "⛔ Super Ega huquqi yo'q.",
                show_alert=True
            )

        return

    users = db_execute(
        """
        SELECT COUNT(*) AS total
        FROM users
        """,
        fetchone=True
    )

    groups = db_execute(
        """
        SELECT COUNT(*) AS total
        FROM groups
        WHERE is_active = 1
        """,
        fetchone=True
    )

    demo_groups = db_execute(
        """
        SELECT COUNT(*) AS total
        FROM subscriptions
        WHERE plan = 'DEMO'
          AND status = 'ACTIVE'
        """,
        fetchone=True
    )

    v7_groups = db_execute(
        """
        SELECT COUNT(*) AS total
        FROM subscriptions
        WHERE plan = 'V7'
          AND status = 'ACTIVE'
        """,
        fetchone=True
    )

    user_count = (
        safe_int(users["total"])
        if users else 0
    )

    group_count = (
        safe_int(groups["total"])
        if groups else 0
    )

    demo_count = (
        safe_int(demo_groups["total"])
        if demo_groups else 0
    )

    v7_count = (
        safe_int(v7_groups["total"])
        if v7_groups else 0
    )

    text = (
        "👑 VERITAS SUPER EGA\n\n"
        f"👤 Foydalanuvchilar: "
        f"{user_count}\n"
        f"👥 Faol guruhlar: "
        f"{group_count}\n"
        f"🎁 Demo guruhlar: "
        f"{demo_count}\n"
        f"💎 V7 guruhlar: "
        f"{v7_count}\n\n"
        f"🤖 {BOT_FULL_NAME}"
    )

    if update.callback_query:

        query = update.callback_query

        await query.answer()

        try:

            await query.edit_message_text(
                text,
                reply_markup=(
                    super_owner_keyboard()
                )
            )

        except BadRequest:

            pass

    else:

        await update.effective_message.reply_text(
            text,
            reply_markup=(
                super_owner_keyboard()
            )
        )


# =========================================================
# /SUPER COMMAND
# =========================================================

async def super_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    if not user:
        return

    if not is_super_owner_id(
        user.id
    ):

        await update.effective_message.reply_text(
            "⛔ Bu bo'lim faqat Super Ega uchun."
        )

        return

    await show_super_home(
        update,
        context
    )


# =========================================================
# USERS LIST
# =========================================================

async def show_super_users(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not await require_super_owner(
        update
    ):
        return

    query = update.callback_query

    rows = db_execute(
        """
        SELECT
            user_id,
            username,
            first_name,
            internal_balance,
            level,
            is_blocked
        FROM users
        ORDER BY updated_at DESC
        LIMIT 30
        """,
        fetchall=True
    )

    lines = [
        "👤 FOYDALANUVCHILAR",
        ""
    ]

    if not rows:

        lines.append(
            "Foydalanuvchilar yo'q."
        )

    else:

        for row in rows:

            name = (
                row["first_name"]
                or (
                    f"@{row['username']}"
                    if row["username"]
                    else "Noma'lum"
                )
            )

            blocked = (
                " 🚫"
                if safe_int(
                    row["is_blocked"]
                )
                else ""
            )

            lines.append(
                (
                    f"👤 {name}{blocked}\n"
                    f"🆔 {row['user_id']} | "
                    f"⭐ {safe_int(row['internal_balance'])} | "
                    f"🏅 L{safe_int(row['level'], 1)}"
                )
            )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🔎 ID orqali ochish",
                    callback_data="super:find_user"
                )
            ],
            [
                InlineKeyboardButton(
                    "⬅️ Super Ega",
                    callback_data="super:home"
                )
            ]
        ]
    )

    await query.answer()

    await query.edit_message_text(
        "\n\n".join(lines),
        reply_markup=keyboard
    )


# =========================================================
# GROUPS LIST
# =========================================================

async def show_super_groups(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not await require_super_owner(
        update
    ):
        return

    query = update.callback_query

    rows = db_execute(
        """
        SELECT
            g.chat_id,
            g.title,
            g.owner_id,
            g.is_active,
            s.plan,
            s.status,
            s.expires_at
        FROM groups g

        LEFT JOIN subscriptions s
            ON s.chat_id = g.chat_id

        ORDER BY g.updated_at DESC
        LIMIT 30
        """,
        fetchall=True
    )

    keyboard_rows = []

    lines = [
        "👥 GURUHLAR",
        ""
    ]

    if not rows:

        lines.append(
            "Guruhlar topilmadi."
        )

    else:

        for row in rows:

            plan = (
                row["plan"]
                or "YO'Q"
            )

            status = (
                row["status"]
                or "INACTIVE"
            )

            lines.append(
                (
                    f"🏢 {row['title']}\n"
                    f"🆔 {row['chat_id']}\n"
                    f"💎 {plan} | {status}"
                )
            )

            keyboard_rows.append(
                [
                    InlineKeyboardButton(
                        (
                            "🏢 "
                            + (
                                row["title"]
                                or str(
                                    row["chat_id"]
                                )
                            )[:35]
                        ),
                        callback_data=(
                            f"group:open:"
                            f"{row['chat_id']}"
                        )
                    )
                ]
            )

    keyboard_rows.append(
        [
            InlineKeyboardButton(
                "⬅️ Super Ega",
                callback_data="super:home"
            )
        ]
    )

    await query.answer()

    await query.edit_message_text(
        "\n\n".join(lines),
        reply_markup=InlineKeyboardMarkup(
            keyboard_rows
        )
    )


# =========================================================
# STATISTICS
# =========================================================

async def show_super_statistics(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not await require_super_owner(
        update
    ):
        return

    query = update.callback_query

    users = db_execute(
        """
        SELECT COUNT(*) AS total
        FROM users
        """,
        fetchone=True
    )

    groups = db_execute(
        """
        SELECT COUNT(*) AS total
        FROM groups
        """,
        fetchone=True
    )

    active_groups = db_execute(
        """
        SELECT COUNT(*) AS total
        FROM groups
        WHERE is_active = 1
        """,
        fetchone=True
    )

    total_internal = db_execute(
        """
        SELECT
            COALESCE(
                SUM(internal_balance),
                0
            ) AS total
        FROM users
        """,
        fetchone=True
    )

    successful_payments = db_execute(
        """
        SELECT
            COUNT(*) AS count,
            COALESCE(
                SUM(amount),
                0
            ) AS amount
        FROM star_payments
        WHERE status = 'SUCCESS'
        """,
        fetchone=True
    )

    refunded = db_execute(
        """
        SELECT
            COUNT(*) AS count,
            COALESCE(
                SUM(amount),
                0
            ) AS amount
        FROM star_payments
        WHERE status = 'REFUNDED'
        """,
        fetchone=True
    )

    rewards = db_execute(
        """
        SELECT
            COUNT(*) AS count,
            COALESCE(
                SUM(star_value),
                0
            ) AS amount
        FROM user_rewards
        """,
        fetchone=True
    )

    reports = db_execute(
        """
        SELECT COUNT(*) AS total
        FROM reports
        WHERE status = 'OPEN'
        """,
        fetchone=True
    )

    text = (
        "📊 VERITAS STATISTIKA\n\n"

        f"👤 Foydalanuvchilar: "
        f"{safe_int(users['total']) if users else 0}\n"

        f"👥 Jami guruhlar: "
        f"{safe_int(groups['total']) if groups else 0}\n"

        f"🟢 Faol guruhlar: "
        f"{safe_int(active_groups['total']) if active_groups else 0}\n\n"

        f"⭐ Ichki balanslar jami: "
        f"{safe_int(total_internal['total']) if total_internal else 0}\n\n"

        "💳 Telegram Stars to'lovlari:\n"
        f"✅ Muvaffaqiyatli: "
        f"{safe_int(successful_payments['count']) if successful_payments else 0}\n"
        f"⭐ Qabul qilingan: "
        f"{safe_int(successful_payments['amount']) if successful_payments else 0}\n\n"

        f"↩️ Refundlar: "
        f"{safe_int(refunded['count']) if refunded else 0}\n"
        f"⭐ Qaytarilgan: "
        f"{safe_int(refunded['amount']) if refunded else 0}\n\n"

        f"🎁 Mukofotlar soni: "
        f"{safe_int(rewards['count']) if rewards else 0}\n"
        f"⭐ Mukofot qiymati: "
        f"{safe_int(rewards['amount']) if rewards else 0}\n\n"

        f"🚨 Ochiq reportlar: "
        f"{safe_int(reports['total']) if reports else 0}"
    )

    await query.answer()

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "⭐ Real Stars balans",
                        callback_data=(
                            "super:real_star_balance"
                        )
                    )
                ],
                [
                    InlineKeyboardButton(
                        "⬅️ Super Ega",
                        callback_data="super:home"
                    )
                ]
            ]
        )
    )


# =========================================================
# TRANSACTIONS
# =========================================================

async def show_super_transactions(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not await require_super_owner(
        update
    ):
        return

    query = update.callback_query

    rows = db_execute(
        """
        SELECT *
        FROM transactions
        ORDER BY id DESC
        LIMIT 30
        """,
        fetchall=True
    )

    lines = [
        "💳 OXIRGI TRANZAKSIYALAR",
        ""
    ]

    if not rows:

        lines.append(
            "Tranzaksiyalar yo'q."
        )

    else:

        for row in rows:

            lines.append(
                (
                    f"#{row['id']} "
                    f"{row['transaction_type']}\n"
                    f"👤 {row['user_id'] or '-'} | "
                    f"⭐ {row['amount'] or 0}\n"
                    f"📌 {row['status']}\n"
                    f"🕒 {row['created_at']}"
                )
            )

    await query.answer()

    await query.edit_message_text(
        "\n\n".join(lines),
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "⬅️ Super Ega",
                        callback_data="super:home"
                    )
                ]
            ]
        )
    )


# =========================================================
# FIND USER BY ID
# =========================================================

async def ask_super_user_id(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not await require_super_owner(
        update
    ):
        return

    user = update.effective_user
    query = update.callback_query

    USER_STATES[user.id] = {
        "state": "WAIT_SUPER_USER_ID"
    }

    await query.answer()

    await query.edit_message_text(
        (
            "🔎 ID ORQALI KABINET\n\n"
            "Foydalanuvchining Telegram ID "
            "raqamini yuboring.\n\n"
            "Masalan:\n"
            "123456789"
        ),
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "❌ Bekor qilish",
                        callback_data="super:home"
                    )
                ]
            ]
        )
    )


# =========================================================
# SUPER USER CABINET
# =========================================================

def super_user_keyboard(
    target_user_id: int
):

    blocked_row = get_user_record(
        target_user_id
    )

    blocked = bool(
        safe_int(
            blocked_row["is_blocked"]
            if blocked_row else 0
        )
    )

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🎁 Mukofot berish",
                    callback_data=(
                        f"super:user_reward:"
                        f"{target_user_id}"
                    )
                )
            ],
            [
                InlineKeyboardButton(
                    "⭐ + Stars",
                    callback_data=(
                        f"super:user_addstars:"
                        f"{target_user_id}"
                    )
                ),
                InlineKeyboardButton(
                    "⭐ - Stars",
                    callback_data=(
                        f"super:user_removestars:"
                        f"{target_user_id}"
                    )
                )
            ],
            [
                InlineKeyboardButton(
                    (
                        "✅ Blokdan chiqarish"
                        if blocked
                        else "🚫 Bloklash"
                    ),
                    callback_data=(
                        f"super:user_block:"
                        f"{target_user_id}"
                    )
                )
            ],
            [
                InlineKeyboardButton(
                    "📜 Tranzaksiyalari",
                    callback_data=(
                        f"super:user_transactions:"
                        f"{target_user_id}"
                    )
                )
            ],
            [
                InlineKeyboardButton(
                    "⬅️ Foydalanuvchilar",
                    callback_data="super:users"
                )
            ]
        ]
    )


async def show_super_user_cabinet(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    target_user_id: int
):

    if not await require_super_owner(
        update
    ):
        return

    query = update.callback_query

    row = get_user_record(
        target_user_id
    )

    if not row:

        await query.answer(
            "❌ Foydalanuvchi bazada topilmadi.",
            show_alert=True
        )

        return

    username = (
        f"@{row['username']}"
        if row["username"]
        else "yo'q"
    )

    blocked = (
        "🚫 Bloklangan"
        if safe_int(row["is_blocked"])
        else "✅ Faol"
    )

    text = (
        "👤 FOYDALANUVCHI KABINETI\n\n"
        f"👤 {row['first_name'] or 'Nomaʼlum'}\n"
        f"🆔 {row['user_id']}\n"
        f"🏷 {username}\n"
        f"🌐 {row['language']}\n\n"
        f"⭐ Balans: "
        f"{safe_int(row['internal_balance'])}\n"
        f"✨ XP: "
        f"{safe_int(row['xp'])}\n"
        f"🏅 Level: "
        f"{safe_int(row['level'], 1)}\n"
        f"🎖 {row['title'] or 'Aʼzo'}\n\n"
        f"📌 {blocked}\n"
        f"🕒 Oxirgi faollik: "
        f"{row['last_seen_at'] or '-'}"
    )

    await query.answer()

    await query.edit_message_text(
        text,
        reply_markup=(
            super_user_keyboard(
                target_user_id
            )
        )
    )


# =========================================================
# HANDLE USER ID STATE
# =========================================================

async def handle_super_user_id(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user
    message = update.effective_message

    if not user or not message:
        return False

    state = USER_STATES.get(
        user.id
    )

    if not state:
        return False

    if (
        state.get("state")
        != "WAIT_SUPER_USER_ID"
    ):
        return False

    if not is_super_owner_id(
        user.id
    ):

        USER_STATES.pop(
            user.id,
            None
        )

        return True

    try:

        target_user_id = int(
            (message.text or "").strip()
        )

    except ValueError:

        await message.reply_text(
            "❌ Telegram ID raqam bo'lishi kerak."
        )

        return True

    row = get_user_record(
        target_user_id
    )

    if not row:

        await message.reply_text(
            "❌ Bu ID bazada topilmadi."
        )

        return True

    USER_STATES.pop(
        user.id,
        None
    )

    text = (
        "👤 FOYDALANUVCHI TOPILDI\n\n"
        f"👤 {row['first_name'] or 'Nomaʼlum'}\n"
        f"🆔 {row['user_id']}\n"
        f"⭐ Balans: "
        f"{safe_int(row['internal_balance'])}\n"
        f"🏅 Level: "
        f"{safe_int(row['level'], 1)}"
    )

    await message.reply_text(
        text,
        reply_markup=(
            super_user_keyboard(
                target_user_id
            )
        )
    )

    return True


# =========================================================
# ADD / REMOVE USER STARS
# =========================================================

async def start_super_balance_edit(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    target_user_id: int,
    mode: str
):

    if not await require_super_owner(
        update
    ):
        return

    query = update.callback_query
    user = update.effective_user

    row = get_user_record(
        target_user_id
    )

    if not row:

        await query.answer(
            "❌ User topilmadi.",
            show_alert=True
        )
        return

    USER_STATES[user.id] = {
        "state": "WAIT_SUPER_BALANCE_AMOUNT",
        "target_user_id": target_user_id,
        "mode": mode,
    }

    action_text = (
        "qo'shiladigan"
        if mode == "add"
        else "ayiriladigan"
    )

    await query.answer()

    await query.edit_message_text(
        (
            f"⭐ STARS {action_text.upper()}\n\n"
            f"👤 ID: {target_user_id}\n"
            f"💰 Hozirgi balans: "
            f"{safe_int(row['internal_balance'])} ⭐\n\n"
            f"{action_text.capitalize()} "
            "Stars miqdorini yuboring."
        ),
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "❌ Bekor qilish",
                        callback_data=(
                            f"super:user:"
                            f"{target_user_id}"
                        )
                    )
                ]
            ]
        )
    )


async def handle_super_balance_amount(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user
    message = update.effective_message

    if not user or not message:
        return False

    state = USER_STATES.get(
        user.id
    )

    if not state:
        return False

    if (
        state.get("state")
        != "WAIT_SUPER_BALANCE_AMOUNT"
    ):
        return False

    if not is_super_owner_id(
        user.id
    ):
        return True

    try:

        amount = int(
            (message.text or "").strip()
        )

    except ValueError:

        await message.reply_text(
            "❌ Faqat raqam yuboring."
        )
        return True

    if (
        amount <= 0
        or amount > 1_000_000
    ):

        await message.reply_text(
            "❌ Miqdor 1 dan "
            "1 000 000 gacha bo'lishi kerak."
        )
        return True

    target_user_id = safe_int(
        state.get("target_user_id")
    )

    mode = state.get(
        "mode"
    )

    signed_amount = (
        amount
        if mode == "add"
        else -amount
    )

    try:

        new_balance = (
            change_internal_balance(
                target_user_id,
                signed_amount,
                (
                    "SUPER_ADD_STARS"
                    if mode == "add"
                    else "SUPER_REMOVE_STARS"
                ),
                description=(
                    "Super Ega tomonidan "
                    "balans o'zgartirildi"
                ),
                reference=(
                    f"super_balance:"
                    f"{user.id}:"
                    f"{utc_timestamp()}"
                ),
                created_by=user.id
            )
        )

        audit(
            "SUPER_BALANCE_CHANGED",
            actor_id=user.id,
            target_user_id=target_user_id,
            details=(
                f"amount={signed_amount}; "
                f"balance={new_balance}"
            )
        )

    except Exception as exc:

        await message.reply_text(
            f"❌ {error_text(exc)}"
        )

        return True

    USER_STATES.pop(
        user.id,
        None
    )

    await message.reply_text(
        (
            "✅ BALANS YANGILANDI\n\n"
            f"👤 ID: {target_user_id}\n"
            f"🔄 O'zgarish: "
            f"{signed_amount:+} ⭐\n"
            f"💰 Yangi balans: "
            f"{new_balance} ⭐"
        ),
        reply_markup=(
            super_user_keyboard(
                target_user_id
            )
        )
    )

    return True


# =========================================================
# BLOCK / UNBLOCK USER
# =========================================================

async def toggle_super_user_block(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    target_user_id: int
):

    if not await require_super_owner(
        update
    ):
        return

    query = update.callback_query
    actor = update.effective_user

    row = get_user_record(
        target_user_id
    )

    if not row:

        await query.answer(
            "❌ User topilmadi.",
            show_alert=True
        )
        return

    current = bool(
        safe_int(
            row["is_blocked"]
        )
    )

    new_value = (
        0 if current else 1
    )

    db_execute(
        """
        UPDATE users
        SET
            is_blocked = ?,
            updated_at = ?
        WHERE user_id = ?
        """,
        (
            new_value,
            iso_now(),
            target_user_id
        )
    )

    audit(
        (
            "USER_UNBLOCKED"
            if current
            else "USER_BLOCKED"
        ),
        actor_id=actor.id,
        target_user_id=target_user_id
    )

    await query.answer(
        (
            "✅ Blok olib tashlandi."
            if current
            else "🚫 Foydalanuvchi bloklandi."
        ),
        show_alert=True
    )

    await show_super_user_cabinet(
        update,
        context,
        target_user_id
    )


# =========================================================
# USER TRANSACTIONS FOR SUPER OWNER
# =========================================================

async def show_super_user_transactions(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    target_user_id: int
):

    if not await require_super_owner(
        update
    ):
        return

    query = update.callback_query

    rows = db_execute(
        """
        SELECT *
        FROM transactions
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT 20
        """,
        (target_user_id,),
        fetchall=True
    )

    lines = [
        "📜 USER TRANZAKSIYALARI",
        f"👤 ID: {target_user_id}",
        ""
    ]

    if not rows:

        lines.append(
            "Tranzaksiyalar yo'q."
        )

    else:

        for row in rows:

            lines.append(
                (
                    f"#{row['id']} "
                    f"{row['transaction_type']}\n"
                    f"⭐ {row['amount'] or 0} | "
                    f"{row['status']}\n"
                    f"🕒 {row['created_at']}"
                )
            )

    await query.answer()

    await query.edit_message_text(
        "\n\n".join(lines),
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "⬅️ User kabineti",
                        callback_data=(
                            f"super:user:"
                            f"{target_user_id}"
                        )
                    )
                ]
            ]
        )
    )


# =========================================================
# AUDIT LOG
# =========================================================

async def show_super_audit(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not await require_super_owner(
        update
    ):
        return

    query = update.callback_query

    rows = db_execute(
        """
        SELECT *
        FROM audit_log
        ORDER BY id DESC
        LIMIT 30
        """,
        fetchall=True
    )

    lines = [
        "📋 AUDIT LOG",
        ""
    ]

    if not rows:

        lines.append(
            "Audit yozuvlari yo'q."
        )

    else:

        for row in rows:

            details = (
                row["details"]
                or "-"
            )

            if len(details) > 100:
                details = (
                    details[:100]
                    + "..."
                )

            lines.append(
                (
                    f"#{row['id']} "
                    f"{row['action']}\n"
                    f"👤 Actor: "
                    f"{row['actor_id'] or '-'}\n"
                    f"🎯 User: "
                    f"{row['target_user_id'] or '-'}\n"
                    f"🏢 Chat: "
                    f"{row['target_chat_id'] or '-'}\n"
                    f"📝 {details}\n"
                    f"🕒 {row['created_at']}"
                )
            )

    await query.answer()

    await query.edit_message_text(
        "\n\n".join(lines),
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🔄 Yangilash",
                        callback_data="super:audit"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "⬅️ Super Ega",
                        callback_data="super:home"
                    )
                ]
            ]
        )
    )


# =========================================================
# SUPER SETTINGS
# =========================================================

def super_settings_keyboard():

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "💎 V7 narxi",
                    callback_data="super:set_price"
                ),
                InlineKeyboardButton(
                    "🎁 Demo muddati",
                    callback_data="super:set_demo"
                )
            ],
            [
                InlineKeyboardButton(
                    "📅 V7 muddati",
                    callback_data="super:set_days"
                )
            ],
            [
                InlineKeyboardButton(
                    "📢 Promo kanallar",
                    callback_data="super:channels"
                )
            ],
            [
                InlineKeyboardButton(
                    "🎁 Mukofot sozlamalari",
                    callback_data="super:reward_settings"
                )
            ],
            [
                InlineKeyboardButton(
                    "⬅️ Super Ega",
                    callback_data="super:home"
                )
            ]
        ]
    )


async def show_super_settings(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not await require_super_owner(
        update
    ):
        return

    query = update.callback_query

    price = safe_int(
        get_setting(
            "v7_price",
            DEFAULT_V7_PRICE
        ),
        DEFAULT_V7_PRICE
    )

    demo_days = safe_int(
        get_setting(
            "demo_days",
            DEFAULT_DEMO_DAYS
        ),
        DEFAULT_DEMO_DAYS
    )

    v7_days = safe_int(
        get_setting(
            "v7_days",
            DEFAULT_V7_DAYS
        ),
        DEFAULT_V7_DAYS
    )

    text = (
        "⚙️ SUPER SOZLAMALAR\n\n"
        f"💎 V7 narxi: {price} ⭐\n"
        f"🎁 Demo: {demo_days} kun\n"
        f"📅 V7 muddati: {v7_days} kun"
    )

    await query.answer()

    await query.edit_message_text(
        text,
        reply_markup=(
            super_settings_keyboard()
        )
    )


# =========================================================
# GENERIC SUPER SETTING INPUT
# =========================================================

async def start_super_setting_edit(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    setting_name: str
):

    if not await require_super_owner(
        update
    ):
        return

    user = update.effective_user
    query = update.callback_query

    allowed = {
        "v7_price": (
            "💎 Yangi V7 narxini "
            "Stars bilan yuboring."
        ),
        "demo_days": (
            "🎁 Demo necha kun "
            "bo'lishini yuboring."
        ),
        "v7_days": (
            "📅 V7 obuna necha kun "
            "bo'lishini yuboring."
        ),
    }

    if setting_name not in allowed:
        return

    USER_STATES[user.id] = {
        "state": "WAIT_SUPER_SETTING_VALUE",
        "setting_name": setting_name,
    }

    await query.answer()

    await query.edit_message_text(
        allowed[setting_name],
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "❌ Bekor qilish",
                        callback_data="super:settings"
                    )
                ]
            ]
        )
    )


async def handle_super_setting_value(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user
    message = update.effective_message

    if not user or not message:
        return False

    state = USER_STATES.get(
        user.id
    )

    if not state:
        return False

    if (
        state.get("state")
        != "WAIT_SUPER_SETTING_VALUE"
    ):
        return False

    if not is_super_owner_id(
        user.id
    ):
        return True

    try:

        value = int(
            (message.text or "").strip()
        )

    except ValueError:

        await message.reply_text(
            "❌ Faqat butun raqam yuboring."
        )

        return True

    setting_name = state.get(
        "setting_name"
    )

    limits = {
        "v7_price": (
            1,
            1_000_000
        ),
        "demo_days": (
            1,
            365
        ),
        "v7_days": (
            1,
            3650
        ),
    }

    if setting_name not in limits:
        return True

    minimum, maximum = limits[
        setting_name
    ]

    if not (
        minimum
        <= value
        <= maximum
    ):

        await message.reply_text(
            (
                "❌ Qiymat "
                f"{minimum}–{maximum} "
                "oralig'ida bo'lishi kerak."
            )
        )

        return True

    set_setting(
        setting_name,
        str(value),
        user.id
    )

    audit(
        "SUPER_SETTING_CHANGED",
        actor_id=user.id,
        details=(
            f"{setting_name}={value}"
        )
    )

    USER_STATES.pop(
        user.id,
        None
    )

    await message.reply_text(
        (
            "✅ SOZLAMA SAQLANDI\n\n"
            f"{setting_name} = {value}"
        ),
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "⚙️ Super Sozlamalar",
                        callback_data="super:settings"
                    )
                ]
            ]
        )
    )

    return True


# =========================================================
# SUPER CALLBACK ROUTER
# =========================================================

async def super_main_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    if not query:
        return

    data = query.data or ""

    if not data.startswith(
        "super:"
    ):
        return

    user = update.effective_user

    if (
        not user
        or not is_super_owner_id(
            user.id
        )
    ):

        await query.answer(
            "⛔ Super Ega huquqi yo'q.",
            show_alert=True
        )

        return

    if data == "super:home":

        await show_super_home(
            update,
            context
        )
        return

    if data == "super:users":

        await show_super_users(
            update,
            context
        )
        return

    if data == "super:groups":

        await show_super_groups(
            update,
            context
        )
        return

    if data == "super:stats":

        await show_super_statistics(
            update,
            context
        )
        return

    if data == "super:transactions":

        await show_super_transactions(
            update,
            context
        )
        return

    if data == "super:find_user":

        await ask_super_user_id(
            update,
            context
        )
        return

    if data == "super:audit":

        await show_super_audit(
            update,
            context
        )
        return

    if data == "super:settings":

        await show_super_settings(
            update,
            context
        )
        return

    if data == "super:set_price":

        await start_super_setting_edit(
            update,
            context,
            "v7_price"
        )
        return

    if data == "super:set_demo":

        await start_super_setting_edit(
            update,
            context,
            "demo_days"
        )
        return

    if data == "super:set_days":

        await start_super_setting_edit(
            update,
            context,
            "v7_days"
        )
        return

    if data.startswith(
        "super:user:"
    ):

        try:
            target_user_id = int(
                data.rsplit(
                    ":",
                    1
                )[1]
            )
        except ValueError:
            return

        await show_super_user_cabinet(
            update,
            context,
            target_user_id
        )
        return

    if data.startswith(
        "super:user_addstars:"
    ):

        try:
            target_user_id = int(
                data.rsplit(
                    ":",
                    1
                )[1]
            )
        except ValueError:
            return

        await start_super_balance_edit(
            update,
            context,
            target_user_id,
            "add"
        )
        return

    if data.startswith(
        "super:user_removestars:"
    ):

        try:
            target_user_id = int(
                data.rsplit(
                    ":",
                    1
                )[1]
            )
        except ValueError:
            return

        await start_super_balance_edit(
            update,
            context,
            target_user_id,
            "remove"
        )
        return

    if data.startswith(
        "super:user_block:"
    ):

        try:
            target_user_id = int(
                data.rsplit(
                    ":",
                    1
                )[1]
            )
        except ValueError:
            return

        await toggle_super_user_block(
            update,
            context,
            target_user_id
        )
        return

    if data.startswith(
        "super:user_transactions:"
    ):

        try:
            target_user_id = int(
                data.rsplit(
                    ":",
                    1
                )[1]
            )
        except ValueError:
            return

        await show_super_user_transactions(
            update,
            context,
            target_user_id
        )
        return

    if data.startswith(
        "super:user_reward:"
    ):

        try:
            target_user_id = int(
                data.rsplit(
                    ":",
                    1
                )[1]
            )
        except ValueError:
            return

        await query.answer()

        await query.edit_message_text(
            (
                "🎁 MUKOFOT TURINI TANLANG\n\n"
                f"👤 ID: {target_user_id}"
            ),
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "💎 Telegram Premium",
                            callback_data=(
                                f"premium:select_user:"
                                f"{target_user_id}"
                            )
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "🎁 Telegram Gift",
                            callback_data=(
                                f"gift:select_user:"
                                f"{target_user_id}"
                            )
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "⭐ Veritas Stars",
                            callback_data=(
                                f"super:user_addstars:"
                                f"{target_user_id}"
                            )
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "⬅️ User kabineti",
                            callback_data=(
                                f"super:user:"
                                f"{target_user_id}"
                            )
                        )
                    ]
                ]
            )
        )

        return


# =========================================================
# SUPER OWNER STATE ROUTER
# =========================================================

async def super_state_router(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    if not user:
        return False

    state = USER_STATES.get(
        user.id
    )

    if not state:
        return False

    state_name = state.get(
        "state"
    )

    if (
        state_name
        == "WAIT_SUPER_USER_ID"
    ):

        return await handle_super_user_id(
            update,
            context
        )

    if (
        state_name
        == "WAIT_SUPER_BALANCE_AMOUNT"
    ):

        return await handle_super_balance_amount(
            update,
            context
        )

    if (
        state_name
        == "WAIT_SUPER_SETTING_VALUE"
    ):

        return await handle_super_setting_value(
            update,
            context
        )

    return False


# =========================================================
# END PART 11
# =========================================================
# =========================================================
# VERITAS BOT V7
# PART 12 — LIBRARY, CHANNELS, MODERATORS & GROUP TEXTS
# =========================================================


# =========================================================
# PART 12 DATABASE COMPATIBILITY
# =========================================================

def init_part12_database():
    conn = db_connect()

    try:
        # Library uchun kerakli ustunlar.
        add_column_if_missing(
            conn,
            "library_books",
            "description",
            "TEXT"
        )

        add_column_if_missing(
            conn,
            "library_books",
            "file_id",
            "TEXT"
        )

        add_column_if_missing(
            conn,
            "library_books",
            "file_type",
            "TEXT"
        )

        add_column_if_missing(
            conn,
            "library_books",
            "active",
            "INTEGER NOT NULL DEFAULT 1"
        )

        # Moderatorlar uchun.
        add_column_if_missing(
            conn,
            "group_moderators",
            "can_ban",
            "INTEGER NOT NULL DEFAULT 1"
        )

        add_column_if_missing(
            conn,
            "group_moderators",
            "can_mute",
            "INTEGER NOT NULL DEFAULT 1"
        )

        add_column_if_missing(
            conn,
            "group_moderators",
            "can_warn",
            "INTEGER NOT NULL DEFAULT 1"
        )

        add_column_if_missing(
            conn,
            "group_moderators",
            "can_delete",
            "INTEGER NOT NULL DEFAULT 1"
        )

        add_column_if_missing(
            conn,
            "group_moderators",
            "can_manage_settings",
            "INTEGER NOT NULL DEFAULT 0"
        )

        conn.commit()

    finally:
        conn.close()


init_part12_database()


# =========================================================
# LIBRARY HELPERS
# =========================================================

def get_library_books(
    limit: int = 50
):
    return db_execute(
        """
        SELECT *
        FROM library_books
        WHERE active = 1
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
        fetchall=True
    )


def get_library_book(
    book_id: int
):
    return db_execute(
        """
        SELECT *
        FROM library_books
        WHERE id = ?
        """,
        (book_id,),
        fetchone=True
    )


def library_main_keyboard(
    super_mode: bool = False
):
    rows = [
        [
            InlineKeyboardButton(
                "📚 Kitoblar",
                callback_data="library:list"
            )
        ]
    ]

    if super_mode:
        rows.extend(
            [
                [
                    InlineKeyboardButton(
                        "➕ Kitob qo'shish",
                        callback_data=(
                            "super:library_add"
                        )
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🗑 Kitob o'chirish",
                        callback_data=(
                            "super:library_delete"
                        )
                    )
                ],
                [
                    InlineKeyboardButton(
                        "⬅️ Super Ega",
                        callback_data="super:home"
                    )
                ]
            ]
        )

    else:
        rows.append(
            [
                InlineKeyboardButton(
                    "⬅️ Kabinet",
                    callback_data="user:home"
                )
            ]
        )

    return InlineKeyboardMarkup(
        rows
    )


# =========================================================
# SUPER LIBRARY HOME
# =========================================================

async def show_super_library(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not await require_super_owner(
        update
    ):
        return

    query = update.callback_query

    count = db_execute(
        """
        SELECT COUNT(*) AS total
        FROM library_books
        WHERE active = 1
        """,
        fetchone=True
    )

    total = (
        safe_int(count["total"])
        if count else 0
    )

    await query.answer()

    await query.edit_message_text(
        (
            "📚 VERITAS KUTUBXONASI\n\n"
            f"📖 Faol kitoblar: {total}\n\n"
            "Bu yerdan kutubxonaga "
            "kitob qo'shish yoki o'chirish "
            "mumkin."
        ),
        reply_markup=(
            library_main_keyboard(
                super_mode=True
            )
        )
    )


# =========================================================
# LIBRARY LIST
# =========================================================

async def show_library_list(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query

    if not query:
        return

    books = get_library_books(
        50
    )

    rows = []

    if books:
        for book in books:
            title = (
                book["title"]
                or "Nomsiz kitob"
            )

            rows.append(
                [
                    InlineKeyboardButton(
                        f"📖 {title[:45]}",
                        callback_data=(
                            f"library:book:"
                            f"{book['id']}"
                        )
                    )
                ]
            )

    else:
        rows.append(
            [
                InlineKeyboardButton(
                    "📭 Kitoblar yo'q",
                    callback_data="library:none"
                )
            ]
        )

    user = update.effective_user

    if (
        user
        and is_super_owner_id(user.id)
    ):
        rows.append(
            [
                InlineKeyboardButton(
                    "⬅️ Kutubxona",
                    callback_data="super:library"
                )
            ]
        )
    else:
        rows.append(
            [
                InlineKeyboardButton(
                    "⬅️ Kabinet",
                    callback_data="user:home"
                )
            ]
        )

    await query.answer()

    await query.edit_message_text(
        "📚 KITOBLAR\n\n"
        "Kitobni tanlang:",
        reply_markup=InlineKeyboardMarkup(
            rows
        )
    )


# =========================================================
# SHOW ONE BOOK
# =========================================================

async def show_library_book(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    book_id: int
):
    query = update.callback_query

    if not query:
        return

    book = get_library_book(
        book_id
    )

    if (
        not book
        or not safe_int(
            book["active"],
            1
        )
    ):
        await query.answer(
            "❌ Kitob topilmadi.",
            show_alert=True
        )
        return

    title = (
        book["title"]
        or "Nomsiz kitob"
    )

    author = (
        book["author"]
        or "Noma'lum"
    )

    description = (
        book["description"]
        or "Tavsif mavjud emas."
    )

    text = (
        f"📖 {title}\n\n"
        f"✍️ Muallif: {author}\n\n"
        f"📝 {description}"
    )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "⬅️ Kitoblar",
                    callback_data="library:list"
                )
            ]
        ]
    )

    await query.answer()

    try:
        await query.edit_message_text(
            text,
            reply_markup=keyboard
        )

    except BadRequest:
        pass

    file_id = book["file_id"]

    if file_id:
        try:
            file_type = (
                book["file_type"]
                or "document"
            )

            if file_type == "photo":
                await context.bot.send_photo(
                    chat_id=query.message.chat.id,
                    photo=file_id,
                    caption=f"📖 {title}"
                )

            else:
                await context.bot.send_document(
                    chat_id=query.message.chat.id,
                    document=file_id,
                    caption=f"📖 {title}"
                )

        except TelegramError:
            pass


# =========================================================
# ADD LIBRARY BOOK
# =========================================================

async def start_library_add(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not await require_super_owner(
        update
    ):
        return

    query = update.callback_query
    user = update.effective_user

    USER_STATES[user.id] = {
        "state": "WAIT_LIBRARY_TITLE"
    }

    await query.answer()

    await query.edit_message_text(
        (
            "➕ KITOB QO'SHISH\n\n"
            "1/4 — Kitob nomini yuboring."
        ),
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "❌ Bekor qilish",
                        callback_data="super:library"
                    )
                ]
            ]
        )
    )


async def handle_library_state(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    user = update.effective_user
    message = update.effective_message

    if not user or not message:
        return False

    state = USER_STATES.get(
        user.id
    )

    if not state:
        return False

    state_name = state.get(
        "state"
    )

    if state_name not in {
        "WAIT_LIBRARY_TITLE",
        "WAIT_LIBRARY_AUTHOR",
        "WAIT_LIBRARY_DESCRIPTION",
        "WAIT_LIBRARY_FILE",
        "WAIT_LIBRARY_DELETE_ID",
    }:
        return False

    if not is_super_owner_id(
        user.id
    ):
        USER_STATES.pop(
            user.id,
            None
        )
        return True

    # -----------------------------------------------------
    # TITLE
    # -----------------------------------------------------

    if state_name == "WAIT_LIBRARY_TITLE":
        title = clean_text(
            message.text
        )

        if not title:
            await message.reply_text(
                "❌ Kitob nomini matn "
                "ko'rinishida yuboring."
            )
            return True

        state["title"] = title[:200]
        state["state"] = (
            "WAIT_LIBRARY_AUTHOR"
        )

        await message.reply_text(
            (
                "2/4 — Muallif nomini yuboring.\n\n"
                "Muallif noma'lum bo'lsa:\n"
                "-"
            )
        )

        return True

    # -----------------------------------------------------
    # AUTHOR
    # -----------------------------------------------------

    if state_name == "WAIT_LIBRARY_AUTHOR":
        author = clean_text(
            message.text
        )

        if not author:
            return True

        if author == "-":
            author = "Noma'lum"

        state["author"] = author[:200]
        state["state"] = (
            "WAIT_LIBRARY_DESCRIPTION"
        )

        await message.reply_text(
            (
                "3/4 — Kitob haqida qisqa "
                "tavsif yuboring.\n\n"
                "Tavsif kerak bo'lmasa:\n"
                "-"
            )
        )

        return True

    # -----------------------------------------------------
    # DESCRIPTION
    # -----------------------------------------------------

    if (
        state_name
        == "WAIT_LIBRARY_DESCRIPTION"
    ):
        description = clean_text(
            message.text
        )

        if not description:
            return True

        if description == "-":
            description = ""

        state["description"] = (
            description[:3000]
        )

        state["state"] = (
            "WAIT_LIBRARY_FILE"
        )

        await message.reply_text(
            (
                "4/4 — Kitob faylini yuboring.\n\n"
                "PDF, EPUB yoki boshqa document "
                "yuborishingiz mumkin.\n\n"
                "Faylsiz saqlash uchun:\n"
                "/skip"
            )
        )

        return True

    # -----------------------------------------------------
    # FILE
    # -----------------------------------------------------

    if state_name == "WAIT_LIBRARY_FILE":
        file_id = None
        file_type = None

        if (
            message.text
            and message.text.strip()
            == "/skip"
        ):
            pass

        elif message.document:
            file_id = (
                message.document.file_id
            )
            file_type = "document"

        elif message.photo:
            file_id = (
                message.photo[-1].file_id
            )
            file_type = "photo"

        else:
            await message.reply_text(
                (
                    "❌ Fayl yuboring yoki "
                    "/skip yozing."
                )
            )
            return True

        conn = db_connect()

        try:
            cursor = conn.execute(
                """
                INSERT INTO library_books (
                    title,
                    author,
                    description,
                    file_id,
                    file_type,
                    active,
                    created_by,
                    created_at
                )
                VALUES (
                    ?, ?, ?, ?, ?,
                    1, ?, ?
                )
                """,
                (
                    state.get("title"),
                    state.get("author"),
                    state.get(
                        "description"
                    ),
                    file_id,
                    file_type,
                    user.id,
                    iso_now()
                )
            )

            book_id = (
                cursor.lastrowid
            )

            conn.commit()

        finally:
            conn.close()

        audit(
            "LIBRARY_BOOK_ADDED",
            actor_id=user.id,
            details=(
                f"book_id={book_id}; "
                f"title={state.get('title')}"
            )
        )

        USER_STATES.pop(
            user.id,
            None
        )

        await message.reply_text(
            (
                "✅ KITOB SAQLANDI\n\n"
                f"🆔 {book_id}\n"
                f"📖 {state.get('title')}"
            ),
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "📚 Kutubxona",
                            callback_data=(
                                "super:library"
                            )
                        )
                    ]
                ]
            )
        )

        return True

    # -----------------------------------------------------
    # DELETE BOOK
    # -----------------------------------------------------

    if (
        state_name
        == "WAIT_LIBRARY_DELETE_ID"
    ):
        try:
            book_id = int(
                (
                    message.text
                    or ""
                ).strip()
            )

        except ValueError:
            await message.reply_text(
                "❌ Kitob ID raqamini yuboring."
            )
            return True

        book = get_library_book(
            book_id
        )

        if not book:
            await message.reply_text(
                "❌ Bunday kitob topilmadi."
            )
            return True

        db_execute(
            """
            UPDATE library_books
            SET active = 0
            WHERE id = ?
            """,
            (book_id,)
        )

        audit(
            "LIBRARY_BOOK_DELETED",
            actor_id=user.id,
            details=f"book_id={book_id}"
        )

        USER_STATES.pop(
            user.id,
            None
        )

        await message.reply_text(
            (
                "🗑 Kitob kutubxonadan "
                "o'chirildi."
            ),
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "📚 Kutubxona",
                            callback_data=(
                                "super:library"
                            )
                        )
                    ]
                ]
            )
        )

        return True

    return False


async def start_library_delete(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not await require_super_owner(
        update
    ):
        return

    query = update.callback_query
    user = update.effective_user

    books = get_library_books(
        30
    )

    lines = [
        "🗑 KITOB O'CHIRISH",
        "",
        "Kitob ID raqamini yuboring.",
        ""
    ]

    if books:
        for book in books:
            lines.append(
                (
                    f"#{book['id']} — "
                    f"{book['title']}"
                )
            )
    else:
        lines.append(
            "Kutubxonada kitob yo'q."
        )

    USER_STATES[user.id] = {
        "state": (
            "WAIT_LIBRARY_DELETE_ID"
        )
    }

    await query.answer()

    await query.edit_message_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "❌ Bekor qilish",
                        callback_data="super:library"
                    )
                ]
            ]
        )
    )


# =========================================================
# PROMO CHANNELS
# =========================================================

def get_promo_channels():
    return db_execute(
        """
        SELECT *
        FROM promo_channels
        ORDER BY id DESC
        """,
        fetchall=True
    )


async def show_promo_channels(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not await require_super_owner(
        update
    ):
        return

    query = update.callback_query

    rows = get_promo_channels()

    lines = [
        "📢 PROMO KANALLAR",
        ""
    ]

    if not rows:
        lines.append(
            "Promo kanallar yo'q."
        )
    else:
        for row in rows:
            lines.append(
                (
                    f"#{row['id']} "
                    f"{row['title'] or 'Kanal'}\n"
                    f"{row['channel_id']}"
                )
            )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "➕ Kanal qo'shish",
                    callback_data=(
                        "super:channel_add"
                    )
                )
            ],
            [
                InlineKeyboardButton(
                    "➖ Kanal o'chirish",
                    callback_data=(
                        "super:channel_delete"
                    )
                )
            ],
            [
                InlineKeyboardButton(
                    "⬅️ Super Sozlamalar",
                    callback_data=(
                        "super:settings"
                    )
                )
            ]
        ]
    )

    await query.answer()

    await query.edit_message_text(
        "\n\n".join(lines),
        reply_markup=keyboard
    )


async def start_channel_add(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not await require_super_owner(
        update
    ):
        return

    query = update.callback_query
    user = update.effective_user

    USER_STATES[user.id] = {
        "state": "WAIT_PROMO_CHANNEL_ID"
    }

    await query.answer()

    await query.edit_message_text(
        (
            "➕ PROMO KANAL\n\n"
            "Kanal ID yoki @username "
            "yuboring.\n\n"
            "Masalan:\n"
            "-1001234567890\n"
            "yoki\n"
            "@kanal"
        ),
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "❌ Bekor qilish",
                        callback_data=(
                            "super:channels"
                        )
                    )
                ]
            ]
        )
    )


async def handle_promo_channel_state(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    user = update.effective_user
    message = update.effective_message

    if not user or not message:
        return False

    state = USER_STATES.get(
        user.id
    )

    if not state:
        return False

    state_name = state.get(
        "state"
    )

    if state_name not in {
        "WAIT_PROMO_CHANNEL_ID",
        "WAIT_PROMO_CHANNEL_DELETE",
    }:
        return False

    if not is_super_owner_id(
        user.id
    ):
        USER_STATES.pop(
            user.id,
            None
        )
        return True

    # ADD
    if (
        state_name
        == "WAIT_PROMO_CHANNEL_ID"
    ):
        raw = clean_text(
            message.text
        )

        if not raw:
            return True

        chat_ref: Any = raw

        if raw.lstrip("-").isdigit():
            chat_ref = int(raw)

        try:
            chat = await context.bot.get_chat(
                chat_ref
            )

        except TelegramError as exc:
            await message.reply_text(
                (
                    "❌ Kanal topilmadi.\n"
                    f"{error_text(exc)}"
                )
            )
            return True

        channel_id = chat.id
        title = (
            chat.title
            or chat.username
            or "Kanal"
        )

        username = (
            chat.username
            if chat.username
            else None
        )

        conn = db_connect()

        try:
            existing = conn.execute(
                """
                SELECT id
                FROM promo_channels
                WHERE channel_id = ?
                LIMIT 1
                """,
                (channel_id,)
            ).fetchone()

            if existing:
                conn.execute(
                    """
                    UPDATE promo_channels
                    SET
                        title = ?,
                        username = ?
                    WHERE id = ?
                    """,
                    (
                        title,
                        username,
                        existing["id"]
                    )
                )

            else:
                conn.execute(
                    """
                    INSERT INTO promo_channels (
                        channel_id,
                        title,
                        username,
                        created_by,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        channel_id,
                        title,
                        username,
                        user.id,
                        iso_now()
                    )
                )

            conn.commit()

        finally:
            conn.close()

        audit(
            "PROMO_CHANNEL_ADDED",
            actor_id=user.id,
            target_chat_id=channel_id
        )

        USER_STATES.pop(
            user.id,
            None
        )

        await message.reply_text(
            (
                "✅ PROMO KANAL SAQLANDI\n\n"
                f"📢 {title}\n"
                f"🆔 {channel_id}"
            ),
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "📢 Promo kanallar",
                            callback_data=(
                                "super:channels"
                            )
                        )
                    ]
                ]
            )
        )

        return True

    # DELETE
    if (
        state_name
        == "WAIT_PROMO_CHANNEL_DELETE"
    ):
        try:
            record_id = int(
                (
                    message.text
                    or ""
                ).strip()
            )

        except ValueError:
            await message.reply_text(
                "❌ Ro'yxatdagi #ID ni yuboring."
            )
            return True

        db_execute(
            """
            DELETE FROM promo_channels
            WHERE id = ?
            """,
            (record_id,)
        )

        audit(
            "PROMO_CHANNEL_DELETED",
            actor_id=user.id,
            details=(
                f"record_id={record_id}"
            )
        )

        USER_STATES.pop(
            user.id,
            None
        )

        await message.reply_text(
            "✅ Promo kanal o'chirildi.",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "📢 Promo kanallar",
                            callback_data=(
                                "super:channels"
                            )
                        )
                    ]
                ]
            )
        )

        return True

    return False


async def start_channel_delete(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not await require_super_owner(
        update
    ):
        return

    query = update.callback_query
    user = update.effective_user

    rows = get_promo_channels()

    lines = [
        "➖ PROMO KANAL O'CHIRISH",
        "",
        "O'chiriladigan #ID ni yuboring.",
        ""
    ]

    for row in rows:
        lines.append(
            (
                f"#{row['id']} — "
                f"{row['title'] or row['channel_id']}"
            )
        )

    USER_STATES[user.id] = {
        "state": (
            "WAIT_PROMO_CHANNEL_DELETE"
        )
    }

    await query.answer()

    await query.edit_message_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "❌ Bekor qilish",
                        callback_data=(
                            "super:channels"
                        )
                    )
                ]
            ]
        )
    )


# =========================================================
# GROUP MODERATOR MANAGEMENT
# =========================================================

async def start_group_mod_edit(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    action: str
):
    query = update.callback_query
    user = update.effective_user

    if not query or not user:
        return

    if not await can_manage_group(
        context,
        chat_id,
        user.id
    ):
        await query.answer(
            "⛔ Ruxsat yo'q.",
            show_alert=True
        )
        return

    USER_STATES[user.id] = {
        "state": "WAIT_GROUP_MOD_ID",
        "chat_id": chat_id,
        "action": action,
    }

    await query.answer()

    await query.edit_message_text(
        (
            (
                "➕ MODERATOR QO'SHISH"
                if action == "add"
                else "➖ MODERATOR O'CHIRISH"
            )
            + "\n\n"
            "Foydalanuvchining Telegram "
            "ID raqamini yuboring."
        ),
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "❌ Bekor qilish",
                        callback_data=(
                            f"group:mods:{chat_id}"
                        )
                    )
                ]
            ]
        )
    )


async def handle_group_mod_id(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    user = update.effective_user
    message = update.effective_message

    if not user or not message:
        return False

    state = USER_STATES.get(
        user.id
    )

    if not state:
        return False

    if (
        state.get("state")
        != "WAIT_GROUP_MOD_ID"
    ):
        return False

    chat_id = safe_int(
        state.get("chat_id")
    )

    action = state.get(
        "action"
    )

    if not await can_manage_group(
        context,
        chat_id,
        user.id
    ):
        USER_STATES.pop(
            user.id,
            None
        )
        return True

    try:
        target_id = int(
            (
                message.text
                or ""
            ).strip()
        )

    except ValueError:
        await message.reply_text(
            "❌ Telegram ID raqam "
            "bo'lishi kerak."
        )
        return True

    if target_id <= 0:
        await message.reply_text(
            "❌ ID noto'g'ri."
        )
        return True

    if action == "add":
        try:
            target_member = (
                await context.bot.get_chat_member(
                    chat_id,
                    target_id
                )
            )

            if target_member.status in (
                "left",
                "kicked",
            ):
                await message.reply_text(
                    (
                        "❌ Bu foydalanuvchi "
                        "guruh a'zosi emas."
                    )
                )
                return True

            ensure_user(
                target_member.user
            )

        except TelegramError:
            await message.reply_text(
                (
                    "❌ Foydalanuvchini "
                    "guruhda topib bo'lmadi."
                )
            )
            return True

        conn = db_connect()

        try:
            conn.execute(
                """
                INSERT OR REPLACE
                INTO group_moderators (
                    chat_id,
                    user_id,
                    can_ban,
                    can_mute,
                    can_warn,
                    can_delete,
                    can_manage_settings,
                    added_by,
                    created_at
                )
                VALUES (
                    ?, ?,
                    1, 1, 1, 1, 0,
                    ?, ?
                )
                """,
                (
                    chat_id,
                    target_id,
                    user.id,
                    iso_now()
                )
            )

            conn.commit()

        finally:
            conn.close()

        audit(
            "GROUP_MODERATOR_ADDED",
            actor_id=user.id,
            target_user_id=target_id,
            target_chat_id=chat_id
        )

        result = (
            "✅ Veritas moderatori qo'shildi."
        )

    else:
        db_execute(
            """
            DELETE FROM group_moderators
            WHERE chat_id = ?
              AND user_id = ?
            """,
            (
                chat_id,
                target_id
            )
        )

        audit(
            "GROUP_MODERATOR_REMOVED",
            actor_id=user.id,
            target_user_id=target_id,
            target_chat_id=chat_id
        )

        result = (
            "✅ Veritas moderatori "
            "o'chirildi."
        )

    USER_STATES.pop(
        user.id,
        None
    )

    await message.reply_text(
        result,
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "👮 Moderatorlar",
                        callback_data=(
                            f"group:mods:{chat_id}"
                        )
                    )
                ]
            ]
        )
    )

    return True


# =========================================================
# WELCOME / GOODBYE TEXT PANEL
# =========================================================

async def show_group_text_settings(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int
):
    query = update.callback_query
    user = update.effective_user

    if not query or not user:
        return

    if not await can_manage_group(
        context,
        chat_id,
        user.id
    ):
        await query.answer(
            "⛔ Ruxsat yo'q.",
            show_alert=True
        )
        return

    group = get_group_record(
        chat_id
    )

    if not group:
        return

    welcome = (
        group["welcome_text"]
        or "Standart matn"
    )

    goodbye = (
        group["goodbye_text"]
        or "Standart matn"
    )

    if len(welcome) > 300:
        welcome = (
            welcome[:300]
            + "..."
        )

    if len(goodbye) > 300:
        goodbye = (
            goodbye[:300]
            + "..."
        )

    text = (
        "✏️ GURUH MATNLARI\n\n"
        "👋 Welcome:\n"
        f"{welcome}\n\n"
        "🚪 Goodbye:\n"
        f"{goodbye}\n\n"
        "Ishlatish mumkin:\n"
        "{name}\n"
        "{first_name}\n"
        "{username}\n"
        "{user_id}\n"
        "{group}\n"
        "{chat_id}"
    )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "👋 Welcome matni",
                    callback_data=(
                        f"group:text_welcome:"
                        f"{chat_id}"
                    )
                )
            ],
            [
                InlineKeyboardButton(
                    "🚪 Goodbye matni",
                    callback_data=(
                        f"group:text_goodbye:"
                        f"{chat_id}"
                    )
                )
            ],
            [
                InlineKeyboardButton(
                    "⬅️ Sozlamalar",
                    callback_data=(
                        f"group:settings:{chat_id}"
                    )
                )
            ]
        ]
    )

    await query.answer()

    await query.edit_message_text(
        text,
        reply_markup=keyboard
    )


async def start_group_text_edit(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    text_type: str
):
    query = update.callback_query
    user = update.effective_user

    if not query or not user:
        return

    if not await can_manage_group(
        context,
        chat_id,
        user.id
    ):
        return

    USER_STATES[user.id] = {
        "state": "WAIT_GROUP_CUSTOM_TEXT",
        "chat_id": chat_id,
        "text_type": text_type,
    }

    title = (
        "👋 Welcome"
        if text_type == "welcome"
        else "🚪 Goodbye"
    )

    await query.answer()

    await query.edit_message_text(
        (
            f"{title} MATNI\n\n"
            "Yangi matnni yuboring.\n\n"
            "Masalan:\n"
            "👋 Xush kelibsiz, {name}!\n"
            "{group} guruhiga xush kelibsiz.\n\n"
            "Standart matnga qaytarish uchun:\n"
            "/default"
        ),
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "❌ Bekor qilish",
                        callback_data=(
                            f"group:texts:{chat_id}"
                        )
                    )
                ]
            ]
        )
    )


async def handle_group_custom_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    user = update.effective_user
    message = update.effective_message

    if not user or not message:
        return False

    state = USER_STATES.get(
        user.id
    )

    if not state:
        return False

    if (
        state.get("state")
        != "WAIT_GROUP_CUSTOM_TEXT"
    ):
        return False

    chat_id = safe_int(
        state.get("chat_id")
    )

    text_type = state.get(
        "text_type"
    )

    if not await can_manage_group(
        context,
        chat_id,
        user.id
    ):
        USER_STATES.pop(
            user.id,
            None
        )
        return True

    text = (
        message.text
        or ""
    ).strip()

    if not text:
        await message.reply_text(
            "❌ Matn yuboring."
        )
        return True

    if len(text) > 3500:
        await message.reply_text(
            "❌ Matn juda uzun."
        )
        return True

    if text == "/default":
        text = None

    if text_type == "welcome":
        column = "welcome_text"
    elif text_type == "goodbye":
        column = "goodbye_text"
    else:
        return True

    db_execute(
        f"""
        UPDATE groups
        SET
            {column} = ?,
            updated_at = ?
        WHERE chat_id = ?
        """,
        (
            text,
            iso_now(),
            chat_id
        )
    )

    audit(
        "GROUP_TEXT_CHANGED",
        actor_id=user.id,
        target_chat_id=chat_id,
        details=text_type
    )

    USER_STATES.pop(
        user.id,
        None
    )

    await message.reply_text(
        "✅ Guruh matni saqlandi.",
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "✏️ Guruh matnlari",
                        callback_data=(
                            f"group:texts:{chat_id}"
                        )
                    )
                ]
            ]
        )
    )

    return True


# =========================================================
# PART 12 CALLBACK ROUTER
# =========================================================

async def part12_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query

    if not query:
        return

    data = query.data or ""

    # -----------------------------------------------------
    # LIBRARY
    # -----------------------------------------------------

    if data == "super:library":
        await show_super_library(
            update,
            context
        )
        return

    if data == "super:library_add":
        await start_library_add(
            update,
            context
        )
        return

    if data == "super:library_delete":
        await start_library_delete(
            update,
            context
        )
        return

    if data == "library:list":
        await show_library_list(
            update,
            context
        )
        return

    if data == "library:none":
        await query.answer(
            "📭 Kutubxona bo'sh."
        )
        return

    if data.startswith(
        "library:book:"
    ):
        try:
            book_id = int(
                data.rsplit(
                    ":",
                    1
                )[1]
            )
        except ValueError:
            return

        await show_library_book(
            update,
            context,
            book_id
        )
        return

    # -----------------------------------------------------
    # PROMO CHANNELS
    # -----------------------------------------------------

    if data == "super:channels":
        await show_promo_channels(
            update,
            context
        )
        return

    if data == "super:channel_add":
        await start_channel_add(
            update,
            context
        )
        return

    if data == "super:channel_delete":
        await start_channel_delete(
            update,
            context
        )
        return

    # -----------------------------------------------------
    # MODERATORS
    # -----------------------------------------------------

    if data.startswith(
        "group:addmod:"
    ):
        try:
            chat_id = int(
                data.rsplit(
                    ":",
                    1
                )[1]
            )
        except ValueError:
            return

        await start_group_mod_edit(
            update,
            context,
            chat_id,
            "add"
        )
        return

    if data.startswith(
        "group:delmod:"
    ):
        try:
            chat_id = int(
                data.rsplit(
                    ":",
                    1
                )[1]
            )
        except ValueError:
            return

        await start_group_mod_edit(
            update,
            context,
            chat_id,
            "delete"
        )
        return

    # -----------------------------------------------------
    # GROUP TEXTS
    # -----------------------------------------------------

    if data.startswith(
        "group:texts:"
    ):
        try:
            chat_id = int(
                data.rsplit(
                    ":",
                    1
                )[1]
            )
        except ValueError:
            return

        await show_group_text_settings(
            update,
            context,
            chat_id
        )
        return

    if data.startswith(
        "group:text_welcome:"
    ):
        try:
            chat_id = int(
                data.rsplit(
                    ":",
                    1
                )[1]
            )
        except ValueError:
            return

        await start_group_text_edit(
            update,
            context,
            chat_id,
            "welcome"
        )
        return

    if data.startswith(
        "group:text_goodbye:"
    ):
        try:
            chat_id = int(
                data.rsplit(
                    ":",
                    1
                )[1]
            )
        except ValueError:
            return

        await start_group_text_edit(
            update,
            context,
            chat_id,
            "goodbye"
        )
        return


# =========================================================
# PART 12 STATE ROUTER
# =========================================================

async def part12_state_router(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    user = update.effective_user

    if not user:
        return False

    state = USER_STATES.get(
        user.id
    )

    if not state:
        return False

    state_name = state.get(
        "state"
    )

    if state_name in {
        "WAIT_LIBRARY_TITLE",
        "WAIT_LIBRARY_AUTHOR",
        "WAIT_LIBRARY_DESCRIPTION",
        "WAIT_LIBRARY_FILE",
        "WAIT_LIBRARY_DELETE_ID",
    }:
        return await handle_library_state(
            update,
            context
        )

    if state_name in {
        "WAIT_PROMO_CHANNEL_ID",
        "WAIT_PROMO_CHANNEL_DELETE",
    }:
        return await handle_promo_channel_state(
            update,
            context
        )

    if (
        state_name
        == "WAIT_GROUP_MOD_ID"
    ):
        return await handle_group_mod_id(
            update,
            context
        )

    if (
        state_name
        == "WAIT_GROUP_CUSTOM_TEXT"
    ):
        return await handle_group_custom_text(
            update,
            context
        )

    return False


# =========================================================
# END PART 12
# =========================================================
# =========================================================
# VERITAS BOT V7
# PART 13 — SUBSCRIPTION CONTROL
# DEMO / V7 / FREE / VIP / EXPIRATION
# =========================================================


# =========================================================
# SUBSCRIPTION PLAN CONSTANTS
# =========================================================

SUBSCRIPTION_PLANS = {
    "DEMO",
    "V7",
    "FREE",
    "VIP",
}

PERMANENT_PLANS = {
    "FREE",
    "VIP",
}


# =========================================================
# CURRENT SUBSCRIPTION SETTINGS
# =========================================================

def current_v7_price() -> int:
    return safe_int(
        get_setting(
            "v7_price",
            DEFAULT_V7_PRICE
        ),
        DEFAULT_V7_PRICE
    )


def current_demo_days() -> int:
    return safe_int(
        get_setting(
            "demo_days",
            DEFAULT_DEMO_DAYS
        ),
        DEFAULT_DEMO_DAYS
    )


def current_v7_days() -> int:
    return safe_int(
        get_setting(
            "v7_days",
            DEFAULT_V7_DAYS
        ),
        DEFAULT_V7_DAYS
    )


# =========================================================
# ISO DATE PARSER
# =========================================================

def parse_iso_datetime(
    value: Optional[str]
):
    if not value:
        return None

    try:
        result = datetime.fromisoformat(
            str(value)
        )

        if result.tzinfo is None:
            result = result.replace(
                tzinfo=timezone.utc
            )

        return result

    except (
        ValueError,
        TypeError,
    ):
        return None


# =========================================================
# SUBSCRIPTION STATUS
# =========================================================

def subscription_status_info(
    chat_id: int
):
    row = get_subscription(
        chat_id
    )

    if not row:
        return {
            "exists": False,
            "active": False,
            "plan": None,
            "status": "NONE",
            "expires_at": None,
            "remaining_seconds": 0,
        }

    plan = (
        row["plan"]
        or ""
    ).upper()

    status = (
        row["status"]
        or ""
    ).upper()

    expires_at = parse_iso_datetime(
        row["expires_at"]
    )

    # FREE va VIP muddatsiz.
    if (
        plan in PERMANENT_PLANS
        and status == "ACTIVE"
    ):
        return {
            "exists": True,
            "active": True,
            "plan": plan,
            "status": status,
            "expires_at": None,
            "remaining_seconds": None,
        }

    if status != "ACTIVE":
        return {
            "exists": True,
            "active": False,
            "plan": plan,
            "status": status,
            "expires_at": expires_at,
            "remaining_seconds": 0,
        }

    if not expires_at:
        return {
            "exists": True,
            "active": False,
            "plan": plan,
            "status": "INVALID",
            "expires_at": None,
            "remaining_seconds": 0,
        }

    now = utc_now()

    remaining = (
        expires_at - now
    ).total_seconds()

    return {
        "exists": True,
        "active": remaining > 0,
        "plan": plan,
        "status": (
            "ACTIVE"
            if remaining > 0
            else "EXPIRED"
        ),
        "expires_at": expires_at,
        "remaining_seconds": max(
            0,
            int(remaining)
        ),
    }


# =========================================================
# HUMAN REMAINING TIME
# =========================================================

def human_remaining_time(
    seconds: Optional[int]
):
    if seconds is None:
        return "♾ Muddatsiz"

    seconds = max(
        0,
        safe_int(seconds)
    )

    if seconds <= 0:
        return "Tugagan"

    days = seconds // 86400

    hours = (
        seconds % 86400
    ) // 3600

    minutes = (
        seconds % 3600
    ) // 60

    if days > 0:
        return (
            f"{days} kun "
            f"{hours} soat"
        )

    if hours > 0:
        return (
            f"{hours} soat "
            f"{minutes} daqiqa"
        )

    return (
        f"{minutes} daqiqa"
    )


# =========================================================
# EXPIRE SUBSCRIPTION IF NEEDED
# =========================================================

def expire_subscription_if_needed(
    chat_id: int
):
    info = subscription_status_info(
        chat_id
    )

    if not info["exists"]:
        return info

    if (
        info["plan"]
        in PERMANENT_PLANS
    ):
        return info

    if (
        info["status"] == "EXPIRED"
    ):
        db_execute(
            """
            UPDATE subscriptions
            SET
                status = 'EXPIRED',
                updated_at = ?
            WHERE chat_id = ?
              AND status = 'ACTIVE'
            """,
            (
                iso_now(),
                chat_id
            )
        )

        info["active"] = False
        info["status"] = "EXPIRED"

    return info


# =========================================================
# CHECK V7 ACCESS
# =========================================================

def group_has_v7_access(
    chat_id: int
) -> bool:
    info = expire_subscription_if_needed(
        chat_id
    )

    return bool(
        info["active"]
    )


# =========================================================
# ASYNC ACCESS CHECK
# =========================================================

async def require_group_v7(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: Optional[int] = None,
    show_message: bool = True
):
    if chat_id is None:
        chat = update.effective_chat

        if not chat:
            return False

        chat_id = chat.id

    user = update.effective_user

    # Super Ega uchun doim ruxsat.
    if (
        user
        and is_super_owner_id(user.id)
    ):
        return True

    if group_has_v7_access(
        chat_id
    ):
        return True

    if not show_message:
        return False

    text = (
        "💎 VERITAS V7 OBUNA KERAK\n\n"
        "Bu guruhning Demo/V7 muddati "
        "tugagan.\n\n"
        f"💰 Narx: {current_v7_price()} ⭐\n"
        f"📅 Muddat: {current_v7_days()} kun"
    )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "💎 V7 faollashtirish",
                    callback_data=(
                        f"user:buy_v7:"
                        f"{chat_id}"
                    )
                )
            ]
        ]
    )

    if update.callback_query:
        query = update.callback_query

        await query.answer(
            "💎 V7 obuna talab qilinadi.",
            show_alert=True
        )

        try:
            await query.edit_message_text(
                text,
                reply_markup=keyboard
            )
        except BadRequest:
            pass

    elif update.effective_message:
        await update.effective_message.reply_text(
            text,
            reply_markup=keyboard
        )

    return False


# =========================================================
# CREATE DEMO FOR NEW GROUP
# =========================================================

def ensure_group_demo(
    chat_id: int,
    granted_by: Optional[int] = None
):
    existing = get_subscription(
        chat_id
    )

    if existing:
        return existing

    days = current_demo_days()

    now = utc_now()

    expires = (
        now
        + timedelta(days=days)
    ).isoformat()

    db_execute(
        """
        INSERT INTO subscriptions (
            chat_id,
            plan,
            status,
            started_at,
            expires_at,
            granted_by,
            price_stars,
            updated_at
        )
        VALUES (
            ?,
            'DEMO',
            'ACTIVE',
            ?, ?, ?, 0, ?
        )
        """,
        (
            chat_id,
            now.isoformat(),
            expires,
            granted_by,
            now.isoformat()
        )
    )

    audit(
        "DEMO_STARTED",
        actor_id=granted_by,
        target_chat_id=chat_id,
        details=(
            f"days={days}; "
            f"expires={expires}"
        )
    )

    return get_subscription(
        chat_id
    )


# =========================================================
# GRANT PERMANENT FREE / VIP
# =========================================================

def grant_permanent_subscription(
    chat_id: int,
    plan: str,
    granted_by: int
):
    plan = (
        plan
        or ""
    ).upper()

    if plan not in {
        "FREE",
        "VIP",
    }:
        raise ValueError(
            "Faqat FREE yoki VIP."
        )

    now = iso_now()

    conn = db_connect()

    try:
        conn.execute(
            """
            INSERT INTO subscriptions (
                chat_id,
                plan,
                status,
                started_at,
                expires_at,
                granted_by,
                price_stars,
                updated_at
            )
            VALUES (
                ?, ?, 'ACTIVE',
                ?, NULL, ?, 0, ?
            )

            ON CONFLICT(chat_id)
            DO UPDATE SET
                plan = excluded.plan,
                status = 'ACTIVE',
                started_at = excluded.started_at,
                expires_at = NULL,
                granted_by = excluded.granted_by,
                price_stars = 0,
                updated_at = excluded.updated_at
            """,
            (
                chat_id,
                plan,
                now,
                granted_by,
                now
            )
        )

        conn.commit()

    finally:
        conn.close()

    audit(
        (
            "FREE_GRANTED"
            if plan == "FREE"
            else "VIP_GRANTED"
        ),
        actor_id=granted_by,
        target_chat_id=chat_id,
        details="permanent=1"
    )


# =========================================================
# REMOVE FREE / VIP / V7
# =========================================================

def deactivate_group_subscription(
    chat_id: int,
    actor_id: int
):
    db_execute(
        """
        UPDATE subscriptions
        SET
            status = 'INACTIVE',
            updated_at = ?
        WHERE chat_id = ?
        """,
        (
            iso_now(),
            chat_id
        )
    )

    audit(
        "SUBSCRIPTION_DEACTIVATED",
        actor_id=actor_id,
        target_chat_id=chat_id
    )


# =========================================================
# SUPER SUBSCRIPTION KEYBOARD
# =========================================================

def super_subscription_keyboard(
    chat_id: int
):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🎁 FREE",
                    callback_data=(
                        f"super:sub_free:"
                        f"{chat_id}"
                    )
                ),
                InlineKeyboardButton(
                    "👑 VIP",
                    callback_data=(
                        f"super:sub_vip:"
                        f"{chat_id}"
                    )
                )
            ],
            [
                InlineKeyboardButton(
                    "💎 +7 kun V7",
                    callback_data=(
                        f"super:sub_v7:"
                        f"{chat_id}"
                    )
                )
            ],
            [
                InlineKeyboardButton(
                    "🎁 Demo qayta berish",
                    callback_data=(
                        f"super:sub_demo:"
                        f"{chat_id}"
                    )
                )
            ],
            [
                InlineKeyboardButton(
                    "⛔ Obunani o'chirish",
                    callback_data=(
                        f"super:sub_disable:"
                        f"{chat_id}"
                    )
                )
            ],
            [
                InlineKeyboardButton(
                    "⬅️ Guruh",
                    callback_data=(
                        f"group:open:"
                        f"{chat_id}"
                    )
                )
            ]
        ]
    )


# =========================================================
# SHOW GROUP SUBSCRIPTION ADMIN PANEL
# =========================================================

async def show_super_group_subscription(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int
):
    if not await require_super_owner(
        update
    ):
        return

    query = update.callback_query

    group = get_group_record(
        chat_id
    )

    if not group:
        await query.answer(
            "❌ Guruh topilmadi.",
            show_alert=True
        )
        return

    info = expire_subscription_if_needed(
        chat_id
    )

    plan = (
        info["plan"]
        or "YO'Q"
    )

    status = info["status"]

    remaining = human_remaining_time(
        info["remaining_seconds"]
    )

    expires_text = "♾ Muddatsiz"

    if info["expires_at"]:
        expires_text = (
            info["expires_at"].strftime(
                "%Y-%m-%d %H:%M UTC"
            )
        )

    text = (
        "💎 GURUH OBUNASI\n\n"
        f"🏢 {group['title']}\n"
        f"🆔 {chat_id}\n\n"
        f"📦 Tarif: {plan}\n"
        f"📌 Holat: {status}\n"
        f"⏳ Qolgan: {remaining}\n"
        f"📅 Tugash: {expires_text}"
    )

    await query.answer()

    await query.edit_message_text(
        text,
        reply_markup=(
            super_subscription_keyboard(
                chat_id
            )
        )
    )


# =========================================================
# SUPER GRANT V7
# =========================================================

def super_grant_v7(
    chat_id: int,
    actor_id: int
):
    days = current_v7_days()

    existing = get_subscription(
        chat_id
    )

    now = utc_now()

    start_from = now

    if existing:
        plan = (
            existing["plan"]
            or ""
        ).upper()

        status = (
            existing["status"]
            or ""
        ).upper()

        expires = parse_iso_datetime(
            existing["expires_at"]
        )

        if (
            plan not in PERMANENT_PLANS
            and status == "ACTIVE"
            and expires
            and expires > now
        ):
            start_from = expires

    new_expires = (
        start_from
        + timedelta(days=days)
    )

    db_execute(
        """
        INSERT INTO subscriptions (
            chat_id,
            plan,
            status,
            started_at,
            expires_at,
            granted_by,
            price_stars,
            updated_at
        )
        VALUES (
            ?,
            'V7',
            'ACTIVE',
            ?, ?, ?, 0, ?
        )

        ON CONFLICT(chat_id)
        DO UPDATE SET
            plan = 'V7',
            status = 'ACTIVE',
            started_at = excluded.started_at,
            expires_at = excluded.expires_at,
            granted_by = excluded.granted_by,
            price_stars = 0,
            updated_at = excluded.updated_at
        """,
        (
            chat_id,
            now.isoformat(),
            new_expires.isoformat(),
            actor_id,
            now.isoformat()
        )
    )

    audit(
        "SUPER_V7_GRANTED",
        actor_id=actor_id,
        target_chat_id=chat_id,
        details=(
            f"days={days}; "
            f"expires={new_expires.isoformat()}"
        )
    )


# =========================================================
# SUPER RESET DEMO
# =========================================================

def reset_group_demo(
    chat_id: int,
    actor_id: int
):
    days = current_demo_days()

    now = utc_now()

    expires = (
        now
        + timedelta(days=days)
    )

    db_execute(
        """
        INSERT INTO subscriptions (
            chat_id,
            plan,
            status,
            started_at,
            expires_at,
            granted_by,
            price_stars,
            updated_at
        )
        VALUES (
            ?,
            'DEMO',
            'ACTIVE',
            ?, ?, ?, 0, ?
        )

        ON CONFLICT(chat_id)
        DO UPDATE SET
            plan = 'DEMO',
            status = 'ACTIVE',
            started_at = excluded.started_at,
            expires_at = excluded.expires_at,
            granted_by = excluded.granted_by,
            price_stars = 0,
            updated_at = excluded.updated_at
        """,
        (
            chat_id,
            now.isoformat(),
            expires.isoformat(),
            actor_id,
            now.isoformat()
        )
    )

    audit(
        "DEMO_RESET",
        actor_id=actor_id,
        target_chat_id=chat_id,
        details=(
            f"days={days}; "
            f"expires={expires.isoformat()}"
        )
    )


# =========================================================
# SUBSCRIPTION PANEL FOR NORMAL GROUP OWNER
# =========================================================

async def show_group_subscription_panel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int
):
    query = update.callback_query
    user = update.effective_user

    if not query or not user:
        return

    if not await can_manage_group(
        context,
        chat_id,
        user.id
    ):
        await query.answer(
            "⛔ Ruxsat yo'q.",
            show_alert=True
        )
        return

    info = expire_subscription_if_needed(
        chat_id
    )

    plan = (
        info["plan"]
        or "YO'Q"
    )

    remaining = human_remaining_time(
        info["remaining_seconds"]
    )

    price = current_v7_price()
    days = current_v7_days()

    rows = []

    if is_super_owner_id(
        user.id
    ):
        rows.append(
            [
                InlineKeyboardButton(
                    "👑 Super boshqaruv",
                    callback_data=(
                        f"super:subscription:"
                        f"{chat_id}"
                    )
                )
            ]
        )

    if info["plan"] not in PERMANENT_PLANS:
        rows.append(
            [
                InlineKeyboardButton(
                    (
                        f"💎 {days} kun V7 "
                        f"— {price} ⭐"
                    ),
                    callback_data=(
                        f"user:buy_v7:"
                        f"{chat_id}"
                    )
                )
            ]
        )

    rows.append(
        [
            InlineKeyboardButton(
                "⬅️ Guruh",
                callback_data=(
                    f"group:open:"
                    f"{chat_id}"
                )
            )
        ]
    )

    text = (
        "💎 VERITAS V7 OBUNA\n\n"
        f"📦 Tarif: {plan}\n"
        f"📌 Holat: {info['status']}\n"
        f"⏳ Qolgan vaqt: {remaining}\n\n"
    )

    if info["plan"] == "FREE":
        text += (
            "🎁 Ushbu guruhga muddatsiz "
            "FREE ruxsat berilgan."
        )

    elif info["plan"] == "VIP":
        text += (
            "👑 Ushbu guruh VIP rejimida."
        )

    elif info["active"]:
        text += (
            "✅ Veritas V7 funksiyalari faol."
        )

    else:
        text += (
            f"💰 {days} kunlik V7: "
            f"{price} ⭐"
        )

    await query.answer()

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(
            rows
        )
    )


# =========================================================
# SAFE V7 PURCHASE
# =========================================================

async def purchase_v7_safely(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int
):
    query = update.callback_query
    user = update.effective_user

    if not query or not user:
        return

    if not await can_manage_group(
        context,
        chat_id,
        user.id
    ):
        await query.answer(
            "⛔ Guruhni boshqarish "
            "huquqi yo'q.",
            show_alert=True
        )
        return

    info = expire_subscription_if_needed(
        chat_id
    )

    if info["plan"] in PERMANENT_PLANS:
        await query.answer(
            (
                f"✅ Guruh {info['plan']} "
                "rejimida."
            ),
            show_alert=True
        )
        return

    price = current_v7_price()
    days = current_v7_days()

    conn = db_connect()

    try:
        conn.execute(
            "BEGIN IMMEDIATE"
        )

        user_row = conn.execute(
            """
            SELECT internal_balance
            FROM users
            WHERE user_id = ?
            """,
            (user.id,)
        ).fetchone()

        if not user_row:
            conn.rollback()

            await query.answer(
                "❌ User bazada topilmadi.",
                show_alert=True
            )
            return

        balance = safe_int(
            user_row["internal_balance"]
        )

        if balance < price:
            conn.rollback()

            await query.answer(
                (
                    "❌ Balans yetarli emas.\n"
                    f"Kerak: {price} ⭐\n"
                    f"Sizda: {balance} ⭐"
                ),
                show_alert=True
            )
            return

        sub = conn.execute(
            """
            SELECT *
            FROM subscriptions
            WHERE chat_id = ?
            """,
            (chat_id,)
        ).fetchone()

        now = utc_now()

        start_from = now

        if sub:
            old_plan = (
                sub["plan"]
                or ""
            ).upper()

            old_status = (
                sub["status"]
                or ""
            ).upper()

            old_expires = parse_iso_datetime(
                sub["expires_at"]
            )

            if old_plan in PERMANENT_PLANS:
                conn.rollback()

                await query.answer(
                    "✅ Guruh muddatsiz tarifda.",
                    show_alert=True
                )
                return

            if (
                old_status == "ACTIVE"
                and old_expires
                and old_expires > now
            ):
                start_from = old_expires

        new_expires = (
            start_from
            + timedelta(days=days)
        )

        new_balance = (
            balance - price
        )

        conn.execute(
            """
            UPDATE users
            SET
                internal_balance = ?,
                updated_at = ?
            WHERE user_id = ?
            """,
            (
                new_balance,
                now.isoformat(),
                user.id
            )
        )

        conn.execute(
            """
            INSERT INTO balance_transactions (
                user_id,
                amount,
                transaction_type,
                description,
                reference,
                created_by,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user.id,
                -price,
                "V7_PURCHASE",
                (
                    f"{days} kunlik "
                    f"V7 | chat={chat_id}"
                ),
                (
                    f"v7:{chat_id}:"
                    f"{int(now.timestamp())}"
                ),
                user.id,
                now.isoformat()
            )
        )

        conn.execute(
            """
            INSERT INTO subscriptions (
                chat_id,
                plan,
                status,
                started_at,
                expires_at,
                granted_by,
                price_stars,
                updated_at
            )
            VALUES (
                ?,
                'V7',
                'ACTIVE',
                ?, ?, ?, ?, ?
            )

            ON CONFLICT(chat_id)
            DO UPDATE SET
                plan = 'V7',
                status = 'ACTIVE',
                started_at = excluded.started_at,
                expires_at = excluded.expires_at,
                granted_by = excluded.granted_by,
                price_stars = excluded.price_stars,
                updated_at = excluded.updated_at
            """,
            (
                chat_id,
                now.isoformat(),
                new_expires.isoformat(),
                user.id,
                price,
                now.isoformat()
            )
        )

        conn.execute(
            """
            INSERT INTO transactions (
                transaction_type,
                user_id,
                chat_id,
                amount,
                status,
                description,
                created_by,
                created_at
            )
            VALUES (
                'V7_PURCHASE',
                ?, ?, ?,
                'SUCCESS',
                ?, ?, ?
            )
            """,
            (
                user.id,
                chat_id,
                price,
                (
                    f"{days} kunlik "
                    "V7 obuna"
                ),
                user.id,
                now.isoformat()
            )
        )

        conn.commit()

    except Exception:
        conn.rollback()
        logger.exception(
            "V7 purchase transaction xatosi"
        )

        await query.answer(
            "❌ V7 xaridida xatolik.",
            show_alert=True
        )
        return

    finally:
        conn.close()

    audit(
        "V7_PURCHASED",
        actor_id=user.id,
        target_chat_id=chat_id,
        details=(
            f"price={price}; "
            f"days={days}; "
            f"expires={new_expires.isoformat()}"
        )
    )

    await query.answer(
        "✅ V7 faollashtirildi!",
        show_alert=True
    )

    await show_group_subscription_panel(
        update,
        context,
        chat_id
    )


# =========================================================
# EXPIRED SUBSCRIPTION JOB
# =========================================================

async def subscription_expiration_job(
    context: ContextTypes.DEFAULT_TYPE
):
    now = utc_now()

    rows = db_execute(
        """
        SELECT
            s.chat_id,
            s.plan,
            s.expires_at,
            g.title
        FROM subscriptions s

        LEFT JOIN groups g
            ON g.chat_id = s.chat_id

        WHERE s.status = 'ACTIVE'
          AND s.plan IN ('DEMO', 'V7')
          AND s.expires_at IS NOT NULL
        """,
        fetchall=True
    )

    for row in rows:
        expires = parse_iso_datetime(
            row["expires_at"]
        )

        if not expires:
            continue

        if expires > now:
            continue

        chat_id = safe_int(
            row["chat_id"]
        )

        plan = (
            row["plan"]
            or ""
        ).upper()

        db_execute(
            """
            UPDATE subscriptions
            SET
                status = 'EXPIRED',
                updated_at = ?
            WHERE chat_id = ?
              AND status = 'ACTIVE'
            """,
            (
                now.isoformat(),
                chat_id
            )
        )

        audit(
            "SUBSCRIPTION_EXPIRED",
            target_chat_id=chat_id,
            details=f"plan={plan}"
        )

        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    "⏳ VERITAS V7\n\n"
                    f"{plan} muddati tugadi.\n\n"
                    f"💎 {current_v7_days()} kunlik "
                    f"V7 narxi: "
                    f"{current_v7_price()} ⭐\n\n"
                    "Guruh boshqaruvchisi "
                    "shaxsiy kabinet orqali "
                    "obunani uzaytirishi mumkin."
                )
            )

        except TelegramError:
            pass


# =========================================================
# EXPIRING SOON CHECK
# =========================================================

async def subscription_reminder_job(
    context: ContextTypes.DEFAULT_TYPE
):
    now = utc_now()

    rows = db_execute(
        """
        SELECT *
        FROM subscriptions
        WHERE status = 'ACTIVE'
          AND plan IN ('DEMO', 'V7')
          AND expires_at IS NOT NULL
        """,
        fetchall=True
    )

    for row in rows:
        expires = parse_iso_datetime(
            row["expires_at"]
        )

        if not expires:
            continue

        remaining = (
            expires - now
        ).total_seconds()

        # 23-24 soat oralig'ida
        # bir marta ogohlantirish.
        if not (
            23 * 3600
            <= remaining
            <= 24 * 3600
        ):
            continue

        chat_id = safe_int(
            row["chat_id"]
        )

        reminder_key = (
            f"sub_reminder:"
            f"{chat_id}:"
            f"{expires.date().isoformat()}"
        )

        already_sent = get_setting(
            reminder_key,
            "0"
        )

        if str(already_sent) == "1":
            continue

        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    "⏰ VERITAS V7\n\n"
                    "Obuna tugashiga taxminan "
                    "1 kun qoldi.\n\n"
                    f"💎 {current_v7_days()} kun: "
                    f"{current_v7_price()} ⭐"
                )
            )

            set_setting(
                reminder_key,
                "1",
                None
            )

        except TelegramError:
            pass


# =========================================================
# SUPER SUBSCRIPTION CALLBACK
# =========================================================

async def subscription_super_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query

    if not query:
        return

    data = query.data or ""

    user = update.effective_user

    if (
        not user
        or not is_super_owner_id(
            user.id
        )
    ):
        await query.answer(
            "⛔ Super Ega huquqi yo'q.",
            show_alert=True
        )
        return

    # -----------------------------------------------------
    # PANEL
    # -----------------------------------------------------

    if data.startswith(
        "super:subscription:"
    ):
        try:
            chat_id = int(
                data.rsplit(
                    ":",
                    1
                )[1]
            )
        except ValueError:
            return

        await show_super_group_subscription(
            update,
            context,
            chat_id
        )
        return

    # -----------------------------------------------------
    # FREE
    # -----------------------------------------------------

    if data.startswith(
        "super:sub_free:"
    ):
        try:
            chat_id = int(
                data.rsplit(
                    ":",
                    1
                )[1]
            )
        except ValueError:
            return

        grant_permanent_subscription(
            chat_id,
            "FREE",
            user.id
        )

        await query.answer(
            "🎁 FREE faollashtirildi.",
            show_alert=True
        )

        await show_super_group_subscription(
            update,
            context,
            chat_id
        )
        return

    # -----------------------------------------------------
    # VIP
    # -----------------------------------------------------

    if data.startswith(
        "super:sub_vip:"
    ):
        try:
            chat_id = int(
                data.rsplit(
                    ":",
                    1
                )[1]
            )
        except ValueError:
            return

        grant_permanent_subscription(
            chat_id,
            "VIP",
            user.id
        )

        await query.answer(
            "👑 VIP faollashtirildi.",
            show_alert=True
        )

        await show_super_group_subscription(
            update,
            context,
            chat_id
        )
        return

    # -----------------------------------------------------
    # V7
    # -----------------------------------------------------

    if data.startswith(
        "super:sub_v7:"
    ):
        try:
            chat_id = int(
                data.rsplit(
                    ":",
                    1
                )[1]
            )
        except ValueError:
            return

        super_grant_v7(
            chat_id,
            user.id
        )

        await query.answer(
            (
                f"💎 +{current_v7_days()} "
                "kun V7 berildi."
            ),
            show_alert=True
        )

        await show_super_group_subscription(
            update,
            context,
            chat_id
        )
        return

    # -----------------------------------------------------
    # DEMO
    # -----------------------------------------------------

    if data.startswith(
        "super:sub_demo:"
    ):
        try:
            chat_id = int(
                data.rsplit(
                    ":",
                    1
                )[1]
            )
        except ValueError:
            return

        reset_group_demo(
            chat_id,
            user.id
        )

        await query.answer(
            (
                f"🎁 {current_demo_days()} "
                "kun Demo berildi."
            ),
            show_alert=True
        )

        await show_super_group_subscription(
            update,
            context,
            chat_id
        )
        return

    # -----------------------------------------------------
    # DISABLE
    # -----------------------------------------------------

    if data.startswith(
        "super:sub_disable:"
    ):
        try:
            chat_id = int(
                data.rsplit(
                    ":",
                    1
                )[1]
            )
        except ValueError:
            return

        deactivate_group_subscription(
            chat_id,
            user.id
        )

        await query.answer(
            "⛔ Obuna o'chirildi.",
            show_alert=True
        )

        await show_super_group_subscription(
            update,
            context,
            chat_id
        )
        return


# =========================================================
# NORMAL SUBSCRIPTION CALLBACK
# =========================================================

async def subscription_user_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query

    if not query:
        return

    data = query.data or ""

    if data.startswith(
        "group:subscription:"
    ):
        try:
            chat_id = int(
                data.rsplit(
                    ":",
                    1
                )[1]
            )
        except ValueError:
            return

        await show_group_subscription_panel(
            update,
            context,
            chat_id
        )
        return

    if data.startswith(
        "user:subscription_group:"
    ):
        try:
            chat_id = int(
                data.rsplit(
                    ":",
                    1
                )[1]
            )
        except ValueError:
            return

        await show_group_subscription_panel(
            update,
            context,
            chat_id
        )
        return

    if data.startswith(
        "user:buy_v7:"
    ):
        try:
            chat_id = int(
                data.rsplit(
                    ":",
                    1
                )[1]
            )
        except ValueError:
            return

        await purchase_v7_safely(
            update,
            context,
            chat_id
        )
        return


# =========================================================
# GROUP V7 GUARD
# =========================================================
#
# Yakuniy message router ichida ishlatiladi.
#
# DEMO / V7 / FREE / VIP faol bo'lsa:
#     True
#
# Tugagan bo'lsa:
#     False
# =========================================================

async def group_v7_guard(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    chat = update.effective_chat
    user = update.effective_user

    if not chat:
        return True

    if chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP,
    ):
        return True

    # Super Ega guruhda sinov qilishi mumkin.
    if (
        user
        and is_super_owner_id(
            user.id
        )
    ):
        return True

    return group_has_v7_access(
        chat.id
    )


# =========================================================
# SUBSCRIPTION DISPLAY LABEL
# =========================================================

def subscription_label(
    chat_id: int
):
    info = expire_subscription_if_needed(
        chat_id
    )

    plan = (
        info["plan"]
        or "YO'Q"
    )

    if not info["active"]:
        return (
            f"🔴 {plan} — "
            f"{info['status']}"
        )

    if plan == "VIP":
        return "👑 VIP — ACTIVE"

    if plan == "FREE":
        return "🎁 FREE — ACTIVE"

    if plan == "DEMO":
        return (
            "🎁 DEMO — "
            + human_remaining_time(
                info["remaining_seconds"]
            )
        )

    return (
        "💎 V7 — "
        + human_remaining_time(
            info["remaining_seconds"]
        )
    )


# =========================================================
# END PART 13
# =========================================================
# =========================================================
# VERITAS BOT V7
# PART 14 — CENTRAL ROUTERS, HANDLERS & MAIN
# =========================================================


# =========================================================
# BOT USERNAME
# =========================================================

BOT_USERNAME = ""


# =========================================================
# COMMAND: /ID
# =========================================================

async def id_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat

    if not message or not user:
        return

    lines = [
        "🆔 VERITAS ID",
        "",
        f"👤 Sizning ID: {user.id}",
    ]

    if chat:
        lines.append(
            f"💬 Chat ID: {chat.id}"
        )

    if (
        message.reply_to_message
        and message.reply_to_message.from_user
    ):
        target = (
            message.reply_to_message.from_user
        )

        lines.extend(
            [
                "",
                f"🎯 User ID: {target.id}",
            ]
        )

    await message.reply_text(
        "\n".join(lines)
    )


# =========================================================
# COMMAND: /BALANCE
# =========================================================

async def balance_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    user = update.effective_user
    message = update.effective_message

    if not user or not message:
        return

    ensure_user(user)

    balance = get_internal_balance(
        user.id
    )

    await message.reply_text(
        (
            "💰 VERITAS HISOB\n\n"
            f"⭐ Balans: {balance} Stars\n\n"
            "Bu Veritas ichki balansidir."
        )
    )


# =========================================================
# COMMAND: /TOPUP
# =========================================================

async def topup_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    await show_topup_menu(
        update,
        context
    )


# =========================================================
# COMMAND: /WALLET
# =========================================================

async def wallet_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    await show_user_wallet(
        update,
        context
    )


# =========================================================
# COMMAND: /PANEL
# =========================================================

async def panel_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    chat = update.effective_chat
    user = update.effective_user
    message = update.effective_message

    if (
        not chat
        or not user
        or not message
    ):
        return

    if chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP,
    ):
        await message.reply_text(
            "ℹ️ /panel guruh ichida ishlaydi."
        )
        return

    ensure_user(user)
    ensure_group(chat)

    if not await can_manage_group(
        context,
        chat.id,
        user.id
    ):
        await message.reply_text(
            "⛔ Guruh boshqaruv paneliga "
            "kirish huquqingiz yo'q."
        )
        return

    # show_group_panel Part 7 da yaratilgan.
    await show_group_panel(
        update,
        context,
        chat.id
    )


# =========================================================
# COMMAND: /HELP
# =========================================================

async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    message = update.effective_message

    if not message:
        return

    text = (
        "🤖 VERITAS BOT V7\n\n"

        "👤 Shaxsiy:\n"
        "/start — kabinet\n"
        "/wallet — hisob\n"
        "/balance — balans\n"
        "/topup — Stars to'ldirish\n"
        "/id — Telegram ID\n\n"

        "👥 Guruh:\n"
        "/panel — boshqaruv paneli\n"
        "/rules — qoidalar\n"
        "/activity — faollik\n"
        "/top — kunlik TOP\n"
        "/weekly — haftalik TOP\n"
        "/report — xabarga report\n\n"

        "📝 Notes:\n"
        "/save nom matn\n"
        "/get nom\n"
        "/notes\n"
        "/clear nom\n"
        "#nom\n\n"

        "🔎 Filter:\n"
        "/filter trigger javob\n"
        "/filters\n"
        "/stopfilter trigger\n\n"

        "🛡 Moderatsiya:\n"
        "/del — reply qilingan xabarni "
        "o'chirish\n\n"

        "🎁 Mukofot:\n"
        "Xabarga reply qilib:\n"
        "*give 25\n"
        "*give 50\n"
        "*give 100"
    )

    if (
        update.effective_user
        and is_super_owner_id(
            update.effective_user.id
        )
    ):
        text += (
            "\n\n👑 Super Ega:\n"
            "/super — Super Ega paneli"
        )

    await message.reply_text(
        text
    )


# =========================================================
# COMMAND: /CANCEL
# =========================================================

async def cancel_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    user = update.effective_user
    message = update.effective_message

    if not user or not message:
        return

    existed = USER_STATES.pop(
        user.id,
        None
    )

    if existed:
        await message.reply_text(
            "❌ Amal bekor qilindi."
        )
    else:
        await message.reply_text(
            "ℹ️ Bekor qilinadigan amal yo'q."
        )


# =========================================================
# CENTRAL STATE ROUTER
# =========================================================
#
# Barcha WAIT_* holatlar shu yerda tekshiriladi.
# =========================================================

async def central_state_router(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    user = update.effective_user

    if not user:
        return False

    if user.id not in USER_STATES:
        return False

    # Super Ega states
    if await super_state_router(
        update,
        context
    ):
        return True

    # Part 12 states
    if await part12_state_router(
        update,
        context
    ):
        return True

    # Reward states
    if await reward_state_router(
        update,
        context
    ):
        return True

    # Moderation states
    if await moderation_state_router(
        update,
        context
    ):
        return True

    # Protection / blacklist states
    if await protection_state_router(
        update,
        context
    ):
        return True

    return False


# =========================================================
# CENTRAL CALLBACK ROUTER
# =========================================================

async def central_callback_router(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query

    if not query:
        return

    data = query.data or ""

    try:

        # -------------------------------------------------
        # PAYMENT
        # -------------------------------------------------

        if data.startswith(
            "payment:"
        ):
            await payment_callback(
                update,
                context
            )
            return

        # -------------------------------------------------
        # PREMIUM
        # -------------------------------------------------

        if data.startswith(
            "premium:"
        ):

            # Super user cabinetidan
            # Premium tanlash.

            if data.startswith(
                "premium:select_user:"
            ):
                if not await require_super_owner(
                    update
                ):
                    return

                try:
                    target_user_id = int(
                        data.rsplit(
                            ":",
                            1
                        )[1]
                    )
                except ValueError:
                    return

                await query.answer()

                await query.edit_message_text(
                    (
                        "💎 TELEGRAM PREMIUM\n\n"
                        f"👤 ID: {target_user_id}\n\n"
                        "Muddatni tanlang:"
                    ),
                    reply_markup=(
                        premium_month_keyboard(
                            target_user_id
                        )
                    )
                )
                return

            await premium_callback(
                update,
                context
            )
            return

        # -------------------------------------------------
        # TELEGRAM GIFTS
        # -------------------------------------------------

        if data.startswith(
            "gift:"
        ):

            if data.startswith(
                "gift:select_user:"
            ):
                if not await require_super_owner(
                    update
                ):
                    return

                try:
                    target_user_id = int(
                        data.rsplit(
                            ":",
                            1
                        )[1]
                    )
                except ValueError:
                    return

                await show_gift_selection(
                    update,
                    context,
                    target_user_id
                )
                return

            await gift_callback(
                update,
                context
            )
            return

        # -------------------------------------------------
        # REWARDS
        # -------------------------------------------------

        if data.startswith(
            "reward:"
        ):
            await reward_callback(
                update,
                context
            )
            return

        # -------------------------------------------------
        # LIBRARY
        # -------------------------------------------------

        if data.startswith(
            "library:"
        ):
            await part12_callback(
                update,
                context
            )
            return

        # -------------------------------------------------
        # SUPER OWNER
        # -------------------------------------------------

        if data.startswith(
            "super:"
        ):
            # Rewards callbacks avval.
            if data in {
                "super:rewards",
                "super:reward_premium",
                "super:reward_gift",
                "super:reward_stars",
                "super:reward_history",
                "super:real_star_balance",
            }:
                await super_reward_callback(
                    update,
                    context
                )
                return

            # Part 12
            if (
                data.startswith(
                    "super:library"
                )
                or data.startswith(
                    "super:channel"
                )
                or data
                == "super:channels"
            ):
                await part12_callback(
                    update,
                    context
                )
                return

            # Subscription
            if (
                data.startswith(
                    "super:subscription:"
                )
                or data.startswith(
                    "super:sub_"
                )
            ):
                await subscription_super_callback(
                    update,
                    context
                )
                return

            await super_main_callback(
                update,
                context
            )
            return

        # -------------------------------------------------
        # USER CABINET
        # -------------------------------------------------

        if data.startswith(
            "user:"
        ):
            # V7 callbacksni yangi,
            # xavfsiz Part 13 boshqaradi.
            if (
                data.startswith(
                    "user:buy_v7:"
                )
                or data.startswith(
                    "user:subscription_group:"
                )
            ):
                await subscription_user_callback(
                    update,
                    context
                )
                return

            await user_callback(
                update,
                context
            )
            return

        # -------------------------------------------------
        # GROUP
        # -------------------------------------------------

        if data.startswith(
            "group:"
        ):
            # V7 subscription
            if data.startswith(
                "group:subscription:"
            ):
                await subscription_user_callback(
                    update,
                    context
                )
                return

            # Activity
            if data.startswith(
                "group:activity:"
            ):
                await activity_callback(
                    update,
                    context
                )
                return

            # Part 12 moderator/text callbacks
            if (
                data.startswith(
                    "group:addmod:"
                )
                or data.startswith(
                    "group:delmod:"
                )
                or data.startswith(
                    "group:text"
                )
            ):
                await part12_callback(
                    update,
                    context
                )
                return

            # Part 8 settings
            if (
                data.startswith(
                    "group:settings:"
                )
                or data.startswith(
                    "group:toggle:"
                )
                or data.startswith(
                    "group:media"
                )
                or data.startswith(
                    "group:blacklist"
                )
            ):
                await group_protection_callback(
                    update,
                    context
                )
                return

            # Part 7
            await group_callback(
                update,
                context
            )
            return

        # -------------------------------------------------
        # UNKNOWN CALLBACK
        # -------------------------------------------------

        await query.answer(
            "ℹ️ Bu tugma hozir faol emas."
        )

    except Exception as exc:
        logger.exception(
            "Callback router xatosi: %s",
            exc
        )

        try:
            await query.answer(
                "❌ Xatolik yuz berdi.",
                show_alert=True
            )
        except TelegramError:
            pass


# =========================================================
# CENTRAL NORMAL MESSAGE ROUTER
# =========================================================

async def central_message_router(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat

    if not message:
        return

    if user:
        ensure_user(
            user
        )

    if (
        chat
        and chat.type in (
            ChatType.GROUP,
            ChatType.SUPERGROUP,
        )
    ):
        ensure_group(
            chat
        )

    # -----------------------------------------------------
    # STATE INPUT
    # -----------------------------------------------------

    if (
        user
        and user.id in USER_STATES
    ):
        handled = await central_state_router(
            update,
            context
        )

        if handled:
            return

    # -----------------------------------------------------
    # GROUP ONLY
    # -----------------------------------------------------

    if (
        chat
        and chat.type in (
            ChatType.GROUP,
            ChatType.SUPERGROUP,
        )
    ):
        # Faollik V7 tugagan bo'lsa ham
        # bazada saqlanib turadi.
        await process_activity(
            update,
            context
        )

        # *give
        if message.text:
            if await star_give_message(
                update,
                context
            ):
                return

        # V7 access
        access = await group_v7_guard(
            update,
            context
        )

        if not access:
            return

        # Protection + notes + filters
        handled = await process_group_content(
            update,
            context
        )

        if handled:
            return


# =========================================================
# POST INIT
# =========================================================

async def post_init(
    application: Application
):
    global BOT_USERNAME

    try:
        me = await application.bot.get_me()

        BOT_USERNAME = (
            me.username
            or "VeritasBot"
        )

        logger.info(
            "Bot: @%s | ID: %s",
            BOT_USERNAME,
            me.id
        )

    except Exception:
        logger.exception(
            "Bot ma'lumotini olishda xato."
        )

        BOT_USERNAME = "VeritasBot"


# =========================================================
# REGISTER JOBS
# =========================================================

def register_jobs(
    application: Application
):
    job_queue = (
        application.job_queue
    )

    if job_queue is None:
        logger.warning(
            "JobQueue mavjud emas. "
            "python-telegram-bot[job-queue] "
            "o'rnatilishi kerak."
        )
        return

    # Har 10 daqiqada obunalarni tekshiradi.
    job_queue.run_repeating(
        subscription_expiration_job,
        interval=600,
        first=30,
        name="subscription_expiration"
    )

    # Har soatda 24 soatlik reminder tekshiruvi.
    job_queue.run_repeating(
        subscription_reminder_job,
        interval=3600,
        first=60,
        name="subscription_reminder"
    )

    # Kunlik mukofot.
    # UTC 00:05 atrofida.
    job_queue.run_daily(
        daily_reward_job,
        time=datetime.strptime(
            "00:05",
            "%H:%M"
        ).time().replace(
            tzinfo=timezone.utc
        ),
        name="daily_rewards"
    )

    # Haftalik mukofot:
    # Dushanba UTC 00:10.
    job_queue.run_daily(
        weekly_reward_job,
        time=datetime.strptime(
            "00:10",
            "%H:%M"
        ).time().replace(
            tzinfo=timezone.utc
        ),
        days=(0,),
        name="weekly_rewards"
    )


# =========================================================
# REGISTER COMMAND HANDLERS
# =========================================================

def register_command_handlers(
    application: Application
):
    application.add_handler(
        CommandHandler(
            "start",
            start_command
        ),
        group=0
    )

    application.add_handler(
        CommandHandler(
            "help",
            help_command
        ),
        group=0
    )

    application.add_handler(
        CommandHandler(
            "id",
            id_command
        ),
        group=0
    )

    application.add_handler(
        CommandHandler(
            "wallet",
            wallet_command
        ),
        group=0
    )

    application.add_handler(
        CommandHandler(
            "balance",
            balance_command
        ),
        group=0
    )

    application.add_handler(
        CommandHandler(
            "topup",
            topup_command
        ),
        group=0
    )

    application.add_handler(
        CommandHandler(
            "panel",
            panel_command
        ),
        group=0
    )

    application.add_handler(
        CommandHandler(
            "super",
            super_command
        ),
        group=0
    )

    application.add_handler(
        CommandHandler(
            "cancel",
            cancel_command
        ),
        group=0
    )

    # -----------------------------------------------------
    # RULES
    # -----------------------------------------------------

    application.add_handler(
        CommandHandler(
            "rules",
            rules_command
        ),
        group=0
    )

    application.add_handler(
        CommandHandler(
            "setrules",
            setrules_command
        ),
        group=0
    )

    # -----------------------------------------------------
    # NOTES
    # -----------------------------------------------------

    application.add_handler(
        CommandHandler(
            "save",
            save_note_command
        ),
        group=0
    )

    application.add_handler(
        CommandHandler(
            "get",
            get_note_command
        ),
        group=0
    )

    application.add_handler(
        CommandHandler(
            "notes",
            notes_command
        ),
        group=0
    )

    application.add_handler(
        CommandHandler(
            "clear",
            clear_note_command
        ),
        group=0
    )

    # -----------------------------------------------------
    # FILTERS
    # -----------------------------------------------------

    application.add_handler(
        CommandHandler(
            "filter",
            filter_command
        ),
        group=0
    )

    application.add_handler(
        CommandHandler(
            "filters",
            filters_command
        ),
        group=0
    )

    application.add_handler(
        CommandHandler(
            "stopfilter",
            stop_filter_command
        ),
        group=0
    )

    # -----------------------------------------------------
    # REPORT
    # -----------------------------------------------------

    application.add_handler(
        CommandHandler(
            "report",
            report_command
        ),
        group=0
    )

    # -----------------------------------------------------
    # ACTIVITY
    # -----------------------------------------------------

    application.add_handler(
        CommandHandler(
            "activity",
            activity_command
        ),
        group=0
    )

    application.add_handler(
        CommandHandler(
            "top",
            daily_top_command
        ),
        group=0
    )

    application.add_handler(
        CommandHandler(
            "weekly",
            weekly_top_command
        ),
        group=0
    )

    # -----------------------------------------------------
    # MODERATION
    # -----------------------------------------------------

    application.add_handler(
        CommandHandler(
            "del",
            delete_command
        ),
        group=0
    )


# =========================================================
# REGISTER SPECIAL HANDLERS
# =========================================================

def register_special_handlers(
    application: Application
):
    # -----------------------------------------------------
    # TELEGRAM STARS
    # -----------------------------------------------------

    application.add_handler(
        PreCheckoutQueryHandler(
            pre_checkout_handler
        ),
        group=0
    )

    application.add_handler(
        MessageHandler(
            filters.SUCCESSFUL_PAYMENT,
            successful_payment_handler
        ),
        group=0
    )

    # -----------------------------------------------------
    # WELCOME
    # -----------------------------------------------------

    application.add_handler(
        MessageHandler(
            filters.StatusUpdate.NEW_CHAT_MEMBERS,
            welcome_new_members
        ),
        group=0
    )

    # -----------------------------------------------------
    # GOODBYE
    # -----------------------------------------------------

    application.add_handler(
        MessageHandler(
            filters.StatusUpdate.LEFT_CHAT_MEMBER,
            goodbye_member
        ),
        group=0
    )

    # -----------------------------------------------------
    # CALLBACKS
    # -----------------------------------------------------

    application.add_handler(
        CallbackQueryHandler(
            central_callback_router
        ),
        group=0
    )


# =========================================================
# REGISTER NORMAL MESSAGE HANDLER
# =========================================================

def register_message_handlers(
    application: Application
):
    application.add_handler(
        MessageHandler(
            filters.ALL
            & ~filters.COMMAND
            & ~filters.StatusUpdate.NEW_CHAT_MEMBERS
            & ~filters.StatusUpdate.LEFT_CHAT_MEMBER
            & ~filters.SUCCESSFUL_PAYMENT,
            central_message_router
        ),
        group=1
    )


# =========================================================
# MAIN
# =========================================================

def main():
    logger.info(
        "%s ishga tushirilmoqda...",
        BOT_FULL_NAME
    )

    # Database yana tekshiriladi.
    init_database()

    # Part 12 migration.
    init_part12_database()

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # -----------------------------------------------------
    # COMMANDS
    # -----------------------------------------------------

    register_command_handlers(
        application
    )

    # -----------------------------------------------------
    # PAYMENT / CALLBACK / WELCOME
    # -----------------------------------------------------

    register_special_handlers(
        application
    )

    # -----------------------------------------------------
    # NORMAL MESSAGES
    # -----------------------------------------------------

    register_message_handlers(
        application
    )

    # -----------------------------------------------------
    # JOBS
    # -----------------------------------------------------

    register_jobs(
        application
    )

    # -----------------------------------------------------
    # ERROR HANDLER
    # -----------------------------------------------------

    application.add_error_handler(
        error_handler
    )

    logger.info(
        "%s handlerlari tayyor.",
        BOT_FULL_NAME
    )

    print(
        f"{BOT_FULL_NAME} ishga tushdi."
    )

    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=False
    )


# =========================================================
# START
# =========================================================

if __name__ == "__main__":
    main()
