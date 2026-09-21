import os
import sqlite3
from telegram import Update
from telegram.ext import (
    Application,
    ContextTypes,
    MessageHandler,
    filters,
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = 5859289233
# Ma'lumotlar bazasi
db = sqlite3.connect("veritas.db", check_same_thread=False)
cursor = db.cursor()

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
db.commit()
cursor.execute("""
CREATE TABLE IF NOT EXISTS allowed_users (
    user_id INTEGER PRIMARY KEY
)
""")
db.commit()
def is_allowed(user_id):
    if user_id == OWNER_ID:
        return True

    cursor.execute(
        "SELECT user_id FROM allowed_users WHERE user_id = ?",
        (user_id,)
    )
    return cursor.fetchone() is not None
def get_name(user):
    if user.username:
        return f"@{user.username}"
    return user.full_name


async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat

    if not message or not user or not chat:
        return
    text = (message.text or "").strip()
    command = text.lower()

    if command.startswith("*") and not is_allowed(user.id):
        return
    if message.text and message.text.strip().lower() == "*id":
        await message.reply_text(f"🆔 Sizning Telegram ID: {user.id}")
        return
    if message.text == "/start":
        await message.reply_text(
            "👋 Veritas botga xush kelibsiz!\n\n"
            "📊 Guruh faolligini kuzatish tizimi ishga tushgan."
        )
        return
    # Faqat guruh va superguruhlar
    if chat.type not in ("group", "supergroup"):
        return

    # Botlarning xabarlarini hisoblamaymiz
    if user.is_bot:
        return


    # "aktiv", "aktiv 10", "aktiv 20" va hokazo
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
            (chat.id, limit)
        )

        rows = cursor.fetchall()

        if not rows:
            await message.reply_text(
                "📊 Hali faollik ma'lumotlari yo‘q."
            )
            return

        result = f"🏆 TOP {len(rows)} FAOL A'ZO\n\n"

        medals = ["🥇", "🥈", "🥉"]

        for i, (name, count) in enumerate(rows, start=1):
            icon = medals[i - 1] if i <= 3 else f"{i}."
            result += f"{icon} {name} — {count} ta xabar\n"

        await message.reply_text(result)
        return

    # "men" — shaxsiy statistika
        if command == "*men":
        cursor.execute(
            """
            SELECT messages
            FROM activity
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
            f"🏆 Reytingdagi o‘rningiz: {rank}"
        )
        return
        # Foydalanuvchiga buyruq berish huquqini berish
    if command == "*ruxsat":
        if user.id != OWNER_ID:
            return

        if not message.reply_to_message:
            await message.reply_text(
                "⚠️ Ruxsat bermoqchi bo‘lgan odamning xabariga Reply qilib *ruxsat yozing."
            )
            return

        target = message.reply_to_message.from_user

        cursor.execute(
            "INSERT OR IGNORE INTO allowed_users (user_id) VALUES (?)",
            (target.id,)
        )
        db.commit()

        await message.reply_text(
            f"✅ {get_name(target)} ga buyruqlardan foydalanish ruxsati berildi."
        )
        return
    # Oddiy xabarni faollikka qo‘shish
    cursor.execute(
        """
        INSERT INTO activity
        (chat_id, user_id, name, username, messages)
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
            user.username
        )
    )

    db.commit()


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN topilmadi!")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(
        MessageHandler(filters.ALL, handle_message)
    )

    print("Veritas ishga tushdi.")
    app.run_polling()


if __name__ == "__main__":
    main()
