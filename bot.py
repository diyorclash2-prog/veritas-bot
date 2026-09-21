import os
import re
import sqlite3

from telegram import Update, ChatPermissions
from telegram.ext import (
    Application,
    ContextTypes,
    MessageHandler,
    filters,
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = 5859289233

db = sqlite3.connect(
    "veritas.db",
    check_same_thread=False
)
cursor = db.cursor()


# ==================================================
# DATABASE
# ==================================================

cursor.execute("""
CREATE TABLE IF NOT EXISTS activity (
    chat_id INTEGER,
    user_id INTEGER,
    name TEXT,
    username TEXT,
    messages INTEGER DEFAULT 0,
    PRIMARY KEY (chat_id, user_id)
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS chat_filters (
    chat_id INTEGER,
    keyword TEXT,
    response TEXT,
    media_type TEXT DEFAULT 'text',
    file_id TEXT DEFAULT '',
    caption TEXT DEFAULT '',
    PRIMARY KEY (chat_id, keyword)
)
""")

# Eski bazaga yangi filter ustunlarini qo'shish
for column, definition in [
    ("media_type", "TEXT DEFAULT 'text'"),
    ("file_id", "TEXT DEFAULT ''"),
    ("caption", "TEXT DEFAULT ''"),
]:
    try:
        cursor.execute(
            f"ALTER TABLE chat_filters "
            f"ADD COLUMN {column} {definition}"
        )
    except sqlite3.OperationalError:
        pass


cursor.execute("""
CREATE TABLE IF NOT EXISTS warnings (
    chat_id INTEGER,
    user_id INTEGER,
    warns INTEGER DEFAULT 0,
    PRIMARY KEY (chat_id, user_id)
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS blacklist (
    chat_id INTEGER,
    word TEXT,
    PRIMARY KEY (chat_id, word)
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS settings (
    chat_id INTEGER PRIMARY KEY,
    link_block INTEGER DEFAULT 0,
    welcome INTEGER DEFAULT 1,
    goodbye INTEGER DEFAULT 1,
    rules TEXT DEFAULT ''
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS notes (
    chat_id INTEGER,
    name TEXT,
    content TEXT,
    PRIMARY KEY (chat_id, name)
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS allowed_users (
    user_id INTEGER PRIMARY KEY
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS games (
    chat_id INTEGER PRIMARY KEY,
    player1_id INTEGER,
    player1_name TEXT,
    player2_id INTEGER,
    player2_name TEXT,
    choice1 TEXT DEFAULT '',
    choice2 TEXT DEFAULT ''
)
""")

db.commit()


# ==================================================
# YORDAMCHI FUNKSIYALAR
# ==================================================

def get_name(user):
    if user.username:
        return f"@{user.username}"

    return user.full_name


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


def contains_link(text):
    pattern = (
        r"(https?://|www\.|t\.me/|telegram\.me/)"
    )

    return bool(
        re.search(
            pattern,
            text,
            re.IGNORECASE
        )
    )


def is_allowed(user_id):
    cursor.execute(
        """
        SELECT 1 FROM allowed_users
        WHERE user_id = ?
        """,
        (user_id,)
    )

    return cursor.fetchone() is not None


async def is_telegram_admin(
    chat,
    user_id,
    context
):
    if user_id == OWNER_ID:
        return True

    try:
        member = await context.bot.get_chat_member(
            chat.id,
            user_id
        )

        return member.status in (
            "administrator",
            "creator",
            "owner"
        )

    except Exception:
        return False


async def is_admin(
    chat,
    user_id,
    context
):
    if user_id == OWNER_ID:
        return True

    if is_allowed(user_id):
        return True

    return await is_telegram_admin(
        chat,
        user_id,
        context
    )


async def admin_required(
    message,
    chat,
    user,
    context
):
    if await is_admin(
        chat,
        user.id,
        context
    ):
        return True

    await message.reply_text(
        "⛔ Bu buyruq faqat adminlar uchun."
    )

    return False


async def telegram_admin_required(
    message,
    chat,
    user,
    context
):
    if await is_telegram_admin(
        chat,
        user.id,
        context
    ):
        return True

    await message.reply_text(
        "⛔ Bu buyruq uchun Telegram "
        "guruh admini bo‘lish kerak."
    )

    return False


# ==================================================
# HELP
# ==================================================

HELP_TEXT = """
🛡 VERITAS BUYRUQLARI

👤 UMUMIY
*id — Telegram ID
*men — shaxsiy statistika
*aktiv — TOP 50
*aktiv 10 — TOP 10
*rules — guruh qoidalari
*warns — ogohlantirishlar

🛡 MODERATSIYA
*warn — ogohlantirish
*unwarn — bitta warn olib tashlash
*clearwarns — warnlarni tozalash
*mute — yozishni taqiqlash
*unmute — yozishni ochish
*kick — guruhdan chiqarish
*ban — bloklash
*unban ID — blokdan chiqarish
*unban — reply orqali blokdan chiqarish
*del — xabarni o‘chirish

👮 TELEGRAM ADMIN
*admin — reply qilib admin berish
*unadmin — reply qilib adminlikdan olish

🔐 VERITAS ADMIN
*ruxsat — Veritas ruxsati berish
*ruxsatsiz — Veritas ruxsatini olish

🔗 HIMOYA
*links on
*links off
*blacklist so‘z
*unblacklist so‘z
*blacklists

💬 FILTER
*filter kalit javob
*filter kalit — media xabariga reply
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
*admins

✊ DON-DON-ZIKI
*ddz — o‘yin ochish
*ddzjoin — o‘yinga qo‘shilish
*tosh — ✊
*qogoz — ✋
*qaychi — ✌️
*ddzcancel — o‘yinni bekor qilish
""".strip()


# ==================================================
# YANGI A'ZO
# ==================================================

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
        SELECT welcome FROM settings
        WHERE chat_id = ?
        """,
        (chat.id,)
    )

    row = cursor.fetchone()

    if not row or row[0] == 0:
        return

    for member in message.new_chat_members:

        if member.is_bot:
            continue

        await message.reply_text(
            f"👋 Xush kelibsiz, "
            f"{member.full_name}!\n\n"
            f"📚 {chat.title} guruhiga "
            f"xush kelibsiz."
        )


# ==================================================
# CHIQIB KETGAN A'ZO
# ==================================================

async def goodbye_member(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    message = update.effective_message
    chat = update.effective_chat

    if not message or not chat:
        return

    member = message.left_chat_member

    if not member or member.is_bot:
        return

    ensure_settings(chat.id)

    cursor.execute(
        """
        SELECT goodbye FROM settings
        WHERE chat_id = ?
        """,
        (chat.id,)
    )

    row = cursor.fetchone()

    if row and row[0]:
        await message.reply_text(
            f"👋 {member.full_name} "
            "guruhni tark etdi."
        )


# ==================================================
# MEDIA FILTER YORDAMCHILARI
# ==================================================

def media_from_message(message):

    if message.sticker:
        return (
            "sticker",
            message.sticker.file_id,
            ""
        )

    if message.photo:
        return (
            "photo",
            message.photo[-1].file_id,
            message.caption or ""
        )

    if message.video:
        return (
            "video",
            message.video.file_id,
            message.caption or ""
        )

    if message.animation:
        return (
            "animation",
            message.animation.file_id,
            message.caption or ""
        )

    if message.audio:
        return (
            "audio",
            message.audio.file_id,
            message.caption or ""
        )

    if message.voice:
        return (
            "voice",
            message.voice.file_id,
            ""
        )

    if message.document:
        return (
            "document",
            message.document.file_id,
            message.caption or ""
        )

    return None, None, None


async def send_saved_filter(
    message,
    media_type,
    file_id,
    response,
    caption
):

    if media_type == "text":
        await message.reply_text(
            response
        )

    elif media_type == "sticker":
        await message.reply_sticker(
            file_id
        )

    elif media_type == "photo":
        await message.reply_photo(
            file_id,
            caption=caption or None
        )

    elif media_type == "video":
        await message.reply_video(
            file_id,
            caption=caption or None
        )

    elif media_type == "animation":
        await message.reply_animation(
            file_id,
            caption=caption or None
        )

    elif media_type == "audio":
        await message.reply_audio(
            file_id,
            caption=caption or None
        )

    elif media_type == "voice":
        await message.reply_voice(
            file_id
        )

    elif media_type == "document":
        await message.reply_document(
            file_id,
            caption=caption or None
        )


# ==================================================
# DON-DON-ZIKI
# ==================================================

CHOICES = {
    "*tosh": "tosh",
    "*qogoz": "qogoz",
    "*qaychi": "qaychi",
}

ICONS = {
    "tosh": "✊",
    "qogoz": "✋",
    "qaychi": "✌️",
}


def ddz_winner(first, second):

    if first == second:
        return 0
        # ==================================================
# DON-DON-ZIKI HANDLER
# ==================================================

async def handle_ddz(
    message,
    chat,
    user,
    command,
    context
):

    if command == "*ddz":

        cursor.execute(
            """
            SELECT chat_id FROM games
            WHERE chat_id = ?
            """,
            (chat.id,)
        )

        if cursor.fetchone():
            await message.reply_text(
                "⚠️ Bu guruhda hozir o‘yin bor."
            )
            return True

        cursor.execute(
            """
            INSERT INTO games (
                chat_id,
                player1_id,
                player1_name,
                player2_id,
                player2_name
            )
            VALUES (?, ?, ?, NULL, '')
            """,
            (
                chat.id,
                user.id,
                get_name(user)
            )
        )

        db.commit()

        await message.reply_text(
            "✊✋✌️ DON-DON-ZIKI\n\n"
            f"{get_name(user)} o‘yin ochdi.\n\n"
            "Ikkinchi o‘yinchi:\n"
            "*ddzjoin"
        )

        return True


    if command == "*ddzjoin":

        cursor.execute(
            """
            SELECT
                player1_id,
                player1_name,
                player2_id
            FROM games
            WHERE chat_id = ?
            """,
            (chat.id,)
        )

        row = cursor.fetchone()

        if not row:
            await message.reply_text(
                "⚠️ Ochiq o‘yin yo‘q.\n"
                "*ddz bilan o‘yin oching."
            )
            return True

        if row[2]:
            await message.reply_text(
                "⚠️ O‘yinga ikki kishi "
                "allaqachon qo‘shilgan."
            )
            return True

        if row[0] == user.id:
            await message.reply_text(
                "⚠️ O‘zingiz bilan "
                "o‘ynay olmaysiz."
            )
            return True

        cursor.execute(
            """
            UPDATE games
            SET
                player2_id = ?,
                player2_name = ?
            WHERE chat_id = ?
            """,
            (
                user.id,
                get_name(user),
                chat.id
            )
        )

        db.commit()

        await message.reply_text(
            "🎮 O‘YIN BOSHLANDI\n\n"
            f"{row[1]}\n"
            "VS\n"
            f"{get_name(user)}\n\n"
            "Tanlang:\n"
            "*tosh ✊\n"
            "*qogoz ✋\n"
            "*qaychi ✌️"
        )

        return True


    if command in CHOICES:

        cursor.execute(
            """
            SELECT
                player1_id,
                player1_name,
                player2_id,
                player2_name,
                choice1,
                choice2
            FROM games
            WHERE chat_id = ?
            """,
            (chat.id,)
        )

        row = cursor.fetchone()

        if not row or not row[2]:
            return False

        player1_id = row[0]
        player1_name = row[1]
        player2_id = row[2]
        player2_name = row[3]
        choice1 = row[4]
        choice2 = row[5]

        choice = CHOICES[command]

        if user.id == player1_id:

            choice1 = choice

            cursor.execute(
                """
                UPDATE games
                SET choice1 = ?
                WHERE chat_id = ?
                """,
                (
                    choice,
                    chat.id
                )
            )

        elif user.id == player2_id:

            choice2 = choice

            cursor.execute(
                """
                UPDATE games
                SET choice2 = ?
                WHERE chat_id = ?
                """,
                (
                    choice,
                    chat.id
                )
            )

        else:
            return False

        db.commit()

        if not choice1 or not choice2:

            await message.reply_text(
                f"✅ {get_name(user)} "
                "tanlov qildi."
            )

            return True

        winner = ddz_winner(
            choice1,
            choice2
        )

        if winner == 0:
            result = "🤝 Durrang!"

        elif winner == 1:
            result = (
                f"🏆 G‘olib: "
                f"{player1_name}"
            )

        else:
            result = (
                f"🏆 G‘olib: "
                f"{player2_name}"
            )

        await message.reply_text(
            "✊✋✌️ NATIJA\n\n"
            f"{player1_name}: "
            f"{ICONS[choice1]}\n"
            f"{player2_name}: "
            f"{ICONS[choice2]}\n\n"
            f"{result}"
        )

        cursor.execute(
            """
            DELETE FROM games
            WHERE chat_id = ?
            """,
            (chat.id,)
        )

        db.commit()

        return True


    if command == "*ddzcancel":

        if not await admin_required(
            message,
            chat,
            user,
            context
        ):
            return True

        cursor.execute(
            """
            DELETE FROM games
            WHERE chat_id = ?
            """,
            (chat.id,)
        )

        db.commit()

        await message.reply_text(
            "🛑 Don-don-ziki "
            "o‘yini bekor qilindi."
        )

        return True

    return False


# ==================================================
# ASOSIY HANDLER
# ==================================================

async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat

    if not message or not user or not chat:
        return

    if user.is_bot:
        return

    text = (
        message.text or ""
    ).strip()

    command = text.lower()


    # ==================================================
    # PRIVATE CHAT
    # ==================================================

    if chat.type == "private":

        if command in (
            "*start",
            "*help",
            "/start",
            "/help"
        ):
            await message.reply_text(
                HELP_TEXT
            )

        elif command == "*id":
            await message.reply_text(
                f"🆔 Telegram ID: {user.id}"
            )

        else:
            await message.reply_text(
                "🛡 VERITAS\n\n"
                "Barcha buyruqlar uchun "
                "*help yozing."
            )

        return


    if chat.type not in (
        "group",
        "supergroup"
    ):
        return

    ensure_settings(chat.id)


    # ==================================================
    # HELP
    # ==================================================

    if command in (
        "*help",
        "*start"
    ):
        await message.reply_text(
            HELP_TEXT
        )
        return


    # ==================================================
    # ID
    # ==================================================

    if command == "*id":

        target = reply_target(
            message
        )

        if target:
            await message.reply_text(
                f"🆔 {get_name(target)}\n"
                f"ID: {target.id}"
            )

        else:
            await message.reply_text(
                "🆔 Sizning Telegram ID: "
                f"{user.id}"
            )

        return


    # ==================================================
    # ADMINLAR
    # ==================================================

    if command == "*admins":

        admins = (
            await context.bot
            .get_chat_administrators(
                chat.id
            )
        )

        result = (
            "👮 GURUH ADMINLARI\n\n"
        )

        for admin in admins:
            result += (
                f"• {get_name(admin.user)}\n"
            )

        await message.reply_text(
            result
        )

        return


    # ==================================================
    # VERITAS RUXSAT BERISH
    # ==================================================

    if command == "*ruxsat":

        if user.id != OWNER_ID:
            return

        target = reply_target(
            message
        )

        if not target:
            await message.reply_text(
                "⚠️ Xabarga reply qilib "
                "*ruxsat yozing."
            )
            return

        cursor.execute(
            """
            INSERT OR IGNORE INTO allowed_users
            (user_id)
            VALUES (?)
            """,
            (target.id,)
        )

        db.commit()

        await message.reply_text(
            f"✅ {get_name(target)} ga "
            "Veritas ruxsati berildi."
        )

        return


    # ==================================================
    # VERITAS RUXSATINI OLISH
    # ==================================================

    if command == "*ruxsatsiz":

        if user.id != OWNER_ID:
            return

        target = reply_target(
            message
        )

        if not target:
            await message.reply_text(
                "⚠️ Xabarga reply qilib "
                "*ruxsatsiz yozing."
            )
            return

        cursor.execute(
            """
            DELETE FROM allowed_users
            WHERE user_id = ?
            """,
            (target.id,)
        )

        db.commit()

        await message.reply_text(
            f"✅ {get_name(target)} dan "
            "Veritas ruxsati olindi."
        )

        return


    # ==================================================
    # TELEGRAM ADMIN BERISH
    # ==================================================

    if command == "*admin":

        if not await telegram_admin_required(
            message,
            chat,
            user,
            context
        ):
            return

        target = reply_target(
            message
        )

        if not target:
            await message.reply_text(
                "⚠️ Xabarga reply qilib "
                "*admin yozing."
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
                can_promote_members=False,
                can_change_info=False
            )

            await message.reply_text(
                f"👮 {get_name(target)} "
                "Telegram admin qilindi."
            )

        except Exception:
            await message.reply_text(
                "⚠️ Admin berilmadi.\n"
                "VeritasBot'ga yangi "
                "adminlar qo‘shish huquqini "
                "bering."
            )

        return


    # ==================================================
    # TELEGRAM ADMINDAN OLISH
    # ==================================================

    if command == "*unadmin":

        if not await telegram_admin_required(
            message,
            chat,
            user,
            context
        ):
            return

        target = reply_target(
            message
        )

        if not target:
            await message.reply_text(
                "⚠️ Xabarga reply qilib "
                "*unadmin yozing."
            )
            return

        if target.id == OWNER_ID:
            await message.reply_text(
                "⛔ Bot egasidan adminlikni "
                "olib bo‘lmaydi."
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
                can_manage_topics=False,
                can_promote_members=False,
                can_change_info=False
            )

            await message.reply_text(
                f"👤 {get_name(target)} "
                "adminlikdan olindi."
            )

        except Exception:
            await message.reply_text(
                "⚠️ Adminlik olinmadi. "
                "VeritasBot huquqlarini "
                "tekshiring."
            )

        return


    # ==================================================
    # WARN
    # ==================================================

    if command == "*warn":

        if not await admin_required(
            message,
            chat,
            user,
            context
        ):
            return

        target = reply_target(
            message
        )

        if not target:
            await message.reply_text(
                "⚠️ Xabarga reply qilib "
                "*warn yozing."
            )
            return

        if await is_telegram_admin(
            chat,
            target.id,
            context
        ):
            await message.reply_text(
                "⛔ Telegram adminini "
                "warn qilib bo‘lmaydi."
            )
            return

        cursor.execute(
            """
            INSERT INTO warnings (
                chat_id,
                user_id,
                warns
            )
            VALUES (?, ?, 1)

            ON CONFLICT(
                chat_id,
                user_id
            )

            DO UPDATE SET
                warns = warns + 1
            """,
            (
                chat.id,
                target.id
            )
        )

        db.commit()

        cursor.execute(
            """
            SELECT warns
            FROM warnings
            WHERE chat_id = ?
            AND user_id = ?
            """,
            (
                chat.id,
                target.id
            )
        )

        warns = cursor.fetchone()[0]

        await message.reply_text(
            f"⚠️ {get_name(target)} "
            "ogohlantirildi.\n"
            f"Warn: {warns}/3"
        )

        if warns >= 3:

            try:
                await context.bot.ban_chat_member(
                    chat.id,
                    target.id
                )

                cursor.execute(
                    """
                    DELETE FROM warnings
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
                    f"🔨 {get_name(target)} "
                    "3 ta warn sabab "
                    "ban qilindi.\n"
                    "♻️ Warnlari 0 ga "
                    "qaytarildi."
                )

            except Exception:
                await message.reply_text(
                    "⚠️ Ban qilish uchun "
                    "botga yetarli admin "
                    "huquqi kerak."
                )

        return


    # ==================================================
    # UNWARN
    # ==================================================

    if command == "*unwarn":

        if not await admin_required(
            message,
            chat,
            user,
            context
        ):
            return

        target = reply_target(
            message
        )

        if not target:
            await message.reply_text(
                "⚠️ Xabarga reply qilib "
                "*unwarn yozing."
            )
            return

        cursor.execute(
            """
            SELECT warns
            FROM warnings
            WHERE chat_id = ?
            AND user_id = ?
            """,
            (
                chat.id,
                target.id
            )
        )

        row = cursor.fetchone()

        warns = (
            row[0]
            if row
            else 0
        )

        warns = max(
            0,
            warns - 1
        )

        cursor.execute(
            """
            INSERT INTO warnings (
                chat_id,
                user_id,
                warns
            )
            VALUES (?, ?, ?)

            ON CONFLICT(
                chat_id,
                user_id
            )

            DO UPDATE SET
                warns = excluded.warns
            """,
            (
                chat.id,
                target.id,
                warns
            )
        )

        db.commit()

        await message.reply_text(
            f"✅ {get_name(target)}\n"
            f"Warn: {warns}/3"
        )

        return


    # ==================================================
    # CLEAR WARNS
    # ==================================================

    if command == "*clearwarns":

        if not await admin_required(
            message,
            chat,
            user,
            context
        ):
            return

        target = reply_target(
            message
        )

        if not target:
            await message.reply_text(
                "⚠️ Foydalanuvchi "
                "xabariga reply qiling."
            )
            return

        cursor.execute(
            """
            DELETE FROM warnings
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
            f"✅ {get_name(target)} "
            "warnlari tozalandi."
        )

        return


    # ==================================================
    # WARNS
    # ==================================================

    if command == "*warns":

        target = (
            reply_target(message)
            or user
        )

        cursor.execute(
            """
            SELECT warns
            FROM warnings
            WHERE chat_id = ?
            AND user_id = ?
            """,
            (
                chat.id,
                target.id
            )
        )

        row = cursor.fetchone()

        warns = (
            row[0]
            if row
            else 0
        )

        await message.reply_text(
            f"⚠️ {get_name(target)}\n"
            f"Warn: {warns}/3"
        )

        return

    wins = {
        ("tosh", "qaychi"),
        ("qaychi", "qogoz"),
        ("qogoz", "tosh"),
    }

    if (first, second) in wins:
        return 1

    return 2
    # ==================================================
# DON-DON-ZIKI HANDLER
# ==================================================

async def handle_ddz(
    message,
    chat,
    user,
    command,
    context
):

    if command == "*ddz":

        cursor.execute(
            """
            SELECT chat_id FROM games
            WHERE chat_id = ?
            """,
            (chat.id,)
        )

        if cursor.fetchone():
            await message.reply_text(
                "⚠️ Bu guruhda hozir o‘yin bor."
            )
            return True

        cursor.execute(
            """
            INSERT INTO games (
                chat_id,
                player1_id,
                player1_name,
                player2_id,
                player2_name
            )
            VALUES (?, ?, ?, NULL, '')
            """,
            (
                chat.id,
                user.id,
                get_name(user)
            )
        )

        db.commit()

        await message.reply_text(
            "✊✋✌️ DON-DON-ZIKI\n\n"
            f"{get_name(user)} o‘yin ochdi.\n\n"
            "Ikkinchi o‘yinchi:\n"
            "*ddzjoin"
        )

        return True


    if command == "*ddzjoin":

        cursor.execute(
            """
            SELECT
                player1_id,
                player1_name,
                player2_id
            FROM games
            WHERE chat_id = ?
            """,
            (chat.id,)
        )

        row = cursor.fetchone()

        if not row:
            await message.reply_text(
                "⚠️ Ochiq o‘yin yo‘q.\n"
                "*ddz bilan o‘yin oching."
            )
            return True

        if row[2]:
            await message.reply_text(
                "⚠️ O‘yinga ikki kishi "
                "allaqachon qo‘shilgan."
            )
            return True

        if row[0] == user.id:
            await message.reply_text(
                "⚠️ O‘zingiz bilan "
                "o‘ynay olmaysiz."
            )
            return True

        cursor.execute(
            """
            UPDATE games
            SET
                player2_id = ?,
                player2_name = ?
            WHERE chat_id = ?
            """,
            (
                user.id,
                get_name(user),
                chat.id
            )
        )

        db.commit()

        await message.reply_text(
            "🎮 O‘YIN BOSHLANDI\n\n"
            f"{row[1]}\n"
            "VS\n"
            f"{get_name(user)}\n\n"
            "Tanlang:\n"
            "*tosh ✊\n"
            "*qogoz ✋\n"
            "*qaychi ✌️"
        )

        return True


    if command in CHOICES:

        cursor.execute(
            """
            SELECT
                player1_id,
                player1_name,
                player2_id,
                player2_name,
                choice1,
                choice2
            FROM games
            WHERE chat_id = ?
            """,
            (chat.id,)
        )

        row = cursor.fetchone()

        if not row or not row[2]:
            return False

        player1_id = row[0]
        player1_name = row[1]
        player2_id = row[2]
        player2_name = row[3]
        choice1 = row[4]
        choice2 = row[5]

        choice = CHOICES[command]

        if user.id == player1_id:

            choice1 = choice

            cursor.execute(
                """
                UPDATE games
                SET choice1 = ?
                WHERE chat_id = ?
                """,
                (
                    choice,
                    chat.id
                )
            )

        elif user.id == player2_id:

            choice2 = choice

            cursor.execute(
                """
                UPDATE games
                SET choice2 = ?
                WHERE chat_id = ?
                """,
                (
                    choice,
                    chat.id
                )
            )

        else:
            return False

        db.commit()

        if not choice1 or not choice2:

            await message.reply_text(
                f"✅ {get_name(user)} "
                "tanlov qildi."
            )

            return True

        winner = ddz_winner(
            choice1,
            choice2
        )

        if winner == 0:
            result = "🤝 Durrang!"

        elif winner == 1:
            result = (
                f"🏆 G‘olib: "
                f"{player1_name}"
            )

        else:
            result = (
                f"🏆 G‘olib: "
                f"{player2_name}"
            )

        await message.reply_text(
            "✊✋✌️ NATIJA\n\n"
            f"{player1_name}: "
            f"{ICONS[choice1]}\n"
            f"{player2_name}: "
            f"{ICONS[choice2]}\n\n"
            f"{result}"
        )

        cursor.execute(
            """
            DELETE FROM games
            WHERE chat_id = ?
            """,
            (chat.id,)
        )

        db.commit()

        return True


    if command == "*ddzcancel":

        if not await admin_required(
            message,
            chat,
            user,
            context
        ):
            return True

        cursor.execute(
            """
            DELETE FROM games
            WHERE chat_id = ?
            """,
            (chat.id,)
        )

        db.commit()

        await message.reply_text(
            "🛑 Don-don-ziki "
            "o‘yini bekor qilindi."
        )

        return True

    return False


# ==================================================
# ASOSIY HANDLER
# ==================================================

async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat

    if not message or not user or not chat:
        return

    if user.is_bot:
        return

    text = (
        message.text or ""
    ).strip()

    command = text.lower()


    # ==================================================
    # PRIVATE CHAT
    # ==================================================

    if chat.type == "private":

        if command in (
            "*start",
            "*help",
            "/start",
            "/help"
        ):
            await message.reply_text(
                HELP_TEXT
            )

        elif command == "*id":
            await message.reply_text(
                f"🆔 Telegram ID: {user.id}"
            )

        else:
            await message.reply_text(
                "🛡 VERITAS\n\n"
                "Barcha buyruqlar uchun "
                "*help yozing."
            )

        return


    if chat.type not in (
        "group",
        "supergroup"
    ):
        return

    ensure_settings(chat.id)


    # ==================================================
    # HELP
    # ==================================================

    if command in (
        "*help",
        "*start"
    ):
        await message.reply_text(
            HELP_TEXT
        )
        return


    # ==================================================
    # ID
    # ==================================================

    if command == "*id":

        target = reply_target(
            message
        )

        if target:
            await message.reply_text(
                f"🆔 {get_name(target)}\n"
                f"ID: {target.id}"
            )

        else:
            await message.reply_text(
                "🆔 Sizning Telegram ID: "
                f"{user.id}"
            )

        return


    # ==================================================
    # ADMINLAR
    # ==================================================

    if command == "*admins":

        admins = (
            await context.bot
            .get_chat_administrators(
                chat.id
            )
        )

        result = (
            "👮 GURUH ADMINLARI\n\n"
        )

        for admin in admins:
            result += (
                f"• {get_name(admin.user)}\n"
            )

        await message.reply_text(
            result
        )

        return


    # ==================================================
    # VERITAS RUXSAT BERISH
    # ==================================================

    if command == "*ruxsat":

        if user.id != OWNER_ID:
            return

        target = reply_target(
            message
        )

        if not target:
            await message.reply_text(
                "⚠️ Xabarga reply qilib "
                "*ruxsat yozing."
            )
            return

        cursor.execute(
            """
            INSERT OR IGNORE INTO allowed_users
            (user_id)
            VALUES (?)
            """,
            (target.id,)
        )

        db.commit()

        await message.reply_text(
            f"✅ {get_name(target)} ga "
            "Veritas ruxsati berildi."
        )

        return


    # ==================================================
    # VERITAS RUXSATINI OLISH
    # ==================================================

    if command == "*ruxsatsiz":

        if user.id != OWNER_ID:
            return

        target = reply_target(
            message
        )

        if not target:
            await message.reply_text(
                "⚠️ Xabarga reply qilib "
                "*ruxsatsiz yozing."
            )
            return

        cursor.execute(
            """
            DELETE FROM allowed_users
            WHERE user_id = ?
            """,
            (target.id,)
        )

        db.commit()

        await message.reply_text(
            f"✅ {get_name(target)} dan "
            "Veritas ruxsati olindi."
        )

        return


    # ==================================================
    # TELEGRAM ADMIN BERISH
    # ==================================================

    if command == "*admin":

        if not await telegram_admin_required(
            message,
            chat,
            user,
            context
        ):
            return

        target = reply_target(
            message
        )

        if not target:
            await message.reply_text(
                "⚠️ Xabarga reply qilib "
                "*admin yozing."
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
                can_promote_members=False,
                can_change_info=False
            )

            await message.reply_text(
                f"👮 {get_name(target)} "
                "Telegram admin qilindi."
            )

        except Exception:
            await message.reply_text(
                "⚠️ Admin berilmadi.\n"
                "VeritasBot'ga yangi "
                "adminlar qo‘shish huquqini "
                "bering."
            )

        return


    # ==================================================
    # TELEGRAM ADMINDAN OLISH
    # ==================================================

    if command == "*unadmin":

        if not await telegram_admin_required(
            message,
            chat,
            user,
            context
        ):
            return

        target = reply_target(
            message
        )

        if not target:
            await message.reply_text(
                "⚠️ Xabarga reply qilib "
                "*unadmin yozing."
            )
            return

        if target.id == OWNER_ID:
            await message.reply_text(
                "⛔ Bot egasidan adminlikni "
                "olib bo‘lmaydi."
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
                can_manage_topics=False,
                can_promote_members=False,
                can_change_info=False
            )

            await message.reply_text(
                f"👤 {get_name(target)} "
                "adminlikdan olindi."
            )

        except Exception:
            await message.reply_text(
                "⚠️ Adminlik olinmadi. "
                "VeritasBot huquqlarini "
                "tekshiring."
            )

        return


    # ==================================================
    # WARN
    # ==================================================

    if command == "*warn":

        if not await admin_required(
            message,
            chat,
            user,
            context
        ):
            return

        target = reply_target(
            message
        )

        if not target:
            await message.reply_text(
                "⚠️ Xabarga reply qilib "
                "*warn yozing."
            )
            return

        if await is_telegram_admin(
            chat,
            target.id,
            context
        ):
            await message.reply_text(
                "⛔ Telegram adminini "
                "warn qilib bo‘lmaydi."
            )
            return

        cursor.execute(
            """
            INSERT INTO warnings (
                chat_id,
                user_id,
                warns
            )
            VALUES (?, ?, 1)

            ON CONFLICT(
                chat_id,
                user_id
            )

            DO UPDATE SET
                warns = warns + 1
            """,
            (
                chat.id,
                target.id
            )
        )

        db.commit()

        cursor.execute(
            """
            SELECT warns
            FROM warnings
            WHERE chat_id = ?
            AND user_id = ?
            """,
            (
                chat.id,
                target.id
            )
        )

        warns = cursor.fetchone()[0]

        await message.reply_text(
            f"⚠️ {get_name(target)} "
            "ogohlantirildi.\n"
            f"Warn: {warns}/3"
        )

        if warns >= 3:

            try:
                await context.bot.ban_chat_member(
                    chat.id,
                    target.id
                )

                cursor.execute(
                    """
                    DELETE FROM warnings
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
                    f"🔨 {get_name(target)} "
                    "3 ta warn sabab "
                    "ban qilindi.\n"
                    "♻️ Warnlari 0 ga "
                    "qaytarildi."
                )

            except Exception:
                await message.reply_text(
                    "⚠️ Ban qilish uchun "
                    "botga yetarli admin "
                    "huquqi kerak."
                )

        return


    # ==================================================
    # UNWARN
    # ==================================================

    if command == "*unwarn":

        if not await admin_required(
            message,
            chat,
            user,
            context
        ):
            return

        target = reply_target(
            message
        )

        if not target:
            await message.reply_text(
                "⚠️ Xabarga reply qilib "
                "*unwarn yozing."
            )
            return

        cursor.execute(
            """
            SELECT warns
            FROM warnings
            WHERE chat_id = ?
            AND user_id = ?
            """,
            (
                chat.id,
                target.id
            )
        )

        row = cursor.fetchone()

        warns = (
            row[0]
            if row
            else 0
        )

        warns = max(
            0,
            warns - 1
        )

        cursor.execute(
            """
            INSERT INTO warnings (
                chat_id,
                user_id,
                warns
            )
            VALUES (?, ?, ?)

            ON CONFLICT(
                chat_id,
                user_id
            )

            DO UPDATE SET
                warns = excluded.warns
            """,
            (
                chat.id,
                target.id,
                warns
            )
        )

        db.commit()

        await message.reply_text(
            f"✅ {get_name(target)}\n"
            f"Warn: {warns}/3"
        )

        return


    # ==================================================
    # CLEAR WARNS
    # ==================================================

    if command == "*clearwarns":

        if not await admin_required(
            message,
            chat,
            user,
            context
        ):
            return

        target = reply_target(
            message
        )

        if not target:
            await message.reply_text(
                "⚠️ Foydalanuvchi "
                "xabariga reply qiling."
            )
            return

        cursor.execute(
            """
            DELETE FROM warnings
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
            f"✅ {get_name(target)} "
            "warnlari tozalandi."
        )

        return


    # ==================================================
    # WARNS
    # ==================================================

    if command == "*warns":

        target = (
            reply_target(message)
            or user
        )

        cursor.execute(
            """
            SELECT warns
            FROM warnings
            WHERE chat_id = ?
            AND user_id = ?
            """,
            (
                chat.id,
                target.id
            )
        )

        row = cursor.fetchone()

        warns = (
            row[0]
            if row
            else 0
        )

        await message.reply_text(
            f"⚠️ {get_name(target)}\n"
            f"Warn: {warns}/3"
        )

        return
            # ==================================================
    # MUTE
    # ==================================================

    if command == "*mute":

        if not await admin_required(
            message, chat, user, context
        ):
            return

        target = reply_target(message)

        if not target:
            await message.reply_text(
                "⚠️ Xabarga reply qilib *mute yozing."
            )
            return

        if await is_telegram_admin(
            chat, target.id, context
        ):
            await message.reply_text(
                "⛔ Telegram adminini mute qilib bo‘lmaydi."
            )
            return

        try:
            await context.bot.restrict_chat_member(
                chat.id,
                target.id,
                permissions=ChatPermissions(
                    can_send_messages=False
                )
            )

            await message.reply_text(
                f"🔇 {get_name(target)} mute qilindi."
            )

        except Exception:
            await message.reply_text(
                "⚠️ Botga foydalanuvchilarni "
                "cheklash huquqini bering."
            )

        return


    # ==================================================
    # UNMUTE
    # ==================================================

    if command == "*unmute":

        if not await admin_required(
            message, chat, user, context
        ):
            return

        target = reply_target(message)

        if not target:
            await message.reply_text(
                "⚠️ Xabarga reply qilib *unmute yozing."
            )
            return

        try:
            await context.bot.restrict_chat_member(
                chat.id,
                target.id,
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

        except Exception:
            await message.reply_text(
                "⚠️ Unmute qilishda xato."
            )

        return


    # ==================================================
    # KICK
    # ==================================================

    if command == "*kick":

        if not await admin_required(
            message, chat, user, context
        ):
            return

        target = reply_target(message)

        if not target:
            await message.reply_text(
                "⚠️ Xabarga reply qilib *kick yozing."
            )
            return

        if await is_telegram_admin(
            chat, target.id, context
        ):
            await message.reply_text(
                "⛔ Telegram adminini kick qilib bo‘lmaydi."
            )
            return

        try:
            await context.bot.ban_chat_member(
                chat.id,
                target.id
            )

            await context.bot.unban_chat_member(
                chat.id,
                target.id
            )

            await message.reply_text(
                f"👢 {get_name(target)} "
                "guruhdan chiqarildi."
            )

        except Exception:
            await message.reply_text(
                "⚠️ Botga ban huquqini bering."
            )

        return


    # ==================================================
    # BAN
    # ==================================================

    if command == "*ban":

        if not await admin_required(
            message, chat, user, context
        ):
            return

        target = reply_target(message)

        if not target:
            await message.reply_text(
                "⚠️ Xabarga reply qilib *ban yozing."
            )
            return

        if await is_telegram_admin(
            chat, target.id, context
        ):
            await message.reply_text(
                "⛔ Telegram adminini ban qilib bo‘lmaydi."
            )
            return

        try:
            await context.bot.ban_chat_member(
                chat.id,
                target.id
            )

            await message.reply_text(
                f"🔨 {get_name(target)} ban qilindi."
            )

        except Exception:
            await message.reply_text(
                "⚠️ Botga ban huquqini bering."
            )

        return


    # ==================================================
    # UNBAN
    # ==================================================

    if (
        command == "*unban"
        or command.startswith("*unban ")
    ):

        if not await admin_required(
            message, chat, user, context
        ):
            return

        target = reply_target(message)

        target_id = (
            target.id
            if target
            else None
        )

        if not target_id:

            parts = command.split()

            if len(parts) == 2:
                try:
                    target_id = int(
                        parts[1]
                    )
                except ValueError:
                    target_id = None

        if not target_id:
            await message.reply_text(
                "⚠️ Eski xabarga reply qilib "
                "*unban yozing yoki:\n"
                "*unban ID"
            )
            return

        try:
            await context.bot.unban_chat_member(
                chat.id,
                target_id
            )

            cursor.execute(
                """
                DELETE FROM warnings
                WHERE chat_id = ?
                AND user_id = ?
                """,
                (
                    chat.id,
                    target_id
                )
            )

            db.commit()

            await message.reply_text(
                "✅ Foydalanuvchi "
                "bandan chiqarildi."
            )

        except Exception:
            await message.reply_text(
                "⚠️ ID yoki huquqlarni tekshiring."
            )

        return


    # ==================================================
    # DELETE
    # ==================================================

    if command == "*del":

        if not await admin_required(
            message, chat, user, context
        ):
            return

        if not message.reply_to_message:
            await message.reply_text(
                "⚠️ O‘chiriladigan "
                "xabarga reply qiling."
            )
            return

        try:
            await message.reply_to_message.delete()
            await message.delete()

        except Exception:
            await message.reply_text(
                "⚠️ Botga xabar o‘chirish "
                "huquqini bering."
            )

        return


    # ==================================================
    # LINK HIMOYASI
    # ==================================================

    if command in (
        "*links on",
        "*links off"
    ):

        if not await admin_required(
            message, chat, user, context
        ):
            return

        value = (
            1
            if command == "*links on"
            else 0
        )

        cursor.execute(
            """
            UPDATE settings
            SET link_block = ?
            WHERE chat_id = ?
            """,
            (
                value,
                chat.id
            )
        )

        db.commit()

        await message.reply_text(
            "🔗 Link himoyasi "
            + (
                "yoqildi."
                if value
                else "o‘chirildi."
            )
        )

        return


    # ==================================================
    # BLACKLIST
    # ==================================================

    if command.startswith(
        "*blacklist "
    ):

        if not await admin_required(
            message, chat, user, context
        ):
            return

        word = text[
            len("*blacklist "):
        ].strip().lower()

        if not word:
            return

        cursor.execute(
            """
            INSERT OR IGNORE INTO blacklist
            (chat_id, word)
            VALUES (?, ?)
            """,
            (
                chat.id,
                word
            )
        )

        db.commit()

        await message.reply_text(
            f"🚫 Blacklistga qo‘shildi: {word}"
        )

        return


    if command.startswith(
        "*unblacklist "
    ):

        if not await admin_required(
            message, chat, user, context
        ):
            return

        word = text[
            len("*unblacklist "):
        ].strip().lower()

        cursor.execute(
            """
            DELETE FROM blacklist
            WHERE chat_id = ?
            AND word = ?
            """,
            (
                chat.id,
                word
            )
        )

        db.commit()

        await message.reply_text(
            f"✅ Blacklistdan olib "
            f"tashlandi: {word}"
        )

        return


    if command == "*blacklists":

        if not await admin_required(
            message, chat, user, context
        ):
            return

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
                "📭 Blacklist bo‘sh."
            )
            return

        result = "🚫 BLACKLIST\n\n"

        for i, row in enumerate(
            rows,
            start=1
        ):
            result += (
                f"{i}. {row[0]}\n"
            )

        await message.reply_text(
            result
        )

        return


    # ==================================================
    # FILTER - MATN VA MEDIA
    # ==================================================

    if command.startswith(
        "*filter "
    ):

        if not await admin_required(
            message, chat, user, context
        ):
            return

        rest = text[
            len("*filter "):
        ].strip()

        if not rest:
            await message.reply_text(
                "⚠️ Matn uchun:\n"
                "*filter salom Assalomu alaykum\n\n"
                "Media uchun rasm, video yoki "
                "stickerga reply qilib:\n"
                "*filter kalit"
            )
            return

        parts = rest.split(
            maxsplit=1
        )

        keyword = (
            parts[0]
            .strip()
            .lower()
        )

        # Oddiy matn filter
        if len(parts) == 2:

            response = parts[1]

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

                ON CONFLICT(
                    chat_id,
                    keyword
                )

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
                f"✅ Matn filter saqlandi: "
                f"{keyword}"
            )

            return

        # Media filter
        if message.reply_to_message:

            media_type, file_id, caption = (
                media_from_message(
                    message.reply_to_message
                )
            )

            if media_type:

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
                    VALUES (?, ?, ?, ?, ?, ?)

                    ON CONFLICT(
                        chat_id,
                        keyword
                    )

                    DO UPDATE SET
                        response = excluded.response,
                        media_type = excluded.media_type,
                        file_id = excluded.file_id,
                        caption = excluded.caption
                    """,
                    (
                        chat.id,
                        keyword,
                        "",
                        media_type,
                        file_id,
                        caption or ""
                    )
                )

                db.commit()

                await message.reply_text(
                    f"✅ Media filter saqlandi: "
                    f"{keyword}"
                )

                return

        await message.reply_text(
            "⚠️ Media xabariga reply qilib:\n"
            "*filter kalit\n\n"
            "Rasm, video, sticker, GIF, "
            "audio, voice va fayl ishlaydi."
        )

        return


    # ==================================================
    # FILTERLAR
    # ==================================================

    if command == "*filters":

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
                "📭 Filterlar yo‘q."
            )
            return

        result = "📋 FILTERLAR\n\n"

        for i, row in enumerate(
            rows,
            start=1
        ):

            keyword = row[0]
            media_type = (
                row[1] or "text"
            )

            icon = (
                "📝"
                if media_type == "text"
                else "🎞"
            )

            result += (
                f"{i}. {icon} "
                f"{keyword}\n"
            )

        await message.reply_text(
            result
        )

        return


    # ==================================================
    # FILTER O'CHIRISH
    # ==================================================

    if command.startswith(
        "*stop "
    ):

        if not await admin_required(
            message, chat, user, context
        ):
            return

        keyword = text[
            len("*stop "):
        ].strip().lower()

        cursor.execute(
            """
            DELETE FROM chat_filters
            WHERE chat_id = ?
            AND keyword = ?
            """,
            (
                chat.id,
                keyword
            )
        )

        db.commit()

        await message.reply_text(
            f"🗑 Filter o‘chirildi: {keyword}"
        )

        return


    if command == "*stopall":

        if not await admin_required(
            message, chat, user, context
        ):
            return

        cursor.execute(
            """
            DELETE FROM chat_filters
            WHERE chat_id = ?
            """,
            (chat.id,)
        )

        count = cursor.rowcount

        db.commit()

        await message.reply_text(
            f"🗑 {count} ta filter o‘chirildi."
        )

        return
            # ==================================================
    # RULES
    # ==================================================

    if command.startswith("*setrules "):

        if not await admin_required(
            message, chat, user, context
        ):
            return

        rules = text[
            len("*setrules "):
        ].strip()

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
            "✅ Guruh qoidalari saqlandi."
        )

        return


    if command == "*rules":

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
            row[0]
            if row
            else ""
        )

        if rules:
            await message.reply_text(
                "📜 GURUH QOIDALARI\n\n"
                f"{rules}"
            )
        else:
            await message.reply_text(
                "📜 Hozircha guruh "
                "qoidalari yozilmagan."
            )

        return


    # ==================================================
    # NOTES
    # ==================================================

    if command.startswith("*save "):

        if not await admin_required(
            message, chat, user, context
        ):
            return

        parts = text.split(
            maxsplit=2
        )

        if len(parts) < 3:
            await message.reply_text(
                "⚠️ *save nom matn"
            )
            return

        name = parts[1].lower()
        content = parts[2]

        cursor.execute(
            """
            INSERT INTO notes (
                chat_id,
                name,
                content
            )
            VALUES (?, ?, ?)

            ON CONFLICT(
                chat_id,
                name
            )

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
            f"📝 Note saqlandi: {name}"
        )

        return


    if command.startswith("*get "):

        name = text[
            len("*get "):
        ].strip().lower()

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

        if row:
            await message.reply_text(
                row[0]
            )
        else:
            await message.reply_text(
                "⚠️ Bunday note topilmadi."
            )

        return


    if command == "*notes":

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
                "📭 Note'lar yo‘q."
            )
            return

        result = "📝 NOTES\n\n"

        for i, row in enumerate(
            rows,
            start=1
        ):
            result += (
                f"{i}. {row[0]}\n"
            )

        await message.reply_text(
            result
        )

        return


    if command.startswith("*clear "):

        if not await admin_required(
            message, chat, user, context
        ):
            return

        name = text[
            len("*clear "):
        ].strip().lower()

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

        db.commit()

        await message.reply_text(
            f"🗑 Note o‘chirildi: {name}"
        )

        return


    # ==================================================
    # WELCOME / GOODBYE SOZLAMALARI
    # ==================================================

    if command in (
        "*welcome on",
        "*welcome off",
        "*goodbye on",
        "*goodbye off"
    ):

        if not await admin_required(
            message, chat, user, context
        ):
            return

        parts = command.split()

        setting = (
            parts[0][1:]
        )

        value = (
            1
            if parts[1] == "on"
            else 0
        )

        cursor.execute(
            f"""
            UPDATE settings
            SET {setting} = ?
            WHERE chat_id = ?
            """,
            (
                value,
                chat.id
            )
        )

        db.commit()

        await message.reply_text(
            f"⚙️ {setting}: "
            + (
                "ON"
                if value
                else "OFF"
            )
        )

        return


    # ==================================================
    # AKTIV
    # ==================================================

    if (
        command == "*aktiv"
        or command.startswith("*aktiv ")
    ):

        parts = command.split()

        limit = 50

        if (
            len(parts) == 2
            and parts[1].isdigit()
        ):
            limit = max(
                1,
                min(
                    int(parts[1]),
                    50
                )
            )

        cursor.execute(
            """
            SELECT
                name,
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
                "📊 Hali statistika yo‘q."
            )
            return

        result = (
            f"🏆 TOP {len(rows)} "
            "FAOL A’ZO\n\n"
        )

        medals = [
            "🥇",
            "🥈",
            "🥉"
        ]

        for i, (
            name,
            count
        ) in enumerate(
            rows,
            start=1
        ):

            if i <= 3:
                icon = medals[i - 1]
            else:
                icon = f"{i}."

            result += (
                f"{icon} {name} — "
                f"{count} ta xabar\n"
            )

        await message.reply_text(
            result
        )

        return


    # ==================================================
    # MEN
    # ==================================================

    if command == "*men":

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

        row = cursor.fetchone()

        count = (
            row[0]
            if row
            else 0
        )

        cursor.execute(
            """
            SELECT COUNT(*) + 1
            FROM activity
            WHERE chat_id = ?
            AND messages > ?
            """,
            (
                chat.id,
                count
            )
        )

        rank = cursor.fetchone()[0]

        await message.reply_text(
            f"👤 {get_name(user)}\n\n"
            f"💬 Xabarlar: {count}\n"
            f"🏆 Reyting: {rank}"
        )

        return


    # ==================================================
    # DON-DON-ZIKI
    # ==================================================

    ddz_handled = await handle_ddz(
        message,
        chat,
        user,
        command,
        context
    )

    if ddz_handled:
        return


    # ==================================================
    # NOTANISH * BUYRUQ
    # ==================================================

    if text.startswith("*"):
        return


    # ==================================================
    # LINK HIMOYASI
    # ==================================================

    cursor.execute(
        """
        SELECT link_block
        FROM settings
        WHERE chat_id = ?
        """,
        (chat.id,)
    )

    row = cursor.fetchone()

    link_block = (
        row[0]
        if row
        else 0
    )

    if (
        link_block
        and contains_link(text)
        and not await is_admin(
            chat,
            user.id,
            context
        )
    ):

        try:
            await message.delete()
        except Exception:
            pass

        return


    # ==================================================
    # BLACKLIST TEKSHIRISH
    # ==================================================

    cursor.execute(
        """
        SELECT word
        FROM blacklist
        WHERE chat_id = ?
        """,
        (chat.id,)
    )

    bad_words = cursor.fetchall()

    lower_text = text.lower()

    for row in bad_words:

        if (
            row[0] in lower_text
            and not await is_admin(
                chat,
                user.id,
                context
            )
        ):

            try:
                await message.delete()
            except Exception:
                pass

            return


    # ==================================================
    # FILTER ISHLATISH
    # ==================================================

    if text:

        cursor.execute(
            """
            SELECT
                response,
                media_type,
                file_id,
                caption
            FROM chat_filters
            WHERE chat_id = ?
            AND keyword = ?
            """,
            (
                chat.id,
                command
            )
        )

        row = cursor.fetchone()

        if row:

            response = (
                row[0] or ""
            )

            media_type = (
                row[1] or "text"
            )

            file_id = (
                row[2] or ""
            )

            caption = (
                row[3] or ""
            )

            await send_saved_filter(
                message,
                media_type,
                file_id,
                response,
                caption
            )


    # ==================================================
    # FAOLLIKNI HISOBLASH
    # ==================================================

    if text:

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

            ON CONFLICT(
                chat_id,
                user_id
            )

            DO UPDATE SET
                name = excluded.name,
                username = excluded.username,
                messages = messages + 1
            """,
            (
                chat.id,
                user.id,
                get_name(user),
                user.username or ""
            )
        )

        db.commit()


# ==================================================
# MAIN
# ==================================================

def main():

    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN topilmadi!"
        )

    app = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .build()
    )

    app.add_handler(
        MessageHandler(
            filters.StatusUpdate.NEW_CHAT_MEMBERS,
            welcome_new_member
        ),
        group=0
    )

    app.add_handler(
        MessageHandler(
            filters.StatusUpdate.LEFT_CHAT_MEMBER,
            goodbye_member
        ),
        group=0
    )

    app.add_handler(
        MessageHandler(
            filters.ALL,
            handle_message
        ),
        group=1
    )

    print(
        "Veritas v3 ishga tushdi."
    )

    app.run_polling()


if __name__ == "__main__":
    main()
