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

# ==================================================
# ASOSIY SOZLAMALAR
# ==================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")

# Veritas egasi
OWNER_ID = 5859289233


# ==================================================
# DATABASE
# ==================================================

db = sqlite3.connect(
    "veritas.db",
    check_same_thread=False
)

cursor = db.cursor()


# Faollik
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


# Filterlar
cursor.execute("""
CREATE TABLE IF NOT EXISTS chat_filters (
    chat_id INTEGER,
    keyword TEXT,
    response TEXT DEFAULT '',
    media_type TEXT DEFAULT 'text',
    file_id TEXT DEFAULT '',
    caption TEXT DEFAULT '',
    PRIMARY KEY (chat_id, keyword)
)
""")


# Eski database bilan moslik
for column, definition in [
    ("media_type", "TEXT DEFAULT 'text'"),
    ("file_id", "TEXT DEFAULT ''"),
    ("caption", "TEXT DEFAULT ''"),
]:
    try:
        cursor.execute(
            f"""
            ALTER TABLE chat_filters
            ADD COLUMN {column} {definition}
            """
        )
    except sqlite3.OperationalError:
        pass


# Warnlar
cursor.execute("""
CREATE TABLE IF NOT EXISTS warnings (
    chat_id INTEGER,
    user_id INTEGER,
    warns INTEGER DEFAULT 0,
    PRIMARY KEY (chat_id, user_id)
)
""")


# Blacklist
cursor.execute("""
CREATE TABLE IF NOT EXISTS blacklist (
    chat_id INTEGER,
    word TEXT,
    PRIMARY KEY (chat_id, word)
)
""")


# Guruh sozlamalari
cursor.execute("""
CREATE TABLE IF NOT EXISTS settings (
    chat_id INTEGER PRIMARY KEY,
    link_block INTEGER DEFAULT 0,
    welcome INTEGER DEFAULT 1,
    goodbye INTEGER DEFAULT 1,
    rules TEXT DEFAULT ''
)
""")


# Notes
cursor.execute("""
CREATE TABLE IF NOT EXISTS notes (
    chat_id INTEGER,
    name TEXT,
    content TEXT,
    PRIMARY KEY (chat_id, name)
)
""")


# Veritas ichki adminlari
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
    if not text:
        return False

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
        SELECT 1
        FROM allowed_users
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
*help — barcha buyruqlar
*id — Telegram ID
*men — shaxsiy statistika
*aktiv — faol a’zolar
*aktiv 10 — TOP 10
*rules — guruh qoidalari
*warns — warnlarni ko‘rish

🛡 MODERATSIYA
*warn — warn berish
*unwarn — bitta warn olish
*clearwarns — warnlarni tozalash
*mute — mute
*unmute — unmute
*kick — guruhdan chiqarish
*ban — ban
*unban — reply orqali unban
*unban ID — ID orqali unban
*del — xabarni o‘chirish

👮 GURUH ADMINI
*admin — reply orqali admin berish
*unadmin — adminlikdan olish

🔐 VERITAS ADMINI
*ruxsat — Veritas ruxsati berish
*ruxsatsiz — Veritas ruxsatini olish

🎁 GIFT
*give 25
*give 50
*give 100
Gift buyruqlarini faqat bot egasi ishlata oladi.

🔗 HIMOYA
*links on
*links off
*blacklist so‘z
*unblacklist so‘z
*blacklists

💬 FILTER
*filter kalit javob
*filter kalit — mediaga reply
*filters
*stop kalit
*stopall

📝 NOTES
*save nom matn
*get nom
*notes
*clear nom

⚙️ SOZLAMALAR
*welcome on
*welcome off
*goodbye on
*goodbye off
*setrules matn
*admins
""".strip()


# ==================================================
# WELCOME
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
        SELECT welcome
        FROM settings
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
            "xush kelibsiz."
        )


# ==================================================
# GOODBYE
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
        SELECT goodbye
        FROM settings
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
# MEDIA FILTER YORDAMCHISI
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
            photo=file_id,
            caption=caption or None
        )

    elif media_type == "video":
        await message.reply_video(
            video=file_id,
            caption=caption or None
        )

    elif media_type == "animation":
        await message.reply_animation(
            animation=file_id,
            caption=caption or None
        )

    elif media_type == "audio":
        await message.reply_audio(
            audio=file_id,
            caption=caption or None
        )

    elif media_type == "voice":
        await message.reply_voice(
            voice=file_id
        )

    elif media_type == "document":
        await message.reply_document(
            document=file_id,
            caption=caption or None
)
        # ==================================================
# GIFT YORDAMCHILARI
# ==================================================

async def give_gift(
    message,
    user,
    context,
    amount
):
    # Faqat bot egasi
    if user.id != OWNER_ID:
        await message.reply_text(
            "⛔ Bu buyruq faqat bot egasi uchun."
        )
        return

    # Foydalanuvchi xabariga reply shart
    target = reply_target(message)

    if not target:
        await message.reply_text(
            f"🎁 {amount} Starslik Gift berish uchun "
            "foydalanuvchining xabariga reply qilib:\n\n"
            f"*give {amount}"
        )
        return

    if target.is_bot:
        await message.reply_text(
            "⛔ Botga Gift berilmaydi."
        )
        return

    try:
        # Telegramdagi hozir mavjud Giftlarni olamiz
        gifts = await context.bot.get_available_gifts()

        selected_gift = None

        for gift in gifts.gifts:
            if gift.star_count == amount:
                selected_gift = gift
                break

        if not selected_gift:
            await message.reply_text(
                f"⚠️ Hozir Telegramda aynan "
                f"{amount} Starslik Gift mavjud emas."
            )
            return

        # Giftni reply qilingan foydalanuvchiga yuboramiz
        await context.bot.send_gift(
            user_id=target.id,
            gift_id=selected_gift.id,
            text=(
                "🎁 Veritas tomonidan sovg‘a!"
            )
        )

        await message.reply_text(
            f"🎁 {get_name(target)} ga "
            f"{amount} Starslik Gift yuborildi."
        )

    except AttributeError:
        await message.reply_text(
            "⚠️ Serverdagi python-telegram-bot "
            "versiyasi Gift funksiyasini "
            "qo‘llamayapti."
        )

    except Exception as error:
        print(
            "GIFT ERROR:",
            repr(error)
        )

        await message.reply_text(
            "⚠️ Gift yuborilmadi.\n"
            "Bot balansini va Telegramdagi "
            "mavjud Giftlarni tekshiring."
        )


# ==================================================
# ASOSIY MESSAGE HANDLER
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
        message.text
        or message.caption
        or ""
    ).strip()

    command = text.lower()


    # ==================================================
    # PRIVATE CHAT
    # ==================================================

    if chat.type == "private":

        if command in (
            "/start",
            "/help",
            "*start",
            "*help"
        ):
            await message.reply_text(
                HELP_TEXT
            )
            return

        if command == "*id":
            await message.reply_text(
                f"🆔 Telegram ID: {user.id}"
            )
            return

        await message.reply_text(
            "🛡 VERITAS\n\n"
            "Barcha buyruqlarni ko‘rish uchun:\n"
            "*help"
        )

        return


    # Faqat guruh va superguruh
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
                f"👤 {get_name(target)}\n"
                f"🆔 ID: {target.id}"
            )

        else:
            await message.reply_text(
                f"👤 {get_name(user)}\n"
                f"🆔 ID: {user.id}"
            )

        return


    # ==================================================
    # GIVE GIFT
    # ==================================================

    if command.startswith("*give"):

        parts = command.split()

        if len(parts) != 2:
            await message.reply_text(
                "🎁 Foydalanish:\n"
                "*give 25\n"
                "*give 50\n"
                "*give 100\n\n"
                "Foydalanuvchi xabariga reply qiling."
            )
            return

        try:
            amount = int(
                parts[1]
            )

        except ValueError:
            await message.reply_text(
                "⚠️ Gift qiymatini raqam bilan yozing."
            )
            return

        if amount not in (
            25,
            50,
            100
        ):
            await message.reply_text(
                "⚠️ Hozir ruxsat etilgan Giftlar:\n"
                "🎁 25 Stars\n"
                "🎁 50 Stars\n"
                "🎁 100 Stars"
            )
            return

        await give_gift(
            message,
            user,
            context,
            amount
        )

        return


    # ==================================================
    # VERITAS RUXSAT BERISH
    # ==================================================

    if command == "*ruxsat":

        if user.id != OWNER_ID:
            await message.reply_text(
                "⛔ Faqat bot egasi ruxsat bera oladi."
            )
            return

        target = reply_target(
            message
        )

        if not target:
            await message.reply_text(
                "⚠️ Foydalanuvchi xabariga "
                "reply qilib *ruxsat yozing."
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
            "Veritas admin ruxsati berildi."
        )

        return


    # ==================================================
    # VERITAS RUXSATINI OLISH
    # ==================================================

    if command == "*ruxsatsiz":

        if user.id != OWNER_ID:
            await message.reply_text(
                "⛔ Faqat bot egasi ruxsatni "
                "olib tashlay oladi."
            )
            return

        target = reply_target(
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
            DELETE FROM allowed_users
            WHERE user_id = ?
            """,
            (target.id,)
        )

        db.commit()

        await message.reply_text(
            f"🔒 {get_name(target)} dan "
            "Veritas admin ruxsati olindi."
        )

        return


    # ==================================================
    # TELEGRAM ADMINLAR RO'YXATI
    # ==================================================

    if command == "*admins":

        try:
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

        except Exception:
            await message.reply_text(
                "⚠️ Adminlar ro‘yxatini "
                "olishda xato."
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
                "⚠️ Foydalanuvchi xabariga "
                "reply qilib *admin yozing."
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
                "guruh admini qilindi."
            )

        except Exception as error:
            print(
                "ADMIN ERROR:",
                repr(error)
            )

            await message.reply_text(
                "⚠️ Admin berilmadi.\n"
                "VeritasBot'ga yangi admin "
                "qo‘shish huquqi berilganini tekshiring."
            )

        return


    # ==================================================
    # TELEGRAM ADMINLIKNI OLISH
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
                "⚠️ Admin xabariga reply qilib "
                "*unadmin yozing."
            )
            return

        if target.id == OWNER_ID:
            await message.reply_text(
                "⛔ Bot egasining adminligini "
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

        except Exception as error:
            print(
                "UNADMIN ERROR:",
                repr(error)
            )

            await message.reply_text(
                "⚠️ Adminlikni olishda xato.\n"
                "Bot huquqlarini tekshiring."
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
                "⛔ Telegram adminiga warn "
                "berib bo‘lmaydi."
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

            ON CONFLICT(chat_id, user_id)
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
            f"⚠️ {get_name(target)}\n"
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
                    "3 ta warn sabab ban qilindi.\n"
                    "♻️ Warnlari 0 ga qaytarildi."
                )

            except Exception as error:
                print(
                    "WARN BAN ERROR:",
                    repr(error)
                )

                await message.reply_text(
                    "⚠️ 3 ta warn bo‘ldi, "
                    "lekin bot ban qila olmadi.\n"
                    "Bot admin huquqlarini tekshiring."
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
            SELECT warns
            FROM warnings
            WHERE chat_id = ?
            AND user_id = ?
            """,
            (chat.id, target.id)
        )

        row = cursor.fetchone()
        warns = row[0] if row else 0
        warns = max(0, warns - 1)

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
                (warns, chat.id, target.id)
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
            WHERE chat_id = ?
            AND user_id = ?
            """,
            (chat.id, target.id)
        )

        db.commit()

        await message.reply_text(
            f"♻️ {get_name(target)} "
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

        if await is_telegram_admin(
            chat, target.id, context
        ):
            await message.reply_text(
                "⛔ Telegram adminini mute qilib bo‘lmaydi."
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
                "⚠️ Mute qilinmadi. "
                "Botga a’zolarni cheklash "
                "huquqini bering."
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
                chat_id=chat.id,
                user_id=target.id
            )

            await context.bot.unban_chat_member(
                chat_id=chat.id,
                user_id=target.id
            )

            await message.reply_text(
                f"👢 {get_name(target)} "
                "guruhdan chiqarildi."
            )

        except Exception as error:
            print(
                "KICK ERROR:",
                repr(error)
            )

            await message.reply_text(
                "⚠️ Kick qilinmadi. "
                "Botning admin huquqlarini tekshiring."
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
                chat_id=chat.id,
                user_id=target.id
            )

            await message.reply_text(
                f"🔨 {get_name(target)} ban qilindi."
            )

        except Exception as error:
            print(
                "BAN ERROR:",
                repr(error)
            )

            await message.reply_text(
                "⚠️ Ban qilinmadi. "
                "Botning admin huquqlarini tekshiring."
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

        if target_id is None:

            parts = command.split()

            if len(parts) == 2:
                try:
                    target_id = int(parts[1])
                except ValueError:
                    target_id = None

        if target_id is None:
            await message.reply_text(
                "⚠️ Foydalanuvchining eski "
                "xabariga reply qilib *unban yozing.\n\n"
                "Yoki:\n"
                "*unban ID"
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
                "✅ Foydalanuvchi bandan chiqarildi.\n"
                "♻️ Warnlari ham tozalandi."
            )

        except Exception as error:
            print(
                "UNBAN ERROR:",
                repr(error)
            )

            await message.reply_text(
                "⚠️ Unban qilinmadi. "
                "ID va bot huquqlarini tekshiring."
            )

        return


    # ==================================================
    # DELETE MESSAGE
    # ==================================================

    if command == "*del":

        if not await admin_required(
            message, chat, user, context
        ):
            return

        if not message.reply_to_message:
            await message.reply_text(
                "⚠️ O‘chiriladigan xabarga "
                "reply qilib *del yozing."
            )
            return

        try:
            await message.reply_to_message.delete()

            try:
                await message.delete()
            except Exception:
                pass

        except Exception as error:
            print(
                "DELETE ERROR:",
                repr(error)
            )

            await message.reply_text(
                "⚠️ Xabar o‘chirilmadi. "
                "Botga xabarlarni o‘chirish "
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
            (value, chat.id)
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
    # BLACKLISTGA QO'SHISH
    # ==================================================

    if command.startswith("*blacklist "):

        if not await admin_required(
            message, chat, user, context
        ):
            return

        word = text[
            len("*blacklist "):
        ].strip().lower()

        if not word:
            await message.reply_text(
                "⚠️ Masalan:\n"
                "*blacklist yomonsoz"
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


    # ==================================================
    # BLACKLISTDAN OLISH
    # ==================================================

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


    # ==================================================
    # BLACKLIST RO'YXATI
    # ==================================================

    if command == "*blacklists":

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

        for number, row in enumerate(
            rows,
            start=1
        ):
            result += (
                f"{number}. {row[0]}\n"
            )

        await message.reply_text(result)
        return


    # ==================================================
    # FILTER QO'SHISH
    # ==================================================

    if command.startswith("*filter "):

        if not await admin_required(
            message, chat, user, context
        ):
            return

        rest = text[
            len("*filter "):
        ].strip()

        if not rest:
            await message.reply_text(
                "⚠️ Matn filter:\n"
                "*filter salom Assalomu alaykum\n\n"
                "🎞 Media filter:\n"
                "Rasm, video, sticker yoki boshqa "
                "mediaga reply qilib:\n"
                "*filter salom"
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

        # ==============================================
        # MATN FILTER
        # ==============================================

        if len(parts) == 2:

            response = parts[1].strip()

            if not response:
                await message.reply_text(
                    "⚠️ Filter javobini yozing."
                )
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
                f"✅ Matn filter saqlandi:\n"
                f"🔑 {keyword}"
            )

            return


        # ==============================================
        # MEDIA FILTER
        # ==============================================

        replied = message.reply_to_message

        if not replied:
            await message.reply_text(
                "⚠️ Media filter uchun rasm, video, "
                "sticker, GIF, audio, voice yoki "
                "faylga reply qiling.\n\n"
                f"Keyin:\n*filter {keyword}"
            )
            return

        media_type, file_id, caption = (
            media_from_message(replied)
        )

        if not media_type or not file_id:
            await message.reply_text(
                "⚠️ Reply qilingan xabarda "
                "saqlanadigan media topilmadi."
            )
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
            VALUES (?, ?, '', ?, ?, ?)

            ON CONFLICT(chat_id, keyword)
            DO UPDATE SET
                response = '',
                media_type = excluded.media_type,
                file_id = excluded.file_id,
                caption = excluded.caption
            """,
            (
                chat.id,
                keyword,
                media_type,
                file_id,
                caption or ""
            )
        )

        db.commit()

        await message.reply_text(
            f"✅ Media filter saqlandi:\n"
            f"🔑 {keyword}\n"
            f"🎞 Turi: {media_type}"
        )

        return


    # ==================================================
    # FILTERLAR RO'YXATI
    # ==================================================

    if command == "*filters":

        cursor.execute(
            """
            SELECT
                keyword,
                media_type
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

        result = "💬 FILTERLAR\n\n"

        for number, row in enumerate(
            rows,
            start=1
        ):
            keyword = row[0]
            media_type = row[1] or "text"

            if media_type == "text":
                icon = "📝"
            elif media_type == "sticker":
                icon = "🎭"
            elif media_type == "photo":
                icon = "🖼"
            elif media_type == "video":
                icon = "🎬"
            elif media_type == "animation":
                icon = "🎞"
            elif media_type == "audio":
                icon = "🎵"
            elif media_type == "voice":
                icon = "🎤"
            elif media_type == "document":
                icon = "📎"
            else:
                icon = "📌"

            result += (
                f"{number}. {icon} {keyword}\n"
            )

        await message.reply_text(result)
        return


    # ==================================================
    # BITTA FILTERNI O'CHIRISH
    # ==================================================

    if command.startswith("*stop "):

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
            (chat.id, keyword)
        )

        deleted = cursor.rowcount
        db.commit()

        if deleted:
            await message.reply_text(
                f"🗑 Filter o‘chirildi: {keyword}"
            )
        else:
            await message.reply_text(
                f"⚠️ Filter topilmadi: {keyword}"
            )

        return


    # ==================================================
    # BARCHA FILTERLARNI O'CHIRISH
    # ==================================================

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

        deleted = cursor.rowcount
        db.commit()

        await message.reply_text(
            f"🗑 {deleted} ta filter o‘chirildi."
        )

        return
            # ==================================================
    # RULES O'RNATISH
    # ==================================================

    if command.startswith("*setrules "):

        if not await admin_required(
            message, chat, user, context
        ):
            return

        rules = text[
            len("*setrules "):
        ].strip()

        if not rules:
            await message.reply_text(
                "⚠️ Qoidalarni yozing."
            )
            return

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


    # ==================================================
    # RULES KO'RISH
    # ==================================================

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
                "📭 Hozircha guruh "
                "qoidalari yozilmagan."
            )

        return


    # ==================================================
    # NOTE SAQLASH
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
                "⚠️ Masalan:\n"
                "*save aloqa Biz bilan bog‘lanish..."
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
            f"📝 Note saqlandi: {name}"
        )

        return


    # ==================================================
    # NOTE OLISH
    # ==================================================

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
                f"⚠️ Note topilmadi: {name}"
            )

        return


    # ==================================================
    # NOTES RO'YXATI
    # ==================================================

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

        for number, row in enumerate(
            rows,
            start=1
        ):
            result += (
                f"{number}. {row[0]}\n"
            )

        await message.reply_text(result)
        return


    # ==================================================
    # NOTE O'CHIRISH
    # ==================================================

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

        deleted = cursor.rowcount
        db.commit()

        if deleted:
            await message.reply_text(
                f"🗑 Note o‘chirildi: {name}"
            )
        else:
            await message.reply_text(
                f"⚠️ Note topilmadi: {name}"
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

        status = (
            "ON"
            if value
            else "OFF"
        )

        await message.reply_text(
            f"⚙️ {setting}: {status}"
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
                "📊 Hali faollik statistikasi yo‘q."
            )
            return

        result = (
            f"🏆 TOP {len(rows)} FAOL A’ZO\n\n"
        )

        medals = [
            "🥇",
            "🥈",
            "🥉"
        ]

        for number, (
            name,
            count
        ) in enumerate(
            rows,
            start=1
        ):

            if number <= 3:
                icon = medals[number - 1]
            else:
                icon = f"{number}."

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
    # NOTANISH * BUYRUQLARNI HISOBLAMAYMIZ
    # ==================================================

    if text.startswith("*"):
        return


    # ==================================================
    # LINKNI AVTOMATIK TEKSHIRISH
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
        except Exception as error:
            print(
                "LINK DELETE ERROR:",
                repr(error)
            )

        return


    # ==================================================
    # BLACKLISTNI AVTOMATIK TEKSHIRISH
    # ==================================================

    cursor.execute(
        """
        SELECT word
        FROM blacklist
        WHERE chat_id = ?
        """,
        (chat.id,)
    )

    blacklist_rows = cursor.fetchall()

    lower_text = text.lower()

    for row in blacklist_rows:

        bad_word = row[0]

        if (
            bad_word in lower_text
            and not await is_admin(
                chat,
                user.id,
                context
            )
        ):
            try:
                await message.delete()
            except Exception as error:
                print(
                    "BLACKLIST DELETE ERROR:",
                    repr(error)
                )

            return


    # ==================================================
    # FILTERNI AVTOMATIK ISHLATISH
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

            response = row[0] or ""
            media_type = row[1] or "text"
            file_id = row[2] or ""
            caption = row[3] or ""

            try:
                await send_saved_filter(
                    message,
                    media_type,
                    file_id,
                    response,
                    caption
                )

            except Exception as error:
                print(
                    "FILTER SEND ERROR:",
                    repr(error)
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
# BOTNI ISHGA TUSHIRISH
# ==================================================

def main():

    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN topilmadi! "
            "Railway Variables bo‘limini tekshiring."
        )

    app = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .build()
    )

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

    # Barcha xabarlar va * buyruqlar
    app.add_handler(
        MessageHandler(
            filters.ALL,
            handle_message
        ),
        group=1
    )

    print(
        "Veritas Gift v4 ishga tushdi."
    )

    app.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


# ==================================================
# START
# ==================================================

if __name__ == "__main__":
    main()
