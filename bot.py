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

db = sqlite3.connect("veritas.db", check_same_thread=False)
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
    PRIMARY KEY (chat_id, keyword)
)
""")

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
        "INSERT OR IGNORE INTO settings (chat_id) VALUES (?)",
        (chat_id,)
    )
    db.commit()


async def is_admin(chat, user_id, context):
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


async def admin_required(message, chat, user, context):
    if await is_admin(chat, user.id, context):
        return True

    await message.reply_text(
        "⛔ Bu buyruq faqat adminlar uchun."
    )
    return False


def reply_target(message):
    if not message.reply_to_message:
        return None

    return message.reply_to_message.from_user


def contains_link(text):
    pattern = (
        r"(https?://|www\.|t\.me/|telegram\.me/)"
    )
    return bool(
        re.search(pattern, text, re.IGNORECASE)
    )


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
        "SELECT welcome FROM settings WHERE chat_id = ?",
        (chat.id,)
    )

    row = cursor.fetchone()

    if not row or row[0] == 0:
        return

    for member in message.new_chat_members:

        if member.is_bot:
            continue

        await message.reply_text(
            f"👋 Xush kelibsiz, {member.full_name}!\n\n"
            f"📚 {chat.title} guruhiga xush kelibsiz."
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
        "SELECT goodbye FROM settings WHERE chat_id = ?",
        (chat.id,)
    )

    row = cursor.fetchone()

    if row and row[0]:
        await message.reply_text(
            f"👋 {member.full_name} guruhni tark etdi."
        )


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

    text = (message.text or "").strip()
    command = text.lower()

    # Private chat
    if chat.type == "private":

        if command in ("*start", "*help"):
            await message.reply_text(
                "🛡 VERITAS\n\n"
                "Guruh boshqaruvi va faollik boti.\n"
                "Botni guruhga qo‘shib admin qiling."
            )

        elif command == "*id":
            await message.reply_text(
                f"🆔 Telegram ID: {user.id}"
            )

        return

    if chat.type not in ("group", "supergroup"):
        return

    ensure_settings(chat.id)


    # ==================================================
    # HELP
    # ==================================================

    if command == "*help":

        await message.reply_text(
            "🛡 VERITAS BUYRUQLARI\n\n"

            "👤 UMUMIY\n"
            "*id — Telegram ID\n"
            "*men — shaxsiy statistika\n"
            "*aktiv — TOP 50\n"
            "*aktiv 10 — TOP 10\n"
            "*rules — guruh qoidalari\n"
            "*warns — ogohlantirishlarim\n\n"

            "🛡 ADMIN\n"
            "*warn — ogohlantirish\n"
            "*unwarn — bitta warn olib tashlash\n"
            "*clearwarns — warnlarni tozalash\n"
            "*mute — yozishni taqiqlash\n"
            "*unmute — yozishni ochish\n"
            "*kick — guruhdan chiqarish\n"
            "*ban — bloklash\n"
            "*unban ID — blokdan chiqarish\n"
            "*del — xabarni o‘chirish\n\n"

            "🔗 HIMOYA\n"
            "*links on\n"
            "*links off\n"
            "*blacklist so‘z\n"
            "*unblacklist so‘z\n"
            "*blacklists\n\n"

            "💬 FILTER\n"
            "*filter kalit javob\n"
            "*filters\n"
            "*stop kalit\n"
            "*stopall\n\n"

            "📝 NOTES\n"
            "*save nom matn\n"
            "*get nom\n"
            "*notes\n"
            "*clear nom\n\n"

            "⚙️ SOZLAMALAR\n"
            "*welcome on/off\n"
            "*goodbye on/off\n"
            "*setrules matn\n"
            "*admins"
        )
        return


    # ==================================================
    # ID
    # ==================================================

    if command == "*id":

        target = reply_target(message)

        if target:
            await message.reply_text(
                f"🆔 {get_name(target)}\n"
                f"ID: {target.id}"
            )
        else:
            await message.reply_text(
                f"🆔 Sizning Telegram ID: {user.id}"
            )

        return


    # ==================================================
    # ADMINLAR
    # ==================================================

    if command == "*admins":

        admins = await context.bot.get_chat_administrators(
            chat.id
        )

        result = "👮 GURUH ADMINLARI\n\n"

        for admin in admins:
            result += (
                f"• {get_name(admin.user)}\n"
            )

        await message.reply_text(result)
        return


    # ==================================================
    # WARN
    # ==================================================

    if command == "*warn":

        if not await admin_required(
            message, chat, user, context
        ):
            return

        target = reply_target(message)

        if not target:
            await message.reply_text(
                "⚠️ Xabarga reply qilib *warn yozing."
            )
            return

        if await is_admin(chat, target.id, context):
            await message.reply_text(
                "⛔ Adminni warn qilib bo‘lmaydi."
            )
            return

        cursor.execute(
            """
            INSERT INTO warnings
                (chat_id, user_id, warns)
            VALUES (?, ?, 1)
            ON CONFLICT(chat_id, user_id)
            DO UPDATE SET warns = warns + 1
            """,
            (chat.id, target.id)
        )

        db.commit()

        cursor.execute(
            """
            SELECT warns FROM warnings
            WHERE chat_id = ? AND user_id = ?
            """,
            (chat.id, target.id)
        )

        warns = cursor.fetchone()[0]

        await message.reply_text(
            f"⚠️ {get_name(target)} ogohlantirildi.\n"
            f"Warn: {warns}/3"
        )

        if warns >= 3:

            try:
                await context.bot.ban_chat_member(
                    chat.id,
                    target.id
                )

                await message.reply_text(
                    f"🔨 {get_name(target)} "
                    "3 ta warn sabab ban qilindi."
                )

            except Exception:
                await message.reply_text(
                    "⚠️ Ban qilish uchun botga "
                    "yetarli admin huquqi kerak."
                )

        return


    # ==================================================
    # UNWARN
    # ==================================================

    if command == "*unwarn":

        if not await admin_required(
            message, chat, user, context
        ):
            return

        target = reply_target(message)

        if not target:
            await message.reply_text(
                "⚠️ Xabarga reply qilib *unwarn yozing."
            )
            return

        cursor.execute(
            """
            SELECT warns FROM warnings
            WHERE chat_id = ? AND user_id = ?
            """,
            (chat.id, target.id)
        )

        row = cursor.fetchone()
        warns = row[0] if row else 0

        warns = max(0, warns - 1)

        cursor.execute(
            """
            INSERT INTO warnings
                (chat_id, user_id, warns)
            VALUES (?, ?, ?)
            ON CONFLICT(chat_id, user_id)
            DO UPDATE SET warns = excluded.warns
            """,
            (chat.id, target.id, warns)
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
            message, chat, user, context
        ):
            return

        target = reply_target(message)

        if not target:
            await message.reply_text(
                "⚠️ Foydalanuvchi xabariga reply qiling."
            )
            return

        cursor.execute(
            """
            DELETE FROM warnings
            WHERE chat_id = ? AND user_id = ?
            """,
            (chat.id, target.id)
        )

        db.commit()

        await message.reply_text(
            f"✅ {get_name(target)} warnlari tozalandi."
        )
        return


    # ==================================================
    # WARNS
    # ==================================================

    if command == "*warns":

        target = reply_target(message) or user

        cursor.execute(
            """
            SELECT warns FROM warnings
            WHERE chat_id = ? AND user_id = ?
            """,
            (chat.id, target.id)
        )

        row = cursor.fetchone()
        warns = row[0] if row else 0

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

        if await is_admin(chat, target.id, context):
            await message.reply_text(
                "⛔ Adminni mute qilib bo‘lmaydi."
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

        if await is_admin(chat, target.id, context):
            await message.reply_text(
                "⛔ Adminni kick qilib bo‘lmaydi."
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
                f"👢 {get_name(target)} guruhdan chiqarildi."
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

        if await is_admin(chat, target.id, context):
            await message.reply_text(
                "⛔ Adminni ban qilib bo‘lmaydi."
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

    if command.startswith("*unban "):

        if not await admin_required(
            message, chat, user, context
        ):
            return

        parts = command.split()

        if len(parts) != 2:
            return

        try:
            target_id = int(parts[1])

            await context.bot.unban_chat_member(
                chat.id,
                target_id
            )

            await message.reply_text(
                "✅ Foydalanuvchi bandan chiqarildi."
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
                "⚠️ O‘chiriladigan xabarga reply qiling."
            )
            return

        try:
            await message.reply_to_message.delete()
            await message.delete()
        except Exception:
            await message.reply_text(
                "⚠️ Botga xabar o‘chirish huquqini bering."
            )

        return


    # ==================================================
    # LINK BLOK
    # ==================================================

    if command in ("*links on", "*links off"):

        if not await admin_required(
            message, chat, user, context
        ):
            return

        value = 1 if command == "*links on" else 0

        cursor.execute(
            """
            UPDATE settings
            SET link_block = ?
            WHERE chat_id = ?
            """,
            (value, chat.id)
        )

        db.commit()

        await message.reply_text(
            "🔗 Link himoyasi "
            + ("yoqildi." if value else "o‘chirildi.")
        )
        return


    # ==================================================
    # BLACKLIST
    # ==================================================

    if command.startswith("*blacklist "):

        if not await admin_required(
            message, chat, user, context
        ):
            return

        word = text[len("*blacklist "):].strip().lower()

        if not word:
            return

        cursor.execute(
            """
            INSERT OR IGNORE INTO blacklist
            (chat_id, word)
            VALUES (?, ?)
            """,
            (chat.id, word)
        )

        db.commit()

        await message.reply_text(
            f"🚫 Blacklistga qo‘shildi: {word}"
        )
        return


    if command.startswith("*unblacklist "):

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
            WHERE chat_id = ? AND word = ?
            """,
            (chat.id, word)
        )

        db.commit()

        await message.reply_text(
            f"✅ Blacklistdan olib tashlandi: {word}"
        )
        return


    if command == "*blacklists":

        if not await admin_required(
            message, chat, user, context
        ):
            return

        cursor.execute(
            """
            SELECT word FROM blacklist
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

        for i, row in enumerate(rows, 1):
            result += f"{i}. {row[0]}\n"

        await message.reply_text(result)
        return


    # ==================================================
    # FILTER
    # ==================================================

    if command.startswith("*filter "):

        if not await admin_required(
            message, chat, user, context
        ):
            return

        parts = text.split(maxsplit=2)

        if len(parts) < 3:
            await message.reply_text(
                "⚠️ *filter kalit javob"
            )
            return

        keyword = parts[1].lower()
        response = parts[2]

        cursor.execute(
            """
            INSERT INTO chat_filters
            (chat_id, keyword, response)
            VALUES (?, ?, ?)
            ON CONFLICT(chat_id, keyword)
            DO UPDATE SET response = excluded.response
            """,
            (chat.id, keyword, response)
        )

        db.commit()

        await message.reply_text(
            f"✅ Filter saqlandi: {keyword}"
        )
        return


    if command == "*filters":

        cursor.execute(
            """
            SELECT keyword FROM chat_filters
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

        for i, row in enumerate(rows, 1):
            result += f"{i}. {row[0]}\n"

        await message.reply_text(result)
        return


    if command.startswith("*stop "):

        if not await admin_required(
            message, chat, user, context
        ):
            return

        keyword = text[6:].strip().lower()

        cursor.execute(
            """
            DELETE FROM chat_filters
            WHERE chat_id = ? AND keyword = ?
            """,
            (chat.id, keyword)
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

        rules = text[len("*setrules "):].strip()

        cursor.execute(
            """
            UPDATE settings
            SET rules = ?
            WHERE chat_id = ?
            """,
            (rules, chat.id)
        )

        db.commit()

        await message.reply_text(
            "✅ Guruh qoidalari saqlandi."
        )
        return


    if command == "*rules":

        cursor.execute(
            """
            SELECT rules FROM settings
            WHERE chat_id = ?
            """,
            (chat.id,)
        )

        row = cursor.fetchone()
        rules = row[0] if row else ""

        if not rules:
            await message.reply_text(
                "📜 Hozircha guruh qoidalari yozilmagan."
            )
        else:
            await message.reply_text(
                f"📜 GURUH QOIDALARI\n\n{rules}"
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

        parts = text.split(maxsplit=2)

        if len(parts) < 3:
            await message.reply_text(
                "⚠️ *save nom matn"
            )
            return

        name = parts[1].lower()
        content = parts[2]

        cursor.execute(
            """
            INSERT INTO notes
            (chat_id, name, content)
            VALUES (?, ?, ?)
            ON CONFLICT(chat_id, name)
            DO UPDATE SET content = excluded.content
            """,
            (chat.id, name, content)
        )

        db.commit()

        await message.reply_text(
            f"📝 Note saqlandi: {name}"
        )
        return


    if command.startswith("*get "):

        name = text[5:].strip().lower()

        cursor.execute(
            """
            SELECT content FROM notes
            WHERE chat_id = ? AND name = ?
            """,
            (chat.id, name)
        )

        row = cursor.fetchone()

        if row:
            await message.reply_text(row[0])
        else:
            await message.reply_text(
                "⚠️ Bunday note topilmadi."
            )

        return


    if command == "*notes":

        cursor.execute(
            """
            SELECT name FROM notes
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

        for i, row in enumerate(rows, 1):
            result += f"{i}. {row[0]}\n"

        await message.reply_text(result)
        return


    if command.startswith("*clear "):

        if not await admin_required(
            message, chat, user, context
        ):
            return

        name = text[7:].strip().lower()

        cursor.execute(
            """
            DELETE FROM notes
            WHERE chat_id = ? AND name = ?
            """,
            (chat.id, name)
        )

        db.commit()

        await message.reply_text(
            f"🗑 Note o‘chirildi: {name}"
        )
        return


    # ==================================================
    # WELCOME / GOODBYE
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
        setting = parts[0][1:]
        value = 1 if parts[1] == "on" else 0

        cursor.execute(
            f"""
            UPDATE settings
            SET {setting} = ?
            WHERE chat_id = ?
            """,
            (value, chat.id)
        )

        db.commit()

        await message.reply_text(
            f"⚙️ {setting}: "
            + ("ON" if value else "OFF")
        )
        return


    # ==================================================
    # AKTIV
    # ==================================================

    if command == "*aktiv" or command.startswith("*aktiv "):

        parts = command.split()
        limit = 50

        if len(parts) == 2 and parts[1].isdigit():
            limit = max(
                1,
                min(int(parts[1]), 50)
            )

        cursor.execute(
            """
            SELECT name, messages
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
                "📊 Hali statistika yo‘q."
            )
            return

        result = (
            f"🏆 TOP {len(rows)} FAOL A’ZO\n\n"
        )

        medals = ["🥇", "🥈", "🥉"]

        for i, (name, count) in enumerate(
            rows,
            start=1
        ):

            icon = (
                medals[i - 1]
                if i <= 3
                else f"{i}."
            )

            result += (
                f"{icon} {name} — "
                f"{count} ta xabar\n"
            )

        await message.reply_text(result)
        return


    # ==================================================
    # MEN
    # ==================================================

    if command == "*men":

        cursor.execute(
            """
            SELECT messages FROM activity
            WHERE chat_id = ? AND user_id = ?
            """,
            (chat.id, user.id)
        )

        row = cursor.fetchone()
        count = row[0] if row else 0

        cursor.execute(
            """
            SELECT COUNT(*) + 1
            FROM activity
            WHERE chat_id = ?
            AND messages > ?
            """,
            (chat.id, count)
        )

        rank = cursor.fetchone()[0]

        await message.reply_text(
            f"👤 {get_name(user)}\n\n"
            f"💬 Xabarlar: {count}\n"
            f"🏆 Reyting: {rank}"
        )
        return


    # ==================================================
    # OWNER RUXSAT
    # ==================================================

    if command == "*ruxsat":

        if user.id != OWNER_ID:
            return

        target = reply_target(message)

        if not target:
            await message.reply_text(
                "⚠️ Xabarga reply qilib *ruxsat yozing."
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
            f"✅ {get_name(target)} ga ruxsat berildi."
        )
        return


    # ==================================================
    # BUYRUQ BO'LSA, PASTGA O'TKAZMAYMIZ
    # ==================================================

    if text.startswith("*"):
        return


    # ==================================================
    # LINK HIMOYASI
    # ==================================================

    cursor.execute(
        """
        SELECT link_block FROM settings
        WHERE chat_id = ?
        """,
        (chat.id,)
    )

    row = cursor.fetchone()
    link_block = row[0] if row else 0

    if (
        link_block
        and contains_link(text)
        and not await is_admin(
            chat, user.id, context
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
        SELECT word FROM blacklist
        WHERE chat_id = ?
        """,
        (chat.id,)
    )

    bad_words = cursor.fetchall()

    lower_text = text.lower()

    for row in bad_words:

        if row[0] in lower_text:

            if not await is_admin(
                chat, user.id, context
            ):
                try:
                    await message.delete()
                except Exception:
                    pass

                return


    # ==================================================
    # FILTER ISHLATISH
    # ==================================================

    cursor.execute(
        """
        SELECT response FROM chat_filters
        WHERE chat_id = ? AND keyword = ?
        """,
        (chat.id, command)
    )

    row = cursor.fetchone()

    if row:
        await message.reply_text(row[0])


    # ==================================================
    # FAOLLIK
    # ==================================================

    if text:

        cursor.execute(
            """
            INSERT INTO activity
            (
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

    print("Veritas v2 ishga tushdi.")

    app.run_polling()


if __name__ == "__main__":
    main()
