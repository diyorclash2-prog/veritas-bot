import os
import sqlite3

from telegram import (
Update, 
InlineKeyboardButton, 
InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    ContextTypes,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)


BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = 5859289233

db = sqlite3.connect("veritas.db", check_same_thread=False)
cursor = db.cursor()


# =========================
# MA'LUMOTLAR BAZASI
# =========================

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
CREATE TABLE IF NOT EXISTS allowed_users (
    user_id INTEGER PRIMARY KEY
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

db.commit()


# =========================
# YORDAMCHI FUNKSIYALAR
# =========================

def get_name(user):
    if user.username:
        return f"@{user.username}"
    return user.full_name


def is_allowed(user_id):
    if user_id == OWNER_ID:
        return True

    cursor.execute(
        "SELECT user_id FROM allowed_users WHERE user_id = ?",
        (user_id,)
    )

    return cursor.fetchone() is not None


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
            "owner",
        )

    except Exception:
        return False


# =========================
# ASOSIY XABAR HANDLER
# =========================

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


    # =====================
    # /start
    # =====================

    if command == "/start":
        await message.reply_text(
            "👋 Veritas botga xush kelibsiz!\n\n"
            "📊 Guruh faolligini kuzatish tizimi ishga tushgan."
        )
        return


    # =====================
    # *id
    # =====================

    if command == "*id":
        await message.reply_text(
            f"🆔 Sizning Telegram ID: {user.id}"
        )
        return


    # Quyidagi funksiyalar guruh uchun
    if chat.type not in ("group", "supergroup"):
        return


    # =====================
    # FILTER QO'SHISH
    # Faqat owner yoki Telegram admin
    # =====================

    if command.startswith("*filter "):

        if not await is_admin(chat, user.id, context):
            await message.reply_text(
                "⛔ Filter qo‘shish faqat adminlar uchun."
            )
            return

        parts = text.split(maxsplit=2)

        if len(parts) < 3:
            await message.reply_text(
                "⚠️ Format:\n"
                "*filter kalit_so‘z javob"
            )
            return

        keyword = parts[1].strip().lower()
        response = parts[2].strip()

        cursor.execute(
            """
            INSERT INTO chat_filters
                (chat_id, keyword, response)
            VALUES (?, ?, ?)
            ON CONFLICT(chat_id, keyword)
            DO UPDATE SET
                response = excluded.response
            """,
            (
                chat.id,
                keyword,
                response,
            )
        )

        db.commit()

        await message.reply_text(
            f"✅ Filter saqlandi:\n"
            f"🔑 {keyword}"
        )
        return


    # =====================
    # FILTERLAR RO'YXATI
    # Faqat owner yoki admin
    # =====================

    if command == "*filters":

        if not await is_admin(chat, user.id, context):
            return

        cursor.execute(
            """
            SELECT keyword
            FROM chat_filters
            WHERE chat_id = ?
            ORDER BY keyword
            """,
            (chat.id,)
        )

        rows = cursor.fetchall()

        if not rows:
            await message.reply_text(
                "📭 Hozircha filterlar yo‘q."
            )
            return

        result = "📋 FILTERLAR:\n\n"

        for i, row in enumerate(rows, start=1):
            result += f"{i}. {row[0]}\n"

        await message.reply_text(result)
        return


    # =====================
    # BITTA FILTERNI O'CHIRISH
    # =====================

    if command.startswith("*stop "):

        if not await is_admin(chat, user.id, context):
            await message.reply_text(
                "⛔ Filter o‘chirish faqat adminlar uchun."
            )
            return

        keyword = text[6:].strip().lower()

        if not keyword:
            return

        cursor.execute(
            """
            DELETE FROM chat_filters
            WHERE chat_id = ?
            AND keyword = ?
            """,
            (
                chat.id,
                keyword,
            )
        )

        deleted = cursor.rowcount
        db.commit()

        if deleted:
            await message.reply_text(
                f"🗑 Filter o‘chirildi:\n"
                f"🔑 {keyword}"
            )
        else:
            await message.reply_text(
                "⚠️ Bunday filter topilmadi."
            )

        return


    # =====================
    # HAMMA FILTERNI O'CHIRISH
    # =====================

    if command == "*stopall":

        if not await is_admin(chat, user.id, context):
            await message.reply_text(
                "⛔ Bu buyruq faqat adminlar uchun."
            )
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
            f"🗑 {deleted} ta filter o‘chirildi."
        )
        return


    # =====================
    # *ruxsat
    # Faqat bot egasi
    # =====================

    if command == "*ruxsat":

        if user.id != OWNER_ID:
            return

        if not message.reply_to_message:
            await message.reply_text(
                "⚠️ Ruxsat bermoqchi bo‘lgan odamning "
                "xabariga reply qilib *ruxsat yozing."
            )
            return

        target = message.reply_to_message.from_user

        if not target:
            await message.reply_text(
                "⚠️ Foydalanuvchini aniqlab bo‘lmadi."
            )
            return

        cursor.execute(
            """
            INSERT OR IGNORE INTO allowed_users (user_id)
            VALUES (?)
            """,
            (target.id,)
        )

        db.commit()

        await message.reply_text(
            f"✅ {get_name(target)} ga buyruqlardan "
            "foydalanish huquqi berildi."
        )
        return


    # =====================
    # *aktiv
    # =====================

    if command == "*aktiv" or command.startswith("*aktiv "):

        parts = command.split()
        limit = 50

        if len(parts) == 2 and parts[1].isdigit():
            limit = int(parts[1])
            limit = max(1, min(limit, 50))

        cursor.execute(
            """
            SELECT name, messages
            FROM activity
            WHERE chat_id = ?
            ORDER BY messages DESC
            LIMIT ?
            """,
            (
                chat.id,
                limit,
            )
        )

        rows = cursor.fetchall()

        if not rows:
            await message.reply_text(
                "📊 Hali faollik ma’lumotlari yo‘q."
            )
            return

        result = f"🏆 TOP {len(rows)} FAOL A’ZO\n\n"
        medals = ["🥇", "🥈", "🥉"]

        for i, (name, count) in enumerate(
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

        await message.reply_text(result)
        return


    # =====================
    # *men
    # =====================

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
                user.id,
            )
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
            (
                chat.id,
                count,
            )
        )

        rank = cursor.fetchone()[0]

        await message.reply_text(
            f"👤 {get_name(user)}\n\n"
            f"💬 Xabarlar: {count}\n"
            f"🏆 Reytingdagi o‘rningiz: {rank}"
        )
        return


    # =====================
    # FILTER ISHLATISH
    # Barcha a'zolar uchun
    # =====================

    if text and not text.startswith("*"):

        cursor.execute(
            """
            SELECT response
            FROM chat_filters
            WHERE chat_id = ?
            AND keyword = ?
            """,
            (
                chat.id,
                command,
            )
        )

        filter_row = cursor.fetchone()

        if filter_row:
            await message.reply_text(
                filter_row[0]
            )


    # =====================
    # FAOLLIKNI SANASH
    # =====================

    if text and not text.startswith("*"):

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
                user.username or "",
            )
        )

        db.commit()


# =========================
# BOTNI ISHGA TUSHIRISH
# =========================
async def welcome_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message

    if not message or not message.new_chat_members:
        return

    for member in message.new_chat_members:
        if member.is_bot:
            continue

        await message.reply_text(
            f"👋 Xush kelibsiz, {member.full_name}!\n\n"
            "My Book guruhiga xush kelibsiz."
        )
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
        )
            )
    app.add_handler(
        MessageHandler(
            filters.ALL,
            handle_message
        )
    )

    print("Veritas ishga tushdi.")

    app.run_polling()


if __name__ == "__main__":
    main()
