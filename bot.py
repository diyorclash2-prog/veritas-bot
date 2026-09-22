import os
import re
import sqlite3

from telegram import Update, ChatPermissions, LabeledPrice
from telegram.ext import (
    Application,
    ContextTypes,
    MessageHandler,
    PreCheckoutQueryHandler,
    filters,
)

# =========================================================
# VERITAS BOT
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")

# Veritas egasi
OWNER_ID = 5859289233


# =========================================================
# DATABASE
# =========================================================

db = sqlite3.connect(
    "veritas.db",
    check_same_thread=False
)

cursor = db.cursor()


# ---------------------------------------------------------
# FAOLLIK
# ---------------------------------------------------------

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


# ---------------------------------------------------------
# FILTERLAR
# ---------------------------------------------------------

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


# Eski bazaga yangi ustunlarni qo‘shish
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


# ---------------------------------------------------------
# OGOHLANTIRISHLAR
# ---------------------------------------------------------

cursor.execute("""
CREATE TABLE IF NOT EXISTS warnings (
    chat_id INTEGER,
    user_id INTEGER,
    warns INTEGER DEFAULT 0,
    PRIMARY KEY (chat_id, user_id)
)
""")


# ---------------------------------------------------------
# QORA RO‘YXAT
# ---------------------------------------------------------

cursor.execute("""
CREATE TABLE IF NOT EXISTS blacklist (
    chat_id INTEGER,
    word TEXT,
    PRIMARY KEY (chat_id, word)
)
""")


# ---------------------------------------------------------
# GURUH SOZLAMALARI
# ---------------------------------------------------------

cursor.execute("""
CREATE TABLE IF NOT EXISTS settings (
    chat_id INTEGER PRIMARY KEY,
    link_block INTEGER DEFAULT 0,
    welcome INTEGER DEFAULT 1,
    goodbye INTEGER DEFAULT 1,
    rules TEXT DEFAULT ''
)
""")


# ---------------------------------------------------------
# ESLATMALAR / NOTES
# ---------------------------------------------------------

cursor.execute("""
CREATE TABLE IF NOT EXISTS notes (
    chat_id INTEGER,
    name TEXT,
    content TEXT,
    PRIMARY KEY (chat_id, name)
)
""")


# ---------------------------------------------------------
# VERITAS ICHKI ADMINLARI
# ---------------------------------------------------------

cursor.execute("""
CREATE TABLE IF NOT EXISTS allowed_users (
    user_id INTEGER PRIMARY KEY
)
""")


db.commit()


# =========================================================
# YORDAMCHI FUNKSIYALAR
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
    if (
        message
        and message.reply_to_message
        and message.reply_to_message.from_user
    ):
        return message.reply_to_message.from_user

    return None


def contains_link(text):
    if not text:
        return False

    pattern = (
        r"(https?://\S+|"
        r"www\.\S+|"
        r"t\.me/\S+|"
        r"telegram\.me/\S+)"
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
    user,
    context
):
    if await is_admin(
        message.chat,
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
    user,
    context
):
    if user.id == OWNER_ID:
        return True

    if await is_telegram_admin(
        message.chat,
        user.id,
        context
    ):
        return True

    await message.reply_text(
        "⛔ Bu buyruq uchun Telegram admin "
        "huquqi kerak."
    )

    return False


# =========================================================
# MEDIA ANIQLASH
# =========================================================

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

    return (
        "text",
        "",
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
    if media_type == "sticker":
        await context.bot.send_sticker(
            chat_id=message.chat.id,
            sticker=file_id
        )

    elif media_type == "photo":
        await context.bot.send_photo(
            chat_id=message.chat.id,
            photo=file_id,
            caption=caption or response or None
        )

    elif media_type == "video":
        await context.bot.send_video(
            chat_id=message.chat.id,
            video=file_id,
            caption=caption or response or None
        )

    elif media_type == "animation":
        await context.bot.send_animation(
            chat_id=message.chat.id,
            animation=file_id,
            caption=caption or response or None
        )

    elif media_type == "audio":
        await context.bot.send_audio(
            chat_id=message.chat.id,
            audio=file_id,
            caption=caption or response or None
        )

    elif media_type == "voice":
        await context.bot.send_voice(
            chat_id=message.chat.id,
            voice=file_id
        )

    elif media_type == "document":
        await context.bot.send_document(
            chat_id=message.chat.id,
            document=file_id,
            caption=caption or response or None
        )

    else:
        await message.reply_text(
            response
        )


# =========================================================
# HELP
# =========================================================

HELP_TEXT = """
🤖 VERITAS BOT

⭐ ASOSIY
*help
*id
*men
*aktiv
*aktiv 10
*rules
*warns

🛡 MODERATSIYA
*warn
*unwarn
*clearwarns
*mute
*unmute
*kick
*ban
*unban
*del

🔗 HIMOYA
*links on
*links off
*blacklist so‘z
*unblacklist so‘z
*blacklists

🎛 FILTER
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
*welcome on
*welcome off
*goodbye on
*goodbye off
*setrules matn
*admins

👑 ADMIN
*ruxsat
*ruxsatsiz
*admin
*unadmin

🎁 VERITAS GIFT
*give 25
*give 50
*give 100

⭐ BOT BALANSI
*topup 100
*topup 500
*topup 1000
"""
# =========================================================
# WELCOME / GOODBYE
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
        if member.id == context.bot.id:
            continue

        await message.reply_text(
            f"👋 Xush kelibsiz, {get_name(member)}!"
        )


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

    await message.reply_text(
        f"👋 {get_name(member)} guruhni tark etdi."
    )


# =========================================================
# TELEGRAM STARS — TOPUP
# =========================================================

async def topup_stars(
    message,
    user,
    context,
    amount
):
    if user.id != OWNER_ID:
        await message.reply_text(
            "⛔ Bu buyruq faqat Veritas egasi uchun."
        )
        return

    if amount < 1:
        await message.reply_text(
            "⚠️ Stars miqdori noto‘g‘ri."
        )
        return

    try:
        await context.bot.send_invoice(
            chat_id=user.id,
            title="Veritas Stars balansi",
            description=(
                f"VeritasBot balansiga "
                f"{amount} ⭐ Stars"
            ),
            payload=f"veritas_topup_{amount}",
            currency="XTR",
            prices=[
                LabeledPrice(
                    label="Veritas Stars",
                    amount=amount
                )
            ],
            provider_token=""
        )

        # Guruhdan buyruq berilsa invoice shaxsiy chatga boradi.
        if message.chat.id != user.id:
            await message.reply_text(
                "⭐ To‘lov oynasi bot bilan "
                "shaxsiy chatga yuborildi."
            )

    except Exception as error:
        print(
            "TOPUP ERROR:",
            repr(error)
        )

        await message.reply_text(
            "❌ Stars to‘lovini ochib bo‘lmadi.\n"
            "Avval botga shaxsiy chatda /start bosing "
            "va qayta urinib ko‘ring."
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

    if not query.invoice_payload.startswith(
        "veritas_topup_"
    ):
        await query.answer(
            ok=False,
            error_message="Noto‘g‘ri Veritas to‘lovi."
        )
        return

    await query.answer(ok=True)


# =========================================================
# MUVAFFAQIYATLI STARS TO‘LOVI
# =========================================================

async def successful_payment(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    message = update.effective_message

    if not message:
        return

    payment = message.successful_payment

    if not payment:
        return

    if not payment.invoice_payload.startswith(
        "veritas_topup_"
    ):
        return

    amount = payment.total_amount

    await message.reply_text(
        "✅ Veritas Stars to‘lovi qabul qilindi!\n"
        f"⭐ {amount} Stars bot balansiga tushdi."
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
    if user.id != OWNER_ID:
        await message.reply_text(
            "⛔ Bu buyruq faqat Veritas egasi uchun."
        )
        return

    target = reply_target(message)

    if not target:
        await message.reply_text(
            "🎁 Gift bermoqchi bo‘lgan odamning "
            "xabariga reply qiling.\n\n"
            "Masalan:\n"
            "*give 25"
        )
        return

    if target.is_bot:
        await message.reply_text(
            "⚠️ Botga Gift berib bo‘lmaydi."
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
                f"⚠️ Hozir Telegramda aynan "
                f"{amount} Starslik Gift mavjud emas."
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

    except AttributeError:
        await message.reply_text(
            "❌ Bot kutubxonasi Telegram Gifts "
            "funksiyasini qo‘llamayapti."
        )

    except Exception as error:
        print(
            "GIFT ERROR:",
            repr(error)
        )

        error_text = str(error).lower()

        if (
            "balance_too_low" in error_text
            or "balance too low" in error_text
        ):
            await message.reply_text(
                "⭐ VeritasBot Stars balansida "
                "mablag‘ yetarli emas.\n"
                "Avval *topup miqdor orqali "
                "balansni to‘ldiring."
            )
        else:
            await message.reply_text(
                "❌ Gift yuborilmadi. "
                "Telegram Gift mavjudligi yoki "
                "bot balansini tekshiring."
                # =========================================================
# ASOSIY MESSAGE HANDLER
# =========================================================

async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat

    if not message or not user or not chat:
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
                f"🆔 Sizning ID: {user.id}"
            )
            return

        # TOPUP private chatda ham ishlaydi
        if lower.startswith("*topup"):
            parts = text.split()

            if len(parts) != 2:
                await message.reply_text(
                    "⭐ Foydalanish:\n"
                    "*topup 100"
                )
                return

            try:
                amount = int(parts[1])
            except ValueError:
                await message.reply_text(
                    "⚠️ Stars miqdorini raqam bilan yozing.\n"
                    "Masalan: *topup 100"
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
    # FAQAT GURUH / SUPERGROUP
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
        else:
            await message.reply_text(
                f"🆔 Sizning ID: {user.id}\n"
                f"💬 Chat ID: {chat.id}"
            )

        return

    # =====================================================
    # TOPUP
    # =====================================================

    if lower.startswith("*topup"):
        parts = text.split()

        if len(parts) != 2:
            await message.reply_text(
                "⭐ Foydalanish:\n"
                "*topup 100"
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
    # GIFT
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
                "⚠️ Gift miqdorini raqam bilan yozing."
            )
            return

        if amount not in (
            25,
            50,
            100,
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

    # =====================================================
    # VERITAS ICHKI ADMIN BERISH
    # =====================================================

    if lower == "*ruxsat":
        if user.id != OWNER_ID:
            await message.reply_text(
                "⛔ Bu buyruq faqat Veritas egasi uchun."
            )
            return

        target = reply_target(message)

        if not target:
            await message.reply_text(
                "⚠️ Foydalanuvchi xabariga reply qiling."
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
            f"✅ {get_name(target)} ga "
            "Veritas admin ruxsati berildi."
        )
        return

    # =====================================================
    # VERITAS ICHKI ADMINNI O‘CHIRISH
    # =====================================================

    if lower == "*ruxsatsiz":
        if user.id != OWNER_ID:
            await message.reply_text(
                "⛔ Bu buyruq faqat Veritas egasi uchun."
            )
            return

        target = reply_target(message)

        if not target:
            await message.reply_text(
                "⚠️ Foydalanuvchi xabariga reply qiling."
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
            f"🚫 {get_name(target)} ning "
            "Veritas admin ruxsati olib tashlandi."
        )
        return

    # =====================================================
    # ADMINLAR
    # =====================================================

    if lower == "*admins":
        try:
            telegram_admins = (
                await context.bot.get_chat_administrators(
                    chat.id
                )
            )

            lines = [
                "👑 TELEGRAM ADMINLARI\n"
            ]

            for admin in telegram_admins:
                lines.append(
                    f"• {get_name(admin.user)}"
                )

            cursor.execute(
                """
                SELECT user_id
                FROM allowed_users
                ORDER BY user_id
                """
            )

            internal = cursor.fetchall()

            if internal:
                lines.append(
                    "\n🛡 VERITAS RUXSATLARI"
                )

                for row in internal:
                    lines.append(
                        f"• ID: {row[0]}"
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
        if not await telegram_admin_required(
            message,
            user,
            context
        ):
            return

        target = reply_target(message)

        if not target:
            await message.reply_text(
                "⚠️ Admin qilinadigan odamning "
                "xabariga reply qiling."
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
                f"👑 {get_name(target)} admin qilindi."
            )

        except Exception as error:
            print(
                "ADMIN ERROR:",
                repr(error)
            )

            await message.reply_text(
                "❌ Admin qilib bo‘lmadi. "
                "Botning admin huquqlarini tekshiring."
            )

        return

    # =====================================================
    # TELEGRAM ADMINNI OLISH
    # =====================================================

    if lower == "*unadmin":
        if not await telegram_admin_required(
            message,
            user,
            context
        ):
            return

        target = reply_target(message)

        if not target:
            await message.reply_text(
                "⚠️ Adminligi olinadigan odamning "
                "xabariga reply qiling."
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
                f"✅ {get_name(target)} "
                "adminlikdan olindi."
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
            message,
            user,
            context
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
                chat_id,
                user_id,
                warns
            )
            VALUES (?, ?, 1)
            ON CONFLICT(chat_id, user_id)
            DO UPDATE SET warns = warns + 1
            """,
            (
                chat.id,
                target.id,
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
                target.id,
            )
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
                    (
                        chat.id,
                        target.id,
                    )
                )

                db.commit()

                await message.reply_text(
                    f"⛔ {get_name(target)} "
                    "3/3 warn oldi va ban qilindi."
                )

            except Exception as error:
                print(
                    "AUTO BAN ERROR:",
                    repr(error)
                )

                await message.reply_text(
                    f"⚠️ {get_name(target)}: "
                    f"{warns}/3 warn.\n"
                    "Ban qilishda xato yuz berdi."
                )

            return

        await message.reply_text(
            f"⚠️ {get_name(target)}: "
            f"{warns}/3 warn."
        )
        return

    # =====================================================
    # UNWARN
    # =====================================================

    if lower == "*unwarn":
        if not await admin_required(
            message,
            user,
            context
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
            SELECT warns
            FROM warnings
            WHERE chat_id = ?
              AND user_id = ?
            """,
            (
                chat.id,
                target.id,
            )
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
                (
                    chat.id,
                    target.id,
                )
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
                    target.id,
                )
            )

        db.commit()

        await message.reply_text(
            f"✅ {get_name(target)}: "
            f"{warns}/3 warn."
        )
        return
    )
        # =====================================================
    # CLEAR WARNS
    # =====================================================

    if lower == "*clearwarns":
        if not await admin_required(message, user, context):
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
            f"✅ {get_name(target)} ning barcha warnlari tozalandi."
        )
        return

    # =====================================================
    # WARNS
    # =====================================================

    if lower == "*warns":
        target = reply_target(message) or user

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
    # MUTE
    # =====================================================

    if lower == "*mute":
        if not await admin_required(message, user, context):
            return

        target = reply_target(message)

        if not target:
            await message.reply_text(
                "⚠️ Mute qilinadigan odamning xabariga reply qiling."
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
            print("MUTE ERROR:", repr(error))

            await message.reply_text(
                "❌ Mute qilib bo‘lmadi. "
                "Botning admin huquqlarini tekshiring."
            )

        return

    # =====================================================
    # UNMUTE
    # =====================================================

    if lower == "*unmute":
        if not await admin_required(message, user, context):
            return

        target = reply_target(message)

        if not target:
            await message.reply_text(
                "⚠️ Unmute qilinadigan odamning xabariga reply qiling."
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
            print("UNMUTE ERROR:", repr(error))

            await message.reply_text(
                "❌ Unmute qilib bo‘lmadi."
            )

        return

    # =====================================================
    # KICK
    # =====================================================

    if lower == "*kick":
        if not await admin_required(message, user, context):
            return

        target = reply_target(message)

        if not target:
            await message.reply_text(
                "⚠️ Kick qilinadigan odamning xabariga reply qiling."
            )
            return

        if target.id == OWNER_ID:
            await message.reply_text(
                "⛔ Veritas egasini kick qilib bo‘lmaydi."
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
            print("KICK ERROR:", repr(error))

            await message.reply_text(
                "❌ Foydalanuvchini chiqarib bo‘lmadi."
            )

        return

    # =====================================================
    # BAN
    # =====================================================

    if lower == "*ban":
        if not await admin_required(message, user, context):
            return

        target = reply_target(message)

        if not target:
            await message.reply_text(
                "⚠️ Ban qilinadigan odamning xabariga reply qiling."
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
            print("BAN ERROR:", repr(error))

            await message.reply_text(
                "❌ Ban qilib bo‘lmadi."
            )

        return

    # =====================================================
    # UNBAN
    # Reply yoki ID orqali
    # =====================================================

    if lower.startswith("*unban"):
        if not await admin_required(message, user, context):
            return

        target = reply_target(message)
        target_id = target.id if target else None

        if target_id is None:
            parts = text.split()

            if len(parts) != 2:
                await message.reply_text(
                    "⚠️ Ban qilingan odamga reply qiling "
                    "yoki ID yozing:\n"
                    "*unban 123456789"
                )
                return

            try:
                target_id = int(parts[1])
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

            if target:
                name = get_name(target)
            else:
                name = str(target_id)

            await message.reply_text(
                f"✅ {name} ban holatidan chiqarildi."
            )

        except Exception as error:
            print("UNBAN ERROR:", repr(error))

            await message.reply_text(
                "❌ Unban qilib bo‘lmadi."
            )

        return

    # =====================================================
    # DELETE
    # =====================================================

    if lower == "*del":
        if not await admin_required(message, user, context):
            return

        if not message.reply_to_message:
            await message.reply_text(
                "⚠️ O‘chiriladigan xabarga reply qilib *del yozing."
            )
            return

        try:
            await context.bot.delete_message(
                chat_id=chat.id,
                message_id=message.reply_to_message.message_id
            )

            try:
                await context.bot.delete_message(
                    chat_id=chat.id,
                    message_id=message.message_id
                )
            except Exception:
                pass

        except Exception as error:
            print("DELETE ERROR:", repr(error))

            await message.reply_text(
                "❌ Xabarni o‘chirib bo‘lmadi."
            )

        return

    # =====================================================
    # LINKS ON / OFF
    # =====================================================

    if lower in ("*links on", "*links off"):
        if not await admin_required(message, user, context):
            return

        enabled = 1 if lower == "*links on" else 0

        cursor.execute(
            """
            UPDATE settings
            SET link_block = ?
            WHERE chat_id = ?
            """,
            (enabled, chat.id)
        )
        db.commit()

        if enabled:
            await message.reply_text(
                "🔗 Link himoyasi yoqildi."
            )
        else:
            await message.reply_text(
                "🔗 Link himoyasi o‘chirildi."
            )

        return

    # =====================================================
    # BLACKLIST
    # =====================================================

    if lower.startswith("*blacklist "):
        if not await admin_required(message, user, context):
            return

        word = text[len("*blacklist "):].strip().lower()

        if not word:
            await message.reply_text(
                "⚠️ So‘z kiriting."
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
            f"🚫 Qora ro‘yxatga qo‘shildi: {word}"
        )
        return

    # =====================================================
    # UNBLACKLIST
    # =====================================================

    if lower.startswith("*unblacklist "):
        if not await admin_required(message, user, context):
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
            f"✅ Qora ro‘yxatdan olib tashlandi: {word}"
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
                "📋 Qora ro‘yxat bo‘sh."
            )
            return

        words = "\n".join(
            f"• {row[0]}"
            for row in rows
        )

        await message.reply_text(
            "🚫 QORA RO‘YXAT\n\n" + words
        )
        return
            # =====================================================
    # FILTER QO‘SHISH
    # =====================================================

    if lower.startswith("*filter "):
        if not await admin_required(message, user, context):
            return

        content = text[len("*filter "):].strip()

        if not content:
            await message.reply_text(
                "⚠️ Foydalanish:\n"
                "*filter salom Assalomu alaykum"
            )
            return

        # Reply qilingan media bo‘lsa media filter
        if message.reply_to_message:
            media_type, file_id, caption = media_from_message(
                message.reply_to_message
            )

            if media_type != "text":
                keyword = content.lower()

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
                        "",
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
        parts = content.split(maxsplit=1)

        if len(parts) != 2:
            await message.reply_text(
                "⚠️ Matn filter uchun:\n"
                "*filter kalit javob\n\n"
                "Media uchun esa media xabariga reply qilib:\n"
                "*filter kalit"
            )
            return

        keyword = parts[0].lower()
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
            f"✅ Filter saqlandi: {keyword}"
        )
        return

    # =====================================================
    # FILTERLAR RO‘YXATI
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
                "📋 Filterlar yo‘q."
            )
            return

        lines = ["🎛 FILTERLAR\n"]

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
    # BITTA FILTERNI O‘CHIRISH
    # =====================================================

    if lower.startswith("*stop "):
        if not await admin_required(message, user, context):
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
    # BARCHA FILTERLARNI O‘CHIRISH
    # =====================================================

    if lower == "*stopall":
        if not await admin_required(message, user, context):
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
    # RULES O‘RNATISH
    # =====================================================

    if lower.startswith("*setrules"):
        if not await admin_required(message, user, context):
            return

        rules = text[len("*setrules"):].strip()

        if not rules:
            await message.reply_text(
                "⚠️ Foydalanish:\n"
                "*setrules Guruh qoidalari..."
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
        rules = row[0] if row else ""

        if not rules:
            await message.reply_text(
                "📜 Guruh qoidalari hali yozilmagan."
            )
        else:
            await message.reply_text(
                "📜 GURUH QOIDALARI\n\n" + rules
            )

        return

    # =====================================================
    # NOTE SAQLASH
    # =====================================================

    if lower.startswith("*save "):
        if not await admin_required(message, user, context):
            return

        content = text[len("*save "):].strip()
        parts = content.split(maxsplit=1)

        if len(parts) != 2:
            await message.reply_text(
                "⚠️ Foydalanish:\n"
                "*save nom matn"
            )
            return

        name = parts[0].lower()
        note_text = parts[1]

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
                note_text
            )
        )

        db.commit()

        await message.reply_text(
            f"📝 Note saqlandi: {name}"
        )
        return

    # =====================================================
    # NOTE OLISH
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
            (
                chat.id,
                name
            )
        )

        row = cursor.fetchone()

        if not row:
            await message.reply_text(
                "❌ Bunday note topilmadi."
            )
            return

        await message.reply_text(
            row[0]
        )
        return

    # =====================================================
    # NOTES RO‘YXATI
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
                "📝 Notes bo‘sh."
            )
            return

        notes_text = "\n".join(
            f"• {row[0]}"
            for row in rows
        )

        await message.reply_text(
            "📝 NOTES\n\n" + notes_text
        )
        return

    # =====================================================
    # NOTE O‘CHIRISH
    # =====================================================

    if lower.startswith("*clear "):
        if not await admin_required(message, user, context):
            return

        name = text[len("*clear "):].strip().lower()

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

    # =====================================================
    # WELCOME ON / OFF
    # =====================================================

    if lower in (
        "*welcome on",
        "*welcome off",
    ):
        if not await admin_required(message, user, context):
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

        if enabled:
            await message.reply_text(
                "👋 Welcome yoqildi."
            )
        else:
            await message.reply_text(
                "👋 Welcome o‘chirildi."
            )

        return

    # =====================================================
    # GOODBYE ON / OFF
    # =====================================================

    if lower in (
        "*goodbye on",
        "*goodbye off",
    ):
        if not await admin_required(message, user, context):
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

        if enabled:
            await message.reply_text(
                "👋 Goodbye yoqildi."
            )
        else:
            await message.reply_text(
                "👋 Goodbye o‘chirildi."
            )

        return
            # =====================================================
    # AKTIV
    # =====================================================

    if lower.startswith("*aktiv"):
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

        limit = max(1, min(limit, 50))

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
                "📊 Hozircha faollik ma’lumoti yo‘q."
            )
            return

        lines = ["🏆 ENG FAOL A’ZOLAR\n"]

        for index, row in enumerate(rows, 1):
            name, username, messages = row

            if username:
                display = f"@{username}"
            else:
                display = name

            lines.append(
                f"{index}. {display} — {messages}"
            )

        await message.reply_text(
            "\n".join(lines)
        )
        return

    # =====================================================
    # MEN
    # =====================================================

    if lower == "*men":
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

        cursor.execute(
            """
            SELECT COUNT(*)
            FROM activity
            WHERE chat_id = ?
              AND messages > ?
            """,
            (chat.id, messages)
        )

        rank_row = cursor.fetchone()
        rank = (rank_row[0] if rank_row else 0) + 1

        await message.reply_text(
            f"👤 {get_name(user)}\n"
            f"💬 Xabarlar: {messages}\n"
            f"🏆 O‘rin: {rank}"
        )
        return

    # =====================================================
    # NOMALUM * BUYRUQ
    # =====================================================

    if text.startswith("*"):
        return

    # =====================================================
    # LINK HIMOYASI
    # =====================================================

    if not await is_admin(
        chat,
        user.id,
        context
    ):
        cursor.execute(
            """
            SELECT link_block
            FROM settings
            WHERE chat_id = ?
            """,
            (chat.id,)
        )

        row = cursor.fetchone()
        link_block = row[0] if row else 0

        if link_block and contains_link(text):
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
    # BLACKLIST HIMOYASI
    # =====================================================

    if text and not await is_admin(
        chat,
        user.id,
        context
    ):
        cursor.execute(
            """
            SELECT word
            FROM blacklist
            WHERE chat_id = ?
            """,
            (chat.id,)
        )

        words = cursor.fetchall()
        text_lower = text.lower()

        for row in words:
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
                        "BLACKLIST DELETE ERROR:",
                        repr(error)
                    )

                return

    # =====================================================
    # AVTOMATIK FILTER JAVOBI
    # =====================================================

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
                text.lower()
            )
        )

        row = cursor.fetchone()

        if row:
            response, media_type, file_id, caption = row

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
                    "FILTER SEND ERROR:",
                    repr(error)
                )

            return

    # =====================================================
    # FAOLLIKNI HISOBLASH
    # =====================================================

    if text:
        name = get_name(user)
        username = user.username or ""

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


# =========================================================
# MAIN
# =========================================================

def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN topilmadi! "
            "Railway Variables bo‘limini tekshiring."
        )

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # Welcome
    app.add_handler(
        MessageHandler(
            filters.StatusUpdate.NEW_CHAT_MEMBERS,
            welcome_new_member
        ),
        group=0
    )

    # Goodbye
    app.add_handler(
        MessageHandler(
            filters.StatusUpdate.LEFT_CHAT_MEMBER,
            goodbye_member
        ),
        group=0
    )

    # Telegram Stars pre-checkout
    app.add_handler(
        PreCheckoutQueryHandler(
            precheckout_callback
        ),
        group=0
    )

    # Muvaffaqiyatli Stars to‘lovi
    app.add_handler(
        MessageHandler(
            filters.SUCCESSFUL_PAYMENT,
            successful_payment
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
        "Veritas Gift + Stars v5 ishga tushdi."
    )

    app.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()
