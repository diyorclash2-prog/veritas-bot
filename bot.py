import os
import re
import sqlite3
import time
from datetime import datetime, timedelta, timezone

from telegram import (
    Update,
    ChatPermissions,
    LabeledPrice,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from telegram.ext import (
    Application,
    ContextTypes,
    MessageHandler,
    CallbackQueryHandler,
    PreCheckoutQueryHandler,
    filters,
)


# =========================================================
# VERITAS BOT v7
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN topilmadi. Railway Variables ni tekshiring."
    )


# =========================================================
# SUPER EGALAR
# =========================================================

# Ikkala Super Ega teng huquqli
SUPER_OWNER_IDS = {
    5859289233,  # Sakranum
    7056675943,  # Vasatiya
}


# Super Ega huquqiga ega kanallar
SUPER_OWNER_CHANNEL_IDS = {
    -1003565272437,  # Sakranum
    -1004342424568,  # Veritas
}


def is_super_owner_id(user_id):
    return bool(
        user_id
        and user_id in SUPER_OWNER_IDS
    )


def sender_channel_id(message):
    if not message or not message.sender_chat:
        return None

    return message.sender_chat.id


def is_super_owner_source(message, user):
    # Shaxsiy Telegram akkaunt
    if user and is_super_owner_id(user.id):
        return True

    # Ruxsat berilgan kanal nomidan
    channel_id = sender_channel_id(message)

    if channel_id in SUPER_OWNER_CHANNEL_IDS:
        return True

    return False


# =========================================================
# V7 ASOSIY SOZLAMALAR
# Keyinchalik Super Sozlamalar panelidan o‘zgartiriladi
# =========================================================

DEFAULT_LANGUAGE = "uz"

SUPPORTED_LANGUAGES = {
    "uz": "🇺🇿 O‘zbekcha",
    "ru": "🇷🇺 Русский",
    "en": "🇬🇧 English",
}

DEFAULT_DEMO_DAYS = 7
DEFAULT_V7_PRICE = 100
DEFAULT_V7_DAYS = 7

DEFAULT_BOOK_REWARD = 5

FREE_PLAN = "v6"
PREMIUM_PLAN = "v7"


# =========================================================
# DATABASE
# =========================================================

db = sqlite3.connect(
    "veritas.db",
    check_same_thread=False
)

db.row_factory = sqlite3.Row

cursor = db.cursor()


# Foreign key himoyasi
cursor.execute(
    "PRAGMA foreign_keys = ON"
)


# =========================================================
# DATABASE — V7 FOYDALANUVCHILAR
# =========================================================

cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT DEFAULT '',
        full_name TEXT DEFAULT '',
        language TEXT DEFAULT 'uz',

        registered_at TEXT NOT NULL,

        cabinet_balance INTEGER NOT NULL DEFAULT 0,

        level INTEGER NOT NULL DEFAULT 1,
        xp INTEGER NOT NULL DEFAULT 0,

        special_title TEXT DEFAULT '',

        is_blocked INTEGER NOT NULL DEFAULT 0,

        last_seen TEXT DEFAULT ''
    )
    """
)


# =========================================================
# DATABASE — GURUHLAR
# =========================================================

cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS groups (
        chat_id INTEGER PRIMARY KEY,

        title TEXT DEFAULT '',
        username TEXT DEFAULT '',

        owner_id INTEGER,

        plan TEXT NOT NULL DEFAULT 'v6',

        demo_started_at TEXT DEFAULT '',
        demo_expires_at TEXT DEFAULT '',

        subscription_expires_at TEXT DEFAULT '',

        free_v7 INTEGER NOT NULL DEFAULT 0,

        active INTEGER NOT NULL DEFAULT 1,

        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """
)


# =========================================================
# DATABASE — GURUH ICHKI ROLLARI
# =========================================================

cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS group_roles (
        chat_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,

        role TEXT NOT NULL DEFAULT 'moderator',

        granted_by INTEGER,
        granted_at TEXT NOT NULL,

        PRIMARY KEY (chat_id, user_id)
    )
    """
)


# =========================================================
# DATABASE — TRANZAKSIYALAR
# =========================================================

cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,

        user_id INTEGER,

        amount INTEGER NOT NULL,

        transaction_type TEXT NOT NULL,

        description TEXT DEFAULT '',

        telegram_charge_id TEXT DEFAULT '',

        created_at TEXT NOT NULL,

        created_by INTEGER
    )
    """
)


# =========================================================
# DATABASE — PLATFORM SOZLAMALARI
# =========================================================

cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS platform_settings (
        setting_key TEXT PRIMARY KEY,
        setting_value TEXT NOT NULL
    )
    """
)


# =========================================================
# DATABASE — SUPER EGA AUDIT LOG
# =========================================================

cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,

        actor_id INTEGER,
        action TEXT NOT NULL,

        target_user_id INTEGER,
        target_chat_id INTEGER,

        details TEXT DEFAULT '',

        created_at TEXT NOT NULL
    )
    """
)


# =========================================================
# DATABASE — USER GIFT TARIXI
# =========================================================

cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS user_rewards (
        id INTEGER PRIMARY KEY AUTOINCREMENT,

        user_id INTEGER NOT NULL,

        reward_type TEXT NOT NULL,
        reward_name TEXT DEFAULT '',

        star_value INTEGER NOT NULL DEFAULT 0,

        chat_id INTEGER,

        received_at TEXT NOT NULL
    )
    """
)


# =========================================================
# DATABASE — DEFAULT PLATFORM SETTINGS
# =========================================================

DEFAULT_SETTINGS = {
    "v7_price": str(DEFAULT_V7_PRICE),
    "v7_days": str(DEFAULT_V7_DAYS),
    "demo_days": str(DEFAULT_DEMO_DAYS),
    "book_reward": str(DEFAULT_BOOK_REWARD),

    "subscriptions_enabled": "1",
    "gifts_enabled": "1",
    "premium_enabled": "1",
    "library_enabled": "1",
    "levels_enabled": "1",
    "giveaways_enabled": "1",
}


for key, value in DEFAULT_SETTINGS.items():
    cursor.execute(
        """
        INSERT OR IGNORE INTO platform_settings (
            setting_key,
            setting_value
        )
        VALUES (?, ?)
        """,
        (
            key,
            value
        )
    )


db.commit()


# =========================================================
# TIME HELPERS
# =========================================================

def utc_now():
    return datetime.now(timezone.utc)


def datetime_to_db(value):
    return value.isoformat()


def db_to_datetime(value):
    if not value:
        return None

    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


# =========================================================
# PLATFORM SETTINGS HELPERS
# =========================================================

def get_platform_setting(
    key,
    default=None
):
    cursor.execute(
        """
        SELECT setting_value
        FROM platform_settings
        WHERE setting_key = ?
        """,
        (key,)
    )

    row = cursor.fetchone()

    if not row:
        return default

    return row["setting_value"]


def get_int_setting(
    key,
    default=0
):
    value = get_platform_setting(
        key,
        str(default)
    )

    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# =========================================================
# AUDIT LOG
# =========================================================

def add_audit_log(
    actor_id,
    action,
    target_user_id=None,
    target_chat_id=None,
    details=""
):
    cursor.execute(
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
            datetime_to_db(utc_now())
        )
    )

    db.commit()


# =========================================================
# USER HELPERS
# =========================================================

def register_or_update_user(user):
    if not user or user.is_bot:
        return

    now = datetime_to_db(
        utc_now()
    )

    username = user.username or ""
    full_name = user.full_name or ""

    cursor.execute(
        """
        INSERT INTO users (
            user_id,
            username,
            full_name,
            registered_at,
            last_seen
        )
        VALUES (?, ?, ?, ?, ?)

        ON CONFLICT(user_id)
        DO UPDATE SET
            username = excluded.username,
            full_name = excluded.full_name,
            last_seen = excluded.last_seen
        """,
        (
            user.id,
            username,
            full_name,
            now,
            now
        )
    )

    db.commit()


def get_user_cabinet(user_id):
    cursor.execute(
        """
        SELECT *
        FROM users
        WHERE user_id = ?
        """,
        (user_id,)
    )

    return cursor.fetchone()


def get_name(user):
    if not user:
        return "Noma’lum"

    if user.full_name:
        return user.full_name

    if user.username:
        return f"@{user.username}"

    return str(user.id)
    # =========================================================
# VERITAS v7 — 2-QISM
# GROUP + PLAN + PERMISSION CORE
# =========================================================


# =========================================================
# GROUP HELPERS
# =========================================================

async def register_or_update_group(
    chat,
    context
):
    if not chat:
        return

    if chat.type not in (
        "group",
        "supergroup",
    ):
        return

    now = utc_now()
    now_text = datetime_to_db(now)

    title = chat.title or ""
    username = chat.username or ""

    # Telegram guruh egasini aniqlaymiz
    owner_id = None

    try:
        admins = await context.bot.get_chat_administrators(
            chat.id
        )

        for admin in admins:
            if admin.status == "creator":
                owner_id = admin.user.id
                register_or_update_user(
                    admin.user
                )
                break

    except Exception as error:
        print(
            "GROUP OWNER ERROR:",
            repr(error)
        )

    cursor.execute(
        """
        SELECT *
        FROM groups
        WHERE chat_id = ?
        """,
        (chat.id,)
    )

    existing = cursor.fetchone()

    # ---------------------------------------------
    # YANGI GURUH
    # 7 KUNLIK V7 DEMO
    # ---------------------------------------------

    if not existing:
        demo_days = get_int_setting(
            "demo_days",
            DEFAULT_DEMO_DAYS
        )

        demo_expires = (
            now
            + timedelta(
                days=demo_days
            )
        )

        cursor.execute(
            """
            INSERT INTO groups (
                chat_id,
                title,
                username,
                owner_id,
                plan,
                demo_started_at,
                demo_expires_at,
                subscription_expires_at,
                free_v7,
                active,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, '', 0, 1, ?, ?)
            """,
            (
                chat.id,
                title,
                username,
                owner_id,
                PREMIUM_PLAN,
                now_text,
                datetime_to_db(
                    demo_expires
                ),
                now_text,
                now_text
            )
        )

        db.commit()

        add_audit_log(
            actor_id=None,
            action="group_registered",
            target_chat_id=chat.id,
            details=(
                f"Yangi guruh. "
                f"V7 demo: {demo_days} kun."
            )
        )

        return

    # ---------------------------------------------
    # MAVJUD GURUH MA'LUMOTINI YANGILASH
    # ---------------------------------------------

    cursor.execute(
        """
        UPDATE groups
        SET
            title = ?,
            username = ?,
            owner_id = COALESCE(?, owner_id),
            active = 1,
            updated_at = ?
        WHERE chat_id = ?
        """,
        (
            title,
            username,
            owner_id,
            now_text,
            chat.id
        )
    )

    db.commit()


def get_group(chat_id):
    cursor.execute(
        """
        SELECT *
        FROM groups
        WHERE chat_id = ?
        """,
        (chat_id,)
    )

    return cursor.fetchone()


# =========================================================
# V7 ACCESS
# =========================================================

def group_has_v7(chat_id):
    group = get_group(chat_id)

    if not group:
        return False

    # Super Ega tomonidan bepul V7
    if group["free_v7"]:
        return True

    now = utc_now()

    # Faol pullik obuna
    subscription_expires = db_to_datetime(
        group["subscription_expires_at"]
    )

    if (
        subscription_expires
        and subscription_expires > now
    ):
        return True

    # 7 kunlik demo
    demo_expires = db_to_datetime(
        group["demo_expires_at"]
    )

    if (
        demo_expires
        and demo_expires > now
    ):
        return True

    return False


def get_effective_plan(chat_id):
    if group_has_v7(chat_id):
        return PREMIUM_PLAN

    return FREE_PLAN


def refresh_group_plan(chat_id):
    """
    Guruhning amaldagi holatini DBga yozadi.

    V7 muddati tugasa:
    V6 free rejimiga qaytadi.

    V7 qayta faollashsa:
    V7 rejimiga qaytadi.
    """

    effective_plan = get_effective_plan(
        chat_id
    )

    cursor.execute(
        """
        SELECT plan
        FROM groups
        WHERE chat_id = ?
        """,
        (chat_id,)
    )

    row = cursor.fetchone()

    if not row:
        return effective_plan

    old_plan = row["plan"]

    if old_plan != effective_plan:
        cursor.execute(
            """
            UPDATE groups
            SET
                plan = ?,
                updated_at = ?
            WHERE chat_id = ?
            """,
            (
                effective_plan,
                datetime_to_db(
                    utc_now()
                ),
                chat_id
            )
        )

        db.commit()

        add_audit_log(
            actor_id=None,
            action="plan_changed",
            target_chat_id=chat_id,
            details=(
                f"{old_plan} -> "
                f"{effective_plan}"
            )
        )

    return effective_plan


# =========================================================
# SUPER OWNER PROTECTION
# =========================================================

def is_protected_super_owner(user_id):
    """
    Ikkala Super Ega:
    - warn
    - mute
    - kick
    - ban

    kabi Veritas amallaridan himoyalanadi.
    """

    return is_super_owner_id(
        user_id
    )


# =========================================================
# TELEGRAM ADMIN CHECK
# =========================================================

async def is_telegram_admin(
    chat,
    user_id,
    context
):
    if not chat or not user_id:
        return False

    try:
        member = await context.bot.get_chat_member(
            chat.id,
            user_id
        )

        return member.status in (
            "administrator",
            "creator",
        )

    except Exception:
        return False


# =========================================================
# GROUP OWNER CHECK
# =========================================================

def is_group_owner(
    chat_id,
    user_id
):
    if not user_id:
        return False

    group = get_group(
        chat_id
    )

    if not group:
        return False

    return (
        group["owner_id"]
        == user_id
    )


# =========================================================
# INTERNAL MODERATOR CHECK
# =========================================================

def is_internal_moderator(
    chat_id,
    user_id
):
    if not user_id:
        return False

    cursor.execute(
        """
        SELECT 1
        FROM group_roles
        WHERE chat_id = ?
          AND user_id = ?
        """,
        (
            chat_id,
            user_id
        )
    )

    return (
        cursor.fetchone()
        is not None
    )


# =========================================================
# VERITAS ADMIN CHECK
# =========================================================

async def is_veritas_admin(
    message,
    user,
    chat,
    context
):
    # Super Ega
    if is_super_owner_source(
        message,
        user
    ):
        return True

    if not user:
        return False

    # Guruh egasi
    if is_group_owner(
        chat.id,
        user.id
    ):
        return True

    # Veritas ichki moderatori
    if is_internal_moderator(
        chat.id,
        user.id
    ):
        return True

    # Telegram administratori
    if await is_telegram_admin(
        chat,
        user.id,
        context
    ):
        return True

    return False


async def admin_required(
    message,
    user,
    chat,
    context
):
    allowed = await is_veritas_admin(
        message,
        user,
        chat,
        context
    )

    if allowed:
        return True

    await message.reply_text(
        "⛔ Bu buyruq uchun "
        "administrator huquqi kerak."
    )

    return False


async def super_owner_required(
    message,
    user
):
    if is_super_owner_source(
        message,
        user
    ):
        return True

    await message.reply_text(
        "⛔ Bu bo‘lim faqat "
        "Veritas Super Egalari uchun."
    )

    return False


# =========================================================
# GROUP PLAN INFORMATION
# =========================================================

def group_plan_text(chat_id):
    group = get_group(
        chat_id
    )

    if not group:
        return (
            "⚠️ Guruh hali Veritas "
            "tizimiga ro‘yxatdan o‘tmagan."
        )

    plan = refresh_group_plan(
        chat_id
    )

    if group["free_v7"]:
        return (
            "💎 Veritas V7\n"
            "🎁 Super Ega tomonidan "
            "bepul V7 ruxsati."
        )

    if plan == PREMIUM_PLAN:
        subscription = db_to_datetime(
            group["subscription_expires_at"]
        )

        if (
            subscription
            and subscription > utc_now()
        ):
            return (
                "💎 Veritas V7\n"
                "✅ Obuna faol.\n"
                f"📅 Tugash: "
                f"{subscription.strftime('%Y-%m-%d %H:%M UTC')}"
            )

        demo = db_to_datetime(
            group["demo_expires_at"]
        )

        if demo and demo > utc_now():
            return (
                "💎 Veritas V7 DEMO\n"
                "🎁 Sinov muddati faol.\n"
                f"📅 Tugash: "
                f"{demo.strftime('%Y-%m-%d %H:%M UTC')}"
            )

    price = get_int_setting(
        "v7_price",
        DEFAULT_V7_PRICE
    )

    days = get_int_setting(
        "v7_days",
        DEFAULT_V7_DAYS
    )

    return (
        "🆓 Veritas V6 FREE\n"
        "V7 funksiyalari hozir faol emas.\n\n"
        f"💎 V7: {price} ⭐ / {days} kun"
    )
    # =========================================================
# VERITAS v7 — 3-QISM
# V6 FREE CORE DATABASE
# =========================================================


# =========================================================
# GROUP SETTINGS
# =========================================================

cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS settings (
        chat_id INTEGER PRIMARY KEY,

        link_block INTEGER NOT NULL DEFAULT 0,
        welcome INTEGER NOT NULL DEFAULT 1,
        goodbye INTEGER NOT NULL DEFAULT 1,

        rules TEXT DEFAULT '',

        antiflood INTEGER NOT NULL DEFAULT 0,
        flood_limit INTEGER NOT NULL DEFAULT 5,

        reports INTEGER NOT NULL DEFAULT 1,
        captcha INTEGER NOT NULL DEFAULT 0
    )
    """
)


# =========================================================
# ACTIVITY
# =========================================================

cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS activity (
        chat_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,

        name TEXT DEFAULT '',
        username TEXT DEFAULT '',

        messages INTEGER NOT NULL DEFAULT 0,

        PRIMARY KEY (chat_id, user_id)
    )
    """
)


# =========================================================
# WARNINGS
# =========================================================

cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS warnings (
        chat_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,

        warns INTEGER NOT NULL DEFAULT 0,

        PRIMARY KEY (chat_id, user_id)
    )
    """
)


# =========================================================
# BLACKLIST
# =========================================================

cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS blacklist (
        chat_id INTEGER NOT NULL,
        word TEXT NOT NULL,

        PRIMARY KEY (chat_id, word)
    )
    """
)


# =========================================================
# FILTERS
# =========================================================

cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS chat_filters (
        chat_id INTEGER NOT NULL,
        keyword TEXT NOT NULL,

        response TEXT DEFAULT '',
        media_type TEXT DEFAULT 'text',
        file_id TEXT DEFAULT '',
        caption TEXT DEFAULT '',

        PRIMARY KEY (chat_id, keyword)
    )
    """
)


# =========================================================
# NOTES
# =========================================================

cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS notes (
        chat_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        content TEXT NOT NULL,

        PRIMARY KEY (chat_id, name)
    )
    """
)


# =========================================================
# APPROVED USERS
# =========================================================

cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS approved_users (
        chat_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,

        PRIMARY KEY (chat_id, user_id)
    )
    """
)


# =========================================================
# LOCKS
# =========================================================

cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS locks (
        chat_id INTEGER NOT NULL,
        lock_type TEXT NOT NULL,

        PRIMARY KEY (chat_id, lock_type)
    )
    """
)


# =========================================================
# FLOOD DATA
# =========================================================

cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS flood_data (
        chat_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,

        count INTEGER NOT NULL DEFAULT 0,
        last_time REAL NOT NULL DEFAULT 0,

        PRIMARY KEY (chat_id, user_id)
    )
    """
)


db.commit()


# =========================================================
# DATABASE MIGRATION HELPER
# =========================================================

def add_column_if_missing(
    table,
    column,
    definition
):
    try:
        cursor.execute(
            f"ALTER TABLE {table} "
            f"ADD COLUMN {column} {definition}"
        )
        db.commit()

    except sqlite3.OperationalError:
        pass


# Eski V6 bazasi mavjud bo‘lsa,
# yetishmayotgan ustunlarni qo‘shamiz.

add_column_if_missing(
    "settings",
    "antiflood",
    "INTEGER DEFAULT 0"
)

add_column_if_missing(
    "settings",
    "flood_limit",
    "INTEGER DEFAULT 5"
)

add_column_if_missing(
    "settings",
    "reports",
    "INTEGER DEFAULT 1"
)

add_column_if_missing(
    "settings",
    "captcha",
    "INTEGER DEFAULT 0"
)

add_column_if_missing(
    "chat_filters",
    "media_type",
    "TEXT DEFAULT 'text'"
)

add_column_if_missing(
    "chat_filters",
    "file_id",
    "TEXT DEFAULT ''"
)

add_column_if_missing(
    "chat_filters",
    "caption",
    "TEXT DEFAULT ''"
)


# =========================================================
# SETTINGS HELPER
# =========================================================

def ensure_settings(chat_id):
    cursor.execute(
        """
        INSERT OR IGNORE INTO settings (
            chat_id
        )
        VALUES (?)
        """,
        (chat_id,)
    )

    db.commit()


# =========================================================
# REPLY TARGET
# =========================================================

def reply_target(message):
    if not message:
        return None

    if not message.reply_to_message:
        return None

    return message.reply_to_message.from_user


# =========================================================
# LINK DETECTION
# =========================================================

def contains_link(text):
    if not text:
        return False

    patterns = (
        r"https?://",
        r"www\.",
        r"t\.me/",
        r"telegram\.me/",
        r"telegram\.dog/",
    )

    lower_text = text.lower()

    return any(
        re.search(
            pattern,
            lower_text
        )
        for pattern in patterns
    )


# =========================================================
# APPROVED CHECK
# =========================================================

def is_approved(
    chat_id,
    user_id
):
    if not user_id:
        return False

    cursor.execute(
        """
        SELECT 1
        FROM approved_users
        WHERE chat_id = ?
          AND user_id = ?
        """,
        (
            chat_id,
            user_id
        )
    )

    return (
        cursor.fetchone()
        is not None
    )


# =========================================================
# LOCK HELPERS
# =========================================================

def get_locks(chat_id):
    cursor.execute(
        """
        SELECT lock_type
        FROM locks
        WHERE chat_id = ?
        ORDER BY lock_type
        """,
        (chat_id,)
    )

    return [
        row["lock_type"]
        for row in cursor.fetchall()
    ]


# =========================================================
# MEDIA HELPER
# =========================================================

def media_from_message(message):
    if message.sticker:
        return (
            "sticker",
            message.sticker.file_id
        )

    if message.photo:
        return (
            "photo",
            message.photo[-1].file_id
        )

    if message.video:
        return (
            "video",
            message.video.file_id
        )

    if message.animation:
        return (
            "animation",
            message.animation.file_id
        )

    if message.audio:
        return (
            "audio",
            message.audio.file_id
        )

    if message.voice:
        return (
            "voice",
            message.voice.file_id
        )

    if message.document:
        return (
            "document",
            message.document.file_id
        )

    return (
        "text",
        ""
    )


# =========================================================
# SAVED FILTER RESPONSE
# =========================================================

async def send_saved_filter(
    message,
    context,
    media_type,
    file_id,
    response,
    caption
):
    final_caption = (
        caption
        or response
        or None
    )

    if media_type == "sticker":
        await context.bot.send_sticker(
            chat_id=message.chat.id,
            sticker=file_id
        )
        return

    if media_type == "photo":
        await context.bot.send_photo(
            chat_id=message.chat.id,
            photo=file_id,
            caption=final_caption
        )
        return

    if media_type == "video":
        await context.bot.send_video(
            chat_id=message.chat.id,
            video=file_id,
            caption=final_caption
        )
        return

    if media_type == "animation":
        await context.bot.send_animation(
            chat_id=message.chat.id,
            animation=file_id,
            caption=final_caption
        )
        return

    if media_type == "audio":
        await context.bot.send_audio(
            chat_id=message.chat.id,
            audio=file_id,
            caption=final_caption
        )
        return

    if media_type == "voice":
        await context.bot.send_voice(
            chat_id=message.chat.id,
            voice=file_id,
            caption=final_caption
        )
        return

    if media_type == "document":
        await context.bot.send_document(
            chat_id=message.chat.id,
            document=file_id,
            caption=final_caption
        )
        return

    if response:
        await message.reply_text(
            response
        )


# =========================================================
# ACTIVITY COUNTER
# =========================================================

def add_activity(
    chat_id,
    user
):
    if not user or user.is_bot:
        return

    username = user.username or ""
    name = get_name(user)

    cursor.execute(
        """
        INSERT INTO activity (
            chat_id,
            user_id,
            name,
            username,
            messages
        )
        VALUES (?, ?, ?, ?, 1)

        ON CONFLICT(chat_id, user_id)
        DO UPDATE SET
            name = excluded.name,
            username = excluded.username,
            messages = messages + 1
        """,
        (
            chat_id,
            user.id,
            name,
            username
        )
    )

    db.commit()


# =========================================================
# WARNING HELPERS
# =========================================================

def get_warn_count(
    chat_id,
    user_id
):
    cursor.execute(
        """
        SELECT warns
        FROM warnings
        WHERE chat_id = ?
          AND user_id = ?
        """,
        (
            chat_id,
            user_id
        )
    )

    row = cursor.fetchone()

    if not row:
        return 0

    return row["warns"]


def clear_warns(
    chat_id,
    user_id
):
    cursor.execute(
        """
        DELETE FROM warnings
        WHERE chat_id = ?
          AND user_id = ?
        """,
        (
            chat_id,
            user_id
        )
    )

    db.commit()


# =========================================================
# PROTECTION BYPASS
# =========================================================

async def is_protection_bypassed(
    message,
    user,
    chat,
    context
):
    if not user:
        return True

    # Ikkala Super Ega
    if is_super_owner_source(
        message,
        user
    ):
        return True

    # Guruh egasi
    if is_group_owner(
        chat.id,
        user.id
    ):
        return True

    # Telegram admin
    if await is_telegram_admin(
        chat,
        user.id,
        context
    ):
        return True

    # Veritas ichki moderator
    if is_internal_moderator(
        chat.id,
        user.id
    ):
        return True

    # Approved user
    if is_approved(
        chat.id,
        user.id
    ):
        return True

    return False
    # =========================================================
# VERITAS v7 — 4-QISM
# LANGUAGE + REGISTRATION + PERSONAL CABINET
# =========================================================


# =========================================================
# LANGUAGE TEXTS
# =========================================================

TEXTS = {
    "uz": {
        "choose_language": (
            "🌐 Tilni tanlang:\n\n"
            "Veritas siz bilan tanlangan tilda ishlaydi."
        ),
        "registered": (
            "✅ Veritas kabineti yaratildi!\n\n"
            "Quyidagi menyudan foydalanishingiz mumkin."
        ),
        "cabinet": "👤 Shaxsiy kabinet",
        "my_groups": "👥 Guruhlarim",
        "balance": "⭐ Balans",
        "profile": "🏅 Profil",
        "help": "❓ Qanday ishlaydi?",
        "settings": "⚙️ Sozlamalar",
        "super_panel": "👑 Super Ega",
        "language": "🌐 Til",
        "back": "⬅️ Orqaga",
    },

    "ru": {
        "choose_language": (
            "🌐 Выберите язык:\n\n"
            "Veritas будет работать на выбранном языке."
        ),
        "registered": (
            "✅ Кабинет Veritas создан!\n\n"
            "Используйте меню ниже."
        ),
        "cabinet": "👤 Личный кабинет",
        "my_groups": "👥 Мои группы",
        "balance": "⭐ Баланс",
        "profile": "🏅 Профиль",
        "help": "❓ Как это работает?",
        "settings": "⚙️ Настройки",
        "super_panel": "👑 Super Owner",
        "language": "🌐 Язык",
        "back": "⬅️ Назад",
    },

    "en": {
        "choose_language": (
            "🌐 Choose your language:\n\n"
            "Veritas will use your selected language."
        ),
        "registered": (
            "✅ Your Veritas cabinet has been created!\n\n"
            "Use the menu below."
        ),
        "cabinet": "👤 Personal cabinet",
        "my_groups": "👥 My groups",
        "balance": "⭐ Balance",
        "profile": "🏅 Profile",
        "help": "❓ How does it work?",
        "settings": "⚙️ Settings",
        "super_panel": "👑 Super Owner",
        "language": "🌐 Language",
        "back": "⬅️ Back",
    },
}


def user_language(user_id):
    cabinet = get_user_cabinet(
        user_id
    )

    if not cabinet:
        return DEFAULT_LANGUAGE

    language = cabinet["language"]

    if language not in SUPPORTED_LANGUAGES:
        return DEFAULT_LANGUAGE

    return language


def tr(
    user_id,
    key
):
    language = user_language(
        user_id
    )

    return (
        TEXTS
        .get(language, TEXTS["uz"])
        .get(key, key)
    )


# =========================================================
# LANGUAGE MENU
# =========================================================

def language_keyboard():
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🇺🇿 O‘zbekcha",
                    callback_data="lang:uz"
                )
            ],
            [
                InlineKeyboardButton(
                    "🇷🇺 Русский",
                    callback_data="lang:ru"
                )
            ],
            [
                InlineKeyboardButton(
                    "🇬🇧 English",
                    callback_data="lang:en"
                )
            ],
        ]
    )


# =========================================================
# MAIN CABINET KEYBOARD
# =========================================================

def cabinet_keyboard(
    user_id
):
    keyboard = [
        [
            InlineKeyboardButton(
                tr(
                    user_id,
                    "profile"
                ),
                callback_data="cabinet:profile"
            ),
            InlineKeyboardButton(
                tr(
                    user_id,
                    "balance"
                ),
                callback_data="cabinet:balance"
            ),
        ],

        [
            InlineKeyboardButton(
                tr(
                    user_id,
                    "my_groups"
                ),
                callback_data="cabinet:groups"
            )
        ],

        [
            InlineKeyboardButton(
                tr(
                    user_id,
                    "help"
                ),
                callback_data="cabinet:help"
            ),
            InlineKeyboardButton(
                tr(
                    user_id,
                    "settings"
                ),
                callback_data="cabinet:settings"
            ),
        ],
    ]

    # Faqat 2 Super Ega ko‘radi
    if is_super_owner_id(
        user_id
    ):
        keyboard.append(
            [
                InlineKeyboardButton(
                    "👑 Super Ega",
                    callback_data="super:home"
                )
            ]
        )

    return InlineKeyboardMarkup(
        keyboard
    )


# =========================================================
# CABINET HOME
# =========================================================

async def show_cabinet(
    message,
    user
):
    cabinet = get_user_cabinet(
        user.id
    )

    if not cabinet:
        register_or_update_user(
            user
        )

        cabinet = get_user_cabinet(
            user.id
        )

    text = (
        "🪶 VERITAS\n\n"
        f"👤 {get_name(user)}\n"
        f"🆔 {user.id}\n\n"
        f"{tr(user.id, 'cabinet')}"
    )

    await message.reply_text(
        text,
        reply_markup=cabinet_keyboard(
            user.id
        )
    )


# =========================================================
# START
# =========================================================

async def private_start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat

    if (
        not message
        or not user
        or not chat
        or chat.type != "private"
    ):
        return

    # Oldin ro‘yxatdan o‘tganmi?
    cabinet = get_user_cabinet(
        user.id
    )

    if cabinet:
        register_or_update_user(
            user
        )

        await show_cabinet(
            message,
            user
        )
        return

    # Yangi foydalanuvchi.
    # Avval users bazasiga yoziladi,
    # keyin til tanlaydi.
    register_or_update_user(
        user
    )

    await message.reply_text(
        TEXTS["uz"]["choose_language"],
        reply_markup=language_keyboard()
    )


# =========================================================
# LANGUAGE CALLBACK
# =========================================================

async def language_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query

    if not query:
        return

    await query.answer()

    user = query.from_user

    if not user:
        return

    data = query.data or ""

    if not data.startswith(
        "lang:"
    ):
        return

    language = data.split(
        ":",
        1
    )[1]

    if language not in SUPPORTED_LANGUAGES:
        return

    register_or_update_user(
        user
    )

    cursor.execute(
        """
        UPDATE users
        SET language = ?
        WHERE user_id = ?
        """,
        (
            language,
            user.id
        )
    )

    db.commit()

    add_audit_log(
        actor_id=user.id,
        action="language_changed",
        target_user_id=user.id,
        details=language
    )

    await query.edit_message_text(
        TEXTS[language]["registered"],
        reply_markup=cabinet_keyboard(
            user.id
        )
    )


# =========================================================
# PROFILE TEXT
# =========================================================

def cabinet_profile_text(
    user_id
):
    cabinet = get_user_cabinet(
        user_id
    )

    if not cabinet:
        return (
            "⚠️ Veritas kabineti topilmadi."
        )

    username = (
        f"@{cabinet['username']}"
        if cabinet["username"]
        else "—"
    )

    special_title = (
        cabinet["special_title"]
        or "—"
    )

    return (
        "🏅 VERITAS PROFIL\n\n"
        f"🆔 ID: {cabinet['user_id']}\n"
        f"👤 {cabinet['full_name']}\n"
        f"🔗 {username}\n\n"
        f"💎 LVL: {cabinet['level']}/15\n"
        f"✨ XP: {cabinet['xp']}\n"
        f"🎖 Unvon: {special_title}\n"
        f"⭐ Balans: "
        f"{cabinet['cabinet_balance']}"
    )


# =========================================================
# BALANCE TEXT
# =========================================================

def cabinet_balance_text(
    user_id
):
    cabinet = get_user_cabinet(
        user_id
    )

    if not cabinet:
        return (
            "⚠️ Kabinet topilmadi."
        )

    return (
        "⭐ VERITAS BALANS\n\n"
        f"⭐ {cabinet['cabinet_balance']} Stars\n\n"
        "Bu — Veritas ichki kabinet balansidir.\n"
        "Telegram botining umumiy Stars "
        "balansidan alohida hisob yuritiladi."
    )


# =========================================================
# USER GROUPS
# =========================================================

def user_groups_text(
    user_id
):
    cursor.execute(
        """
        SELECT
            chat_id,
            title,
            plan,
            free_v7,
            demo_expires_at,
            subscription_expires_at
        FROM groups
        WHERE owner_id = ?
          AND active = 1
        ORDER BY created_at DESC
        """,
        (user_id,)
    )

    rows = cursor.fetchall()

    if not rows:
        return (
            "👥 Sizga tegishli Veritas "
            "guruhi hozircha topilmadi."
        )

    lines = [
        "👥 GURUHLARIM",
        ""
    ]

    for row in rows:
        plan = refresh_group_plan(
            row["chat_id"]
        )

        icon = (
            "💎"
            if plan == PREMIUM_PLAN
            else "🆓"
        )

        lines.append(
            f"{icon} {row['title']}\n"
            f"   ID: {row['chat_id']}\n"
            f"   Rejim: {plan.upper()}"
        )

    return "\n\n".join(
        lines
    )


# =========================================================
# CABINET CALLBACK
# =========================================================

async def cabinet_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query

    if not query:
        return

    await query.answer()

    user = query.from_user

    if not user:
        return

    register_or_update_user(
        user
    )

    data = query.data or ""

    # ---------------------------------------------
    # PROFILE
    # ---------------------------------------------

    if data == "cabinet:profile":
        await query.edit_message_text(
            cabinet_profile_text(
                user.id
            ),
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            tr(
                                user.id,
                                "back"
                            ),
                            callback_data="cabinet:home"
                        )
                    ]
                ]
            )
        )
        return

    # ---------------------------------------------
    # BALANCE
    # ---------------------------------------------

    if data == "cabinet:balance":
        await query.edit_message_text(
            cabinet_balance_text(
                user.id
            ),
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            tr(
                                user.id,
                                "back"
                            ),
                            callback_data="cabinet:home"
                        )
                    ]
                ]
            )
        )
        return

    # ---------------------------------------------
    # GROUPS
    # ---------------------------------------------

    if data == "cabinet:groups":
        await query.edit_message_text(
            user_groups_text(
                user.id
            ),
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            tr(
                                user.id,
                                "back"
                            ),
                            callback_data="cabinet:home"
                        )
                    ]
                ]
            )
        )
        return

    # ---------------------------------------------
    # SETTINGS
    # ---------------------------------------------

    if data == "cabinet:settings":
        await query.edit_message_text(
            "⚙️ VERITAS SOZLAMALARI",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            tr(
                                user.id,
                                "language"
                            ),
                            callback_data=(
                                "cabinet:language"
                            )
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            tr(
                                user.id,
                                "back"
                            ),
                            callback_data=(
                                "cabinet:home"
                            )
                        )
                    ],
                ]
            )
        )
        return

    # ---------------------------------------------
    # CHANGE LANGUAGE
    # ---------------------------------------------

    if data == "cabinet:language":
        await query.edit_message_text(
            tr(
                user.id,
                "language"
            ),
            reply_markup=language_keyboard()
        )
        return

    # ---------------------------------------------
    # HELP
    # ---------------------------------------------

    if data == "cabinet:help":
        await query.edit_message_text(
            (
                "❓ VERITAS QANDAY ISHLAYDI?\n\n"
                "🆓 V6 — asosiy guruh "
                "boshqaruvi va himoya.\n\n"
                "💎 V7 — kabinet, darajalar, "
                "mukofotlar, kutubxona va "
                "qo‘shimcha imkoniyatlar.\n\n"
                "Yangi guruhga V7 DEMO "
                "avtomatik beriladi."
            ),
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            tr(
                                user.id,
                                "back"
                            ),
                            callback_data="cabinet:home"
                        )
                    ]
                ]
            )
        )
        return

    # ---------------------------------------------
    # HOME
    # ---------------------------------------------

    if data == "cabinet:home":
        await query.edit_message_text(
            (
                "🪶 VERITAS\n\n"
                f"👤 {get_name(user)}\n"
                f"🆔 {user.id}\n\n"
                f"{tr(user.id, 'cabinet')}"
            ),
            reply_markup=cabinet_keyboard(
                user.id
            )
        )
        return
        # =========================================================
# VERITAS v7 — 5-QISM
# SUPER OWNER CABINET
# =========================================================


# =========================================================
# SUPER OWNER KEYBOARD
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
                ),
            ],
            [
                InlineKeyboardButton(
                    "💳 Tranzaksiyalar",
                    callback_data="super:transactions"
                ),
                InlineKeyboardButton(
                    "🎁 Mukofotlar",
                    callback_data="super:rewards"
                ),
            ],
            [
                InlineKeyboardButton(
                    "📚 Kutubxona",
                    callback_data="super:library"
                ),
                InlineKeyboardButton(
                    "📊 Statistika",
                    callback_data="super:stats"
                ),
            ],
            [
                InlineKeyboardButton(
                    "⚙️ Super Sozlamalar",
                    callback_data="super:settings"
                ),
            ],
            [
                InlineKeyboardButton(
                    "🔎 ID orqali kabinet",
                    callback_data="super:find_user"
                ),
            ],
            [
                InlineKeyboardButton(
                    "📋 Audit log",
                    callback_data="super:audit"
                ),
            ],
            [
                InlineKeyboardButton(
                    "⬅️ Shaxsiy kabinet",
                    callback_data="cabinet:home"
                )
            ],
        ]
    )


# =========================================================
# SUPER OWNER HOME
# =========================================================

async def show_super_owner_home(
    query,
    user
):
    if not is_super_owner_id(user.id):
        await query.answer(
            "⛔ Ruxsat yo‘q.",
            show_alert=True
        )
        return

    cursor.execute(
        "SELECT COUNT(*) AS total FROM users"
    )
    users_count = cursor.fetchone()["total"]

    cursor.execute(
        """
        SELECT COUNT(*) AS total
        FROM groups
        WHERE active = 1
        """
    )
    groups_count = cursor.fetchone()["total"]

    cursor.execute(
        """
        SELECT COUNT(*) AS total
        FROM groups
        WHERE active = 1
          AND free_v7 = 1
        """
    )
    free_v7_count = cursor.fetchone()["total"]

    text = (
        "👑 VERITAS SUPER EGA\n\n"
        "🤝 Umumiy boshqaruv kabineti\n\n"
        f"👤 Foydalanuvchilar: {users_count}\n"
        f"👥 Faol guruhlar: {groups_count}\n"
        f"🎁 Bepul V7 guruhlar: {free_v7_count}\n\n"
        "🔐 Super Egalar:\n"
        "• Sakranum\n"
        "• Vasatiya"
    )

    await query.edit_message_text(
        text,
        reply_markup=super_owner_keyboard()
    )


# =========================================================
# SUPER OWNER STATS
# =========================================================

def super_stats_text():
    cursor.execute(
        "SELECT COUNT(*) AS total FROM users"
    )
    users_count = cursor.fetchone()["total"]

    cursor.execute(
        """
        SELECT COUNT(*) AS total
        FROM groups
        WHERE active = 1
        """
    )
    groups_count = cursor.fetchone()["total"]

    v7_count = 0
    v6_count = 0

    cursor.execute(
        """
        SELECT chat_id
        FROM groups
        WHERE active = 1
        """
    )

    group_rows = cursor.fetchall()

    for row in group_rows:
        if group_has_v7(row["chat_id"]):
            v7_count += 1
        else:
            v6_count += 1

    cursor.execute(
        """
        SELECT COALESCE(
            SUM(cabinet_balance),
            0
        ) AS total
        FROM users
        """
    )

    internal_balance = cursor.fetchone()["total"]

    cursor.execute(
        """
        SELECT COUNT(*) AS total
        FROM transactions
        """
    )

    transaction_count = cursor.fetchone()["total"]

    return (
        "📊 VERITAS STATISTIKA\n\n"
        f"👤 Kabinetlar: {users_count}\n"
        f"👥 Faol guruhlar: {groups_count}\n"
        f"💎 V7 guruhlar: {v7_count}\n"
        f"🆓 V6 guruhlar: {v6_count}\n\n"
        f"⭐ Ichki balanslar jami: "
        f"{internal_balance}\n"
        f"💳 Tranzaksiyalar: "
        f"{transaction_count}"
    )


# =========================================================
# USERS LIST
# =========================================================

def super_users_text():
    cursor.execute(
        """
        SELECT
            user_id,
            username,
            full_name,
            level,
            cabinet_balance
        FROM users
        ORDER BY registered_at DESC
        LIMIT 20
        """
    )

    rows = cursor.fetchall()

    if not rows:
        return (
            "👤 Hali foydalanuvchilar yo‘q."
        )

    lines = [
        "👤 SO‘NGGI 20 FOYDALANUVCHI",
        ""
    ]

    for row in rows:
        name = (
            f"@{row['username']}"
            if row["username"]
            else row["full_name"]
        )

        lines.append(
            f"• {name}\n"
            f"  ID: {row['user_id']} | "
            f"LVL {row['level']} | "
            f"⭐ {row['cabinet_balance']}"
        )

    return "\n\n".join(lines)


# =========================================================
# GROUPS LIST
# =========================================================

def super_groups_text():
    cursor.execute(
        """
        SELECT
            chat_id,
            title,
            owner_id
        FROM groups
        WHERE active = 1
        ORDER BY created_at DESC
        LIMIT 20
        """
    )

    rows = cursor.fetchall()

    if not rows:
        return (
            "👥 Hali Veritas guruhlari yo‘q."
        )

    lines = [
        "👥 SO‘NGGI 20 GURUH",
        ""
    ]

    for row in rows:
        plan = get_effective_plan(
            row["chat_id"]
        )

        icon = (
            "💎"
            if plan == PREMIUM_PLAN
            else "🆓"
        )

        lines.append(
            f"{icon} {row['title']}\n"
            f"  ID: {row['chat_id']}\n"
            f"  Ega ID: {row['owner_id'] or '—'}"
        )

    return "\n\n".join(lines)


# =========================================================
# TRANSACTIONS LIST
# =========================================================

def super_transactions_text():
    cursor.execute(
        """
        SELECT
            id,
            user_id,
            amount,
            transaction_type,
            description,
            created_at
        FROM transactions
        ORDER BY id DESC
        LIMIT 20
        """
    )

    rows = cursor.fetchall()

    if not rows:
        return (
            "💳 Hali tranzaksiyalar yo‘q."
        )

    lines = [
        "💳 SO‘NGGI 20 TRANZAKSIYA",
        ""
    ]

    for row in rows:
        amount = row["amount"]

        sign = (
            "+"
            if amount > 0
            else ""
        )

        lines.append(
            f"#{row['id']} | "
            f"{sign}{amount} ⭐\n"
            f"👤 {row['user_id'] or '—'}\n"
            f"📌 {row['transaction_type']}\n"
            f"📝 {row['description'] or '—'}"
        )

    return "\n\n".join(lines)


# =========================================================
# AUDIT LOG
# =========================================================

def super_audit_text():
    cursor.execute(
        """
        SELECT
            actor_id,
            action,
            target_user_id,
            target_chat_id,
            details,
            created_at
        FROM audit_log
        ORDER BY id DESC
        LIMIT 15
        """
    )

    rows = cursor.fetchall()

    if not rows:
        return (
            "📋 Audit log hozircha bo‘sh."
        )

    lines = [
        "📋 SO‘NGGI 15 HARAKAT",
        ""
    ]

    for row in rows:
        lines.append(
            f"👑 Actor: {row['actor_id'] or 'SYSTEM'}\n"
            f"⚙️ {row['action']}\n"
            f"👤 User: {row['target_user_id'] or '—'}\n"
            f"👥 Group: {row['target_chat_id'] or '—'}\n"
            f"📝 {row['details'] or '—'}"
        )

    return "\n\n".join(lines)


# =========================================================
# USER CABINET BY ID
# =========================================================

def super_user_cabinet_text(
    target_user_id
):
    cabinet = get_user_cabinet(
        target_user_id
    )

    if not cabinet:
        return None

    username = (
        f"@{cabinet['username']}"
        if cabinet["username"]
        else "—"
    )

    title = (
        cabinet["special_title"]
        or "—"
    )

    cursor.execute(
        """
        SELECT COUNT(*) AS total
        FROM groups
        WHERE owner_id = ?
          AND active = 1
        """,
        (target_user_id,)
    )

    group_count = cursor.fetchone()["total"]

    cursor.execute(
        """
        SELECT COUNT(*) AS total
        FROM user_rewards
        WHERE user_id = ?
        """,
        (target_user_id,)
    )

    reward_count = cursor.fetchone()["total"]

    return (
        "👑 SUPER EGA — USER KABINET\n\n"
        f"👤 {cabinet['full_name']}\n"
        f"🔗 {username}\n"
        f"🆔 {cabinet['user_id']}\n\n"
        f"💎 LVL: {cabinet['level']}/15\n"
        f"✨ XP: {cabinet['xp']}\n"
        f"🎖 Unvon: {title}\n"
        f"⭐ Ichki balans: "
        f"{cabinet['cabinet_balance']}\n\n"
        f"👥 Guruhlari: {group_count}\n"
        f"🎁 Mukofotlari: {reward_count}\n"
        f"🚫 Blok: "
        f"{'Ha' if cabinet['is_blocked'] else 'Yo‘q'}"
    )


# =========================================================
# SUPER SETTINGS KEYBOARD
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
                ),
            ],
            [
                InlineKeyboardButton(
                    "📅 V7 muddati",
                    callback_data="super:set_days"
                ),
                InlineKeyboardButton(
                    "📚 Kitob mukofoti",
                    callback_data="super:set_book_reward"
                ),
            ],
            [
                InlineKeyboardButton(
                    "⭐ To‘lov tizimi",
                    callback_data="super:payments"
                ),
                InlineKeyboardButton(
                    "🎁 Gift tizimi",
                    callback_data="super:gift_settings"
                ),
            ],
            [
                InlineKeyboardButton(
                    "🏆 Mukofot tizimi",
                    callback_data="super:reward_settings"
                ),
                InlineKeyboardButton(
                    "📚 Kutubxona",
                    callback_data="super:library"
                ),
            ],
            [
                InlineKeyboardButton(
                    "🌐 3 til matnlari",
                    callback_data="super:texts"
                ),
            ],
            [
                InlineKeyboardButton(
                    "📢 Kanallar",
                    callback_data="super:channels"
                ),
            ],
            [
                InlineKeyboardButton(
                    "⬅️ Super Ega",
                    callback_data="super:home"
                )
            ],
        ]
    )


# =========================================================
# SUPER OWNER CALLBACK
# =========================================================

async def super_owner_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query

    if not query:
        return

    user = query.from_user

    if not user:
        return

    data = query.data or ""

    if not data.startswith("super:"):
        return

    if not is_super_owner_id(user.id):
        await query.answer(
            "⛔ Bu bo‘lim faqat Super Egalar uchun.",
            show_alert=True
        )
        return

    await query.answer()

    # ---------------------------------------------
    # HOME
    # ---------------------------------------------

    if data == "super:home":
        await show_super_owner_home(
            query,
            user
        )
        return

    # ---------------------------------------------
    # USERS
    # ---------------------------------------------

    if data == "super:users":
        await query.edit_message_text(
            super_users_text(),
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🔎 ID orqali topish",
                            callback_data="super:find_user"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "⬅️ Orqaga",
                            callback_data="super:home"
                        )
                    ],
                ]
            )
        )
        return

    # ---------------------------------------------
    # GROUPS
    # ---------------------------------------------

    if data == "super:groups":
        await query.edit_message_text(
            super_groups_text(),
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "⬅️ Orqaga",
                            callback_data="super:home"
                        )
                    ]
                ]
            )
        )
        return

    # ---------------------------------------------
    # STATS
    # ---------------------------------------------

    if data == "super:stats":
        await query.edit_message_text(
            super_stats_text(),
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "⬅️ Orqaga",
                            callback_data="super:home"
                        )
                    ]
                ]
            )
        )
        return

    # ---------------------------------------------
    # TRANSACTIONS
    # ---------------------------------------------

    if data == "super:transactions":
        await query.edit_message_text(
            super_transactions_text(),
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "⬅️ Orqaga",
                            callback_data="super:home"
                        )
                    ]
                ]
            )
        )
        return

    # ---------------------------------------------
    # AUDIT
    # ---------------------------------------------

    if data == "super:audit":
        await query.edit_message_text(
            super_audit_text(),
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "⬅️ Orqaga",
                            callback_data="super:home"
                        )
                    ]
                ]
            )
        )
        return

    # ---------------------------------------------
    # FIND USER
    # ---------------------------------------------

    if data == "super:find_user":
        context.user_data[
            "super_waiting_user_id"
        ] = True

        await query.edit_message_text(
            "🔎 FOYDALANUVCHI KABINETI\n\n"
            "Telegram ID raqamini yuboring.\n\n"
            "Masalan:\n"
            "5859289233\n\n"
            "Bekor qilish uchun /cancel yozing."
        )
        return

    # ---------------------------------------------
    # SETTINGS
    # ---------------------------------------------

    if data == "super:settings":
        price = get_int_setting(
            "v7_price",
            DEFAULT_V7_PRICE
        )

        demo = get_int_setting(
            "demo_days",
            DEFAULT_DEMO_DAYS
        )

        days = get_int_setting(
            "v7_days",
            DEFAULT_V7_DAYS
        )

        book_reward = get_int_setting(
            "book_reward",
            DEFAULT_BOOK_REWARD
        )

        await query.edit_message_text(
            (
                "⚙️ SUPER SOZLAMALAR\n\n"
                f"💎 V7: {price} ⭐\n"
                f"🎁 Demo: {demo} kun\n"
                f"📅 Obuna: {days} kun\n"
                f"📚 Kitob mukofoti: "
                f"{book_reward} ⭐"
            ),
            reply_markup=super_settings_keyboard()
        )
        return

    # ---------------------------------------------
    # KEYINGI MODULLAR
    # ---------------------------------------------

    future_sections = {
        "super:rewards": "🎁 Mukofotlar",
        "super:library": "📚 Kutubxona",
        "super:payments": "⭐ To‘lov tizimi",
        "super:gift_settings": "🎁 Gift tizimi",
        "super:reward_settings": "🏆 Mukofot tizimi",
        "super:texts": "🌐 Til matnlari",
        "super:channels": "📢 Super Ega kanallari",
        "super:set_price": "💎 V7 narxi",
        "super:set_demo": "🎁 Demo muddati",
        "super:set_days": "📅 V7 muddati",
        "super:set_book_reward": "📚 Kitob mukofoti",
    }

    if data in future_sections:
        await query.edit_message_text(
            (
                f"{future_sections[data]}\n\n"
                "⚙️ Ushbu modul V7 qurilishining "
                "keyingi qismida ulanadi."
            ),
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "⬅️ Super Sozlamalar",
                            callback_data="super:settings"
                        )
                    ]
                ]
            )
        )
        return


# =========================================================
# SUPER OWNER — ID INPUT
# =========================================================

async def handle_super_owner_input(
    message,
    user,
    context
):
    if not is_super_owner_id(user.id):
        return False

    waiting = context.user_data.get(
        "super_waiting_user_id"
    )

    if not waiting:
        return False

    text = (
        message.text
        or ""
    ).strip()

    if text.lower() == "/cancel":
        context.user_data.pop(
            "super_waiting_user_id",
            None
        )

        await message.reply_text(
            "✅ Qidiruv bekor qilindi.",
            reply_markup=cabinet_keyboard(
                user.id
            )
        )
        return True

    try:
        target_user_id = int(text)

    except ValueError:
        await message.reply_text(
            "⚠️ Telegram ID faqat raqamlardan "
            "iborat bo‘lishi kerak.\n\n"
            "Masalan: 5859289233"
        )
        return True

    cabinet_text = super_user_cabinet_text(
        target_user_id
    )

    if not cabinet_text:
        await message.reply_text(
            "❌ Bu ID bilan Veritas kabineti topilmadi.\n\n"
            "Boshqa ID yuboring yoki /cancel yozing."
        )
        return True

    context.user_data.pop(
        "super_waiting_user_id",
        None
    )

    add_audit_log(
        actor_id=user.id,
        action="super_view_user_cabinet",
        target_user_id=target_user_id,
        details="Kabinet ID orqali ko‘rildi."
    )

    await message.reply_text(
        cabinet_text,
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "👑 Super Ega paneli",
                        callback_data="super:home"
                    )
                ]
            ]
        )
    )

    return True
    # =========================================================
# VERITAS v7 — 6-QISM
# STARS + CABINET BALANCE + TRANSACTIONS
# =========================================================


# =========================================================
# PAYMENT DATABASE
# =========================================================

cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS star_payments (
        telegram_charge_id TEXT PRIMARY KEY,

        user_id INTEGER NOT NULL,
        amount INTEGER NOT NULL,

        payload TEXT DEFAULT '',
        created_at TEXT NOT NULL
    )
    """
)

db.commit()


# =========================================================
# BALANCE HELPERS
# =========================================================

def get_cabinet_balance(user_id):
    cabinet = get_user_cabinet(
        user_id
    )

    if not cabinet:
        return 0

    return int(
        cabinet["cabinet_balance"]
    )


def add_transaction(
    user_id,
    amount,
    transaction_type,
    description="",
    telegram_charge_id="",
    created_by=None
):
    cursor.execute(
        """
        INSERT INTO transactions (
            user_id,
            amount,
            transaction_type,
            description,
            telegram_charge_id,
            created_at,
            created_by
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            amount,
            transaction_type,
            description,
            telegram_charge_id,
            datetime_to_db(
                utc_now()
            ),
            created_by
        )
    )


def change_cabinet_balance(
    user_id,
    amount,
    transaction_type,
    description="",
    telegram_charge_id="",
    created_by=None
):
    """
    amount:
      +100 = balansga qo‘shish
      -100 = balansdan yechish

    Manfiy balansga tushishga ruxsat berilmaydi.
    """

    cabinet = get_user_cabinet(
        user_id
    )

    if not cabinet:
        return False

    current_balance = int(
        cabinet["cabinet_balance"]
    )

    new_balance = (
        current_balance
        + amount
    )

    if new_balance < 0:
        return False

    try:
        cursor.execute(
            "BEGIN"
        )

        cursor.execute(
            """
            UPDATE users
            SET cabinet_balance = ?
            WHERE user_id = ?
            """,
            (
                new_balance,
                user_id
            )
        )

        add_transaction(
            user_id=user_id,
            amount=amount,
            transaction_type=transaction_type,
            description=description,
            telegram_charge_id=telegram_charge_id,
            created_by=created_by
        )

        db.commit()

        return True

    except Exception as error:
        db.rollback()

        print(
            "BALANCE ERROR:",
            repr(error)
        )

        return False


# =========================================================
# STARS TOP-UP INVOICE
# =========================================================

async def create_stars_topup(
    message,
    user,
    context,
    amount
):
    if not user:
        return

    # Oddiy xavfsizlik chegarasi
    if amount < 1:
        await message.reply_text(
            "⚠️ Stars miqdori kamida 1 bo‘lishi kerak."
        )
        return

    if amount > 10000:
        await message.reply_text(
            "⚠️ Bir martalik to‘lov miqdori "
            "10 000 ⭐ dan oshmasin."
        )
        return

    register_or_update_user(
        user
    )

    payload = (
        f"veritas_balance:"
        f"{user.id}:"
        f"{amount}"
    )

    try:
        await context.bot.send_invoice(
            chat_id=user.id,

            title=(
                "Veritas kabinet balansi"
            ),

            description=(
                f"Veritas ichki balansiga "
                f"{amount} ⭐ qo‘shish"
            ),

            payload=payload,

            currency="XTR",

            prices=[
                LabeledPrice(
                    "Veritas Stars",
                    amount
                )
            ],

            provider_token=""
        )

    except Exception as error:
        print(
            "INVOICE ERROR:",
            repr(error)
        )

        await message.reply_text(
            "❌ Stars to‘lovi yaratilmadi."
        )


# =========================================================
# PRE-CHECKOUT
# =========================================================

async def precheckout_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.pre_checkout_query

    if not query:
        return

    payload = (
        query.invoice_payload
        or ""
    )

    # Faqat Veritas yaratgan invoice
    if not payload.startswith(
        "veritas_balance:"
    ):
        await query.answer(
            ok=False,
            error_message=(
                "Noto‘g‘ri Veritas to‘lovi."
            )
        )
        return

    parts = payload.split(":")

    if len(parts) != 3:
        await query.answer(
            ok=False,
            error_message=(
                "To‘lov ma’lumoti noto‘g‘ri."
            )
        )
        return

    try:
        payload_user_id = int(
            parts[1]
        )

        payload_amount = int(
            parts[2]
        )

    except ValueError:
        await query.answer(
            ok=False,
            error_message=(
                "To‘lov ma’lumoti noto‘g‘ri."
            )
        )
        return

    # Invoice boshqa foydalanuvchiga
    # o‘tib ketmasligi uchun
    if query.from_user.id != payload_user_id:
        await query.answer(
            ok=False,
            error_message=(
                "Bu to‘lov boshqa "
                "foydalanuvchiga tegishli."
            )
        )
        return

    # Telegram yuborgan summa bilan
    # payload summasi bir xil bo‘lishi shart
    if (
        query.currency != "XTR"
        or query.total_amount != payload_amount
    ):
        await query.answer(
            ok=False,
            error_message=(
                "Stars miqdori mos kelmadi."
            )
        )
        return

    await query.answer(
        ok=True
    )


# =========================================================
# SUCCESSFUL STARS PAYMENT
# =========================================================

async def successful_payment(
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

    payload = (
        payment.invoice_payload
        or ""
    )

    if not payload.startswith(
        "veritas_balance:"
    ):
        return

    parts = payload.split(":")

    if len(parts) != 3:
        return

    try:
        payload_user_id = int(
            parts[1]
        )

        payload_amount = int(
            parts[2]
        )

    except ValueError:
        return

    if payload_user_id != user.id:
        return

    if (
        payment.currency != "XTR"
        or payment.total_amount != payload_amount
    ):
        return

    charge_id = (
        payment.telegram_payment_charge_id
    )

    if not charge_id:
        print(
            "PAYMENT ERROR: "
            "telegram_payment_charge_id yo‘q"
        )
        return

    register_or_update_user(
        user
    )

    # ---------------------------------------------
    # DUPLICATE PAYMENT CHECK
    # ---------------------------------------------

    cursor.execute(
        """
        SELECT 1
        FROM star_payments
        WHERE telegram_charge_id = ?
        """,
        (charge_id,)
    )

    if cursor.fetchone():
        await message.reply_text(
            "ℹ️ Bu to‘lov avval hisobga olingan."
        )
        return

    try:
        cursor.execute(
            "BEGIN"
        )

        # To‘lovni birinchi marta qayd qilamiz
        cursor.execute(
            """
            INSERT INTO star_payments (
                telegram_charge_id,
                user_id,
                amount,
                payload,
                created_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                charge_id,
                user.id,
                payment.total_amount,
                payload,
                datetime_to_db(
                    utc_now()
                )
            )
        )

        # Kabinet balansini oshiramiz
        cursor.execute(
            """
            UPDATE users
            SET cabinet_balance =
                cabinet_balance + ?
            WHERE user_id = ?
            """,
            (
                payment.total_amount,
                user.id
            )
        )

        # Tranzaksiya
        add_transaction(
            user_id=user.id,
            amount=payment.total_amount,
            transaction_type="stars_topup",
            description=(
                "Telegram Stars orqali "
                "kabinet balansi to‘ldirildi."
            ),
            telegram_charge_id=charge_id,
            created_by=user.id
        )

        db.commit()

    except sqlite3.IntegrityError:
        db.rollback()

        await message.reply_text(
            "ℹ️ Bu to‘lov avval hisobga olingan."
        )
        return

    except Exception as error:
        db.rollback()

        print(
            "PAYMENT SAVE ERROR:",
            repr(error)
        )

        # Muhim:
        # Telegram to‘lovi amalga oshgan bo‘lishi mumkin.
        # Shuning uchun "to‘lov bo‘lmadi" demaymiz.
        await message.reply_text(
            "⚠️ To‘lov Telegram tomonidan qabul qilindi, "
            "ammo Veritas hisobini yangilashda xato yuz berdi.\n"
            "Super Egaga murojaat qiling."
        )
        return

    balance = get_cabinet_balance(
        user.id
    )

    await message.reply_text(
        "✅ To‘lov qabul qilindi!\n\n"
        f"➕ {payment.total_amount} ⭐\n"
        f"💰 Veritas balansingiz: "
        f"{balance} ⭐"
    )


# =========================================================
# PRIVATE *TOPUP COMMAND
# =========================================================

async def handle_private_topup(
    message,
    user,
    context,
    text
):
    parts = text.split()

    if len(parts) != 2:
        await message.reply_text(
            "⭐ Foydalanish:\n"
            "*topup 100"
        )
        return True

    try:
        amount = int(
            parts[1]
        )

    except ValueError:
        await message.reply_text(
            "⚠️ Stars miqdorini raqam bilan yozing.\n"
            "Masalan: *topup 100"
        )
        return True

    await create_stars_topup(
        message,
        user,
        context,
        amount
    )

    return True
    # =========================================================
# VERITAS v7 — 7-QISM
# V7 SUBSCRIPTION SYSTEM
# =========================================================


# =========================================================
# SUBSCRIPTION HELPERS
# =========================================================

def get_v7_price():
    return get_int_setting(
        "v7_price",
        DEFAULT_V7_PRICE
    )


def get_v7_days():
    return get_int_setting(
        "v7_days",
        DEFAULT_V7_DAYS
    )


def subscription_keyboard(chat_id):
    price = get_v7_price()
    days = get_v7_days()

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    f"💎 V7 — {price} ⭐ / {days} kun",
                    callback_data=f"sub:buy:{chat_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    "📊 Holatini tekshirish",
                    callback_data=f"sub:status:{chat_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    "⬅️ Kabinet",
                    callback_data="cabinet:home"
                )
            ],
        ]
    )


def can_manage_group_subscription(
    user_id,
    chat_id
):
    if is_super_owner_id(user_id):
        return True

    return is_group_owner(
        chat_id,
        user_id
    )


# =========================================================
# SUBSCRIPTION STATUS
# =========================================================

def subscription_status_text(chat_id):
    group = get_group(chat_id)

    if not group:
        return (
            "❌ Guruh Veritas bazasidan topilmadi."
        )

    plan = refresh_group_plan(chat_id)

    title = (
        group["title"]
        or str(chat_id)
    )

    if group["free_v7"]:
        return (
            f"👥 {title}\n\n"
            "💎 VERITAS V7\n"
            "🎁 Bepul V7 ruxsati faol.\n\n"
            "Bu guruhdan avtomatik "
            "obuna to‘lovi olinmaydi."
        )

    subscription_expires = db_to_datetime(
        group["subscription_expires_at"]
    )

    if (
        subscription_expires
        and subscription_expires > utc_now()
    ):
        return (
            f"👥 {title}\n\n"
            "💎 VERITAS V7\n"
            "✅ Obuna faol.\n"
            f"📅 Tugash: "
            f"{subscription_expires.strftime('%Y-%m-%d %H:%M UTC')}"
        )

    demo_expires = db_to_datetime(
        group["demo_expires_at"]
    )

    if (
        demo_expires
        and demo_expires > utc_now()
    ):
        return (
            f"👥 {title}\n\n"
            "🎁 V7 DEMO FAOL\n"
            f"📅 Demo tugashi: "
            f"{demo_expires.strftime('%Y-%m-%d %H:%M UTC')}\n\n"
            f"💎 Keyingi V7 muddati: "
            f"{get_v7_price()} ⭐ / "
            f"{get_v7_days()} kun"
        )

    return (
        f"👥 {title}\n\n"
        "🆓 VERITAS V6 FREE\n"
        "V7 demo/obuna muddati tugagan.\n\n"
        "V6 asosiy funksiyalari ishlashda davom etadi.\n"
        f"💎 V7: {get_v7_price()} ⭐ / "
        f"{get_v7_days()} kun"
    )


# =========================================================
# BUY / EXTEND V7
# =========================================================

def buy_v7_subscription(
    user_id,
    chat_id
):
    group = get_group(chat_id)

    if not group:
        return (
            False,
            "❌ Guruh Veritas bazasidan topilmadi."
        )

    if not can_manage_group_subscription(
        user_id,
        chat_id
    ):
        return (
            False,
            "⛔ Bu guruh obunasini boshqarish "
            "uchun ruxsatingiz yo‘q."
        )

    # Bepul V7 bo‘lsa pul yechmaymiz.
    if group["free_v7"]:
        return (
            False,
            "🎁 Bu guruhga bepul V7 ruxsati berilgan."
        )

    price = get_v7_price()
    days = get_v7_days()

    if price < 1 or days < 1:
        return (
            False,
            "⚠️ V7 tarif sozlamasi noto‘g‘ri."
        )

    cabinet = get_user_cabinet(user_id)

    if not cabinet:
        return (
            False,
            "❌ Shaxsiy Veritas kabinetingiz topilmadi."
        )

    current_balance = int(
        cabinet["cabinet_balance"]
    )

    if current_balance < price:
        return (
            False,
            (
                "⭐ Kabinet balansida mablag‘ yetarli emas.\n\n"
                f"Kerak: {price} ⭐\n"
                f"Mavjud: {current_balance} ⭐\n\n"
                f"Balansni to‘ldirish uchun:\n"
                f"*topup {price}"
            )
        )

    now = utc_now()

    old_expiry = db_to_datetime(
        group["subscription_expires_at"]
    )

    # Faol pullik obuna mavjud bo‘lsa,
    # yangi muddat uning oxiridan qo‘shiladi.
    if old_expiry and old_expiry > now:
        start_from = old_expiry
    else:
        start_from = now

    new_expiry = (
        start_from
        + timedelta(days=days)
    )

    try:
        cursor.execute("BEGIN")

        # Balansdan yechamiz.
        cursor.execute(
            """
            UPDATE users
            SET cabinet_balance =
                cabinet_balance - ?
            WHERE user_id = ?
              AND cabinet_balance >= ?
            """,
            (
                price,
                user_id,
                price
            )
        )

        if cursor.rowcount != 1:
            db.rollback()

            return (
                False,
                "⭐ Kabinet balansida mablag‘ yetarli emas."
            )

        # Guruhni V7 qilamiz.
        cursor.execute(
            """
            UPDATE groups
            SET
                plan = ?,
                subscription_expires_at = ?,
                updated_at = ?
            WHERE chat_id = ?
            """,
            (
                PREMIUM_PLAN,
                datetime_to_db(new_expiry),
                datetime_to_db(now),
                chat_id
            )
        )

        # Tranzaksiya jurnali.
        add_transaction(
            user_id=user_id,
            amount=-price,
            transaction_type="v7_subscription",
            description=(
                f"V7 obuna: {chat_id}, "
                f"{days} kun"
            ),
            created_by=user_id
        )

        db.commit()

    except Exception as error:
        db.rollback()

        print(
            "SUBSCRIPTION ERROR:",
            repr(error)
        )

        return (
            False,
            "❌ V7 obunasini faollashtirishda xato yuz berdi."
        )

    add_audit_log(
        actor_id=user_id,
        action="v7_subscription_purchased",
        target_user_id=user_id,
        target_chat_id=chat_id,
        details=(
            f"{price} Stars / {days} kun. "
            f"Tugash: {datetime_to_db(new_expiry)}"
        )
    )

    return (
        True,
        (
            "✅ VERITAS V7 FAOLLASHTIRILDI\n\n"
            f"💳 To‘lov: {price} ⭐\n"
            f"📅 Muddat: {days} kun\n"
            f"⏳ Tugash: "
            f"{new_expiry.strftime('%Y-%m-%d %H:%M UTC')}\n\n"
            f"⭐ Qolgan balans: "
            f"{get_cabinet_balance(user_id)}"
        )
    )


# =========================================================
# USER GROUP SUBSCRIPTION MENU
# =========================================================

def subscription_groups_keyboard(user_id):
    if is_super_owner_id(user_id):
        cursor.execute(
            """
            SELECT chat_id, title
            FROM groups
            WHERE active = 1
            ORDER BY created_at DESC
            LIMIT 50
            """
        )
    else:
        cursor.execute(
            """
            SELECT chat_id, title
            FROM groups
            WHERE owner_id = ?
              AND active = 1
            ORDER BY created_at DESC
            LIMIT 50
            """,
            (user_id,)
        )

    rows = cursor.fetchall()

    keyboard = []

    for row in rows:
        plan = get_effective_plan(
            row["chat_id"]
        )

        icon = (
            "💎"
            if plan == PREMIUM_PLAN
            else "🆓"
        )

        title = (
            row["title"]
            or str(row["chat_id"])
        )

        # Telegram callback_data limiti sabab
        # faqat ID saqlaymiz.
        keyboard.append(
            [
                InlineKeyboardButton(
                    f"{icon} {title[:35]}",
                    callback_data=(
                        f"sub:open:{row['chat_id']}"
                    )
                )
            ]
        )

    keyboard.append(
        [
            InlineKeyboardButton(
                "⬅️ Kabinet",
                callback_data="cabinet:home"
            )
        ]
    )

    return InlineKeyboardMarkup(keyboard)


# =========================================================
# SUBSCRIPTION CALLBACK
# =========================================================

async def subscription_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query

    if not query:
        return

    user = query.from_user

    if not user:
        return

    data = query.data or ""

    if not data.startswith("sub:"):
        return

    await query.answer()

    register_or_update_user(user)

    parts = data.split(":")

    # ---------------------------------------------
    # GROUP LIST
    # ---------------------------------------------

    if data == "sub:list":
        await query.edit_message_text(
            "💎 V7 OBUNA\n\n"
            "Guruhni tanlang:",
            reply_markup=(
                subscription_groups_keyboard(
                    user.id
                )
            )
        )
        return

    if len(parts) != 3:
        return

    action = parts[1]

    try:
        chat_id = int(parts[2])
    except ValueError:
        return

    # Faqat o‘z guruhi yoki Super Ega.
    if not can_manage_group_subscription(
        user.id,
        chat_id
    ):
        await query.answer(
            "⛔ Bu guruhga ruxsatingiz yo‘q.",
            show_alert=True
        )
        return

    # ---------------------------------------------
    # OPEN / STATUS
    # ---------------------------------------------

    if action in (
        "open",
        "status",
    ):
        await query.edit_message_text(
            subscription_status_text(
                chat_id
            ),
            reply_markup=subscription_keyboard(
                chat_id
            )
        )
        return

    # ---------------------------------------------
    # BUY
    # ---------------------------------------------

    if action == "buy":
        success, result_text = (
            buy_v7_subscription(
                user.id,
                chat_id
            )
        )

        await query.edit_message_text(
            result_text,
            reply_markup=subscription_keyboard(
                chat_id
            )
        )

        return
        # =========================================================
# VERITAS v7 — 8-QISM
# V6 FREE MODERATION CORE
# =========================================================


# =========================================================
# TARGET HELPERS
# =========================================================

def target_from_reply(message):
    if not message:
        return None

    replied = message.reply_to_message

    if not replied:
        return None

    return replied.from_user


def target_label(user):
    if not user:
        return "Noma’lum"

    if user.username:
        return f"@{user.username}"

    return user.full_name or str(user.id)


# =========================================================
# MODERATION SAFETY
# =========================================================

async def moderation_target_allowed(
    message,
    target,
    chat,
    context
):
    if not target:
        await message.reply_text(
            "⚠️ Bu buyruqni foydalanuvchining "
            "xabariga reply qilib ishlating."
        )
        return False

    # Veritas botning o‘ziga amal qilinmaydi.
    try:
        bot_user = await context.bot.get_me()

        if target.id == bot_user.id:
            await message.reply_text(
                "⚠️ Veritas o‘zini moderatsiya qila olmaydi."
            )
            return False

    except Exception:
        pass

    # Ikki Super Ega doim himoyalangan.
    if is_protected_super_owner(
        target.id
    ):
        await message.reply_text(
            "👑 Super Ega Veritas moderatsiyasidan "
            "himoyalangan."
        )
        return False

    # Telegram guruh egasini Veritas orqali
    # ban/mute/kick qilmaymiz.
    try:
        member = await context.bot.get_chat_member(
            chat.id,
            target.id
        )

        if member.status == "creator":
            await message.reply_text(
                "⛔ Telegram guruh egasiga "
                "bu amalni qo‘llab bo‘lmaydi."
            )
            return False

    except Exception:
        # Telegram keyinroq aniq xato qaytaradi.
        pass

    return True


# =========================================================
# WARN
# =========================================================

async def command_warn(
    message,
    user,
    chat,
    context
):
    if not await admin_required(
        message,
        user,
        chat,
        context
    ):
        return

    target = target_from_reply(
        message
    )

    if not await moderation_target_allowed(
        message,
        target,
        chat,
        context
    ):
        return

    current = get_warn_count(
        chat.id,
        target.id
    )

    new_count = current + 1

    cursor.execute(
        """
        INSERT INTO warnings (
            chat_id,
            user_id,
            warns
        )
        VALUES (?, ?, ?)

        ON CONFLICT(chat_id, user_id)
        DO UPDATE SET
            warns = excluded.warns
        """,
        (
            chat.id,
            target.id,
            new_count
        )
    )

    db.commit()

    actor_id = (
        user.id
        if user
        else sender_channel_id(message)
    )

    add_audit_log(
        actor_id=actor_id,
        action="warn",
        target_user_id=target.id,
        target_chat_id=chat.id,
        details=f"Warn {new_count}/3"
    )

    # ---------------------------------------------
    # 3/3 = BAN
    # ---------------------------------------------

    if new_count >= 3:
        try:
            await context.bot.ban_chat_member(
                chat_id=chat.id,
                user_id=target.id
            )

        except Exception as error:
            print(
                "AUTO BAN ERROR:",
                repr(error)
            )

            await message.reply_text(
                f"⚠️ {target_label(target)} — 3/3 ogohlantirish.\n"
                "Lekin avtomatik ban bajarilmadi.\n"
                "Botning Ban users huquqini tekshiring."
            )
            return

        clear_warns(
            chat.id,
            target.id
        )

        add_audit_log(
            actor_id=actor_id,
            action="auto_ban_3_warns",
            target_user_id=target.id,
            target_chat_id=chat.id,
            details="3/3 warn sababli ban."
        )

        await message.reply_text(
            f"⛔ {target_label(target)} ban qilindi.\n"
            "Sabab: 3/3 ogohlantirish."
        )
        return

    await message.reply_text(
        f"⚠️ {target_label(target)}\n"
        f"Ogohlantirish: {new_count}/3"
    )


# =========================================================
# UNWARN
# =========================================================

async def command_unwarn(
    message,
    user,
    chat,
    context
):
    if not await admin_required(
        message,
        user,
        chat,
        context
    ):
        return

    target = target_from_reply(
        message
    )

    if not target:
        await message.reply_text(
            "⚠️ *unwarn buyrug‘ini "
            "foydalanuvchi xabariga reply qiling."
        )
        return

    current = get_warn_count(
        chat.id,
        target.id
    )

    if current <= 0:
        await message.reply_text(
            f"ℹ️ {target_label(target)} da "
            "ogohlantirish yo‘q."
        )
        return

    new_count = current - 1

    if new_count == 0:
        clear_warns(
            chat.id,
            target.id
        )

    else:
        cursor.execute(
            """
            UPDATE warnings
            SET warns = ?
            WHERE chat_id = ?
              AND user_id = ?
            """,
            (
                new_count,
                chat.id,
                target.id
            )
        )

        db.commit()

    actor_id = (
        user.id
        if user
        else sender_channel_id(message)
    )

    add_audit_log(
        actor_id=actor_id,
        action="unwarn",
        target_user_id=target.id,
        target_chat_id=chat.id,
        details=f"Warn {new_count}/3"
    )

    await message.reply_text(
        f"✅ {target_label(target)}\n"
        f"Ogohlantirish: {new_count}/3"
    )


# =========================================================
# CLEAR WARNS
# =========================================================

async def command_clearwarns(
    message,
    user,
    chat,
    context
):
    if not await admin_required(
        message,
        user,
        chat,
        context
    ):
        return

    target = target_from_reply(
        message
    )

    if not target:
        await message.reply_text(
            "⚠️ *clearwarns buyrug‘ini "
            "foydalanuvchi xabariga reply qiling."
        )
        return

    clear_warns(
        chat.id,
        target.id
    )

    actor_id = (
        user.id
        if user
        else sender_channel_id(message)
    )

    add_audit_log(
        actor_id=actor_id,
        action="clearwarns",
        target_user_id=target.id,
        target_chat_id=chat.id
    )

    await message.reply_text(
        f"✅ {target_label(target)} ning "
        "barcha ogohlantirishlari tozalandi."
    )


# =========================================================
# MUTE
# =========================================================

async def command_mute(
    message,
    user,
    chat,
    context
):
    if not await admin_required(
        message,
        user,
        chat,
        context
    ):
        return

    target = target_from_reply(
        message
    )

    if not await moderation_target_allowed(
        message,
        target,
        chat,
        context
    ):
        return

    try:
        await context.bot.restrict_chat_member(
            chat_id=chat.id,
            user_id=target.id,
            permissions=ChatPermissions(
                can_send_messages=False
            )
        )

    except Exception as error:
        print(
            "MUTE ERROR:",
            repr(error)
        )

        await message.reply_text(
            "❌ Mute bajarilmadi.\n"
            "Botning Restrict members "
            "huquqini tekshiring."
        )
        return

    actor_id = (
        user.id
        if user
        else sender_channel_id(message)
    )

    add_audit_log(
        actor_id=actor_id,
        action="mute",
        target_user_id=target.id,
        target_chat_id=chat.id
    )

    await message.reply_text(
        f"🔇 {target_label(target)} mute qilindi."
    )


# =========================================================
# UNMUTE
# =========================================================

async def command_unmute(
    message,
    user,
    chat,
    context
):
    if not await admin_required(
        message,
        user,
        chat,
        context
    ):
        return

    target = target_from_reply(
        message
    )

    if not target:
        await message.reply_text(
            "⚠️ *unmute buyrug‘ini "
            "foydalanuvchi xabariga reply qiling."
        )
        return

    try:
        await context.bot.restrict_chat_member(
            chat_id=chat.id,
            user_id=target.id,
            permissions=ChatPermissions(
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
                can_invite_users=True
            )
        )

    except Exception as error:
        print(
            "UNMUTE ERROR:",
            repr(error)
        )

        await message.reply_text(
            "❌ Unmute bajarilmadi.\n"
            "Botning Restrict members "
            "huquqini tekshiring."
        )
        return

    actor_id = (
        user.id
        if user
        else sender_channel_id(message)
    )

    add_audit_log(
        actor_id=actor_id,
        action="unmute",
        target_user_id=target.id,
        target_chat_id=chat.id
    )

    await message.reply_text(
        f"🔊 {target_label(target)} mute holatidan chiqarildi."
    )


# =========================================================
# KICK
# =========================================================

async def command_kick(
    message,
    user,
    chat,
    context
):
    if not await admin_required(
        message,
        user,
        chat,
        context
    ):
        return

    target = target_from_reply(
        message
    )

    if not await moderation_target_allowed(
        message,
        target,
        chat,
        context
    ):
        return

    try:
        # Ban + darhol unban = guruhdan chiqarish,
        # keyin yana qo‘shila oladi.
        await context.bot.ban_chat_member(
            chat_id=chat.id,
            user_id=target.id
        )

        await context.bot.unban_chat_member(
            chat_id=chat.id,
            user_id=target.id,
            only_if_banned=True
        )

    except Exception as error:
        print(
            "KICK ERROR:",
            repr(error)
        )

        await message.reply_text(
            "❌ Kick bajarilmadi.\n"
            "Botning Ban users huquqini tekshiring."
        )
        return

    actor_id = (
        user.id
        if user
        else sender_channel_id(message)
    )

    add_audit_log(
        actor_id=actor_id,
        action="kick",
        target_user_id=target.id,
        target_chat_id=chat.id
    )

    await message.reply_text(
        f"👢 {target_label(target)} guruhdan chiqarildi."
    )


# =========================================================
# BAN
# =========================================================

async def command_ban(
    message,
    user,
    chat,
    context
):
    if not await admin_required(
        message,
        user,
        chat,
        context
    ):
        return

    target = target_from_reply(
        message
    )

    if not await moderation_target_allowed(
        message,
        target,
        chat,
        context
    ):
        return

    try:
        await context.bot.ban_chat_member(
            chat_id=chat.id,
            user_id=target.id
        )

    except Exception as error:
        print(
            "BAN ERROR:",
            repr(error)
        )

        await message.reply_text(
            "❌ Ban bajarilmadi.\n"
            "Botning Ban users huquqini tekshiring."
        )
        return

    actor_id = (
        user.id
        if user
        else sender_channel_id(message)
    )

    add_audit_log(
        actor_id=actor_id,
        action="ban",
        target_user_id=target.id,
        target_chat_id=chat.id
    )

    await message.reply_text(
        f"⛔ {target_label(target)} ban qilindi."
    )


# =========================================================
# UNBAN
# Reply yoki ID orqali
# =========================================================

async def command_unban(
    message,
    user,
    chat,
    context,
    text
):
    if not await admin_required(
        message,
        user,
        chat,
        context
    ):
        return

    target = target_from_reply(
        message
    )

    target_id = None
    target_name = None

    if target:
        target_id = target.id
        target_name = target_label(
            target
        )

    else:
        parts = text.split()

        if len(parts) != 2:
            await message.reply_text(
                "⚠️ Foydalanish:\n"
                "• xabarga reply: *unban\n"
                "yoki\n"
                "• *unban USER_ID"
            )
            return

        try:
            target_id = int(
                parts[1]
            )

            target_name = str(
                target_id
            )

        except ValueError:
            await message.reply_text(
                "⚠️ USER_ID raqam bo‘lishi kerak."
            )
            return

    try:
        await context.bot.unban_chat_member(
            chat_id=chat.id,
            user_id=target_id,
            only_if_banned=True
        )

    except Exception as error:
        print(
            "UNBAN ERROR:",
            repr(error)
        )

        await message.reply_text(
            "❌ Unban bajarilmadi.\n"
            "Botning Ban users huquqini tekshiring."
        )
        return

    clear_warns(
        chat.id,
        target_id
    )

    actor_id = (
        user.id
        if user
        else sender_channel_id(message)
    )

    add_audit_log(
        actor_id=actor_id,
        action="unban",
        target_user_id=target_id,
        target_chat_id=chat.id
    )

    await message.reply_text(
        f"✅ {target_name} ban holatidan chiqarildi."
    )


# =========================================================
# DELETE MESSAGE
# =========================================================

async def command_delete(
    message,
    user,
    chat,
    context
):
    if not await admin_required(
        message,
        user,
        chat,
        context
    ):
        return

    replied = message.reply_to_message

    if not replied:
        await message.reply_text(
            "⚠️ O‘chiriladigan xabarga reply qilib "
            "*del yozing."
        )
        return

    try:
        # Avval reply qilingan xabarni o‘chiramiz.
        await context.bot.delete_message(
            chat_id=chat.id,
            message_id=replied.message_id
        )

        # Keyin *del buyrug‘ining o‘zini ham
        # imkon bo‘lsa o‘chiramiz.
        try:
            await context.bot.delete_message(
                chat_id=chat.id,
                message_id=message.message_id
            )
        except Exception:
            pass

    except Exception as error:
        print(
            "DELETE ERROR:",
            repr(error)
        )

        await message.reply_text(
            "❌ Xabar o‘chirilmadi.\n"
            "Botning Delete messages "
            "huquqini tekshiring."
        )
        return

    actor_id = (
        user.id
        if user
        else sender_channel_id(message)
    )

    add_audit_log(
        actor_id=actor_id,
        action="delete_message",
        target_chat_id=chat.id,
        details=(
            f"Message ID: {replied.message_id}"
        )
    )


# =========================================================
# MODERATION COMMAND ROUTER
# =========================================================

async def handle_moderation_command(
    message,
    user,
    chat,
    context,
    text
):
    command = (
        text.split()[0].lower()
        if text
        else ""
    )

    if command == "*warn":
        await command_warn(
            message,
            user,
            chat,
            context
        )
        return True

    if command == "*unwarn":
        await command_unwarn(
            message,
            user,
            chat,
            context
        )
        return True

    if command == "*clearwarns":
        await command_clearwarns(
            message,
            user,
            chat,
            context
        )
        return True

    if command == "*mute":
        await command_mute(
            message,
            user,
            chat,
            context
        )
        return True

    if command == "*unmute":
        await command_unmute(
            message,
            user,
            chat,
            context
        )
        return True

    if command == "*kick":
        await command_kick(
            message,
            user,
            chat,
            context
        )
        return True

    if command == "*ban":
        await command_ban(
            message,
            user,
            chat,
            context
        )
        return True

    if command == "*unban":
        await command_unban(
            message,
            user,
            chat,
            context,
            text
        )
        return True

    if command == "*del":
        await command_delete(
            message,
            user,
            chat,
            context
        )
        return True

    return False
    # =========================================================
# VERITAS v7 — 9-QISM
# APPROVE + LINKS + BLACKLIST + LOCKS
# =========================================================


# =========================================================
# APPROVE
# =========================================================

async def command_approve(
    message,
    user,
    chat,
    context
):
    if not await admin_required(
        message, user, chat, context
    ):
        return

    target = target_from_reply(message)

    if not target:
        await message.reply_text(
            "⚠️ Foydalanuvchi xabariga reply qilib "
            "*approve yozing."
        )
        return

    cursor.execute(
        """
        INSERT OR IGNORE INTO approved_users (
            chat_id,
            user_id
        )
        VALUES (?, ?)
        """,
        (chat.id, target.id)
    )

    db.commit()

    await message.reply_text(
        f"✅ {target_label(target)} approved ro‘yxatiga qo‘shildi.\n"
        "Veritas himoyalari unga qo‘llanmaydi."
    )


# =========================================================
# UNAPPROVE
# =========================================================

async def command_unapprove(
    message,
    user,
    chat,
    context
):
    if not await admin_required(
        message, user, chat, context
    ):
        return

    target = target_from_reply(message)

    if not target:
        await message.reply_text(
            "⚠️ Foydalanuvchi xabariga reply qilib "
            "*unapprove yozing."
        )
        return

    cursor.execute(
        """
        DELETE FROM approved_users
        WHERE chat_id = ?
          AND user_id = ?
        """,
        (chat.id, target.id)
    )

    db.commit()

    await message.reply_text(
        f"✅ {target_label(target)} approved "
        "ro‘yxatidan chiqarildi."
    )


# =========================================================
# APPROVED LIST
# =========================================================

async def command_approved(
    message,
    chat
):
    cursor.execute(
        """
        SELECT user_id
        FROM approved_users
        WHERE chat_id = ?
        ORDER BY user_id
        """,
        (chat.id,)
    )

    rows = cursor.fetchall()

    if not rows:
        await message.reply_text(
            "📋 Approved ro‘yxati bo‘sh."
        )
        return

    lines = [
        "✅ APPROVED FOYDALANUVCHILAR",
        ""
    ]

    for row in rows:
        lines.append(
            f"• {row['user_id']}"
        )

    await message.reply_text(
        "\n".join(lines)
    )


# =========================================================
# LINKS ON / OFF
# =========================================================

async def command_links(
    message,
    user,
    chat,
    context,
    text
):
    if not await admin_required(
        message, user, chat, context
    ):
        return

    parts = text.lower().split()

    if len(parts) != 2 or parts[1] not in (
        "on",
        "off",
    ):
        ensure_settings(chat.id)

        cursor.execute(
            """
            SELECT link_block
            FROM settings
            WHERE chat_id = ?
            """,
            (chat.id,)
        )

        row = cursor.fetchone()

        status = (
            "ON"
            if row and row["link_block"]
            else "OFF"
        )

        await message.reply_text(
            f"🔗 Link himoyasi: {status}\n\n"
            "*links on\n"
            "*links off"
        )
        return

    enabled = (
        1
        if parts[1] == "on"
        else 0
    )

    ensure_settings(chat.id)

    cursor.execute(
        """
        UPDATE settings
        SET link_block = ?
        WHERE chat_id = ?
        """,
        (enabled, chat.id)
    )

    db.commit()

    await message.reply_text(
        "🔗 Link himoyasi "
        + (
            "yoqildi. ✅"
            if enabled
            else "o‘chirildi. ⭕"
        )
    )


# =========================================================
# BLACKLIST
# =========================================================

async def command_blacklist(
    message,
    user,
    chat,
    context,
    text
):
    if not await admin_required(
        message, user, chat, context
    ):
        return

    parts = text.split(
        maxsplit=1
    )

    if len(parts) != 2:
        await message.reply_text(
            "⚠️ Foydalanish:\n"
            "*blacklist so‘z"
        )
        return

    word = parts[1].strip().lower()

    if not word:
        return

    cursor.execute(
        """
        INSERT OR IGNORE INTO blacklist (
            chat_id,
            word
        )
        VALUES (?, ?)
        """,
        (chat.id, word)
    )

    db.commit()

    await message.reply_text(
        f"🚫 Blacklistga qo‘shildi:\n{word}"
    )


async def command_unblacklist(
    message,
    user,
    chat,
    context,
    text
):
    if not await admin_required(
        message, user, chat, context
    ):
        return

    parts = text.split(
        maxsplit=1
    )

    if len(parts) != 2:
        await message.reply_text(
            "⚠️ Foydalanish:\n"
            "*unblacklist so‘z"
        )
        return

    word = parts[1].strip().lower()

    cursor.execute(
        """
        DELETE FROM blacklist
        WHERE chat_id = ?
          AND word = ?
        """,
        (chat.id, word)
    )

    db.commit()

    await message.reply_text(
        f"✅ Blacklistdan olib tashlandi:\n{word}"
    )


async def command_blacklists(
    message,
    chat
):
    cursor.execute(
        """
        SELECT word
        FROM blacklist
        WHERE chat_id = ?
        ORDER BY word
        """,
        (chat.id,)
    )

    rows = cursor.fetchall()

    if not rows:
        await message.reply_text(
            "🚫 Blacklist bo‘sh."
        )
        return

    words = [
        row["word"]
        for row in rows
    ]

    await message.reply_text(
        "🚫 BLACKLIST\n\n"
        + "\n".join(
            f"• {word}"
            for word in words
        )
    )


# =========================================================
# LOCK / UNLOCK
# =========================================================

VALID_LOCKS = {
    "links",
    "photo",
    "video",
    "sticker",
    "animation",
    "document",
    "voice",
    "audio",
}


async def command_lock(
    message,
    user,
    chat,
    context,
    text
):
    if not await admin_required(
        message, user, chat, context
    ):
        return

    parts = text.lower().split()

    if len(parts) != 2:
        await message.reply_text(
            "🔒 Foydalanish:\n"
            "*lock photo\n"
            "*lock video\n"
            "*lock sticker\n"
            "*lock links"
        )
        return

    lock_type = parts[1]

    if lock_type not in VALID_LOCKS:
        await message.reply_text(
            "⚠️ Noto‘g‘ri lock turi.\n\n"
            + ", ".join(
                sorted(VALID_LOCKS)
            )
        )
        return

    cursor.execute(
        """
        INSERT OR IGNORE INTO locks (
            chat_id,
            lock_type
        )
        VALUES (?, ?)
        """,
        (chat.id, lock_type)
    )

    db.commit()

    await message.reply_text(
        f"🔒 {lock_type} bloklandi."
    )


async def command_unlock(
    message,
    user,
    chat,
    context,
    text
):
    if not await admin_required(
        message, user, chat, context
    ):
        return

    parts = text.lower().split()

    if len(parts) != 2:
        await message.reply_text(
            "🔓 Foydalanish:\n"
            "*unlock photo"
        )
        return

    lock_type = parts[1]

    if lock_type not in VALID_LOCKS:
        await message.reply_text(
            "⚠️ Noto‘g‘ri lock turi."
        )
        return

    cursor.execute(
        """
        DELETE FROM locks
        WHERE chat_id = ?
          AND lock_type = ?
        """,
        (chat.id, lock_type)
    )

    db.commit()

    await message.reply_text(
        f"🔓 {lock_type} blokdan chiqarildi."
    )


async def command_locks(
    message,
    chat
):
    locks = get_locks(
        chat.id
    )

    if not locks:
        await message.reply_text(
            "🔓 Hozir hech narsa lock qilinmagan."
        )
        return

    await message.reply_text(
        "🔒 LOCKLAR\n\n"
        + "\n".join(
            f"• {item}"
            for item in locks
        )
    )


# =========================================================
# AUTOMATIC LINK PROTECTION
# =========================================================

async def check_link_protection(
    message,
    user,
    chat,
    context
):
    text = (
        message.text
        or message.caption
        or ""
    )

    if not text:
        return False

    ensure_settings(chat.id)

    cursor.execute(
        """
        SELECT link_block
        FROM settings
        WHERE chat_id = ?
        """,
        (chat.id,)
    )

    row = cursor.fetchone()

    settings_link_block = bool(
        row and row["link_block"]
    )

    locks = get_locks(
        chat.id
    )

    link_locked = (
        "links" in locks
    )

    if not (
        settings_link_block
        or link_locked
    ):
        return False

    if not contains_link(text):
        return False

    if await is_protection_bypassed(
        message,
        user,
        chat,
        context
    ):
        return False

    try:
        await message.delete()

    except Exception as error:
        print(
            "LINK DELETE ERROR:",
            repr(error)
        )
        return False

    return True


# =========================================================
# AUTOMATIC BLACKLIST PROTECTION
# =========================================================

async def check_blacklist_protection(
    message,
    user,
    chat,
    context
):
    text = (
        message.text
        or message.caption
        or ""
    ).lower()

    if not text:
        return False

    if await is_protection_bypassed(
        message,
        user,
        chat,
        context
    ):
        return False

    cursor.execute(
        """
        SELECT word
        FROM blacklist
        WHERE chat_id = ?
        """,
        (chat.id,)
    )

    words = cursor.fetchall()

    for row in words:
        word = (
            row["word"]
            or ""
        ).strip().lower()

        if word and word in text:
            try:
                await message.delete()

            except Exception as error:
                print(
                    "BLACKLIST DELETE ERROR:",
                    repr(error)
                )
                return False

            return True

    return False


# =========================================================
# AUTOMATIC MEDIA LOCK
# =========================================================

async def check_media_lock(
    message,
    user,
    chat,
    context
):
    locks = set(
        get_locks(chat.id)
    )

    if not locks:
        return False

    media_type = None

    if message.photo:
        media_type = "photo"

    elif message.video:
        media_type = "video"

    elif message.sticker:
        media_type = "sticker"

    elif message.animation:
        media_type = "animation"

    elif message.document:
        media_type = "document"

    elif message.voice:
        media_type = "voice"

    elif message.audio:
        media_type = "audio"

    if not media_type:
        return False

    if media_type not in locks:
        return False

    if await is_protection_bypassed(
        message,
        user,
        chat,
        context
    ):
        return False

    try:
        await message.delete()

    except Exception as error:
        print(
            "MEDIA LOCK ERROR:",
            repr(error)
        )
        return False

    return True


# =========================================================
# PROTECTION COMMAND ROUTER
# =========================================================

async def handle_protection_command(
    message,
    user,
    chat,
    context,
    text
):
    command = (
        text.split()[0].lower()
        if text
        else ""
    )

    if command == "*approve":
        await command_approve(
            message, user, chat, context
        )
        return True

    if command == "*unapprove":
        await command_unapprove(
            message, user, chat, context
        )
        return True

    if command == "*approved":
        await command_approved(
            message, chat
        )
        return True

    if command == "*links":
        await command_links(
            message, user, chat, context, text
        )
        return True

    if command == "*blacklist":
        await command_blacklist(
            message, user, chat, context, text
        )
        return True

    if command == "*unblacklist":
        await command_unblacklist(
            message, user, chat, context, text
        )
        return True

    if command == "*blacklists":
        await command_blacklists(
            message, chat
        )
        return True

    if command == "*lock":
        await command_lock(
            message, user, chat, context, text
        )
        return True

    if command == "*unlock":
        await command_unlock(
            message, user, chat, context, text
        )
        return True

    if command == "*locks":
        await command_locks(
            message, chat
        )
        return True

    return False
    # =========================================================
# VERITAS v7 — 10-QISM
# ANTIFLOOD + REPORTS + FILTERS
# =========================================================


# =========================================================
# ANTIFLOOD SETTINGS
# =========================================================

async def command_antiflood(
    message,
    user,
    chat,
    context,
    text
):
    if not await admin_required(
        message, user, chat, context
    ):
        return

    ensure_settings(chat.id)

    parts = text.lower().split()

    if len(parts) != 2 or parts[1] not in ("on", "off"):
        cursor.execute(
            """
            SELECT antiflood, flood_limit
            FROM settings
            WHERE chat_id = ?
            """,
            (chat.id,)
        )

        row = cursor.fetchone()

        enabled = bool(
            row and row["antiflood"]
        )

        limit = (
            row["flood_limit"]
            if row
            else 5
        )

        await message.reply_text(
            "🌊 ANTI-FLOOD\n\n"
            f"Holat: {'ON ✅' if enabled else 'OFF ⭕'}\n"
            f"Limit: {limit} xabar / 5 soniya\n\n"
            "*antiflood on\n"
            "*antiflood off\n"
            "*flood 5"
        )
        return

    enabled = 1 if parts[1] == "on" else 0

    cursor.execute(
        """
        UPDATE settings
        SET antiflood = ?
        WHERE chat_id = ?
        """,
        (enabled, chat.id)
    )

    db.commit()

    if not enabled:
        cursor.execute(
            """
            DELETE FROM flood_data
            WHERE chat_id = ?
            """,
            (chat.id,)
        )
        db.commit()

    await message.reply_text(
        "🌊 Anti-flood "
        + (
            "yoqildi. ✅"
            if enabled
            else "o‘chirildi. ⭕"
        )
    )


# =========================================================
# FLOOD LIMIT
# =========================================================

async def command_flood(
    message,
    user,
    chat,
    context,
    text
):
    if not await admin_required(
        message, user, chat, context
    ):
        return

    parts = text.split()

    if len(parts) != 2:
        await message.reply_text(
            "⚠️ Foydalanish:\n"
            "*flood 5\n\n"
            "Limit: 3 dan 20 gacha."
        )
        return

    try:
        limit = int(parts[1])
    except ValueError:
        await message.reply_text(
            "⚠️ Flood limiti raqam bo‘lishi kerak."
        )
        return

    if limit < 3 or limit > 20:
        await message.reply_text(
            "⚠️ Limit 3 dan 20 gacha bo‘lishi kerak."
        )
        return

    ensure_settings(chat.id)

    cursor.execute(
        """
        UPDATE settings
        SET flood_limit = ?
        WHERE chat_id = ?
        """,
        (limit, chat.id)
    )

    cursor.execute(
        """
        DELETE FROM flood_data
        WHERE chat_id = ?
        """,
        (chat.id,)
    )

    db.commit()

    await message.reply_text(
        f"✅ Anti-flood limiti: "
        f"{limit} xabar / 5 soniya"
    )


# =========================================================
# AUTOMATIC ANTIFLOOD
# =========================================================

async def check_antiflood(
    message,
    user,
    chat,
    context
):
    if not user or user.is_bot:
        return False

    ensure_settings(chat.id)

    cursor.execute(
        """
        SELECT antiflood, flood_limit
        FROM settings
        WHERE chat_id = ?
        """,
        (chat.id,)
    )

    row = cursor.fetchone()

    if not row or not row["antiflood"]:
        return False

    if await is_protection_bypassed(
        message, user, chat, context
    ):
        return False

    limit = int(
        row["flood_limit"] or 5
    )

    now = time.time()

    cursor.execute(
        """
        SELECT count, last_time
        FROM flood_data
        WHERE chat_id = ?
          AND user_id = ?
        """,
        (chat.id, user.id)
    )

    flood_row = cursor.fetchone()

    if not flood_row:
        count = 1

    elif (
        now - float(flood_row["last_time"])
        > 5
    ):
        count = 1

    else:
        count = int(
            flood_row["count"]
        ) + 1

    cursor.execute(
        """
        INSERT INTO flood_data (
            chat_id,
            user_id,
            count,
            last_time
        )
        VALUES (?, ?, ?, ?)

        ON CONFLICT(chat_id, user_id)
        DO UPDATE SET
            count = excluded.count,
            last_time = excluded.last_time
        """,
        (
            chat.id,
            user.id,
            count,
            now
        )
    )

    db.commit()

    if count < limit:
        return False

    # Hisoblagichni qayta boshlaymiz.
    cursor.execute(
        """
        DELETE FROM flood_data
        WHERE chat_id = ?
          AND user_id = ?
        """,
        (chat.id, user.id)
    )

    db.commit()

    try:
        await context.bot.restrict_chat_member(
            chat_id=chat.id,
            user_id=user.id,
            permissions=ChatPermissions(
                can_send_messages=False
            )
        )

    except Exception as error:
        print(
            "ANTIFLOOD MUTE ERROR:",
            repr(error)
        )
        return False

    add_audit_log(
        actor_id=None,
        action="antiflood_mute",
        target_user_id=user.id,
        target_chat_id=chat.id,
        details=(
            f"{count} xabar / 5 soniya"
        )
    )

    await message.reply_text(
        f"🌊 {target_label(user)} anti-flood "
        "sababli mute qilindi."
    )

    return True


# =========================================================
# REPORT SETTINGS
# =========================================================

async def command_reports(
    message,
    user,
    chat,
    context,
    text
):
    if not await admin_required(
        message, user, chat, context
    ):
        return

    ensure_settings(chat.id)

    parts = text.lower().split()

    if len(parts) != 2 or parts[1] not in ("on", "off"):
        cursor.execute(
            """
            SELECT reports
            FROM settings
            WHERE chat_id = ?
            """,
            (chat.id,)
        )

        row = cursor.fetchone()

        enabled = bool(
            row and row["reports"]
        )

        await message.reply_text(
            "🚨 Report tizimi: "
            + (
                "ON ✅"
                if enabled
                else "OFF ⭕"
            )
            + "\n\n"
            "*reports on\n"
            "*reports off"
        )
        return

    enabled = 1 if parts[1] == "on" else 0

    cursor.execute(
        """
        UPDATE settings
        SET reports = ?
        WHERE chat_id = ?
        """,
        (enabled, chat.id)
    )

    db.commit()

    await message.reply_text(
        "🚨 Report tizimi "
        + (
            "yoqildi. ✅"
            if enabled
            else "o‘chirildi. ⭕"
        )
    )


# =========================================================
# REPORT
# =========================================================

async def command_report(
    message,
    user,
    chat,
    context
):
    ensure_settings(chat.id)

    cursor.execute(
        """
        SELECT reports
        FROM settings
        WHERE chat_id = ?
        """,
        (chat.id,)
    )

    row = cursor.fetchone()

    if not row or not row["reports"]:
        await message.reply_text(
            "ℹ️ Bu guruhda report tizimi o‘chirilgan."
        )
        return

    replied = message.reply_to_message

    if not replied:
        await message.reply_text(
            "⚠️ Shikoyat qilinadigan xabarga "
            "reply qilib *report yozing."
        )
        return

    target = replied.from_user

    if not target:
        await message.reply_text(
            "⚠️ Ushbu xabar egasini aniqlab bo‘lmadi."
        )
        return

    reporter = target_label(user)

    await message.reply_text(
        "🚨 REPORT\n\n"
        f"👤 Shikoyat qiluvchi: {reporter}\n"
        f"🎯 Xabar egasi: {target_label(target)}\n"
        f"🆔 User ID: {target.id}\n\n"
        "⚠️ Guruh administratorlari, "
        "ushbu xabarni tekshiring."
    )


# =========================================================
# SAVE FILTER
# =========================================================

async def command_filter(
    message,
    user,
    chat,
    context,
    text
):
    if not await admin_required(
        message, user, chat, context
    ):
        return

    parts = text.split(
        maxsplit=2
    )

    # ---------------------------------------------
    # MEDIA FILTER
    # Reply media + *filter keyword
    # ---------------------------------------------

    if message.reply_to_message:
        replied = message.reply_to_message

        media_type, file_id = (
            media_from_message(replied)
        )

        if media_type != "text":
            if len(parts) < 2:
                await message.reply_text(
                    "⚠️ Media filter:\n"
                    "Media xabariga reply qilib:\n"
                    "*filter kalitsoz"
                )
                return

            keyword = (
                parts[1]
                .strip()
                .lower()
            )

            caption = (
                replied.caption
                or ""
            )

            cursor.execute(
                """
                INSERT INTO chat_filters (
                    chat_id,
                    keyword,
                    response,
                    media_type,
                    file_id,
                    caption
                )
                VALUES (?, ?, '', ?, ?, ?)

                ON CONFLICT(chat_id, keyword)
                DO UPDATE SET
                    response = excluded.response,
                    media_type = excluded.media_type,
                    file_id = excluded.file_id,
                    caption = excluded.caption
                """,
                (
                    chat.id,
                    keyword,
                    media_type,
                    file_id,
                    caption
                )
            )

            db.commit()

            await message.reply_text(
                f"✅ Media filter saqlandi:\n"
                f"{keyword}"
            )
            return

    # ---------------------------------------------
    # TEXT FILTER
    # *filter hello Salom!
    # ---------------------------------------------

    if len(parts) < 3:
        await message.reply_text(
            "⚠️ Matn filter:\n"
            "*filter kalitsoz javob\n\n"
            "Media filter:\n"
            "Media xabariga reply qilib "
            "*filter kalitsoz"
        )
        return

    keyword = (
        parts[1]
        .strip()
        .lower()
    )

    response = parts[2].strip()

    if not keyword or not response:
        return

    cursor.execute(
        """
        INSERT INTO chat_filters (
            chat_id,
            keyword,
            response,
            media_type,
            file_id,
            caption
        )
        VALUES (?, ?, ?, 'text', '', '')

        ON CONFLICT(chat_id, keyword)
        DO UPDATE SET
            response = excluded.response,
            media_type = 'text',
            file_id = '',
            caption = ''
        """,
        (
            chat.id,
            keyword,
            response
        )
    )

    db.commit()

    await message.reply_text(
        f"✅ Filter saqlandi:\n{keyword}"
    )


# =========================================================
# FILTER LIST
# =========================================================

async def command_filters(
    message,
    chat
):
    cursor.execute(
        """
        SELECT keyword, media_type
        FROM chat_filters
        WHERE chat_id = ?
        ORDER BY keyword
        """,
        (chat.id,)
    )

    rows = cursor.fetchall()

    if not rows:
        await message.reply_text(
            "📋 Filterlar yo‘q."
        )
        return

    lines = [
        "🔎 FILTERLAR",
        ""
    ]

    for row in rows:
        media_type = (
            row["media_type"]
            or "text"
        )

        lines.append(
            f"• {row['keyword']} "
            f"[{media_type}]"
        )

    await message.reply_text(
        "\n".join(lines)
    )


# =========================================================
# STOP FILTER
# =========================================================

async def command_stop(
    message,
    user,
    chat,
    context,
    text
):
    if not await admin_required(
        message, user, chat, context
    ):
        return

    parts = text.split(
        maxsplit=1
    )

    if len(parts) != 2:
        await message.reply_text(
            "⚠️ Foydalanish:\n"
            "*stop kalitsoz"
        )
        return

    keyword = (
        parts[1]
        .strip()
        .lower()
    )

    cursor.execute(
        """
        DELETE FROM chat_filters
        WHERE chat_id = ?
          AND keyword = ?
        """,
        (chat.id, keyword)
    )

    deleted = cursor.rowcount

    db.commit()

    if deleted:
        await message.reply_text(
            f"✅ Filter o‘chirildi:\n{keyword}"
        )
    else:
        await message.reply_text(
            f"ℹ️ Filter topilmadi:\n{keyword}"
        )


# =========================================================
# STOP ALL FILTERS
# =========================================================

async def command_stopall(
    message,
    user,
    chat,
    context
):
    if not await admin_required(
        message, user, chat, context
    ):
        return

    cursor.execute(
        """
        DELETE FROM chat_filters
        WHERE chat_id = ?
        """,
        (chat.id,)
    )

    deleted = cursor.rowcount

    db.commit()

    await message.reply_text(
        f"✅ {deleted} ta filter o‘chirildi."
    )


# =========================================================
# AUTOMATIC FILTER RESPONSE
# =========================================================

async def check_saved_filters(
    message,
    chat,
    context
):
    text = (
        message.text
        or message.caption
        or ""
    ).lower()

    if not text:
        return False

    cursor.execute(
        """
        SELECT
            keyword,
            response,
            media_type,
            file_id,
            caption
        FROM chat_filters
        WHERE chat_id = ?
        ORDER BY LENGTH(keyword) DESC
        """,
        (chat.id,)
    )

    rows = cursor.fetchall()

    for row in rows:
        keyword = (
            row["keyword"]
            or ""
        ).lower()

        if not keyword:
            continue

        if keyword not in text:
            continue

        try:
            await send_saved_filter(
                message=message,
                context=context,
                media_type=(
                    row["media_type"]
                    or "text"
                ),
                file_id=(
                    row["file_id"]
                    or ""
                ),
                response=(
                    row["response"]
                    or ""
                ),
                caption=(
                    row["caption"]
                    or ""
                )
            )

        except Exception as error:
            print(
                "FILTER SEND ERROR:",
                repr(error)
            )

        return True

    return False


# =========================================================
# ANTIFLOOD / REPORT / FILTER COMMAND ROUTER
# =========================================================

async def handle_extra_protection_command(
    message,
    user,
    chat,
    context,
    text
):
    command = (
        text.split()[0].lower()
        if text
        else ""
    )

    if command == "*antiflood":
        await command_antiflood(
            message, user, chat, context, text
        )
        return True

    if command == "*flood":
        await command_flood(
            message, user, chat, context, text
        )
        return True

    if command == "*reports":
        await command_reports(
            message, user, chat, context, text
        )
        return True

    if command == "*report":
        await command_report(
            message, user, chat, context
        )
        return True

    if command == "*filter":
        await command_filter(
            message, user, chat, context, text
        )
        return True

    if command == "*filters":
        await command_filters(
            message, chat
        )
        return True

    if command == "*stop":
        await command_stop(
            message, user, chat, context, text
        )
        return True

    if command == "*stopall":
        await command_stopall(
            message, user, chat, context
        )
        return True

    return False
    # =========================================================
# VERITAS v7 — 11-QISM
# NOTES + RULES + WELCOME + GOODBYE
# =========================================================


# =========================================================
# SAVE NOTE
# =========================================================

async def command_save(
    message,
    user,
    chat,
    context,
    text
):
    if not await admin_required(
        message, user, chat, context
    ):
        return

    parts = text.split(
        maxsplit=2
    )

    if len(parts) < 3:
        await message.reply_text(
            "⚠️ Foydalanish:\n"
            "*save nom matn\n\n"
            "Masalan:\n"
            "*save aloqa Admin: @username"
        )
        return

    name = (
        parts[1]
        .strip()
        .lower()
    )

    content = parts[2].strip()

    if not name or not content:
        return

    cursor.execute(
        """
        INSERT INTO notes (
            chat_id,
            name,
            content
        )
        VALUES (?, ?, ?)

        ON CONFLICT(chat_id, name)
        DO UPDATE SET
            content = excluded.content
        """,
        (
            chat.id,
            name,
            content
        )
    )

    db.commit()

    await message.reply_text(
        f"✅ Note saqlandi:\n{name}"
    )


# =========================================================
# GET NOTE
# =========================================================

async def command_get(
    message,
    chat,
    text
):
    parts = text.split(
        maxsplit=1
    )

    if len(parts) != 2:
        await message.reply_text(
            "⚠️ Foydalanish:\n"
            "*get nom"
        )
        return

    name = (
        parts[1]
        .strip()
        .lower()
    )

    cursor.execute(
        """
        SELECT content
        FROM notes
        WHERE chat_id = ?
          AND name = ?
        """,
        (
            chat.id,
            name
        )
    )

    row = cursor.fetchone()

    if not row:
        await message.reply_text(
            f"❌ Note topilmadi: {name}"
        )
        return

    await message.reply_text(
        row["content"]
    )


# =========================================================
# NOTES LIST
# =========================================================

async def command_notes(
    message,
    chat
):
    cursor.execute(
        """
        SELECT name
        FROM notes
        WHERE chat_id = ?
        ORDER BY name
        """,
        (chat.id,)
    )

    rows = cursor.fetchall()

    if not rows:
        await message.reply_text(
            "📝 Saqlangan note yo‘q."
        )
        return

    lines = [
        "📝 NOTES",
        ""
    ]

    for row in rows:
        lines.append(
            f"• {row['name']}"
        )

    await message.reply_text(
        "\n".join(lines)
    )


# =========================================================
# CLEAR NOTE
# =========================================================

async def command_clear_note(
    message,
    user,
    chat,
    context,
    text
):
    if not await admin_required(
        message, user, chat, context
    ):
        return

    parts = text.split(
        maxsplit=1
    )

    if len(parts) != 2:
        await message.reply_text(
            "⚠️ Foydalanish:\n"
            "*clear nom"
        )
        return

    name = (
        parts[1]
        .strip()
        .lower()
    )

    cursor.execute(
        """
        DELETE FROM notes
        WHERE chat_id = ?
          AND name = ?
        """,
        (
            chat.id,
            name
        )
    )

    deleted = cursor.rowcount

    db.commit()

    if deleted:
        await message.reply_text(
            f"🗑 Note o‘chirildi: {name}"
        )
    else:
        await message.reply_text(
            f"ℹ️ Note topilmadi: {name}"
        )


# =========================================================
# RULES
# =========================================================

async def command_rules(
    message,
    chat
):
    ensure_settings(
        chat.id
    )

    cursor.execute(
        """
        SELECT rules
        FROM settings
        WHERE chat_id = ?
        """,
        (chat.id,)
    )

    row = cursor.fetchone()

    rules = (
        row["rules"]
        if row and row["rules"]
        else ""
    )

    if not rules:
        await message.reply_text(
            "📜 Guruh qoidalari hali yozilmagan."
        )
        return

    await message.reply_text(
        "📜 GURUH QOIDALARI\n\n"
        + rules
    )


# =========================================================
# SET RULES
# =========================================================

async def command_setrules(
    message,
    user,
    chat,
    context,
    text
):
    if not await admin_required(
        message, user, chat, context
    ):
        return

    parts = text.split(
        maxsplit=1
    )

    if len(parts) != 2:
        await message.reply_text(
            "⚠️ Foydalanish:\n"
            "*setrules Guruh qoidalari..."
        )
        return

    rules = parts[1].strip()

    if not rules:
        return

    ensure_settings(
        chat.id
    )

    cursor.execute(
        """
        UPDATE settings
        SET rules = ?
        WHERE chat_id = ?
        """,
        (
            rules,
            chat.id
        )
    )

    db.commit()

    await message.reply_text(
        "✅ Guruh qoidalari yangilandi."
    )


# =========================================================
# WELCOME ON / OFF
# =========================================================

async def command_welcome(
    message,
    user,
    chat,
    context,
    text
):
    if not await admin_required(
        message, user, chat, context
    ):
        return

    ensure_settings(
        chat.id
    )

    parts = text.lower().split()

    if (
        len(parts) != 2
        or parts[1] not in (
            "on",
            "off",
        )
    ):
        cursor.execute(
            """
            SELECT welcome
            FROM settings
            WHERE chat_id = ?
            """,
            (chat.id,)
        )

        row = cursor.fetchone()

        enabled = bool(
            row and row["welcome"]
        )

        await message.reply_text(
            "👋 Welcome: "
            + (
                "ON ✅"
                if enabled
                else "OFF ⭕"
            )
            + "\n\n"
            "*welcome on\n"
            "*welcome off"
        )
        return

    enabled = (
        1
        if parts[1] == "on"
        else 0
    )

    cursor.execute(
        """
        UPDATE settings
        SET welcome = ?
        WHERE chat_id = ?
        """,
        (
            enabled,
            chat.id
        )
    )

    db.commit()

    await message.reply_text(
        "👋 Welcome "
        + (
            "yoqildi. ✅"
            if enabled
            else "o‘chirildi. ⭕"
        )
    )


# =========================================================
# GOODBYE ON / OFF
# =========================================================

async def command_goodbye(
    message,
    user,
    chat,
    context,
    text
):
    if not await admin_required(
        message, user, chat, context
    ):
        return

    ensure_settings(
        chat.id
    )

    parts = text.lower().split()

    if (
        len(parts) != 2
        or parts[1] not in (
            "on",
            "off",
        )
    ):
        cursor.execute(
            """
            SELECT goodbye
            FROM settings
            WHERE chat_id = ?
            """,
            (chat.id,)
        )

        row = cursor.fetchone()

        enabled = bool(
            row and row["goodbye"]
        )

        await message.reply_text(
            "👋 Goodbye: "
            + (
                "ON ✅"
                if enabled
                else "OFF ⭕"
            )
            + "\n\n"
            "*goodbye on\n"
            "*goodbye off"
        )
        return

    enabled = (
        1
        if parts[1] == "on"
        else 0
    )

    cursor.execute(
        """
        UPDATE settings
        SET goodbye = ?
        WHERE chat_id = ?
        """,
        (
            enabled,
            chat.id
        )
    )

    db.commit()

    await message.reply_text(
        "👋 Goodbye "
        + (
            "yoqildi. ✅"
            if enabled
            else "o‘chirildi. ⭕"
        )
    )


# =========================================================
# NEW MEMBER WELCOME
# =========================================================

async def welcome_new_member(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    message = update.effective_message
    chat = update.effective_chat

    if not message or not chat:
        return

    if chat.type not in (
        "group",
        "supergroup",
    ):
        return

    # Guruhni V7 tizimiga yozamiz.
    await register_or_update_group(
        chat,
        context
    )

    ensure_settings(
        chat.id
    )

    cursor.execute(
        """
        SELECT welcome
        FROM settings
        WHERE chat_id = ?
        """,
        (chat.id,)
    )

    row = cursor.fetchone()

    if not row or not row["welcome"]:
        return

    new_members = (
        message.new_chat_members
        or []
    )

    for member in new_members:
        if member.is_bot:
            continue

        register_or_update_user(
            member
        )

        name = get_name(
            member
        )

        await message.reply_text(
            "👋 Xush kelibsiz!\n\n"
            f"👤 {name}\n"
            f"👥 {chat.title or 'Veritas guruhi'}\n\n"
            "🪶 Veritas sizga yaxshi "
            "suhbatlar tilaydi."
        )


# =========================================================
# GOODBYE MEMBER
# =========================================================

async def goodbye_member(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    message = update.effective_message
    chat = update.effective_chat

    if not message or not chat:
        return

    if chat.type not in (
        "group",
        "supergroup",
    ):
        return

    ensure_settings(
        chat.id
    )

    cursor.execute(
        """
        SELECT goodbye
        FROM settings
        WHERE chat_id = ?
        """,
        (chat.id,)
    )

    row = cursor.fetchone()

    if not row or not row["goodbye"]:
        return

    member = (
        message.left_chat_member
    )

    if not member or member.is_bot:
        return

    await message.reply_text(
        "👋 Guruhni tark etdi:\n"
        f"{get_name(member)}"
    )


# =========================================================
# NOTES / RULES / WELCOME ROUTER
# =========================================================

async def handle_group_content_command(
    message,
    user,
    chat,
    context,
    text
):
    command = (
        text.split()[0].lower()
        if text
        else ""
    )

    if command == "*save":
        await command_save(
            message,
            user,
            chat,
            context,
            text
        )
        return True

    if command == "*get":
        await command_get(
            message,
            chat,
            text
        )
        return True

    if command == "*notes":
        await command_notes(
            message,
            chat
        )
        return True

    if command == "*clear":
        await command_clear_note(
            message,
            user,
            chat,
            context,
            text
        )
        return True

    if command == "*rules":
        await command_rules(
            message,
            chat
        )
        return True

    if command == "*setrules":
        await command_setrules(
            message,
            user,
            chat,
            context,
            text
        )
        return True

    if command == "*welcome":
        await command_welcome(
            message,
            user,
            chat,
            context,
            text
        )
        return True

    if command == "*goodbye":
        await command_goodbye(
            message,
            user,
            chat,
            context,
            text
        )
        return True

    return False
    # =========================================================
# VERITAS v7 — 12-QISM
# ID + PROFILE + ACTIVITY + ADMINS + ROLES
# =========================================================


# =========================================================
# *ID
# =========================================================

async def command_id(
    message,
    user,
    chat
):
    target = target_from_reply(message)

    if target:
        await message.reply_text(
            "🆔 FOYDALANUVCHI ID\n\n"
            f"👤 {target_label(target)}\n"
            f"🆔 {target.id}"
        )
        return

    if user:
        await message.reply_text(
            "🆔 VERITAS ID\n\n"
            f"👤 {get_name(user)}\n"
            f"🆔 User ID: {user.id}\n"
            f"👥 Chat ID: {chat.id}"
        )
        return

    channel_id = sender_channel_id(message)

    await message.reply_text(
        "🆔 VERITAS ID\n\n"
        f"📢 Sender Chat ID: {channel_id or '—'}\n"
        f"👥 Chat ID: {chat.id}"
    )


# =========================================================
# *MEN — PUBLIC PROFILE
# =========================================================

async def command_men(
    message,
    user,
    chat
):
    if not user:
        await message.reply_text(
            "⚠️ Kanal nomidan *men ishlatilmaydi."
        )
        return

    register_or_update_user(user)

    cabinet = get_user_cabinet(
        user.id
    )

    cursor.execute(
        """
        SELECT messages
        FROM activity
        WHERE chat_id = ?
          AND user_id = ?
        """,
        (
            chat.id,
            user.id
        )
    )

    activity_row = cursor.fetchone()

    messages = (
        activity_row["messages"]
        if activity_row
        else 0
    )

    cursor.execute(
        """
        SELECT COUNT(*) AS total
        FROM user_rewards
        WHERE user_id = ?
        """,
        (user.id,)
    )

    reward_count = cursor.fetchone()["total"]

    title = (
        cabinet["special_title"]
        or "—"
    )

    await message.reply_text(
        "🪶 VERITAS PROFIL\n\n"
        f"👤 {get_name(user)}\n"
        f"🆔 {user.id}\n\n"
        f"💎 LVL: {cabinet['level']}/15\n"
        f"✨ XP: {cabinet['xp']}\n"
        f"🎖 Unvon: {title}\n"
        f"💬 Guruhdagi faollik: {messages}\n"
        f"🎁 Mukofotlar: {reward_count}\n"
        f"⭐ Kabinet balansi: "
        f"{cabinet['cabinet_balance']}"
    )


# =========================================================
# *AKTIV
# =========================================================

async def command_aktiv(
    message,
    chat,
    text
):
    parts = text.split()

    limit = 10

    if len(parts) >= 2:
        try:
            limit = int(parts[1])
        except ValueError:
            await message.reply_text(
                "⚠️ Foydalanish:\n"
                "*aktiv\n"
                "*aktiv 10"
            )
            return

    if limit < 1:
        limit = 1

    if limit > 50:
        limit = 50

    cursor.execute(
        """
        SELECT
            user_id,
            name,
            username,
            messages
        FROM activity
        WHERE chat_id = ?
        ORDER BY messages DESC
        LIMIT ?
        """,
        (
            chat.id,
            limit
        )
    )

    rows = cursor.fetchall()

    if not rows:
        await message.reply_text(
            "📊 Hali faollik ma’lumoti yo‘q."
        )
        return

    lines = [
        f"🏆 TOP {len(rows)} FAOL A’ZO",
        ""
    ]

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

        if row["username"]:
            name = f"@{row['username']}"
        else:
            name = (
                row["name"]
                or str(row["user_id"])
            )

        lines.append(
            f"{icon} {name} — "
            f"{row['messages']}"
        )

    await message.reply_text(
        "\n".join(lines)
    )


# =========================================================
# *ADMINS
# =========================================================

async def command_admins(
    message,
    chat,
    context
):
    lines = [
        "👑 VERITAS ADMINLARI",
        ""
    ]

    # Telegram administratorlari
    try:
        telegram_admins = (
            await context.bot.get_chat_administrators(
                chat.id
            )
        )

        lines.append(
            "🔷 Telegram adminlari:"
        )

        for admin in telegram_admins:
            member = admin.user

            marker = (
                "👑"
                if admin.status == "creator"
                else "•"
            )

            lines.append(
                f"{marker} {get_name(member)}"
            )

    except Exception as error:
        print(
            "ADMIN LIST ERROR:",
            repr(error)
        )

        lines.append(
            "🔷 Telegram adminlari: "
            "olinmadi."
        )

    # Veritas ichki moderatorlari
    cursor.execute(
        """
        SELECT user_id, role
        FROM group_roles
        WHERE chat_id = ?
        ORDER BY granted_at
        """,
        (chat.id,)
    )

    rows = cursor.fetchall()

    lines.append("")
    lines.append(
        "🪶 Veritas ichki moderatorlari:"
    )

    if not rows:
        lines.append("• Yo‘q")

    else:
        for row in rows:
            cabinet = get_user_cabinet(
                row["user_id"]
            )

            if cabinet:
                name = (
                    f"@{cabinet['username']}"
                    if cabinet["username"]
                    else cabinet["full_name"]
                )
            else:
                name = str(
                    row["user_id"]
                )

            lines.append(
                f"• {name} "
                f"({row['role']})"
            )

    await message.reply_text(
        "\n".join(lines)
    )


# =========================================================
# *RUXSAT
# SUPER OWNER → INTERNAL MODERATOR
# =========================================================

async def command_ruxsat(
    message,
    user,
    chat,
    context
):
    if not await super_owner_required(
        message,
        user
    ):
        return

    target = target_from_reply(
        message
    )

    if not target:
        await message.reply_text(
            "⚠️ Foydalanuvchi xabariga "
            "reply qilib *ruxsat yozing."
        )
        return

    if target.is_bot:
        await message.reply_text(
            "⚠️ Botga ichki moderator "
            "ruxsati berilmaydi."
        )
        return

    register_or_update_user(
        target
    )

    actor_id = (
        user.id
        if user
        else sender_channel_id(message)
    )

    cursor.execute(
        """
        INSERT INTO group_roles (
            chat_id,
            user_id,
            role,
            granted_by,
            granted_at
        )
        VALUES (?, ?, 'moderator', ?, ?)

        ON CONFLICT(chat_id, user_id)
        DO UPDATE SET
            role = 'moderator',
            granted_by = excluded.granted_by,
            granted_at = excluded.granted_at
        """,
        (
            chat.id,
            target.id,
            actor_id,
            datetime_to_db(
                utc_now()
            )
        )
    )

    db.commit()

    add_audit_log(
        actor_id=actor_id,
        action="internal_moderator_granted",
        target_user_id=target.id,
        target_chat_id=chat.id
    )

    await message.reply_text(
        f"🪶 {target_label(target)} ga "
        "Veritas moderator ruxsati berildi."
    )


# =========================================================
# *RUXSATSIZ
# =========================================================

async def command_ruxsatsiz(
    message,
    user,
    chat,
    context
):
    if not await super_owner_required(
        message,
        user
    ):
        return

    target = target_from_reply(
        message
    )

    if not target:
        await message.reply_text(
            "⚠️ Foydalanuvchi xabariga "
            "reply qilib *ruxsatsiz yozing."
        )
        return

    cursor.execute(
        """
        DELETE FROM group_roles
        WHERE chat_id = ?
          AND user_id = ?
        """,
        (
            chat.id,
            target.id
        )
    )

    deleted = cursor.rowcount

    db.commit()

    actor_id = (
        user.id
        if user
        else sender_channel_id(message)
    )

    if deleted:
        add_audit_log(
            actor_id=actor_id,
            action="internal_moderator_removed",
            target_user_id=target.id,
            target_chat_id=chat.id
        )

        await message.reply_text(
            f"✅ {target_label(target)} ning "
            "Veritas moderator ruxsati olib tashlandi."
        )

    else:
        await message.reply_text(
            "ℹ️ Bu foydalanuvchida "
            "Veritas moderator ruxsati yo‘q."
        )


# =========================================================
# *ADMIN
# TELEGRAM ADMIN BERISH
# =========================================================

async def command_admin(
    message,
    user,
    chat,
    context
):
    if not await super_owner_required(
        message,
        user
    ):
        return

    target = target_from_reply(
        message
    )

    if not target:
        await message.reply_text(
            "⚠️ Foydalanuvchi xabariga "
            "reply qilib *admin yozing."
        )
        return

    if target.is_bot:
        await message.reply_text(
            "⚠️ Bu buyruq foydalanuvchi uchun."
        )
        return

    try:
        await context.bot.promote_chat_member(
            chat_id=chat.id,
            user_id=target.id,

            can_manage_chat=True,
            can_delete_messages=True,
            can_manage_video_chats=True,
            can_restrict_members=True,
            can_invite_users=True,
            can_pin_messages=True,
            can_manage_topics=True,

            # Boshqa adminlarni tayinlash huquqini
            # bermaymiz.
            can_promote_members=False,

            # Kanalga oid huquqlar
            can_post_messages=False,
            can_edit_messages=False
        )

    except Exception as error:
        print(
            "PROMOTE ADMIN ERROR:",
            repr(error)
        )

        await message.reply_text(
            "❌ Telegram admin berilmadi.\n\n"
            "VeritasBot'da “Add administrators / "
            "Promote members” huquqi borligini tekshiring."
        )
        return

    actor_id = (
        user.id
        if user
        else sender_channel_id(message)
    )

    add_audit_log(
        actor_id=actor_id,
        action="telegram_admin_granted",
        target_user_id=target.id,
        target_chat_id=chat.id
    )

    await message.reply_text(
        f"👑 {target_label(target)} "
        "Telegram administratori qilindi."
    )


# =========================================================
# *UNADMIN
# TELEGRAM ADMIN HUQUQLARINI OLISH
# =========================================================

async def command_unadmin(
    message,
    user,
    chat,
    context
):
    if not await super_owner_required(
        message,
        user
    ):
        return

    target = target_from_reply(
        message
    )

    if not target:
        await message.reply_text(
            "⚠️ Foydalanuvchi xabariga "
            "reply qilib *unadmin yozing."
        )
        return

    if is_protected_super_owner(
        target.id
    ):
        await message.reply_text(
            "👑 Super Eganing admin huquqi "
            "Veritas orqali olib tashlanmaydi."
        )
        return

    try:
        member = await context.bot.get_chat_member(
            chat.id,
            target.id
        )

        if member.status == "creator":
            await message.reply_text(
                "⛔ Telegram guruh egasini "
                "adminlikdan tushirib bo‘lmaydi."
            )
            return

        await context.bot.promote_chat_member(
            chat_id=chat.id,
            user_id=target.id,

            can_manage_chat=False,
            can_delete_messages=False,
            can_manage_video_chats=False,
            can_restrict_members=False,
            can_invite_users=False,
            can_pin_messages=False,
            can_manage_topics=False,
            can_promote_members=False,
            can_post_messages=False,
            can_edit_messages=False
        )

    except Exception as error:
        print(
            "UNADMIN ERROR:",
            repr(error)
        )

        await message.reply_text(
            "❌ Admin huquqlari olib tashlanmadi.\n"
            "Botning Telegram admin huquqlarini tekshiring."
        )
        return

    actor_id = (
        user.id
        if user
        else sender_channel_id(message)
    )

    add_audit_log(
        actor_id=actor_id,
        action="telegram_admin_removed",
        target_user_id=target.id,
        target_chat_id=chat.id
    )

    await message.reply_text(
        f"✅ {target_label(target)} "
        "Telegram adminligidan tushirildi."
    )


# =========================================================
# ID / ACTIVITY / ROLE COMMAND ROUTER
# =========================================================

async def handle_identity_role_command(
    message,
    user,
    chat,
    context,
    text
):
    command = (
        text.split()[0].lower()
        if text
        else ""
    )

    if command == "*id":
        await command_id(
            message,
            user,
            chat
        )
        return True

    if command == "*men":
        await command_men(
            message,
            user,
            chat
        )
        return True

    if command == "*aktiv":
        await command_aktiv(
            message,
            chat,
            text
        )
        return True

    if command == "*admins":
        await command_admins(
            message,
            chat,
            context
        )
        return True

    if command == "*ruxsat":
        await command_ruxsat(
            message,
            user,
            chat,
            context
        )
        return True

    if command == "*ruxsatsiz":
        await command_ruxsatsiz(
            message,
            user,
            chat,
            context
        )
        return True

    if command == "*admin":
        await command_admin(
            message,
            user,
            chat,
            context
        )
        return True

    if command == "*unadmin":
        await command_unadmin(
            message,
            user,
            chat,
            context
        )
        return True

    return False
    # =========================================================
# VERITAS v7 — 13-QISM
# HELP + PLAN STATUS + MAIN MESSAGE ROUTER
# =========================================================


# =========================================================
# HELP
# =========================================================

HELP_TEXT = """
🪶 VERITAS BOT

👤 ASOSIY
*help — buyruqlar ro‘yxati
*id — foydalanuvchi va guruh ID
*men — Veritas profilingiz
*aktiv — faol a’zolar
*aktiv 10 — TOP 10 faol a’zo
*admins — administratorlar

🛡 MODERATSIYA
*warn — ogohlantirish
*unwarn — bitta ogohlantirishni olib tashlash
*clearwarns — barcha ogohlantirishlarni tozalash
*mute — yozishni cheklash
*unmute — mute holatidan chiqarish
*kick — guruhdan chiqarish
*ban — ban qilish
*unban — bandan chiqarish
*unban ID — ID orqali bandan chiqarish
*del — xabarni o‘chirish

✅ APPROVED
*approve — himoyalardan ozod qilish
*unapprove — approved holatini olib tashlash
*approved — approved ro‘yxati

🔗 HIMOYA
*links on — link himoyasini yoqish
*links off — link himoyasini o‘chirish
*blacklist so‘z — so‘zni blacklistga qo‘shish
*unblacklist so‘z — blacklistdan olib tashlash
*blacklists — blacklist ro‘yxati

🔒 LOCK
*lock photo
*lock video
*lock sticker
*lock animation
*lock document
*lock voice
*lock audio
*lock links
*unlock turi
*locks — faol locklar

🌊 ANTI-FLOOD
*antiflood on
*antiflood off
*flood 5

🚨 REPORT
*reports on
*reports off
*report — xabarga shikoyat

🔎 FILTER
*filter so‘z javob
*filter so‘z — media xabariga reply orqali
*filters — filterlar
*stop so‘z — bitta filterni o‘chirish
*stopall — barcha filterlarni o‘chirish

📝 NOTES
*save nom matn
*get nom
*notes
*clear nom

📜 GURUH
*rules — qoidalar
*setrules matn — qoidalarni yozish
*welcome on
*welcome off
*goodbye on
*goodbye off

👑 BOSHQARUV
*ruxsat — Veritas ichki moderator ruxsati
*ruxsatsiz — ichki moderator ruxsatini olish
*admin — Telegram admin qilish
*unadmin — Telegram admin huquqini olish

💎 VERITAS V7
*plan — guruhning V6/V7 holati

⭐ SHAXSIY KABINET
*topup 100 — kabinet balansini 100 Stars bilan to‘ldirish

ℹ️ Warn, mute, ban, kick, admin kabi buyruqlarni
foydalanuvchining xabariga reply qilib ishlating.
""".strip()


async def command_help(message):
    await message.reply_text(
        HELP_TEXT
    )


# =========================================================
# *PLAN
# =========================================================

async def command_plan(
    message,
    chat
):
    await message.reply_text(
        subscription_status_text(
            chat.id
        )
    )


# =========================================================
# KNOWN COMMANDS
# =========================================================

KNOWN_COMMANDS = [
    "*help",
    "*id",
    "*men",
    "*aktiv",
    "*admins",

    "*warn",
    "*unwarn",
    "*clearwarns",
    "*mute",
    "*unmute",
    "*kick",
    "*ban",
    "*unban",
    "*del",

    "*approve",
    "*unapprove",
    "*approved",

    "*links",
    "*blacklist",
    "*unblacklist",
    "*blacklists",

    "*lock",
    "*unlock",
    "*locks",

    "*antiflood",
    "*flood",

    "*report",
    "*reports",

    "*filter",
    "*filters",
    "*stop",
    "*stopall",

    "*save",
    "*get",
    "*notes",
    "*clear",

    "*rules",
    "*setrules",
    "*welcome",
    "*goodbye",

    "*ruxsat",
    "*ruxsatsiz",
    "*admin",
    "*unadmin",

    "*plan",
    "*topup",
    "*cabinet",
    "*kabinet",
]


# =========================================================
# COMMAND SUGGESTION
# =========================================================

def command_similarity(
    first,
    second
):
    first = (
        first
        .strip()
        .lower()
    )

    second = (
        second
        .strip()
        .lower()
    )

    if not first or not second:
        return -999

    if first == second:
        return 100

    if first.startswith(second):
        return 80

    if second.startswith(first):
        return 80

    length_difference = abs(
        len(first) - len(second)
    )

    same_positions = sum(
        1
        for first_char, second_char in zip(
            first,
            second
        )
        if first_char == second_char
    )

    score = (
        same_positions * 10
        - length_difference * 3
    )

    return score


def suggest_command(
    typed_command
):
    if not typed_command:
        return None

    best_command = None
    best_score = -999

    for known_command in KNOWN_COMMANDS:
        score = command_similarity(
            typed_command,
            known_command
        )

        if score > best_score:
            best_score = score
            best_command = known_command

    if best_score < 10:
        return None

    return best_command


# =========================================================
# UNKNOWN COMMAND MESSAGE
# =========================================================

async def send_unknown_command(
    message,
    command
):
    suggestion = suggest_command(
        command
    )

    if suggestion:
        await message.reply_text(
            "❓ Bunday buyruq topilmadi.\n\n"
            f"Balki siz {suggestion} "
            "demoqchi bo‘lgandirsiz."
        )
        return

    await message.reply_text(
        "❓ Buyruq topilmadi.\n\n"
        "*help orqali buyruqlarni ko‘ring."
    )


# =========================================================
# PRIVATE MESSAGE ROUTER
# =========================================================

async def handle_private_message(
    update,
    context,
    message,
    user,
    text
):
    normalized_text = (
        text
        .strip()
    )

    lower_text = (
        normalized_text
        .lower()
    )

    # -----------------------------------------------------
    # /START
    # -----------------------------------------------------

    if (
        lower_text == "/start"
        or lower_text.startswith("/start ")
    ):
        await private_start(
            update,
            context
        )
        return

    # -----------------------------------------------------
    # SUPER OWNER INPUT MODE
    # -----------------------------------------------------

    if is_super_owner_id(
        user.id
    ):
        handled = await handle_super_owner_input(
            message,
            user,
            context
        )

        if handled:
            return

    # -----------------------------------------------------
    # STARS TOPUP
    # -----------------------------------------------------

    if (
        lower_text == "*topup"
        or lower_text.startswith("*topup ")
    ):
        await handle_private_topup(
            message,
            user,
            context,
            normalized_text
        )
        return

    # -----------------------------------------------------
    # CABINET
    # -----------------------------------------------------

    if lower_text in (
        "*cabinet",
        "*kabinet",
        "cabinet",
        "kabinet",
    ):
        register_or_update_user(
            user
        )

        await show_cabinet(
            message,
            user
        )
        return

    # -----------------------------------------------------
    # PRIVATE *MEN
    # -----------------------------------------------------

    if lower_text == "*men":
        register_or_update_user(
            user
        )

        cabinet = get_user_cabinet(
            user.id
        )

        if not cabinet:
            await message.reply_text(
                "❌ Veritas kabinetingiz topilmadi."
            )
            return

        await message.reply_text(
            cabinet_profile_text(
                cabinet
            ),
            reply_markup=cabinet_keyboard(
                user.id
            )
        )
        return

    # -----------------------------------------------------
    # PRIVATE *HELP
    # -----------------------------------------------------

    if lower_text == "*help":
        await command_help(
            message
        )
        return

    # -----------------------------------------------------
    # UNKNOWN PRIVATE COMMAND
    # -----------------------------------------------------

    if normalized_text.startswith("*"):
        command = (
            normalized_text
            .split()[0]
            .lower()
        )

        await send_unknown_command(
            message,
            command
        )
        return

    # -----------------------------------------------------
    # NORMAL PRIVATE MESSAGE
    # -----------------------------------------------------

    register_or_update_user(
        user
    )

    await show_cabinet(
        message,
        user
    )


# =========================================================
# GROUP MESSAGE ROUTER
# =========================================================

async def handle_group_message(
    update,
    context,
    message,
    user,
    chat,
    text
):
    # -----------------------------------------------------
    # REGISTER / UPDATE GROUP
    # -----------------------------------------------------

    await register_or_update_group(
        chat,
        context
    )

    ensure_settings(
        chat.id
    )

    # Reja muddati o‘tgan bo‘lsa,
    # V7/V6 holatini yangilaydi.
    refresh_group_plan(
        chat.id
    )

    # -----------------------------------------------------
    # REGISTER USER
    # -----------------------------------------------------

    if (
        user
        and not user.is_bot
    ):
        register_or_update_user(
            user
        )

    normalized_text = (
        text
        .strip()
    )

    # -----------------------------------------------------
    # COMMANDS
    # -----------------------------------------------------

    if normalized_text.startswith("*"):
        command = (
            normalized_text
            .split()[0]
            .lower()
        )

        # HELP
        if command == "*help":
            await command_help(
                message
            )
            return

        # PLAN
        if command == "*plan":
            await command_plan(
                message,
                chat
            )
            return

        # ID / MEN / AKTIV / ADMINS / ROLES
        handled = await handle_identity_role_command(
            message,
            user,
            chat,
            context,
            normalized_text
        )

        if handled:
            return

        # WARN / MUTE / BAN / KICK / DEL
        handled = await handle_moderation_command(
            message,
            user,
            chat,
            context,
            normalized_text
        )

        if handled:
            return

        # APPROVE / LINKS / BLACKLIST / LOCKS
        handled = await handle_protection_command(
            message,
            user,
            chat,
            context,
            normalized_text
        )

        if handled:
            return

        # ANTIFLOOD / REPORT / FILTERS
        handled = await handle_extra_protection_command(
            message,
            user,
            chat,
            context,
            normalized_text
        )

        if handled:
            return

        # NOTES / RULES / WELCOME / GOODBYE
        handled = await handle_group_content_command(
            message,
            user,
            chat,
            context,
            normalized_text
        )

        if handled:
            return

        # UNKNOWN COMMAND
        await send_unknown_command(
            message,
            command
        )

        return

    # -----------------------------------------------------
    # NORMAL MESSAGE ACTIVITY
    # -----------------------------------------------------

    if (
        user
        and not user.is_bot
    ):
        add_activity(
            chat.id,
            user
        )

    # Kanal nomidan yuborilgan oddiy xabarlarda
    # user bo‘lmasligi mumkin. Anti-flood faqat
    # haqiqiy foydalanuvchilar uchun ishlaydi.
    if user and not user.is_bot:
        if await check_antiflood(
            message,
            user,
            chat,
            context
        ):
            return

    # -----------------------------------------------------
    # LINK PROTECTION
    # -----------------------------------------------------

    if await check_link_protection(
        message,
        user,
        chat,
        context
    ):
        return

    # -----------------------------------------------------
    # BLACKLIST
    # -----------------------------------------------------

    if await check_blacklist_protection(
        message,
        user,
        chat,
        context
    ):
        return

    # -----------------------------------------------------
    # MEDIA LOCK
    # -----------------------------------------------------

    if await check_media_lock(
        message,
        user,
        chat,
        context
    ):
        return

    # -----------------------------------------------------
    # SAVED FILTERS
    # -----------------------------------------------------

    await check_saved_filters(
        message,
        chat,
        context
    )


# =========================================================
# MAIN MESSAGE HANDLER
# =========================================================

async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    message = (
        update.effective_message
    )

    chat = (
        update.effective_chat
    )

    user = (
        update.effective_user
    )

    if not message or not chat:
        return

    # Status update xabarlarini bu router
    # qayta ishlamaydi.
    if (
        message.new_chat_members
        or message.left_chat_member
    ):
        return

    text = (
        message.text
        or message.caption
        or ""
    )

    text = text.strip()

    # -----------------------------------------------------
    # PRIVATE CHAT
    # -----------------------------------------------------

    if chat.type == "private":
        if not user:
            return

        await handle_private_message(
            update,
            context,
            message,
            user,
            text
        )

        return

    # -----------------------------------------------------
    # GROUP / SUPERGROUP
    # -----------------------------------------------------

    if chat.type in (
        "group",
        "supergroup",
    ):
        await handle_group_message(
            update,
            context,
            message,
            user,
            chat,
            text
        )

        return
        # =========================================================
# VERITAS v7 — 14-QISM
# CALLBACKS + PAYMENTS + FINAL MAIN
# =========================================================


# =========================================================
# MAIN CALLBACK ROUTER
# =========================================================

async def handle_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query

    if not query:
        return

    data = query.data or ""

    # -----------------------------------------------------
    # LANGUAGE
    # -----------------------------------------------------

    if data.startswith("lang:"):
        await language_callback(
            update,
            context
        )
        return

    # -----------------------------------------------------
    # PERSONAL CABINET
    # -----------------------------------------------------

    if data.startswith("cabinet:"):
        await cabinet_callback(
            update,
            context
        )
        return

    # -----------------------------------------------------
    # SUPER OWNER CABINET
    # -----------------------------------------------------

    if data.startswith("super:"):
        await super_owner_callback(
            update,
            context
        )
        return

    # -----------------------------------------------------
    # V7 SUBSCRIPTION
    # -----------------------------------------------------

    if data.startswith("sub:"):
        await subscription_callback(
            update,
            context
        )
        return

    # -----------------------------------------------------
    # UNKNOWN CALLBACK
    # -----------------------------------------------------

    try:
        await query.answer(
            "Bu tugma hozir faol emas.",
            show_alert=False
        )
    except Exception:
        pass


# =========================================================
# GLOBAL ERROR HANDLER
# =========================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE
):
    error = context.error

    print(
        "VERITAS ERROR:",
        repr(error)
    )

    # Foydalanuvchiga ichki texnik
    # ma'lumotlarni ko‘rsatmaymiz.
    if isinstance(
        update,
        Update
    ):
        message = (
            update.effective_message
        )

        if message:
            try:
                await message.reply_text(
                    "⚠️ Veritas bu amalni bajarishda "
                    "xatoga uchradi."
                )
            except Exception:
                pass


# =========================================================
# MAIN
# =========================================================

def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN topilmadi. "
            "Railway Variables bo‘limini tekshiring."
        )

    application = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .build()
    )

    # -----------------------------------------------------
    # JOIN / LEAVE
    # -----------------------------------------------------

    application.add_handler(
        MessageHandler(
            filters.StatusUpdate.NEW_CHAT_MEMBERS,
            welcome_new_member
        ),
        group=0
    )

    application.add_handler(
        MessageHandler(
            filters.StatusUpdate.LEFT_CHAT_MEMBER,
            goodbye_member
        ),
        group=0
    )

    # -----------------------------------------------------
    # TELEGRAM STARS PAYMENT
    # -----------------------------------------------------

    application.add_handler(
        PreCheckoutQueryHandler(
            precheckout_callback
        ),
        group=0
    )

    application.add_handler(
        MessageHandler(
            filters.SUCCESSFUL_PAYMENT,
            successful_payment
        ),
        group=0
    )

    # -----------------------------------------------------
    # INLINE BUTTON CALLBACKS
    # -----------------------------------------------------

    application.add_handler(
        CallbackQueryHandler(
            handle_callback
        ),
        group=0
    )

    # -----------------------------------------------------
    # ALL NORMAL MESSAGES
    # -----------------------------------------------------

    application.add_handler(
        MessageHandler(
            filters.ALL
            & ~filters.StatusUpdate.NEW_CHAT_MEMBERS
            & ~filters.StatusUpdate.LEFT_CHAT_MEMBER
            & ~filters.SUCCESSFUL_PAYMENT,
            handle_message
        ),
        group=1
    )

    # -----------------------------------------------------
    # ERROR HANDLER
    # -----------------------------------------------------

    application.add_error_handler(
        error_handler
    )

    print(
        "VeritasBot v7 ishga tushdi."
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
