import os
import re
import sqlite3
import time

from telegram import (
    Update,
    ChatPermissions,
    LabeledPrice,
)

from telegram.ext import (
    Application,
    ContextTypes,
    MessageHandler,
    PreCheckoutQueryHandler,
    filters,
)


# =========================================================
# VERITAS BOT v6
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")

# Asosiy ega
OWNER_ID = 5859289233

# Ega huquqiga ega kanallar
OWNER_CHANNEL_IDS = {
    -1003565272437,   # Sakranum
    -1004342424568,   # Veritas
}


# =========================================================
# DATABASE
# =========================================================

db = sqlite3.connect(
    "veritas.db",
    check_same_thread=False
)

cursor = db.cursor()


# ---------------------------------------------------------
# SETTINGS
# ---------------------------------------------------------

cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS settings (
        chat_id INTEGER PRIMARY KEY,
        link_block INTEGER DEFAULT 0,
        welcome INTEGER DEFAULT 1,
        goodbye INTEGER DEFAULT 1,
        rules TEXT DEFAULT '',
        antiflood INTEGER DEFAULT 0,
        flood_limit INTEGER DEFAULT 5,
        reports INTEGER DEFAULT 1,
        captcha INTEGER DEFAULT 0
    )
    """
)


# ---------------------------------------------------------
# ACTIVITY
# ---------------------------------------------------------

cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS activity (
        chat_id INTEGER,
        user_id INTEGER,
        name TEXT,
        username TEXT,
        messages INTEGER DEFAULT 0,
        PRIMARY KEY (chat_id, user_id)
    )
    """
)


# ---------------------------------------------------------
# WARNINGS
# ---------------------------------------------------------

cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS warnings (
        chat_id INTEGER,
        user_id INTEGER,
        warns INTEGER DEFAULT 0,
        PRIMARY KEY (chat_id, user_id)
    )
    """
)


# ---------------------------------------------------------
# BLACKLIST
# ---------------------------------------------------------

cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS blacklist (
        chat_id INTEGER,
        word TEXT,
        PRIMARY KEY (chat_id, word)
    )
    """
)


# ---------------------------------------------------------
# FILTERS
# ---------------------------------------------------------

cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS chat_filters (
        chat_id INTEGER,
        keyword TEXT,
        response TEXT DEFAULT '',
        media_type TEXT DEFAULT 'text',
        file_id TEXT DEFAULT '',
        caption TEXT DEFAULT '',
        PRIMARY KEY (chat_id, keyword)
    )
    """
)


# ---------------------------------------------------------
# NOTES
# ---------------------------------------------------------

cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS notes (
        chat_id INTEGER,
        name TEXT,
        content TEXT,
        PRIMARY KEY (chat_id, name)
    )
    """
)


# ---------------------------------------------------------
# VERITAS INTERNAL ADMINS
# ---------------------------------------------------------

cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS allowed_users (
        chat_id INTEGER,
        user_id INTEGER,
        PRIMARY KEY (chat_id, user_id)
    )
    """
)


# ---------------------------------------------------------
# APPROVED USERS
# ---------------------------------------------------------

cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS approved_users (
        chat_id INTEGER,
        user_id INTEGER,
        PRIMARY KEY (chat_id, user_id)
    )
    """
)


# ---------------------------------------------------------
# LOCKS
# ---------------------------------------------------------

cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS locks (
        chat_id INTEGER,
        lock_type TEXT,
        PRIMARY KEY (chat_id, lock_type)
    )
    """
)


# ---------------------------------------------------------
# FLOOD DATA
# ---------------------------------------------------------

cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS flood_data (
        chat_id INTEGER,
        user_id INTEGER,
        count INTEGER DEFAULT 0,
        last_time REAL DEFAULT 0,
        PRIMARY KEY (chat_id, user_id)
    )
    """
)


db.commit()


# =========================================================
# OLD DATABASE MIGRATION
# =========================================================

def add_column_if_missing(table, column, definition):
    try:
        cursor.execute(
            f"ALTER TABLE {table} "
            f"ADD COLUMN {column} {definition}"
        )
        db.commit()
    except sqlite3.OperationalError:
        pass


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
# BASIC HELPERS
# =========================================================

def get_name(user):
    if not user:
        return "Noma’lum"

    if user.full_name:
        return user.full_name

    if user.username:
        return f"@{user.username}"

    return str(user.id)


def ensure_settings(chat_id):
    cursor.execute(
        """
        INSERT OR IGNORE INTO settings (chat_id)
        VALUES (?)
        """,
        (chat_id,)
    )
    db.commit()


def reply_target(message):
    if not message.reply_to_message:
        return None

    return message.reply_to_message.from_user


def sender_channel_id(message):
    if not message.sender_chat:
        return None

    return message.sender_chat.id


def is_owner_source(message, user):
    # Asosiy ega
    if user and user.id == OWNER_ID:
        return True

    # Sakranum yoki Veritas kanali nomidan yozilgan xabar
    channel_id = sender_channel_id(message)

    if channel_id in OWNER_CHANNEL_IDS:
        return True

    return False


def contains_link(text):
    if not text:
        return False

    patterns = (
        r"https?://",
        r"www\.",
        r"t\.me/",
        r"telegram\.me/",
        r"telegram\.dog/"
    )

    lower_text = text.lower()

    return any(
        re.search(pattern, lower_text)
        for pattern in patterns
    )


async def is_telegram_admin(chat, user_id, context):
    if not user_id:
        return False

    try:
        member = await context.bot.get_chat_member(
            chat.id,
            user_id
        )

        return member.status in (
            "administrator",
            "creator"
        )

    except Exception:
        return False


async def is_internal_admin(chat_id, user_id):
    if not user_id:
        return False

    cursor.execute(
        """
        SELECT 1
        FROM allowed_users
        WHERE chat_id = ?
          AND user_id = ?
        """,
        (chat_id, user_id)
    )

    return cursor.fetchone() is not None


async def is_admin(message, user, chat, context):
    if is_owner_source(message, user):
        return True

    if user and await is_internal_admin(
        chat.id,
        user.id
    ):
        return True

    if user and await is_telegram_admin(
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
    allowed = await is_admin(
        message,
        user,
        chat,
        context
    )

    if allowed:
        return True

    await message.reply_text(
        "⛔ Bu buyruq faqat administratorlar uchun."
    )

    return False
    # =========================================================
# EXTRA HELPERS
# =========================================================

async def owner_required(message, user):
    if is_owner_source(message, user):
        return True

    await message.reply_text(
        "⛔ Bu buyruq faqat Veritas egasi uchun."
    )
    return False


def is_approved(chat_id, user_id):
    if not user_id:
        return False

    cursor.execute(
        """
        SELECT 1
        FROM approved_users
        WHERE chat_id = ?
          AND user_id = ?
        """,
        (chat_id, user_id)
    )

    return cursor.fetchone() is not None


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
        row[0]
        for row in cursor.fetchall()
    ]


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


async def send_saved_filter(
    message,
    context,
    media_type,
    file_id,
    response,
    caption
):
    final_caption = caption or response or None

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
        await message.reply_text(response)


# =========================================================
# HELP
# =========================================================

HELP_TEXT = """
🤖 VERITAS BOT v6

📌 ASOSIY
*help
*id
*men
*aktiv
*aktiv 10
*rules
*admins

🛡 MODERATSIYA
*warn
*unwarn
*warns
*clearwarns
*mute
*unmute
*kick
*ban
*unban
*del

👑 VERITAS ADMIN
*ruxsat
*ruxsatsiz

👮 TELEGRAM ADMIN
*admin
*unadmin

🔗 LINK HIMOYASI
*links on
*links off

🚫 BLACKLIST
*blacklist so‘z
*unblacklist so‘z
*blacklists

🔐 LOCK
*lock links
*lock photo
*lock video
*lock sticker
*lock animation
*lock document
*lock voice
*lock audio
*unlock turi
*locks

🌊 ANTI-FLOOD
*antiflood on
*antiflood off
*flood 5

✅ APPROVAL
*approve
*unapprove
*approved

📢 REPORT
*report
*reports on
*reports off

💬 FILTER
*filter kalit javob
*filters
*stop kalit
*stopall

📝 NOTES
*save nom matn
*get nom
*notes
*clear nom

⚙️ SOZLAMALAR
*welcome on/off
*goodbye on/off
*setrules matn

⭐ STARS
*topup 100

🎁 GIFT
*give 25
*give 50
*give 100
"""


# =========================================================
# WELCOME
# =========================================================

async def welcome_new_member(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    message = update.effective_message
    chat = update.effective_chat

    if not message or not chat:
        return

    ensure_settings(chat.id)

    cursor.execute(
        """
        SELECT welcome
        FROM settings
        WHERE chat_id = ?
        """,
        (chat.id,)
    )

    row = cursor.fetchone()

    if not row or not row[0]:
        return

    for member in message.new_chat_members:
        if member.is_bot:
            continue

        try:
            await message.reply_text(
                f"👋 Xush kelibsiz, {get_name(member)}!\n"
                f"📚 Qoidalar uchun: *rules"
            )
        except Exception as error:
            print(
                "WELCOME ERROR:",
                repr(error)
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

    ensure_settings(chat.id)

    cursor.execute(
        """
        SELECT goodbye
        FROM settings
        WHERE chat_id = ?
        """,
        (chat.id,)
    )

    row = cursor.fetchone()

    if not row or not row[0]:
        return

    try:
        await message.reply_text(
            f"👋 {get_name(member)} guruhni tark etdi."
        )
    except Exception as error:
        print(
            "GOODBYE ERROR:",
            repr(error)
        )


# =========================================================
# STARS PAYMENT
# =========================================================

async def topup_stars(
    message,
    user,
    context,
    amount
):
    if not is_owner_source(message, user):
        await message.reply_text(
            "⛔ Stars balansini faqat ega to‘ldira oladi."
        )
        return

    if amount < 1:
        await message.reply_text(
            "⚠️ Stars miqdori noto‘g‘ri."
        )
        return

    # Invoice foydalanuvchining shaxsiy chatiga yuboriladi.
    if not user:
        await message.reply_text(
            "⚠️ Bu buyruqni shaxsiy profilingizdan yuboring."
        )
        return

    try:
        await context.bot.send_invoice(
            chat_id=user.id,
            title="Veritas Stars balansi",
            description=(
                f"VeritasBot uchun {amount} Stars"
            ),
            payload=f"veritas_topup_{amount}",
            currency="XTR",
            prices=[
                LabeledPrice(
                    "Stars",
                    amount
                )
            ],
            provider_token=""
        )

    except Exception as error:
        print(
            "TOPUP ERROR:",
            repr(error)
        )

        await message.reply_text(
            "❌ Stars invoice yaratilmadi."
        )


async def precheckout_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.pre_checkout_query

    if not query:
        return

    await query.answer(ok=True)


async def successful_payment(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    message = update.effective_message

    if not message or not message.successful_payment:
        return

    payment = message.successful_payment

    await message.reply_text(
        "✅ Veritas Stars to‘lovi qabul qilindi!\n"
        f"⭐ {payment.total_amount} Stars bot balansiga tushdi."
)
    # =========================================================
# TELEGRAM GIFT
# =========================================================

async def give_gift(
    message,
    user,
    context,
    amount
):
    if not is_owner_source(message, user):
        await message.reply_text(
            "⛔ Gift yuborish faqat egaga ruxsat."
        )
        return

    target = reply_target(message)

    if not target:
        await message.reply_text(
            "🎁 Gift beriladigan odamning xabariga "
            "reply qilib yozing:\n"
            "*give 25"
        )
        return

    if target.is_bot:
        await message.reply_text(
            "⚠️ Botga Gift yuborib bo‘lmaydi."
        )
        return

    try:
        gifts = await context.bot.get_available_gifts()

        selected_gift = None

        for gift in gifts.gifts:
            if gift.star_count == amount:
                selected_gift = gift
                break

        if not selected_gift:
            await message.reply_text(
                f"⚠️ Hozir aynan {amount} Starslik "
                "Telegram Gift mavjud emas."
            )
            return

        await context.bot.send_gift(
            user_id=target.id,
            gift_id=selected_gift.id,
            text="🎁 Veritas tomonidan sovg‘a!"
        )

        await message.reply_text(
            f"🎁 {get_name(target)} ga "
            f"{amount} Starslik Gift yuborildi!"
        )

    except Exception as error:
        print(
            "GIFT ERROR:",
            repr(error)
        )

        error_text = str(error).lower()

        if "balance_too_low" in error_text:
            await message.reply_text(
                "⭐ VeritasBot Stars balansida "
                "mablag‘ yetarli emas."
            )
        else:
            await message.reply_text(
                "❌ Gift yuborilmadi."
            )


# =========================================================
# MAIN MESSAGE HANDLER
# =========================================================

async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat

    if not message or not chat:
        return

    text = (
        message.text
        or message.caption
        or ""
    ).strip()

    lower = text.lower()

    # =====================================================
    # PRIVATE CHAT
    # =====================================================

    if chat.type == "private":
        if lower in (
            "/start",
            "/help",
            "*start",
            "*help",
        ):
            await message.reply_text(
                HELP_TEXT
            )
            return

        if lower == "*id":
            await message.reply_text(
                f"🆔 ID: {user.id}"
            )
            return

        if lower.startswith("*topup"):
            parts = text.split()

            if len(parts) != 2:
                await message.reply_text(
                    "⭐ Masalan:\n*topup 100"
                )
                return

            try:
                amount = int(parts[1])
            except ValueError:
                await message.reply_text(
                    "⚠️ Stars miqdorini raqam bilan yozing."
                )
                return

            await topup_stars(
                message,
                user,
                context,
                amount
            )
            return

        await message.reply_text(
            "🤖 VeritasBot\n"
            "Buyruqlar uchun *help yozing."
        )
        return

    # =====================================================
    # GROUP / SUPERGROUP
    # =====================================================

    if chat.type not in (
        "group",
        "supergroup",
    ):
        return

    ensure_settings(chat.id)

    # =====================================================
    # HELP
    # =====================================================

    if lower in (
        "*help",
        "*start",
    ):
        await message.reply_text(
            HELP_TEXT
        )
        return

    # =====================================================
    # ID
    # =====================================================

    if lower == "*id":
        target = reply_target(message)

        if target:
            await message.reply_text(
                f"👤 {get_name(target)}\n"
                f"🆔 ID: {target.id}"
            )
            return

        channel_id = sender_channel_id(message)

        if channel_id:
            await message.reply_text(
                f"📢 Kanal ID: {channel_id}\n"
                f"💬 Guruh ID: {chat.id}"
            )
            return

        await message.reply_text(
            f"👤 {get_name(user)}\n"
            f"🆔 ID: {user.id}\n"
            f"💬 Guruh ID: {chat.id}"
        )
        return

    # =====================================================
    # TOPUP
    # =====================================================

    if lower.startswith("*topup"):
        parts = text.split()

        if len(parts) != 2:
            await message.reply_text(
                "⭐ Masalan:\n*topup 100"
            )
            return

        try:
            amount = int(parts[1])
        except ValueError:
            await message.reply_text(
                "⚠️ Stars miqdorini raqam bilan yozing."
            )
            return

        await topup_stars(
            message,
            user,
            context,
            amount
        )
        return

    # =====================================================
    # GIVE
    # =====================================================

    if lower.startswith("*give"):
        parts = text.split()

        if len(parts) != 2:
            await message.reply_text(
                "🎁 Foydalanish:\n"
                "*give 25\n"
                "*give 50\n"
                "*give 100"
            )
            return

        try:
            amount = int(parts[1])
        except ValueError:
            await message.reply_text(
                "⚠️ Gift miqdori raqam bo‘lishi kerak."
            )
            return

        if amount not in (
            25,
            50,
            100,
        ):
            await message.reply_text(
                "🎁 Ruxsat etilgan miqdor:\n"
                "25 / 50 / 100 Stars"
            )
            return

        await give_gift(
            message,
            user,
            context,
            amount
        )
        return

    # =====================================================
    # VERITAS ADMIN — RUXSAT
    # =====================================================

    if lower == "*ruxsat":
        if not await owner_required(
            message,
            user
        ):
            return

        target = reply_target(message)

        if not target:
            await message.reply_text(
                "⚠️ Odamning xabariga reply qiling."
            )
            return

        cursor.execute(
            """
            INSERT OR IGNORE INTO allowed_users (
                chat_id,
                user_id
            )
            VALUES (?, ?)
            """,
            (
                chat.id,
                target.id
            )
        )

        db.commit()

        await message.reply_text(
            f"🛡 {get_name(target)} ga "
            "Veritas admin huquqi berildi."
        )
        return

    # =====================================================
    # VERITAS ADMIN — RUXSATSIZ
    # =====================================================

    if lower == "*ruxsatsiz":
        if not await owner_required(
            message,
            user
        ):
            return

        target = reply_target(message)

        if not target:
            await message.reply_text(
                "⚠️ Odamning xabariga reply qiling."
            )
            return

        cursor.execute(
            """
            DELETE FROM allowed_users
            WHERE chat_id = ?
              AND user_id = ?
            """,
            (
                chat.id,
                target.id
            )
        )

        db.commit()

        await message.reply_text(
            f"🚫 {get_name(target)} ning "
            "Veritas admin huquqi olib tashlandi."
        )
        return

    # =====================================================
    # ADMINS
    # =====================================================

    if lower == "*admins":
        try:
            admins = await context.bot.get_chat_administrators(
                chat.id
            )

            lines = [
                "👑 TELEGRAM ADMINLARI",
                ""
            ]

            for admin in admins:
                lines.append(
                    f"• {get_name(admin.user)}"
                )

            await message.reply_text(
                "\n".join(lines)
            )

        except Exception as error:
            print(
                "ADMINS ERROR:",
                repr(error)
            )

            await message.reply_text(
                "❌ Adminlar ro‘yxatini olib bo‘lmadi."
            )

        return

    # =====================================================
    # TELEGRAM ADMIN BERISH
    # =====================================================

    if lower == "*admin":
        if not await owner_required(
            message,
            user
        ):
            return

        target = reply_target(message)

        if not target:
            await message.reply_text(
                "⚠️ Admin qilinadigan odamga reply qiling."
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
                can_pin_messages=True
            )

            await message.reply_text(
                f"👑 {get_name(target)} Telegram admin qilindi."
            )

        except Exception as error:
            print(
                "PROMOTE ERROR:",
                repr(error)
            )

            await message.reply_text(
                "❌ Admin qilib bo‘lmadi. "
                "VeritasBot huquqlarini tekshiring."
            )

        return

    # =====================================================
    # TELEGRAM ADMINNI OLISH
    # =====================================================

    if lower == "*unadmin":
        if not await owner_required(
            message,
            user
        ):
            return

        target = reply_target(message)

        if not target:
            await message.reply_text(
                "⚠️ Adminligi olinadigan odamga reply qiling."
            )
            return

        try:
            await context.bot.promote_chat_member(
                chat_id=chat.id,
                user_id=target.id,
                can_manage_chat=False,
                can_delete_messages=False,
                can_manage_video_chats=False,
                can_restrict_members=False,
                can_invite_users=False,
                can_pin_messages=False,
                can_promote_members=False,
                can_change_info=False
            )

            await message.reply_text(
                f"✅ {get_name(target)} adminlikdan olindi."
            )

        except Exception as error:
            print(
                "UNADMIN ERROR:",
                repr(error)
            )

            await message.reply_text(
                "❌ Adminlikni olib bo‘lmadi."
            )

        return
            # =====================================================
    # WARN
    # =====================================================

    if lower == "*warn":
        if not await admin_required(
            message, user, chat, context
        ):
            return

        target = reply_target(message)

        if not target:
            await message.reply_text(
                "⚠️ Ogohlantiriladigan odamning "
                "xabariga reply qiling."
            )
            return

        if target.id == OWNER_ID:
            await message.reply_text(
                "⛔ Veritas egasiga warn berib bo‘lmaydi."
            )
            return

        cursor.execute(
            """
            INSERT INTO warnings (
                chat_id, user_id, warns
            )
            VALUES (?, ?, 1)
            ON CONFLICT(chat_id, user_id)
            DO UPDATE SET warns = warns + 1
            """,
            (chat.id, target.id)
        )
        db.commit()

        cursor.execute(
            """
            SELECT warns
            FROM warnings
            WHERE chat_id = ?
              AND user_id = ?
            """,
            (chat.id, target.id)
        )

        row = cursor.fetchone()
        warns = row[0] if row else 0

        if warns >= 3:
            try:
                await context.bot.ban_chat_member(
                    chat_id=chat.id,
                    user_id=target.id
                )

                cursor.execute(
                    """
                    DELETE FROM warnings
                    WHERE chat_id = ?
                      AND user_id = ?
                    """,
                    (chat.id, target.id)
                )
                db.commit()

                await message.reply_text(
                    f"⛔ {get_name(target)} 3/3 warn "
                    "oldi va ban qilindi."
                )

            except Exception as error:
                print(
                    "AUTO BAN ERROR:",
                    repr(error)
                )

                await message.reply_text(
                    f"⚠️ {get_name(target)}: {warns}/3 warn.\n"
                    "Avtomatik ban amalga oshmadi."
                )

            return

        await message.reply_text(
            f"⚠️ {get_name(target)}: {warns}/3 warn."
        )
        return

    # =====================================================
    # UNWARN
    # =====================================================

    if lower == "*unwarn":
        if not await admin_required(
            message, user, chat, context
        ):
            return

        target = reply_target(message)

        if not target:
            await message.reply_text(
                "⚠️ Odamning xabariga reply qiling."
            )
            return

        cursor.execute(
            """
            SELECT warns
            FROM warnings
            WHERE chat_id = ?
              AND user_id = ?
            """,
            (chat.id, target.id)
        )

        row = cursor.fetchone()
        warns = row[0] if row else 0

        if warns <= 0:
            await message.reply_text(
                "ℹ️ Bu foydalanuvchida warn yo‘q."
            )
            return

        warns -= 1

        if warns == 0:
            cursor.execute(
                """
                DELETE FROM warnings
                WHERE chat_id = ?
                  AND user_id = ?
                """,
                (chat.id, target.id)
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
                    warns,
                    chat.id,
                    target.id
                )
            )

        db.commit()

        await message.reply_text(
            f"✅ {get_name(target)}: {warns}/3 warn."
        )
        return

    # =====================================================
    # WARNS
    # =====================================================

    if lower == "*warns":
        target = reply_target(message) or user

        if not target:
            return

        cursor.execute(
            """
            SELECT warns
            FROM warnings
            WHERE chat_id = ?
              AND user_id = ?
            """,
            (chat.id, target.id)
        )

        row = cursor.fetchone()
        warns = row[0] if row else 0

        await message.reply_text(
            f"⚠️ {get_name(target)}: {warns}/3 warn."
        )
        return

    # =====================================================
    # CLEAR WARNS
    # =====================================================

    if lower == "*clearwarns":
        if not await admin_required(
            message, user, chat, context
        ):
            return

        target = reply_target(message)

        if not target:
            await message.reply_text(
                "⚠️ Odamning xabariga reply qiling."
            )
            return

        cursor.execute(
            """
            DELETE FROM warnings
            WHERE chat_id = ?
              AND user_id = ?
            """,
            (chat.id, target.id)
        )
        db.commit()

        await message.reply_text(
            f"✅ {get_name(target)} ning warnlari tozalandi."
        )
        return

    # =====================================================
    # MUTE
    # =====================================================

    if lower == "*mute":
        if not await admin_required(
            message, user, chat, context
        ):
            return

        target = reply_target(message)

        if not target:
            await message.reply_text(
                "⚠️ Mute qilinadigan odamga reply qiling."
            )
            return

        if target.id == OWNER_ID:
            await message.reply_text(
                "⛔ Veritas egasini mute qilib bo‘lmaydi."
            )
            return

        try:
            await context.bot.restrict_chat_member(
                chat_id=chat.id,
                user_id=target.id,
                permissions=ChatPermissions(
                    can_send_messages=False
                )
            )

            await message.reply_text(
                f"🔇 {get_name(target)} mute qilindi."
            )

        except Exception as error:
            print(
                "MUTE ERROR:",
                repr(error)
            )

            await message.reply_text(
                "❌ Mute qilib bo‘lmadi."
            )

        return

    # =====================================================
    # UNMUTE
    # =====================================================

    if lower == "*unmute":
        if not await admin_required(
            message, user, chat, context
        ):
            return

        target = reply_target(message)

        if not target:
            await message.reply_text(
                "⚠️ Unmute qilinadigan odamga reply qiling."
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

            await message.reply_text(
                f"🔊 {get_name(target)} unmute qilindi."
            )

        except Exception as error:
            print(
                "UNMUTE ERROR:",
                repr(error)
            )

            await message.reply_text(
                "❌ Unmute qilib bo‘lmadi."
            )

        return

    # =====================================================
    # KICK
    # =====================================================

    if lower == "*kick":
        if not await admin_required(
            message, user, chat, context
        ):
            return

        target = reply_target(message)

        if not target:
            await message.reply_text(
                "⚠️ Guruhdan chiqariladigan odamga reply qiling."
            )
            return

        if target.id == OWNER_ID:
            await message.reply_text(
                "⛔ Veritas egasini chiqarib bo‘lmaydi."
            )
            return

        try:
            await context.bot.ban_chat_member(
                chat_id=chat.id,
                user_id=target.id
            )

            await context.bot.unban_chat_member(
                chat_id=chat.id,
                user_id=target.id,
                only_if_banned=True
            )

            await message.reply_text(
                f"👢 {get_name(target)} guruhdan chiqarildi."
            )

        except Exception as error:
            print(
                "KICK ERROR:",
                repr(error)
            )

            await message.reply_text(
                "❌ Guruhdan chiqarib bo‘lmadi."
            )

        return

    # =====================================================
    # BAN
    # =====================================================

    if lower == "*ban":
        if not await admin_required(
            message, user, chat, context
        ):
            return

        target = reply_target(message)

        if not target:
            await message.reply_text(
                "⚠️ Ban qilinadigan odamga reply qiling."
            )
            return

        if target.id == OWNER_ID:
            await message.reply_text(
                "⛔ Veritas egasini ban qilib bo‘lmaydi."
            )
            return

        try:
            await context.bot.ban_chat_member(
                chat_id=chat.id,
                user_id=target.id
            )

            await message.reply_text(
                f"⛔ {get_name(target)} ban qilindi."
            )

        except Exception as error:
            print(
                "BAN ERROR:",
                repr(error)
            )

            await message.reply_text(
                "❌ Ban qilib bo‘lmadi."
            )

        return

    # =====================================================
    # UNBAN — REPLY YOKI ID
    # =====================================================

    if lower.startswith("*unban"):
        if not await admin_required(
            message, user, chat, context
        ):
            return

        target = reply_target(message)

        if target:
            target_id = target.id
            target_name = get_name(target)

        else:
            parts = text.split()

            if len(parts) != 2:
                await message.reply_text(
                    "⚠️ Reply qiling yoki ID yozing:\n"
                    "*unban 123456789"
                )
                return

            try:
                target_id = int(parts[1])
                target_name = str(target_id)

            except ValueError:
                await message.reply_text(
                    "⚠️ ID raqam bo‘lishi kerak."
                )
                return

        try:
            await context.bot.unban_chat_member(
                chat_id=chat.id,
                user_id=target_id,
                only_if_banned=True
            )

            cursor.execute(
                """
                DELETE FROM warnings
                WHERE chat_id = ?
                  AND user_id = ?
                """,
                (chat.id, target_id)
            )
            db.commit()

            await message.reply_text(
                f"✅ {target_name} ban holatidan chiqarildi."
            )

        except Exception as error:
            print(
                "UNBAN ERROR:",
                repr(error)
            )

            await message.reply_text(
                "❌ Unban qilib bo‘lmadi."
            )

        return

    # =====================================================
    # DELETE
    # =====================================================

    if lower == "*del":
        if not await admin_required(
            message, user, chat, context
        ):
            return

        if not message.reply_to_message:
            await message.reply_text(
                "⚠️ O‘chiriladigan xabarga reply qilib "
                "*del yozing."
            )
            return

        try:
            await context.bot.delete_message(
                chat_id=chat.id,
                message_id=(
                    message.reply_to_message.message_id
                )
            )

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
                "❌ Xabarni o‘chirib bo‘lmadi."
            )

        return
            # =====================================================
    # APPROVE
    # =====================================================

    if lower == "*approve":
        if not await admin_required(
            message, user, chat, context
        ):
            return

        target = reply_target(message)

        if not target:
            await message.reply_text(
                "⚠️ Tasdiqlanadigan odamning xabariga reply qiling."
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
            f"✅ {get_name(target)} tasdiqlandi.\n"
            "Himoya cheklovlari unga qo‘llanmaydi."
        )
        return

    # =====================================================
    # UNAPPROVE
    # =====================================================

    if lower == "*unapprove":
        if not await admin_required(
            message, user, chat, context
        ):
            return

        target = reply_target(message)

        if not target:
            await message.reply_text(
                "⚠️ Odamning xabariga reply qiling."
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
            f"🚫 {get_name(target)} tasdiqlanganlar "
            "ro‘yxatidan chiqarildi."
        )
        return

    # =====================================================
    # APPROVED
    # =====================================================

    if lower == "*approved":
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
                "✅ Tasdiqlangan foydalanuvchilar yo‘q."
            )
            return

        lines = ["✅ TASDIQLANGANLAR", ""]

        for row in rows:
            lines.append(
                f"• ID: {row[0]}"
            )

        await message.reply_text(
            "\n".join(lines)
        )
        return

    # =====================================================
    # REPORT SETTINGS
    # =====================================================

    if lower in (
        "*reports on",
        "*reports off",
    ):
        if not await admin_required(
            message, user, chat, context
        ):
            return

        enabled = (
            1
            if lower == "*reports on"
            else 0
        )

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
            "📢 Report tizimi "
            + ("yoqildi." if enabled else "o‘chirildi.")
        )
        return

    # =====================================================
    # REPORT
    # =====================================================

    if lower == "*report":
        if not message.reply_to_message:
            await message.reply_text(
                "⚠️ Shikoyat qilinadigan xabarga "
                "reply qilib *report yozing."
            )
            return

        cursor.execute(
            """
            SELECT reports
            FROM settings
            WHERE chat_id = ?
            """,
            (chat.id,)
        )

        row = cursor.fetchone()

        if row and not row[0]:
            await message.reply_text(
                "ℹ️ Bu guruhda report tizimi o‘chirilgan."
            )
            return

        target = reply_target(message)

        target_name = (
            get_name(target)
            if target
            else "xabar"
        )

        await message.reply_text(
            "🚨 ADMINLARGA MUROJAAT\n"
            f"Shikoyat qiluvchi: {get_name(user)}\n"
            f"Shikoyat: {target_name}\n"
            "Adminlar ushbu xabarni tekshiring."
        )
        return

    # =====================================================
    # LINKS ON / OFF
    # =====================================================

    if lower in (
        "*links on",
        "*links off",
    ):
        if not await admin_required(
            message, user, chat, context
        ):
            return

        enabled = (
            1
            if lower == "*links on"
            else 0
        )

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
            + ("yoqildi." if enabled else "o‘chirildi.")
        )
        return

    # =====================================================
    # LOCK
    # =====================================================

    if lower.startswith("*lock "):
        if not await admin_required(
            message, user, chat, context
        ):
            return

        lock_type = (
            text[len("*lock "):]
            .strip()
            .lower()
        )

        allowed_locks = {
            "links",
            "photo",
            "video",
            "sticker",
            "animation",
            "document",
            "voice",
            "audio",
        }

        if lock_type not in allowed_locks:
            await message.reply_text(
                "⚠️ Lock turlari:\n"
                "links, photo, video, sticker,\n"
                "animation, document, voice, audio"
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
        return

    # =====================================================
    # UNLOCK
    # =====================================================

    if lower.startswith("*unlock "):
        if not await admin_required(
            message, user, chat, context
        ):
            return

        lock_type = (
            text[len("*unlock "):]
            .strip()
            .lower()
        )

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
        return

    # =====================================================
    # LOCKS
    # =====================================================

    if lower == "*locks":
        locked = get_locks(chat.id)

        if not locked:
            await message.reply_text(
                "🔓 Hozir hech narsa lock qilinmagan."
            )
            return

        await message.reply_text(
            "🔒 LOCKLAR\n\n"
            + "\n".join(
                f"• {item}"
                for item in locked
            )
        )
        return

    # =====================================================
    # ANTI-FLOOD ON / OFF
    # =====================================================

    if lower in (
        "*antiflood on",
        "*antiflood off",
    ):
        if not await admin_required(
            message, user, chat, context
        ):
            return

        enabled = (
            1
            if lower == "*antiflood on"
            else 0
        )

        cursor.execute(
            """
            UPDATE settings
            SET antiflood = ?
            WHERE chat_id = ?
            """,
            (enabled, chat.id)
        )
        db.commit()

        await message.reply_text(
            "🌊 Anti-flood "
            + ("yoqildi." if enabled else "o‘chirildi.")
        )
        return

    # =====================================================
    # FLOOD LIMIT
    # =====================================================

    if lower.startswith("*flood "):
        if not await admin_required(
            message, user, chat, context
        ):
            return

        parts = text.split()

        if len(parts) != 2:
            await message.reply_text(
                "⚠️ Masalan: *flood 5"
            )
            return

        try:
            limit = int(parts[1])
        except ValueError:
            await message.reply_text(
                "⚠️ Limit raqam bo‘lishi kerak."
            )
            return

        if limit < 3 or limit > 20:
            await message.reply_text(
                "⚠️ Flood limiti 3 dan 20 gacha bo‘lsin."
            )
            return

        cursor.execute(
            """
            UPDATE settings
            SET flood_limit = ?
            WHERE chat_id = ?
            """,
            (limit, chat.id)
        )
        db.commit()

        await message.reply_text(
            f"🌊 Flood limiti: {limit} ta xabar."
        )
        return
            # =====================================================
    # BLACKLIST ADD
    # =====================================================

    if lower.startswith("*blacklist "):
        if not await admin_required(
            message, user, chat, context
        ):
            return

        word = text[len("*blacklist "):].strip().lower()

        if not word:
            await message.reply_text(
                "⚠️ Masalan: *blacklist reklama"
            )
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
            f"🚫 Blacklistga qo‘shildi: {word}"
        )
        return

    # =====================================================
    # BLACKLIST REMOVE
    # =====================================================

    if lower.startswith("*unblacklist "):
        if not await admin_required(
            message, user, chat, context
        ):
            return

        word = text[len("*unblacklist "):].strip().lower()

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
            f"✅ Blacklistdan olindi: {word}"
        )
        return

    # =====================================================
    # BLACKLISTS
    # =====================================================

    if lower == "*blacklists":
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

        await message.reply_text(
            "🚫 BLACKLIST\n\n"
            + "\n".join(
                f"• {row[0]}"
                for row in rows
            )
        )
        return

    # =====================================================
    # FILTER ADD
    # =====================================================

    if lower.startswith("*filter "):
        if not await admin_required(
            message, user, chat, context
        ):
            return

        content = text[len("*filter "):].strip()

        if not content:
            await message.reply_text(
                "⚠️ Masalan:\n"
                "*filter salom Va alaykum assalom"
            )
            return

        parts = content.split(maxsplit=1)
        keyword = parts[0].lower()

        # Reply qilingan media bo‘lsa, mediani saqlaymiz
        if message.reply_to_message:
            replied = message.reply_to_message

            media_type, file_id = media_from_message(
                replied
            )

            if media_type != "text":
                response = (
                    parts[1]
                    if len(parts) > 1
                    else ""
                )

                caption = (
                    replied.caption
                    or response
                    or ""
                )

                cursor.execute(
                    """
                    INSERT OR REPLACE INTO chat_filters (
                        chat_id,
                        keyword,
                        response,
                        media_type,
                        file_id,
                        caption
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chat.id,
                        keyword,
                        response,
                        media_type,
                        file_id,
                        caption
                    )
                )
                db.commit()

                await message.reply_text(
                    f"✅ Media filter saqlandi: {keyword}"
                )
                return

        # Oddiy matn filter
        if len(parts) < 2:
            await message.reply_text(
                "⚠️ Matn filter uchun javob ham yozing:\n"
                "*filter salom Va alaykum assalom"
            )
            return

        response = parts[1]

        cursor.execute(
            """
            INSERT OR REPLACE INTO chat_filters (
                chat_id,
                keyword,
                response,
                media_type,
                file_id,
                caption
            )
            VALUES (?, ?, ?, 'text', '', '')
            """,
            (
                chat.id,
                keyword,
                response
            )
        )
        db.commit()

        await message.reply_text(
            f"✅ Filter saqlandi: {keyword}"
        )
        return

    # =====================================================
    # FILTERS
    # =====================================================

    if lower == "*filters":
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
                "💬 Filterlar yo‘q."
            )
            return

        lines = ["💬 FILTERLAR", ""]

        for keyword, media_type in rows:
            if media_type == "text":
                lines.append(f"• {keyword}")
            else:
                lines.append(
                    f"• {keyword} [{media_type}]"
                )

        await message.reply_text(
            "\n".join(lines)
        )
        return

    # =====================================================
    # STOP FILTER
    # =====================================================

    if lower.startswith("*stop "):
        if not await admin_required(
            message, user, chat, context
        ):
            return

        keyword = text[len("*stop "):].strip().lower()

        cursor.execute(
            """
            DELETE FROM chat_filters
            WHERE chat_id = ?
              AND keyword = ?
            """,
            (chat.id, keyword)
        )
        db.commit()

        await message.reply_text(
            f"🗑 Filter o‘chirildi: {keyword}"
        )
        return

    # =====================================================
    # STOP ALL FILTERS
    # =====================================================

    if lower == "*stopall":
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
        db.commit()

        await message.reply_text(
            "🗑 Barcha filterlar o‘chirildi."
        )
        return

    # =====================================================
    # SAVE NOTE
    # =====================================================

    if lower.startswith("*save "):
        if not await admin_required(
            message, user, chat, context
        ):
            return

        content = text[len("*save "):].strip()
        parts = content.split(maxsplit=1)

        if len(parts) < 2:
            await message.reply_text(
                "⚠️ Masalan:\n"
                "*save aloqa Admin: @username"
            )
            return

        name = parts[0].lower()
        note_text = parts[1]

        cursor.execute(
            """
            INSERT OR REPLACE INTO notes (
                chat_id,
                name,
                content
            )
            VALUES (?, ?, ?)
            """,
            (
                chat.id,
                name,
                note_text
            )
        )
        db.commit()

        await message.reply_text(
            f"📝 Note saqlandi: {name}"
        )
        return

    # =====================================================
    # GET NOTE
    # =====================================================

    if lower.startswith("*get "):
        name = text[len("*get "):].strip().lower()

        cursor.execute(
            """
            SELECT content
            FROM notes
            WHERE chat_id = ?
              AND name = ?
            """,
            (chat.id, name)
        )

        row = cursor.fetchone()

        if not row:
            await message.reply_text(
                "⚠️ Bunday note topilmadi."
            )
            return

        await message.reply_text(
            row[0]
        )
        return

    # =====================================================
    # NOTES LIST
    # =====================================================

    if lower == "*notes":
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
                "📝 Notelar yo‘q."
            )
            return

        await message.reply_text(
            "📝 NOTELAR\n\n"
            + "\n".join(
                f"• {row[0]}"
                for row in rows
            )
        )
        return

    # =====================================================
    # CLEAR NOTE
    # =====================================================

    if lower.startswith("*clear "):
        if not await admin_required(
            message, user, chat, context
        ):
            return

        name = text[len("*clear "):].strip().lower()

        cursor.execute(
            """
            DELETE FROM notes
            WHERE chat_id = ?
              AND name = ?
            """,
            (chat.id, name)
        )
        db.commit()

        await message.reply_text(
            f"🗑 Note o‘chirildi: {name}"
        )
        return

    # =====================================================
    # SET RULES
    # =====================================================

    if lower.startswith("*setrules "):
        if not await admin_required(
            message, user, chat, context
        ):
            return

        rules_text = text[len("*setrules "):].strip()

        cursor.execute(
            """
            UPDATE settings
            SET rules = ?
            WHERE chat_id = ?
            """,
            (
                rules_text,
                chat.id
            )
        )
        db.commit()

        await message.reply_text(
            "📜 Guruh qoidalari saqlandi."
        )
        return

    # =====================================================
    # RULES
    # =====================================================

    if lower == "*rules":
        cursor.execute(
            """
            SELECT rules
            FROM settings
            WHERE chat_id = ?
            """,
            (chat.id,)
        )

        row = cursor.fetchone()
        rules_text = row[0] if row else ""

        if not rules_text:
            await message.reply_text(
                "📜 Guruh qoidalari hali yozilmagan."
            )
            return

        await message.reply_text(
            "📜 GURUH QOIDALARI\n\n"
            + rules_text
        )
        return

    # =====================================================
    # WELCOME ON / OFF
    # =====================================================

    if lower in (
        "*welcome on",
        "*welcome off",
    ):
        if not await admin_required(
            message, user, chat, context
        ):
            return

        enabled = (
            1
            if lower == "*welcome on"
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
            + ("yoqildi." if enabled else "o‘chirildi.")
        )
        return

    # =====================================================
    # GOODBYE ON / OFF
    # =====================================================

    if lower in (
        "*goodbye on",
        "*goodbye off",
    ):
        if not await admin_required(
            message, user, chat, context
        ):
            return

        enabled = (
            1
            if lower == "*goodbye on"
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
            + ("yoqildi." if enabled else "o‘chirildi.")
        )
        return
            # =====================================================
    # MEN — SHAXSIY FAOLLIK
    # =====================================================

    if lower == "*men":
        if not user:
            await message.reply_text(
                "ℹ️ Kanal nomidan yozilganda *men ishlamaydi."
            )
            return

        cursor.execute(
            """
            SELECT messages
            FROM activity
            WHERE chat_id = ?
              AND user_id = ?
            """,
            (chat.id, user.id)
        )

        row = cursor.fetchone()
        messages = row[0] if row else 0

        await message.reply_text(
            f"👤 {get_name(user)}\n"
            f"💬 Xabarlar: {messages}"
        )
        return

    # =====================================================
    # AKTIV
    # =====================================================

    if lower == "*aktiv" or lower.startswith("*aktiv "):
        parts = text.split()

        limit = 10

        if len(parts) == 2:
            try:
                limit = int(parts[1])
            except ValueError:
                await message.reply_text(
                    "⚠️ Masalan: *aktiv 10"
                )
                return

        if limit < 1:
            limit = 1

        if limit > 50:
            limit = 50

        cursor.execute(
            """
            SELECT name, username, messages
            FROM activity
            WHERE chat_id = ?
            ORDER BY messages DESC
            LIMIT ?
            """,
            (chat.id, limit)
        )

        rows = cursor.fetchall()

        if not rows:
            await message.reply_text(
                "📊 Hali faollik ma’lumoti yo‘q."
            )
            return

        lines = [
            f"🏆 TOP {limit} FAOL A’ZO",
            ""
        ]

        medals = {
            1: "🥇",
            2: "🥈",
            3: "🥉",
        }

        for number, row in enumerate(
            rows,
            start=1
        ):
            name, username, count = row

            icon = medals.get(
                number,
                f"{number}."
            )

            display_name = (
                f"@{username}"
                if username
                else name
            )

            lines.append(
                f"{icon} {display_name} — {count}"
            )

        await message.reply_text(
            "\n".join(lines)
        )
        return

    # =====================================================
    # KANAL NOMIDAN YOZILGAN ODDIY XABAR
    # =====================================================

    if not user:
        return

    # =====================================================
    # ADMIN / APPROVED HOLATI
    # =====================================================

    protected = (
        is_owner_source(message, user)
        or await is_telegram_admin(
            chat,
            user.id,
            context
        )
        or await is_internal_admin(
            chat.id,
            user.id
        )
        or is_approved(
            chat.id,
            user.id
        )
    )

    # =====================================================
    # ACTIVITY COUNT
    # =====================================================

    if not user.is_bot:
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
                chat.id,
                user.id,
                name,
                username
            )
        )

        db.commit()

    # =====================================================
    # HIMOYA SOZLAMALARI
    # =====================================================

    cursor.execute(
        """
        SELECT
            link_block,
            antiflood,
            flood_limit
        FROM settings
        WHERE chat_id = ?
        """,
        (chat.id,)
    )

    setting_row = cursor.fetchone()

    if setting_row:
        link_block = setting_row[0]
        antiflood = setting_row[1]
        flood_limit = setting_row[2]
    else:
        link_block = 0
        antiflood = 0
        flood_limit = 5

    # =====================================================
    # LINK PROTECTION
    # =====================================================

    if not protected:
        locked = get_locks(chat.id)

        link_locked = (
            link_block
            or "links" in locked
        )

        if link_locked and contains_link(text):
            try:
                await message.delete()

                await context.bot.send_message(
                    chat_id=chat.id,
                    text=(
                        f"🔗 {get_name(user)}, "
                        "guruhda link yuborish taqiqlangan."
                    )
                )

            except Exception as error:
                print(
                    "LINK DELETE ERROR:",
                    repr(error)
                )

            return

    # =====================================================
    # MEDIA LOCK PROTECTION
    # =====================================================

    if not protected:
        locked = get_locks(chat.id)

        blocked_type = None

        if message.photo and "photo" in locked:
            blocked_type = "photo"

        elif message.video and "video" in locked:
            blocked_type = "video"

        elif message.sticker and "sticker" in locked:
            blocked_type = "sticker"

        elif (
            message.animation
            and "animation" in locked
        ):
            blocked_type = "animation"

        elif (
            message.document
            and "document" in locked
        ):
            blocked_type = "document"

        elif message.voice and "voice" in locked:
            blocked_type = "voice"

        elif message.audio and "audio" in locked:
            blocked_type = "audio"

        if blocked_type:
            try:
                await message.delete()

                await context.bot.send_message(
                    chat_id=chat.id,
                    text=(
                        f"🔒 {get_name(user)}, "
                        f"{blocked_type} yuborish bloklangan."
                    )
                )

            except Exception as error:
                print(
                    "MEDIA LOCK ERROR:",
                    repr(error)
                )

            return

    # =====================================================
    # BLACKLIST PROTECTION
    # =====================================================

    if text and not protected:
        cursor.execute(
            """
            SELECT word
            FROM blacklist
            WHERE chat_id = ?
            """,
            (chat.id,)
        )

        blacklist_words = cursor.fetchall()

        text_lower = text.lower()

        for row in blacklist_words:
            word = row[0].lower()

            if word and word in text_lower:
                try:
                    await message.delete()

                    await context.bot.send_message(
                        chat_id=chat.id,
                        text=(
                            f"🚫 {get_name(user)}, "
                            "taqiqlangan so‘z ishlatildi."
                        )
                    )

                except Exception as error:
                    print(
                        "BLACKLIST ERROR:",
                        repr(error)
                    )

                return

    # =====================================================
    # ANTI-FLOOD
    # 5 soniya ichidagi tezkor xabarlarni hisoblaydi
    # =====================================================

    if antiflood and not protected:
        now = time.time()

        cursor.execute(
            """
            SELECT count, last_time
            FROM flood_data
            WHERE chat_id = ?
              AND user_id = ?
            """,
            (
                chat.id,
                user.id
            )
        )

        flood_row = cursor.fetchone()

        if flood_row:
            old_count = flood_row[0]
            last_time = flood_row[1]

            if now - last_time <= 5:
                new_count = old_count + 1
            else:
                new_count = 1
        else:
            new_count = 1

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
                new_count,
                now
            )
        )

        db.commit()

        if new_count >= flood_limit:
            try:
                await context.bot.restrict_chat_member(
                    chat_id=chat.id,
                    user_id=user.id,
                    permissions=ChatPermissions(
                        can_send_messages=False
                    )
                )

                cursor.execute(
                    """
                    DELETE FROM flood_data
                    WHERE chat_id = ?
                      AND user_id = ?
                    """,
                    (
                        chat.id,
                        user.id
                    )
                )

                db.commit()

                await context.bot.send_message(
                    chat_id=chat.id,
                    text=(
                        f"🌊 {get_name(user)} flood sababli "
                        "mute qilindi."
                    )
                )

            except Exception as error:
                print(
                    "ANTIFLOOD ERROR:",
                    repr(error)
                )

            return

    # =====================================================
    # AUTOMATIC FILTER RESPONSE
    # =====================================================

    if text and not text.startswith("*"):
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
            """,
            (chat.id,)
        )

        saved_filters = cursor.fetchall()
        text_lower = text.lower()

        for saved in saved_filters:
            (
                keyword,
                response,
                media_type,
                file_id,
                caption
            ) = saved

            if keyword.lower() in text_lower:
                try:
                    await send_saved_filter(
                        message,
                        context,
                        media_type,
                        file_id,
                        response,
                        caption
                    )

                except Exception as error:
                    print(
                        "FILTER RESPONSE ERROR:",
                        repr(error)
                    )

                return
                # =========================================================
# MAIN
# =========================================================

def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN topilmadi. Railway Variables ni tekshiring."
        )

    app = Application.builder().token(BOT_TOKEN).build()

    # Yangi a'zo
    app.add_handler(
        MessageHandler(
            filters.StatusUpdate.NEW_CHAT_MEMBERS,
            welcome_new_member
        ),
        group=0
    )

    # Guruhdan chiqqan a'zo
    app.add_handler(
        MessageHandler(
            filters.StatusUpdate.LEFT_CHAT_MEMBER,
            goodbye_member
        ),
        group=0
    )

    # Telegram Stars to'lovini tasdiqlash
    app.add_handler(
        PreCheckoutQueryHandler(
            precheckout_callback
        ),
        group=0
    )

    # Muvaffaqiyatli Stars to'lovi
    app.add_handler(
        MessageHandler(
            filters.SUCCESSFUL_PAYMENT,
            successful_payment
        ),
        group=0
    )

    # Barcha oddiy xabarlar va * komandalar
    app.add_handler(
        MessageHandler(
            filters.ALL
            & ~filters.StatusUpdate.NEW_CHAT_MEMBERS
            & ~filters.StatusUpdate.LEFT_CHAT_MEMBER
            & ~filters.SUCCESSFUL_PAYMENT,
            handle_message
        ),
        group=1
    )

    print("VeritasBot v6 ishga tushdi.")

    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=False
    )


if __name__ == "__main__":
    main()
