# VERITAS BOT v8 â€” Vasatiya Library build
# Python 3.11+ | python-telegram-bot[job-queue]>=22.5,<23
#
# ENV:
# BOT_TOKEN=...
# SUPER_OWNER_IDS=5859289233,7056675943
# DB_PATH=veritas_v7.sqlite3
#
# NOTE:
# *stars now opens Telegram's official Stars Gift section.
# Recipient/amount are displayed by Veritas, but must be selected/confirmed in Telegram.

import os, re, sqlite3, time, random, logging, json, asyncio, base64, io
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    from telethon import TelegramClient
    from telethon.sessions import StringSession
except ImportError:
    TelegramClient = StringSession = None

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, ChatPermissions,
    LabeledPrice
)
from telegram.constants import ChatMemberStatus
from telegram.error import TelegramError, BadRequest, RetryAfter, ChatMigrated, Forbidden
from telegram import CallbackQuery
from telegram.ext import (
    Application, ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler,
    PreCheckoutQueryHandler, ExtBot, filters, ApplicationHandlerStop, ChatMemberHandler
)

TOKEN = os.getenv ( "BOT_TOKEN", "" ) .strip ( )
DB_PATH = os.getenv ( "DB_PATH", "veritas_v7.sqlite3")
SUPER_OWNERS = {int ( x) for x in os.getenv ( "SUPER_OWNER_IDS","" ) .split ( ",") if x.strip (  ) .isdigit (  ) }
VERSION = "9.1.1"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6-luna").strip() or "gpt-5.6-luna"
REBUS_IMAGE_MODEL = os.getenv("REBUS_IMAGE_MODEL", "gpt-image-2").strip() or "gpt-image-2"
TG_API_ID = int(os.getenv("TG_API_ID", "0") or 0)
TG_API_HASH = os.getenv("TG_API_HASH", "").strip()
TG_SESSION = os.getenv("TG_SESSION", "").strip()
TG_STORAGE_CHAT_ID = int(os.getenv("TG_STORAGE_CHAT_ID", "0") or 0)
DEMO_DAYS = 7
WEEK_PRICE = 100
PREMIUM = {3:1000, 6:1500, 12:2500}
TOPUPS = (25,50,100,250,500,1000,2500)
AI_PRIVATE_PRICE = 10
AI_PRIVATE_DAYS = 30
AI_GROUP_PLANS = {30:100}
AI_RATE_CACHE = {}
TRANSLATION_SEMAPHORE = asyncio.Semaphore(2)
FLOOD_CACHE = {}
STATE = {}
URL_RE = re.compile ( r" ( https?://|www\.|t\.me/|telegram\.me/|@\w+ ) ", re.I)

logging.basicConfig ( level=logging.INFO)
log = logging.getLogger ( "veritas-v8")

# =========================================================
# V9.1.1 â€” XAVFSIZ CALLBACK JAVOBI
# Telegram har bir tugma bosilishiga faqat BITTA answerCallbackQuery qabul qiladi.
# Avval handlerlar boshida bo'sh q.answer() chaqirilib, keyin yana
# q.answer("...", show_alert=True) chaqirilardi -> 400 BadRequest, alert ko'rinmasdi
# va undan keyingi kod (keyingi test savoli, profil yangilanishi va h.k.) ishlamasdi.
# Endi: 1) har bir query faqat bir marta javoblanadi, takroriy chaqiruv xato bermaydi;
#       2) handler boshidagi bo'sh javob "kechiktiriladi" â€” agar handler qisqa vaqt
#          ichida o'zi matnli/alert javob bersa, aynan o'sha javob foydalanuvchiga chiqadi.
# =========================================================
_CQ_ANSWERED = {}
_CQ_TASKS = set()
_orig_cq_answer = CallbackQuery.answer

async def _safe_cq_answer(self, *args, **kwargs):
    qid = self.id
    t = time.time()
    if len(_CQ_ANSWERED) > 5000:
        for k, v in list(_CQ_ANSWERED.items()):
            if t - v > 120:
                _CQ_ANSWERED.pop(k, None)
    text = kwargs.get("text", args[0] if args else None)
    show_alert = kwargs.get("show_alert", args[1] if len(args) > 1 else None)
    if qid in _CQ_ANSWERED:
        # Allaqachon javob berilgan: muhim alert yo'qolmasin â€” shaxsiy chatda xabar sifatida chiqaramiz.
        if text and show_alert and self.message and self.message.chat and self.message.chat.type == "private":
            try:
                await self.get_bot().send_message(self.message.chat.id, text)
            except Exception:
                log.debug("fallback alert message failed", exc_info=True)
        return False
    _CQ_ANSWERED[qid] = t
    try:
        return await _orig_cq_answer(self, *args, **kwargs)
    except BadRequest as exc:
        if "query" in str(exc).lower():
            log.warning("callback answer ignored (%s): %s", qid, exc)
            return False
        raise

CallbackQuery.answer = _safe_cq_answer

def cq_defer(q, delay=1.5):
    """Bo'sh javobni kechiktirib yuboradi; handler o'zi javob bersa, bu hech narsa qilmaydi."""
    async def _later():
        try:
            await asyncio.sleep(delay)
            await q.answer()
        except Exception:
            log.debug("deferred callback answer failed", exc_info=True)
    task = asyncio.create_task(_later())
    _CQ_TASKS.add(task)
    task.add_done_callback(_CQ_TASKS.discard)

def now (  ) : return int ( time.time (  ) )
def iso ( ts=None ) : return datetime.fromtimestamp ( ts or now (  ) , timezone.utc ) .isoformat ( )
def db (  ) :
    c=sqlite3.connect ( DB_PATH, timeout=30)
    c.row_factory=sqlite3.Row
    return c
def execute ( sql,args= (  )  ) :
    with db ( ) as c: return c.execute ( sql,args)
def one ( sql,args= (  )  ) :
    with db ( ) as c: return c.execute ( sql,args ) .fetchone ( )
def all_ ( sql,args= (  )  ) :
    with db ( ) as c: return c.execute ( sql,args ) .fetchall ( )

def init_db (  ) :
    schema = """
    PRAGMA journal_mode=WAL;
    CREATE TABLE IF NOT EXISTS users(
      user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, lang TEXT DEFAULT 'uz',
      wallet INTEGER DEFAULT 0, created_at INTEGER, blocked INTEGER DEFAULT 0 ) ;
    CREATE TABLE IF NOT EXISTS groups(
      chat_id INTEGER PRIMARY KEY, title TEXT, owner_id INTEGER, created_at INTEGER,
      demo_until INTEGER, paid_until INTEGER DEFAULT 0, free INTEGER DEFAULT 0,
      links INTEGER DEFAULT 1, antiflood INTEGER DEFAULT 1, flood_limit INTEGER DEFAULT 5,
      reports INTEGER DEFAULT 1, welcome INTEGER DEFAULT 1, goodbye INTEGER DEFAULT 1,
      rules TEXT DEFAULT '', locks TEXT DEFAULT '{}' ) ;
    CREATE TABLE IF NOT EXISTS members(
      chat_id INTEGER,user_id INTEGER,xp INTEGER DEFAULT 0,messages INTEGER DEFAULT 0,
      daily INTEGER DEFAULT 0,weekly INTEGER DEFAULT 0,last_day TEXT,last_week TEXT,
      title TEXT DEFAULT '', PRIMARY KEY ( chat_id,user_id )  ) ;
    CREATE TABLE IF NOT EXISTS vadmins ( chat_id INTEGER,user_id INTEGER,PRIMARY KEY ( chat_id,user_id )  ) ;
    CREATE TABLE IF NOT EXISTS group_message_history(
      chat_id INTEGER NOT NULL,user_id INTEGER NOT NULL,message_id INTEGER NOT NULL,
      created_at INTEGER NOT NULL,PRIMARY KEY(chat_id,message_id) ) ;
    CREATE INDEX IF NOT EXISTS idx_group_message_history_user
      ON group_message_history(chat_id,user_id,message_id);
    CREATE TABLE IF NOT EXISTS approved ( chat_id INTEGER,user_id INTEGER,PRIMARY KEY ( chat_id,user_id )  ) ;
    CREATE TABLE IF NOT EXISTS warns ( chat_id INTEGER,user_id INTEGER,count INTEGER DEFAULT 0,PRIMARY KEY ( chat_id,user_id )  ) ;
    -- V8 Moderation 2.0: Rose-uslubidagi kengaytirilgan moderatsiya.
    CREATE TABLE IF NOT EXISTS moderation_settings(
      chat_id INTEGER PRIMARY KEY, warn_limit INTEGER DEFAULT 3, warn_action TEXT DEFAULT 'ban',
      warn_mute_seconds INTEGER DEFAULT 3600, clean_service INTEGER DEFAULT 0,
      antirepeat INTEGER DEFAULT 1, repeat_limit INTEGER DEFAULT 4, repeat_window INTEGER DEFAULT 30 ) ;
    CREATE TABLE IF NOT EXISTS moderation_log(
      id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL, actor_id INTEGER DEFAULT 0,
      target_id INTEGER DEFAULT 0, action TEXT NOT NULL, reason TEXT DEFAULT '',
      duration INTEGER DEFAULT 0, created_at INTEGER NOT NULL ) ;
    CREATE INDEX IF NOT EXISTS idx_moderation_log_chat ON moderation_log(chat_id,created_at);
    CREATE TABLE IF NOT EXISTS warn_records(
      id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
      actor_id INTEGER DEFAULT 0, reason TEXT DEFAULT '', created_at INTEGER NOT NULL ) ;
    CREATE TABLE IF NOT EXISTS blacklist ( chat_id INTEGER,word TEXT,PRIMARY KEY ( chat_id,word )  ) ;
    CREATE TABLE IF NOT EXISTS notes ( chat_id INTEGER,name TEXT,text TEXT,PRIMARY KEY ( chat_id,name )  ) ;
    CREATE TABLE IF NOT EXISTS filters_ ( chat_id INTEGER,key TEXT,response TEXT,PRIMARY KEY ( chat_id,key )  ) ;
    CREATE TABLE IF NOT EXISTS tx(
      id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,kind TEXT,amount INTEGER,
      target_id INTEGER,ref TEXT,created_at INTEGER,meta TEXT DEFAULT '{}' ) ;
    CREATE TABLE IF NOT EXISTS payments(
      charge_id TEXT PRIMARY KEY,user_id INTEGER,amount INTEGER,payload TEXT,created_at INTEGER,refunded INTEGER DEFAULT 0 ) ;
    CREATE TABLE IF NOT EXISTS subscriptions(
      chat_id INTEGER PRIMARY KEY, payer_id INTEGER, paid_until INTEGER DEFAULT 0 ) ;
    CREATE TABLE IF NOT EXISTS ai_user_subscriptions(
      user_id INTEGER PRIMARY KEY, paid_until INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0 ) ;
    CREATE TABLE IF NOT EXISTS ai_group_subscriptions(
      chat_id INTEGER PRIMARY KEY, payer_id INTEGER DEFAULT 0, paid_until INTEGER DEFAULT 0,
      source TEXT DEFAULT 'paid', updated_at INTEGER DEFAULT 0 ) ;
    CREATE TABLE IF NOT EXISTS ai_user_trials(
      user_id INTEGER PRIMARY KEY, claimed_at INTEGER NOT NULL ) ;
    CREATE TABLE IF NOT EXISTS ai_group_trials(
      chat_id INTEGER PRIMARY KEY, claimed_at INTEGER NOT NULL, claimed_by INTEGER DEFAULT 0 ) ;
    CREATE TABLE IF NOT EXISTS profile_likes(
      target_user_id INTEGER NOT NULL,
      voter_user_id INTEGER NOT NULL,
      created_at INTEGER NOT NULL,
      PRIMARY KEY(target_user_id,voter_user_id) ) ;
    CREATE INDEX IF NOT EXISTS idx_profile_likes_target ON profile_likes(target_user_id);
    CREATE TABLE IF NOT EXISTS profile_dislikes(
      target_user_id INTEGER NOT NULL,
      voter_user_id INTEGER NOT NULL,
      created_at INTEGER NOT NULL,
      PRIMARY KEY(target_user_id,voter_user_id) ) ;
    CREATE INDEX IF NOT EXISTS idx_profile_dislikes_target ON profile_dislikes(target_user_id);
    CREATE TABLE IF NOT EXISTS ai_book_translations(
      id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, book_id INTEGER NOT NULL,
      target_lang TEXT NOT NULL, status TEXT DEFAULT 'running', started_at INTEGER NOT NULL,
      completed_at INTEGER DEFAULT 0 ) ;
    CREATE INDEX IF NOT EXISTS idx_ai_book_translation_user_done ON ai_book_translations(user_id,completed_at);
    -- V8: AI rasmli rebus. Kanalga post qilinadi, javob bogâ€˜langan guruhda tekshiriladi.
    CREATE TABLE IF NOT EXISTS rebus_channels(
      owner_id INTEGER PRIMARY KEY, channel_id INTEGER NOT NULL, channel_title TEXT DEFAULT '',
      answer_group_id INTEGER NOT NULL, answer_group_title TEXT DEFAULT '', updated_at INTEGER NOT NULL ) ;
    CREATE TABLE IF NOT EXISTS rebuses(
      id INTEGER PRIMARY KEY AUTOINCREMENT, creator_id INTEGER NOT NULL, channel_id INTEGER NOT NULL,
      answer_group_id INTEGER NOT NULL, answer TEXT NOT NULL, answer_norm TEXT NOT NULL,
      hint TEXT DEFAULT '', channel_message_id INTEGER DEFAULT 0, status TEXT DEFAULT 'active',
      winner_id INTEGER DEFAULT 0, created_at INTEGER NOT NULL, solved_at INTEGER DEFAULT 0 ) ;
    CREATE INDEX IF NOT EXISTS idx_rebus_active_group ON rebuses(answer_group_id,status,id);
    CREATE TABLE IF NOT EXISTS rebus_sessions(
      id INTEGER PRIMARY KEY AUTOINCREMENT, creator_id INTEGER NOT NULL,
      group_id INTEGER NOT NULL, target_chat_id INTEGER NOT NULL,
      total INTEGER NOT NULL, current_no INTEGER DEFAULT 0,
      status TEXT DEFAULT 'active', created_at INTEGER NOT NULL ) ;
    CREATE TABLE IF NOT EXISTS rebus_session_items(
      session_id INTEGER NOT NULL, item_no INTEGER NOT NULL, answer TEXT NOT NULL,
      rebus_id INTEGER DEFAULT 0, status TEXT DEFAULT 'waiting',
      PRIMARY KEY(session_id,item_no) ) ;
    CREATE TABLE IF NOT EXISTS rebus_session_scores(
      session_id INTEGER NOT NULL, user_id INTEGER NOT NULL, first_name TEXT DEFAULT '',
      wins INTEGER DEFAULT 0, PRIMARY KEY(session_id,user_id) ) ;
    CREATE INDEX IF NOT EXISTS idx_rebus_session_group ON rebus_sessions(group_id,status,id);
    CREATE TABLE IF NOT EXISTS rebus_group_channels(
      group_id INTEGER PRIMARY KEY, channel_id INTEGER NOT NULL,
      channel_title TEXT DEFAULT '', updated_at INTEGER NOT NULL ) ;
    -- V8: global Super Adminlar. Super Ega tayinlaydi/oladi.
    CREATE TABLE IF NOT EXISTS super_admins(
      user_id INTEGER PRIMARY KEY, added_by INTEGER NOT NULL, created_at INTEGER NOT NULL ) ;
    CREATE TABLE IF NOT EXISTS giveaways(
      id INTEGER PRIMARY KEY AUTOINCREMENT,chat_id INTEGER,creator_id INTEGER,kind TEXT,
      prize TEXT,winners INTEGER,end_at INTEGER,status TEXT DEFAULT 'open',created_at INTEGER ) ;
    CREATE TABLE IF NOT EXISTS giveaway_entries(
      giveaway_id INTEGER,user_id INTEGER,PRIMARY KEY ( giveaway_id,user_id )  ) ;
    CREATE TABLE IF NOT EXISTS books(
      id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT,author TEXT,tags TEXT,file_id TEXT,added_by INTEGER,created_at INTEGER ) ;

    -- V8: Vasatiya kutubxonasi. Eski books jadvali oâ€˜zgartirilmaydi.
    CREATE TABLE IF NOT EXISTS library_books(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      title TEXT NOT NULL, author TEXT DEFAULT '', lang TEXT DEFAULT 'uz',
      description TEXT DEFAULT '', cover_file_id TEXT DEFAULT '',
      pdf_file_id TEXT DEFAULT '', pdf_unique_id TEXT DEFAULT '',
      audio_file_id TEXT DEFAULT '', audio_unique_id TEXT DEFAULT '',
      added_by INTEGER NOT NULL, status TEXT DEFAULT 'approved',
      views INTEGER DEFAULT 0, downloads INTEGER DEFAULT 0, created_at INTEGER NOT NULL ) ;
    CREATE UNIQUE INDEX IF NOT EXISTS idx_library_pdf_unique
      ON library_books ( pdf_unique_id) WHERE pdf_unique_id<>'';
    CREATE INDEX IF NOT EXISTS idx_library_title_author ON library_books ( title,author ) ;
    CREATE INDEX IF NOT EXISTS idx_library_lang ON library_books ( lang,status ) ;
    CREATE TABLE IF NOT EXISTS library_categories(
      id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT UNIQUE COLLATE NOCASE ) ;
    CREATE TABLE IF NOT EXISTS library_book_categories(
      book_id INTEGER,category_id INTEGER,PRIMARY KEY ( book_id,category_id )  ) ;
    CREATE TABLE IF NOT EXISTS library_favorites(
      user_id INTEGER,book_id INTEGER,created_at INTEGER,PRIMARY KEY ( user_id,book_id )  ) ;
    CREATE TABLE IF NOT EXISTS library_admins(
      user_id INTEGER PRIMARY KEY,added_by INTEGER,created_at INTEGER ) ;
    CREATE TABLE IF NOT EXISTS library_progress(
      user_id INTEGER,book_id INTEGER,kind TEXT DEFAULT 'pdf',position TEXT DEFAULT '',updated_at INTEGER,
      PRIMARY KEY ( user_id,book_id,kind )  ) ;

    -- V8: Sahih Hadislar moduli
    CREATE TABLE IF NOT EXISTS hadith_admins(
      user_id INTEGER PRIMARY KEY,added_by INTEGER,created_at INTEGER ) ;
    CREATE TABLE IF NOT EXISTS hadiths(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      collection TEXT NOT NULL, number INTEGER NOT NULL,
      arabic TEXT DEFAULT '', translation TEXT NOT NULL, explanation TEXT DEFAULT '', source TEXT DEFAULT '',
      added_by INTEGER NOT NULL,status TEXT DEFAULT 'approved',created_at INTEGER NOT NULL,
      UNIQUE ( collection,number )  ) ;
    CREATE INDEX IF NOT EXISTS idx_hadith_collection_number ON hadiths ( collection,number ) ;

    CREATE TABLE IF NOT EXISTS audit(
      id INTEGER PRIMARY KEY AUTOINCREMENT,actor_id INTEGER,chat_id INTEGER,action TEXT,detail TEXT,created_at INTEGER ) ;
    """
    with db ( ) as c:
        c.executescript ( schema)
        # Universal library file support. Old PDF columns remain compatible.
        cols={r[1] for r in c.execute("PRAGMA table_info(library_books)").fetchall()}
        for col,decl in (
            ("book_file_id","TEXT DEFAULT ''"),
            ("book_unique_id","TEXT DEFAULT ''"),
            ("book_file_name","TEXT DEFAULT ''"),
            ("book_format","TEXT DEFAULT ''"),
            ("book_file_size","INTEGER DEFAULT 0")
        ):
            if col not in cols:
                c.execute(f"ALTER TABLE library_books ADD COLUMN {col} {decl}")
        c.execute("CREATE INDEX IF NOT EXISTS idx_library_book_unique ON library_books(book_unique_id)")
        # Existing PDF records automatically become universal file records too.
        c.execute("""UPDATE library_books
                     SET book_file_id=pdf_file_id,
                         book_unique_id=pdf_unique_id,
                         book_format=CASE WHEN COALESCE(book_format,'')='' THEN 'pdf' ELSE book_format END
                     WHERE COALESCE(book_file_id,'')='' AND COALESCE(pdf_file_id,'')<>''""")

def ensure_user ( u ) :
    if not u: return
    with db ( ) as c:
        c.execute ( """INSERT INTO users ( user_id,username,first_name,created_at) VALUES ( ?,?,?,?)
        ON CONFLICT ( user_id) DO UPDATE SET username=excluded.username,first_name=excluded.first_name""",
        (u.id,u.username or "",u.first_name or "",now (  )  ) )
def ensure_group ( chat ) :
    if not chat or chat.type not in ("group","supergroup" ) : return
    with db ( ) as c:
        c.execute ( """INSERT INTO groups ( chat_id,title,created_at,demo_until) VALUES ( ?,?,?,?)
        ON CONFLICT ( chat_id) DO UPDATE SET title=excluded.title""",
        (chat.id,chat.title or "",now (  ) ,now (  ) +DEMO_DAYS*86400 ) )
def audit ( actor,chat,action,detail="" ) :
    execute ( "INSERT INTO audit ( actor_id,chat_id,action,detail,created_at) VALUES ( ?,?,?,?,? ) ",
            (actor,chat,action,detail,now (  )  ) )

def wallet ( uid ) :
    r=one ( "SELECT wallet FROM users WHERE user_id=?", ( uid, )  ) ; return int ( r["wallet"]) if r else 0
def wallet_change ( uid,delta,kind,target=None,ref=None,meta=None ) :
    with db ( ) as c:
        r=c.execute ( "SELECT wallet FROM users WHERE user_id=?", ( uid, )  ) .fetchone ( )
        bal=int ( r["wallet"]) if r else 0
        if delta<0 and bal+delta<0: return False
        c.execute ( "UPDATE users SET wallet=wallet+? WHERE user_id=?", ( delta,uid ) )
        c.execute ( "INSERT INTO tx ( user_id,kind,amount,target_id,ref,created_at,meta) VALUES ( ?,?,?,?,?,?,? ) ",
                  (uid,kind,delta,target,ref,now (  ) ,json.dumps ( meta or {},ensure_ascii=False )  ) )
    return True

def is_super_admin ( uid ) :
    return bool ( one ( "SELECT 1 FROM super_admins WHERE user_id=?", ( uid, )  ) )

def is_super ( uid ) :
    return uid in SUPER_OWNERS or is_super_admin ( uid )

def super_role ( uid ) :
    if uid in SUPER_OWNERS: return "ðŸ‘‘ Super Ega"
    if is_super_admin ( uid ): return "ðŸ›¡ Super Admin"
    return "Aâ€™zo"

def ai_actor_context ( u ) :
    if not u: return ""
    # Asosiy yaratuvchilar Telegram ID orqali aniq taniladi.
    creator_names={5859289233:"Sakranum",7056675943:"Vasatiya"}
    if u.id in creator_names:
        return f"\n\nTIZIM KONTEKSTI: Hozir yozayotgan foydalanuvchi {creator_names[u.id]} (Telegram ID {u.id}). U Veritasni yaratgan Super Egalardan biri."
    if is_super_admin ( u.id ):
        return f"\n\nTIZIM KONTEKSTI: Hozir yozayotgan foydalanuvchi Telegram ID {u.id}; u Veritas Super Admini. Super Admin bot boshqaruvida Super Ega vakolatlariga ega, lekin Super Admin tayinlash/olish huquqi Super Egalarda qoladi."
    return f"\n\nTIZIM KONTEKSTI: Hozir yozayotgan foydalanuvchining Telegram IDsi {u.id}."

async def is_tg_admin ( bot,chat_id,uid ) :
    try:
        m=await bot.get_chat_member ( chat_id,uid)
        return m.status in (ChatMemberStatus.OWNER,ChatMemberStatus.ADMINISTRATOR)
    except TelegramError: return False
async def can_manage ( bot,chat_id,uid ) :
    if is_super ( uid ): return True
    if await is_tg_admin ( bot,chat_id,uid ) : return True
    return bool ( one ( "SELECT 1 FROM vadmins WHERE chat_id=? AND user_id=?", ( chat_id,uid )  ) )
async def protected ( bot,chat_id,uid ) :
    return is_super ( uid ) or await is_tg_admin ( bot,chat_id,uid)
def replied ( update ) : return update.effective_message.reply_to_message if update.effective_message else None

def level ( xp ) : return max ( 1, int (  ( xp/20 ) **0.5 ) +1)
def title_for ( uid,custom="" ) :
    if uid in SUPER_OWNERS: return "ðŸ‘‘ Super Ega"
    if is_super_admin ( uid ): return "ðŸ›¡ Super Admin"
    return custom or "Aâ€™zo"


# =========================================================
# VERITAS V9 â€” START
# V8 MUZLATILGAN. V9 faqat v9_* jadvallar va v9:/root: callbacklaridan foydalanadi.
# =========================================================
def v9_init_db():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS v9_profiles(user_id INTEGER PRIMARY KEY,institution_type TEXT DEFAULT '',role TEXT DEFAULT '',created_at INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS v9_groups(id INTEGER PRIMARY KEY AUTOINCREMENT,teacher_id INTEGER NOT NULL,institution_type TEXT NOT NULL,title TEXT NOT NULL,subject TEXT DEFAULT '',join_code TEXT NOT NULL UNIQUE,is_active INTEGER DEFAULT 1,created_at INTEGER NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_v9_groups_teacher ON v9_groups(teacher_id);
        CREATE TABLE IF NOT EXISTS v9_group_members(group_id INTEGER NOT NULL,user_id INTEGER NOT NULL,joined_at INTEGER NOT NULL,is_active INTEGER DEFAULT 1,PRIMARY KEY(group_id,user_id));
        CREATE INDEX IF NOT EXISTS idx_v9_members_user ON v9_group_members(user_id);
        CREATE TABLE IF NOT EXISTS v9_lessons(id INTEGER PRIMARY KEY AUTOINCREMENT,group_id INTEGER NOT NULL,teacher_id INTEGER NOT NULL,title TEXT NOT NULL,material_type TEXT DEFAULT 'text',material_file_id TEXT DEFAULT '',material_text TEXT DEFAULT '',ai_mode TEXT DEFAULT 'material_only',status TEXT DEFAULT 'draft',created_at INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS v9_lesson_progress(lesson_id INTEGER NOT NULL,user_id INTEGER NOT NULL,stage TEXT DEFAULT 'new',score INTEGER DEFAULT 0,updated_at INTEGER NOT NULL,PRIMARY KEY(lesson_id,user_id));
        CREATE TABLE IF NOT EXISTS v9_points(group_id INTEGER NOT NULL,user_id INTEGER NOT NULL,points INTEGER DEFAULT 0,updated_at INTEGER NOT NULL,PRIMARY KEY(group_id,user_id));
        CREATE TABLE IF NOT EXISTS v9_test_results(id INTEGER PRIMARY KEY AUTOINCREMENT,lesson_id INTEGER NOT NULL,group_id INTEGER NOT NULL,user_id INTEGER NOT NULL,score INTEGER DEFAULT 0,max_score INTEGER DEFAULT 100,correct_count INTEGER DEFAULT 0,total_count INTEGER DEFAULT 0,details TEXT DEFAULT '',created_at INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS v9_lesson_materials(
          id INTEGER PRIMARY KEY AUTOINCREMENT,lesson_id INTEGER NOT NULL,kind TEXT NOT NULL,
          file_id TEXT DEFAULT '',file_name TEXT DEFAULT '',mime_type TEXT DEFAULT '',
          extracted_text TEXT DEFAULT '',created_at INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS v9_tests(
          id INTEGER PRIMARY KEY AUTOINCREMENT,lesson_id INTEGER NOT NULL,questions_json TEXT NOT NULL,
          created_at INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS v9_teacher_plans(
          id INTEGER PRIMARY KEY AUTOINCREMENT,teacher_id INTEGER NOT NULL,title TEXT NOT NULL,
          class_name TEXT DEFAULT '',subject TEXT DEFAULT '',quarter TEXT DEFAULT '',weekly_hours REAL DEFAULT 0,
          planned_hours REAL DEFAULT 0,is_active INTEGER DEFAULT 1,created_at INTEGER NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_v9_teacher_plans_teacher ON v9_teacher_plans(teacher_id,is_active,id);
        CREATE TABLE IF NOT EXISTS v9_plan_lessons(
          id INTEGER PRIMARY KEY AUTOINCREMENT,plan_id INTEGER NOT NULL,lesson_no INTEGER NOT NULL,
          topic TEXT NOT NULL,visual_aids TEXT DEFAULT '',textbook_tasks TEXT DEFAULT '',
          hours REAL DEFAULT 1,calendar_date TEXT DEFAULT '',status TEXT DEFAULT 'planned',created_at INTEGER NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_v9_plan_lessons_plan ON v9_plan_lessons(plan_id,lesson_no,id);
        """)

def root_choice_markup():
    return InlineKeyboardMarkup([[InlineKeyboardButton("ðŸ›¡ Veritas",callback_data="root:v8")],[InlineKeyboardButton("ðŸŽ“ Oâ€˜quv â€¢ Talaba",callback_data="root:v9")]])

def v9_entry_markup():
    return InlineKeyboardMarkup([[InlineKeyboardButton("ðŸ« Maktab",callback_data="v9:inst:school")],[InlineKeyboardButton("ðŸ› Institut",callback_data="v9:inst:institute"),InlineKeyboardButton("ðŸŽ“ Universitet",callback_data="v9:inst:university")],[InlineKeyboardButton("â¬…ï¸ Veritas tanlash",callback_data="root:choose")]])

def v9_role_markup(inst):
    return InlineKeyboardMarkup([[InlineKeyboardButton("ðŸ‘¨â€ðŸ« Ustoz",callback_data=f"v9:role:{inst}:teacher"),InlineKeyboardButton("ðŸ‘¨â€ðŸŽ“ Oâ€˜quvchi / Talaba",callback_data=f"v9:role:{inst}:student")],[InlineKeyboardButton("â¬…ï¸ Orqaga",callback_data="v9:home")]])

def v9_teacher_markup():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("ðŸ“… Ish rejalarim",callback_data="v9:plan:list"),InlineKeyboardButton("âž• Yangi ish reja",callback_data="v9:plan:new")],
        [InlineKeyboardButton("ðŸ‘¨â€ðŸ« Oâ€˜qituvchilar",callback_data="v9:teachers")],
        [InlineKeyboardButton("âž• Yangi guruh",callback_data="v9:teacher:newgroup")],
        [InlineKeyboardButton("ðŸ‘¥ Guruhlarim",callback_data="v9:teacher:groups")],
        [InlineKeyboardButton("ðŸ“Š Natijalar / Jurnal",callback_data="v9:teacher:journal")],
        [InlineKeyboardButton("â¬…ï¸ Veritas tanlash",callback_data="root:choose")]])

def v9_student_markup():
    return InlineKeyboardMarkup([[InlineKeyboardButton("âž• Guruhga qoâ€˜shilish",callback_data="v9:student:join")],[InlineKeyboardButton("ðŸ“š Guruhlarim / Darslarim",callback_data="v9:student:groups")],[InlineKeyboardButton("ðŸ† Ballarim",callback_data="v9:student:points")],[InlineKeyboardButton("â¬…ï¸ Veritas tanlash",callback_data="root:choose")]])

async def v9_start_selector(update,ctx):
    ensure_user(update.effective_user)
    await update.effective_message.reply_text(
        "ðŸª¶ VERITAS\n\nAsosiy menyu pastda doim turadi.",
        reply_markup=veritas_global_keyboard()
    )
    await update.effective_message.reply_text(
        "Qaysi boâ€˜limga kirishni xohlaysiz?",
        reply_markup=root_choice_markup()
    )

async def v9_callback(update,ctx):
    q=update.callback_query
    if not q or not q.data:return
    d=q.data; u=q.from_user
    cq_defer(q); ensure_user(u)
    if d=="root:choose": return await q.edit_message_text("ðŸª¶ VERITAS\n\nQaysi boâ€˜limga kirishni xohlaysiz?",reply_markup=root_choice_markup())
    if d=="root:v8": return await q.edit_message_text("ðŸ›¡ VERITAS\n\nAsosiy boâ€˜lim:",reply_markup=main_menu_markup(u.id))
    if d in ("root:v9","v9:home"): return await q.edit_message_text("ðŸŽ“ VERITAS V9 â€” Oâ€˜QUV â€¢ TALABA\n\nTaâ€™lim turini tanlang:",reply_markup=v9_entry_markup())
    if d.startswith("v9:inst:"):
        inst=d.rsplit(":",1)[1]
        if inst in {"school","institute","university"}: return await q.edit_message_text("Sizning rolingiz:",reply_markup=v9_role_markup(inst))
    if d.startswith("v9:role:"):
        _,_,inst,role=d.split(":",3)
        if inst not in {"school","institute","university"} or role not in {"teacher","student"}: return
        with db() as c:c.execute("INSERT INTO v9_profiles(user_id,institution_type,role,created_at) VALUES(?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET institution_type=excluded.institution_type,role=excluded.role",(u.id,inst,role,now()))
        if role=="teacher": return await q.edit_message_text("ðŸ‘¨â€ðŸ« USTOZ KABINETI\n\nGuruh yarating, dars materiallarini bering va natijalarni kuzating.",reply_markup=v9_teacher_markup())
        return await q.edit_message_text("ðŸ‘¨â€ðŸŽ“ Oâ€˜QUVCHI / TALABA KABINETI\n\nGuruhga qoâ€˜shiling, AI bilan dars oâ€˜rganing va ball toâ€˜plang.",reply_markup=v9_student_markup())
    if d=="v9:teacher:home": return await q.edit_message_text("ðŸ‘¨â€ðŸ« USTOZ KABINETI",reply_markup=v9_teacher_markup())
    if d=="v9:student:home": return await q.edit_message_text("ðŸ‘¨â€ðŸŽ“ Oâ€˜QUVCHI / TALABA KABINETI",reply_markup=v9_student_markup())
    if d=="v9:teacher:newgroup":
        STATE[u.id]={"mode":"v9_new_group_title"}
        return await q.edit_message_text("âž• YANGI GURUH\n\nGuruh nomini yozing.\nMasalan: Matematika â€” 1-kurs",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("â¬…ï¸ Kabinet",callback_data="v9:teacher:home")]]))
    if d=="v9:student:join":
        STATE[u.id]={"mode":"v9_join_group"}
        return await q.edit_message_text("ðŸ”‘ GURUHGA QOâ€˜SHILISH\n\nUstoz bergan guruh kodini yuboring.",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("â¬…ï¸ Kabinet",callback_data="v9:student:home")]]))
    if d=="v9:teacher:groups":
        rows=all_("SELECT id,title FROM v9_groups WHERE teacher_id=? AND is_active=1 ORDER BY id DESC",(u.id,))
        if not rows:return await q.edit_message_text("ðŸ‘¥ Hali guruh yaratmagansiz.",reply_markup=v9_teacher_markup())
        kb=[[InlineKeyboardButton("ðŸ“š "+r["title"][:45],callback_data=f"v9:group:{r['id']}")] for r in rows[:30]]+[[InlineKeyboardButton("â¬…ï¸ Kabinet",callback_data="v9:teacher:home")]]
        return await q.edit_message_text("ðŸ‘¥ GURUHLARIM",reply_markup=InlineKeyboardMarkup(kb))
    if d=="v9:student:groups":
        rows=all_("SELECT g.id,g.title FROM v9_groups g JOIN v9_group_members m ON m.group_id=g.id WHERE m.user_id=? AND m.is_active=1 AND g.is_active=1 ORDER BY g.id DESC",(u.id,))
        if not rows:return await q.edit_message_text("ðŸ“š Siz hali guruhga qoâ€˜shilmagansiz.",reply_markup=v9_student_markup())
        kb=[[InlineKeyboardButton("ðŸ“š "+r["title"][:45],callback_data=f"v9:group:{r['id']}")] for r in rows[:30]]+[[InlineKeyboardButton("â¬…ï¸ Kabinet",callback_data="v9:student:home")]]
        return await q.edit_message_text("ðŸ“š GURUHLARIM / DARSLARIM",reply_markup=InlineKeyboardMarkup(kb))
    if d=="v9:student:points":
        rows=all_("SELECT g.title,p.points FROM v9_points p JOIN v9_groups g ON g.id=p.group_id WHERE p.user_id=? ORDER BY p.points DESC",(u.id,))
        body="\n".join(f"ðŸ† {r['title']}: {r['points']} ball" for r in rows) or "Hozircha ball yoâ€˜q."
        return await q.edit_message_text("ðŸ† BALLARIM\n\n"+body,reply_markup=v9_student_markup())
    if d.startswith("v9:group:"):
        gid=int(d.rsplit(":",1)[1]); g=one("SELECT * FROM v9_groups WHERE id=? AND is_active=1",(gid,))
        if not g:return await q.answer("Guruh topilmadi.",show_alert=True)
        teacher=int(g["teacher_id"])==u.id; member=one("SELECT 1 FROM v9_group_members WHERE group_id=? AND user_id=? AND is_active=1",(gid,u.id))
        if not teacher and not member:return await q.answer("Bu guruhga kirish huquqingiz yoâ€˜q.",show_alert=True)
        count=one("SELECT COUNT(*) n FROM v9_group_members WHERE group_id=? AND is_active=1",(gid,))["n"]
        kb=InlineKeyboardMarkup([[InlineKeyboardButton("âž• Yangi dars",callback_data=f"v9:lesson:new:{gid}")],[InlineKeyboardButton("ðŸ“š Darslar",callback_data=f"v9:lessons:{gid}"),InlineKeyboardButton("ðŸ“Š Natijalar",callback_data=f"v9:results:{gid}")],[InlineKeyboardButton("â¬…ï¸ Guruhlarim",callback_data="v9:teacher:groups")]]) if teacher else InlineKeyboardMarkup([[InlineKeyboardButton("ðŸ“š Darslar",callback_data=f"v9:lessons:{gid}")],[InlineKeyboardButton("ðŸ† Guruh reytingi",callback_data=f"v9:ranking:{gid}")],[InlineKeyboardButton("â¬…ï¸ Guruhlarim",callback_data="v9:student:groups")]])
        return await q.edit_message_text(f"ðŸ“š {g['title']}\nðŸ“– Fan: {g['subject'] or 'Kiritilmagan'}\nðŸ‘¥ Talabalar: {count}\nðŸ”‘ Guruh kodi: {g['join_code']}",reply_markup=kb)

    if d.startswith("v9:lesson:new:"):
        gid=int(d.rsplit(":",1)[1])
        g=one("SELECT * FROM v9_groups WHERE id=? AND teacher_id=? AND is_active=1",(gid,u.id))
        if not g:return await q.answer("Bu guruh sizga tegishli emas.",show_alert=True)
        STATE[u.id]={"mode":"v9_lesson_title","group_id":gid}
        return await q.edit_message_text(
            f"âž• YANGI DARS\n\nðŸ“š Guruh: {g['title']}\n\n1/3 â€” Dars nomini yozing.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("âŒ Bekor qilish",callback_data=f"v9:group:{gid}")]]))

    if d.startswith("v9:lessonmode:"):
        mode_choice=d.rsplit(":",1)[1]
        st=STATE.get(u.id) or {}
        if st.get("mode")!="v9_lesson_mode" or mode_choice not in {"material_only","ai_plus"}:
            return await q.answer("Dars yaratish sessiyasi topilmadi.",show_alert=True)
        gid=int(st["group_id"]); g=one("SELECT * FROM v9_groups WHERE id=? AND teacher_id=?",(gid,u.id))
        if not g:return await q.answer("Ruxsat yoâ€˜q.",show_alert=True)
        mat=st["material"]; title=st["title"]
        with db() as c:
            lid=c.execute("""INSERT INTO v9_lessons(group_id,teacher_id,title,material_type,material_file_id,material_text,ai_mode,status,created_at)
                             VALUES(?,?,?,?,?,?,?,'published',?)""",
                          (gid,u.id,title,mat["kind"],mat["file_id"],mat["text"],mode_choice,now())).lastrowid
            c.execute("""INSERT INTO v9_lesson_materials(lesson_id,kind,file_id,file_name,mime_type,extracted_text,created_at)
                         VALUES(?,?,?,?,?,?,?)""",(lid,mat["kind"],mat["file_id"],mat["file_name"],mat["mime"],mat["text"],now()))
        STATE.pop(u.id,None)
        await q.edit_message_text(
            f"âœ… DARS Eâ€™LON QILINDI\n\nðŸ“– {title}\nðŸ“š {g['title']}\n"
            +("ðŸ”’ AI faqat darslikdan javob beradi." if mode_choice=="material_only" else "ðŸ§  AI darslikni asos qilib qoâ€˜shimcha tushuntiradi."),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("ðŸ“– Darsni ochish",callback_data=f"v9:lesson:view:{lid}")],[InlineKeyboardButton("â¬…ï¸ Guruh",callback_data=f"v9:group:{gid}")]]))
        return
    if d.startswith("v9:lessons:"):
        gid=int(d.rsplit(":",1)[1])
        g=one("SELECT * FROM v9_groups WHERE id=? AND is_active=1",(gid,))
        if not g:return await q.answer("Guruh topilmadi.",show_alert=True)
        teacher=int(g["teacher_id"])==u.id
        member=one("SELECT 1 FROM v9_group_members WHERE group_id=? AND user_id=? AND is_active=1",(gid,u.id))
        if not teacher and not member:return await q.answer("Ruxsat yoâ€˜q.",show_alert=True)
        rows=all_("SELECT id,title,status FROM v9_lessons WHERE group_id=? AND status='published' ORDER BY id DESC",(gid,))
        if not rows:
            back=f"v9:group:{gid}"
            return await q.edit_message_text("ðŸ“š Hozircha eâ€™lon qilingan dars yoâ€˜q.",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("â¬…ï¸ Guruh",callback_data=back)]]))
        kb=[[InlineKeyboardButton(("ðŸ‘¨â€ðŸ« " if teacher else "ðŸ“– ")+r["title"][:45],callback_data=f"v9:lesson:view:{r['id']}")] for r in rows[:40]]
        kb.append([InlineKeyboardButton("â¬…ï¸ Guruh",callback_data=f"v9:group:{gid}")])
        return await q.edit_message_text("ðŸ“š DARSLAR",reply_markup=InlineKeyboardMarkup(kb))

    if d.startswith("v9:lesson:view:"):
        lid=int(d.rsplit(":",1)[1])
        l=one("""SELECT l.*,g.title group_title,g.teacher_id group_teacher
                 FROM v9_lessons l JOIN v9_groups g ON g.id=l.group_id
                 WHERE l.id=? AND l.status='published'""",(lid,))
        if not l:return await q.answer("Dars topilmadi.",show_alert=True)
        teacher=int(l["group_teacher"])==u.id
        member=one("SELECT 1 FROM v9_group_members WHERE group_id=? AND user_id=? AND is_active=1",(l["group_id"],u.id))
        if not teacher and not member:return await q.answer("Ruxsat yoâ€˜q.",show_alert=True)
        mode="ðŸ”’ Faqat darslikdan" if l["ai_mode"]=="material_only" else "ðŸ§  Darslik + AI tushuntirishi"
        if teacher:
            kb=InlineKeyboardMarkup([
              [InlineKeyboardButton("ðŸ“„ Material",callback_data=f"v9:lesson:material:{lid}"),
               InlineKeyboardButton("ðŸ“ Test yaratish",callback_data=f"v9:test:make:{lid}")],
              [InlineKeyboardButton("ðŸ“Š Natijalar",callback_data=f"v9:lesson:results:{lid}")],
              [InlineKeyboardButton("â¬…ï¸ Darslar",callback_data=f"v9:lessons:{l['group_id']}")]])
        else:
            kb=InlineKeyboardMarkup([
              [InlineKeyboardButton("ðŸ¤– AI bilan oâ€˜rganish",callback_data=f"v9:learn:{lid}")],
              [InlineKeyboardButton("ðŸ“ Yakuniy test",callback_data=f"v9:test:start:{lid}")],
              [InlineKeyboardButton("â¬…ï¸ Darslar",callback_data=f"v9:lessons:{l['group_id']}")]])
        return await q.edit_message_text(
            f"ðŸ“– {l['title']}\nðŸ“š {l['group_title']}\n{mode}",
            reply_markup=kb)

    if d.startswith("v9:lesson:material:"):
        lid=int(d.rsplit(":",1)[1])
        l=one("SELECT * FROM v9_lessons WHERE id=? AND teacher_id=?",(lid,u.id))
        if not l:return await q.answer("Ruxsat yoâ€˜q.",show_alert=True)
        mats=all_("SELECT kind,file_name,extracted_text FROM v9_lesson_materials WHERE lesson_id=? ORDER BY id",(lid,))
        lines=[]
        for i,m in enumerate(mats,1):
            nm=m["file_name"] or ("Yozma material" if m["kind"]=="text" else m["kind"])
            lines.append(f"{i}. {nm} â€” {len(m['extracted_text'] or '')} belgi")
        return await q.edit_message_text("ðŸ“„ DARS MATERIALLARI\n\n"+("\n".join(lines) or "Material yoâ€˜q."),reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("â¬…ï¸ Dars",callback_data=f"v9:lesson:view:{lid}")]]))

    if d.startswith("v9:learn:"):
        lid=int(d.rsplit(":",1)[1])
        l=one("SELECT * FROM v9_lessons WHERE id=? AND status='published'",(lid,))
        if not l:return await q.answer("Dars topilmadi.",show_alert=True)
        member=one("SELECT 1 FROM v9_group_members WHERE group_id=? AND user_id=? AND is_active=1",(l["group_id"],u.id))
        if not member:return await q.answer("Siz bu guruh talabasi emassiz.",show_alert=True)
        material=v9_lesson_context(lid)
        if not material:return await q.answer("Dars materiali boâ€˜sh.",show_alert=True)
        STATE[u.id]={"mode":"v9_ai_lesson","lesson_id":lid,"group_id":l["group_id"]}
        with db() as c:
            c.execute("""INSERT INTO v9_lesson_progress(lesson_id,user_id,stage,score,updated_at)
                         VALUES(?,?,'learning',0,?)
                         ON CONFLICT(lesson_id,user_id) DO UPDATE SET stage='learning',updated_at=excluded.updated_at""",(lid,u.id,now()))
        intro=await v9_ai_teach(l,material,"Darsni boshlang. Avval mavzuni sodda va qiziqarli qilib tushuntiring, keyin menga bitta tekshiruvchi savol bering.")
        await q.edit_message_text(f"ðŸ¤– AI USTOZ â€” {l['title']}\n\n{intro[:3500]}",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("ðŸ“ Testga oâ€˜tish",callback_data=f"v9:test:start:{lid}")],[InlineKeyboardButton("â¬…ï¸ Dars",callback_data=f"v9:lesson:view:{lid}")]]))
        return

    if d.startswith("v9:test:make:"):
        lid=int(d.rsplit(":",1)[1])
        l=one("SELECT * FROM v9_lessons WHERE id=? AND teacher_id=?",(lid,u.id))
        if not l:return await q.answer("Ruxsat yoâ€˜q.",show_alert=True)
        await q.edit_message_text("ðŸ§  AI test tayyorlamoqda...")
        qs=await v9_make_test(lid,10)
        if not qs:return await q.edit_message_text("âš ï¸ Test yaratilmadi.",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("â¬…ï¸ Dars",callback_data=f"v9:lesson:view:{lid}")]]))
        with db() as c:c.execute("INSERT INTO v9_tests(lesson_id,questions_json,created_at) VALUES(?,?,?)",(lid,json.dumps(qs,ensure_ascii=False),now()))
        return await q.edit_message_text(f"âœ… {len(qs)} ta savolli test tayyorlandi.\n\nTalabalar endi dars ichidan testni topshira oladi.",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("â¬…ï¸ Dars",callback_data=f"v9:lesson:view:{lid}")]]))

    if d.startswith("v9:test:start:"):
        lid=int(d.rsplit(":",1)[1])
        l=one("SELECT * FROM v9_lessons WHERE id=? AND status='published'",(lid,))
        if not l:return await q.answer("Dars topilmadi.",show_alert=True)
        member=one("SELECT 1 FROM v9_group_members WHERE group_id=? AND user_id=? AND is_active=1",(l["group_id"],u.id))
        if not member:return await q.answer("Siz bu guruh talabasi emassiz.",show_alert=True)
        tr=one("SELECT * FROM v9_tests WHERE lesson_id=? ORDER BY id DESC LIMIT 1",(lid,))
        if not tr:
            qs=await v9_make_test(lid,10)
            if not qs:return await q.answer("Test hali tayyor emas.",show_alert=True)
            with db() as c:
                tid=c.execute("INSERT INTO v9_tests(lesson_id,questions_json,created_at) VALUES(?,?,?)",(lid,json.dumps(qs,ensure_ascii=False),now())).lastrowid
        else:
            tid=tr["id"]; qs=json.loads(tr["questions_json"])
        STATE[u.id]={"mode":"v9_test","lesson_id":lid,"group_id":l["group_id"],"test_id":tid,"questions":qs,"index":0,"correct":0}
        return await v9_send_test_question(q.message,u.id)

    if d.startswith("v9:ans:"):
        parts=d.split(":")
        if len(parts)!=4:return
        lid=int(parts[2]); chosen=int(parts[3])
        st=STATE.get(u.id) or {}
        if st.get("mode")!="v9_test" or int(st.get("lesson_id",0))!=lid:return await q.answer("Bu test sessiyasi tugagan.",show_alert=True)
        qs=st["questions"]; idx=int(st["index"])
        if idx>=len(qs):return
        correct=int(qs[idx]["answer"])
        if chosen==correct: st["correct"]=int(st.get("correct",0))+1
        st["index"]=idx+1; STATE[u.id]=st
        await q.answer("âœ… Toâ€˜gâ€˜ri!" if chosen==correct else f"âŒ Toâ€˜gâ€˜ri javob: {correct+1}")
        if st["index"]>=len(qs):
            total=len(qs); corr=int(st["correct"]); score=round(corr*100/total) if total else 0
            with db() as c:
                c.execute("""INSERT INTO v9_test_results(lesson_id,group_id,user_id,score,max_score,correct_count,total_count,details,created_at)
                             VALUES(?,?,?,?,100,?,?,?,?)""",(lid,st["group_id"],u.id,score,corr,total,json.dumps({"test_id":st["test_id"]}),now()))
                c.execute("""INSERT INTO v9_points(group_id,user_id,points,updated_at) VALUES(?,?,?,?)
                             ON CONFLICT(group_id,user_id) DO UPDATE SET points=points+excluded.points,updated_at=excluded.updated_at""",(st["group_id"],u.id,score,now()))
                c.execute("""INSERT INTO v9_lesson_progress(lesson_id,user_id,stage,score,updated_at)
                             VALUES(?,?,'completed',?,?)
                             ON CONFLICT(lesson_id,user_id) DO UPDATE SET stage='completed',score=excluded.score,updated_at=excluded.updated_at""",(lid,u.id,score,now()))
            STATE.pop(u.id,None)
            return await q.edit_message_text(f"ðŸ TEST TUGADI\n\nâœ… Toâ€˜gâ€˜ri: {corr}/{total}\nðŸŽ¯ Natija: {score}/100\nðŸ† Guruh balliga: +{score}",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("ðŸ“– Darsga qaytish",callback_data=f"v9:lesson:view:{lid}")]]))
        return await v9_send_test_question(q.message,u.id,edit=True)

    if d.startswith("v9:lesson:results:"):
        lid=int(d.rsplit(":",1)[1])
        l=one("SELECT * FROM v9_lessons WHERE id=? AND teacher_id=?",(lid,u.id))
        if not l:return await q.answer("Ruxsat yoâ€˜q.",show_alert=True)
        rows=all_("""SELECT r.user_id,MAX(r.score) score,MAX(r.correct_count) correct_count,MAX(r.total_count) total_count,
                    COALESCE(us.first_name,'') first_name,COALESCE(us.username,'') username
                    FROM v9_test_results r LEFT JOIN users us ON us.user_id=r.user_id
                    WHERE r.lesson_id=? GROUP BY r.user_id ORDER BY score DESC""",(lid,))
        body="\n".join(f"{i}. {r['first_name'] or ('@'+r['username'] if r['username'] else r['user_id'])} â€” {r['score']}/100" for i,r in enumerate(rows,1)) or "Hali test topshirgan talaba yoâ€˜q."
        return await q.edit_message_text(f"ðŸ“Š {l['title']} â€” NATIJALAR\n\n{body[:3500]}",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("â¬…ï¸ Dars",callback_data=f"v9:lesson:view:{lid}")]]))

    if d.startswith("v9:results:"):
        gid=int(d.rsplit(":",1)[1])
        g=one("SELECT * FROM v9_groups WHERE id=? AND teacher_id=?",(gid,u.id))
        if not g:return await q.answer("Ruxsat yoâ€˜q.",show_alert=True)
        rows=all_("""SELECT m.user_id,COALESCE(us.first_name,'') first_name,COALESCE(us.username,'') username,
                    COALESCE(p.points,0) points,COALESCE(AVG(r.score),0) avg_score
                    FROM v9_group_members m LEFT JOIN users us ON us.user_id=m.user_id
                    LEFT JOIN v9_points p ON p.group_id=m.group_id AND p.user_id=m.user_id
                    LEFT JOIN v9_test_results r ON r.group_id=m.group_id AND r.user_id=m.user_id
                    WHERE m.group_id=? AND m.is_active=1 GROUP BY m.user_id ORDER BY points DESC""",(gid,))
        body="\n".join(f"{i}. {r['first_name'] or ('@'+r['username'] if r['username'] else r['user_id'])} â€” ðŸ† {r['points']} | ðŸ“ {round(r['avg_score'])}" for i,r in enumerate(rows,1)) or "Talabalar natijasi hali yoâ€˜q."
        return await q.edit_message_text(f"ðŸ“Š {g['title']} â€” JURNAL\n\n{body[:3500]}",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("â¬…ï¸ Guruh",callback_data=f"v9:group:{gid}")]]))

    if d.startswith("v9:ranking:"):
        gid=int(d.rsplit(":",1)[1])
        rows=all_("""SELECT p.user_id,p.points,COALESCE(us.first_name,'') first_name,COALESCE(us.username,'') username
                     FROM v9_points p LEFT JOIN users us ON us.user_id=p.user_id
                     WHERE p.group_id=? ORDER BY p.points DESC LIMIT 30""",(gid,))
        body="\n".join(f"{i}. {r['first_name'] or ('@'+r['username'] if r['username'] else r['user_id'])} â€” {r['points']} ball" for i,r in enumerate(rows,1)) or "Hali ballar yoâ€˜q."
        return await q.edit_message_text("ðŸ† GURUH REYTINGI\n\n"+body,reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("â¬…ï¸ Guruh",callback_data=f"v9:group:{gid}")]]))

    # V9 Oâ€˜QITUVCHI ISH REJASI
    if d=="v9:teachers":
        rows=all_("""SELECT p.user_id,COALESCE(u.first_name,'') first_name,COALESCE(u.username,'') username,
                    (SELECT COUNT(*) FROM v9_teacher_plans tp WHERE tp.teacher_id=p.user_id AND tp.is_active=1) plans,
                    (SELECT COUNT(*) FROM v9_groups g WHERE g.teacher_id=p.user_id AND g.is_active=1) groups_n
                    FROM v9_profiles p LEFT JOIN users u ON u.user_id=p.user_id
                    WHERE p.role='teacher' ORDER BY first_name COLLATE NOCASE LIMIT 100""")
        body="\n".join(f"{i}. {r['first_name'] or ('@'+r['username'] if r['username'] else 'Ustoz')} â€” ðŸ“… {r['plans']} reja | ðŸ‘¥ {r['groups_n']} guruh" for i,r in enumerate(rows,1)) or "Hozircha ustozlar roâ€˜yxati boâ€˜sh."
        return await q.edit_message_text("ðŸ‘¨â€ðŸ« Oâ€˜QITUVCHILAR ROâ€˜YXATI\n\n"+body[:3600],reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("â¬…ï¸ Kabinet",callback_data="v9:teacher:home")]]))

    if d=="v9:plan:new":
        prof=one("SELECT role FROM v9_profiles WHERE user_id=?",(u.id,))
        if not prof or prof["role"]!="teacher":return await q.answer("Faqat ustoz uchun.",show_alert=True)
        STATE[u.id]={"mode":"v9_plan_class"}
        return await q.edit_message_text("âž• YANGI ISH REJA â€” 1/6\n\nSinf/kursni yozing.\nMasalan: 1-sinf",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("âŒ Bekor qilish",callback_data="v9:teacher:home")]]))

    if d=="v9:plan:list":
        rows=all_("SELECT * FROM v9_teacher_plans WHERE teacher_id=? AND is_active=1 ORDER BY id DESC",(u.id,))
        if not rows:return await q.edit_message_text("ðŸ“… Hali ish rejangiz yoâ€˜q.",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("âž• Yangi ish reja",callback_data="v9:plan:new")],[InlineKeyboardButton("â¬…ï¸ Kabinet",callback_data="v9:teacher:home")]]))
        kb=[[InlineKeyboardButton(f"ðŸ“˜ {r['class_name']} â€¢ {r['subject']} â€¢ {r['quarter']}"[:55],callback_data=f"v9:plan:view:{r['id']}")] for r in rows[:40]]
        kb += [[InlineKeyboardButton("âž• Yangi ish reja",callback_data="v9:plan:new")],[InlineKeyboardButton("â¬…ï¸ Kabinet",callback_data="v9:teacher:home")]]
        return await q.edit_message_text("ðŸ“… ISH REJALARIM",reply_markup=InlineKeyboardMarkup(kb))

    if d.startswith("v9:plan:view:"):
        pid=int(d.rsplit(":",1)[1]); p=one("SELECT * FROM v9_teacher_plans WHERE id=? AND teacher_id=? AND is_active=1",(pid,u.id))
        if not p:return await q.answer("Reja topilmadi.",show_alert=True)
        stat=one("SELECT COUNT(*) n,COALESCE(SUM(hours),0) total,COALESCE(SUM(CASE WHEN status='done' THEN hours ELSE 0 END),0) done FROM v9_plan_lessons WHERE plan_id=?",(pid,))
        remaining=max(float(p['planned_hours'] or stat['total'] or 0)-float(stat['done'] or 0),0)
        text=(f"ðŸ“˜ {p['title']}\nðŸ« {p['class_name']} â€¢ ðŸ“š {p['subject']}\nðŸ—“ {p['quarter']}\n"
              f"â± Haftasiga: {p['weekly_hours']:g} soat | Reja: {p['planned_hours']:g} soat\n"
              f"ðŸ“– Darslar: {stat['n']} | âœ… Oâ€˜tilgan: {float(stat['done']):g} soat | â³ Qolgan: {remaining:g} soat")
        kb=InlineKeyboardMarkup([[InlineKeyboardButton("âž• Dars qoâ€˜shish",callback_data=f"v9:plan:addlesson:{pid}")],[InlineKeyboardButton("ðŸ“‹ Darslar roâ€˜yxati",callback_data=f"v9:plan:lessons:{pid}")],[InlineKeyboardButton("â¬…ï¸ Rejalar",callback_data="v9:plan:list")]])
        return await q.edit_message_text(text,reply_markup=kb)

    if d.startswith("v9:plan:addlesson:"):
        pid=int(d.rsplit(":",1)[1]); p=one("SELECT id FROM v9_teacher_plans WHERE id=? AND teacher_id=? AND is_active=1",(pid,u.id))
        if not p:return await q.answer("Ruxsat yoâ€˜q.",show_alert=True)
        nxt=one("SELECT COALESCE(MAX(lesson_no),0)+1 n FROM v9_plan_lessons WHERE plan_id=?",(pid,))["n"]
        STATE[u.id]={"mode":"v9_plan_lesson_topic","plan_id":pid,"lesson_no":int(nxt)}
        return await q.edit_message_text(f"âž• {nxt}-DARS â€” 1/5\n\nMavzu nomini yozing.")

    if d.startswith("v9:plan:lessons:"):
        pid=int(d.rsplit(":",1)[1]); p=one("SELECT * FROM v9_teacher_plans WHERE id=? AND teacher_id=?",(pid,u.id))
        if not p:return await q.answer("Ruxsat yoâ€˜q.",show_alert=True)
        rows=all_("SELECT * FROM v9_plan_lessons WHERE plan_id=? ORDER BY lesson_no,id",(pid,))
        if not rows:return await q.edit_message_text("ðŸ“‹ Hali dars kiritilmagan.",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("âž• Dars qoâ€˜shish",callback_data=f"v9:plan:addlesson:{pid}")],[InlineKeyboardButton("â¬…ï¸ Reja",callback_data=f"v9:plan:view:{pid}")]]))
        kb=[]
        for r in rows[:50]:
            icon="âœ…" if r['status']=="done" else "â–«ï¸"
            kb.append([InlineKeyboardButton(f"{icon} {r['lesson_no']}-dars â€¢ {r['topic'][:38]}",callback_data=f"v9:plan:lesson:{r['id']}")])
        kb.append([InlineKeyboardButton("â¬…ï¸ Reja",callback_data=f"v9:plan:view:{pid}")])
        return await q.edit_message_text(f"ðŸ“‹ {p['class_name']} â€¢ {p['subject']} â€” DARSLAR",reply_markup=InlineKeyboardMarkup(kb))

    if d.startswith("v9:plan:lesson:"):
        lid=int(d.rsplit(":",1)[1]); r=one("""SELECT l.*,p.teacher_id,p.class_name,p.subject FROM v9_plan_lessons l JOIN v9_teacher_plans p ON p.id=l.plan_id WHERE l.id=? AND p.teacher_id=?""",(lid,u.id))
        if not r:return await q.answer("Ruxsat yoâ€˜q.",show_alert=True)
        text=(f"ðŸ“– {r['lesson_no']}-DARS â€” {r['topic']}\n\nðŸŽ¨ Koâ€˜rgazmali qurollar: {r['visual_aids'] or 'â€”'}\n"
              f"ðŸ“š Darslik/mashqlar: {r['textbook_tasks'] or 'â€”'}\nâ± Soat: {r['hours']:g}\nðŸ“… Taqvimiy muddat: {r['calendar_date'] or 'â€”'}\n"
              f"Holat: {'âœ… Oâ€˜tildi' if r['status']=='done' else 'â–«ï¸ Rejada'}")
        action="â†©ï¸ Oâ€˜tilmadi" if r['status']=="done" else "âœ… Oâ€˜tildi"
        return await q.edit_message_text(text,reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(action,callback_data=f"v9:plan:toggle:{lid}")],[InlineKeyboardButton("â¬…ï¸ Darslar",callback_data=f"v9:plan:lessons:{r['plan_id']}")]]))

    if d.startswith("v9:plan:toggle:"):
        lid=int(d.rsplit(":",1)[1]); r=one("""SELECT l.id,l.plan_id,l.status FROM v9_plan_lessons l JOIN v9_teacher_plans p ON p.id=l.plan_id WHERE l.id=? AND p.teacher_id=?""",(lid,u.id))
        if not r:return await q.answer("Ruxsat yoâ€˜q.",show_alert=True)
        new="planned" if r['status']=="done" else "done";execute("UPDATE v9_plan_lessons SET status=? WHERE id=?",(new,lid))
        await q.answer("Holat yangilandi.")
        # shu dars kartasini qayta ochish
        r2=one("""SELECT l.*,p.teacher_id,p.class_name,p.subject FROM v9_plan_lessons l JOIN v9_teacher_plans p ON p.id=l.plan_id WHERE l.id=?""",(lid,))
        text=(f"ðŸ“– {r2['lesson_no']}-DARS â€” {r2['topic']}\n\nðŸŽ¨ Koâ€˜rgazmali qurollar: {r2['visual_aids'] or 'â€”'}\nðŸ“š Darslik/mashqlar: {r2['textbook_tasks'] or 'â€”'}\nâ± Soat: {r2['hours']:g}\nðŸ“… Taqvimiy muddat: {r2['calendar_date'] or 'â€”'}\nHolat: {'âœ… Oâ€˜tildi' if new=='done' else 'â–«ï¸ Rejada'}")
        action="â†©ï¸ Oâ€˜tilmadi" if new=="done" else "âœ… Oâ€˜tildi"
        return await q.edit_message_text(text,reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(action,callback_data=f"v9:plan:toggle:{lid}")],[InlineKeyboardButton("â¬…ï¸ Darslar",callback_data=f"v9:plan:lessons:{r2['plan_id']}")]]))

    if d=="v9:teacher:journal":
        rows=all_("SELECT id,title FROM v9_groups WHERE teacher_id=? AND is_active=1 ORDER BY id DESC",(u.id,))
        if not rows:return await q.edit_message_text("ðŸ“Š Hali guruh yoâ€˜q.",reply_markup=v9_teacher_markup())
        kb=[[InlineKeyboardButton("ðŸ“Š "+r["title"][:45],callback_data=f"v9:results:{r['id']}")] for r in rows]
        kb.append([InlineKeyboardButton("â¬…ï¸ Kabinet",callback_data="v9:teacher:home")])
        return await q.edit_message_text("ðŸ“Š NATIJALAR / JURNAL\n\nGuruhni tanlang:",reply_markup=InlineKeyboardMarkup(kb))


def veritas_global_keyboard():
    return ReplyKeyboardMarkup(
        [[KeyboardButton("ðŸ›¡ Veritas"), KeyboardButton("ðŸŽ“ Oâ€˜quv â€¢ Talaba")]],
        resize_keyboard=True,
        is_persistent=True
    )

def v9_teacher_keyboard():
    return veritas_global_keyboard()

def v9_student_keyboard():
    return veritas_global_keyboard()

def v9_lesson_context(lid,limit=30000):
    rows=all_("SELECT extracted_text FROM v9_lesson_materials WHERE lesson_id=? ORDER BY id",(lid,))
    text="\n\n".join((r["extracted_text"] or "").strip() for r in rows if (r["extracted_text"] or "").strip())
    if not text:
        l=one("SELECT material_text FROM v9_lessons WHERE id=?",(lid,))
        text=(l["material_text"] or "") if l else ""
    return text[:limit]

def v9_extract_pdf(raw):
    if fitz is None:return ""
    doc=fitz.open(stream=raw,filetype="pdf")
    parts=[]
    for page in doc:
        parts.append(page.get_text("text"))
        if sum(len(x) for x in parts)>45000:break
    doc.close()
    return "\n".join(parts)[:45000]

async def v9_ai_teach(lesson,material,user_text):
    if not OPENAI_API_KEY:
        return "âš ï¸ OPENAI_API_KEY sozlanmagan."
    rule=("FAQAT berilgan dars materiali doirasida javob ber. Materialda javob boâ€˜lmasa, "
          "â€œBu maâ€™lumot ustoz bergan darslikda yoâ€˜qâ€ deb ayt.") if lesson["ai_mode"]=="material_only" else (
          "Asosiy manba ustoz bergan material boâ€˜lsin. Tushuntirish uchun umumiy bilimdan foydalanishingiz mumkin, "
          "lekin materialdan tashqari qoâ€˜shimchani aniq ajratib koâ€˜rsating.")
    prompt=f"""Siz Veritas V9 AI Ustozsiz.
Dars: {lesson['title']}
QOIDA: {rule}
Talabaga yoshiga mos, sodda, bosqichma-bosqich va interaktiv tarzda oâ€˜rgating.
Keraksiz uzun javob bermang.

USTOZ BERGAN MATERIAL:
{material}

TALABA:
{user_text}
"""
    try:return await asyncio.to_thread(_openai_response_sync,prompt)
    except Exception as e:
        log.exception("V9 AI teach: %s",e)
        return "âš ï¸ AI Ustoz vaqtincha javob bera olmadi."

async def v9_make_test(lid,count=10):
    l=one("SELECT * FROM v9_lessons WHERE id=?",(lid,))
    material=v9_lesson_context(lid)
    if not l or not material or not OPENAI_API_KEY:return []
    prompt=f"""Quyidagi dars materialidan aynan {count} ta 4 variantli test tuzing.
Faqat materialga tayangan savollar boâ€˜lsin. JSONdan boshqa hech narsa yozmang.
Format:
[{{"q":"savol","options":["A","B","C","D"],"answer":0}}]
answer 0..3 oraligâ€˜idagi toâ€˜gâ€˜ri variant indeksi.

DARS: {l['title']}
MATERIAL:
{material[:28000]}
"""
    try:
        raw=await asyncio.to_thread(_openai_response_sync,prompt)
        m=re.search(r"\[[\s\S]*\]",raw)
        data=json.loads(m.group(0) if m else raw)
        good=[]
        for x in data:
            if isinstance(x,dict) and isinstance(x.get("q"),str) and isinstance(x.get("options"),list) and len(x["options"])==4 and str(x.get("answer","")).isdigit():
                a=int(x["answer"])
                if 0<=a<4:good.append({"q":x["q"][:500],"options":[str(z)[:200] for z in x["options"]],"answer":a})
        return good[:count]
    except Exception as e:
        log.exception("V9 test generation: %s",e);return []

async def v9_send_test_question(msg,uid,edit=False):
    st=STATE.get(uid) or {}; qs=st.get("questions") or []; idx=int(st.get("index",0))
    if idx>=len(qs):return
    x=qs[idx]; lid=st["lesson_id"]
    kb=InlineKeyboardMarkup([[InlineKeyboardButton(f"{i+1}. {opt}",callback_data=f"v9:ans:{lid}:{i}")] for i,opt in enumerate(x["options"])])
    text=f"ðŸ“ TEST â€” {idx+1}/{len(qs)}\n\n{x['q']}"
    if edit:return await msg.edit_text(text,reply_markup=kb)
    return await msg.reply_text(text,reply_markup=kb)

async def v9_show_teacher_home(msg,uid):
    await msg.reply_text("ðŸ‘¨â€ðŸ« USTOZ KABINETI\n\nTezkor menyu pastda doim turadi.",reply_markup=v9_teacher_keyboard())
    await msg.reply_text("Kerakli boâ€˜lim:",reply_markup=v9_teacher_markup())

async def v9_show_student_home(msg,uid):
    await msg.reply_text("ðŸ‘¨â€ðŸŽ“ Oâ€˜QUVCHI / TALABA KABINETI\n\nTezkor menyu pastda doim turadi.",reply_markup=v9_student_keyboard())
    await msg.reply_text("Kerakli boâ€˜lim:",reply_markup=v9_student_markup())

async def v9_private_input(update,ctx):
    msg=update.effective_message;u=update.effective_user
    if ctx.user_data.get("news_consumed_message_id")==getattr(msg,"message_id",None):return
    if not msg or not u or msg.chat.type!="private":return
    st=STATE.get(u.id) or {};mode=st.get("mode")
    if str(mode).startswith("v9_"):
        ctx.user_data["v9_consumed_message_id"]=msg.message_id
    # V9 doimiy tezkor menyu
    txt=(msg.text or "").strip()
    prof=one("SELECT role FROM v9_profiles WHERE user_id=?",(u.id,))
    role=prof["role"] if prof else ""

    # GLOBAL NAVIGATSIYA â€” V8/V9 ichida qayerda boâ€˜lishidan qatâ€™i nazar.
    if txt=="ðŸ›¡ Veritas":
        STATE.pop(u.id,None)
        # This navigation message is fully consumed here. Prevent private AI from
        # treating the same button text as a normal AI prompt in a later handler group.
        ctx.user_data["v9_consumed_message_id"]=msg.message_id
        return await msg.reply_text("ðŸ›¡ VERITAS\n\nAsosiy boâ€˜lim:",reply_markup=main_menu_markup(u.id))

    if txt=="ðŸŽ“ Oâ€˜quv â€¢ Talaba":
        STATE.pop(u.id,None)
        ctx.user_data.pop("v9_consumed_message_id",None)
        await msg.reply_text("ðŸŽ“ Oâ€˜QUV â€¢ TALABA\n\nTaâ€™lim turini tanlang:",reply_markup=v9_entry_markup())
        return await msg.reply_text("Asosiy panel:",reply_markup=veritas_global_keyboard())

    if txt=="ðŸ  Bosh menyu" and role:
        STATE.pop(u.id,None)
        if role=="teacher": return await v9_show_teacher_home(msg,u.id)
        return await v9_show_student_home(msg,u.id)

    if txt=="ðŸ‘¥ Guruhlarim" and role=="teacher":
        STATE.pop(u.id,None)
        rows=all_("SELECT id,title FROM v9_groups WHERE teacher_id=? AND is_active=1 ORDER BY id DESC",(u.id,))
        kb=[[InlineKeyboardButton("ðŸ“š "+r["title"][:45],callback_data=f"v9:group:{r['id']}")] for r in rows[:30]]
        if not kb:return await msg.reply_text("ðŸ‘¥ Hali guruh yaratmagansiz.",reply_markup=v9_teacher_keyboard())
        return await msg.reply_text("ðŸ‘¥ GURUHLARIM",reply_markup=InlineKeyboardMarkup(kb))

    if txt=="âž• Dars berish" and role=="teacher":
        STATE.pop(u.id,None)
        rows=all_("SELECT id,title FROM v9_groups WHERE teacher_id=? AND is_active=1 ORDER BY id DESC",(u.id,))
        if not rows:return await msg.reply_text("Avval guruh yarating.",reply_markup=v9_teacher_keyboard())
        kb=[[InlineKeyboardButton("âž• "+r["title"][:45],callback_data=f"v9:lesson:new:{r['id']}")] for r in rows]
        return await msg.reply_text("Qaysi guruhga dars berasiz?",reply_markup=InlineKeyboardMarkup(kb))

    if txt=="ðŸ“Š Jurnal" and role=="teacher":
        STATE.pop(u.id,None)
        rows=all_("SELECT id,title FROM v9_groups WHERE teacher_id=? AND is_active=1 ORDER BY id DESC",(u.id,))
        kb=[[InlineKeyboardButton("ðŸ“Š "+r["title"][:45],callback_data=f"v9:results:{r['id']}")] for r in rows]
        return await msg.reply_text("ðŸ“Š JURNAL\n\nGuruhni tanlang:",reply_markup=InlineKeyboardMarkup(kb) if kb else v9_teacher_keyboard())

    if txt=="ðŸ“š Darslarim" and role=="student":
        STATE.pop(u.id,None)
        rows=all_("SELECT g.id,g.title FROM v9_groups g JOIN v9_group_members m ON m.group_id=g.id WHERE m.user_id=? AND m.is_active=1 AND g.is_active=1",(u.id,))
        kb=[[InlineKeyboardButton("ðŸ“š "+r["title"][:45],callback_data=f"v9:lessons:{r['id']}")] for r in rows]
        return await msg.reply_text("ðŸ“š DARSLARIM\n\nGuruhni tanlang:",reply_markup=InlineKeyboardMarkup(kb) if kb else v9_student_keyboard())

    if txt=="â­ Ballarim" and role=="student":
        STATE.pop(u.id,None)
        rows=all_("SELECT g.title,p.points FROM v9_points p JOIN v9_groups g ON g.id=p.group_id WHERE p.user_id=? ORDER BY p.points DESC",(u.id,))
        body="\n".join(f"ðŸ† {r['title']}: {r['points']} ball" for r in rows) or "Hozircha ball yoâ€˜q."
        return await msg.reply_text("â­ BALLARIM\n\n"+body,reply_markup=v9_student_keyboard())

    if txt=="ðŸ¤– AI Ustoz" and role=="student":
        active=st if st.get("mode")=="v9_ai_lesson" else None
        if active:
            l=one("SELECT title FROM v9_lessons WHERE id=?",(active["lesson_id"],))
            return await msg.reply_text(f"ðŸ¤– AI Ustoz faol: {l['title'] if l else 'dars'}\nSavolingizni yozavering.",reply_markup=v9_student_keyboard())
        rows=all_("""SELECT l.id,l.title FROM v9_lessons l JOIN v9_group_members m ON m.group_id=l.group_id
                     WHERE m.user_id=? AND m.is_active=1 AND l.status='published' ORDER BY l.id DESC LIMIT 20""",(u.id,))
        kb=[[InlineKeyboardButton("ðŸ¤– "+r["title"][:45],callback_data=f"v9:learn:{r['id']}")] for r in rows]
        return await msg.reply_text("ðŸ¤– Qaysi dars boâ€˜yicha AI Ustoz kerak?",reply_markup=InlineKeyboardMarkup(kb) if kb else v9_student_keyboard())

    # V9 oâ€˜qituvchi ish rejasi â€” qoâ€˜lda kiritish
    if mode=="v9_plan_class":
        if not txt:return await msg.reply_text("Sinf/kursni yozing.")
        st.update(class_name=txt[:80],mode="v9_plan_subject");STATE[u.id]=st
        return await msg.reply_text("2/6 â€” Fan nomini yozing. Masalan: Alifbe")
    if mode=="v9_plan_subject":
        if not txt:return await msg.reply_text("Fan nomini yozing.")
        st.update(subject=txt[:100],mode="v9_plan_quarter");STATE[u.id]=st
        return await msg.reply_text("3/6 â€” Davrni yozing. Masalan: I chorak")
    if mode=="v9_plan_quarter":
        if not txt:return await msg.reply_text("Chorak/semestrni yozing.")
        st.update(quarter=txt[:80],mode="v9_plan_weekly");STATE[u.id]=st
        return await msg.reply_text("4/6 â€” Haftasiga necha soat? Masalan: 4")
    if mode=="v9_plan_weekly":
        try: val=float(txt.replace(",","."))
        except:return await msg.reply_text("Faqat soat sonini yozing. Masalan: 4")
        if val<=0 or val>100:return await msg.reply_text("Soat 0 dan katta boâ€˜lsin.")
        st.update(weekly_hours=val,mode="v9_plan_total");STATE[u.id]=st
        return await msg.reply_text("5/6 â€” Jami reja necha soat? Masalan: 36")
    if mode=="v9_plan_total":
        try: val=float(txt.replace(",","."))
        except:return await msg.reply_text("Jami soatni son bilan yozing. Masalan: 36")
        if val<=0 or val>2000:return await msg.reply_text("Jami soat notoâ€˜gâ€˜ri.")
        st.update(planned_hours=val,mode="v9_plan_title");STATE[u.id]=st
        return await msg.reply_text("6/6 â€” Rejaga nom bering.\nMasalan: 1-sinf Alifbe I chorak ish rejasi")
    if mode=="v9_plan_title":
        if not txt:return await msg.reply_text("Reja nomini yozing.")
        with db() as c:
            pid=c.execute("INSERT INTO v9_teacher_plans(teacher_id,title,class_name,subject,quarter,weekly_hours,planned_hours,is_active,created_at) VALUES(?,?,?,?,?,?,?,1,?)",(u.id,txt[:160],st['class_name'],st['subject'],st['quarter'],st['weekly_hours'],st['planned_hours'],now())).lastrowid
        STATE.pop(u.id,None)
        return await msg.reply_text("âœ… Ish reja yaratildi.",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("ðŸ“˜ Rejani ochish",callback_data=f"v9:plan:view:{pid}")]]))

    if mode=="v9_plan_lesson_topic":
        if not txt:return await msg.reply_text("Mavzu nomini yozing.")
        st.update(topic=txt[:300],mode="v9_plan_lesson_visual");STATE[u.id]=st
        return await msg.reply_text("2/5 â€” Koâ€˜rgazmali qurollarni yozing. Yoâ€˜q boâ€˜lsa â€” yozing.")
    if mode=="v9_plan_lesson_visual":
        st.update(visual_aids="" if txt in {"-","â€”"} else txt[:500],mode="v9_plan_lesson_tasks");STATE[u.id]=st
        return await msg.reply_text("3/5 â€” Darslik betlari va mashqlarni yozing. Masalan: Darslik 2â€“3-bet, Mashq 1â€“2")
    if mode=="v9_plan_lesson_tasks":
        st.update(textbook_tasks="" if txt in {"-","â€”"} else txt[:500],mode="v9_plan_lesson_hours");STATE[u.id]=st
        return await msg.reply_text("4/5 â€” Bu dars necha soat? Masalan: 1")
    if mode=="v9_plan_lesson_hours":
        try: val=float(txt.replace(",","."))
        except:return await msg.reply_text("Soatni son bilan yozing. Masalan: 1")
        if val<=0 or val>24:return await msg.reply_text("Soat notoâ€˜gâ€˜ri.")
        st.update(hours=val,mode="v9_plan_lesson_date");STATE[u.id]=st
        return await msg.reply_text("5/5 â€” Taqvimiy muddat/sanani yozing. Masalan: 15.10.2026. Hozircha belgilanmagan boâ€˜lsa â€” yozing.")
    if mode=="v9_plan_lesson_date":
        date="" if txt in {"-","â€”"} else txt[:80]
        with db() as c:c.execute("INSERT INTO v9_plan_lessons(plan_id,lesson_no,topic,visual_aids,textbook_tasks,hours,calendar_date,status,created_at) VALUES(?,?,?,?,?,?,?,'planned',?)",(st['plan_id'],st['lesson_no'],st['topic'],st.get('visual_aids',''),st.get('textbook_tasks',''),st['hours'],date,now()))
        pid=st['plan_id'];STATE.pop(u.id,None)
        return await msg.reply_text(f"âœ… {st['lesson_no']}-dars ish rejaga qoâ€˜shildi.",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("ðŸ“‹ Darslar",callback_data=f"v9:plan:lessons:{pid}")],[InlineKeyboardButton("âž• Yana dars",callback_data=f"v9:plan:addlesson:{pid}")]]))

    # Yangi dars: nom -> material -> AI rejimi
    if mode=="v9_lesson_title":
        if not msg.text or len(txt)<2:return await msg.reply_text("Dars nomini yozing.")
        st["title"]=txt[:150];st["mode"]="v9_lesson_material";STATE[u.id]=st
        return await msg.reply_text(
            "2/3 â€” Dars materialini yuboring.\n\n"
            "ðŸ“ Oddiy matn\nðŸ“„ PDF\nðŸ–¼ Rasm yoki skrinshot\n\n"
            "Veritas materialni oâ€˜qib, talabaga oâ€˜rgatish uchun tayyorlaydi.",
            reply_markup=v9_teacher_keyboard())

    if mode=="v9_lesson_material":
        kind=""; file_id=""; file_name=""; mime=""; extracted=""
        try:
            if msg.text:
                kind="text";extracted=txt
            elif msg.document and (msg.document.mime_type or "").lower()=="application/pdf":
                kind="pdf";file_id=msg.document.file_id;file_name=msg.document.file_name or "dars.pdf";mime="application/pdf"
                tg=await ctx.bot.get_file(file_id);raw=bytes(await tg.download_as_bytearray())
                extracted=v9_extract_pdf(raw)
                if not extracted.strip():
                    return await msg.reply_text("âš ï¸ Bu PDFdan matn olinmadi. Agar skan PDF boâ€˜lsa, sahifalarni rasm qilib yuboring.")
            elif msg.photo or (msg.document and (msg.document.mime_type or "").lower().startswith("image/")):
                obj=msg.photo[-1] if msg.photo else msg.document
                kind="image";file_id=obj.file_id;file_name=getattr(obj,"file_name",None) or "screenshot.jpg";mime=getattr(obj,"mime_type",None) or "image/jpeg"
                tg=await ctx.bot.get_file(file_id);raw=bytes(await tg.download_as_bytearray())
                if not OPENAI_API_KEY:return await msg.reply_text("âš ï¸ Rasmni oâ€˜qish uchun OPENAI_API_KEY kerak.")
                extracted=await asyncio.to_thread(_openai_image_response_sync,raw,mime,"Rasmdagi darslik matni, formulalar, jadval va asosiy maâ€™lumotlarni aniq koâ€˜chirib/tavsiflab bering. Hech narsa uydirmang.")
            else:
                return await msg.reply_text("PDF, rasm/skrinshot yoki yozma dars yuboring.")
        except Exception as e:
            log.exception("V9 material: %s",e)
            return await msg.reply_text("âš ï¸ Materialni oâ€˜qishda xato boâ€˜ldi. Boshqa fayl yoki matn bilan urinib koâ€˜ring.")
        st["material"]={"kind":kind,"file_id":file_id,"file_name":file_name,"mime":mime,"text":extracted[:45000]}
        st["mode"]="v9_lesson_mode";STATE[u.id]=st
        kb=InlineKeyboardMarkup([
          [InlineKeyboardButton("ðŸ”’ Faqat darslikdan",callback_data="v9:lessonmode:material_only")],
          [InlineKeyboardButton("ðŸ§  Darslik + AI tushuntirishi",callback_data="v9:lessonmode:ai_plus")]])
        return await msg.reply_text(f"âœ… Material qabul qilindi ({len(extracted)} belgi).\n\n3/3 â€” AI qanday oâ€˜qitsin?",reply_markup=kb)

    if mode=="v9_ai_lesson" and msg.text:
        lid=int(st["lesson_id"]);l=one("SELECT * FROM v9_lessons WHERE id=? AND status='published'",(lid,))
        if not l:return
        material=v9_lesson_context(lid)
        answer=await v9_ai_teach(l,material,txt)
        ctx.user_data["v9_consumed_message_id"]=msg.message_id
        return await msg.reply_text(answer[:4000],reply_markup=v9_student_keyboard())
    if mode=="v9_new_group_title":
        if not msg.text or len(msg.text.strip())<2:return await msg.reply_text("Guruh nomini matn qilib yozing.")
        st["title"]=msg.text.strip()[:120];st["mode"]="v9_new_group_subject";STATE[u.id]=st
        return await msg.reply_text("ðŸ“– Endi fan nomini yozing.\nMasalan: Matematika")
    if mode=="v9_new_group_subject":
        if not msg.text or len(msg.text.strip())<2:return await msg.reply_text("Fan nomini matn qilib yozing.")
        import secrets
        prof=one("SELECT institution_type FROM v9_profiles WHERE user_id=?",(u.id,));inst=prof["institution_type"] if prof else "school"
        title=st.get("title","Yangi guruh");subject=msg.text.strip()[:100];gid=None
        for _ in range(10):
            code="V9-"+secrets.token_hex(3).upper()
            try:
                with db() as c:gid=c.execute("INSERT INTO v9_groups(teacher_id,institution_type,title,subject,join_code,is_active,created_at) VALUES(?,?,?,?,?,1,?)",(u.id,inst,title,subject,code,now())).lastrowid
                break
            except sqlite3.IntegrityError:pass
        if not gid:return await msg.reply_text("Guruh kodi yaratilmadi. Qayta urinib koâ€˜ring.")
        STATE.pop(u.id,None)
        return await msg.reply_text(f"âœ… GURUH YARATILDI\n\nðŸ“š {title}\nðŸ“– {subject}\nðŸ”‘ Kod: {code}\n\nTalabalarga shu kodni bering.",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("ðŸ“š Guruhni ochish",callback_data=f"v9:group:{gid}")]]))
    if mode=="v9_join_group":
        if not msg.text:return await msg.reply_text("Ustoz bergan guruh kodini yozing.")
        code=msg.text.strip().upper();g=one("SELECT id,title,teacher_id FROM v9_groups WHERE upper(join_code)=? AND is_active=1",(code,))
        if not g:return await msg.reply_text("âŒ Bunday faol guruh kodi topilmadi.")
        if int(g["teacher_id"])==u.id:STATE.pop(u.id,None);return await msg.reply_text("Siz bu guruhning ustozisiz.")
        with db() as c:
            c.execute("INSERT INTO v9_group_members(group_id,user_id,joined_at,is_active) VALUES(?,?,?,1) ON CONFLICT(group_id,user_id) DO UPDATE SET is_active=1",(g["id"],u.id,now()))
            c.execute("INSERT INTO v9_points(group_id,user_id,points,updated_at) VALUES(?,?,0,?) ON CONFLICT(group_id,user_id) DO NOTHING",(g["id"],u.id,now()))
        STATE.pop(u.id,None)
        return await msg.reply_text(f"âœ… {g['title']} guruhiga qoâ€˜shildingiz.",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("ðŸ“š Guruhni ochish",callback_data=f"v9:group:{g['id']}")]]))
# =========================================================
# VERITAS V9 â€” END
# =========================================================

# =========================================================
# VERITAS V9.1 â€” UNIVERSAL 3-LANGUAGE ENGINE
# All outgoing bot text/UI is localized automatically.
# Uzbek is source/default; Russian/English are translated and cached.
# =========================================================
I18N_LANGS={"uz":"Oâ€˜zbekcha","ru":"Ð ÑƒÑÑÐºÐ¸Ð¹","en":"English"}

def i18n_init_db():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS i18n_cache(
            lang TEXT NOT NULL,
            source TEXT NOT NULL,
            translated TEXT NOT NULL,
            PRIMARY KEY(lang,source)
        );
        CREATE TABLE IF NOT EXISTS group_languages(
            chat_id INTEGER PRIMARY KEY,
            lang TEXT NOT NULL DEFAULT 'uz',
            updated_by INTEGER DEFAULT 0,
            updated_at INTEGER DEFAULT 0
        );
        """)

def chat_lang(chat_id):
    try:
        cid=int(chat_id)
    except Exception:
        return "uz"
    # Telegram private chat id equals user id.
    if cid > 0:
        try:
            r=one("SELECT lang FROM users WHERE user_id=?",(cid,))
            x=(r["lang"] if r else "uz") or "uz"
            return x if x in I18N_LANGS else "uz"
        except Exception:
            return "uz"
    try:
        r=one("SELECT lang FROM group_languages WHERE chat_id=?",(cid,))
        x=(r["lang"] if r else "uz") or "uz"
        return x if x in I18N_LANGS else "uz"
    except Exception:
        return "uz"

def set_group_lang(chat_id,lang,uid=0):
    if lang not in I18N_LANGS:return
    with db() as c:
        c.execute("""INSERT INTO group_languages(chat_id,lang,updated_by,updated_at)
                     VALUES(?,?,?,?)
                     ON CONFLICT(chat_id) DO UPDATE SET
                     lang=excluded.lang,updated_by=excluded.updated_by,updated_at=excluded.updated_at""",
                  (int(chat_id),lang,int(uid or 0),now()))

def _i18n_translate_sync(text,lang):
    text=str(text or "")
    if not text or lang=="uz": return text
    try:
        r=one("SELECT translated FROM i18n_cache WHERE lang=? AND source=?",(lang,text))
        if r:return r["translated"]
    except Exception:pass
    if not OPENAI_API_KEY:
        # Never break the bot if AI key is temporarily unavailable.
        return text
    target="Russian" if lang=="ru" else "English"
    prompt=f"""Translate the following Telegram bot interface/message from Uzbek into natural {target}.
STRICT RULES:
- Return ONLY the translated text.
- Preserve meaning exactly; do not add facts or commentary.
- Preserve all URLs, @usernames, Telegram commands, IDs, numbers, emojis, Markdown/HTML tags and placeholders.
- Do not translate proper product names: Veritas, Vasatiya, Telegram, AI.
- Keep line breaks and compact UI style.
TEXT:
{text}"""
    try:
        out=_openai_response_sync(prompt).strip()
        if not out:return text
        try:
            with db() as c:
                c.execute("INSERT OR REPLACE INTO i18n_cache(lang,source,translated) VALUES(?,?,?)",(lang,text,out))
        except Exception:pass
        return out
    except Exception:
        log.exception("i18n translation failed")
        return text

async def i18n_text(text,lang):
    if not text or lang=="uz":return text
    return await asyncio.to_thread(_i18n_translate_sync,text,lang)

async def i18n_markup(markup,lang,bot):
    if not markup or lang=="uz":return markup
    try:
        data=markup.to_dict()
        if "inline_keyboard" in data:
            for row in data["inline_keyboard"]:
                for b in row:
                    if b.get("text"):b["text"]=await i18n_text(b["text"],lang)
            return InlineKeyboardMarkup.de_json(data,bot)
        if "keyboard" in data:
            # Reply-klaviatura matnlari handlerlarda aynan solishtiriladi ("ðŸ›¡ Veritas" va h.k.).
            # Tarjima qilinsa tugmalar ishlamay qoladi, shuning uchun o'zgartirmaymiz.
            return markup
            for row in data["keyboard"]:
                for b in row:
                    if isinstance(b,dict) and b.get("text"):b["text"]=await i18n_text(b["text"],lang)
            return ReplyKeyboardMarkup.de_json(data,bot)
    except Exception:
        log.exception("i18n markup failed")
    return markup

class VeritasI18nBot(ExtBot):
    async def send_message(self,chat_id,text,*args,**kwargs):
        if kwargs.pop("_skip_i18n", False):
            return await super().send_message(chat_id,text,*args,**kwargs)
        lang=chat_lang(chat_id)
        text=await i18n_text(text,lang)
        if kwargs.get("reply_markup"):
            kwargs["reply_markup"]=await i18n_markup(kwargs["reply_markup"],lang,self)
        return await super().send_message(chat_id,text,*args,**kwargs)

    async def edit_message_text(self,text,*args,**kwargs):
        if kwargs.pop("_skip_i18n", False):
            return await super().edit_message_text(text,*args,**kwargs)
        chat_id=kwargs.get("chat_id")
        lang=chat_lang(chat_id) if chat_id is not None else "uz"
        text=await i18n_text(text,lang)
        if kwargs.get("reply_markup"):
            kwargs["reply_markup"]=await i18n_markup(kwargs["reply_markup"],lang,self)
        return await super().edit_message_text(text,*args,**kwargs)

    async def send_photo(self,chat_id,photo,*args,**kwargs):
        if kwargs.pop("_skip_i18n", False):
            return await super().send_photo(chat_id,photo,*args,**kwargs)
        lang=chat_lang(chat_id)
        if kwargs.get("caption"):kwargs["caption"]=await i18n_text(kwargs["caption"],lang)
        if kwargs.get("reply_markup"):kwargs["reply_markup"]=await i18n_markup(kwargs["reply_markup"],lang,self)
        return await super().send_photo(chat_id,photo,*args,**kwargs)

    async def send_video(self,chat_id,video,*args,**kwargs):
        if kwargs.pop("_skip_i18n", False):
            return await super().send_video(chat_id,video,*args,**kwargs)
        lang=chat_lang(chat_id)
        if kwargs.get("caption"):kwargs["caption"]=await i18n_text(kwargs["caption"],lang)
        if kwargs.get("reply_markup"):kwargs["reply_markup"]=await i18n_markup(kwargs["reply_markup"],lang,self)
        return await super().send_video(chat_id,video,*args,**kwargs)

    async def send_document(self,chat_id,document,*args,**kwargs):
        if kwargs.pop("_skip_i18n", False):
            return await super().send_document(chat_id,document,*args,**kwargs)
        lang=chat_lang(chat_id)
        if kwargs.get("caption"):kwargs["caption"]=await i18n_text(kwargs["caption"],lang)
        if kwargs.get("reply_markup"):kwargs["reply_markup"]=await i18n_markup(kwargs["reply_markup"],lang,self)
        return await super().send_document(chat_id,document,*args,**kwargs)

    async def edit_message_caption(self,*args,**kwargs):
        chat_id=kwargs.get("chat_id")
        lang=chat_lang(chat_id) if chat_id is not None else "uz"
        if kwargs.get("caption"):kwargs["caption"]=await i18n_text(kwargs["caption"],lang)
        if kwargs.get("reply_markup"):kwargs["reply_markup"]=await i18n_markup(kwargs["reply_markup"],lang,self)
        return await super().edit_message_caption(*args,**kwargs)

def group_lang_markup(chat_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("ðŸ‡ºðŸ‡¿ Oâ€˜zbekcha",callback_data=f"glang:{chat_id}:uz"),
         InlineKeyboardButton("ðŸ‡·ðŸ‡º Ð ÑƒÑÑÐºÐ¸Ð¹",callback_data=f"glang:{chat_id}:ru")],
        [InlineKeyboardButton("ðŸ‡¬ðŸ‡§ English",callback_data=f"glang:{chat_id}:en")]
    ])

async def group_lang_command(update,ctx):
    msg=update.effective_message;u=update.effective_user;chat=update.effective_chat
    if not msg or not u or not chat or chat.type=="private":return
    try:
        cm=await ctx.bot.get_chat_member(chat.id,u.id)
        allowed=(cm.status in (ChatMemberStatus.ADMINISTRATOR,ChatMemberStatus.OWNER)) or u.id in SUPER_OWNERS
    except Exception:
        allowed=u.id in SUPER_OWNERS
    if not allowed:
        return await msg.reply_text("âš ï¸ Guruh tilini faqat administrator oâ€˜zgartira oladi.")
    return await msg.reply_text("ðŸŒ Guruh tilini tanlang:",reply_markup=group_lang_markup(chat.id))

async def group_lang_callback(update,ctx):
    q=update.callback_query;d=q.data or "";u=q.from_user
    m=re.fullmatch(r"glang:(-?\d+):(uz|ru|en)",d)
    if not m:return
    chat_id=int(m.group(1));lang=m.group(2)
    try:
        cm=await ctx.bot.get_chat_member(chat_id,u.id)
        allowed=(cm.status in (ChatMemberStatus.ADMINISTRATOR,ChatMemberStatus.OWNER)) or u.id in SUPER_OWNERS
    except Exception:
        allowed=u.id in SUPER_OWNERS
    if not allowed:return await q.answer("Faqat guruh administratori.",show_alert=True)
    set_group_lang(chat_id,lang,u.id)
    await q.answer("âœ…")
    text={"uz":"âœ… Guruh tili: Oâ€˜zbekcha","ru":"âœ… Ð¯Ð·Ñ‹Ðº Ð³Ñ€ÑƒÐ¿Ð¿Ñ‹: Ð ÑƒÑÑÐºÐ¸Ð¹","en":"âœ… Group language: English"}[lang]
    try:await q.edit_message_text(text)
    except TelegramError:pass

# =========================================================
# V9.1 â€” BIR TILLI AI YANGILIK MARKAZI
# =========================================================
LANG_NAMES={"uz":"ðŸ‡ºðŸ‡¿ Oâ€˜zbekcha","ru":"ðŸ‡·ðŸ‡º Ð ÑƒÑÑÐºÐ¸Ð¹","en":"ðŸ‡¬ðŸ‡§ English"}
NEWS_SEND_SEMAPHORE=asyncio.Semaphore(12)
def user_lang(uid):
    r=one("SELECT lang FROM users WHERE user_id=?",(uid,)); x=(r["lang"] if r else "uz") or "uz"
    return x if x in LANG_NAMES else "uz"
def set_user_lang(uid,lang):
    if lang in LANG_NAMES: execute("UPDATE users SET lang=? WHERE user_id=?",(lang,uid))
def L(uid,uz,ru,en): return {"uz":uz,"ru":ru,"en":en}.get(user_lang(uid),uz)
def lang_markup(back="home"):
    return InlineKeyboardMarkup([[InlineKeyboardButton("ðŸ‡ºðŸ‡¿ Oâ€˜zbekcha",callback_data="lang:set:uz"),InlineKeyboardButton("ðŸ‡·ðŸ‡º Ð ÑƒÑÑÐºÐ¸Ð¹",callback_data="lang:set:ru")],[InlineKeyboardButton("ðŸ‡¬ðŸ‡§ English",callback_data="lang:set:en")],[InlineKeyboardButton("â¬…ï¸ Orqaga / ÐÐ°Ð·Ð°Ð´ / Back",callback_data=back)]])
def ai_news_init_db():
    with db() as c:
        c.executescript("""CREATE TABLE IF NOT EXISTS ai_news_posts(id INTEGER PRIMARY KEY AUTOINCREMENT,creator_id INTEGER NOT NULL,source_text TEXT DEFAULT '',uz_text TEXT DEFAULT '',ru_text TEXT DEFAULT '',en_text TEXT DEFAULT '',media_type TEXT DEFAULT '',media_file_id TEXT DEFAULT '',status TEXT DEFAULT 'draft',sent_ok INTEGER DEFAULT 0,sent_fail INTEGER DEFAULT 0,created_at INTEGER NOT NULL,sent_at INTEGER DEFAULT 0); CREATE INDEX IF NOT EXISTS idx_ai_news_status ON ai_news_posts(status,id);""")
        cols={r[1] for r in c.execute("PRAGMA table_info(ai_news_posts)").fetchall()}
        if "target_chat_id" not in cols:
            c.execute("ALTER TABLE ai_news_posts ADD COLUMN target_chat_id INTEGER DEFAULT 0")
        if "scope" not in cols:
            c.execute("ALTER TABLE ai_news_posts ADD COLUMN scope TEXT DEFAULT 'global'")
def _ai_news_prepare_sync(source):
    if not OPENAI_API_KEY: raise RuntimeError("OPENAI_API_KEY sozlanmagan")
    prompt=("Siz Veritas rasmiy yangilik muharririsiz. Quyidagi xabarni AYNAN O'Z TILIDA saqlang. "
            "Tarjima qilmang. Ma'nosini o'zgartirmasdan imlo va uslubini tuzating, Telegram posti uchun "
            "ixcham va chiroyli bezang. Yangi fakt uydirmang. Faqat tayyor post matnini qaytaring; JSON kerak emas. "
            "Mos sarlavha va me'yorida emoji ishlating.\n\nXABAR:\n"+source)
    text=str(_openai_response_sync(prompt) or '').strip()
    if not text: raise ValueError("AI post matnini qaytarmadi")
    return {"uz":text,"ru":"","en":""}
async def ai_news_prepare(source): return await asyncio.to_thread(_ai_news_prepare_sync,source)
def ai_news_super_markup():
    return InlineKeyboardMarkup([[InlineKeyboardButton("ðŸ“¢ AI Yangilik joylash",callback_data="news:new")],[InlineKeyboardButton("ðŸ“° Oxirgi yangiliklar",callback_data="news:list")],[InlineKeyboardButton("â¬…ï¸ Orqaga",callback_data="super")]])
def ai_news_preview_markup(nid):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("ðŸ”„ AI qayta bezasin",callback_data=f"news:redo:{nid}"),InlineKeyboardButton("âœï¸ Qayta yozish",callback_data=f"news:edit:{nid}")],
        [InlineKeyboardButton("ðŸ–¼ POSTER YARATISH",callback_data=f"poster:styles:{nid}")],
        [InlineKeyboardButton("ðŸ“¢ BARCHA GURUHLARGA YUBORISH",callback_data=f"news:send:{nid}")],
        [InlineKeyboardButton("âŒ Bekor qilish",callback_data=f"news:cancel:{nid}")]
    ])

def ai_news_ready_markup(nid):
    # Poster confirmed: send button is immediately available; no language selection step.
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("ðŸ“¢ BARCHA GURUHLARGA YUBORISH",callback_data=f"news:send:{nid}")],
        [InlineKeyboardButton("ðŸ”„ Posterni qayta yaratish",callback_data=f"poster:styles:{nid}")],
        [InlineKeyboardButton("âœï¸ Matnni qayta yozish",callback_data=f"news:edit:{nid}")],
        [InlineKeyboardButton("âŒ Bekor qilish",callback_data=f"news:cancel:{nid}")],
    ])
def ai_news_group_preview_markup(nid):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("ðŸ–¼ POSTER YARATISH",callback_data=f"poster:styles:{nid}")],
        [InlineKeyboardButton("ðŸ“¢ SHU GURUHGA YUBORISH",callback_data=f"news:sendgroup:{nid}")],
        [InlineKeyboardButton("âŒ Bekor qilish",callback_data=f"news:cancel:{nid}")],
    ])

def ai_news_group_ready_markup(nid):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("ðŸ“¢ SHU GURUHGA YUBORISH",callback_data=f"news:sendgroup:{nid}")],
        [InlineKeyboardButton("ðŸ”„ Posterni qayta yaratish",callback_data=f"poster:styles:{nid}")],
        [InlineKeyboardButton("âŒ Bekor qilish",callback_data=f"news:cancel:{nid}")],
    ])

async def _news_send_one(bot,uid,text,media_type='',file_id=''):
    """Send one news item. Poster/media and full text are sent separately.
    This avoids Telegram's 1024-char media-caption limit and does not require
    the owner to press any language-preview buttons first.
    """
    async with NEWS_SEND_SEMAPHORE:
        try:
            if media_type=='photo' and file_id:
                uid=await _news_call(bot.send_photo,uid,photo=file_id,_skip_i18n=True)
            elif media_type=='video' and file_id:
                uid=await _news_call(bot.send_video,uid,video=file_id,_skip_i18n=True)
            elif media_type=='document' and file_id:
                uid=await _news_call(bot.send_document,uid,document=file_id,_skip_i18n=True)
            if text:
                # Telegram message limit is 4096. Split safely if AI made a longer post.
                for pos in range(0,len(text),4000):
                    uid=await _news_call(bot.send_message,uid,text=text[pos:pos+4000],_skip_i18n=True)
            return True
        except TelegramError as exc:
            log.warning("AI news delivery failed uid=%s: %s",uid,exc)
            return False
        except Exception as exc:
            log.exception("AI news unexpected delivery error uid=%s: %s",uid,exc)
            return False
async def ai_news_broadcast(ctx,nid):
    post=one("SELECT * FROM ai_news_posts WHERE id=?",(nid,))
    groups=all_("SELECT chat_id FROM groups ORDER BY chat_id")
    if not post:return (0,0)
    text=(post['uz_text'] or post['source_text'] or '').strip()
    ok=fail=0
    for pos in range(0,len(groups),20):
        tasks=[_news_send_one(ctx.bot,int(r['chat_id']),text,post['media_type'],post['media_file_id']) for r in groups[pos:pos+20]]
        for x in await asyncio.gather(*tasks,return_exceptions=True):
            if x is True:ok+=1
            else:fail+=1
        await asyncio.sleep(.35)
    execute("UPDATE ai_news_posts SET status='sent',sent_ok=?,sent_fail=?,sent_at=? WHERE id=?",(ok,fail,now(),nid))
    return ok,fail

async def ai_news_private_input(update,ctx):
    msg=update.effective_message;u=update.effective_user
    if not msg or not u or msg.chat.type!='private' or u.id not in SUPER_OWNERS:return
    st=STATE.get(u.id) or {}
    if st.get('mode')!='ai_news_input':return
    ctx.user_data['news_consumed_message_id']=msg.message_id; source=(msg.text or msg.caption or '').strip()
    if not source:return await msg.reply_text("Yangilik matnini yozing. Rasm/video yuborsangiz caption ham yozing.")
    media_type=file_id=''
    if msg.photo:media_type='photo';file_id=msg.photo[-1].file_id
    elif msg.video:media_type='video';file_id=msg.video.file_id
    elif msg.document:media_type='document';file_id=msg.document.file_id
    wait=await msg.reply_text("ðŸ¤– AI postni tayyorlamoqda...")
    try:data=await ai_news_prepare(source)
    except Exception as e:log.exception("AI news prepare: %s",e);return await wait.edit_text("âš ï¸ AI yangilikni tayyorlay olmadi. OPENAI_API_KEY va logni tekshiring.")
    edit_id=int(st.get('edit_id') or 0)
    old=one("SELECT * FROM ai_news_posts WHERE id=? AND status='draft'",(edit_id,)) if edit_id else None
    if old:
        nid=edit_id
        with db() as c:
            if media_type:
                c.execute("UPDATE ai_news_posts SET source_text=?,uz_text=?,ru_text=?,en_text=?,media_type=?,media_file_id=? WHERE id=?",(source,data['uz'],data['ru'],data['en'],media_type,file_id,nid))
            else:
                # Eski poster eski matn asosida chizilgan â€” matn o'zgargani uchun uni olib tashlaymiz.
                pr=c.execute("SELECT file_id FROM ai_news_posters WHERE post_id=?",(nid,)).fetchone()
                if pr and pr["file_id"]==(old["media_file_id"] or ""):
                    c.execute("UPDATE ai_news_posts SET media_type='',media_file_id='' WHERE id=?",(nid,))
                c.execute("UPDATE ai_news_posts SET source_text=?,uz_text=?,ru_text=?,en_text=? WHERE id=?",(source,data['uz'],data['ru'],data['en'],nid))
            c.execute("DELETE FROM ai_news_posters WHERE post_id=?",(nid,))
    else:
        with db() as c:nid=c.execute("INSERT INTO ai_news_posts(creator_id,source_text,uz_text,ru_text,en_text,media_type,media_file_id,status,created_at) VALUES(?,?,?,?,?,?,?,'draft',?)",(u.id,source,data['uz'],data['ru'],data['en'],media_type,file_id,now())).lastrowid
    STATE.pop(u.id,None); await wait.edit_text(f"ðŸ“¢ YANGILIK #{nid} â€” PREVIEW\n\n{data['uz'][:3300]}",reply_markup=ai_news_preview_markup(nid))
async def _news_edit(q,text,reply_markup=None):
    # AI News preview is already deliberately written in uz/ru/en.
    # Do NOT pass it through the global auto-translator again.
    bot=q.get_bot()
    chat_id=q.message.chat_id
    try:
        return await bot.edit_message_text(
            chat_id=chat_id,message_id=q.message.message_id,text=text,
            reply_markup=reply_markup,_skip_i18n=True)
    except TelegramError:
        return await bot.send_message(
            chat_id=chat_id,text=text,reply_markup=reply_markup,_skip_i18n=True)

# =========================================================
# V9.1 â€” AI POSTER STUDIO (faqat Super Egalar)
# =========================================================
POSTER_STYLES = {
    "gold": ("ðŸ–¤ Qora-oltin Veritas", "luxurious black and antique gold, Veritas monogram, premium editorial design"),
    "books": ("ðŸ“š Kitobiy", "warm library, beautiful books, cozy scholarly aesthetic, elegant typography"),
    "islam": ("ðŸ•Œ Islomiy", "tasteful Islamic geometric ornament, elegant arches, warm lantern light, no human figures"),
    "school": ("ðŸŽ“ Taâ€™lim", "modern educational infographic, academic symbols, readable hierarchy, welcoming school aesthetic"),
    "auto": ("âœ¨ AI oâ€˜zi tanlasin", "choose a suitable professional visual style for the announcement topic"),
}
POSTER_LOCK = asyncio.Semaphore(2)

def poster_init_db():
    with db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS ai_news_posters(
            post_id INTEGER PRIMARY KEY,
            style TEXT NOT NULL,
            file_id TEXT NOT NULL,
            created_at INTEGER NOT NULL
        )""")

def poster_style_markup(nid):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(name, callback_data=f"poster:make:{nid}:{key}")]
        for key,(name,_) in POSTER_STYLES.items()
    ] + [[InlineKeyboardButton("â¬…ï¸ Yangilikka qaytish",callback_data=f"news:preview:{nid}:uz")]])

def poster_confirm_markup(nid,style):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("âœ… POSTERNI TASDIQLASH",callback_data=f"poster:accept:{nid}")],
        [InlineKeyboardButton("ðŸ”„ Qayta yaratish",callback_data=f"poster:make:{nid}:{style}"),
         InlineKeyboardButton("ðŸŽ¨ Boshqa uslub",callback_data=f"poster:styles:{nid}")],
        [InlineKeyboardButton("âŒ Rad etish",callback_data=f"poster:reject:{nid}")],
    ])

def poster_generate_sync(text,style):
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY Railway'da sozlanmagan")
    visual=POSTER_STYLES[style][1]
    prompt=(
        "Create a gorgeous, professionally designed TELEGRAM ANNOUNCEMENT POSTER, portrait 1024x1536. "
        "Design: "+visual+". High-end polished infographic layout, strong visual hierarchy, legible text, "
        "tasteful illustrations, sophisticated lighting and composition. "
        "Use the following announcement as the ONLY factual source. "
        "Do not invent dates, prices, phone numbers, claims, or links. "
        "Use its original Uzbek language, with a short exact headline and 3-5 short key points. "
        "Avoid long paragraphs, ensure Uzbek Latin letters and punctuation are correct. "
        "Include brand name VERITAS only if relevant. No watermark. "
        "ANNOUNCEMENT:\n"+text[:2200]
    )
    payload=json.dumps({"model":os.getenv("POSTER_IMAGE_MODEL",REBUS_IMAGE_MODEL),
                        "prompt":prompt,"size":"1024x1536","quality":"medium"},ensure_ascii=False).encode("utf-8")
    req=urllib.request.Request("https://api.openai.com/v1/images/generations",data=payload,
        headers={"Authorization":f"Bearer {OPENAI_API_KEY}","Content-Type":"application/json"},method="POST")
    try:
        with urllib.request.urlopen(req,timeout=240) as response:
            result=json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail=exc.read().decode("utf-8",errors="replace")[:400]
        raise RuntimeError(f"Image API HTTP {exc.code}: {detail}") from exc
    item=(result.get("data") or [{}])[0]
    if item.get("b64_json"):
        return base64.b64decode(item["b64_json"])
    if item.get("url"):
        with urllib.request.urlopen(item["url"],timeout=120) as response:
            return response.read()
    raise RuntimeError("Image API rasm qaytarmadi")

async def poster_callback(update,ctx):
    q=update.callback_query; d=q.data or ""; uid=q.from_user.id
    # Super Ega global postlarni; guruh admini esa faqat oâ€˜z guruhiga tegishli postni boshqaradi.
    # Post yuklangach target_chat_id boâ€˜yicha yana tekshiriladi.
    # Callbackni regexsiz qatâ€™iy parse qilamiz. Telegram callback_data uchun ishonchliroq.
    parts=d.split(":")
    if len(parts) not in (3,4) or parts[0] != "poster":
        return await q.answer("Notoâ€˜gâ€˜ri tugma",show_alert=True)
    action=parts[1]
    if action not in {"styles","make","accept","reject"} or not parts[2].isdigit():
        return await q.answer("Notoâ€˜gâ€˜ri tugma",show_alert=True)
    nid=int(parts[2])
    style=parts[3] if len(parts)==4 else None
    if action=="make" and style not in POSTER_STYLES:
        return await q.answer("Poster uslubi topilmadi.",show_alert=True)
    if action!="make" and style is not None:
        return await q.answer("Notoâ€˜gâ€˜ri tugma",show_alert=True)
    post=one("SELECT * FROM ai_news_posts WHERE id=?",(nid,))
    if not post or post['status']!='draft':
        return await q.answer("Yangilik topilmadi yoki yuborilgan.",show_alert=True)
    target_chat_id=int(post["target_chat_id"] or 0)
    if target_chat_id:
        if post["creator_id"] != uid or not await can_manage(ctx.bot,target_chat_id,uid):
            return await q.answer("Bu poster sizning guruhingizga tegishli emas.",show_alert=True)
    elif uid not in SUPER_OWNERS:
        return await q.answer("Faqat Super Ega uchun.",show_alert=True)
    if action=='styles':
        await q.answer()
        return await ctx.bot.send_message(q.message.chat_id,"ðŸŽ¨ Poster uchun uslubni tanlang:",reply_markup=poster_style_markup(nid),_skip_i18n=True)
    if action=='make':
        await q.answer("ðŸŽ¨ Poster yaratilmoqda...")
        status=await ctx.bot.send_message(q.message.chat_id,"â³ AI poster chizmoqda. Bu biroz vaqt olishi mumkin.",_skip_i18n=True)
        try:
            async with POSTER_LOCK:
                image_bytes=await asyncio.to_thread(poster_generate_sync,post['uz_text'],style)
            bio=io.BytesIO(image_bytes);bio.name="veritas_poster.png";bio.seek(0)
            photo=await ctx.bot.send_photo(q.message.chat_id,bio,caption=f"ðŸ–¼ Yangilik #{nid} â€” poster preview\nðŸŽ¨ {POSTER_STYLES[style][0]}\n\nTasdiqlashdan oldin rasmdagi yozuvlarni tekshiring.",reply_markup=poster_confirm_markup(nid,style),_skip_i18n=True)
            file_id=photo.photo[-1].file_id
            with db() as c:
                c.execute("INSERT OR REPLACE INTO ai_news_posters(post_id,style,file_id,created_at) VALUES(?,?,?,?)",(nid,style,file_id,now()))
            await status.delete()
        except Exception as exc:
            log.exception("poster generation failed")
            await status.edit_text("âš ï¸ Poster yaratilmadi. Hech kimga yuborilmadi.\nSabab: "+str(exc)[:550])
        return
    if action=='reject':
        await q.answer("Bekor qilindi")
        execute("DELETE FROM ai_news_posters WHERE post_id=?",(nid,))
        return await ctx.bot.send_message(q.message.chat_id,"âŒ Poster rad etildi. Yangilik matni saqlandi.",reply_markup=ai_news_group_preview_markup(nid) if target_chat_id else ai_news_preview_markup(nid),_skip_i18n=True)
    if action=='accept':
        candidate=one("SELECT * FROM ai_news_posters WHERE post_id=?",(nid,))
        if not candidate:return await q.answer("Poster topilmadi. Qayta yarating.",show_alert=True)
        execute("UPDATE ai_news_posts SET media_type='photo',media_file_id=? WHERE id=? AND status='draft'",(candidate['file_id'],nid))
        await q.answer("Poster saqlandi!")
        if target_chat_id:
            return await ctx.bot.send_message(q.message.chat_id,f"âœ… Poster #{nid} tayyor.\n\nðŸ“¢ SHU GURUHGA YUBORISH tugmasi faqat shu guruhga yuboradi.",reply_markup=ai_news_group_ready_markup(nid),_skip_i18n=True)
        return await ctx.bot.send_message(q.message.chat_id,f"âœ… Poster #{nid} yangilikka biriktirildi.\n\nðŸ“¢ BARCHA GURUHLARGA YUBORISH bosilganda shu bitta post va poster bot qoâ€˜shilgan barcha guruhlarga yuboriladi.",reply_markup=ai_news_ready_markup(nid),_skip_i18n=True)

async def ai_news_callback(update,ctx):
    q=update.callback_query;u=q.from_user;d=q.data or ''
    log.warning("NEWS CALLBACK RECEIVED uid=%s data=%s", u.id, d)
    if u.id not in SUPER_OWNERS:
        # Guruh admini faqat o'zi *poster orqali yaratgan, shu guruhga tegishli postni
        # ko'rishi (preview) va bekor qilishi mumkin.
        gm=re.fullmatch(r"news:(?:cancel:(\d+)|preview:(\d+):(?:uz|ru|en))",d)
        gp=one("SELECT * FROM ai_news_posts WHERE id=?",(int(gm.group(1) or gm.group(2)),)) if gm else None
        if not gp or not int(gp["target_chat_id"] or 0) or gp["creator_id"]!=u.id or not await can_manage(ctx.bot,int(gp["target_chat_id"]),u.id):
            return await q.answer("Faqat Super Ega uchun.",show_alert=True)
    if d=='news:menu':await q.answer();return await _news_edit(q,"ðŸ“¢ AI YANGILIK MARKAZI",reply_markup=ai_news_super_markup())
    if d=='news:new':await q.answer();STATE[u.id]={'mode':'ai_news_input'};return await _news_edit(q,"ðŸ“¢ Yangilik matnini yuboring.\n\nMatn, rasm+caption, video+caption yoki hujjat+caption mumkin. AI matnni oâ€˜z tilida tuzatib, bitta tayyor post yaratadi.")
    if d=='news:list':
        await q.answer();rows=all_("SELECT id,status,sent_ok,sent_fail FROM ai_news_posts ORDER BY id DESC LIMIT 15");body='\n'.join(f"#{r['id']} Â· {r['status']} Â· âœ…{r['sent_ok']} âŒ{r['sent_fail']}" for r in rows) or 'Hali yangilik yoâ€˜q.';return await _news_edit(q,"ðŸ“° OXIRGI YANGILIKLAR\n\n"+body,reply_markup=ai_news_super_markup())
    m=re.fullmatch(r"news:preview:(\d+):(uz|ru|en)", d)
    if m:
        nid=int(m.group(1)); lang=m.group(2)
        r=one("SELECT * FROM ai_news_posts WHERE id=?",(nid,))
        if not r:
            return await q.answer("Yangilik topilmadi.",show_alert=True)
        body=(r[lang+"_text"] or "").strip()
        if not body:
            return await q.answer("Bu tildagi matn tayyor emas.",show_alert=True)
        await q.answer({"uz":"ðŸ‡ºðŸ‡¿ Oâ€˜zbekcha","ru":"ðŸ‡·ðŸ‡º Ð ÑƒÑÑÐºÐ¸Ð¹","en":"ðŸ‡¬ðŸ‡§ English"}[lang])
        if int(r["target_chat_id"] or 0):
            # Guruh posti: faqat shu guruhga yuborish tugmalari. Global yuborish ko'rsatilmaydi.
            pmk=ai_news_group_ready_markup(nid) if (r["media_file_id"] or "") else ai_news_group_preview_markup(nid)
        elif (r["media_file_id"] or ""):
            pmk=ai_news_ready_markup(nid)
        else:
            pmk=ai_news_preview_markup(nid)
        # Til previewini global i18n qatlamidan o'tkazmaymiz.
        # Eski xabarni edit qilish Telegram/client sabab ishlamasa ham, yangi preview aniq chiqadi.
        return await ctx.bot.send_message(
            chat_id=q.message.chat_id,
            text=f"{LANG_NAMES[lang]} Â· #{nid}\n\n{body[:3300]}",
            reply_markup=pmk,
            _skip_i18n=True
        )
    m=re.match(r'news:(redo|edit|cancel|send):(\d+)$',d)
    if not m:return
    action,n=m.group(1),int(m.group(2));r=one("SELECT * FROM ai_news_posts WHERE id=?",(n,))
    if not r:return await q.answer("Topilmadi",show_alert=True)
    if action=='cancel':
        if r['status']!='draft':return await q.answer("Bu yangilik allaqachon yuborilgan yoki bekor qilingan.",show_alert=True)
        await q.answer();execute("UPDATE ai_news_posts SET status='cancelled' WHERE id=? AND status='draft'",(n,));return await _news_edit(q,"âŒ Yangilik bekor qilindi.")
    if action=='edit':
        if r['status']!='draft':return await q.answer("Bu yangilik allaqachon yuborilgan yoki bekor qilingan.",show_alert=True)
        await q.answer();STATE[u.id]={'mode':'ai_news_input','edit_id':n};return await _news_edit(q,f"âœï¸ Yangilik #{n} uchun yangi matnni yuboring.")
    if action=='redo' and r['status']!='draft':
        return await q.answer("Bu yangilik allaqachon yuborilgan yoki bekor qilingan.",show_alert=True)
    if action=='redo':
        await q.answer();await _news_edit(q,"ðŸ¤– AI qayta bezamoqda...")
        try:data=await ai_news_prepare(r['source_text'])
        except Exception:return await _news_edit(q,"âš ï¸ AI qayta tayyorlay olmadi.",reply_markup=ai_news_preview_markup(n))
        execute("UPDATE ai_news_posts SET uz_text=?,ru_text='',en_text='' WHERE id=?",(data['uz'],n));return await _news_edit(q,f"ðŸ“¢ YANGILIK #{n} â€” YANGI PREVIEW\n\n{data['uz'][:3300]}",reply_markup=ai_news_preview_markup(n))
    if action=='send':
        if r['status']!='draft':
            return await q.answer("Bu yangilik allaqachon yuborilgan/bekor qilingan.",show_alert=True)
        changed=execute("UPDATE ai_news_posts SET status='sending' WHERE id=? AND status='draft'",(n,))
        await q.answer("ðŸ“¤ Yuborish boshlandi")
        await _news_edit(q,"ðŸ“¤ BARCHA GURUHLARGA YUBORILMOQDA...")
        try:
            ok,fail=await ai_news_broadcast(ctx,n)
        except Exception as exc:
            log.exception("AI news broadcast failed post=%s",n)
            execute("UPDATE ai_news_posts SET status='draft' WHERE id=?",(n,))
            return await ctx.bot.send_message(u.id,"âš ï¸ Yuborishda xato yuz berdi. Yangilik draft holatiga qaytarildi.\nSabab: "+str(exc)[:500],reply_markup=ai_news_ready_markup(n),_skip_i18n=True)
        return await ctx.bot.send_message(u.id,f"âœ… YANGILIK GURUHLARGA TARQATILDI\n\nðŸ˜ Yetkazilgan guruhlar: {ok}\nâŒ Yetkazilmagan guruhlar: {fail}",_skip_i18n=True)

def main_menu_markup ( uid ) :
    kb=[
      [InlineKeyboardButton ( "ðŸ‘¤ Profil",callback_data="me" ) ,InlineKeyboardButton ( "â­ Hisob",callback_data="wallet" ) ],
      [InlineKeyboardButton ( "ðŸŽ Gift",callback_data="gifts" ) ,InlineKeyboardButton ( "ðŸ’Ž Premium",callback_data="premium" ) ],
      [InlineKeyboardButton ( "ðŸ˜ Guruhlarim",callback_data="mygroups" ) ],
      [InlineKeyboardButton ( "ðŸŒ Global aktiv",callback_data="globalactive" ) ],
      [InlineKeyboardButton ( "ðŸ”Ž Aâ€™zo profili",callback_data="profilefind" ) ,InlineKeyboardButton ( "ðŸ’  Qadr TOP",callback_data="qadrtop" ) ],
      [InlineKeyboardButton ( "ðŸ¤– Veritas AI",callback_data="ai_private" ) ],
      [InlineKeyboardButton ( "ðŸ§© AI Rebus",callback_data="rebus:start" ) ],
      [InlineKeyboardButton ( "ðŸ“š Vasatiya kutubxonasi",callback_data="library" ) ,InlineKeyboardButton ( "ðŸ“œ Sahih Hadislar",callback_data="hadith" ) ],
      [InlineKeyboardButton ( "ðŸ“¨ Egaga xabar qoldirish",callback_data="owner:message" ) ],
      [InlineKeyboardButton ( "ðŸŒ Til / Ð¯Ð·Ñ‹Ðº / Language",callback_data="lang:menu" ) ],
      [InlineKeyboardButton ( "â„¹ï¸ Veritas haqida",callback_data="about" ) ],
    ]
    # AI Yangilik: faqat 2 ta haqiqiy Super Ega asosiy menyusida koâ€˜rinadi.
    if uid in SUPER_OWNERS:
        kb.append([InlineKeyboardButton("ðŸ“¢ Xabar joâ€˜natish", callback_data="news:menu")])
    if is_super ( uid ):
        kb.append ( [InlineKeyboardButton ( "ðŸ‘‘ Super Ega",callback_data="super" ) ])
    return InlineKeyboardMarkup ( kb)

def back_markup ( target="home" ) :
    return InlineKeyboardMarkup ( [[InlineKeyboardButton ( "â¬…ï¸ Orqaga",callback_data=target ) ,InlineKeyboardButton ( "ðŸ  Bosh menyu",callback_data="home" ) ]])

def super_menu_markup ( uid=None ) :
    kb=[
        [InlineKeyboardButton ( "ðŸ‘¥ Kabinetlar",callback_data="cabs:0" ) ],
        [InlineKeyboardButton ( "ðŸ›¡ Barcha adminlar",callback_data="alladmins:0" ) ],
        [InlineKeyboardButton ( "ðŸ˜ Bot ishlayotgan guruhlar",callback_data="botgroups:0" ) ],
    ]
    if uid in SUPER_OWNERS:
        kb.append([InlineKeyboardButton("ðŸ“¸ Chat rasmlari",callback_data="chatshot:list")])
        kb.append([InlineKeyboardButton("ðŸ“¢ AI Yangilik",callback_data="news:menu")])
    kb.append([InlineKeyboardButton ( "â¬…ï¸ Orqaga",callback_data="home" ) ,InlineKeyboardButton ( "ðŸ  Bosh menyu",callback_data="home" ) ])
    return InlineKeyboardMarkup(kb)

def user_total_stats ( uid ) :
    # GLOBAL: foydalanuvchining Veritas ishlayotgan barcha guruhlaridagi natija jamlanadi.
    r=one ( "SELECT COALESCE ( SUM ( xp ) ,0) xp,COALESCE ( SUM ( messages ) ,0) messages FROM members WHERE user_id=?", ( uid, ) )
    return (int ( r["xp"] ) ,int ( r["messages"] ) ) if r else (0,0)

def activity_degree ( lvl ) :
    if lvl >= 251: return "ðŸ¦… Afsona"
    if lvl >= 151: return "âšœï¸ Ustoz darajasi"
    if lvl >= 101: return "ðŸŒŸ Veritas faxri"
    if lvl >= 76: return "ðŸ‘‘ Elita aâ€™zo"
    if lvl >= 51: return "ðŸ† Faollar sardori"
    if lvl >= 31: return "ðŸ’Ž Yuksak faol"
    if lvl >= 21: return "ðŸ”¥ Super Aktiv"
    if lvl >= 11: return "âœ¨ Ilmga intiluvchi"
    if lvl >= 6: return "ðŸ“– Faol aâ€™zo"
    return "ðŸŒ± Ilm izlovchi"

def content_contributions ( uid ) :
    b=one ( "SELECT COUNT(*) n FROM library_books WHERE added_by=? AND status='approved'", ( uid, ) )
    h=one ( "SELECT COUNT(*) n FROM hadiths WHERE added_by=? AND status='approved'", ( uid, ) )
    return int ( b["n"] if b else 0 ),int ( h["n"] if h else 0 )

def knowledge_medal ( books,hadiths ) :
    total=int ( books ) +int ( hadiths )
    if total >=100: return "ðŸ† Ilm fidoyisi"
    if total >=50: return "ðŸŒŸ Ilm elchisi"
    if total >=20: return "ðŸ… Ilm tarqatuvchi"
    if total >=1: return "ðŸ“š Ilm xizmatida"
    return "â€”"

def bot_roles ( uid ) :
    roles=[]
    if uid in SUPER_OWNERS: roles.append ( "ðŸ‘‘ Super Ega" )
    elif is_super_admin ( uid ): roles.append ( "ðŸ›¡ Super Admin" )
    if one ( "SELECT 1 FROM library_admins WHERE user_id=?", ( uid, ) ): roles.append ( "ðŸ“š Kutubxona admini" )
    if one ( "SELECT 1 FROM hadith_admins WHERE user_id=?", ( uid, ) ): roles.append ( "ðŸ“œ Hadis admini" )
    vg=one ( "SELECT COUNT(*) n FROM vadmins WHERE user_id=?", ( uid, ) )
    if vg and int ( vg["n"] ) >0: roles.append ( f"ðŸ›¡ Veritas admini ({int ( vg['n'] )} guruh)" )
    return ", ".join ( roles ) if roles else "Aâ€™zo"

def global_profile_text ( u ) :
    xp,msgs=user_total_stats ( u.id )
    lvl=level ( xp )
    books,hadiths=content_contributions ( u.id )
    ai_until=ai_user_until ( u.id )
    ai_status=( "ðŸ‘‘ Cheksiz (Super boshqaruv)" if is_super ( u.id ) else ( "âœ… FAOL â€” "+fmt_until ( ai_until ) if ai_until>now ( ) else "âŒ YOâ€˜Q" ) )
    return (
        f"ðŸ‘¤ {u.full_name}\n"
        f"ðŸ†” {u.id}\n"
        f"ðŸ›¡ Botdagi roli: {bot_roles ( u.id )}\n"
        f"â­ Kredit: {wallet ( u.id )}\n"
        f"ðŸŒ Umumiy XP: {xp}\n"
        f"ðŸ’¬ Umumiy xabarlar: {msgs}\n"
        f"ðŸ“ˆ Level: {lvl}\n"
        f"ðŸ”¥ Aktivlik darajasi: {activity_degree ( lvl )}\n"
        f"ðŸ“š Qoâ€˜shgan kitoblari: {books} ta\n"
        f"ðŸ“œ Qoâ€˜shgan hadislari: {hadiths} ta\n"
        f"ðŸ… Ilm medali: {knowledge_medal ( books,hadiths )}\n\n"
        f"ðŸ¤– AI Premium: {ai_status}"
    )

def global_active_rows ( limit=10 ) :
    # Global TOP faqat haqiqiy foydalanuvchilar uchun.
    # Telegram botlari/channel senderlari bazada users sifatida saqlanib qolgan boâ€˜lsa ham,
    # @...bot username orqali TOPdan chiqariladi.
    return all_ ( """SELECT m.user_id,SUM ( m.messages ) messages,SUM ( m.xp ) xp,
                     COALESCE ( u.first_name,'' ) first_name,COALESCE ( u.username,'' ) username
                     FROM members m
                     JOIN users u ON u.user_id=m.user_id
                     WHERE LOWER ( COALESCE ( u.username,'' ) ) NOT LIKE '%bot'
                       AND LOWER ( COALESCE ( u.first_name,'' ) ) NOT IN ('channel','anonymous')
                     GROUP BY m.user_id
                     ORDER BY messages DESC,xp DESC,m.user_id ASC LIMIT ?""", ( int ( limit ), ) )

def global_active_text ( limit=10 ) :
    rows=global_active_rows ( limit )
    if not rows: return "ðŸŒ VERITAS â€” GLOBAL AKTIV\n\nHozircha maâ€™lumot yoâ€˜q."
    lines=[]
    medals=["ðŸ¥‡","ðŸ¥ˆ","ðŸ¥‰"]
    for i,r in enumerate ( rows ) :
        mark=medals[i] if i<3 else f"{i+1}."
        lvl=level ( int ( r["xp"] or 0 ) )
        lines.append ( f"{mark} {display_name_row ( r )} â€” {int ( r['messages'] or 0 )} xabar | LVL {lvl} {activity_degree ( lvl )}" )
    return "ðŸŒ VERITAS â€” GLOBAL AKTIV TOP 10\n\n"+"\n".join ( lines )+"\n\nðŸ‘¥ Faqat foydalanuvchilar reytingi.\nðŸ“Š Barcha guruhlardagi aktivlik jamlangan."

def fmt_until ( ts ) :
    if not ts: return "â€”"
    return datetime.fromtimestamp ( int ( ts ),timezone.utc ) .strftime ( "%d.%m.%Y %H:%M UTC" )

def ai_user_until ( uid ) :
    r=one ( "SELECT paid_until FROM ai_user_subscriptions WHERE user_id=?", ( uid, ) )
    return int ( r["paid_until"] ) if r else 0

def ai_user_active ( uid ) :
    return is_super ( uid ) or ai_user_until ( uid ) > now ( )

def ai_group_until ( chat_id ) :
    r=one ( "SELECT paid_until FROM ai_group_subscriptions WHERE chat_id=?", ( chat_id, ) )
    return int ( r["paid_until"] ) if r else 0

def ai_group_active ( chat_id ) :
    return ai_group_until ( chat_id ) > now ( )

def ai_user_trial_used ( uid ) :
    return bool ( one ( "SELECT 1 FROM ai_user_trials WHERE user_id=?", ( uid, ) ) )

def ai_group_trial_used ( chat_id ) :
    return bool ( one ( "SELECT 1 FROM ai_group_trials WHERE chat_id=?", ( chat_id, ) ) )

def claim_ai_user_trial ( uid ) :
    # Bir foydalanuvchiga faqat bir marta. Transaction race-conditionni ham toâ€˜sadi.
    ts=now ( )
    with db ( ) as c:
        try:
            c.execute ( "INSERT INTO ai_user_trials(user_id,claimed_at) VALUES(?,?)", ( uid,ts ) )
        except sqlite3.IntegrityError:
            return 0
        old=c.execute ( "SELECT paid_until FROM ai_user_subscriptions WHERE user_id=?", ( uid, ) ).fetchone ( )
        base=max ( ts,int ( old["paid_until"] ) if old else 0 )
        until=base+30*86400
        c.execute ( "INSERT INTO ai_user_subscriptions(user_id,paid_until,updated_at) VALUES(?,?,?) "
                    "ON CONFLICT(user_id) DO UPDATE SET paid_until=excluded.paid_until,updated_at=excluded.updated_at",
                    ( uid,until,ts ) )
    return until

def claim_ai_group_trial ( chat_id,uid ) :
    # Har bir guruhga faqat bir marta 30 kun bepul.
    ts=now ( )
    with db ( ) as c:
        try:
            c.execute ( "INSERT INTO ai_group_trials(chat_id,claimed_at,claimed_by) VALUES(?,?,?)", ( chat_id,ts,uid ) )
        except sqlite3.IntegrityError:
            return 0
        old=c.execute ( "SELECT paid_until FROM ai_group_subscriptions WHERE chat_id=?", ( chat_id, ) ).fetchone ( )
        base=max ( ts,int ( old["paid_until"] ) if old else 0 )
        until=base+30*86400
        c.execute ( "INSERT INTO ai_group_subscriptions(chat_id,payer_id,paid_until,source,updated_at) VALUES(?,?,?,?,?) "
                    "ON CONFLICT(chat_id) DO UPDATE SET payer_id=excluded.payer_id,paid_until=excluded.paid_until,"
                    "source=excluded.source,updated_at=excluded.updated_at",
                    ( chat_id,uid,until,"trial",ts ) )
    return until

def extend_ai_user ( uid,days ) :
    old=ai_user_until ( uid ); base=max ( now ( ),old ); until=base+int ( days ) *86400
    execute ( "INSERT INTO ai_user_subscriptions ( user_id,paid_until,updated_at) VALUES ( ?,?,? ) ON CONFLICT ( user_id) DO UPDATE SET paid_until=excluded.paid_until,updated_at=excluded.updated_at", ( uid,until,now ( ) ) )
    return until

def extend_ai_group ( chat_id,days,payer_id=0,source="paid" ) :
    old=ai_group_until ( chat_id ); base=max ( now ( ),old ); until=base+int ( days ) *86400
    execute ( "INSERT INTO ai_group_subscriptions ( chat_id,payer_id,paid_until,source,updated_at) VALUES ( ?,?,?,?,? ) ON CONFLICT ( chat_id) DO UPDATE SET payer_id=excluded.payer_id,paid_until=excluded.paid_until,source=excluded.source,updated_at=excluded.updated_at", ( chat_id,payer_id,until,source,now ( ) ) )
    return until

def ai_rate_ok ( scope_id,uid,seconds=5 ) :
    k=(scope_id,uid); t=time.time ( ); last=AI_RATE_CACHE.get ( k,0 )
    if t-last < seconds: return False
    AI_RATE_CACHE[k]=t; return True

def ai_group_menu ( chat_id,uid ) :
    kb=[]
    if not ai_group_trial_used ( chat_id ):
        kb.append ( [InlineKeyboardButton ( "ðŸŽ 30 kun BEPUL",callback_data=f"aigtrial:{chat_id}" ) ] )
    else:
        kb.append ( [InlineKeyboardButton ( "â­ 100 â€” 30 kun",callback_data=f"aigbuy:{chat_id}:30" ) ] )
    if is_super ( uid ):
        kb += [
          [InlineKeyboardButton ( "ðŸ‘‘ Bepul 1 kun",callback_data=f"aigfree:{chat_id}:1" ) ,InlineKeyboardButton ( "ðŸ‘‘ 7 kun",callback_data=f"aigfree:{chat_id}:7" ) ,InlineKeyboardButton ( "ðŸ‘‘ 30 kun",callback_data=f"aigfree:{chat_id}:30" ) ],
          [InlineKeyboardButton ( "â›” AI ni oâ€˜chirish",callback_data=f"aigoff:{chat_id}" ) ]
        ]
    return InlineKeyboardMarkup ( kb )


def is_library_admin ( uid ) :
    return is_super ( uid ) or bool ( one ( "SELECT 1 FROM library_admins WHERE user_id=?", ( uid, )  ) )

def lib_lang_name ( code ) :
    return {"uz":"ðŸ‡ºðŸ‡¿ Oâ€˜zbekcha","ru":"ðŸ‡·ðŸ‡º Ð ÑƒÑÑÐºÐ¸Ð¹","en":"ðŸ‡¬ðŸ‡§ English"}.get ( code,code)

def profile_like_count ( uid ) :
    r=one ( "SELECT COUNT(*) n FROM profile_likes WHERE target_user_id=?", ( uid, ) )
    return int ( r["n"] if r else 0 )


def profile_liked_by ( target_uid,voter_uid ) :
    return bool ( one ( "SELECT 1 FROM profile_likes WHERE target_user_id=? AND voter_user_id=?", ( target_uid,voter_uid ) ) )


def profile_dislike_count ( uid ) :
    r=one ( "SELECT COUNT(*) n FROM profile_dislikes WHERE target_user_id=?", ( uid, ) )
    return int ( r["n"] if r else 0 )


def profile_disliked_by ( target_uid,voter_uid ) :
    return bool ( one ( "SELECT 1 FROM profile_dislikes WHERE target_user_id=? AND voter_user_id=?", ( target_uid,voter_uid ) ) )


def public_profile_text ( uid ) :
    r=one ( "SELECT user_id,username,first_name FROM users WHERE user_id=?", ( uid, ) )
    if not r: return None
    xp,msgs=user_total_stats ( uid )
    lvl=level ( xp )
    shown_lvl="+99" if uid in SUPER_OWNERS else str(lvl)
    books,hadiths=content_contributions ( uid )
    ai_until=ai_user_until ( uid )
    ai_status=( "ðŸ‘‘ Cheksiz (Super boshqaruv)" if is_super ( uid ) else ( "âœ… FAOL â€” "+fmt_until ( ai_until ) if ai_until>now ( ) else "âŒ YOâ€˜Q" ) )
    name=r["first_name"] or ( "@"+r["username"] if r["username"] else f"ID {uid}" )
    username=(" @"+r["username"]) if r["username"] else ""
    return (
        f"ðŸ‘¤ {name}{username}\n"
        f"ðŸ†” {uid}\n"
        f"ðŸ›¡ Botdagi roli: {bot_roles ( uid )}\n"
        f"â­ Kredit: {wallet ( uid )}\n"
        f"ðŸ¤– AI Premium: {ai_status}\n\n"
        f"ðŸŒ Umumiy XP: {xp}\n"
        f"ðŸ’¬ Umumiy xabarlar: {msgs}\n"
        f"ðŸ“ˆ Level: {shown_lvl}\n"
        f"ðŸ”¥ Aktivlik darajasi: {activity_degree ( lvl )}\n"
        f"ðŸ“š Qoâ€˜shgan kitoblari: {books} ta\n"
        f"ðŸ“œ Qoâ€˜shgan hadislari: {hadiths} ta\n"
        f"ðŸ… Ilm medali: {knowledge_medal ( books,hadiths )}\n"
        f"ðŸ’  Qadr: {profile_like_count ( uid )}\n"
        f"âš–ï¸ Eâ€™tiroz: {profile_dislike_count ( uid )}"
    )


def qadr_top_text ( limit=10 ) :
    rows=all_ ( """SELECT u.user_id,u.first_name,u.username,COUNT(pl.voter_user_id) qadr
                    FROM profile_likes pl JOIN users u ON u.user_id=pl.target_user_id
                    GROUP BY u.user_id,u.first_name,u.username
                    ORDER BY qadr DESC,u.user_id ASC LIMIT ?""", ( int(limit), ) )
    if not rows:
        return "ðŸ† VERITAS â€” QADR TOP 10\n\nHozircha Qadr berilmagan."
    medals=["ðŸ¥‡","ðŸ¥ˆ","ðŸ¥‰"]
    lines=["ðŸ† VERITAS â€” QADR TOP 10",""]
    for i,r in enumerate(rows,1):
        mark=medals[i-1] if i<=3 else f"{i}."
        name=r["first_name"] or (("@"+r["username"]) if r["username"] else f"ID {r['user_id']}")
        lines.append(f"{mark} {name} â€” ðŸ’  {int(r['qadr'])} Qadr")
    return "\n".join(lines)


def public_profile_markup ( target_uid,viewer_uid ) :
    liked=profile_liked_by ( target_uid,viewer_uid )
    disliked=profile_disliked_by ( target_uid,viewer_uid )
    like_text=("â†©ï¸ Qadrni olish" if liked else "ðŸ’  Qadr")+f" Â· {profile_like_count ( target_uid )}"
    dislike_text=("â†©ï¸ Eâ€™tirozni olish" if disliked else "âš–ï¸ Eâ€™tiroz")+f" Â· {profile_dislike_count ( target_uid )}"
    kb=[]
    # Like/Dizlayk tugmalari har bir profilda koâ€˜rinadi.
    # Oâ€˜z profilida ham tugmalar koâ€˜rinadi, ammo callback ovoz berishni bloklaydi.
    kb.append ( [
        InlineKeyboardButton ( like_text,callback_data=f"plike:{target_uid}" ),
        InlineKeyboardButton ( dislike_text,callback_data=f"pdislike:{target_uid}" )
    ] )
    kb.append ( [InlineKeyboardButton ( "ðŸ”Ž Boshqa aâ€™zoni topish",callback_data="profilefind" )] )
    kb.append ( [InlineKeyboardButton ( "â¬…ï¸ Orqaga",callback_data="home" ),InlineKeyboardButton ( "ðŸ  Bosh menyu",callback_data="home" )] )
    return InlineKeyboardMarkup ( kb )


async def send_public_profile ( ctx,chat_id,target_uid,viewer_uid,old_message=None ) :
    text=public_profile_text ( target_uid )
    if not text:
        if old_message:
            return await old_message.reply_text ( "âŒ Aâ€™zo topilmadi." )
        return await ctx.bot.send_message ( chat_id,"âŒ Aâ€™zo topilmadi." )
    markup=public_profile_markup ( target_uid,viewer_uid )
    photo_id=None
    try:
        photos=await ctx.bot.get_user_profile_photos ( target_uid,limit=1 )
        if photos.total_count and photos.photos:
            # Eng kichik profil rasmi varianti.
            photo_id=photos.photos[0][0].file_id
    except TelegramError:
        photo_id=None
    if old_message:
        try: await old_message.delete ( )
        except TelegramError: pass
    if photo_id:
        return await ctx.bot.send_photo ( chat_id,photo=photo_id,caption=text[:1024],reply_markup=markup )
    return await ctx.bot.send_message ( chat_id,text,reply_markup=markup )


def library_home_markup ( uid ) :
    kb=[
      [InlineKeyboardButton ( "ðŸ¤– AI Kitob qidirish",callback_data="libaisearch" ) ],
      [InlineKeyboardButton ( "ðŸ”Ž Oddiy qidirish",callback_data="libsearch" ) ,InlineKeyboardButton ( "ðŸ—‚ Kategoriyalar",callback_data="libcats:0" ) ],
      [InlineKeyboardButton ( "ðŸ†• Yangi kitoblar",callback_data="libnew:0" ) ,InlineKeyboardButton ( "â¤ï¸ Sevimlilar",callback_data="libfav:0" ) ],
      [InlineKeyboardButton ( "ðŸ‡ºðŸ‡¿",callback_data="liblang:uz:0" ) ,InlineKeyboardButton ( "ðŸ‡·ðŸ‡º",callback_data="liblang:ru:0" ) ,InlineKeyboardButton ( "ðŸ‡¬ðŸ‡§",callback_data="liblang:en:0" ) ],
    ]
    if is_library_admin ( uid ) :
        kb.append ( [InlineKeyboardButton ( "âž• Kitob qoâ€˜shish",callback_data="libadd" ) ])
    kb.append ( [InlineKeyboardButton ( "â¬…ï¸ Orqaga",callback_data="home" ) ,InlineKeyboardButton ( "ðŸ  Bosh menyu",callback_data="home" ) ])
    return InlineKeyboardMarkup ( kb)

def library_book_categories ( book_id ) :
    rows=all_ ( """SELECT c.name FROM library_categories c
                 JOIN library_book_categories bc ON bc.category_id=c.id
                 WHERE bc.book_id=? ORDER BY c.name""", ( book_id, ) )
    return [r["name"] for r in rows]

def library_book_text ( r ) :
    cats=library_book_categories ( r["id"])
    uploader=one ( "SELECT first_name,username FROM users WHERE user_id=?", ( r["added_by"], ) )
    added= ( uploader["first_name"] if uploader and uploader["first_name"] else str ( r["added_by"] ) )
    if uploader and uploader["username"]: added += " @"+uploader["username"]
    return (f"ðŸ“– {r['title']}\n"
            f"âœï¸ Muallif: {r['author'] or 'â€”'}\n"
            f"ðŸŒ Til: {lib_lang_name ( r['lang'] ) }\n"
            f"ðŸ—‚ Kategoriya: {', '.join ( cats) if cats else 'â€”'}\n"
            f"ðŸ‘¤ Qoâ€˜shgan: {added}\n"
            f"ðŸ‘ Koâ€˜rildi: {r['views']} | â¬‡ï¸ Yuklandi: {r['downloads']}\n\n"
            f"{r['description'] or 'Tavsif mavjud emas.'}")

def library_book_markup ( uid,book_id,back="library" ) :
    fav=bool ( one ( "SELECT 1 FROM library_favorites WHERE user_id=? AND book_id=?", ( uid,book_id )  ) )
    r=one ( "SELECT pdf_file_id,audio_file_id,book_file_id,book_format FROM library_books WHERE id=?", ( book_id, ) )
    kb=[]
    row=[]
    if r and (r["book_file_id"] or r["pdf_file_id"]): row.append ( InlineKeyboardButton ( "ðŸ“¥ Kitobni olish",callback_data=f"libfile:{book_id}" ) )
    if r and r["audio_file_id"]: row.append ( InlineKeyboardButton ( "ðŸŽ§ Audio",callback_data=f"libaudio:{book_id}" ) )
    if row: kb.append ( row)
    if r and r["pdf_file_id"]:
        kb.append ( [InlineKeyboardButton ( "ðŸ§  Test tuzish",callback_data=f"libquiz:{book_id}" ) ])
        kb.append ( [InlineKeyboardButton ( "ðŸŒ AI Tarjima",callback_data=f"libtranslate:{book_id}" ) ])
    kb.append ( [InlineKeyboardButton ( "ðŸ’” Sevimlidan olish" if fav else "â¤ï¸ Sevimliga",callback_data=f"libfavtoggle:{book_id}" ) ])
    if is_library_admin ( uid ) :
        kb.append ( [InlineKeyboardButton ( "âœï¸ Tahrirlash",callback_data=f"libedit:{book_id}" ) ,InlineKeyboardButton ( "ðŸ—‘ Oâ€˜chirish",callback_data=f"libdelask:{book_id}" ) ])
    kb.append ( [InlineKeyboardButton ( "â¬…ï¸ Kutubxona",callback_data=back ) ,InlineKeyboardButton ( "ðŸ  Bosh menyu",callback_data="home" ) ])
    return InlineKeyboardMarkup ( kb)

async def library_show_book ( q,ctx,book_id,back="library" ) :
    r=one ( "SELECT * FROM library_books WHERE id=? AND status='approved'", ( book_id, ) )
    if not r: return await q.edit_message_text ( "âŒ Kitob topilmadi.",reply_markup=back_markup ( "library" ) )
    execute ( "UPDATE library_books SET views=views+1 WHERE id=?", ( book_id, ) )
    r=one ( "SELECT * FROM library_books WHERE id=?", ( book_id, ) )
    text=library_book_text ( r)
    if r["cover_file_id"]:
        try:
            await q.message.delete ( )
            return await ctx.bot.send_photo ( q.message.chat.id,r["cover_file_id"],caption=text[:1024],reply_markup=library_book_markup ( q.from_user.id,book_id,back ) )
        except Exception: pass
    return await q.edit_message_text ( text,reply_markup=library_book_markup ( q.from_user.id,book_id,back ) )

def library_list_markup ( rows,page,prefix,total,extra="" ) :
    per=8; kb=[]
    for r in rows:
        title= ( r["title"] or "Nomsiz" ) [:38]
        kb.append ( [InlineKeyboardButton ( "ðŸ“– "+title,callback_data=f"libbook:{r['id']}" ) ])
    nav=[]
    if page>0: nav.append ( InlineKeyboardButton ( "â—€ï¸",callback_data=f"{prefix}:{extra+':' if extra else ''}{page-1}" ) )
    if (page+1 ) *per<total: nav.append ( InlineKeyboardButton ( "â–¶ï¸",callback_data=f"{prefix}:{extra+':' if extra else ''}{page+1}" ) )
    if nav: kb.append ( nav)
    kb.append ( [InlineKeyboardButton ( "â¬…ï¸ Kutubxona",callback_data="library" ) ,InlineKeyboardButton ( "ðŸ  Bosh menyu",callback_data="home" ) ])
    return InlineKeyboardMarkup ( kb)


def _compact(s, n=180):
    return re.sub(r"\s+"," ",str(s or "")).strip()[:n]

def _ids_from_ai(text, allowed):
    found=[]
    for x in re.findall(r"\b\d+\b", text or ""):
        i=int(x)
        if i in allowed and i not in found:
            found.append(i)
    return found[:8]

async def ai_library_search(query):
    """AI may rank only rows that actually exist in Vasatiya library."""
    rows=all_("""SELECT b.id,b.title,b.author,b.description,b.lang,
                       COALESCE(GROUP_CONCAT(c.name, ', '),'') cats
                FROM library_books b
                LEFT JOIN library_book_categories bc ON bc.book_id=b.id
                LEFT JOIN library_categories c ON c.id=bc.category_id
                WHERE b.status='approved'
                GROUP BY b.id ORDER BY b.id DESC LIMIT 1200""")
    if not rows: return []
    q=(query or "").strip().lower()
    words=[w for w in re.findall(r"[\wÊ»â€™'-]+",q,re.U) if len(w)>2]
    scored=[]
    for r in rows:
        hay=" ".join([r["title"] or "",r["author"] or "",r["description"] or "",r["cats"] or ""]).lower()
        score=sum(5 if w in (r["title"] or "").lower() else 2 if w in hay else 0 for w in words)
        if score: scored.append((score,r))
    scored.sort(key=lambda x:(-x[0],-int(x[1]["id"])))
    # Give AI a real catalog, never open web/external books.
    pool=[x[1] for x in scored[:120]]
    if len(pool)<80:
        seen={int(r["id"]) for r in pool}
        for r in rows:
            if int(r["id"]) not in seen:
                pool.append(r); seen.add(int(r["id"]))
            if len(pool)>=160: break
    if OPENAI_API_KEY:
        catalog="\n".join(
            f"ID={r['id']} | { _compact(r['title'],90) } | { _compact(r['author'],55) } | "
            f"{ _compact(r['cats'],55) } | { _compact(r['description'],120) }"
            for r in pool
        )
        prompt=(
            "Vazifa: foydalanuvchi soâ€˜roviga mos kitoblarni FAQAT quyidagi Vasatiya katalogidan tanla. "
            "Katalogda yoâ€˜q kitobni uydirma. Eng mos 1-8 ta kitob ID sini moslik tartibida qaytar. "
            "Javob formati faqat vergul bilan IDlar, masalan: 12,5,91. Mos kitob boâ€˜lmasa NONE.\n\n"
            f"Soâ€˜rov: {query}\n\nKATALOG:\n{catalog}"
        )
        try:
            ans=await asyncio.to_thread(_openai_response_sync,prompt)
            ids=_ids_from_ai(ans,{int(r["id"]) for r in pool})
            if ids:
                byid={int(r["id"]):r for r in rows}
                return [byid[i] for i in ids if i in byid]
        except Exception:
            log.exception("AI library search failed; lexical fallback used")
    return [r for _,r in scored[:8]]

async def ai_hadith_search(query):
    """AI may rank only hadiths stored in Veritas hadith DB."""
    rows=all_("""SELECT id,collection,number,translation,explanation,source
                 FROM hadiths WHERE status='approved'
                 ORDER BY id DESC LIMIT 1600""")
    if not rows: return []
    q=(query or "").strip().lower()
    words=[w for w in re.findall(r"[\wÊ»â€™'-]+",q,re.U) if len(w)>2]
    scored=[]
    for r in rows:
        hay=" ".join([r["collection"] or "",str(r["number"]),r["translation"] or "",r["explanation"] or "",r["source"] or ""]).lower()
        score=sum(3 if w in hay else 0 for w in words)
        if score: scored.append((score,r))
    scored.sort(key=lambda x:(-x[0],-int(x[1]["id"])))
    pool=[x[1] for x in scored[:140]]
    if len(pool)<100:
        seen={int(r["id"]) for r in pool}
        for r in rows:
            if int(r["id"]) not in seen:
                pool.append(r); seen.add(int(r["id"]))
            if len(pool)>=180: break
    if OPENAI_API_KEY:
        catalog="\n".join(
            f"ID={r['id']} | { _compact(r['collection'],35) } {r['number']} | "
            f"{ _compact(r['translation'],150) } | { _compact(r['explanation'],90) }"
            for r in pool
        )
        prompt=(
            "Vazifa: foydalanuvchi mavzusiga mos hadislarni FAQAT quyidagi Veritas hadis bazasidan tanla. "
            "Tashqaridan hadis keltirma, raqam yoki matn uydirma. Eng mos 1-8 ta IDni qaytar. "
            "Format faqat IDlar vergul bilan. Mos kelmasa NONE.\n\n"
            f"Soâ€˜rov: {query}\n\nHADIS BAZASI:\n{catalog}"
        )
        try:
            ans=await asyncio.to_thread(_openai_response_sync,prompt)
            ids=_ids_from_ai(ans,{int(r["id"]) for r in pool})
            if ids:
                byid={int(r["id"]):r for r in rows}
                return [byid[i] for i in ids if i in byid]
        except Exception:
            log.exception("AI hadith search failed; lexical fallback used")
    return [r for _,r in scored[:8]]

async def send_ai_library_results(msg, query):
    rows=await ai_library_search(query)
    if not rows:
        return await msg.reply_text(
            "ðŸ¤– Vasatiya AI bu soâ€˜rovga mos kitobni oâ€˜z kutubxonamizdan topmadi.\n"
            "Boshqa kalit soâ€˜z yoki mavzu bilan urinib koâ€˜ring.",
            reply_markup=library_home_markup(msg.from_user.id)
        )
    kb=[]
    for r in rows[:8]:
        title=_compact(r["title"],42)
        author=_compact(r["author"],24)
        label=f"ðŸ“– {title}" + (f" â€” {author}" if author else "")
        kb.append([InlineKeyboardButton(label,callback_data=f"libbook:{r['id']}")])
    kb.append([InlineKeyboardButton("ðŸ¤– Yana AI qidiruv",callback_data="libaisearch"),
               InlineKeyboardButton("ðŸ“š Kutubxona",callback_data="library")])
    return await msg.reply_text(
        f"ðŸ¤– VASATIYA AI QIDIRUV\n\nðŸ”Ž Soâ€˜rov: {query}\n"
        f"ðŸ“š Faqat Vasatiya kutubxonasidagi kitoblardan {len(rows[:8])} ta mos natija:",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def send_ai_hadith_results(msg, query):
    rows=await ai_hadith_search(query)
    if not rows:
        return await msg.reply_text(
            "ðŸ¤– AI bu mavzuga mos hadisni faqat biz qoâ€˜shgan hadislar orasidan topmadi.",
            reply_markup=back_markup("hadith")
        )
    kb=[]
    for r in rows[:8]:
        kb.append([InlineKeyboardButton(
            f"ðŸ“œ {r['collection']} â€” {r['number']}",
            callback_data=f"hshow:{r['id']}"
        )])
    kb.append([InlineKeyboardButton("ðŸ¤– Yana AI qidiruv",callback_data="hadaisearch"),
               InlineKeyboardButton("ðŸ“œ Hadislar",callback_data="hadith")])
    return await msg.reply_text(
        f"ðŸ¤– AI HADIS QIDIRUV\n\nðŸ”Ž Mavzu: {query}\n"
        f"ðŸ“œ Faqat Veritas bazasidagi hadislardan {len(rows[:8])} ta mos natija:",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def library_private_input ( update,ctx ) :
    if ctx.user_data.get("news_consumed_message_id")==getattr(update.effective_message,"message_id",None):return
    if ctx.user_data.get("bayram_consumed_message_id")==getattr(update.effective_message,"message_id",None):return
    if update.effective_chat.type!="private": return
    uid=update.effective_user.id; st=STATE.get ( uid)
    if st: ctx.user_data["workflow_message_id"]=update.effective_message.message_id
    if st and str ( st.get ( "mode","" )  ) .startswith ( "had_" ) :
        return await hadith_private_input ( update,ctx)
    if st and st.get("mode")=="profile_find":
        msg=update.effective_message
        if not msg.text: return await msg.reply_text("Aâ€™zoning @username yoki Telegram ID sini yozing.")
        value=msg.text.strip(); target_uid=0
        if value.isdigit():
            target_uid=int(value)
        elif value.startswith("@"):
            r=one("SELECT user_id FROM users WHERE lower(username)=lower(?)",(value[1:],))
            target_uid=int(r["user_id"]) if r else 0
        if not target_uid or not one("SELECT 1 FROM users WHERE user_id=?",(target_uid,)):
            return await msg.reply_text("âŒ Veritas bazasida bunday aâ€™zo topilmadi.")
        STATE.pop(uid,None)
        return await send_public_profile(ctx,msg.chat.id,target_uid,uid)

    if st and st.get("mode")=="lib_ai_search":
        msg=update.effective_message
        if not msg.text: return await msg.reply_text("ðŸ”Ž Qidirayotgan kitob mavzusini matn qilib yozing.")
        query=msg.text.strip()
        if len(query)<2: return await msg.reply_text("Soâ€˜rov juda qisqa.")
        STATE.pop(uid,None)
        await msg.reply_text("ðŸ¤– Vasatiya AI kutubxonamiz ichidan qidirmoqda...")
        return await send_ai_library_results(msg,query)

    if st and st.get("mode")=="had_ai_search":
        msg=update.effective_message
        if not msg.text: return await msg.reply_text("ðŸ”Ž Hadis mavzusini matn qilib yozing.")
        query=msg.text.strip()
        if len(query)<2: return await msg.reply_text("Soâ€˜rov juda qisqa.")
        STATE.pop(uid,None)
        await msg.reply_text("ðŸ¤– AI faqat Veritasga qoâ€˜shilgan hadislar ichidan qidirmoqda...")
        return await send_ai_hadith_results(msg,query)
    if st and str(st.get("mode","")).startswith("rebus_"):
        msg=update.effective_message
        mode=st["mode"]
        if not msg.text:
            return await msg.reply_text("Matn koâ€˜rinishida yuboring.")
        value=msg.text.strip()
        if mode=="rebus_group_count":
            if not value.isdigit():
                return await msg.reply_text("âŒ Son yozing. Masalan: 5 yoki 10")
            count=int(value)
            if count<1 or count>20:
                return await msg.reply_text("âŒ 1 dan 20 tagacha rebus tanlang.")
            st["count"]=count
            st["answers"]=[]
            st["mode"]="rebus_group_answers"
            return await msg.reply_text(
                f"âœ… {count} ta rebus.\n\n1/{count}-rebusning JAVOBINI yozing.\nMasalan: OLMA"
            )

        if mode=="rebus_group_answers":
            if len(value)>120:
                return await msg.reply_text("âŒ Javob juda uzun. 120 belgidan qisqa yozing.")
            answers=st.setdefault("answers",[])
            answers.append(value)
            count=int(st["count"])
            if len(answers)<count:
                return await msg.reply_text(
                    f"âœ… Qabul qilindi.\n\n{len(answers)+1}/{count}-rebusning JAVOBINI yozing."
                )

            group_id=int(st["group_id"])
            target_chat_id=int(st["target_chat_id"])
            answers=list(answers)
            with db() as c:
                cur=c.execute(
                    "INSERT INTO rebus_sessions(creator_id,group_id,target_chat_id,total,current_no,status,created_at) "
                    "VALUES(?,?,?,?,0,'active',?)",
                    (uid,group_id,target_chat_id,count,now())
                )
                session_id=cur.lastrowid
                for n,ans in enumerate(answers,1):
                    c.execute(
                        "INSERT INTO rebus_session_items(session_id,item_no,answer,status) VALUES(?,?,?,'waiting')",
                        (session_id,n,ans)
                    )
            STATE.pop(uid,None)
            await msg.reply_text(
                f"âœ… {count} ta javob qabul qilindi.\n\nðŸŽ¨ 1/{count}-rebus tayyorlanmoqda. "
                "Birinchisi topilgach, keyingisi avtomatik chiqadi."
            )
            task=asyncio.create_task(_launch_session_item(ctx,session_id,1))
            def _first_rebus_done(t):
                try: t.result()
                except asyncio.CancelledError: pass
                except Exception: log.exception("First rebus task failed")
            task.add_done_callback(_first_rebus_done)
            return
        if mode=="rebus_channel":
            try:
                raw=value.strip()
                # t.me/kanal_nomi, https://t.me/kanal_nomi yoki @kanal_nomi qabul qilinadi.
                m=re.fullmatch(r"(?:https?://)?(?:www\.)?t\.me/([A-Za-z0-9_]{5,})(?:/)?(?:\?.*)?",raw,re.I)
                if m:
                    target="@"+m.group(1)
                elif re.fullmatch(r"-?\d+",raw):
                    target=int(raw)
                else:
                    target=raw if raw.startswith("@") else "@"+raw.lstrip("@")
                ch=await ctx.bot.get_chat(target)
                if ch.type!="channel":
                    return await msg.reply_text("âŒ Bu kanal emas. Kanal @username yoki -100... ID yuboring.")
                me=await ctx.bot.get_chat_member(ch.id,ctx.bot.id)
                if me.status not in (ChatMemberStatus.ADMINISTRATOR,ChatMemberStatus.OWNER):
                    return await msg.reply_text("âŒ Veritas bu kanalda admin emas. Avval botni kanalga admin qiling.")
                linked=getattr(ch,"linked_chat_id",None)
                st["channel_id"]=ch.id
                st["channel_title"]=ch.title or str(ch.id)
                if linked:
                    try:
                        gr=await ctx.bot.get_chat(linked)
                        st["group_id"]=gr.id
                        st["group_title"]=gr.title or str(gr.id)
                        st["mode"]="rebus_topic"
                        return await msg.reply_text(
                            f"âœ… Kanal: {st['channel_title']}\nðŸ‘¥ Javob guruhi: {st['group_title']}\n\n"
                            "Endi rebus javobi boâ€˜ladigan soâ€˜z/ibora yoki mavzuni yozing.\n"
                            "Masalan: KITOB yoki Islom tarixi"
                        )
                    except TelegramError:
                        pass
                st["mode"]="rebus_group"
                return await msg.reply_text(
                    "âœ… Kanal qabul qilindi.\n\nBu kanalga bogâ€˜langan muhokama guruhini topmadim.\n"
                    "Javob tekshiriladigan guruhning @username yoki -100... ID sini yuboring."
                )
            except TelegramError:
                return await msg.reply_text("âŒ Kanal topilmadi. Kanal linkini tekshiring va Veritas botni kanalga admin qiling.")
        if mode=="rebus_group":
            try:
                target=int(value) if re.fullmatch(r"-?\d+",value) else value
                gr=await ctx.bot.get_chat(target)
                if gr.type not in ("group","supergroup"):
                    return await msg.reply_text("âŒ Bu guruh emas.")
                member=await ctx.bot.get_chat_member(gr.id,ctx.bot.id)
                if member.status not in (ChatMemberStatus.ADMINISTRATOR,ChatMemberStatus.OWNER):
                    return await msg.reply_text("âŒ Veritas bu guruhda ishlamayapti.")
                st["group_id"]=gr.id
                st["group_title"]=gr.title or str(gr.id)
                st["mode"]="rebus_topic"
                return await msg.reply_text(
                    f"ðŸ‘¥ Javob guruhi: {st['group_title']}\n\n"
                    "Endi rebus javobi boâ€˜ladigan soâ€˜z/ibora yoki mavzuni yozing."
                )
            except TelegramError:
                return await msg.reply_text("âŒ Guruh topilmadi. Veritas guruhda boâ€˜lishi kerak.")
        if mode=="rebus_topic":
            channel_id=st["channel_id"]; group_id=st["group_id"]
            execute(
                "INSERT INTO rebus_channels(owner_id,channel_id,channel_title,answer_group_id,answer_group_title,updated_at) "
                "VALUES(?,?,?,?,?,?) ON CONFLICT(owner_id) DO UPDATE SET channel_id=excluded.channel_id,"
                "channel_title=excluded.channel_title,answer_group_id=excluded.answer_group_id,"
                "answer_group_title=excluded.answer_group_title,updated_at=excluded.updated_at",
                (uid,channel_id,st.get("channel_title",""),group_id,st.get("group_title",""),now())
            )
            STATE.pop(uid,None)
            await msg.reply_text("ðŸŽ¨ AI rebus tayyorlayapti...\nBotdan foydalanishda davom etishingiz mumkin.")
            task=asyncio.create_task(_create_and_post_rebus(ctx,uid,channel_id,group_id,value,msg.chat.id))
            def _rebus_done(t):
                try: t.result()
                except asyncio.CancelledError: pass
                except Exception: log.exception("Rebus background task failed")
            task.add_done_callback(_rebus_done)
            return
        return
    if not st or not str ( st.get ( "mode","" )  ) .startswith ( "lib_" ) : return
    msg=update.effective_message
    mode=st["mode"]
    if mode=="lib_search":
        if not msg.text: return await msg.reply_text ( "ðŸ”Ž Qidiruv uchun matn yuboring.")
        q=msg.text.strip (  ) ; STATE.pop ( uid,None)
        rows=all_ ( """SELECT * FROM library_books WHERE status='approved' AND
                     (title LIKE ? OR author LIKE ? OR description LIKE ?)
                     ORDER BY id DESC LIMIT 20""", ( f"%{q}%",f"%{q}%",f"%{q}%" ) )
        kb=[[InlineKeyboardButton ( "ðŸ“– "+r["title"][:38],callback_data=f"libbook:{r['id']}" ) ] for r in rows]
        kb.append ( [InlineKeyboardButton ( "â¬…ï¸ Kutubxona",callback_data="library" ) ])
        return await msg.reply_text ( f"ðŸ”Ž Â«{q}Â» boâ€˜yicha: {len ( rows ) } ta natija",reply_markup=InlineKeyboardMarkup ( kb ) )
    if not is_library_admin ( uid ) :
        STATE.pop ( uid,None ) ; return await msg.reply_text ( "â›” Kutubxona boshqaruv huquqi yoâ€˜q.")
    data=st.setdefault ( "data",{})
    if mode.startswith ( "lib_edit_" ) :
        bid=int ( data.get ( "book_id",0 ) )
        if not bid or not one ( "SELECT 1 FROM library_books WHERE id=? AND status='approved'", ( bid, ) ) :
            STATE.pop ( uid,None ) ; return await msg.reply_text ( "âŒ Kitob topilmadi." )
        field=mode[9:]
        if field=="title":
            if not msg.text: return await msg.reply_text ( "Yangi kitob nomini matn qilib yuboring." )
            execute ( "UPDATE library_books SET title=? WHERE id=?", ( msg.text.strip ( ) [:250],bid ) )
        elif field=="author":
            if not msg.text: return await msg.reply_text ( "Yangi muallif nomini matn qilib yuboring." )
            execute ( "UPDATE library_books SET author=? WHERE id=?", ( msg.text.strip ( ) [:250],bid ) )
        elif field=="categories":
            if not msg.text: return await msg.reply_text ( "Kategoriyalarni vergul bilan yuboring." )
            cats=[x.strip ( ) [:80] for x in msg.text.split ( "," ) if x.strip ( ) ][:10]
            with db ( ) as c:
                c.execute ( "DELETE FROM library_book_categories WHERE book_id=?", ( bid, ) )
                for cat in cats:
                    c.execute ( "INSERT OR IGNORE INTO library_categories ( name) VALUES ( ? ) ", ( cat, ) )
                    cr=c.execute ( "SELECT id FROM library_categories WHERE name=? COLLATE NOCASE", ( cat, ) ).fetchone ( )
                    c.execute ( "INSERT OR IGNORE INTO library_book_categories ( book_id,category_id) VALUES ( ?,? ) ", ( bid,cr["id"] ) )
        elif field=="description":
            if not msg.text: return await msg.reply_text ( "Yangi tavsifni matn qilib yuboring." )
            execute ( "UPDATE library_books SET description=? WHERE id=?", ( msg.text.strip ( ) [:3000],bid ) )
        elif field=="cover":
            if msg.photo: fid=msg.photo[-1].file_id
            elif msg.text and msg.text.casefold ( ).replace ( "â€˜","'" ).replace ( "â€™","'" ) in {"o'chirish","ochirish","o'tkazish","otkazish"}: fid=""
            else: return await msg.reply_text ( "ðŸ–¼ Yangi rasm yuboring. Muqovani olib tashlash uchun Â«oâ€˜chirishÂ» yozing." )
            execute ( "UPDATE library_books SET cover_file_id=? WHERE id=?", ( fid,bid ) )
        elif field=="pdf":
            if not msg.document:
                return await msg.reply_text ( "ðŸ“„ Yangi kitob faylini Document sifatida yuboring.\nPDF, EPUB, DOCX, TXT, FB2, MOBI yoki DJVU." )
            doc=msg.document; name=(doc.file_name or "").lower ( ).strip ( )
            allowed=(".pdf",".epub",".docx",".txt",".fb2",".mobi",".djvu")
            if not name.endswith(allowed):
                return await msg.reply_text ( "âŒ Format qabul qilinmaydi.\nPDF, EPUB, DOCX, TXT, FB2, MOBI yoki DJVU yuboring." )
            uniq=doc.file_unique_id or ""
            dup=one ( "SELECT id FROM library_books WHERE pdf_unique_id=? AND id<>? AND status<>'deleted'", ( uniq,bid ) ) if uniq else None
            if dup: return await msg.reply_text ( f"âš ï¸ Bu fayl boshqa kitobda mavjud. ID: {dup['id']}" )
            fmt=name.rsplit(".",1)[-1] if "." in name else "file"
            execute ( """UPDATE library_books
                         SET pdf_file_id=?,pdf_unique_id=?,book_file_id=?,book_unique_id=?,
                             book_file_name=?,book_format=?,book_file_size=?
                         WHERE id=?""",
                      ( doc.file_id,uniq,doc.file_id,uniq,doc.file_name or "",fmt,int(doc.file_size or 0),bid ) )
        elif field=="audio":
            af=None
            if msg.audio: af=msg.audio
            elif msg.voice: af=msg.voice
            elif msg.document:
                d=msg.document; name=(d.file_name or "").lower ( ); mime=(d.mime_type or "").lower ( )
                if mime.startswith ( "audio/" ) or name.endswith ( ( ".mp3",".m4a",".m4b",".aac",".ogg",".opus",".wav",".flac",".wma" ) ): af=d
            if msg.text and msg.text.casefold ( ).replace ( "â€˜","'" ).replace ( "â€™","'" ) in {"o'chirish","ochirish","o'tkazish","otkazish"}:
                execute ( "UPDATE library_books SET audio_file_id='',audio_unique_id='' WHERE id=?", ( bid, ) )
            elif af:
                execute ( "UPDATE library_books SET audio_file_id=?,audio_unique_id=? WHERE id=?", ( af.file_id,af.file_unique_id or "",bid ) )
            else: return await msg.reply_text ( "ðŸŽ§ Yangi audio/voice/audio-fayl yuboring. Olib tashlash uchun Â«oâ€˜chirishÂ» yozing." )
        else: return
        STATE.pop ( uid,None ) ; audit ( uid,0,"library_edit",f"{bid}:{field}" )
        return await msg.reply_text ( "âœ… Kitob maâ€™lumoti yangilandi.",reply_markup=InlineKeyboardMarkup ( [[InlineKeyboardButton ( "ðŸ“– Kitobni ochish",callback_data=f"libbook:{bid}" ) ,InlineKeyboardButton ( "ðŸ“š Kutubxona",callback_data="library" ) ]] ) )
    if mode=="lib_quick_file":
        doc=msg.document
        if not doc:
            return await msg.reply_text(
                "ðŸ“Ž Kitob faylini Document/Fayl sifatida yuboring.\n\n"
                "Qabul qilinadi: PDF, EPUB, DOCX, TXT, FB2, MOBI, DJVU."
            )
        filename=(doc.file_name or "Nomsiz kitob").strip()
        low=filename.lower()
        allowed=(".pdf",".epub",".docx",".txt",".fb2",".mobi",".djvu")
        if not low.endswith(allowed):
            return await msg.reply_text(
                "âŒ Bu format hozir kutubxona uchun qabul qilinmaydi.\n"
                "PDF, EPUB, DOCX, TXT, FB2, MOBI yoki DJVU yuboring."
            )
        uniq=doc.file_unique_id or ""
        if uniq:
            dup=one("SELECT id,title FROM library_books WHERE pdf_unique_id=? AND status<>'deleted'", (uniq,))
            if dup:
                STATE.pop(uid,None)
                return await msg.reply_text(
                    f"âš ï¸ Bu fayl kutubxonada avval qoâ€˜shilgan.\nðŸ“– {dup['title']}\nID: {dup['id']}",
                    reply_markup=library_home_markup(uid)
                )

        # Fayl nomidan kitob nomini avtomatik chiqaramiz.
        title=re.sub(r"\.(pdf|epub|docx|txt|fb2|mobi|djvu)$", "", filename, flags=re.I)
        title=title.replace("_"," ").replace("-"," ")
        title=re.sub(r"\s+"," ",title).strip()[:250] or "Nomsiz kitob"

        with db() as c:
            cur=c.execute(
                """INSERT INTO library_books
                (title,author,lang,description,cover_file_id,pdf_file_id,pdf_unique_id,
                 audio_file_id,audio_unique_id,added_by,status,created_at,
                 book_file_id,book_unique_id,book_file_name,book_format,book_file_size)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (title,"","uz","","",doc.file_id,uniq,"","",uid,"approved",now(),
                 doc.file_id,uniq,filename,filename.rsplit(".",1)[-1].lower() if "." in filename else "file",
                 int(doc.file_size or 0))
            )
            bid=cur.lastrowid

        STATE.pop(uid,None)
        audit(uid,0,"library_add_quick",str(bid))
        kb=InlineKeyboardMarkup([
            [InlineKeyboardButton("âœï¸ Nomi / muallif / kategoriya", callback_data=f"libedit:{bid}")],
            [InlineKeyboardButton("ðŸ“– Kitobni ochish", callback_data=f"libbook:{bid}"),
             InlineKeyboardButton("âž• Yana kitob", callback_data="libadd")],
            [InlineKeyboardButton("ðŸ“š Kutubxona", callback_data="library")]
        ])
        return await msg.reply_text(
            "âœ… KITOB QOâ€˜SHILDI\n\n"
            f"ðŸ“– Nomi avtomatik: {title}\n"
            f"ðŸ“Ž Fayl: {filename}\n\n"
            "Kerak boâ€˜lsa pastdagi âœï¸ tugma orqali nomi, muallifi, tili, "
            "kategoriyasi, tavsifi yoki muqovasini tahrirlang.",
            reply_markup=kb
        )

    if mode=="lib_add_title":
        if not msg.text: return await msg.reply_text ( "Kitob nomini matn qilib yuboring.")
        data["title"]=msg.text.strip (  ) [:250]; st["mode"]="lib_add_author"
        return await msg.reply_text ( "âœï¸ Muallif nomini yuboring:")
    if mode=="lib_add_author":
        if not msg.text: return await msg.reply_text ( "Muallif nomini matn qilib yuboring.")
        data["author"]=msg.text.strip (  ) [:250]
        dup=one ( "SELECT id FROM library_books WHERE lower ( title ) =lower ( ?) AND lower ( author ) =lower ( ?) AND status<>'deleted'", ( data["title"],data["author"] ) )
        if dup:
            STATE.pop ( uid,None ) ; return await msg.reply_text ( f"âš ï¸ Bu kitob kutubxonada mavjud. ID: {dup['id']}",reply_markup=library_home_markup ( uid ) )
        st["mode"]="lib_add_lang"
        kb=InlineKeyboardMarkup ( [[InlineKeyboardButton ( "ðŸ‡ºðŸ‡¿ Oâ€˜zbekcha",callback_data="libaddlang:uz" ) ,InlineKeyboardButton ( "ðŸ‡·ðŸ‡º Ð ÑƒÑÑÐºÐ¸Ð¹",callback_data="libaddlang:ru" ) ,InlineKeyboardButton ( "ðŸ‡¬ðŸ‡§ English",callback_data="libaddlang:en" ) ]])
        return await msg.reply_text ( "ðŸŒ Kitob tilini tanlang:",reply_markup=kb)
    if mode=="lib_add_categories":
        if not msg.text: return await msg.reply_text ( "Kategoriyalarni matn qilib yuboring.")
        data["categories"]=[x.strip (  ) [:80] for x in msg.text.split ( ",") if x.strip (  ) ][:10]
        st["mode"]="lib_add_description"
        return await msg.reply_text ( "ðŸ“ Kitob tavsifini yuboring:")
    if mode=="lib_add_description":
        if not msg.text: return await msg.reply_text ( "Tavsifni matn qilib yuboring.")
        data["description"]=msg.text.strip (  ) [:3000]; st["mode"]="lib_add_cover"
        return await msg.reply_text ( "ðŸ–¼ Muqova rasmini yuboring. Muqova boâ€˜lmasa: o'tkazish")
    if mode=="lib_add_cover":
        if msg.photo:
            data["cover_file_id"]=msg.photo[-1].file_id
        elif msg.text and msg.text.lower (  ) .replace ( "â€˜","'" ) .replace ( "â€™","'") in ("o'tkazish","otkazish" ) :
            data["cover_file_id"]=""
        else: return await msg.reply_text ( "ðŸ–¼ Rasm yuboring yoki Â«o'tkazishÂ» deb yozing.")
        st["mode"]="lib_add_pdf"; return await msg.reply_text ( "ðŸ“„ Endi PDF faylni yuboring:")
    if mode=="lib_add_pdf":
        # Faylning oâ€˜zini Railway'ga yuklamaymiz; Telegram file_id saqlanadi.
        doc=msg.document
        if not doc:
            return await msg.reply_text ( "ðŸ“„ PDF hujjatni ðŸ“Ž Fayl/Document sifatida yuboring.\n\nâš ï¸ Rasm yoki boshqa turdagi xabar PDF sifatida qabul qilinmaydi.")
        name= ( doc.file_name or "" ) .lower (  ) .strip (  ) ; mime= ( doc.mime_type or "" ) .lower (  ) .strip ( )
        if not (name.endswith ( ".pdf") or mime=="application/pdf" ) :
            return await msg.reply_text ( f"âŒ Bu PDF emas.\nFayl: {doc.file_name or 'nomsiz'}\nTuri: {doc.mime_type or 'nomaâ€™lum'}\n\nPDF fayl yuboring.")
        uniq=doc.file_unique_id or ""
        if uniq and one ( "SELECT id FROM library_books WHERE pdf_unique_id=? AND status<>'deleted'", ( uniq, )  ) :
            STATE.pop ( uid,None)
            return await msg.reply_text ( "âš ï¸ Aynan shu PDF avval qoâ€˜shilgan.",reply_markup=library_home_markup ( uid ) )
        data["pdf_file_id"]=doc.file_id; data["pdf_unique_id"]=uniq
        data["pdf_file_name"]=doc.file_name or ""; data["pdf_file_size"]=int ( doc.file_size or 0)
        st["mode"]="lib_add_audio"
        size_mb= ( int ( doc.file_size or 0 ) / ( 1024*1024 ) ) if doc.file_size else 0
        kb=InlineKeyboardMarkup ( [[InlineKeyboardButton ( "â­ Audio yoâ€˜q â€” oâ€˜tkazish",callback_data="libskipaudio" ) ]])
        return await msg.reply_text(
            f"âœ… PDF qabul qilindi" + (f" ({size_mb:.1f} MB ) " if size_mb else "") +
            "\n\nðŸŽ§ Endi audio kitobni yuboring.\nMP3, M4A, M4B, OGG, OPUS, WAV, FLAC yoki voice qabul qilinadi.", reply_markup=kb)
    if mode=="lib_add_audio":
        af=None
        if msg.audio: af=msg.audio
        elif msg.voice: af=msg.voice
        elif msg.document:
            d=msg.document
            name= ( d.file_name or "" ) .lower (  ) .strip (  ) ; mime= ( d.mime_type or "" ) .lower (  ) .strip ( )
            audio_ext= ( ".mp3",".m4a",".m4b",".aac",".ogg",".opus",".wav",".flac",".wma")
            if mime.startswith ( "audio/") or name.endswith ( audio_ext ) : af=d
            else: return await msg.reply_text ( "âŒ Bu audio fayl emas.\nMP3/M4A/M4B/OGG/OPUS/WAV/FLAC yuboring yoki Â«o'tkazishÂ» deb yozing.")
        elif msg.text and msg.text.lower (  ) .replace ( "â€˜","'" ) .replace ( "â€™","'") in ("o'tkazish","otkazish" ) :
            data["audio_file_id"]=""; data["audio_unique_id"]=""
        else:
            return await msg.reply_text ( "ðŸŽ§ Audio, voice yoki audio-fayl yuboring.\nAudio kerak boâ€˜lmasa Â«o'tkazishÂ» deb yozing.")
        if af:
            data["audio_file_id"]=af.file_id; data["audio_unique_id"]=af.file_unique_id or ""
            data["audio_file_size"]=int ( getattr ( af,"file_size",0) or 0)
        with db ( ) as c:
            cur=c.execute ( """INSERT INTO library_books ( title,author,lang,description,cover_file_id,pdf_file_id,pdf_unique_id,audio_file_id,audio_unique_id,added_by,status,created_at)
                             VALUES ( ?,?,?,?,?,?,?,?,?,?,?,? ) """,
                          (data["title"],data["author"],data.get ( "lang","uz" ) ,data.get ( "description","" ) ,data.get ( "cover_file_id","" ) ,data.get ( "pdf_file_id","" ) ,data.get ( "pdf_unique_id","" ) ,data.get ( "audio_file_id","" ) ,data.get ( "audio_unique_id","" ) ,uid,"approved",now (  )  ) )
            bid=cur.lastrowid
            for cat in data.get ( "categories",[] ) :
                c.execute ( "INSERT OR IGNORE INTO library_categories ( name) VALUES ( ? ) ", ( cat, ) )
                cr=c.execute ( "SELECT id FROM library_categories WHERE name=? COLLATE NOCASE", ( cat, )  ) .fetchone ( )
                c.execute ( "INSERT OR IGNORE INTO library_book_categories ( book_id,category_id) VALUES ( ?,? ) ", ( bid,cr["id"] ) )
        STATE.pop ( uid,None ) ; audit ( uid,0,"library_add",str ( bid ) )
        return await msg.reply_text ( f"âœ… Kitob Vasatiya kutubxonasiga qoâ€˜shildi.\nðŸ“– {data['title']}\nID: {bid}",reply_markup=library_home_markup ( uid ) )

def is_hadith_admin ( uid ) :
    return is_super ( uid ) or bool ( one ( "SELECT 1 FROM hadith_admins WHERE user_id=?", ( uid, )  ) )

def hadith_collection_key ( name ) :
    x= ( name or "" ) .strip (  ) .casefold ( )
    aliases={
        "buxoriy":"Buxoriy","bukhari":"Buxoriy","bukhariy":"Buxoriy",
        "muslim":"Muslim","termiziy":"Termiziy","tirmiziy":"Termiziy","tirmidhi":"Termiziy",
        "abu dovud":"Abu Dovud","abudovud":"Abu Dovud","abu dawood":"Abu Dovud",
        "nasai":"Nasoiy","nasoiy":"Nasoiy","ibn moja":"Ibn Moja","ibnmajah":"Ibn Moja"
    }
    return aliases.get ( x, ( name or "" ) .strip (  ) .title (  ) )

def hadith_text ( r ) :
    parts=[f"ðŸ“œ {r['collection']} â€” {r['number']}-hadis"]
    if r["arabic"]: parts += ["",r["arabic"]]
    parts += ["",f"ðŸ‡ºðŸ‡¿ {r['translation']}"]
    if r["explanation"]: parts += ["",f"ðŸ“ Sharh: {r['explanation']}"]
    if r["source"]: parts += ["",f"ðŸ“š Manba: {r['source']}"]
    return "\n".join ( parts)

def hadith_markup ( r,back="hadith" ) :
    uploader=one ( "SELECT first_name,username FROM users WHERE user_id=?", ( r["added_by"], ) )
    name= ( uploader["first_name"] if uploader and uploader["first_name"] else f"ID {r['added_by']}")
    kb=[[InlineKeyboardButton ( f"ðŸ‘¤ Qoâ€˜shdi: {name[:40]}",url=f"tg://user?id={r['added_by']}" ) ]]
    kb.append ( [InlineKeyboardButton ( "â¬…ï¸ Hadislar",callback_data=back ) ,InlineKeyboardButton ( "ðŸ  Bosh menyu",callback_data="home" ) ])
    return InlineKeyboardMarkup ( kb)

async def send_hadith ( chat_id,ctx,r,reply_to=None ) :
    if not r: return
    await ctx.bot.send_message ( chat_id,hadith_text ( r ) ,reply_markup=hadith_markup ( r ) ,reply_to_message_id=reply_to)

async def hadith_command ( update,ctx,args ) :
    msg=update.effective_message
    if not args:
        r=one ( "SELECT * FROM hadiths WHERE status='approved' ORDER BY RANDOM ( ) LIMIT 1")
        if not r: return await msg.reply_text ( "ðŸ“œ Hozircha hadis bazasi boâ€˜sh.")
        return await send_hadith ( update.effective_chat.id,ctx,r,msg.message_id)
    if not args[-1].isdigit (  ) :
        return await msg.reply_text ( "Misol: *hadis buxoriy 1")
    num=int ( args[-1] ) ; collection=hadith_collection_key ( " ".join ( args[:-1] ) )
    r=one ( "SELECT * FROM hadiths WHERE lower ( collection ) =lower ( ?) AND number=? AND status='approved'", ( collection,num ) )
    if not r: return await msg.reply_text ( f"âŒ {collection} {num} topilmadi.")
    return await send_hadith ( update.effective_chat.id,ctx,r,msg.message_id)

async def content_admin_command ( update,ctx,cmd ) :
    msg=update.effective_message; uid=update.effective_user.id
    if not is_super ( uid ): return await msg.reply_text ( "â›” Bu buyruq faqat Super Ega uchun.")
    t=replied ( update)
    if cmd in {"ad.book","unad.book","ad.hadis","unad.hadis"}:
        if not t or not t.from_user: return await msg.reply_text ( "â†©ï¸ Foydalanuvchi xabariga reply qiling.")
        ensure_user ( t.from_user ) ; target=t.from_user.id
        if cmd=="ad.book":
            execute ( "INSERT OR REPLACE INTO library_admins ( user_id,added_by,created_at) VALUES ( ?,?,? ) ", ( target,uid,now (  )  ) )
            return await msg.reply_text ( f"âœ… {t.from_user.full_name} â€” kutubxona admini qilindi.")
        if cmd=="unad.book":
            execute ( "DELETE FROM library_admins WHERE user_id=?", ( target, ) )
            return await msg.reply_text ( f"âœ… {t.from_user.full_name}ning kutubxona adminligi olib tashlandi.")
        if cmd=="ad.hadis":
            execute ( "INSERT OR REPLACE INTO hadith_admins ( user_id,added_by,created_at) VALUES ( ?,?,? ) ", ( target,uid,now (  )  ) )
            return await msg.reply_text ( f"âœ… {t.from_user.full_name} â€” hadis admini qilindi.")
        execute ( "DELETE FROM hadith_admins WHERE user_id=?", ( target, ) )
        return await msg.reply_text ( f"âœ… {t.from_user.full_name}ning hadis adminligi olib tashlandi.")
    table="library_admins" if cmd=="bookadmins" else "hadith_admins"
    rows=all_ ( f"SELECT a.user_id,u.first_name,u.username FROM {table} a LEFT JOIN users u ON u.user_id=a.user_id ORDER BY a.created_at")
    title="ðŸ“š Kutubxona adminlari" if cmd=="bookadmins" else "ðŸ“œ Hadis adminlari"
    lines=[title]
    for i,r in enumerate ( rows,1 ) :
        nm= ( r["first_name"] or "Nomsiz") + ( ( " @"+r["username"]) if r["username"] else "")
        lines.append ( f"{i}. {nm} â€” {r['user_id']}")
    if len ( lines ) ==1: lines.append ( "Hozircha admin yoâ€˜q.")
    await msg.reply_text ( "\n".join ( lines ) )

async def add_hadith_command ( update,ctx ) :
    msg=update.effective_message; uid=update.effective_user.id
    if not is_hadith_admin ( uid ) : return await msg.reply_text ( "â›” Hadis qoâ€˜shish huquqi yoâ€˜q.")
    if update.effective_chat.type != "private":
        return await msg.reply_text ( "ðŸ“œ Hadis qoâ€˜shish xavfsiz va qulay boâ€˜lishi uchun botning private chatida *add.hadis yozing.")
    STATE[uid]={"mode":"had_add_collection","data":{}}
    await msg.reply_text ( "ðŸ“œ HADIS QOâ€˜SHISH â€” 1/6\n\nToâ€˜plam nomini yuboring.\nMisol: Buxoriy")

async def hadith_private_input ( update,ctx ) :
    uid=update.effective_user.id; msg=update.effective_message; st=STATE.get ( uid)
    if not st or not str ( st.get ( "mode","" )  ) .startswith ( "had_" ) : return
    if not is_hadith_admin ( uid ) :
        STATE.pop ( uid,None ) ; return await msg.reply_text ( "â›” Hadis boshqaruv huquqi yoâ€˜q.")
    if not msg.text:
        return await msg.reply_text ( "âœï¸ Bu bosqichda matn yuboring.")
    text=msg.text.strip (  ) ; data=st.setdefault ( "data",{} ) ; mode=st["mode"]
    if text.casefold ( ) in {"bekor","cancel","/cancel"}:
        STATE.pop ( uid,None ) ; return await msg.reply_text ( "âŒ Hadis qoâ€˜shish bekor qilindi.",reply_markup=main_menu_markup ( uid ) )
    if mode.startswith ( "had_edit_" ) :
        hid=int ( data.get ( "hadith_id",0 ) )
        if not hid or not one ( "SELECT 1 FROM hadiths WHERE id=? AND status='approved'", ( hid, ) ) :
            STATE.pop ( uid,None ) ; return await msg.reply_text ( "âŒ Hadis topilmadi." )
        field=mode[9:]
        if field=="collection": value=hadith_collection_key ( text )
        elif field=="number":
            if not text.isdigit ( ) or int ( text ) <=0: return await msg.reply_text ( "âŒ Musbat raqam yuboring." )
            value=int ( text )
        elif field in {"arabic","explanation","source"}:
            value="" if text.casefold ( ).replace ( "â€˜","'" ).replace ( "â€™","'" ) in {"o'tkazish","otkazish","o'chirish","ochirish"} else text
        elif field=="translation": value=text
        else: return
        current=one ( "SELECT collection,number FROM hadiths WHERE id=?", ( hid, ) )
        col=value if field=="collection" else current["collection"]; num=value if field=="number" else current["number"]
        dup=one ( "SELECT id FROM hadiths WHERE lower(collection)=lower(?) AND number=? AND id<>? AND status<>'deleted'", ( col,num,hid ) )
        if dup: return await msg.reply_text ( f"âš ï¸ {col} {num} boshqa hadis sifatida bazada mavjud. ID: {dup['id']}" )
        execute ( f"UPDATE hadiths SET {field}=? WHERE id=?", ( value,hid ) )
        STATE.pop ( uid,None ) ; audit ( uid,0,"hadith_edit",f"{hid}:{field}" )
        r=one ( "SELECT * FROM hadiths WHERE id=?", ( hid, ) )
        kb=InlineKeyboardMarkup ( [[InlineKeyboardButton ( "âœï¸ Yana tahrirlash",callback_data=f"hedit:{hid}" ) ],[InlineKeyboardButton ( "ðŸ“œ Hadislar",callback_data="hadith" ) ]] )
        return await msg.reply_text ( "âœ… Hadis yangilandi.\n\n"+hadith_text ( r ),reply_markup=kb )
    if mode=="had_add_collection":
        data["collection"]=hadith_collection_key ( text ) ; st["mode"]="had_add_number"
        return await msg.reply_text ( "ðŸ“œ 2/6 â€” Hadis raqamini yuboring.\nMisol: 1")
    if mode=="had_add_number":
        if not text.isdigit ( ) or int ( text ) <=0: return await msg.reply_text ( "âŒ Musbat raqam yuboring. Misol: 1")
        data["number"]=int ( text)
        existing=one ( "SELECT * FROM hadiths WHERE lower ( collection ) =lower ( ?) AND number=? AND status<>'deleted'", ( data["collection"],data["number"] )  )
        if existing:
            STATE.pop ( uid,None )
            kb=InlineKeyboardMarkup ( [[InlineKeyboardButton ( "âœï¸ Mavjud hadisni tahrirlash",callback_data=f"hedit:{existing['id']}" ) ],[InlineKeyboardButton ( "âŒ Bekor",callback_data="hadith" ) ]] )
            return await msg.reply_text ( f"âš ï¸ {data['collection']} {data['number']} bazada mavjud.\n\nYangi nusxa qoâ€˜shilmaydi. Mavjud hadisni tahrirlashingiz mumkin.",reply_markup=kb )
        st["mode"]="had_add_arabic"
        return await msg.reply_text ( "ðŸ“œ 3/6 â€” Hadisning arabcha asl matnini yuboring.\nArabcha matn boâ€˜lmasa: o'tkazish")
    if mode=="had_add_arabic":
        data["arabic"]="" if text.casefold (  ) .replace ( "â€˜","'" ) .replace ( "â€™","'") in {"o'tkazish","otkazish"} else text
        st["mode"]="had_add_translation"
        return await msg.reply_text ( "ðŸ“œ 4/6 â€” Oâ€˜zbekcha tarjimasini yuboring:")
    if mode=="had_add_translation":
        data["translation"]=text; st["mode"]="had_add_explanation"
        return await msg.reply_text ( "ðŸ“œ 5/6 â€” Qisqa sharh yuboring.\nSharh boâ€˜lmasa: o'tkazish")
    if mode=="had_add_explanation":
        data["explanation"]="" if text.casefold (  ) .replace ( "â€˜","'" ) .replace ( "â€™","'") in {"o'tkazish","otkazish"} else text
        st["mode"]="had_add_source"
        return await msg.reply_text ( "ðŸ“œ 6/6 â€” Manbani yuboring.\nMisol: Sahih al-Buxoriy, Kitob ...")
    if mode=="had_add_source":
        data["source"]=text
        try:
            execute ( "INSERT INTO hadiths ( collection,number,arabic,translation,explanation,source,added_by,status,created_at) VALUES ( ?,?,?,?,?,?,?,?,? ) ",
                    (data["collection"],data["number"],data.get ( "arabic","" ) ,data["translation"],data.get ( "explanation","" ) ,data["source"],uid,"approved",now (  )  ) )
        except sqlite3.IntegrityError:
            STATE.pop ( uid,None ) ; return await msg.reply_text ( "âš ï¸ Bu hadis bazada mavjud.",reply_markup=main_menu_markup ( uid ) )
        audit ( uid,update.effective_chat.id,"hadith_add",f"{data['collection']} {data['number']}")
        r=one ( "SELECT * FROM hadiths WHERE lower ( collection ) =lower ( ?) AND number=?", ( data["collection"],data["number"] ) )
        STATE.pop ( uid,None)
        await msg.reply_text ( "âœ… Hadis saqlandi.")
        return await send_hadith ( update.effective_chat.id,ctx,r)

async def delete_hadith_command ( update,ctx,args ) :
    msg=update.effective_message; uid=update.effective_user.id
    if not is_hadith_admin ( uid ) : return await msg.reply_text ( "â›” Hadis oâ€˜chirish huquqi yoâ€˜q.")
    if len ( args ) <2 or not args[-1].isdigit (  ) : return await msg.reply_text ( "Misol: *del.hadis buxoriy 1")
    num=int ( args[-1] ) ; collection=hadith_collection_key ( " ".join ( args[:-1] ) )
    r=one ( "SELECT id,collection,number FROM hadiths WHERE lower ( collection ) =lower ( ?) AND number=? AND status='approved'", ( collection,num ) )
    if not r: return await msg.reply_text ( "âŒ Hadis topilmadi.")
    kb=InlineKeyboardMarkup ( [[InlineKeyboardButton ( "âœ… Oâ€˜chirish",callback_data=f"hdel:{r['id']}" ) ,InlineKeyboardButton ( "âŒ Bekor",callback_data="hadith" ) ]])
    await msg.reply_text ( f"ðŸ—‘ {r['collection']} {r['number']} hadisni oâ€˜chirishni tasdiqlaysizmi?",reply_markup=kb)

async def broadcast_command ( update,ctx,args ) :
    msg=update.effective_message; uid=update.effective_user.id
    if not is_super ( uid ):
        return await msg.reply_text ( "â›” *post faqat Super Ega uchun.")
    targets=[]
    for r in all_ ( "SELECT user_id FROM users WHERE blocked=0" ) :
        targets.append ( int ( r["user_id"] ) )
    for r in all_ ( "SELECT chat_id FROM groups" ) :
        targets.append ( int ( r["chat_id"] ) )
    # Takroriy IDlarni olib tashlaymiz; manba chatiga qayta yubormaymiz.
    targets=list ( dict.fromkeys ( targets ) )
    source=msg.reply_to_message
    direct_text=" ".join ( args ) .strip ( )
    if not source and not direct_text:
        return await msg.reply_text ( "ðŸ“¢ Xabar yuborish:\n1) Post/xabarga reply qilib *post yozing\nyoki\n2) *post Xabaringiz")
    sent=0; failed=0
    status=await msg.reply_text ( f"ðŸ“¢ Yuborish boshlandi...\nQabul qiluvchilar: {len ( targets ) }")
    for chat_id in targets:
        if chat_id==update.effective_chat.id: continue
        try:
            if source:
                await ctx.bot.copy_message ( chat_id=chat_id,from_chat_id=source.chat_id,message_id=source.message_id)
            else:
                await ctx.bot.send_message ( chat_id,direct_text)
            sent+=1
        except TelegramError:
            failed+=1
        except Exception:
            failed+=1
    audit ( uid,update.effective_chat.id,"broadcast",f"sent={sent},failed={failed}")
    await status.edit_text ( f"âœ… Xabarnoma tugadi.\n\nðŸ“¨ Yuborildi: {sent}\nâš ï¸ Yetib bormadi: {failed}")

async def stars_cmd ( update, ctx, args ) :
    uid = update.effective_user.id
    msg = update.effective_message
    if not is_super ( uid ):
        return await msg.reply_text ( "â›” *stars faqat Super Ega uchun.")
    t = replied ( update)
    if not t or not t.from_user:
        return await msg.reply_text ( "â†©ï¸ Stars oluvchining xabariga reply qiling.\nMisol: *stars 100")
    if not args or not args[0].isdigit (  ) :
        return await msg.reply_text ( "Misol: *stars 100")
    stars = int ( args[0])
    if stars <= 0:
        return await msg.reply_text ( "âŒ Stars miqdori 0 dan katta boâ€˜lishi kerak.")
    target = t.from_user
    username = f"@{target.username}" if target.username else "username mavjud emas"
    kb = InlineKeyboardMarkup ( [[
        InlineKeyboardButton ( "â­ Telegram orqali Stars sovgâ€˜a qilish", url="tg://settings/stars/gift")
    ]])
    await msg.reply_text(
        f"â­ Stars sovgâ€˜asi\n\n"
        f"ðŸ‘¤ Oluvchi: {target.full_name}\n"
        f"ðŸ”— Username: {username}\n"
        f"ðŸ†” ID: {target.id}\n"
        f"â­ Miqdor: {stars}\n\n"
        f"Quyidagi tugmani bosing.\n"
        f"Telegramning rasmiy Stars Gift oynasi ochiladi.\n"
        f"U yerdan oluvchini tanlab, {stars} â­ paketini tanlang va toâ€˜lovni tasdiqlang.",
        reply_markup=kb
    )

async def start ( update,ctx ) :
    ensure_user ( update.effective_user)
    u=update.effective_user
    if update.effective_chat.type != "private":
        ensure_group ( update.effective_chat)
        await update.effective_message.reply_text ( "ðŸª¶ Veritas v8 ishlayapti. Shaxsiy kabinet uchun botga private yozing.")
        return
    await update.effective_message.reply_text ( "ðŸª¶ VERITAS v8\n\nShaxsiy kabinet",reply_markup=main_menu_markup ( u.id ) )

async def cmd_id ( update,ctx ) :
    ensure_user ( update.effective_user)
    await update.effective_message.reply_text ( f"ðŸ‘¤ ID: {update.effective_user.id}\nðŸ’¬ Chat ID: {update.effective_chat.id}")

async def cmd_help ( update,ctx ) :
    await update.effective_message.reply_text(
        "â“ VERITAS V8 â€” YORDAM MARKAZI\n\n"
        "ðŸª¶ Veritas qila oladigan barcha asosiy ishlar shu yerda jamlangan.\n"
        "Kerakli boâ€˜limni tanlang:",
        reply_markup=help_home_markup()
    )

def help_home_markup():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("ðŸ“Œ Asosiy",callback_data="help:main"), InlineKeyboardButton("ðŸ‘¤ Profil / Faollik",callback_data="help:profile")],
        [InlineKeyboardButton("ðŸ¤– Veritas AI",callback_data="help:ai"), InlineKeyboardButton("ðŸ§© AI Rebus",callback_data="help:rebus")],
        [InlineKeyboardButton("ðŸ“š Vasatiya",callback_data="help:library"), InlineKeyboardButton("ðŸ“œ Hadislar",callback_data="help:hadith")],
        [InlineKeyboardButton("ðŸ›¡ Moderatsiya",callback_data="help:moderation"), InlineKeyboardButton("â± Vaqtli jazolar",callback_data="help:tempmod")],
        [InlineKeyboardButton("ðŸ” Himoya / Lock",callback_data="help:security"), InlineKeyboardButton("ðŸŒŠ Anti-spam / Raid",callback_data="help:antispam")],
        [InlineKeyboardButton("ðŸ‘‹ Welcome / Goodbye",callback_data="help:welcome"), InlineKeyboardButton("ðŸ’¬ Filter / Notes",callback_data="help:filters")],
        [InlineKeyboardButton("ðŸ›¡ Adminlar",callback_data="help:admins"), InlineKeyboardButton("ðŸ‘‘ Super boshqaruv",callback_data="help:superadmins")],
        [InlineKeyboardButton("â­ Stars / Gift",callback_data="help:stars"), InlineKeyboardButton("ðŸŽ‰ Giveaway",callback_data="help:giveaway")],
        [InlineKeyboardButton("ðŸ“¢ Xabarnoma",callback_data="help:broadcast"), InlineKeyboardButton("ðŸ“¨ Egaga xabar",callback_data="help:owner")],
        [InlineKeyboardButton("âš™ï¸ Guruh sozlamalari",callback_data="help:settings")],
        [InlineKeyboardButton("ðŸ  Bosh menyu",callback_data="home")]
    ])

def help_menu_markup():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("â¬…ï¸ Yordam boâ€˜limlari",callback_data="help:home"), InlineKeyboardButton("ðŸ  Bosh menyu",callback_data="home")]
    ])

def help_text(section):
    data={
      "main":"ðŸ“Œ ASOSIY BUYRUQLAR\nâ”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n*help â€” barcha yordam boâ€˜limlarini ochadi.\n*id â€” sizning Telegram ID va joriy chat ID sini koâ€˜rsatadi.\n*men â€” shaxsiy/global profilingizni koâ€˜rsatadi.\n*qadr â€” Qadr TOP-10 ni koâ€˜rsatadi.\nðŸ’  Qadr / âš–ï¸ Eâ€™tiroz â€” aâ€™zoning ochiq profilidan baholash.\n*rules â€” guruh qoidalarini chiqaradi.\n*admins â€” guruh va Veritas adminlarini koâ€˜rsatadi.\n*vse â€” Veritas xabariga reply qilib yozilganda aâ€™zoning Veritas qayd etgan oldingi xabarlarini tozalaydi.\n\nðŸ  Shaxsiy chatdagi bosh menyudan AI, kutubxona, hadis, profil, Stars, Rebus va Egaga xabar boâ€˜limlari ochiladi.",
      "profile":"ðŸ‘¤ PROFIL VA FAOLLIK\nâ”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n*men â€” rol, XP, level, xabarlar, ilm hissasi va kabinet maâ€™lumotlari.\n*ak â€” barcha Veritas guruhlari boâ€˜yicha Global TOP-10.\n*aktiv â€” global faollik TOP roâ€˜yxati.\n*top 10 â€” TOP paneli.\n*unvon <nom> â€” maxsus unvon oâ€˜rnatadi.\n*unvonoff â€” maxsus unvonni olib tashlaydi.\n\nðŸ“ˆ Veritas guruhlardagi faollikni jamlab profilga qoâ€˜shadi.",
      "ai":"ðŸ¤– VERITAS AI\nâ”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\nShaxsiy menyudagi Â«ðŸ¤– Veritas AIÂ» â€” AI yordamchi.\n*ai â€” guruhdagi AI holati va tarifini ochadi.\n*ai.p â€” replydagi foydalanuvchiga AI Premium sovgâ€˜a qiladi.\n\nðŸŽ Shaxsiy AI: birinchi 30 kun bepul, keyin 10 â­ / 30 kun.\nðŸŽ Guruh AI: birinchi 30 kun bepul, keyin 100 â­ / 30 kun.\nðŸ–¼ AI rasmni koâ€˜rib tahlil qila oladi.\nðŸ“š Kutubxona PDFlaridan AI test yaratish imkoniyatlari ham mavjud.",
      "rebus":"ðŸ§© AI REBUS\nâ”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\nGuruhda Veritas xabariga reply qilib *rebus yozing.\nBot private chatda rebuslar soni va javoblarini soâ€˜raydi.\nAI rasmli rebus yaratadi; toâ€˜gâ€˜ri javob topilgach keyingisi chiqadi.\nðŸ† Yakunda gâ€˜oliblar natijasi chiqariladi.\nðŸ“ Bogâ€˜langan kanal boâ€˜lsa rebus kanalga, aks holda guruhga joylanadi.",
      "library":"ðŸ“š VASATIYA KUTUBXONASI\nâ”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\nðŸ”Ž Kitob qidirish, kategoriya, yangi kitoblar va sevimlilar.\nðŸ“„ PDF/audio kitoblar va kitob boshqaruvi.\n*ad.book â€” replydagi odamga kutubxona adminligi beradi.\n*unad.book â€” kutubxona adminligini oladi.\n*bookadmins â€” kutubxona adminlarini koâ€˜rsatadi.\n\nâœï¸ Kitob admini nom, muallif, til, kategoriya, tavsif, muqova, PDF va audioni boshqaradi.",
      "hadith":"ðŸ“œ SAHIH HADISLAR\nâ”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n*hadis â€” tasodifiy hadis chiqaradi.\nðŸ¤– AI Hadis qidirish â€” faqat Veritasga qoâ€˜shilgan hadislar orasidan mavzu boâ€˜yicha topadi.\n*hadis buxoriy 1 â€” aniq hadisni topadi.\n*add.hadis â€” private chatda yangi hadis qoâ€˜shadi.\n*del.hadis buxoriy 1 â€” hadisni oâ€˜chiradi.\n*ad.hadis â€” hadis adminligi beradi.\n*unad.hadis â€” huquqni oladi.\n*hadisadmins â€” hadis adminlari roâ€˜yxati.\nâœï¸ Mavjud hadisni tahrirlash ham mumkin.",
      "moderation":"ðŸ›¡ MODERATSIYA\nâ”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n*warn [sabab] â€” replydagi aâ€™zoga ogohlantirish beradi.\n*unwarn â€” bitta warnni olib tashlaydi.\n*warns â€” warnlar sonini koâ€˜rsatadi.\n*clearwarns â€” barcha warnlarni tozalaydi.\n*mute â€” replydagi aâ€™zoni yozishdan cheklaydi.\n*unmute â€” mute holatini ochadi.\n*kick â€” aâ€™zoni guruhdan chiqaradi.\n*ban â€” aâ€™zoni bloklaydi.\n*unban â€” ban holatini ochadi.\n*del â€” reply qilingan xabarni oâ€˜chiradi.\n*purge â€” reply qilingan joydan buyruqqacha xabarlarni tozalaydi.\n*pin â€” replydagi xabarni pin qiladi.\n*unpin â€” joriy pinni olib tashlaydi.\n*modlog â€” soâ€˜nggi moderatsiya amallarini koâ€˜rsatadi.\n\nâ„¹ï¸ Jazolash buyruqlarini foydalanuvchi xabariga reply qilib ishlating.",
      "tempmod":"â± VAQTLI JAZOLAR\nâ”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n*tempmute 10m [sabab] â€” replydagi aâ€™zoni 10 daqiqaga mute qiladi.\n*tempban 2h [sabab] â€” replydagi aâ€™zoni 2 soatga ban qiladi.\n\nâ° Vaqt: s=soniya, m=daqiqa, h=soat, d=kun, w=hafta.\nMisol: *tempmute 1d flood\nMuddat tugaganda Veritas jazoni avtomatik ochadi.",
      "security":"ðŸ” HIMOYA VA LOCKLAR\nâ”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n*links on/off â€” havolalarni nazorat qiladi.\n*blacklist <soâ€˜z> â€” taqiqlangan soâ€˜z qoâ€˜shadi.\n*unblacklist <soâ€˜z> â€” blacklistdan olib tashlaydi.\n*blacklists â€” blacklist roâ€˜yxati.\n*lock <turi> â€” turdagi kontentni bloklaydi.\n*unlock <turi> â€” lockni ochadi.\n*locks â€” faol locklarni koâ€˜rsatadi.\n*lockall â€” media locklarning barchasini yoqadi.\n*unlockall â€” media locklarning barchasini oâ€˜chiradi.\n\nðŸ”’ Rose Full media himoyasi: forward, contact, location, poll, photo, video, audio, voice, document, sticker, animation.",
      "antispam":"ðŸŒŠ ANTI-SPAM / ANTI-RAID\nâ”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n*antiflood on/off â€” flood himoyasini yoqadi/oâ€˜chiradi.\n*flood 5 â€” flood chegarasini belgilaydi.\n*antirepeat on/off [limit] â€” bir xil xabarni takrorlashdan himoya qiladi.\n*raid on/off â€” koâ€˜p odam birdan kirgandagi raid himoyasi.\n*report â€” adminlarni yordamga chaqiradi.\n*reports on/off â€” report tizimini boshqaradi.\n\nðŸ›¡ Approved va admin foydalanuvchilar himoya filtrlari uchun istisno qilinishi mumkin.",
      "welcome":"ðŸ‘‹ WELCOME / GOODBYE\nâ”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n*welcome on/off â€” kirish xabarini yoqadi/oâ€˜chiradi.\n*goodbye on/off â€” chiqish xabarini yoqadi/oâ€˜chiradi.\n*setwelcome <matn> â€” maxsus welcome matni.\n*setgoodbye <matn> â€” maxsus goodbye matni.\n*cleanservice on/off â€” join/leave servis xabarlarini tozalaydi.\n\nðŸ§© Matnda {first} â€” ism, {chatname} â€” guruh nomi sifatida ishlatiladi.",
      "filters":"ðŸ’¬ FILTER VA NOTES\nâ”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n*filter <kalit> <javob> â€” kalit soâ€˜zga avtomatik javob saqlaydi.\n*filters â€” filterlar roâ€˜yxati.\n*stop <kalit> â€” bitta filterni oâ€˜chiradi.\n*stopall â€” barcha filterlarni tozalaydi.\n*save <nom> <matn> â€” note saqlaydi.\n*get <nom> â€” note chiqaradi.\n*notes â€” notelar roâ€˜yxati.\n*clear <nom> â€” noteni oâ€˜chiradi.",
      "admins":"ðŸ›¡ ADMIN BOSHQARUVI\nâ”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n*ruxsat â€” replydagi aâ€™zoga Veritas boshqaruv huquqi beradi.\n*ruxsatsiz â€” Veritas huquqini oladi.\n*admin â€” Telegram admini qiladi.\n*unadmin â€” Telegram adminligini oladi.\n*approve â€” aâ€™zoni himoya filtrlari uchun tasdiqlaydi.\n*unapprove â€” approve holatini olib tashlaydi.\n*approved â€” tasdiqlangan aâ€™zolar roâ€˜yxati.\n*ad.book / *unad.book â€” kutubxona admini.\n*ad.hadis / *unad.hadis â€” hadis admini.",
      "superadmins":"ðŸ‘‘ SUPER BOSHQARUV\nâ”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n*superadmin â€” replydagi foydalanuvchini Super Admin qiladi.\n*unsuperadmin â€” Super Admin huquqini oladi.\n*superadmins â€” Super Egalar va Super Adminlar roâ€˜yxati.\n*post â€” global xabarnoma yuboradi.\n*ai.p â€” replydagi foydalanuvchiga AI Premium beradi.\n\nðŸ‘‘ Super Admin qoâ€˜shish/olish faqat haqiqiy Super Ega uchun.",
      "stars":"â­ STARS / GIFT / PREMIUM\nâ”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n*topup 100 â€” Veritas kabinetiga Stars kredit oladi.\n*stars 100 â€” Telegram Stars bilan bogâ€˜liq oynani ochadi (ruxsatga qarab).\n*give <narx> â€” replydagi foydalanuvchiga real Telegram Gift yuboradi.\n*premium 3/6/12 â€” replydagi foydalanuvchiga Telegram Premium sovgâ€˜a qiladi.\nâ­ Kabinet balansi bosh menyudagi Â«HisobÂ» boâ€˜limida koâ€˜rinadi.",
      "giveaway":"ðŸŽ‰ GIVEAWAY\nâ”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n*giveaway gift <narx> <daq> <gâ€˜oliblar> â€” guruhda Gift konkursini ochadi.\n*join â€” faol konkursga qatnashadi.\nðŸ† Vaqt tugaganda Veritas gâ€˜oliblarni avtomatik tanlaydi.",
      "broadcast":"ðŸ“¢ GLOBAL XABARNOMA\nâ”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n*post <matn> â€” barcha foydalanuvchi va guruhlarga matn yuboradi.\n*post â€” biror post/xabarga reply qilib ishlatilsa, oâ€˜sha xabarni nusxalaydi.\nðŸ” Faqat Super boshqaruv uchun.",
      "owner":"ðŸ“¨ EGAGA XABAR QOLDIRISH\nâ”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\nBosh menyudan Â«ðŸ“¨ Egaga xabar qoldirishÂ» tugmasini bosing.\nKeyin matn, rasm, video, voice, audio, sticker yoki hujjat yuborishingiz mumkin.\nðŸ“¬ Xabar Super Egalarga yetkaziladi.\nâœ‰ï¸ Ega Â«Javob berishÂ» tugmasi orqali sizga Veritas ichidan javob beradi.\nâœ… Â«Koâ€˜rildiÂ» â€” murojaat koâ€˜rilganini belgilaydi.\nðŸ—‘ Â«YopishÂ» â€” murojaatni yakunlaydi.",
      "settings":"âš™ï¸ GURUH SOZLAMALARI\nâ”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n*setrules <matn> â€” guruh qoidalarini saqlaydi.\n*welcome on/off â€” welcome tizimi.\n*goodbye on/off â€” goodbye tizimi.\n*cleanservice on/off â€” servis xabarlarini tozalash.\n*links on/off â€” link himoyasi.\n*antiflood on/off â€” flood himoyasi.\n*reports on/off â€” report tizimi.\n\nðŸª¶ Barcha sozlamalar guruh boâ€˜yicha alohida saqlanadi."
    }
    return data.get(section,"Boâ€˜lim topilmadi.")

async def cmd_super ( update,ctx ) :
    ensure_user ( update.effective_user)
    if not is_super ( update.effective_user.id ):
        return await update.effective_message.reply_text ( "â›” Bu boâ€˜lim faqat Super Ega uchun.")
    uc=one ( "SELECT COUNT ( *) n FROM users" ) ["n"]; gc=one ( "SELECT COUNT ( *) n FROM groups" ) ["n"]
    try:
        sb=await ctx.bot.get_my_star_balance ( )
        real=getattr ( sb,"amount",sb)
    except Exception: real="API orqali olinmadi"
    await update.effective_message.reply_text(
        f"ðŸ‘‘ VERITAS SUPER EGA\n\nFoydalanuvchilar: {uc}\nGuruhlar: {gc}\nBot real Stars: {real}\n"
        f"Super Egalar: {', '.join ( map ( str,SUPER_OWNERS )  ) }"
    )

async def topup ( update,ctx,amount ) :
    if update.effective_chat.type!="private":
        return await update.effective_message.reply_text ( "â­ Hisobni private kabinetda toâ€˜ldiring.")
    if amount not in TOPUPS:
        return await update.effective_message.reply_text ( "Miqdor: "+", ".join ( map ( str,TOPUPS )  ) )
    payload=f"topup:{update.effective_user.id}:{amount}:{now (  ) }"
    await ctx.bot.send_invoice(
        chat_id=update.effective_chat.id,title="Veritas Stars krediti",
        description=f"Veritas kabinetiga {amount} â­ kredit",
        payload=payload,currency="XTR",prices=[LabeledPrice ( "Stars",amount ) ]
    )

async def precheckout ( update,ctx ) :
    q=update.pre_checkout_query
    ok=q.invoice_payload.startswith ( "topup:")
    await q.answer ( ok=ok,error_message=None if ok else "Notoâ€˜gâ€˜ri toâ€˜lov.")

async def paid ( update,ctx ) :
    ensure_user ( update.effective_user)
    p=update.effective_message.successful_payment
    if not p or p.currency!="XTR" or not p.invoice_payload.startswith ( "topup:" ) : return
    if one ( "SELECT 1 FROM payments WHERE charge_id=?", ( p.telegram_payment_charge_id, )  ) : return
    with db ( ) as c:
        c.execute ( "INSERT INTO payments ( charge_id,user_id,amount,payload,created_at) VALUES ( ?,?,?,?,? ) ",
                  (p.telegram_payment_charge_id,update.effective_user.id,p.total_amount,p.invoice_payload,now (  )  ) )
    wallet_change ( update.effective_user.id,p.total_amount,"topup",ref=p.telegram_payment_charge_id)
    await update.effective_message.reply_text ( f"âœ… {p.total_amount} â­ kredit qoâ€˜shildi.\nBalans: {wallet ( update.effective_user.id ) } â­")

async def show_me ( update,ctx ) :
    u=update.effective_user; ensure_user ( u)
    chat=update.effective_chat
    txt=global_profile_text ( u )
    if chat.type in ("group","supergroup" ) :
        ensure_group ( chat )
        r=one ( "SELECT title FROM members WHERE chat_id=? AND user_id=?", ( chat.id,u.id ) )
        custom=( r["title"] if r else "" ) or ""
        if custom:
            txt += f"\nðŸŽ– Guruh unvoni: {custom}"
    await update.effective_message.reply_text ( txt)

async def title_command ( update,ctx,cmd,args ) :
    chat=update.effective_chat; msg=update.effective_message; actor=update.effective_user
    if chat.type not in ("group","supergroup" ) :
        return await msg.reply_text ( "â›” Unvon faqat guruhda boshqariladi.")
    ensure_group ( chat ) ; ensure_user ( actor)
    if not await can_manage ( ctx.bot,chat.id,actor.id ) :
        return await msg.reply_text ( "â›” Sizda unvon boshqarish huquqi yoâ€˜q.")
    target=replied ( update)
    if not target or not target.from_user:
        return await msg.reply_text ( "â†©ï¸ Foydalanuvchi xabariga reply qiling.")
    tu=target.from_user
    if tu.id in SUPER_OWNERS:
        return await msg.reply_text ( "ðŸ‘‘ Super Ega unvonini oâ€˜zgartirib boâ€˜lmaydi.")
    execute ( """INSERT OR IGNORE INTO members ( chat_id,user_id,xp,messages,daily,weekly,title)
               VALUES ( ?,?,0,0,0,0,'' ) """, ( chat.id,tu.id ) )
    if cmd=="unvon":
        title=" ".join ( args ) .strip ( )
        if not title: return await msg.reply_text ( "Misol: *unvon Kitobxon")
        if len ( title ) >40: return await msg.reply_text ( "â— Unvon 40 belgidan uzun boâ€˜lmasin.")
        if title.casefold (  ) .replace ( "ðŸ‘‘","" ) .strip (  ) .replace ( " ","" ) =="superega":
            return await msg.reply_text ( "â›” Â«Super EgaÂ» unvoni himoyalangan.")
        execute ( "UPDATE members SET title=? WHERE chat_id=? AND user_id=?", ( title,chat.id,tu.id ) )
        audit ( actor.id,chat.id,"title_set",f"{tu.id}: {title}")
        return await msg.reply_text ( f"ðŸŽ– {tu.full_name} uchun unvon: Â«{title}Â»")
    execute ( "UPDATE members SET title='' WHERE chat_id=? AND user_id=?", ( chat.id,tu.id ) )
    audit ( actor.id,chat.id,"title_removed",str ( tu.id ) )
    await msg.reply_text ( f"âœ… {tu.full_name}ning unvoni olib tashlandi.")

def display_name_row ( r ) :
    name= ( r["first_name"] or "" ) .strip ( ) or "Nomsiz"
    username= ( " @"+r["username"]) if (r["username"] or "" ) .strip ( ) else ""
    return name+username

async def top10_menu ( update,ctx ) :
    if not is_super ( update.effective_user.id ):
        return await update.effective_message.reply_text ( "â›” TOP mukofot paneli faqat Super Ega uchun.")
    kb=InlineKeyboardMarkup ( [[
        InlineKeyboardButton ( "ðŸŽ Giftli",callback_data=f"topgift:{update.effective_chat.id}" ) ,
        InlineKeyboardButton ( "ðŸ† Giftsiz",callback_data=f"topplain:{update.effective_chat.id}")
    ]])
    await update.effective_message.reply_text(
        "ðŸ† TOP-10 yakunlash usulini tanlang:\n\n"
        "ðŸŽ Giftli â€” TOP-3 ga 50 â­ lik haqiqiy Telegram Gift.\n"
        "ðŸ† Giftsiz â€” faqat TOP-10 natijasi.",
        reply_markup=kb
    )

async def top10_result ( bot,chat_id,with_gifts=False,actor_id=None ) :
    rows=all_ ( """SELECT m.user_id,m.messages,m.xp,m.title,u.first_name,u.username
                 FROM members m LEFT JOIN users u ON u.user_id=m.user_id
                 WHERE m.chat_id=? ORDER BY m.messages DESC LIMIT 10""", ( chat_id, ) )
    if not rows:
        await bot.send_message ( chat_id,"ðŸ† TOP-10 uchun maâ€™lumot yoâ€˜q.")
        return
    lines=["ðŸ† TOP-10"]
    for i,r in enumerate ( rows ) :
        lines.append ( f"{i+1}. {display_name_row ( r ) } â€” {r['messages']} xabar")
    await bot.send_message ( chat_id,"\n".join ( lines ) )
    if not with_gifts: return
    try:
        available=await bot.get_available_gifts ( )
        gift=next (  ( g for g in available.gifts
                   if int ( getattr ( g,"star_count",0 )  ) ==50
                   and (getattr ( g,"remaining_count",None) is None or getattr ( g,"remaining_count",0 ) >0 )  ) ,None)
    except Exception as e:
        await bot.send_message ( chat_id,f"âŒ Giftlar olinmadi: {e}" ) ; return
    if not gift:
        await bot.send_message ( chat_id,"âŒ Hozir 50 â­ lik Telegram Gift mavjud emas." ) ; return
    cost=50*min ( 3,len ( rows ) )
    if actor_id is None or wallet ( actor_id ) <cost:
        await bot.send_message ( chat_id,f"âŒ Super Ega kreditida kamida {cost} â­ kerak." ) ; return
    sent=[]
    for r in rows[:3]:
        uid=int ( r["user_id"])
        if not wallet_change ( actor_id,-50,"top10_gift_pending",uid,meta={"gift_id":str ( gift.id ) } ) :
            break
        try:
            await bot.send_gift ( user_id=uid,gift_id=gift.id,text="ðŸ† Veritas TOP-3 mukofoti")
            sent.append ( display_name_row ( r ) )
        except Exception:
            wallet_change ( actor_id,50,"top10_gift_rollback",uid)
    await bot.send_message ( chat_id,
        "ðŸŽ TOP-3 Gift natijasi:\n"+ ( "\n".join ( "âœ… "+x for x in sent) if sent else "Gift yuborilmadi." ) )

def parse_duration(value):
    """10m, 2h, 1d, 1w kabi vaqtni sekundga aylantiradi."""
    if not value: return 0
    m=re.fullmatch(r"(\d+)(s|m|h|d|w)",str(value).strip().lower())
    if not m: return 0
    n=int(m.group(1)); unit=m.group(2)
    return n*{"s":1,"m":60,"h":3600,"d":86400,"w":604800}[unit]

def moderation_settings(chat_id):
    execute("INSERT OR IGNORE INTO moderation_settings(chat_id) VALUES(?)",(chat_id,))
    return one("SELECT * FROM moderation_settings WHERE chat_id=?",(chat_id,))

def modlog(chat_id,actor_id,target_id,action,reason="",duration=0):
    execute("INSERT INTO moderation_log(chat_id,actor_id,target_id,action,reason,duration,created_at) VALUES(?,?,?,?,?,?,?)",
            (chat_id,actor_id or 0,target_id or 0,action,reason or "",int(duration or 0),now()))

async def purge_command(update,ctx,args):
    chat=update.effective_chat; msg=update.effective_message; actor=update.effective_user
    if chat.type not in ("group","supergroup"): return
    if not await can_manage(ctx.bot,chat.id,actor.id):
        return await msg.reply_text("â›” Ruxsat yoâ€˜q.")
    limit=0
    if args and args[0].isdigit(): limit=min(200,max(1,int(args[0])))
    elif msg.reply_to_message: limit=max(1,msg.message_id-msg.reply_to_message.message_id+1)
    else: return await msg.reply_text("Misol: *purge 20 yoki eski xabarga reply qilib *purge")
    deleted=0
    start=max(1,msg.message_id-limit+1)
    for mid in range(msg.message_id,start-1,-1):
        try:
            await ctx.bot.delete_message(chat.id,mid); deleted+=1
        except TelegramError: pass
    modlog(chat.id,actor.id,0,"purge",f"{deleted} xabar")

async def moderation_config_command(update,ctx,cmd,args):
    chat=update.effective_chat; msg=update.effective_message; actor=update.effective_user
    if chat.type not in ("group","supergroup"): return await msg.reply_text("Bu buyruq guruh uchun.")
    if not await can_manage(ctx.bot,chat.id,actor.id): return await msg.reply_text("â›” Ruxsat yoâ€˜q.")
    st=moderation_settings(chat.id)
    if cmd=="warnlimit":
        if not args or not args[0].isdigit() or not 1<=int(args[0])<=10: return await msg.reply_text("Misol: *warnlimit 3")
        execute("UPDATE moderation_settings SET warn_limit=? WHERE chat_id=?",(int(args[0]),chat.id)); return await msg.reply_text("âœ… Warn limiti saqlandi.")
    if cmd=="warnaction":
        if not args or args[0].lower() not in {"ban","kick","mute"}: return await msg.reply_text("Misol: *warnaction ban / kick / mute")
        execute("UPDATE moderation_settings SET warn_action=? WHERE chat_id=?",(args[0].lower(),chat.id)); return await msg.reply_text("âœ… Warn jazosi saqlandi.")
    if cmd in {"cleanservice","antirepeat"}:
        if not args or args[0].lower() not in {"on","off"}: return await msg.reply_text(f"*{cmd} on/off")
        col="clean_service" if cmd=="cleanservice" else "antirepeat"
        execute(f"UPDATE moderation_settings SET {col}=? WHERE chat_id=?",(1 if args[0].lower()=="on" else 0,chat.id)); return await msg.reply_text("âœ… Saqlandi.")
    if cmd=="modlog":
        rows=all_("SELECT * FROM moderation_log WHERE chat_id=? ORDER BY id DESC LIMIT 15",(chat.id,))
        if not rows: return await msg.reply_text("ðŸ“‹ Moderatsiya logi boâ€˜sh.")
        lines=["ðŸ“‹ SOâ€˜NGGI MODERATSIYA AMALLARI"]
        for r in rows: lines.append(f"â€¢ {r['action']} | target {r['target_id']} | admin {r['actor_id']}"+(f" | {r['reason']}" if r['reason'] else ""))
        return await msg.reply_text("\n".join(lines))

async def group_action ( update,ctx,cmd,arg ) :
    chat=update.effective_chat; u=update.effective_user; msg=update.effective_message
    ensure_group ( chat ) ; ensure_user ( u)
    if not await can_manage ( ctx.bot,chat.id,u.id ) :
        return await msg.reply_text ( "â›” Sizda bu amal uchun ruxsat yoâ€˜q.")
    target=replied ( update)
    if cmd in {"warn","unwarn","clearwarns","mute","unmute","kick","ban","unban","del","ruxsat","ruxsatsiz","admin","unadmin","approve","unapprove"} and not target:
        return await msg.reply_text ( "â†©ï¸ Foydalanuvchi xabariga reply qiling.")
    if cmd=="del":
        try: await target.delete (  ) ; await msg.delete ( )
        except TelegramError: pass
        return
    tu=target.from_user if target else None
    if tu and cmd in {"warn","mute","kick","ban"} and await protected ( ctx.bot,chat.id,tu.id ) :
        return await msg.reply_text ( "ðŸ›¡ Himoyalangan foydalanuvchi.")
    try:
        if cmd=="warn":
            reason=" ".join(arg).strip() or "Sabab koâ€˜rsatilmagan"
            execute ( """INSERT INTO warns ( chat_id,user_id,count) VALUES ( ?,?,1)
            ON CONFLICT ( chat_id,user_id) DO UPDATE SET count=count+1""", ( chat.id,tu.id ) )
            execute("INSERT INTO warn_records(chat_id,user_id,actor_id,reason,created_at) VALUES(?,?,?,?,?)",(chat.id,tu.id,u.id,reason,now()))
            n=one ( "SELECT count FROM warns WHERE chat_id=? AND user_id=?", ( chat.id,tu.id )  ) ["count"]
            st=moderation_settings(chat.id); limit=int(st["warn_limit"] or 3); action=st["warn_action"] or "ban"
            modlog(chat.id,u.id,tu.id,"warn",reason)
            if n>=limit:
                execute ( "DELETE FROM warns WHERE chat_id=? AND user_id=?", ( chat.id,tu.id ) )
                if action=="kick":
                    await ctx.bot.ban_chat_member(chat.id,tu.id); await ctx.bot.unban_chat_member(chat.id,tu.id)
                elif action=="mute":
                    sec=int(st["warn_mute_seconds"] or 3600)
                    await ctx.bot.restrict_chat_member(chat.id,tu.id,ChatPermissions(can_send_messages=False),until_date=datetime.now(timezone.utc)+timedelta(seconds=sec))
                else: await ctx.bot.ban_chat_member(chat.id,tu.id)
                modlog(chat.id,u.id,tu.id,"warn_"+action,reason)
                return await msg.reply_text(f"âš ï¸ {tu.full_name}: {limit}/{limit} warn â†’ {action}.\nSabab: {reason}")
            return await msg.reply_text(f"âš ï¸ {tu.full_name}: {n}/{limit} warn.\nSabab: {reason}")
        if cmd=="unwarn":
            execute ( "UPDATE warns SET count=MAX ( count-1,0) WHERE chat_id=? AND user_id=?", ( chat.id,tu.id ) )
        elif cmd=="clearwarns": execute ( "DELETE FROM warns WHERE chat_id=? AND user_id=?", ( chat.id,tu.id ) )
        elif cmd=="mute":
            sec=parse_duration(arg[0]) if arg else 0
            until=(datetime.now(timezone.utc)+timedelta(seconds=sec)) if sec else None
            await ctx.bot.restrict_chat_member(chat.id,tu.id,ChatPermissions(can_send_messages=False),until_date=until)
            reason=" ".join(arg[1:] if sec else arg).strip()
            modlog(chat.id,u.id,tu.id,"mute",reason,sec)
        elif cmd=="unmute":
            await ctx.bot.restrict_chat_member ( chat.id,tu.id,ChatPermissions ( can_send_messages=True,can_send_audios=True,can_send_documents=True,can_send_photos=True,can_send_videos=True,can_send_video_notes=True,can_send_voice_notes=True,can_send_polls=True,can_send_other_messages=True,can_add_web_page_previews=True,can_invite_users=True ) )
        elif cmd=="kick":
            await ctx.bot.ban_chat_member ( chat.id,tu.id ) ; await ctx.bot.unban_chat_member ( chat.id,tu.id)
        elif cmd=="ban":
            sec=parse_duration(arg[0]) if arg else 0
            until=(datetime.now(timezone.utc)+timedelta(seconds=sec)) if sec else None
            await ctx.bot.ban_chat_member(chat.id,tu.id,until_date=until)
            reason=" ".join(arg[1:] if sec else arg).strip()
            modlog(chat.id,u.id,tu.id,"ban",reason,sec)
        elif cmd=="unban": await ctx.bot.unban_chat_member ( chat.id,tu.id,only_if_banned=True)
        elif cmd=="ruxsat": execute ( "INSERT OR IGNORE INTO vadmins VALUES ( ?,? ) ", ( chat.id,tu.id ) )
        elif cmd=="ruxsatsiz": execute ( "DELETE FROM vadmins WHERE chat_id=? AND user_id=?", ( chat.id,tu.id ) )
        elif cmd=="approve": execute ( "INSERT OR IGNORE INTO approved VALUES ( ?,? ) ", ( chat.id,tu.id ) )
        elif cmd=="unapprove": execute ( "DELETE FROM approved WHERE chat_id=? AND user_id=?", ( chat.id,tu.id ) )
        elif cmd=="admin":
            await ctx.bot.promote_chat_member ( chat.id,tu.id,can_delete_messages=True,can_restrict_members=True,can_invite_users=True)
        elif cmd=="unadmin":
            await ctx.bot.promote_chat_member ( chat.id,tu.id,can_delete_messages=False,can_restrict_members=False,can_invite_users=False,can_promote_members=False,can_change_info=False,can_pin_messages=False)
        audit ( u.id,chat.id,cmd,str ( tu.id ) )
        await msg.reply_text ( "âœ… Bajarildi.")
    except TelegramError as e: await msg.reply_text ( f"âŒ Telegram: {e}")

async def settings_command ( update,ctx,cmd,args ) :
    chat=update.effective_chat; msg=update.effective_message; uid=update.effective_user.id
    ensure_group ( chat)
    if not await can_manage ( ctx.bot,chat.id,uid ) : return await msg.reply_text ( "â›” Ruxsat yoâ€˜q.")
    if cmd in ("links","antiflood","reports","welcome","goodbye" ) :
        if not args or args[0].lower ( ) not in ("on","off" ) : return await msg.reply_text ( f"*{cmd} on/off")
        execute ( f"UPDATE groups SET {cmd}=? WHERE chat_id=?", ( 1 if args[0].lower (  ) =="on" else 0,chat.id ) )
        return await msg.reply_text ( "âœ… Saqlandi.")
    if cmd=="flood":
        n=int ( args[0]) if args and args[0].isdigit ( ) else 0
        if not 3<=n<=20: return await msg.reply_text ( "*flood 3..20")
        execute ( "UPDATE groups SET flood_limit=? WHERE chat_id=?", ( n,chat.id )  ) ; return await msg.reply_text ( "âœ… Saqlandi.")
    if cmd=="setrules":
        text=" ".join ( args ) .strip ( )
        execute ( "UPDATE groups SET rules=? WHERE chat_id=?", ( text,chat.id )  ) ; return await msg.reply_text ( "âœ… Qoidalar saqlandi.")
    if cmd=="lock" and args:
        typ=args[0].lower (  ) ; r=one ( "SELECT locks FROM groups WHERE chat_id=?", ( chat.id, )  ) ; d=json.loads ( r["locks"] or "{}" ) ; d[typ]=True
        execute ( "UPDATE groups SET locks=? WHERE chat_id=?", ( json.dumps ( d ) ,chat.id )  ) ; return await msg.reply_text ( f"ðŸ”’ {typ}")
    if cmd=="unlock" and args:
        typ=args[0].lower (  ) ; r=one ( "SELECT locks FROM groups WHERE chat_id=?", ( chat.id, )  ) ; d=json.loads ( r["locks"] or "{}" ) ; d.pop ( typ,None)
        execute ( "UPDATE groups SET locks=? WHERE chat_id=?", ( json.dumps ( d ) ,chat.id )  ) ; return await msg.reply_text ( f"ðŸ”“ {typ}")
    if cmd=="blacklist" and args:
        w=" ".join ( args ) .lower (  ) ; execute ( "INSERT OR IGNORE INTO blacklist VALUES ( ?,? ) ", ( chat.id,w )  ) ; return await msg.reply_text ( "âœ… Blacklistga qoâ€˜shildi.")
    if cmd=="unblacklist" and args:
        w=" ".join ( args ) .lower (  ) ; execute ( "DELETE FROM blacklist WHERE chat_id=? AND word=?", ( chat.id,w )  ) ; return await msg.reply_text ( "âœ… Oâ€˜chirildi.")
    if cmd=="filter" and len ( args ) >=2:
        key=args[0].lower (  ) ; response=" ".join ( args[1:])
        execute ( "INSERT OR REPLACE INTO filters_ VALUES ( ?,?,? ) ", ( chat.id,key,response )  ) ; return await msg.reply_text ( "âœ… Filter saqlandi.")
    if cmd=="stop" and args:
        execute ( "DELETE FROM filters_ WHERE chat_id=? AND key=?", ( chat.id,args[0].lower (  )  )  ) ; return await msg.reply_text ( "âœ… Filter oâ€˜chirildi.")
    if cmd=="stopall": execute ( "DELETE FROM filters_ WHERE chat_id=?", ( chat.id, )  ) ; return await msg.reply_text ( "âœ… Barcha filterlar oâ€˜chirildi.")
    if cmd=="save" and len ( args ) >=2:
        execute ( "INSERT OR REPLACE INTO notes VALUES ( ?,?,? ) ", ( chat.id,args[0].lower (  ) ," ".join ( args[1:] )  )  ) ; return await msg.reply_text ( "âœ… Note saqlandi.")
    if cmd=="clear" and args:
        execute ( "DELETE FROM notes WHERE chat_id=? AND name=?", ( chat.id,args[0].lower (  )  )  ) ; return await msg.reply_text ( "âœ… Note oâ€˜chirildi.")

async def info_command ( update,ctx,cmd,args ) :
    chat=update.effective_chat; msg=update.effective_message
    if cmd=="rules":
        r=one ( "SELECT rules FROM groups WHERE chat_id=?", ( chat.id, )  ) ; return await msg.reply_text (  ( r["rules"] if r else "") or "Qoidalar hali yozilmagan.")
    if cmd=="admins":
        admins=await ctx.bot.get_chat_administrators ( chat.id ) ; va=all_ ( "SELECT user_id FROM vadmins WHERE chat_id=?", ( chat.id, ) )
        s="ðŸ‘® Telegram adminlar:\n"+"\n".join ( f"â€¢ {x.user.full_name}" for x in admins)
        if va: s+="\n\nðŸª¶ Veritas admin ID:\n"+"\n".join ( str ( x["user_id"]) for x in va)
        return await msg.reply_text ( s)
    if cmd=="warns":
        t=replied ( update ) ; uid=t.from_user.id if t else update.effective_user.id
        r=one ( "SELECT count FROM warns WHERE chat_id=? AND user_id=?", ( chat.id,uid )  ) ; return await msg.reply_text ( f"âš ï¸ Warn: {r['count'] if r else 0}/3")
    if cmd=="blacklists":
        rows=all_ ( "SELECT word FROM blacklist WHERE chat_id=? ORDER BY word", ( chat.id, )  ) ; return await msg.reply_text ( "ðŸš« "+ ( ", ".join ( r["word"] for r in rows) or "Boâ€˜sh" ) )
    if cmd=="locks":
        r=one ( "SELECT locks FROM groups WHERE chat_id=?", ( chat.id, )  ) ; d=json.loads ( r["locks"] or "{}") if r else {}
        return await msg.reply_text ( "ðŸ” "+ ( ", ".join ( d.keys (  ) ) or "Lock yoâ€˜q" ) )
    if cmd=="approved":
        rows=all_ ( "SELECT user_id FROM approved WHERE chat_id=?", ( chat.id, )  ) ; return await msg.reply_text ( "âœ… "+ ( ", ".join ( str ( r["user_id"]) for r in rows) or "Boâ€˜sh" ) )
    if cmd=="filters":
        rows=all_ ( "SELECT key FROM filters_ WHERE chat_id=?", ( chat.id, )  ) ; return await msg.reply_text ( "ðŸ’¬ "+ ( ", ".join ( r["key"] for r in rows) or "Boâ€˜sh" ) )
    if cmd=="notes":
        rows=all_ ( "SELECT name FROM notes WHERE chat_id=?", ( chat.id, )  ) ; return await msg.reply_text ( "ðŸ“ "+ ( ", ".join ( r["name"] for r in rows) or "Boâ€˜sh" ) )
    if cmd=="get" and args:
        r=one ( "SELECT text FROM notes WHERE chat_id=? AND name=?", ( chat.id,args[0].lower (  )  )  ) ; return await msg.reply_text ( r["text"] if r else "Topilmadi.")
    if cmd=="aktiv":
        n=min ( 50,max ( 1,int ( args[0]) if args and args[0].isdigit ( ) else 10 ) )
        return await msg.reply_text ( global_active_text ( min ( n,10 ) ) )

async def report_cmd ( update,ctx ) :
    if not replied ( update ) : return await update.effective_message.reply_text ( "â†©ï¸ Shikoyat qilinadigan xabarga reply qiling.")
    r=one ( "SELECT reports FROM groups WHERE chat_id=?", ( update.effective_chat.id, ) )
    if r and not r["reports"]: return
    admins=await ctx.bot.get_chat_administrators ( update.effective_chat.id)
    tags=" ".join ( "@"+a.user.username for a in admins if a.user.username)
    await update.effective_message.reply_text ( f"ðŸ“¢ Report: {tags or 'adminlar'}")

async def gift_send ( update,ctx,args ) :
    t=replied ( update)
    if not t or not t.from_user: return await update.effective_message.reply_text ( "â†©ï¸ Gift oluvchining xabariga reply qiling.")
    sender=update.effective_user.id; target=t.from_user.id
    try:
        gifts=await ctx.bot.get_available_gifts ( )
        gl=list ( gifts.gifts)
    except Exception as e: return await update.effective_message.reply_text ( f"âŒ Gift roâ€˜yxati olinmadi: {e}")
    price=int ( args[0]) if args and args[0].isdigit ( ) else None
    candidates=[g for g in gl if (price is None or getattr ( g,"star_count",None ) ==price) and (getattr ( g,"remaining_count",None) is None or getattr ( g,"remaining_count",0 ) >0 ) ]
    if not candidates:
        prices=sorted ( {getattr ( g,"star_count",0) for g in gl if getattr ( g,"star_count",0 ) })
        return await update.effective_message.reply_text ( "ðŸŽ Mavjud narxlar: "+", ".join ( map ( str,prices[:30] )  ) )
    g=candidates[0]; cost=int ( g.star_count)
    if wallet ( sender ) <cost: return await update.effective_message.reply_text ( f"â­ Kredit yetarli emas. Kerak: {cost}, sizda: {wallet ( sender ) }")
    tx_ref=f"gift:{sender}:{target}:{now()}:{random.randint(100000,999999)}"
    if not wallet_change ( sender,-cost,"gift_pending",target,ref=tx_ref,meta={"gift_id":str ( g.id ) } ) : return
    try:
        await ctx.bot.send_gift ( user_id=target,gift_id=g.id,text=f"ðŸŽ Veritas orqali {update.effective_user.first_name}dan sovgâ€˜a")
        execute ( "UPDATE tx SET kind='gift' WHERE user_id=? AND ref=? AND kind='gift_pending'", ( sender,tx_ref ) )
        await update.effective_message.reply_text ( f"âœ… Haqiqiy Telegram Gift yuborildi: {cost} â­")
    except Exception as e:
        wallet_change ( sender,cost,"gift_rollback",target)
        await update.effective_message.reply_text ( f"âŒ Gift yuborilmadi, kredit qaytarildi.\n{e}")

async def premium_send ( update,ctx,args ) :
    t=replied ( update)
    if not t or not t.from_user: return await update.effective_message.reply_text ( "â†©ï¸ Premium oluvchiga reply qiling.")
    m=int ( args[0]) if args and args[0].isdigit ( ) else 0
    if m not in PREMIUM: return await update.effective_message.reply_text ( "*premium 3 / 6 / 12")
    cost=PREMIUM[m]; sender=update.effective_user.id; target=t.from_user.id
    if wallet ( sender ) <cost: return await update.effective_message.reply_text ( f"â­ Kredit yetarli emas. Kerak: {cost}")
    tx_ref=f"premium:{sender}:{target}:{now()}:{random.randint(100000,999999)}"
    if not wallet_change ( sender,-cost,"premium_pending",target,ref=tx_ref ) : return
    try:
        await ctx.bot.gift_premium_subscription ( user_id=target,month_count=m,star_count=cost,text="ðŸ’Ž Veritas orqali Premium sovgâ€˜a")
        execute ( "UPDATE tx SET kind='premium' WHERE user_id=? AND ref=? AND kind='premium_pending'", ( sender,tx_ref ) )
        await update.effective_message.reply_text ( f"âœ… {m} oylik Telegram Premium yuborildi.")
    except Exception as e:
        wallet_change ( sender,cost,"premium_rollback",target)
        await update.effective_message.reply_text ( f"âŒ Premium yuborilmadi, kredit qaytarildi.\n{e}")

async def superadmin_command ( update,ctx,cmd ) :
    msg=update.effective_message; actor=update.effective_user
    if not msg or not actor: return
    if cmd=="superadmins":
        rows=all_ ( "SELECT user_id,added_by,created_at FROM super_admins ORDER BY created_at" )
        lines=["ðŸ‘‘ SUPER EGALAR"]
        creator_names={5859289233:"Sakranum",7056675943:"Vasatiya"}
        for sid in sorted ( SUPER_OWNERS ): lines.append ( f"â€¢ {creator_names.get(sid,'Super Ega')} â€” {sid}" )
        lines.append ( "\nðŸ›¡ SUPER ADMINLAR" )
        if not rows: lines.append ( "â€¢ Hozircha yoâ€˜q" )
        else:
            for r in rows:
                try:
                    ch=await ctx.bot.get_chat ( r["user_id"] ); name=ch.full_name or ch.title or str(r["user_id"])
                except Exception: name=str ( r["user_id"] )
                lines.append ( f"â€¢ {name} â€” {r['user_id']}" )
        return await msg.reply_text ( "\n".join ( lines ) )
    # Xavfsizlik: tayinlash va olib tashlash faqat haqiqiy Super Ega tomonidan.
    if actor.id not in SUPER_OWNERS:
        return await msg.reply_text ( "â›” Super Admin qoâ€˜shish yoki olish faqat Super Ega uchun." )
    t=replied ( update )
    if not t or not t.from_user:
        return await msg.reply_text ( "â†©ï¸ Foydalanuvchining xabariga reply qiling.\nMisol: *superadmin" if cmd=="superadmin" else "â†©ï¸ Super Admin xabariga reply qilib *unsuperadmin yozing." )
    target=t.from_user
    ensure_user ( target )
    if target.id in SUPER_OWNERS:
        return await msg.reply_text ( "ðŸ‘‘ Bu foydalanuvchi Super Ega. Uning huquqi bu buyruq bilan oâ€˜zgarmaydi." )
    if cmd=="superadmin":
        execute ( "INSERT INTO super_admins ( user_id,added_by,created_at) VALUES ( ?,?,? ) ON CONFLICT ( user_id ) DO UPDATE SET added_by=excluded.added_by,created_at=excluded.created_at", ( target.id,actor.id,now ( ) ) )
        audit ( actor.id,update.effective_chat.id,"superadmin_add",str ( target.id ) )
        return await msg.reply_text ( f"ðŸ›¡ {target.full_name} Super Admin qilindi.\nðŸ†” {target.id}" )
    execute ( "DELETE FROM super_admins WHERE user_id=?", ( target.id, ) )
    audit ( actor.id,update.effective_chat.id,"superadmin_remove",str ( target.id ) )
    return await msg.reply_text ( f"âœ… {target.full_name} Super Adminlikdan olindi.\nðŸ†” {target.id}" )

async def ai_premium_gift_command(update, ctx):
    msg = update.effective_message
    actor = update.effective_user
    if not actor:
        return
    t = replied(update)
    if not t or not t.from_user:
        return await msg.reply_text("â†©ï¸ AI Premium oluvchining xabariga reply qilib *ai.p yozing.")
    target = t.from_user
    if target.is_bot:
        return await msg.reply_text("âŒ Botga AI Premium sovgâ€˜a qilib boâ€˜lmaydi.")
    if target.id == actor.id:
        return await msg.reply_text("âŒ AI Premiumni oâ€˜zingizga *ai.p orqali sovgâ€˜a qilib boâ€˜lmaydi.")
    ensure_user(target)
    # Super boshqaruv AI'dan allaqachon cheksiz foydalanadi.
    if is_super(target.id):
        return await msg.reply_text(f"ðŸ‘‘ {target.full_name} uchun AI allaqachon cheksiz faol.")
    ts = now()
    with db() as c:
        r = c.execute("SELECT wallet FROM users WHERE user_id=?", (actor.id,)).fetchone()
        bal = int(r["wallet"]) if r else 0
        if bal < AI_PRIVATE_PRICE:
            return await msg.reply_text(f"âŒ Kredit yetarli emas. Kerak: {AI_PRIVATE_PRICE} â­\nBalans: {bal} â­")
        old = c.execute("SELECT paid_until FROM ai_user_subscriptions WHERE user_id=?", (target.id,)).fetchone()
        old_until = int(old["paid_until"]) if old else 0
        until = max(ts, old_until) + AI_PRIVATE_DAYS * 86400
        c.execute("UPDATE users SET wallet=wallet-? WHERE user_id=?", (AI_PRIVATE_PRICE, actor.id))
        c.execute("INSERT INTO tx(user_id,kind,amount,target_id,ref,created_at,meta) VALUES(?,?,?,?,?,?,?)",
                  (actor.id, "ai_private_gift_30d", -AI_PRIVATE_PRICE, target.id, None, ts, json.dumps({"days": AI_PRIVATE_DAYS}, ensure_ascii=False)))
        c.execute("INSERT INTO ai_user_subscriptions(user_id,paid_until,updated_at) VALUES(?,?,?) "
                  "ON CONFLICT(user_id) DO UPDATE SET paid_until=excluded.paid_until,updated_at=excluded.updated_at",
                  (target.id, until, ts))
    audit(actor.id, update.effective_chat.id, "ai_private_gift", f"target={target.id},days={AI_PRIVATE_DAYS}")
    return await msg.reply_text(
        f"ðŸŽ {target.full_name}ga Veritas AI Premium berildi.\n"
        f"ðŸ’Ž {AI_PRIVATE_PRICE} â­ yechildi\n"
        f"ðŸ“… {AI_PRIVATE_DAYS} kun â€” {fmt_until(until)} gacha\n"
        f"â­ Qolgan balans: {wallet(actor.id)} â­"
    )

async def star_text_router ( update,ctx ) :
    msg=update.effective_message
    if not msg or not msg.text or not msg.text.startswith ( "*" ) : return
    ensure_user ( update.effective_user)
    if update.effective_chat.type in ("group","supergroup" ) : ensure_group ( update.effective_chat)
    parts=msg.text[1:].strip (  ) .split ( )
    if not parts: return
    cmd=parts[0].lower (  ) ; args=parts[1:]
    if cmd=="help": return await cmd_help ( update,ctx)
    if cmd=="id": return await cmd_id ( update,ctx)
    if cmd=="men": return await show_me ( update,ctx)
    if cmd=="ak": return await msg.reply_text ( global_active_text ( 10 ) )
    if cmd in {"unvon","unvonoff"}:
        return await title_command ( update,ctx,cmd,args)
    if cmd=="top" and args and args[0]=="10":
        return await top10_menu ( update,ctx)
    if cmd=="topup":
        a=int ( args[0]) if args and args[0].isdigit ( ) else 0
        return await topup ( update,ctx,a)
    if cmd=="stars":
        return await stars_cmd ( update,ctx,args)
    if cmd=="post":
        return await broadcast_command ( update,ctx,args)
    if cmd=="ai.p":
        return await ai_premium_gift_command ( update,ctx)
    if cmd in {"superadmin","unsuperadmin","superadmins"}:
        return await superadmin_command ( update,ctx,cmd)
    if cmd in {"ad.book","unad.book","bookadmins","ad.hadis","unad.hadis","hadisadmins"}:
        return await content_admin_command ( update,ctx,cmd)
    if cmd=="qadr":
        return await msg.reply_text(qadr_top_text(10))
    if cmd=="hadis":
        return await hadith_command ( update,ctx,args)
    if cmd=="add.hadis":
        return await add_hadith_command ( update,ctx)
    if cmd=="del.hadis":
        return await delete_hadith_command ( update,ctx,args)
    if cmd=="ai":
        if update.effective_chat.type not in ("group","supergroup" ) :
            return await msg.reply_text ( "ðŸ¤– Shaxsiy Veritas AI uchun bosh menyudagi Â«Veritas AIÂ» tugmasidan foydalaning." )
        until=ai_group_until ( update.effective_chat.id )
        status=( "âœ… FAOL\nðŸ“… "+fmt_until ( until ) ) if until>now ( ) else "âŒ FAOL EMAS"
        trial=("ðŸŽ Birinchi 30 kun â€” BEPUL" if not ai_group_trial_used ( update.effective_chat.id ) else "â­ Keyingi 30 kun â€” 100 â­")
        return await msg.reply_text ( f"ðŸ¤– VERITAS AI â€” GURUH\n\n{status}\n\n{trial}",reply_markup=ai_group_menu ( update.effective_chat.id,update.effective_user.id ) )
    if update.effective_chat.type not in ("group","supergroup" ) :
        return await msg.reply_text ( "Bu buyruq guruh uchun.")
    if cmd=="purge": return await purge_command(update,ctx,args)
    if cmd in {"warnlimit","warnaction","cleanservice","antirepeat","modlog"}:
        return await moderation_config_command(update,ctx,cmd,args)
    if cmd=="pin":
        if not await can_manage(ctx.bot,update.effective_chat.id,update.effective_user.id): return await msg.reply_text("â›” Ruxsat yoâ€˜q.")
        t=replied(update)
        if not t: return await msg.reply_text("â†©ï¸ Pin qilinadigan xabarga reply qiling.")
        await ctx.bot.pin_chat_message(update.effective_chat.id,t.message_id); modlog(update.effective_chat.id,update.effective_user.id,0,"pin"); return await msg.reply_text("ðŸ“Œ Pin qilindi.")
    if cmd=="unpin":
        if not await can_manage(ctx.bot,update.effective_chat.id,update.effective_user.id): return await msg.reply_text("â›” Ruxsat yoâ€˜q.")
        await ctx.bot.unpin_chat_message(update.effective_chat.id); modlog(update.effective_chat.id,update.effective_user.id,0,"unpin"); return await msg.reply_text("ðŸ“Œ Pin olib tashlandi.")
    if cmd in {"warn","unwarn","clearwarns","mute","unmute","kick","ban","unban","del","ruxsat","ruxsatsiz","admin","unadmin","approve","unapprove"}:
        return await group_action ( update,ctx,cmd,args)
    if cmd in {"links","antiflood","reports","welcome","goodbye","flood","setrules","lock","unlock","blacklist","unblacklist","filter","stop","stopall","save","clear"}:
        return await settings_command ( update,ctx,cmd,args)
    if cmd in {"rules","admins","warns","blacklists","locks","approved","filters","notes","get","aktiv"}:
        return await info_command ( update,ctx,cmd,args)
    if cmd=="report": return await report_cmd ( update,ctx)
    if cmd=="give": return await gift_send ( update,ctx,args)
    if cmd=="premium": return await premium_send ( update,ctx,args)
    if cmd=="join":
        g=one ( "SELECT id FROM giveaways WHERE chat_id=? AND status='open' AND end_at>? ORDER BY id DESC LIMIT 1", ( update.effective_chat.id,now (  )  ) )
        if not g: return await msg.reply_text ( "Faol konkurs yoâ€˜q.")
        execute ( "INSERT OR IGNORE INTO giveaway_entries VALUES ( ?,? ) ", ( g["id"],update.effective_user.id )  ) ; return await msg.reply_text ( "ðŸŽ‰ Ishtirok qabul qilindi.")
    if cmd=="giveaway":
        if not await can_manage ( ctx.bot,update.effective_chat.id,update.effective_user.id ) : return await msg.reply_text ( "â›” Ruxsat yoâ€˜q.")
        if len ( args ) <4 or args[0]!="gift" or not all ( x.isdigit ( ) for x in args[1:4] ) : return await msg.reply_text ( "*giveaway gift <narx> <daq> <gâ€˜oliblar>")
        price,mins,wins=map ( int,args[1:4])
        execute ( "INSERT INTO giveaways ( chat_id,creator_id,kind,prize,winners,end_at,created_at) VALUES ( ?,?,?,?,?,?,? ) ",
                (update.effective_chat.id,update.effective_user.id,"gift",str ( price ) ,wins,now (  ) +mins*60,now (  )  ) )
        return await msg.reply_text ( f"ðŸŽ‰ Konkurs ochildi: {price} â­ Gift | {wins} gâ€˜olib | {mins} daqiqa\n*join bilan qatnashing.")


def _norm_rebus_answer(text):
    text=(text or "").lower().strip()
    text=text.replace("Ê»","'").replace("â€™","'").replace("`","'")
    return re.sub(r"[^a-z0-9Ð°-ÑÑ‘Ò›Ò“Ò³Ñž' ]+","",text,flags=re.I).strip()

def _rebus_plan_sync(answer):
    answer=(answer or "").strip()
    prompt=(
        "Telegram uchun rasmli rebus dizaynini tuzing. "
        f"Rebusning ANIQ JAVOBI: {answer}. "
        "Javobni oâ€˜zgartirmang. Faqat JSON qaytaring: "
        '{"hint":"...", "image_prompt":"..."}. '
        "image_prompt rasm generatoriga moâ€˜ljallangan boâ€˜lsin: 1:1 kvadrat, chiroyli, kitobiy va toza dizayn; "
        "javobni rasmlar, belgilar, harflarni qoâ€˜shish/ayirish yoki vizual mantiq orqali ifodalasin. "
        "JAVOBNING Oâ€˜ZINI rasmga yozmasin. Yuqorida faqat 'VERITAS REBUS' yozuvi boâ€˜lishi mumkin."
    )
    raw=_openai_response_sync(prompt).strip()
    raw=re.sub(r"^```(?:json)?\\s*|\\s*```$","",raw,flags=re.I|re.S)
    try:
        data=json.loads(raw)
    except Exception:
        m=re.search(r"\\{.*\\}",raw,re.S)
        if not m: raise RuntimeError("AI rebus rejasini JSON koâ€˜rinishda qaytarmadi")
        data=json.loads(m.group(0))
    hint=str(data.get("hint","")).strip()
    image_prompt=str(data.get("image_prompt","")).strip()
    if not image_prompt:
        raise RuntimeError("AI rebus rejasi toâ€˜liq emas")
    return answer,hint,image_prompt

def _rebus_image_sync(image_prompt):
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY sozlanmagan")
    payload=json.dumps({
        "model":REBUS_IMAGE_MODEL,
        "prompt":image_prompt,
        "size":"1024x1024",
        "quality":"medium"
    },ensure_ascii=False).encode("utf-8")
    req=urllib.request.Request(
        "https://api.openai.com/v1/images/generations",
        data=payload,
        headers={"Authorization":f"Bearer {OPENAI_API_KEY}","Content-Type":"application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req,timeout=180) as resp:
        data=json.loads(resp.read().decode("utf-8"))
    item=(data.get("data") or [{}])[0]
    if item.get("b64_json"):
        return base64.b64decode(item["b64_json"])
    if item.get("url"):
        with urllib.request.urlopen(item["url"],timeout=120) as resp:
            return resp.read()
    raise RuntimeError("Rasm generatori rasm qaytarmadi")

async def _remember_rebus_channel_from_group(ctx,group_id):
    """Discussion groupdan unga bogâ€˜langan kanalni topib, DBga saqlaydi."""
    try:
        gr=await ctx.bot.get_chat(group_id)
        channel_id=getattr(gr,"linked_chat_id",None)
        if not channel_id:
            return None
        ch=await ctx.bot.get_chat(channel_id)
        me=await ctx.bot.get_chat_member(channel_id,ctx.bot.id)
        if me.status not in (ChatMemberStatus.ADMINISTRATOR,ChatMemberStatus.OWNER):
            return None
        execute(
            "INSERT INTO rebus_group_channels(group_id,channel_id,channel_title,updated_at) VALUES(?,?,?,?) "
            "ON CONFLICT(group_id) DO UPDATE SET channel_id=excluded.channel_id,"
            "channel_title=excluded.channel_title,updated_at=excluded.updated_at",
            (group_id,channel_id,ch.title or str(channel_id),now())
        )
        return channel_id
    except Exception:
        return None

async def _start_group_rebus_flow(update,ctx):
    msg=update.effective_message; u=update.effective_user; chat=update.effective_chat
    if not msg or not u or chat.type not in ("group","supergroup"):
        return False
    if not msg.reply_to_message or not msg.reply_to_message.from_user or msg.reply_to_message.from_user.id!=ctx.bot.id:
        return False
    if (msg.text or "").strip().lower()!="*rebus":
        return False
    if not is_super(u.id):
        await msg.reply_text("â›” AI Rebus yaratish hozircha Super Ega yoki Super Admin uchun.")
        return True

    # Kanal bogâ€˜langan va Veritas u yerda admin boâ€˜lsa â€” kanalga.
    # Aks holda â€” rebus bevosita shu guruhga joylanadi.
    channel_id=await _remember_rebus_channel_from_group(ctx,chat.id)
    target_chat_id=int(channel_id or chat.id)
    STATE[u.id]={
        "mode":"rebus_group_count",
        "group_id":chat.id,
        "group_title":chat.title or str(chat.id),
        "target_chat_id":target_chat_id,
        "answers":[]
    }
    try:
        place="bogâ€˜langan kanalga" if channel_id else "shu guruhning oâ€˜ziga"
        await ctx.bot.send_message(
            u.id,
            f"ðŸ§© AI REBUS MUSOBAQASI\n\nðŸ‘¥ Guruh: {chat.title or chat.id}\n"
            f"ðŸ“ Rebuslar: {place}\n\n"
            "Nechta rebus oâ€˜tkazilsin?\nMasalan: 5 yoki 10"
        )
        await msg.reply_text("ðŸ“© Shaxsiy chatga yubordim. Rebuslar sonini oâ€˜sha yerda yozing.")
    except TelegramError:
        STATE.pop(u.id,None)
        await msg.reply_text("ðŸ“© Avval Veritasning shaxsiy chatiga kirib /start bosing, keyin *rebus ni qayta yuboring.")
    return True

async def _create_and_post_rebus(ctx,uid,target_chat_id,group_id,answer_text,progress_chat_id,session_id=0,item_no=0):
    try:
        answer,hint,image_prompt=await asyncio.to_thread(_rebus_plan_sync,answer_text)
        image_bytes=await asyncio.to_thread(_rebus_image_sync,image_prompt)
        with db() as c:
            cur=c.execute(
                "INSERT INTO rebuses (creator_id,channel_id,answer_group_id,answer,answer_norm,hint,created_at) VALUES (?,?,?,?,?,?,?)",
                (uid,target_chat_id,group_id,answer,_norm_rebus_answer(answer),hint,now())
            )
            rid=cur.lastrowid
            if session_id and item_no:
                c.execute(
                    "UPDATE rebus_session_items SET rebus_id=?,status='active' WHERE session_id=? AND item_no=?",
                    (rid,session_id,item_no)
                )
                c.execute("UPDATE rebus_sessions SET current_no=? WHERE id=?",(item_no,session_id))
        caption=(
            f"ðŸ§© VERITAS REBUS #{rid}"
            + (f" â€” {item_no}" if session_id else "") +
            "\n\nRasmga qarab yashiringan soâ€˜z yoki iborani toping!\n"
            "ðŸ’¬ Javobni guruhga yozing."
        )
        if hint:
            caption+=f"\n\nðŸ’¡ Ishora: {hint}"
        sent=await ctx.bot.send_photo(
            chat_id=target_chat_id, photo=io.BytesIO(image_bytes), caption=caption
        )
        execute("UPDATE rebuses SET channel_message_id=? WHERE id=?",(sent.message_id,rid))
        if progress_chat_id:
            where="kanalga" if target_chat_id!=group_id else "guruhga"
            await ctx.bot.send_message(
                progress_chat_id,
                f"âœ… {item_no if item_no else ''}-rebus {where} joylandi. Javob guruhda tekshiriladi."
            )
        return rid
    except Exception:
        log.exception("AI rebus yaratish xatosi")
        if session_id and item_no:
            execute("UPDATE rebus_session_items SET status='error' WHERE session_id=? AND item_no=?",(session_id,item_no))
        if progress_chat_id:
            await ctx.bot.send_message(progress_chat_id,"âš ï¸ Rebus yaratishda xato boâ€˜ldi. Qayta urinib koâ€˜ring.")
        return 0

async def _launch_session_item(ctx,session_id,item_no):
    ses=one("SELECT * FROM rebus_sessions WHERE id=? AND status='active'",(session_id,))
    item=one("SELECT * FROM rebus_session_items WHERE session_id=? AND item_no=?",(session_id,item_no))
    if not ses or not item: return
    await _create_and_post_rebus(
        ctx,int(ses["creator_id"]),int(ses["target_chat_id"]),int(ses["group_id"]),
        item["answer"],int(ses["creator_id"]),session_id,item_no
    )

async def _finish_rebus_session(ctx,session_id,group_id):
    execute("UPDATE rebus_sessions SET status='done' WHERE id=?",(session_id,))
    scores=all_(
        "SELECT first_name,wins FROM rebus_session_scores WHERE session_id=? ORDER BY wins DESC, first_name COLLATE NOCASE",
        (session_id,)
    )
    if scores:
        lines=["ðŸ REBUS MUSOBAQASI YAKUNLANDI",""]
        for i,r in enumerate(scores,1):
            lines.append(f"{i}. {r['first_name'] or 'Ishtirokchi'} â€” {r['wins']} ta")
        await ctx.bot.send_message(group_id,"\n".join(lines))
    else:
        await ctx.bot.send_message(group_id,"ðŸ Rebus musobaqasi yakunlandi.")

async def _check_rebus_answer(update,ctx):
    msg=update.effective_message; u=update.effective_user; chat=update.effective_chat
    if not msg or not u or u.is_bot or not msg.text or chat.type not in ("group","supergroup"):
        return False
    r=one(
        "SELECT * FROM rebuses WHERE answer_group_id=? AND status='active' ORDER BY id DESC LIMIT 1",
        (chat.id,)
    )
    if not r: return False
    guess=_norm_rebus_answer(msg.text)
    if not guess or guess!=r["answer_norm"]:
        return False

    with db() as c:
        cur=c.execute(
            "UPDATE rebuses SET status='solved',winner_id=?,solved_at=? WHERE id=? AND status='active'",
            (u.id,now(),r["id"])
        )
        if cur.rowcount!=1: return False
        c.execute(
            "INSERT INTO members (chat_id,user_id,xp,messages,daily,weekly,last_day,last_week) VALUES (?,?,10,0,0,0,'','') "
            "ON CONFLICT(chat_id,user_id) DO UPDATE SET xp=xp+10",
            (chat.id,u.id)
        )
        item=c.execute(
            "SELECT session_id,item_no FROM rebus_session_items WHERE rebus_id=?",(r["id"],)
        ).fetchone()
        if item:
            c.execute(
                "UPDATE rebus_session_items SET status='solved' WHERE session_id=? AND item_no=?",
                (item["session_id"],item["item_no"])
            )
            c.execute(
                "INSERT INTO rebus_session_scores(session_id,user_id,first_name,wins) VALUES(?,?,?,1) "
                "ON CONFLICT(session_id,user_id) DO UPDATE SET wins=wins+1,first_name=excluded.first_name",
                (item["session_id"],u.id,u.first_name or "")
            )

    await msg.reply_text(
        f"ðŸŽ‰ TOâ€˜Gâ€˜RI!\n\nâœ… Javob: {r['answer']}\nðŸ† {u.first_name} birinchi topdi!\nâœ¨ +10 XP"
    )

    # Javobi topilgan eski rebus endi kerak emas â€” oâ€˜chiriladi.
    if int(r["channel_message_id"] or 0):
        try:
            await ctx.bot.delete_message(int(r["channel_id"]),int(r["channel_message_id"]))
        except TelegramError:
            log.warning("Topilgan rebus xabarini oâ€˜chirib boâ€˜lmadi: %s",r["id"])

    if item:
        session_id=int(item["session_id"]); current_no=int(item["item_no"])
        ses=one("SELECT * FROM rebus_sessions WHERE id=?",(session_id,))
        if ses and ses["status"]=="active":
            total=int(ses["total"])
            if current_no < total:
                next_no=current_no+1
                await msg.reply_text(f"â³ {next_no}/{total}-rebus tayyorlanmoqda...")
                task=asyncio.create_task(_launch_session_item(ctx,session_id,next_no))
                def _next_rebus_done(t):
                    try: t.result()
                    except asyncio.CancelledError: pass
                    except Exception: log.exception("Next rebus task failed")
                task.add_done_callback(_next_rebus_done)
            else:
                await _finish_rebus_session(ctx,session_id,chat.id)
    return True

def media_type ( msg ) :
    if msg.photo:return "photo"
    if msg.video:return "video"
    if msg.sticker:return "sticker"
    if msg.animation:return "animation"
    if msg.document:return "document"
    if msg.voice:return "voice"
    if msg.audio:return "audio"
    return None

def _openai_response_sync ( prompt ) :
    payload=json.dumps({
        "model":OPENAI_MODEL,
        "instructions":(
            "Siz Veritas Botsiz. Oâ€˜zingiz haqingizda soâ€˜rashsa javobni tabiiy ravishda â€˜Men Veritas Botmanâ€™ deb boshlang. "
            "Veritasni yaratgan Super Egalar: Sakranum (Telegram ID 5859289233) va Vasatiya (Telegram ID 7056675943). Kim yaratgan, egasi yoki Super Egalari kim deb soâ€˜ralsa shu ikki nomni ayting. "
            "Telegram ID 5859289233 dan yozayotgan odamni Sakranum, 7056675943 dan yozayotgan odamni Vasatiya deb taning. Super Adminlar ham global boshqaruv vakolatiga ega, ammo Super Admin tayinlash/olish faqat Super Egalarga tegishli. "
            "Veritas â€” Telegram uchun guruh boshqaruvi va AI yordamchi bot. Shaxsiy Veritas AI Premium birinchi 30 kun bepul, keyingi 30 kun 10 Stars. "
            "Guruh Veritas AI birinchi 30 kun bepul, keyingi 30 kun 100 Stars. Super Ega guruh AI sini bepul 1, 7 yoki 30 kunga yoqa oladi. "
            "Shaxsiy AI Premium va guruh AI obunasi alohida. Veritasda Vasatiya kutubxonasi bor: PDF/audio kitoblar, qidiruv, kategoriya, tillar, sevimlilar va kitob tahriri. "
            "Kutubxonadagi PDF kitobdan AI yordamida 5, 10 yoki 20 ta Telegram Quiz testi tuzib, foydalanuvchi admin boâ€˜lgan Veritas guruhiga yuborish mumkin. "
            "Veritasda Sahih Hadislar boâ€˜limi, hadis qidirish/random hadis va hadis adminlari mavjud. Guruh boshqaruvida warn, mute, kick, ban, blacklist, links, lock, antiflood, report, welcome/goodbye, filter, notes, rules, faollik va TOP funksiyalari bor. "
            "Kabinetda Stars krediti bor. Telegram Gift va Telegram Premium sovgâ€˜a qilish funksiyalari Veritas AI Premiumdan boshqa xizmat. *help yordam markazini ochadi, *ai guruh AI holati/tariflarini koâ€˜rsatadi. "
            "Mavjud boâ€˜lmagan Veritas funksiyasini uydirmang. Aniq bilmagan sozlama boâ€˜lsa *help yoki menyuni tekshirishni ayting. "
            "Foydalanuvchi qaysi tilda yozsa, asosan oâ€˜sha tilda javob bering. Javob Telegram uchun aniq va ortiqcha uzun boâ€˜lmasin. "
            "Diniy, tibbiy, huquqiy yoki moliyaviy mavzularda noaniqlik boâ€˜lsa buni ochiq ayting."
        ),
        "input":prompt,
        "max_output_tokens":700
    },ensure_ascii=False).encode("utf-8")
    req=urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=payload,
        headers={"Authorization":f"Bearer {OPENAI_API_KEY}","Content-Type":"application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req,timeout=45) as resp:
        data=json.loads(resp.read().decode("utf-8"))
    if data.get("output_text"):
        return str(data["output_text"]).strip()
    parts=[]
    for item in data.get("output",[]):
        for content in item.get("content",[]):
            if content.get("type")=="output_text" and content.get("text"):
                parts.append(content["text"])
    return "\n".join(parts).strip()



def _openai_image_response_sync(image_bytes, mime_type, user_text):
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY sozlanmagan")
    import base64 as _b64
    data_url=f"data:{mime_type};base64,"+_b64.b64encode(image_bytes).decode("ascii")
    payload=json.dumps({
        "model":OPENAI_MODEL,
        "instructions":(
            "Siz Veritas Botsiz. Oâ€˜zingiz haqingizda soâ€˜rashsa â€˜Men Veritas Botmanâ€™ deb boshlang. "
            "Veritasni yaratgan Super Egalar Sakranum (5859289233) va Vasatiya (7056675943). Kim yaratgan deb soâ€˜ralsa shu ikki nomni ayting. "
            "Foydalanuvchi yuborgan rasmni diqqat bilan koâ€˜ring. Undagi matn, jadval, diagramma, kitob sahifasi "
            "yoki boshqa koâ€˜rinadigan maâ€™lumotni tahlil qiling. Koâ€˜rinmagan narsani uydirmang. "
            "Foydalanuvchi qaysi tilda yozsa oâ€˜sha tilda javob bering."
        ),
        "input":[{
            "role":"user",
            "content":[
                {"type":"input_image","image_url":data_url,"detail":"auto"},
                {"type":"input_text","text":user_text or "Bu rasmni koâ€˜rib, undagi maâ€™lumotni tushuntirib bering."}
            ]
        }],
        "max_output_tokens":900
    },ensure_ascii=False).encode("utf-8")
    req=urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=payload,
        headers={"Authorization":f"Bearer {OPENAI_API_KEY}","Content-Type":"application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req,timeout=90) as resp:
        data=json.loads(resp.read().decode("utf-8"))
    return _extract_response_text(data) or "Rasm tahlil qilindi, lekin javob hosil boâ€˜lmadi."

async def private_ai_media_reply(update,ctx):
    if ctx.user_data.get("owner_consumed_message_id")==getattr(update.effective_message,"message_id",None):
        return

    msg=update.effective_message; u=update.effective_user; chat=update.effective_chat
    if not msg or not u or chat.type!="private" or u.is_bot:
        return
    if STATE.get(u.id):
        return
    # Only image support in this first safe phase; PDF large-file downloader follows separately.
    photo = msg.photo[-1] if msg.photo else None
    image_doc = None
    if msg.document and (msg.document.mime_type or "").lower().startswith("image/"):
        image_doc=msg.document
    if not photo and not image_doc:
        return
    ensure_user(u)
    if not ai_user_active(u.id):
        kb=InlineKeyboardMarkup([[InlineKeyboardButton("ðŸ’Ž 10 â­ â€” 30 kun",callback_data="aipbuy")],
                                 [InlineKeyboardButton("â­ Hisobni toâ€˜ldirish",callback_data="wallet")]])
        return await msg.reply_text("ðŸ”’ Rasmni Veritas AI bilan tahlil qilish AI Premium uchun.\n\nðŸ’Ž 10 â­ â€” 30 kun",reply_markup=kb)
    if not OPENAI_API_KEY:
        return await msg.reply_text("âš ï¸ Veritas AI kaliti sozlanmagan.")
    try:
        await ctx.bot.send_chat_action(chat.id,"typing")
        obj=photo or image_doc
        tgfile=await ctx.bot.get_file(obj.file_id)
        raw=bytes(await tgfile.download_as_bytearray())
        mime=(getattr(image_doc,"mime_type",None) or "image/jpeg")
        prompt=(msg.caption or "").strip() or "Bu rasmni koâ€˜rib, undagi maâ€™lumotni tushuntirib bering."
        answer=await asyncio.to_thread(_openai_image_response_sync,raw,mime,prompt)
        for i in range(0,len(answer),4000):
            await msg.reply_text(answer[i:i+4000])
    except Exception as e:
        log.exception("Private AI image error: %s",e)
        await msg.reply_text("âš ï¸ Rasmni tahlil qilishda xatolik boâ€˜ldi.")


def _openai_upload_pdf_sync ( pdf_bytes,filename ) :
    boundary="----VeritasBoundary"+str ( int ( time.time ( ) *1000 ) )
    safe=(filename or "book.pdf").replace('"','').replace("\r","").replace("\n","")
    chunks=[]
    def add ( x ) : chunks.append ( x.encode ( "utf-8" ) if isinstance ( x,str ) else x )
    add ( f"--{boundary}\r\nContent-Disposition: form-data; name=\"purpose\"\r\n\r\nuser_data\r\n" )
    add ( f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{safe}\"\r\nContent-Type: application/pdf\r\n\r\n" )
    add ( pdf_bytes ) ; add ( f"\r\n--{boundary}--\r\n" )
    req=urllib.request.Request ( "https://api.openai.com/v1/files",data=b"".join ( chunks ),headers={"Authorization":f"Bearer {OPENAI_API_KEY}","Content-Type":f"multipart/form-data; boundary={boundary}"},method="POST" )
    with urllib.request.urlopen ( req,timeout=90 ) as resp: data=json.loads ( resp.read ( ).decode ( "utf-8" ) )
    return data.get ( "id","" )

def _openai_delete_file_sync ( file_id ) :
    if not file_id: return
    try:
        req=urllib.request.Request ( f"https://api.openai.com/v1/files/{file_id}",headers={"Authorization":f"Bearer {OPENAI_API_KEY}"},method="DELETE" )
        urllib.request.urlopen ( req,timeout=20 ).read ( )
    except Exception: pass

def _extract_response_text ( data ) :
    if data.get ( "output_text" ): return str ( data["output_text"] ).strip ( )
    parts=[]
    for item in data.get ( "output",[] ):
        for content in item.get ( "content",[] ):
            if content.get ( "type" )=="output_text" and content.get ( "text" ): parts.append ( content["text"] )
    return "\n".join ( parts ).strip ( )

def _clean_json_text ( text ) :
    t=(text or "").strip ( )
    if t.startswith ( "```" ):
        t=re.sub ( r"^```(?:json)?\s*","",t,flags=re.I )
        t=re.sub ( r"\s*```$","",t )
    a=t.find ( "[" ) ; b=t.rfind ( "]" )
    return t[a:b+1] if a>=0 and b>a else t

def _openai_book_quiz_sync ( pdf_bytes,filename,title,count ) :
    """Matnli yoki skaner PDFni Responses API orqali o'qib, kitobning o'zidan quiz tuzadi."""
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY sozlanmagan")
    if not pdf_bytes or not pdf_bytes.startswith(b"%PDF"):
        raise RuntimeError("Fayl haqiqiy PDF emas")
    if len(pdf_bytes) > 45 * 1024 * 1024:
        raise RuntimeError("PDF 45 MB dan katta")

    safe=(filename or "book.pdf").replace('"','').replace("\r","").replace("\n","")
    file_data="data:application/pdf;base64,"+base64.b64encode(pdf_bytes).decode("ascii")
    instruction=(
      f"Bu PDF â€” â€˜{title}â€™ kitobi. PDFni toâ€˜liq tahlil qiling va FAQAT shu kitob mazmuniga tayangan holda aynan {count} ta test tuzing. "
      "Agar PDF skanerlangan boâ€˜lsa, sahifa rasmlaridagi matnni ham oâ€˜qing. Tashqi bilim qoâ€˜shmang. "
      "Har savolda aynan 4 ta variant boâ€˜lsin va faqat bittasi toâ€˜gâ€˜ri boâ€˜lsin. "
      "Savollar takrorlanmasin, kitobni oâ€˜qiganlikni tekshiradigan mazmunli savollar boâ€˜lsin. "
      "Savol va variantlarni oâ€˜zbek tilida yozing. "
      "Faqat JSON massiv qaytaring. Har element: "
      '{"question":"...","options":["...","...","...","..."],"correct":0,"explanation":"..."}. '
      "correct faqat 0,1,2,3 dan biri. explanation kitobdagi javobga tayangan juda qisqa izoh. "
      "Markdown yoki JSONdan tashqari hech qanday matn yozmang."
    )
    payload=json.dumps({
      "model":OPENAI_MODEL,
      "input":[{
        "role":"user",
        "content":[
          {"type":"input_file","filename":safe,"file_data":file_data,"detail":"low"},
          {"type":"input_text","text":instruction}
        ]
      }],
      "max_output_tokens":max(2200,count*320)
    },ensure_ascii=False).encode("utf-8")

    req=urllib.request.Request(
      "https://api.openai.com/v1/responses",
      data=payload,
      headers={"Authorization":f"Bearer {OPENAI_API_KEY}","Content-Type":"application/json"},
      method="POST"
    )
    try:
        with urllib.request.urlopen(req,timeout=180) as resp:
            data=json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail=""
        try: detail=e.read().decode("utf-8","replace")[:3000]
        except Exception: pass
        log.error("Book quiz OpenAI HTTP %s: %s",getattr(e,"code","?"),detail)
        raise RuntimeError(f"OpenAI HTTP {getattr(e,'code','?')}: {detail[:600]}")
    except Exception as e:
        log.exception("Book quiz OpenAI connection error")
        raise RuntimeError(f"OpenAI ulanish xatosi: {e}")

    raw_text=_extract_response_text(data)
    if not raw_text:
        log.error("Book quiz empty OpenAI response: %s",str(data)[:3000])
        raise RuntimeError("AI boâ€˜sh javob qaytardi")
    raw=_clean_json_text(raw_text)
    try:
        items=json.loads(raw)
    except Exception:
        log.error("Book quiz invalid JSON: %s",raw_text[:5000])
        raise RuntimeError("AI testlarni JSON formatida qaytarmadi")
    if not isinstance(items,list):
        raise RuntimeError("AI JSON massiv qaytarmadi")

    out=[]
    for x in items:
        if not isinstance(x,dict): continue
        q=str(x.get("question","")).strip()[:300]
        opts=x.get("options",[])
        try: correct=int(x.get("correct",-1))
        except Exception: correct=-1
        exp=str(x.get("explanation","")).strip()[:190]
        if q and isinstance(opts,list) and len(opts)==4 and 0<=correct<4:
            opts=[str(z).strip()[:100] for z in opts]
            if all(opts):
                out.append({"question":q,"options":opts,"correct":correct,"explanation":exp})
        if len(out)>=count: break
    if len(out)<count:
        raise RuntimeError(f"AI {len(out)} ta yaroqli test qaytardi, {count} ta kerak")
    return out[:count]


def _openai_quiz_from_context_sync(context, title, count):
    """Extracted book context -> grounded Telegram quiz JSON."""
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY sozlanmagan")
    if not context or len(context.strip()) < 300:
        raise RuntimeError("PDFdan test uchun yetarli matn olinmadi")
    instruction = (
        f"Quyidagi material â€˜{title}â€™ kitobidan olingan. FAQAT berilgan materialga tayangan holda "
        f"aynan {count} ta test tuzing. Tashqi bilim qoâ€˜shmang. "
        "Har savolda aynan 4 ta variant va faqat bitta toâ€˜gâ€˜ri javob boâ€˜lsin. "
        "Savollar takrorlanmasin. Savol va variantlar oâ€˜zbek tilida boâ€˜lsin. "
        "Faqat JSON massiv qaytaring. Har element: "
        '{"question":"...","options":["...","...","...","..."],"correct":0,"explanation":"..."}. '
        "correct 0,1,2,3 dan biri. explanation juda qisqa boâ€˜lsin.\n\n"
        "KITOBDAN OLINGAN MATERIAL:\n" + context
    )
    payload = json.dumps({
        "model": OPENAI_MODEL,
        "input": instruction,
        "max_output_tokens": max(2200, count * 320)
    }, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=payload,
        headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:3000]
        except Exception:
            pass
        raise RuntimeError(f"OpenAI HTTP {getattr(e,'code','?')}: {detail[:600]}")
    raw_text = _extract_response_text(data)
    raw = _clean_json_text(raw_text)
    try:
        items = json.loads(raw)
    except Exception:
        log.error("Large PDF quiz invalid JSON: %s", raw_text[:5000])
        raise RuntimeError("AI testlarni JSON formatida qaytarmadi")
    out = []
    if isinstance(items, list):
        for x in items:
            if not isinstance(x, dict):
                continue
            question = str(x.get("question", "")).strip()[:300]
            opts = x.get("options", [])
            try:
                correct = int(x.get("correct", -1))
            except Exception:
                correct = -1
            explanation = str(x.get("explanation", "")).strip()[:190]
            if question and isinstance(opts, list) and len(opts) == 4 and 0 <= correct < 4:
                opts = [str(z).strip()[:100] for z in opts]
                if all(opts):
                    out.append({
                        "question": question,
                        "options": opts,
                        "correct": correct,
                        "explanation": explanation
                    })
            if len(out) >= count:
                break
    if len(out) < count:
        raise RuntimeError(f"AI {len(out)} ta yaroqli test qaytardi, {count} ta kerak")
    return out[:count]


def _even_page_indexes(total, wanted):
    if total <= 0:
        return []
    wanted = max(1, min(int(wanted), total))
    if wanted == total:
        return list(range(total))
    if wanted == 1:
        return [total // 2]
    return sorted(set(round(i * (total - 1) / (wanted - 1)) for i in range(wanted)))


def _extract_large_pdf_context_sync(path, title, count):
    """
    Large PDF is never loaded fully into RAM.
    Text PDFs: read all pages, keep evenly distributed bounded excerpts.
    Scanned PDFs: render evenly distributed pages and let Vision read them in small batches.
    """
    if fitz is None:
        raise RuntimeError("PyMuPDF oâ€˜rnatilmagan")
    doc = fitz.open(path)
    try:
        total = doc.page_count
        if total < 1:
            raise RuntimeError("PDF sahifalari topilmadi")

        # First determine whether this is a text PDF.
        probe_ids = _even_page_indexes(total, min(12, total))
        probe_chars = 0
        for pno in probe_ids:
            try:
                probe_chars += len((doc.load_page(pno).get_text("text") or "").strip())
            except Exception:
                pass

        # TEXT PDF: extract across the whole book without keeping the whole PDF in memory.
        if probe_chars >= max(800, len(probe_ids) * 120):
            page_budget = 2200
            max_chars = 110000 if count >= 20 else (85000 if count >= 10 else 60000)
            pieces = []
            used = 0
            for pno in range(total):
                try:
                    t = (doc.load_page(pno).get_text("text") or "").strip()
                except Exception:
                    t = ""
                if not t:
                    continue
                # Keep a bounded excerpt from every page so coverage spans the whole book.
                if len(t) > page_budget:
                    half = page_budget // 2
                    t = t[:half] + "\n...\n" + t[-half:]
                block = f"\n--- {pno+1}-sahifa / {total} ---\n{t}\n"
                if used + len(block) > max_chars:
                    # Once budget is full, switch to evenly sampled remaining pages.
                    break
                pieces.append(block)
                used += len(block)

            # If early pages filled the budget, rebuild with even page coverage.
            if len(pieces) < total and used >= max_chars * 0.85:
                pieces = []
                used = 0
                sample_n = min(total, 48 if count >= 20 else (36 if count >= 10 else 28))
                for pno in _even_page_indexes(total, sample_n):
                    try:
                        t = (doc.load_page(pno).get_text("text") or "").strip()
                    except Exception:
                        t = ""
                    if not t:
                        continue
                    per = max(900, max_chars // max(1, sample_n))
                    if len(t) > per:
                        half = per // 2
                        t = t[:half] + "\n...\n" + t[-half:]
                    block = f"\n--- {pno+1}-sahifa / {total} ---\n{t}\n"
                    if used + len(block) > max_chars:
                        break
                    pieces.append(block)
                    used += len(block)

            context = "".join(pieces).strip()
            if len(context) < 500:
                raise RuntimeError("PDF matni juda kam")
            return context, total, "text"

        # SCANNED PDF: Vision reads evenly distributed pages.
        sample_n = min(total, 18 if count >= 20 else (14 if count >= 10 else 10))
        page_ids = _even_page_indexes(total, sample_n)
        vision_notes = []
        for idx, pno in enumerate(page_ids, 1):
            page = doc.load_page(pno)
            pix = page.get_pixmap(matrix=fitz.Matrix(1.35, 1.35), alpha=False)
            img = pix.tobytes("jpeg", jpg_quality=72)
            prompt = (
                f"Bu â€˜{title}â€™ kitobining {pno+1}/{total}-sahifasi. "
                "Sahifadagi TEST tuzishga yaroqli aniq faktlar, taâ€™riflar, voqealar, ism va tushunchalarni "
                "oâ€˜zbekcha ixcham konspekt qiling. Faqat koâ€˜rinayotgan sahifadagi maâ€™lumotni yozing; uydirmang."
            )
            note = _openai_image_response_sync(img, "image/jpeg", prompt)
            if note:
                vision_notes.append(f"\n--- {pno+1}-sahifa / {total} ---\n{note.strip()}\n")
        context = "".join(vision_notes).strip()
        if len(context) < 500:
            raise RuntimeError("Skan PDFdan yetarli mazmun oâ€˜qilmadi")
        return context, total, "scan"
    finally:
        doc.close()


def _build_book_quiz_from_path_sync(path, title, count):
    size = Path(path).stat().st_size
    # Small PDFs keep the direct PDF path; large PDFs use streaming/chunk extraction.
    if size <= 45 * 1024 * 1024:
        pdf_bytes = Path(path).read_bytes()
        return _openai_book_quiz_sync(pdf_bytes, Path(path).name, title, count), None
    context, pages, mode = _extract_large_pdf_context_sync(path, title, count)
    quizzes = _openai_quiz_from_context_sync(context, title, count)
    return quizzes, {"pages": pages, "mode": mode, "size": size}


async def quiz_replace_message(q, ctx, text, reply_markup=None):
    """Quiz menyusini rasmli yoki oddiy xabardan ishonchli ochadi."""
    msg = q.message
    try:
        # Kitob kartasi cover rasmi bilan yuborilgan bo'lsa edit_message_text ishlamaydi.
        if msg and (msg.photo or msg.video or msg.document or msg.audio or msg.animation):
            chat_id = msg.chat.id
            try:
                await msg.delete()
            except Exception:
                pass
            return await ctx.bot.send_message(chat_id, text, reply_markup=reply_markup)
        return await q.edit_message_text(text, reply_markup=reply_markup)
    except TelegramError:
        return await ctx.bot.send_message(q.message.chat.id, text, reply_markup=reply_markup)

async def _quiz_allowed_groups ( ctx,uid ) :
    rows=all_ ( "SELECT chat_id,title FROM groups ORDER BY title" )
    out=[]
    for r in rows:
        cid=int ( r["chat_id"] )
        if is_super ( uid ):
            out.append ( (cid,r["title"] or str ( cid )) )
            continue
        try:
            if await is_tg_admin ( ctx.bot,cid,uid ): out.append ( (cid,r["title"] or str ( cid )) )
        except Exception: pass
    return out[:40]

async def _download_large_telegram_file(ctx, file_id, path):
    """
    Bot API getFile katta faylni bermasa:
    1) bot file_id orqali PDFni maxsus storage guruhiga server-side yuboradi;
    2) Telethon user session shu xabarni MTProto orqali yuklab oladi.
    Bot va TG_SESSION egasi storage guruhida boâ€˜lishi kerak.
    """
    if not (TelegramClient and StringSession):
        raise RuntimeError("Telethon oâ€˜rnatilmagan")
    if not TG_API_ID or not TG_API_HASH or not TG_SESSION:
        raise RuntimeError("TG_API_ID/TG_API_HASH/TG_SESSION sozlanmagan")
    if not TG_STORAGE_CHAT_ID:
        raise RuntimeError("TG_STORAGE_CHAT_ID sozlanmagan")

    storage_msg = await ctx.bot.send_document(
        chat_id=TG_STORAGE_CHAT_ID,
        document=file_id,
        caption="Veritas AI vaqtinchalik PDF"
    )
    client = TelegramClient(StringSession(TG_SESSION), TG_API_ID, TG_API_HASH)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            raise RuntimeError("TG_SESSION avtorizatsiyadan chiqib qolgan")
        entity = await client.get_entity(TG_STORAGE_CHAT_ID)
        msg = await client.get_messages(entity, ids=storage_msg.message_id)
        if not msg:
            raise RuntimeError("Storage guruhidagi PDF xabari topilmadi")
        saved = await client.download_media(msg, file=path)
        if not saved or not Path(path).exists():
            raise RuntimeError("MTProto PDFni yuklay olmadi")
        return path
    finally:
        await client.disconnect()
        try:
            await ctx.bot.delete_message(TG_STORAGE_CHAT_ID, storage_msg.message_id)
        except Exception:
            pass

async def _make_and_send_book_quiz ( q,ctx,bid,chat_id,count ) :
    u=q.from_user
    r=one ( "SELECT title,pdf_file_id FROM library_books WHERE id=? AND status='approved'",(bid,) )
    if not r or not r["pdf_file_id"]:
        return await q.edit_message_text("âŒ Kitob PDFâ€™i topilmadi.",reply_markup=back_markup("library"))
    if count not in (5,10,20):
        return await q.answer("Test soni notoâ€˜gâ€˜ri.",show_alert=True)
    if not is_super ( u.id ) and not await is_tg_admin(ctx.bot,chat_id,u.id):
        return await q.answer("Bu guruhda admin emassiz.",show_alert=True)
    if not OPENAI_API_KEY:
        return await q.edit_message_text("âš ï¸ Veritas AI kaliti sozlanmagan.",reply_markup=back_markup("library"))

    await q.edit_message_text(
        f"ðŸ§  â€˜{r['title']}â€™ kitobi oâ€˜qilmoqda...\n\n"
        f"{count} ta test tayyorlanadi. Matnli yoki skaner PDF boâ€˜lishi mumkin.\nBiroz kuting."
    )
    path=f"/tmp/veritas_book_{bid}_{u.id}.pdf"
    try:
        try:
            tgfile=await ctx.bot.get_file(r["pdf_file_id"])
            await tgfile.download_to_drive(custom_path=path)
        except TelegramError as e:
            if "File is too big" not in str(e):
                raise
            log.info("Bot API file too big; MTProto fallback boshlandi.")
            await _download_large_telegram_file(ctx, r["pdf_file_id"], path)

        with open(path, "rb") as _fh:
            if _fh.read(4) != b"%PDF":
                raise RuntimeError("Telegramdan olingan fayl PDF emas")

        quizzes, pdf_meta = await asyncio.to_thread(
            _build_book_quiz_from_path_sync, path, r["title"], count
        )
        if pdf_meta:
            log.info(
                "Large PDF processed: %.1f MB, %s pages, mode=%s",
                pdf_meta["size"] / (1024 * 1024), pdf_meta["pages"], pdf_meta["mode"]
            )

        await ctx.bot.send_message(
            chat_id,
            f"ðŸ§  VASATIYA KITOB TESTI\n\nðŸ“– {r['title']}\nðŸ“ {len(quizzes)} ta savol\n\nTestni boshlaymiz ðŸ‘‡"
        )
        sent=0
        for i,x in enumerate(quizzes,1):
            await ctx.bot.send_poll(
                chat_id=chat_id,
                question=f"{i}. {x['question']}"[:300],
                options=x["options"],
                type="quiz",
                correct_option_id=x["correct"],
                is_anonymous=False,
                explanation=(x["explanation"] or None),
                protect_content=False
            )
            sent+=1
            await asyncio.sleep(0.4)

        return await q.edit_message_text(
            f"âœ… Tayyor!\n\nðŸ“– {r['title']}\nðŸ§  {sent} ta test guruhga yuborildi.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("ðŸ“– Kitobga qaytish",callback_data=f"libbook:{bid}")]]
            )
        )
    except Exception as e:
        log.exception("Book quiz error: %s",e)
        s=str(e)
        if "401" in s:
            msg="âš ï¸ OpenAI kaliti qabul qilinmadi. Railwayâ€™dagi OPENAI_API_KEY ni tekshiring."
        elif "429" in s:
            msg="âš ï¸ OpenAI limiti yoki balans sabab test tuzilmadi. API balansini tekshiring."
        elif "PyMuPDF" in s:
            msg="âš ï¸ Katta PDF moduli uchun PyMuPDF kutubxonasi oâ€˜rnatilmagan."
        elif "Skan PDF" in s or "PDF matni juda kam" in s:
            msg="âš ï¸ PDF oâ€˜qildi, lekin test tuzish uchun yetarli mazmun ajratilmadi."
        elif "JSON" in s or "yaroqli test" in s:
            msg="âš ï¸ AI kitobni oâ€˜qidi, lekin test formatini toâ€˜gâ€˜ri qaytarmadi. Qayta urinib koâ€˜ring."
        elif "TG_STORAGE_CHAT_ID" in s:
            msg="âš ï¸ Katta PDF uchun storage guruh hali sozlanmagan."
        elif "Telethon" in s:
            msg="âš ï¸ Katta PDF moduli uchun Telethon kutubxonasi kerak."
        elif "TG_API_ID" in s or "TG_SESSION" in s:
            msg="âš ï¸ Katta PDF uchun Telegram MTProto sozlamalari toâ€˜liq emas."
        else:
            msg="âš ï¸ Kitobdan test tuzishda xatolik boâ€˜ldi. Aniq sabab Railway logiga yozildi."
        return await q.edit_message_text(msg,reply_markup=back_markup("library"))
    finally:
        try: Path(path).unlink(missing_ok=True)
        except Exception: pass


def _translation_last_completed(uid):
    r=one("SELECT MAX(completed_at) AS t FROM ai_book_translations WHERE user_id=? AND status='done'", (uid,))
    return int(r["t"] or 0) if r else 0

def _translation_wait_seconds(uid):
    last=_translation_last_completed(uid)
    return max(0, last + 86400 - now()) if last else 0

def _translation_running(uid):
    return bool(one("SELECT 1 FROM ai_book_translations WHERE user_id=? AND status='running' LIMIT 1", (uid,)))

def _translate_text_sync(text, target_lang, title, part_no, total_parts):
    names={"uz":"Oâ€˜zbekcha","ru":"Ruscha","en":"English"}; lang=names.get(target_lang,target_lang)
    payload=json.dumps({"model":OPENAI_MODEL,"instructions":f"Berilgan kitob matnini {lang} tiliga toâ€˜liq va sodiq tarjima qiling. Qisqartirmang, sharh va yangi maâ€™lumot qoâ€˜shmang. Tuzilma va raqamlarni saqlang. Faqat tarjimani qaytaring.","input":f"Kitob: {title}\nQism: {part_no}/{total_parts}\n\n{text}","max_output_tokens":7000},ensure_ascii=False).encode("utf-8")
    req=urllib.request.Request("https://api.openai.com/v1/responses",data=payload,headers={"Authorization":f"Bearer {OPENAI_API_KEY}","Content-Type":"application/json"},method="POST")
    with urllib.request.urlopen(req,timeout=180) as resp: data=json.loads(resp.read().decode("utf-8"))
    out=_extract_response_text(data)
    if not out.strip(): raise RuntimeError("AI tarjima qaytarmadi")
    return out.strip()

def _split_translation_text(text,max_chars=9000):
    chunks=[]; cur=""
    for para in re.split(r"\n\s*\n",(text or "").strip()):
        para=para.strip()
        if not para: continue
        for piece in [para[i:i+max_chars] for i in range(0,len(para),max_chars)]:
            cand=(cur+"\n\n"+piece).strip() if cur else piece
            if len(cand)>max_chars and cur: chunks.append(cur); cur=piece
            else: cur=cand
    if cur: chunks.append(cur)
    return chunks

def _find_unicode_font():
    for x in ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf","/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf","/usr/share/fonts/opentype/noto/NotoSans-Regular.ttf","/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"]:
        if Path(x).exists(): return x
    return None

def _write_translation_pdf_sync(out_path,title,target_lang,parts):
    if fitz is None: raise RuntimeError("PyMuPDF oâ€˜rnatilmagan")
    doc=fitz.open(); fontfile=_find_unicode_font(); fontname="veritasfont" if fontfile else "helv"
    def page_new():
        p=doc.new_page(width=595,height=842)
        if fontfile: p.insert_font(fontname=fontname,fontfile=fontfile)
        return p
    page=page_new(); y=55; text=f"{title}\nAI tarjima Â· {target_lang}\n\n"+"\n\n".join(parts)
    lines=[]
    for para in text.splitlines():
        if not para: lines.append(""); continue
        line=""
        for w in para.split():
            c=(line+" "+w).strip()
            if len(c)>88 and line: lines.append(line); line=w
            else: line=c
        if line: lines.append(line)
    for line in lines:
        if y>790: page=page_new(); y=55
        if not line: y+=9; continue
        try: page.insert_text((45,y),line,fontsize=10.5,fontname=fontname)
        except Exception: page.insert_text((45,y),line.encode("latin-1","replace").decode("latin-1"),fontsize=10.5,fontname="helv")
        y+=14
    doc.save(out_path,garbage=3,deflate=True); doc.close()

def _translate_pdf_path_sync(path,out_path,title,target_lang):
    if fitz is None: raise RuntimeError("PyMuPDF oâ€˜rnatilmagan")
    doc=fitz.open(path); pages=[]; chars=0
    try:
        for pno in range(doc.page_count):
            t=(doc.load_page(pno).get_text("text") or "").strip()
            if t: pages.append(f"--- {pno+1}-sahifa ---\n{t}"); chars+=len(t)
    finally: doc.close()
    if chars<500: raise RuntimeError("SCAN_TRANSLATION_NOT_READY")
    chunks=_split_translation_text("\n\n".join(pages))
    translated=[_translate_text_sync(ch,target_lang,title,i,len(chunks)) for i,ch in enumerate(chunks,1)]
    _write_translation_pdf_sync(out_path,title,target_lang,translated)
    return len(chunks)

async def _run_book_translation(q,ctx,bid,target_lang):
    u=q.from_user
    if not ai_user_active(u.id): return await q.answer("ðŸ”’ AI Premium kerak: birinchi 30 kun bepul, keyin 10 â­ / 30 kun",show_alert=True)
    if _translation_running(u.id): return await q.answer("â³ Sizda boshqa tarjima davom etmoqda.",show_alert=True)
    wait=_translation_wait_seconds(u.id)
    if wait>0: return await q.answer(f"â³ Kunlik limit ishlatilgan. Taxminan {(wait+3599)//3600} soat qoldi.",show_alert=True)
    if target_lang not in {"uz","ru","en"}: return await q.answer("Til notoâ€˜gâ€˜ri",show_alert=True)
    r=one("SELECT title,pdf_file_id FROM library_books WHERE id=? AND status='approved'",(bid,))
    if not r or not r["pdf_file_id"]: return await q.answer("Kitob fayli mavjud emas",show_alert=True)
    cur=execute("INSERT INTO ai_book_translations(user_id,book_id,target_lang,status,started_at) VALUES(?,?,?,?,?)",(u.id,bid,target_lang,"running",now())); job_id=cur.lastrowid
    names={"uz":"ðŸ‡ºðŸ‡¿ Oâ€˜zbekcha","ru":"ðŸ‡·ðŸ‡º Ruscha","en":"ðŸ‡¬ðŸ‡§ English"}
    await quiz_replace_message(q,ctx,f"ðŸŒ AI TARJIMA\n\nðŸ“– {r['title']}\nâž¡ï¸ {names[target_lang]}\n\nTarjima qilinmoqda. Katta kitob vaqt olishi mumkin...")
    src=f"/tmp/veritas_translate_{bid}_{u.id}.pdf"; out=f"/tmp/veritas_translated_{bid}_{u.id}_{target_lang}.pdf"
    try:
        async with TRANSLATION_SEMAPHORE:
            try:
                tgfile=await ctx.bot.get_file(r["pdf_file_id"]); await tgfile.download_to_drive(custom_path=src)
            except TelegramError as e:
                if "File is too big" not in str(e): raise
                await _download_large_telegram_file(ctx,r["pdf_file_id"],src)
            parts=await asyncio.to_thread(_translate_pdf_path_sync,src,out,r["title"],target_lang)
        execute("UPDATE ai_book_translations SET status='done',completed_at=? WHERE id=?",(now(),job_id))
        with open(out,"rb") as fh:
            await ctx.bot.send_document(u.id,document=fh,filename=f"translated_{bid}_{target_lang}.pdf",caption=f"âœ… AI tarjima tayyor\nðŸ“– {r['title']}\nðŸŒ {names[target_lang]}\nðŸ§© {parts} qism.\n\nKeyingi kitob: 24 soatdan keyin.")
    except Exception as e:
        log.exception("Book translation error: %s",e); execute("UPDATE ai_book_translations SET status='failed' WHERE id=?",(job_id,))
        msg="âš ï¸ Tarjima tugamadi. Kunlik limitingiz sarflanmadi."
        if "SCAN_TRANSLATION_NOT_READY" in str(e): msg="âš ï¸ Bu PDF skaner/rasm koâ€˜rinishida. Hozirgi bosqich matnli PDFlarni tarjima qiladi. Kunlik limitingiz sarflanmadi."
        await ctx.bot.send_message(u.id,msg)
    finally:
        Path(src).unlink(missing_ok=True); Path(out).unlink(missing_ok=True)


def ai_cabinet_name_context(uid):
    r=one("SELECT first_name,username FROM users WHERE user_id=?",(uid,))
    if not r:
        return ""
    nick=(r["first_name"] or "").strip()
    if not nick and r["username"]:
        nick="@"+r["username"]
    if not nick:
        return ""
    return (
        f"\n\nVERITAS KABINET KONTEKSTI: Bu foydalanuvchining kabinetdagi niki/ismi: {nick}. "
        f"Suhbatda uni tabiiy ravishda {nick} deb taning va kerak boâ€˜lganda shu nom bilan murojaat qiling. "
        "Boshqa foydalanuvchining nomi bilan adashtirmang."
    )

async def group_ai_reply ( update,ctx ) :
    msg=update.effective_message; chat=update.effective_chat; u=update.effective_user
    if not msg or not u or chat.type not in ("group","supergroup") : return False
    if u.is_bot or not msg.reply_to_message or not msg.text: return False
    replied_msg=msg.reply_to_message
    if not replied_msg.from_user or replied_msg.from_user.id!=ctx.bot.id: return False
    question=msg.text.strip()
    if not question or question.startswith("*"): return False
    if not ai_group_active ( chat.id ) :
        await msg.reply_text ( "ðŸ”’ Bu guruhda Veritas AI obunasi faol emas.\n\n*ai yozib tariflarni oching: birinchi 30 kun bepul, keyin 100 â­ / 30 kun." )
        return True
    if not ai_rate_ok ( chat.id,u.id,5 ) :
        await msg.reply_text ( "â³ Juda tez soâ€˜rov yuborildi. 5 soniyadan keyin qayta yozing." )
        return True
    if not OPENAI_API_KEY:
        await msg.reply_text("âš ï¸ Veritas AI kaliti sozlanmagan.")
        return True
    try:
        await ctx.bot.send_chat_action(chat.id,"typing")
        previous=(replied_msg.text or replied_msg.caption or "").strip()
        prompt=(f"Oldingi Veritas xabari:\n{previous[:2500]}\n\n" if previous else "") + f"Foydalanuvchi savoli:\n{question[:4000]}" + ai_actor_context ( u ) + ai_cabinet_name_context(u.id)
        answer=await asyncio.to_thread(_openai_response_sync,prompt)
        if not answer: answer="Hozir javob hosil boâ€˜lmadi. Qayta urinib koâ€˜ring."
        for i in range(0,len(answer),4000): await msg.reply_text(answer[i:i+4000])
    except urllib.error.HTTPError as e:
        detail=""
        try: detail=e.read().decode("utf-8")[:700]
        except Exception: pass
        log.error("OpenAI HTTP error %s: %s",getattr(e,"code","?"),detail)
        await msg.reply_text("âš ï¸ Veritas AI hozir javob bera olmadi. Keyinroq qayta urinib koâ€˜ring.")
    except Exception:
        log.exception("Veritas AI error")
        await msg.reply_text("âš ï¸ Veritas AI bilan ulanishda xatolik boâ€˜ldi.")
    return True

async def private_ai_reply ( update,ctx ) :
    if ctx.user_data.get("news_consumed_message_id")==getattr(update.effective_message,"message_id",None):
        return
    if ctx.user_data.get("bayram_consumed_message_id")==getattr(update.effective_message,"message_id",None):return
    if ctx.user_data.get("v9_consumed_message_id")==getattr(update.effective_message,"message_id",None):
        return
    if ctx.user_data.get("owner_consumed_message_id")==getattr(update.effective_message,"message_id",None):
        return

    msg=update.effective_message; u=update.effective_user; chat=update.effective_chat
    if not msg or not u or chat.type!="private" or u.is_bot or not msg.text: return
    text=msg.text.strip ( )
    if not text or text.startswith ( "*" ) or text.startswith ( "/" ): return
    if STATE.get ( u.id ): return
    if ctx.user_data.get ( "workflow_message_id" )==msg.message_id: return
    ensure_user ( u )
    if not ai_user_active ( u.id ) :
        kb=InlineKeyboardMarkup ( [[InlineKeyboardButton ( "ðŸ’Ž 10 â­ â€” 30 kun",callback_data="aipbuy" ) ],[InlineKeyboardButton ( "â­ Hisobni toâ€˜ldirish",callback_data="wallet" ) ]] )
        return await msg.reply_text ( "ðŸ”’ Shaxsiy Veritas AI faqat AI Premium aâ€™zolar uchun.\n\nðŸ’Ž 10 â­ â€” 30 kun",reply_markup=kb )
    if not ai_rate_ok ( "private",u.id,4 ) : return await msg.reply_text ( "â³ 4 soniyadan keyin yana yozing." )
    if not OPENAI_API_KEY: return await msg.reply_text ( "âš ï¸ Veritas AI kaliti sozlanmagan." )
    try:
        await ctx.bot.send_chat_action ( chat.id,"typing" )
        previous=""
        if msg.reply_to_message and msg.reply_to_message.from_user and msg.reply_to_message.from_user.id==ctx.bot.id:
            previous=(msg.reply_to_message.text or msg.reply_to_message.caption or "")[:2500]
        prompt=(f"Oldingi Veritas javobi:\n{previous}\n\n" if previous else "")+f"Foydalanuvchi:\n{text[:4000]}"+ai_actor_context ( u )
        answer=await asyncio.to_thread ( _openai_response_sync,prompt )
        if not answer: answer="Hozir javob hosil boâ€˜lmadi. Qayta urinib koâ€˜ring."
        for i in range ( 0,len ( answer ),4000 ): await msg.reply_text ( answer[i:i+4000] )
    except Exception:
        log.exception ( "Private Veritas AI error" )
        await msg.reply_text ( "âš ï¸ Veritas AI hozir javob bera olmadi." )

async def vse_self_clean(update,ctx):
    msg=update.effective_message; u=update.effective_user; chat=update.effective_chat
    if not msg or not u or chat.type not in ("group","supergroup"):
        return False
    if (msg.text or "").strip().lower()!="*vse":
        return False
    # Buyruq faqat Veritasning xabariga reply qilinganda ishlaydi.
    if not msg.reply_to_message or not msg.reply_to_message.from_user or msg.reply_to_message.from_user.id!=ctx.bot.id:
        return False

    rows=all_(
        "SELECT message_id FROM group_message_history WHERE chat_id=? AND user_id=? ORDER BY message_id DESC",
        (chat.id,u.id)
    )
    deleted=0
    # *vse xabarining oâ€˜zini ham oâ€˜chirishga harakat qilamiz.
    ids=[msg.message_id]+[int(r["message_id"]) for r in rows if int(r["message_id"])!=msg.message_id]
    for mid in ids:
        try:
            await ctx.bot.delete_message(chat.id,mid)
            deleted+=1
        except TelegramError:
            pass
    execute("DELETE FROM group_message_history WHERE chat_id=? AND user_id=?",(chat.id,u.id))
    try:
        await ctx.bot.send_message(chat.id,f"ðŸ§¹ {u.first_name}: {deleted} ta Veritas qayd etgan xabar oâ€˜chirildi.")
        # Qisqa xizmat xabari guruhda qoladi; job-queue boâ€˜lmasa ham asosiy funksiya buzilmaydi.
    except TelegramError:
        pass
    return True

async def passive ( update,ctx ) :
    msg=update.effective_message; u=update.effective_user; chat=update.effective_chat
    if msg and u and not u.is_bot and chat and chat.type in ("group","supergroup"):
        try:
            execute(
                "INSERT OR IGNORE INTO group_message_history(chat_id,user_id,message_id,created_at) VALUES(?,?,?,?)",
                (chat.id,u.id,msg.message_id,now())
            )
        except Exception:
            log.exception("group message history save failed")
        try:
            archive_group_message(msg,u,chat)
        except Exception:
            log.exception("group chat archive save failed")
    if not msg or not u or chat.type not in ("group","supergroup" ) : return
    ensure_user ( u ) ; ensure_group ( chat)
    day=datetime.now ( timezone.utc ) .strftime ( "%Y-%m-%d" ) ; week=datetime.now ( timezone.utc ) .strftime ( "%G-%V")
    with db ( ) as c:
        r=c.execute ( "SELECT * FROM members WHERE chat_id=? AND user_id=?", ( chat.id,u.id )  ) .fetchone ( )
        if not r:
            c.execute ( "INSERT INTO members ( chat_id,user_id,xp,messages,daily,weekly,last_day,last_week) VALUES ( ?,?,1,1,1,1,?,? ) ", ( chat.id,u.id,day,week ) )
        else:
            daily= ( r["daily"] if r["last_day"]==day else 0 ) +1; weekly= ( r["weekly"] if r["last_week"]==week else 0 ) +1
            c.execute ( "UPDATE members SET xp=xp+1,messages=messages+1,daily=?,weekly=?,last_day=?,last_week=? WHERE chat_id=? AND user_id=?", ( daily,weekly,day,week,chat.id,u.id ) )
    # *vse avval tekshiriladi; aks holda Group AI uni oddiy savol deb olishi mumkin.
    if await vse_self_clean(update,ctx): return
    if await _check_rebus_answer(update,ctx): return
    if await _start_group_rebus_flow(update,ctx): return
    if await group_ai_reply ( update,ctx ) : return
    if await protected ( ctx.bot,chat.id,u.id) or one ( "SELECT 1 FROM approved WHERE chat_id=? AND user_id=?", ( chat.id,u.id )  ) : return
    g=one ( "SELECT * FROM groups WHERE chat_id=?", ( chat.id, ) )
    text= ( msg.text or msg.caption or "" ) .lower ( )
    for r in all_ ( "SELECT word FROM blacklist WHERE chat_id=?", ( chat.id, )  ) :
        if r["word"] in text:
            try: await msg.delete ( )
            except TelegramError: pass
            return
    if g and g["links"] and URL_RE.search ( text ) :
        try: await msg.delete ( )
        except TelegramError: pass
        return
    d=json.loads ( g["locks"] or "{}") if g else {}
    mt=media_type ( msg)
    if (mt and d.get ( mt ) ) or (d.get ( "links") and URL_RE.search ( text )  ) :
        try: await msg.delete ( )
        except TelegramError: pass
        return
    if g and g["antiflood"]:
        k= ( chat.id,u.id ) ; arr=[x for x in FLOOD_CACHE.get ( k,[]) if now (  ) -x<=8]; arr.append ( now (  )  ) ; FLOOD_CACHE[k]=arr
        if len ( arr ) >g["flood_limit"]:
            try:
                await ctx.bot.restrict_chat_member ( chat.id,u.id,ChatPermissions ( can_send_messages=False ) ,until_date=datetime.now ( timezone.utc ) +timedelta ( minutes=1 ) )
                await msg.reply_text ( f"ðŸŒŠ {u.first_name}: flood sabab 1 daqiqa mute.")
            except TelegramError: pass
            FLOOD_CACHE[k]=[]
            return
    if msg.text and msg.text.startswith ( "#" ) :
        name=msg.text[1:].split (  ) [0].lower ( )
        r=one ( "SELECT text FROM notes WHERE chat_id=? AND name=?", ( chat.id,name ) )
        if r: return await msg.reply_text ( r["text"])
    if text:
        for r in all_ ( "SELECT key,response FROM filters_ WHERE chat_id=?", ( chat.id, )  ) :
            if r["key"] in text: return await msg.reply_text ( r["response"])

async def new_members ( update,ctx ) :
    st=moderation_settings(update.effective_chat.id)
    g=one ( "SELECT welcome FROM groups WHERE chat_id=?", ( update.effective_chat.id, ) )
    if g and g["welcome"]:
        names=", ".join ( u.first_name for u in update.effective_message.new_chat_members)
        await update.effective_message.reply_text ( f"ðŸ‘‹ Xush kelibsiz, {names}!")
    if st and st["clean_service"]:
        try: await update.effective_message.delete()
        except TelegramError: pass

async def left_member ( update,ctx ) :
    st=moderation_settings(update.effective_chat.id)
    g=one ( "SELECT goodbye FROM groups WHERE chat_id=?", ( update.effective_chat.id, ) )
    if g and g["goodbye"] and update.effective_message.left_chat_member:
        await update.effective_message.reply_text ( f"ðŸ‘‹ {update.effective_message.left_chat_member.first_name} guruhni tark etdi.")
    if st and st["clean_service"]:
        try: await update.effective_message.delete()
        except TelegramError: pass

async def callback ( update,ctx ) :
    q=update.callback_query; d=q.data; u=q.from_user

    # V9/root tugmalari shu yagona callback router ichidan boshqariladi.
    # Bu V8 callbacklariga tegmaydi va alohida handler guruhlari to'qnashuvini yo'q qiladi.
    if d and (d.startswith("v9:") or d.startswith("root:")):
        return await v9_callback(update,ctx)

    ensure_user ( u)
    cq_defer ( q )

    if d=="owner:message":
        if q.message.chat.type != "private":
            return await q.edit_message_text("ðŸ“¨ Egaga xabar faqat botning shaxsiy chatida ishlaydi.",reply_markup=back_markup("home"))
        STATE[u.id]={"mode":"owner_message"}
        return await q.edit_message_text(
            "ðŸ“¨ EGAGA XABAR QOLDIRISH\n\nXabaringizni yuboring. Matn, rasm, video, voice, audio, sticker yoki hujjat boâ€˜lishi mumkin.\n\nâŒ Bekor qilish uchun /start bosing.",
            reply_markup=back_markup("home")
        )

    if d.startswith("ownerreply:"):
        if u.id not in SUPER_OWNERS:
            return await q.answer("Faqat Super Ega uchun.",show_alert=True)
        tid=int(d.split(":",1)[1]); row=one("SELECT * FROM owner_messages WHERE id=?",(tid,))
        if not row: return await q.answer("Murojaat topilmadi.",show_alert=True)
        STATE[u.id]={"mode":"owner_reply","ticket_id":tid,"target_id":int(row["user_id"])}
        return await q.message.reply_text(f"âœ‰ï¸ #{tid} murojaatga javobingizni yuboring. Matn yoki media mumkin.")

    if d.startswith("ownerseen:"):
        if u.id not in SUPER_OWNERS: return await q.answer("Faqat Super Ega uchun.",show_alert=True)
        tid=int(d.split(":",1)[1]); execute("UPDATE owner_messages SET status='seen',handled_by=? WHERE id=?",(u.id,tid))
        return await q.answer("âœ… Koâ€˜rildi deb belgilandi.",show_alert=True)

    if d.startswith("ownerclose:"):
        if u.id not in SUPER_OWNERS: return await q.answer("Faqat Super Ega uchun.",show_alert=True)
        tid=int(d.split(":",1)[1]); execute("UPDATE owner_messages SET status='closed',handled_by=? WHERE id=?",(u.id,tid))
        return await q.answer("ðŸ—‘ Murojaat yopildi.",show_alert=True)

    if d=="help:home":
        return await q.edit_message_text(
            "â“ VERITAS V8 â€” YORDAM MARKAZI\n\nðŸª¶ Veritas qila oladigan barcha asosiy ishlar shu yerda jamlangan.\nKerakli boâ€˜limni tanlang:",
            reply_markup=help_home_markup()
        )

    if d.startswith ( "help:" ) :
        return await q.edit_message_text ( help_text ( d.split ( ":",1 )[1] ),reply_markup=help_menu_markup ( ) )

    if d=="rebus:start":
        if not is_super(u.id):
            return await q.edit_message_text(
                "â›” AI Rebus yaratish hozircha Super Ega yoki Super Admin boshqaruvida.",
                reply_markup=back_markup("home")
            )
        return await q.edit_message_text(
            "ðŸ§© AI REBUS\n\n"
            "1ï¸âƒ£ Veritas ishlayotgan muhokama guruhiga kiring.\n"
            "2ï¸âƒ£ Veritasning xabariga reply qilib: *rebus deb yozing.\n"
            "3ï¸âƒ£ Shaxsiy chatda nechta rebus kerakligini yozing: masalan 5 yoki 10.\n"
            "4ï¸âƒ£ Veritas javoblarni birma-bir soâ€˜raydi.\n"
            "5ï¸âƒ£ 1-rebus chiqadi; topilgach oâ€˜chadi va 2-rebus chiqadi.\n"
            "6ï¸âƒ£ Kanal bogâ€˜langan boâ€˜lsa kanalga, boâ€˜lmasa guruhning oâ€˜ziga joylanadi.\n"
            "7ï¸âƒ£ Oxirida umumiy natija chiqadi.",
            reply_markup=back_markup("home")
        )

    if d=="me":
        return await send_public_profile(ctx,q.message.chat.id,u.id,u.id,q.message)

    if d=="profilefind":
        STATE[u.id]={"mode":"profile_find"}
        return await q.edit_message_text(
            "ðŸ”Ž Aâ€™ZONI TOPISH\n\nAâ€™zoning @username yoki Telegram ID sini yozing.",
            reply_markup=back_markup("home")
        )

    if d.startswith("plike:"):
        target_uid=int(d.split(":",1)[1])
        if target_uid==u.id: return await q.answer("Oâ€˜z profilingizga Qadr berib boâ€˜lmaydi.",show_alert=True)
        if profile_liked_by(target_uid,u.id):
            execute("DELETE FROM profile_likes WHERE target_user_id=? AND voter_user_id=?",(target_uid,u.id))
            notice="Qadr olib tashlandi."
        else:
            execute("DELETE FROM profile_dislikes WHERE target_user_id=? AND voter_user_id=?",(target_uid,u.id))
            execute("INSERT OR IGNORE INTO profile_likes(target_user_id,voter_user_id,created_at) VALUES(?,?,?)",(target_uid,u.id,now()))
            notice="ðŸ’  Qadr berildi."
        await q.answer(notice)
        return await send_public_profile(ctx,q.message.chat.id,target_uid,u.id,q.message)

    if d.startswith("pdislike:"):
        target_uid=int(d.split(":",1)[1])
        if target_uid==u.id: return await q.answer("Oâ€˜z profilingizga Eâ€™tiroz berib boâ€˜lmaydi.",show_alert=True)
        if profile_disliked_by(target_uid,u.id):
            execute("DELETE FROM profile_dislikes WHERE target_user_id=? AND voter_user_id=?",(target_uid,u.id))
            notice="Eâ€™tiroz olib tashlandi."
        else:
            execute("DELETE FROM profile_likes WHERE target_user_id=? AND voter_user_id=?",(target_uid,u.id))
            execute("INSERT OR IGNORE INTO profile_dislikes(target_user_id,voter_user_id,created_at) VALUES(?,?,?)",(target_uid,u.id,now()))
            notice="âš–ï¸ Eâ€™tiroz bildirildi."
        await q.answer(notice)
        return await send_public_profile(ctx,q.message.chat.id,target_uid,u.id,q.message)

    if d=="libaisearch":
        STATE[u.id]={"mode":"lib_ai_search"}
        return await q.edit_message_text(
            "ðŸ¤– AI KITOB QIDIRUV\n\n"
            "Qanday kitob kerakligini oddiy gap bilan yozing.\n"
            "Masalan: â€œSabr haqida kitobâ€, â€œqiziqarli tarixiy kitobâ€, "
            "â€œbolalar tarbiyasi haqidaâ€.\n\n"
            "ðŸ”’ AI faqat Vasatiya kutubxonasiga qoâ€˜shilgan kitoblardan topadi.",
            reply_markup=back_markup("library")
        )

    if d=="hadaisearch":
        STATE[u.id]={"mode":"had_ai_search"}
        return await q.edit_message_text(
            "ðŸ¤– AI HADIS QIDIRUV\n\n"
            "Mavzuni oddiy gap bilan yozing. Masalan: â€œsabr haqidaâ€, â€œota-ona haqqiâ€.\n\n"
            "ðŸ”’ AI faqat Veritasga qoâ€˜shilgan hadislar ichidan topadi.",
            reply_markup=back_markup("hadith")
        )

    if d=="home":
        try:
            if q.message.photo or q.message.video or q.message.document or q.message.audio or q.message.animation:
                await q.message.delete ( )
                return await ctx.bot.send_message ( q.message.chat.id,"ðŸª¶ VERITAS v8\n\nShaxsiy kabinet",reply_markup=main_menu_markup ( u.id ) )
            return await q.edit_message_text ( "ðŸª¶ VERITAS v8\n\nShaxsiy kabinet",reply_markup=main_menu_markup ( u.id ) )
        except TelegramError:
            return await ctx.bot.send_message ( q.message.chat.id,"ðŸª¶ VERITAS v8\n\nShaxsiy kabinet",reply_markup=main_menu_markup ( u.id ) )

    if d.startswith ( "topgift:") or d.startswith ( "topplain:" ) :
        if not is_super ( u.id ): return
        chat_id=int ( d.split ( ":",1 ) [1] ) ; with_gifts=d.startswith ( "topgift:")
        await q.edit_message_text ( "â³ TOP-10 hisoblanmoqda..." if not with_gifts else "â³ TOP-10 va TOP-3 Giftlar tayyorlanmoqda...")
        return await top10_result ( ctx.bot,chat_id,with_gifts,u.id)

    if d=="me":
        return await q.edit_message_text ( global_profile_text ( u ),reply_markup=back_markup ( ) )

    if d=="qadrtop":
        return await q.edit_message_text(qadr_top_text(10),reply_markup=back_markup("home"))

    if d=="globalactive":
        return await q.edit_message_text ( global_active_text ( 10 ),reply_markup=back_markup ( ) )

    if d=="ai_private":
        until=ai_user_until ( u.id )
        if is_super ( u.id ): status="ðŸ‘‘ FAOL â€” "+super_role ( u.id )
        elif until>now ( ): status="âœ… FAOL\nðŸ“… "+fmt_until ( until )
        else: status="âŒ FAOL EMAS"
        if not ai_user_trial_used ( u.id ) and not is_super ( u.id ):
            kb=InlineKeyboardMarkup ( [[InlineKeyboardButton ( "ðŸŽ 30 kun BEPUL",callback_data="aiptrial" ) ],[InlineKeyboardButton ( "â¬…ï¸ Orqaga",callback_data="home" ) ]] )
            price_text="ðŸŽ Birinchi 30 kun â€” BEPUL\nKeyingi 30 kun â€” 10 â­"
        else:
            kb=InlineKeyboardMarkup ( [[InlineKeyboardButton ( "ðŸ’Ž 10 â­ â€” 30 kun",callback_data="aipbuy" ) ],[InlineKeyboardButton ( "â¬…ï¸ Orqaga",callback_data="home" ) ]] )
            price_text="Premium narxi: 10 â­ / 30 kun."
        return await q.edit_message_text ( f"ðŸ¤– VERITAS AI â€” SHAXSIY YORDAMCHI\n\n{status}\n\n{price_text}\nFaol boâ€˜lsa botga oddiy xabar yozishingiz kifoya.",reply_markup=kb )

    if d=="aiptrial":
        if is_super ( u.id ): return await q.answer ( "Super boshqaruv uchun AI allaqachon faol.",show_alert=True )
        until=claim_ai_user_trial ( u.id )
        if not until: return await q.answer ( "Bepul 30 kunlik muddat avval ishlatilgan.",show_alert=True )
        return await q.edit_message_text ( f"ðŸŽ Shaxsiy Veritas AI Premium 30 kun BEPUL yoqildi.\nðŸ“… {fmt_until ( until )} gacha\n\nKeyingi 30 kun â€” 10 â­",reply_markup=back_markup ( "home" ) )

    if d=="aipbuy":
        if is_super ( u.id ): return await q.answer ( "Super boshqaruv uchun AI allaqachon faol.",show_alert=True )
        if not ai_user_trial_used ( u.id ):
            return await q.answer ( "Avval bepul 30 kunlik muddatdan foydalaning.",show_alert=True )
        if wallet ( u.id ) <AI_PRIVATE_PRICE: return await q.answer ( "Kredit yetarli emas. Hisobni Stars bilan toâ€˜ldiring.",show_alert=True )
        if not wallet_change ( u.id,-AI_PRIVATE_PRICE,"ai_private_30d",u.id ): return
        until=extend_ai_user ( u.id,AI_PRIVATE_DAYS )
        return await q.edit_message_text ( f"âœ… Shaxsiy Veritas AI Premium yoqildi.\nðŸ’Ž {AI_PRIVATE_PRICE} â­\nðŸ“… {fmt_until ( until )} gacha",reply_markup=back_markup ( "home" ) )

    if d.startswith ( "aigtrial:" ) :
        chat_id=int ( d.split ( ":" )[1] )
        until=claim_ai_group_trial ( chat_id,u.id )
        if not until: return await q.answer ( "Bu guruhning bepul 30 kuni avval ishlatilgan.",show_alert=True )
        return await q.edit_message_text ( f"ðŸŽ Veritas AI guruh uchun 30 kun BEPUL yoqildi.\nðŸ“… {fmt_until ( until )} gacha\n\nKeyingi 30 kun â€” 100 â­",reply_markup=ai_group_menu ( chat_id,u.id ) )

    if d.startswith ( "aigbuy:" ) :
        _,schat,sdays=d.split ( ":" ); chat_id=int ( schat ); days=int ( sdays ); price=AI_GROUP_PLANS.get ( days )
        if not price: return
        if not ai_group_trial_used ( chat_id ):
            return await q.answer ( "Avval guruh uchun bepul 30 kunlik muddatni yoqing.",show_alert=True )
        if wallet ( u.id ) <price: return await q.answer ( f"Kredit yetarli emas. Kerak: {price} â­",show_alert=True )
        if not wallet_change ( u.id,-price,f"ai_group_{days}d",chat_id ): return
        until=extend_ai_group ( chat_id,days,u.id,"paid" )
        return await q.edit_message_text ( f"âœ… Veritas AI guruh uchun yoqildi.\nâ­ {price}\nðŸ“… {fmt_until ( until )} gacha",reply_markup=ai_group_menu ( chat_id,u.id ) )

    if d.startswith ( "aigfree:" ) :
        if not is_super ( u.id ): return await q.answer ( "Faqat Super Ega.",show_alert=True )
        _,schat,sdays=d.split ( ":" ); chat_id=int ( schat ); days=int ( sdays )
        if days not in ( 1,7,30 ): return
        until=extend_ai_group ( chat_id,days,u.id,"super_free" )
        return await q.edit_message_text ( f"ðŸ‘‘ Guruhga Veritas AI bepul yoqildi.\nðŸ“… {days} kun â€” {fmt_until ( until )} gacha",reply_markup=ai_group_menu ( chat_id,u.id ) )

    if d.startswith ( "aigoff:" ) :
        if not is_super ( u.id ): return await q.answer ( "Faqat Super Ega.",show_alert=True )
        chat_id=int ( d.split ( ":" )[1] ); execute ( "UPDATE ai_group_subscriptions SET paid_until=0,updated_at=? WHERE chat_id=?", ( now ( ),chat_id ) )
        return await q.edit_message_text ( "â›” Bu guruh uchun Veritas AI oâ€˜chirildi.",reply_markup=ai_group_menu ( chat_id,u.id ) )

    if d=="wallet":
        kb=[[InlineKeyboardButton ( f"{x} â­",callback_data=f"top:{x}") for x in TOPUPS[i:i+3]] for i in range ( 0,len ( TOPUPS ) ,3 ) ]
        kb.append ( [InlineKeyboardButton ( "â¬…ï¸ Orqaga",callback_data="home" ) ,InlineKeyboardButton ( "ðŸ  Bosh menyu",callback_data="home" ) ])
        return await q.edit_message_text ( f"â­ Kredit: {wallet ( u.id ) }\nToâ€˜ldirish:",reply_markup=InlineKeyboardMarkup ( kb ) )

    if d.startswith ( "top:" ) :
        amount=int ( d.split ( ":" ) [1])
        return await ctx.bot.send_invoice ( chat_id=u.id,title="Veritas Stars krediti",description=f"{amount} â­ kredit",payload=f"topup:{u.id}:{amount}:{now (  ) }",currency="XTR",prices=[LabeledPrice ( "Stars",amount ) ])

    if d=="gifts":
        try:
            gs=await ctx.bot.get_available_gifts (  ) ; prices=sorted ( {int ( g.star_count) for g in gs.gifts})
            return await q.edit_message_text ( "ðŸŽ Hozirgi Gift narxlari:\n"+", ".join ( f"{p} â­" for p in prices[:50] ) +"\n\nGuruhda oluvchiga reply: *give <narx>",reply_markup=back_markup (  ) )
        except Exception as e: return await q.edit_message_text ( f"âŒ {e}",reply_markup=back_markup (  ) )

    if d=="premium":
        return await q.edit_message_text ( "ðŸ’Ž Premium: 3 oy â€” 1000 â­ | 6 oy â€” 1500 â­ | 12 oy â€” 2500 â­\nGuruhda reply: *premium 3",reply_markup=back_markup (  ) )

    if d=="mygroups":
        rows=all_ ( "SELECT chat_id,title FROM groups WHERE owner_id=? OR chat_id IN (SELECT chat_id FROM vadmins WHERE user_id=? ) ", ( u.id,u.id ) )
        return await q.edit_message_text ( "ðŸ˜ "+ ( "\n".join ( f"{r['title']} ({r['chat_id']} ) " for r in rows) or "Guruh topilmadi." ) ,reply_markup=back_markup (  ) )

    if d=="about":
        text= ( "â„¹ï¸ VERITAS v8\n\n"
              "Veritas â€” guruh boshqaruvi, faollik, Stars/Gift/Premium va Vasatiya kutubxonasini bir joyga jamlaydigan Telegram bot.\n\n"
              "ðŸ“š Vasatiya kutubxonasi â€” PDF va audio kitoblar, tillar, kategoriyalar, qidiruv va sevimlilar.\n"
              "ðŸ“œ Sahih Hadislar â€” hadis bazasi, toâ€˜plamlar va random hadis.\n"
              "ðŸ›¡ Guruhlar â€” moderatsiya, blacklist, lock, antiflood, filter va notes.\n"
              "â­ Kabinet â€” Stars krediti, Telegram Gift va Premium.\n\n"
              "Buyruqlar uchun: *help")
        return await q.edit_message_text ( text,reply_markup=back_markup (  ) )

    if d=="hadith":
        total=one ( "SELECT COUNT ( *) n FROM hadiths WHERE status='approved'" ) ["n"]
        cols=all_ ( "SELECT collection,COUNT ( *) n FROM hadiths WHERE status='approved' GROUP BY collection ORDER BY collection")
        kb=[[InlineKeyboardButton ( f"ðŸ“š {r['collection']} Â· {r['n']}",callback_data=f"hcol:{r['collection']}:0" ) ] for r in cols[:20]]
        kb.append ( [InlineKeyboardButton ( "ðŸ¤– AI Hadis qidirish",callback_data="hadaisearch" ) ])
        kb.append ( [InlineKeyboardButton ( "ðŸŽ² Random hadis",callback_data="hrandom" ) ])
        if is_hadith_admin ( u.id ) : kb.append ( [InlineKeyboardButton ( "âž• Hadis qoâ€˜shish",callback_data="hadd" ) ])
        kb.append ( [InlineKeyboardButton ( "â¬…ï¸ Orqaga",callback_data="home" ) ,InlineKeyboardButton ( "ðŸ  Bosh menyu",callback_data="home" ) ])
        txt=f"ðŸ“œ SAHIH HADISLAR\n\nJami hadislar: {total}\nToâ€˜plamni tanlang yoki random hadis oâ€˜qing."
        try:
            if q.message.photo or q.message.video or q.message.document or q.message.audio or q.message.animation:
                await q.message.delete (  ) ; return await ctx.bot.send_message ( q.message.chat.id,txt,reply_markup=InlineKeyboardMarkup ( kb ) )
            return await q.edit_message_text ( txt,reply_markup=InlineKeyboardMarkup ( kb ) )
        except TelegramError:
            return await ctx.bot.send_message ( q.message.chat.id,txt,reply_markup=InlineKeyboardMarkup ( kb ) )

    if d=="hadd":
        if not is_hadith_admin ( u.id ) : return await q.answer ( "Ruxsat yoâ€˜q",show_alert=True)
        STATE[u.id]={"mode":"had_add_collection","data":{}}
        return await q.edit_message_text ( "ðŸ“œ HADIS QOâ€˜SHISH â€” 1/6\n\nToâ€˜plam nomini yuboring.\nMisol: Buxoriy")

    if d=="hrandom":
        r=one ( "SELECT * FROM hadiths WHERE status='approved' ORDER BY RANDOM ( ) LIMIT 1")
        if not r: return await q.edit_message_text ( "ðŸ“œ Hozircha hadis bazasi boâ€˜sh.",reply_markup=back_markup ( "home" ) )
        return await q.edit_message_text ( hadith_text ( r ) ,reply_markup=hadith_markup ( r ) )

    if d.startswith ( "hcol:" ) :
        _,collection,spage=d.split ( ":",2 ) ; page=max ( 0,int ( spage )  ) ; per=10; off=page*per
        total=one ( "SELECT COUNT ( *) n FROM hadiths WHERE collection=? AND status='approved'", ( collection, )  ) ["n"]
        rows=all_ ( "SELECT id,number FROM hadiths WHERE collection=? AND status='approved' ORDER BY number LIMIT ? OFFSET ?", ( collection,per,off ) )
        kb=[[InlineKeyboardButton ( f"ðŸ“œ {collection} {r['number']}",callback_data=f"hshow:{r['id']}" ) ] for r in rows]
        nav=[]
        if page>0: nav.append ( InlineKeyboardButton ( "â—€ï¸",callback_data=f"hcol:{collection}:{page-1}" ) )
        if off+per<total: nav.append ( InlineKeyboardButton ( "â–¶ï¸",callback_data=f"hcol:{collection}:{page+1}" ) )
        if nav: kb.append ( nav)
        kb.append ( [InlineKeyboardButton ( "â¬…ï¸ Hadislar",callback_data="hadith" ) ])
        return await q.edit_message_text ( f"ðŸ“š {collection} Â· {total} ta hadis",reply_markup=InlineKeyboardMarkup ( kb ) )

    if d.startswith ( "hshow:" ) :
        hid=int ( d.split ( ":" ) [1] ) ; r=one ( "SELECT * FROM hadiths WHERE id=? AND status='approved'", ( hid, ) )
        if not r: return await q.edit_message_text ( "âŒ Hadis topilmadi.",reply_markup=back_markup ( "hadith" ) )
        if is_hadith_admin ( u.id ) :
            uploader=one ( "SELECT first_name FROM users WHERE user_id=?", ( r["added_by"], ) ); nm=(uploader["first_name"] if uploader and uploader["first_name"] else f"ID {r['added_by']}")
            kb=InlineKeyboardMarkup ( [[InlineKeyboardButton ( f"ðŸ‘¤ Qoâ€˜shdi: {nm[:35]}",url=f"tg://user?id={r['added_by']}" ) ],[InlineKeyboardButton ( "âœï¸ Tahrirlash",callback_data=f"hedit:{r['id']}" ) ,InlineKeyboardButton ( "ðŸ—‘ Oâ€˜chirish",callback_data=f"hdelask:{r['id']}" ) ],[InlineKeyboardButton ( "â¬…ï¸ Hadislar",callback_data="hadith" ) ,InlineKeyboardButton ( "ðŸ  Bosh menyu",callback_data="home" ) ]] )
            return await q.edit_message_text ( hadith_text ( r ),reply_markup=kb )
        return await q.edit_message_text ( hadith_text ( r ) ,reply_markup=hadith_markup ( r ) )

    if d.startswith ( "hedit:" ) :
        if not is_hadith_admin ( u.id ) : return await q.answer ( "Ruxsat yoâ€˜q",show_alert=True )
        hid=int ( d.split ( ":" )[1] ); r=one ( "SELECT * FROM hadiths WHERE id=? AND status='approved'", ( hid, ) )
        if not r: return await q.edit_message_text ( "âŒ Hadis topilmadi.",reply_markup=back_markup ( "hadith" ) )
        kb=InlineKeyboardMarkup ( [
          [InlineKeyboardButton ( "ðŸ“š Toâ€˜plam",callback_data=f"heditfield:{hid}:collection" ) ,InlineKeyboardButton ( "ðŸ”¢ Raqam",callback_data=f"heditfield:{hid}:number" ) ],
          [InlineKeyboardButton ( "ðŸ‡¸ðŸ‡¦ Arabcha",callback_data=f"heditfield:{hid}:arabic" ) ,InlineKeyboardButton ( "ðŸ‡ºðŸ‡¿ Tarjima",callback_data=f"heditfield:{hid}:translation" ) ],
          [InlineKeyboardButton ( "ðŸ“ Sharh",callback_data=f"heditfield:{hid}:explanation" ) ,InlineKeyboardButton ( "ðŸ“– Manba",callback_data=f"heditfield:{hid}:source" ) ],
          [InlineKeyboardButton ( "â¬…ï¸ Hadis",callback_data=f"hshow:{hid}" ) ] ] )
        return await q.edit_message_text ( "âœï¸ HADISNI TAHRIRLASH\n\nQaysi qismini oâ€˜zgartirasiz?",reply_markup=kb )

    if d.startswith ( "heditfield:" ) :
        if not is_hadith_admin ( u.id ) : return await q.answer ( "Ruxsat yoâ€˜q",show_alert=True )
        _,shid,field=d.split ( ":",2 ); hid=int ( shid )
        prompts={"collection":"Yangi toâ€˜plam nomini yuboring:","number":"Yangi hadis raqamini yuboring:","arabic":"Yangi arabcha matnni yuboring. Olib tashlash uchun: oâ€˜chirish","translation":"Yangi oâ€˜zbekcha tarjimani yuboring:","explanation":"Yangi sharhni yuboring. Olib tashlash uchun: oâ€˜chirish","source":"Yangi manbani yuboring. Olib tashlash uchun: oâ€˜chirish"}
        if field not in prompts: return
        STATE[u.id]={"mode":f"had_edit_{field}","data":{"hadith_id":hid}}
        return await q.edit_message_text ( "âœï¸ "+prompts[field],reply_markup=back_markup ( f"hedit:{hid}" ) )

    if d.startswith ( "hdelask:" ) :
        if not is_hadith_admin ( u.id ) : return await q.answer ( "Ruxsat yoâ€˜q",show_alert=True )
        hid=int ( d.split ( ":" )[1] ); r=one ( "SELECT collection,number FROM hadiths WHERE id=?", ( hid, ) )
        if not r: return
        kb=InlineKeyboardMarkup ( [[InlineKeyboardButton ( "âœ… Oâ€˜chirish",callback_data=f"hdel:{hid}" ) ,InlineKeyboardButton ( "âŒ Bekor",callback_data=f"hshow:{hid}" ) ]] )
        return await q.edit_message_text ( f"ðŸ—‘ {r['collection']} {r['number']} hadisni oâ€˜chirishni tasdiqlaysizmi?",reply_markup=kb )

    if d.startswith ( "hdel:" ) :
        if not is_hadith_admin ( u.id ) : return await q.answer ( "Ruxsat yoâ€˜q",show_alert=True)
        hid=int ( d.split ( ":" ) [1] ) ; r=one ( "SELECT collection,number FROM hadiths WHERE id=? AND status='approved'", ( hid, ) )
        if not r: return await q.edit_message_text ( "âŒ Hadis topilmadi.",reply_markup=back_markup ( "hadith" ) )
        execute ( "UPDATE hadiths SET status='deleted' WHERE id=?", ( hid, )  ) ; audit ( u.id,0,"hadith_delete",f"{r['collection']} {r['number']}")
        return await q.edit_message_text ( f"âœ… {r['collection']} {r['number']} oâ€˜chirildi.",reply_markup=back_markup ( "hadith" ) )

    if d=="libskipaudio":
        st=STATE.get ( u.id)
        if not st or st.get ( "mode" ) !="lib_add_audio":
            return await q.answer ( "Kitob qoâ€˜shish jarayoni faol emas.",show_alert=True)
        st["data"]["audio_file_id"]=""; st["data"]["audio_unique_id"]=""
        data=st["data"]
        with db ( ) as c:
            cur=c.execute ( """INSERT INTO library_books ( title,author,lang,description,cover_file_id,pdf_file_id,pdf_unique_id,audio_file_id,audio_unique_id,added_by,status,created_at)
                             VALUES ( ?,?,?,?,?,?,?,?,?,?,?,? ) """,
                          (data["title"],data["author"],data.get ( "lang","uz" ) ,data.get ( "description","" ) ,data.get ( "cover_file_id","" ) ,data.get ( "pdf_file_id","" ) ,data.get ( "pdf_unique_id","" ) ,"","",u.id,"approved",now (  )  ) )
            bid=cur.lastrowid
            for cat in data.get ( "categories",[] ) :
                c.execute ( "INSERT OR IGNORE INTO library_categories ( name) VALUES ( ? ) ", ( cat, ) )
                cr=c.execute ( "SELECT id FROM library_categories WHERE name=? COLLATE NOCASE", ( cat, )  ) .fetchone ( )
                c.execute ( "INSERT OR IGNORE INTO library_book_categories ( book_id,category_id) VALUES ( ?,? ) ", ( bid,cr["id"] ) )
        STATE.pop ( u.id,None ) ; audit ( u.id,0,"library_add",str ( bid ) )
        return await q.edit_message_text ( f"âœ… Kitob Vasatiya kutubxonasiga qoâ€˜shildi.\nðŸ“– {data['title']}\nID: {bid}",reply_markup=library_home_markup ( u.id ) )

    if d=="library":
        total=one ( "SELECT COUNT ( *) n FROM library_books WHERE status='approved'" ) ["n"]
        txt=f"ðŸ“š VASATIYA KUTUBXONASI\n\nJami kitoblar: {total}\nTil, kategoriya yoki qidiruv orqali kitob toping."
        try:
            if q.message.photo or q.message.video or q.message.document or q.message.audio or q.message.animation:
                await q.message.delete ( )
                return await ctx.bot.send_message ( q.message.chat.id,txt,reply_markup=library_home_markup ( u.id ) )
            return await q.edit_message_text ( txt,reply_markup=library_home_markup ( u.id ) )
        except TelegramError:
            return await ctx.bot.send_message ( q.message.chat.id,txt,reply_markup=library_home_markup ( u.id ) )

    if d=="libsearch":
        STATE[u.id]={"mode":"lib_search"}
        return await q.edit_message_text ( "ðŸ”Ž Kitob nomi, muallif yoki kalit soâ€˜zni yuboring:",reply_markup=back_markup ( "library" ) )

    if d=="libadd":
        if not is_library_admin ( u.id ) : return await q.edit_message_text ( "â›” Ruxsat yoâ€˜q.",reply_markup=back_markup ( "library" ) )
        STATE[u.id]={"mode":"lib_quick_file","data":{}}
        return await q.edit_message_text(
            "âž• KITOB QOâ€˜SHISH\n\n"
            "ðŸ“Ž Kitob faylini yuboring â€” nomini Veritas avtomatik oladi va kitobni darhol saqlaydi.\n\n"
            "âœ… PDF â€¢ EPUB â€¢ DOCX â€¢ TXT â€¢ FB2 â€¢ MOBI â€¢ DJVU\n\n"
            "Saqlangandan keyin nomi, muallifi, tili, kategoriya, tavsif va muqovani "
            "âœï¸ Tahrirlash orqali oâ€˜zgartirishingiz mumkin.",
            reply_markup=back_markup ( "library" )
        )

    if d.startswith ( "libaddlang:" ) :
        st=STATE.get ( u.id)
        if not st or st.get ( "mode" ) !="lib_add_lang": return await q.edit_message_text ( "Jarayon eskirgan. Qaytadan boshlang.",reply_markup=back_markup ( "library" ) )
        lang=d.split ( ":",1 ) [1]
        if lang not in ("uz","ru","en" ) : return
        st["data"]["lang"]=lang; st["mode"]="lib_add_categories"
        return await q.edit_message_text ( "ðŸ—‚ Kategoriyalarni vergul bilan yuboring.\nMisol: Islomiy, Hadis, Tarix")

    if d.startswith ( "libnew:" ) :
        page=max ( 0,int ( d.split ( ":" ) [1] )  ) ; per=8; off=page*per
        total=one ( "SELECT COUNT ( *) n FROM library_books WHERE status='approved'" ) ["n"]
        rows=all_ ( "SELECT id,title FROM library_books WHERE status='approved' ORDER BY id DESC LIMIT ? OFFSET ?", ( per,off ) )
        return await q.edit_message_text ( f"ðŸ†• Yangi kitoblar Â· {page+1}-sahifa",reply_markup=library_list_markup ( rows,page,"libnew",total ) )

    if d.startswith ( "liblang:" ) :
        _,lang,spage=d.split ( ":" ) ; page=max ( 0,int ( spage )  ) ; per=8; off=page*per
        total=one ( "SELECT COUNT ( *) n FROM library_books WHERE status='approved' AND lang=?", ( lang, )  ) ["n"]
        rows=all_ ( "SELECT id,title FROM library_books WHERE status='approved' AND lang=? ORDER BY id DESC LIMIT ? OFFSET ?", ( lang,per,off ) )
        return await q.edit_message_text ( f"{lib_lang_name ( lang ) } Â· {total} ta kitob",reply_markup=library_list_markup ( rows,page,"liblang",total,lang ) )

    if d.startswith ( "libfav:" ) :
        page=max ( 0,int ( d.split ( ":" ) [1] )  ) ; per=8; off=page*per
        total=one ( "SELECT COUNT ( *) n FROM library_favorites f JOIN library_books b ON b.id=f.book_id WHERE f.user_id=? AND b.status='approved'", ( u.id, )  ) ["n"]
        rows=all_ ( """SELECT b.id,b.title FROM library_favorites f JOIN library_books b ON b.id=f.book_id
                     WHERE f.user_id=? AND b.status='approved' ORDER BY f.created_at DESC LIMIT ? OFFSET ?""", ( u.id,per,off ) )
        return await q.edit_message_text ( f"â¤ï¸ Sevimlilar Â· {total} ta",reply_markup=library_list_markup ( rows,page,"libfav",total ) )

    if d=="libcats:0" or d.startswith ( "libcats:" ) :
        page=max ( 0,int ( d.split ( ":" ) [1] )  ) ; per=10; off=page*per
        total=one ( "SELECT COUNT ( *) n FROM library_categories" ) ["n"]
        rows=all_ ( "SELECT id,name FROM library_categories ORDER BY name LIMIT ? OFFSET ?", ( per,off ) )
        kb=[[InlineKeyboardButton ( "ðŸ—‚ "+r["name"][:35],callback_data=f"libcat:{r['id']}:0" ) ] for r in rows]
        nav=[]
        if page>0: nav.append ( InlineKeyboardButton ( "â—€ï¸",callback_data=f"libcats:{page-1}" ) )
        if off+per<total: nav.append ( InlineKeyboardButton ( "â–¶ï¸",callback_data=f"libcats:{page+1}" ) )
        if nav: kb.append ( nav)
        kb.append ( [InlineKeyboardButton ( "â¬…ï¸ Kutubxona",callback_data="library" ) ])
        return await q.edit_message_text ( "ðŸ—‚ KATEGORIYALAR",reply_markup=InlineKeyboardMarkup ( kb ) )

    if d.startswith ( "libcat:" ) :
        _,scid,spage=d.split ( ":" ) ; cid=int ( scid ) ; page=max ( 0,int ( spage )  ) ; per=8; off=page*per
        cr=one ( "SELECT name FROM library_categories WHERE id=?", ( cid, ) )
        if not cr: return await q.edit_message_text ( "Kategoriya topilmadi.",reply_markup=back_markup ( "library" ) )
        total=one ( """SELECT COUNT ( *) n FROM library_book_categories bc JOIN library_books b ON b.id=bc.book_id
                     WHERE bc.category_id=? AND b.status='approved'""", ( cid, )  ) ["n"]
        rows=all_ ( """SELECT b.id,b.title FROM library_book_categories bc JOIN library_books b ON b.id=bc.book_id
                     WHERE bc.category_id=? AND b.status='approved' ORDER BY b.id DESC LIMIT ? OFFSET ?""", ( cid,per,off ) )
        kb=[]
        for r in rows: kb.append ( [InlineKeyboardButton ( "ðŸ“– "+r["title"][:38],callback_data=f"libbook:{r['id']}" ) ])
        nav=[]
        if page>0: nav.append ( InlineKeyboardButton ( "â—€ï¸",callback_data=f"libcat:{cid}:{page-1}" ) )
        if off+per<total: nav.append ( InlineKeyboardButton ( "â–¶ï¸",callback_data=f"libcat:{cid}:{page+1}" ) )
        if nav: kb.append ( nav)
        kb.append ( [InlineKeyboardButton ( "â¬…ï¸ Kategoriyalar",callback_data="libcats:0" ) ])
        return await q.edit_message_text ( f"ðŸ—‚ {cr['name']} Â· {total} ta",reply_markup=InlineKeyboardMarkup ( kb ) )

    if d.startswith ( "libtranslate:" ) :
        bid=int(d.split(":")[1])
        if not ai_user_active(u.id):
            kb=InlineKeyboardMarkup([[InlineKeyboardButton("ðŸ’Ž 10 â­ â€” 30 kun",callback_data="aipbuy")],[InlineKeyboardButton("â¬…ï¸ Kitob",callback_data=f"libbook:{bid}")]])
            return await quiz_replace_message(q,ctx,"ðŸ”’ AI KITOB TARJIMASI â€” Premium funksiya.\n\nðŸ’Ž 10 â­ / 30 kun\nPremium aâ€™zo 24 soatda 1 ta kitob tarjima qila oladi.",reply_markup=kb)
        wait=_translation_wait_seconds(u.id)
        if wait>0: return await q.answer(f"â³ Kunlik limit ishlatilgan. Taxminan {(wait+3599)//3600} soat qoldi.",show_alert=True)
        kb=InlineKeyboardMarkup([[InlineKeyboardButton("ðŸ‡ºðŸ‡¿ Oâ€˜zbekcha",callback_data=f"libtrun:{bid}:uz")],[InlineKeyboardButton("ðŸ‡·ðŸ‡º Ruscha",callback_data=f"libtrun:{bid}:ru"),InlineKeyboardButton("ðŸ‡¬ðŸ‡§ English",callback_data=f"libtrun:{bid}:en")],[InlineKeyboardButton("â¬…ï¸ Kitob",callback_data=f"libbook:{bid}")]])
        return await quiz_replace_message(q,ctx,"ðŸŒ AI KITOB TARJIMASI\n\nTarjima tilini tanlang.\nPremium: 24 soatda 1 ta muvaffaqiyatli kitob tarjimasi.",reply_markup=kb)

    if d.startswith ( "libtrun:" ) :
        _,sbid,lang=d.split(":")
        task=asyncio.create_task(_run_book_translation(q,ctx,int(sbid),lang))
        def _translation_task_done(t):
            try:
                t.result()
            except asyncio.CancelledError:
                pass
            except Exception:
                log.exception("Background book translation task failed")
        task.add_done_callback(_translation_task_done)
        return

    if d.startswith ( "libquiz:" ) :
        bid=int ( d.split ( ":" )[1] )
        r=one ( "SELECT title,pdf_file_id FROM library_books WHERE id=? AND status='approved'",(bid,) )
        if not r or not r["pdf_file_id"]: return await q.answer ( "Kitob fayli mavjud emas",show_alert=True )
        groups=await _quiz_allowed_groups ( ctx,u.id )
        if not groups:
            return await quiz_replace_message ( q,ctx,"ðŸ‘¥ Test yuborish uchun Veritas ishlayotgan kamida bitta guruhda admin boâ€˜lishingiz kerak.",reply_markup=InlineKeyboardMarkup ( [[InlineKeyboardButton ( "â¬…ï¸ Kitob",callback_data=f"libbook:{bid}" ) ]] ) )
        kb=[]
        for cid,title in groups[:20]: kb.append ( [InlineKeyboardButton ( "ðŸ‘¥ "+title[:35],callback_data=f"libqgrp:{bid}:{cid}" ) ] )
        kb.append ( [InlineKeyboardButton ( "â¬…ï¸ Kitob",callback_data=f"libbook:{bid}" ) ] )
        return await quiz_replace_message ( q,ctx,f"ðŸ§  TEST TUZISH\n\nðŸ“– {r['title']}\n\nTest qaysi guruhga yuborilsin?",reply_markup=InlineKeyboardMarkup ( kb ) )

    if d.startswith ( "libqgrp:" ) :
        _,sbid,schat=d.split ( ":" ); bid=int ( sbid ); chat_id=int ( schat )
        if not is_super ( u.id ) and not await is_tg_admin ( ctx.bot,chat_id,u.id ):
            return await q.answer ( "Bu guruhda admin emassiz.",show_alert=True )
        gr=one ( "SELECT title FROM groups WHERE chat_id=?",(chat_id,) ); book=one ( "SELECT title FROM library_books WHERE id=?",(bid,) )
        if not gr or not book: return await q.answer ( "Kitob yoki guruh topilmadi.",show_alert=True )
        kb=InlineKeyboardMarkup ( [[InlineKeyboardButton ( "5 ta",callback_data=f"libqrun:{bid}:{chat_id}:5" ),InlineKeyboardButton ( "10 ta",callback_data=f"libqrun:{bid}:{chat_id}:10" ),InlineKeyboardButton ( "20 ta",callback_data=f"libqrun:{bid}:{chat_id}:20" )],[InlineKeyboardButton ( "â¬…ï¸ Guruhlar",callback_data=f"libquiz:{bid}" ) ]] )
        return await quiz_replace_message ( q,ctx,f"ðŸ§  TEST TUZISH\n\nðŸ“– {book['title']}\nðŸ‘¥ {gr['title']}\n\nNechta test tuzilsin?",reply_markup=kb )

    if d.startswith ( "libqrun:" ) :
        _,sbid,schat,scount=d.split ( ":" )
        return await _make_and_send_book_quiz ( q,ctx,int ( sbid ),int ( schat ),int ( scount ) )

    if d.startswith ( "libbook:" ) :
        return await library_show_book ( q,ctx,int ( d.split ( ":" ) [1] ) )

    if d.startswith ( "libfavtoggle:" ) :
        bid=int ( d.split ( ":" ) [1])
        if one ( "SELECT 1 FROM library_favorites WHERE user_id=? AND book_id=?", ( u.id,bid )  ) :
            execute ( "DELETE FROM library_favorites WHERE user_id=? AND book_id=?", ( u.id,bid ) )
        else: execute ( "INSERT OR IGNORE INTO library_favorites ( user_id,book_id,created_at) VALUES ( ?,?,? ) ", ( u.id,bid,now (  )  ) )
        return await library_show_book ( q,ctx,bid)

    if d.startswith("libfile:"):
        bid=int(d.split(":")[1])
        r=one("""SELECT title,book_file_id,book_file_name,book_format,pdf_file_id
                 FROM library_books WHERE id=? AND status='approved'""",(bid,))
        if not r: return await q.answer("Kitob topilmadi",show_alert=True)
        fid=r["book_file_id"] or r["pdf_file_id"]
        if not fid: return await q.answer("Kitob fayli mavjud emas",show_alert=True)
        execute("UPDATE library_books SET downloads=downloads+1 WHERE id=?",(bid,))
        try:
            return await ctx.bot.send_document(
                u.id,fid,
                caption=f"ðŸ“š {r['title']}\nðŸ“ {(r['book_format'] or 'PDF').upper()}\nVasatiya kutubxonasi"
            )
        except TelegramError:
            log.exception("Library file send failed: %s",bid)
            return await q.answer("âš ï¸ Faylni yuborishda xato.",show_alert=True)

    if d.startswith ( "libpdf:" ) :
        bid=int ( d.split ( ":" ) [1] ) ; r=one ( "SELECT title,pdf_file_id FROM library_books WHERE id=? AND status='approved'", ( bid, ) )
        if not r or not r["pdf_file_id"]: return await q.answer ( "Kitob fayli mavjud emas",show_alert=True)
        execute ( "UPDATE library_books SET downloads=downloads+1 WHERE id=?", ( bid, ) )
        await ctx.bot.send_document ( u.id,r["pdf_file_id"],caption=f"ðŸ“š {r['title']}\nVasatiya kutubxonasi")
        return

    if d.startswith ( "libaudio:" ) :
        bid=int ( d.split ( ":" ) [1] ) ; r=one ( "SELECT title,audio_file_id FROM library_books WHERE id=? AND status='approved'", ( bid, ) )
        if not r or not r["audio_file_id"]: return await q.answer ( "Audio mavjud emas",show_alert=True)
        execute ( "UPDATE library_books SET downloads=downloads+1 WHERE id=?", ( bid, ) )
        try: await ctx.bot.send_audio ( u.id,r["audio_file_id"],caption=f"ðŸŽ§ {r['title']}\nVasatiya kutubxonasi")
        except Exception: await ctx.bot.send_document ( u.id,r["audio_file_id"],caption=f"ðŸŽ§ {r['title']}")
        return

    if d.startswith ( "libedit:" ) :
        if not is_library_admin ( u.id ) : return await q.answer ( "Ruxsat yoâ€˜q",show_alert=True )
        bid=int ( d.split ( ":" )[1] ); r=one ( "SELECT id,title FROM library_books WHERE id=? AND status='approved'", ( bid, ) )
        if not r: return await q.edit_message_text ( "âŒ Kitob topilmadi.",reply_markup=back_markup ( "library" ) )
        kb=InlineKeyboardMarkup ( [
          [InlineKeyboardButton ( "ðŸ“– Nomi",callback_data=f"libeditfield:{bid}:title" ) ,InlineKeyboardButton ( "âœï¸ Muallif",callback_data=f"libeditfield:{bid}:author" ) ],
          [InlineKeyboardButton ( "ðŸŒ Til",callback_data=f"libeditfield:{bid}:lang" ) ,InlineKeyboardButton ( "ðŸ—‚ Kategoriya",callback_data=f"libeditfield:{bid}:categories" ) ],
          [InlineKeyboardButton ( "ðŸ“ Tavsif",callback_data=f"libeditfield:{bid}:description" ) ,InlineKeyboardButton ( "ðŸ–¼ Muqova",callback_data=f"libeditfield:{bid}:cover" ) ],
          [InlineKeyboardButton ( "ðŸ“„ Kitob fayli",callback_data=f"libeditfield:{bid}:pdf" ) ,InlineKeyboardButton ( "ðŸŽ§ Audio",callback_data=f"libeditfield:{bid}:audio" ) ],
          [InlineKeyboardButton ( "â¬…ï¸ Kitob",callback_data=f"libbook:{bid}" ) ] ] )
        txt=f"âœï¸ KITOBNI TAHRIRLASH\n\nðŸ“– {r['title']}\nQaysi qismini oâ€˜zgartirasiz?"
        try:
            if q.message.photo or q.message.video or q.message.document or q.message.audio or q.message.animation:
                await q.message.delete ( )
                return await ctx.bot.send_message ( q.message.chat.id,txt,reply_markup=kb )
            return await q.edit_message_text ( txt,reply_markup=kb )
        except TelegramError:
            return await ctx.bot.send_message ( q.message.chat.id,txt,reply_markup=kb )

    if d.startswith ( "libeditfield:" ) :
        if not is_library_admin ( u.id ) : return await q.answer ( "Ruxsat yoâ€˜q",show_alert=True )
        _,sbid,field=d.split ( ":",2 ); bid=int ( sbid )
        if field=="lang":
            kb=InlineKeyboardMarkup ( [[InlineKeyboardButton ( "ðŸ‡ºðŸ‡¿ Oâ€˜zbekcha",callback_data=f"libeditlang:{bid}:uz" ) ,InlineKeyboardButton ( "ðŸ‡·ðŸ‡º Ð ÑƒÑÑÐºÐ¸Ð¹",callback_data=f"libeditlang:{bid}:ru" ) ,InlineKeyboardButton ( "ðŸ‡¬ðŸ‡§ English",callback_data=f"libeditlang:{bid}:en" ) ],[InlineKeyboardButton ( "â¬…ï¸ Orqaga",callback_data=f"libedit:{bid}" ) ]] )
            return await q.edit_message_text ( "ðŸŒ Yangi tilni tanlang:",reply_markup=kb )
        prompts={"title":"Yangi kitob nomini yuboring:","author":"Yangi muallif nomini yuboring:","categories":"Yangi kategoriyalarni vergul bilan yuboring:","description":"Yangi tavsifni yuboring:","cover":"Yangi muqova rasmini yuboring. Olib tashlash uchun: oâ€˜chirish","pdf":"Yangi kitob faylini yuboring (PDF/EPUB/DOCX/TXT/FB2/MOBI/DJVU):","audio":"Yangi audio/voice/audio-fayl yuboring. Olib tashlash uchun: oâ€˜chirish"}
        if field not in prompts: return
        STATE[u.id]={"mode":f"lib_edit_{field}","data":{"book_id":bid}}
        return await q.edit_message_text ( "âœï¸ "+prompts[field],reply_markup=back_markup ( f"libedit:{bid}" ) )

    if d.startswith ( "libeditlang:" ) :
        if not is_library_admin ( u.id ) : return await q.answer ( "Ruxsat yoâ€˜q",show_alert=True )
        _,sbid,lang=d.split ( ":",2 ); bid=int ( sbid )
        if lang not in {"uz","ru","en"}: return
        execute ( "UPDATE library_books SET lang=? WHERE id=?", ( lang,bid ) ); audit ( u.id,0,"library_edit",f"{bid}:lang" )
        return await q.edit_message_text ( "âœ… Kitob tili yangilandi.",reply_markup=InlineKeyboardMarkup ( [[InlineKeyboardButton ( "âœï¸ Tahrirlash",callback_data=f"libedit:{bid}" ) ,InlineKeyboardButton ( "ðŸ“– Kitob",callback_data=f"libbook:{bid}" ) ]] ) )

    if d.startswith ( "libdelask:" ) :
        if not is_library_admin ( u.id ) : return
        bid=int ( d.split ( ":" ) [1] ) ; r=one ( "SELECT title FROM library_books WHERE id=?", ( bid, ) )
        if not r: return
        kb=InlineKeyboardMarkup ( [[InlineKeyboardButton ( "âœ… Ha, oâ€˜chirish",callback_data=f"libdel:{bid}" ) ,InlineKeyboardButton ( "âŒ Bekor",callback_data=f"libbook:{bid}" ) ]])
        return await q.edit_message_text ( f"ðŸ—‘ Â«{r['title']}Â» kitobini oâ€˜chirishni tasdiqlaysizmi?",reply_markup=kb)

    if d.startswith ( "libdel:" ) :
        if not is_library_admin ( u.id ) : return
        bid=int ( d.split ( ":" ) [1] ) ; execute ( "UPDATE library_books SET status='deleted' WHERE id=?", ( bid, )  ) ; audit ( u.id,0,"library_delete",str ( bid ) )
        return await q.edit_message_text ( "âœ… Kitob kutubxonadan olib tashlandi.",reply_markup=library_home_markup ( u.id ) )

    if d=="super":
        if not is_super ( u.id ): return await q.edit_message_text ( "â›” Ruxsat yoâ€˜q.")
        uc=one ( "SELECT COUNT ( *) n FROM users" ) ["n"]; gc=one ( "SELECT COUNT ( *) n FROM groups" ) ["n"]
        return await q.edit_message_text ( f"ðŸ‘‘ SUPER BOSHQARUV\nðŸŽ– {super_role ( u.id )}\nFoydalanuvchilar: {uc}\nGuruhlar: {gc}",reply_markup=super_menu_markup ( u.id ) )

    if d.startswith ( "alladmins:" ) :
        if not is_super ( u.id ): return
        page=max ( 0,int ( d.split ( ":" ) [1] )  ) ; per=8
        entries=[]
        for sid in sorted ( SUPER_OWNERS ) :
            ur=one ( "SELECT first_name,username FROM users WHERE user_id=?", ( sid, ) )
            nm= ( ur["first_name"] if ur and ur["first_name"] else str ( sid ) )
            if ur and ur["username"]: nm += " @"+ur["username"]
            entries.append (  ( "ðŸ‘‘ Super Ega",sid,nm,"" ) )
        for r in all_ ( "SELECT a.user_id,u.first_name,u.username FROM super_admins a LEFT JOIN users u ON u.user_id=a.user_id ORDER BY a.created_at DESC" ) :
            nm=( r["first_name"] or str ( r["user_id"] ) ) + ( ( " @"+r["username"] ) if r["username"] else "" )
            entries.append ( ( "ðŸ›¡ Super Admin",int ( r["user_id"] ),nm,"" ) )
        for r in all_ ( "SELECT a.user_id,u.first_name,u.username FROM library_admins a LEFT JOIN users u ON u.user_id=a.user_id ORDER BY a.created_at DESC" ) :
            nm= ( r["first_name"] or str ( r["user_id"] ) ) + ( ( " @"+r["username"]) if r["username"] else "")
            entries.append (  ( "ðŸ“š Kitob admini",int ( r["user_id"] ) ,nm,"" ) )
        for r in all_ ( "SELECT a.user_id,u.first_name,u.username FROM hadith_admins a LEFT JOIN users u ON u.user_id=a.user_id ORDER BY a.created_at DESC" ) :
            nm= ( r["first_name"] or str ( r["user_id"] ) ) + ( ( " @"+r["username"]) if r["username"] else "")
            entries.append (  ( "ðŸ“œ Hadis admini",int ( r["user_id"] ) ,nm,"" ) )
        for r in all_ ( """SELECT v.user_id,v.chat_id,u.first_name,u.username,g.title FROM vadmins v
                         LEFT JOIN users u ON u.user_id=v.user_id LEFT JOIN groups g ON g.chat_id=v.chat_id
                         ORDER BY g.title,u.first_name""" ) :
            nm= ( r["first_name"] or str ( r["user_id"] ) ) + ( ( " @"+r["username"]) if r["username"] else "")
            entries.append (  ( "ðŸª¶ Veritas admini",int ( r["user_id"] ) ,nm,r["title"] or str ( r["chat_id"] )  ) )
        # Bir odam bir necha rolga ega boâ€˜lishi mumkin â€” rollar alohida koâ€˜rsatiladi.
        total=len ( entries ) ; off=page*per; chunk=entries[off:off+per]
        lines=[f"ðŸ›¡ BARCHA ADMINLAR\nJami rollar: {total} | Sahifa: {page+1}\n"]
        for role,uid2,nm,grp in chunk:
            lines.append ( f"{role}\nâ€¢ {nm}\nâ€¢ ID: {uid2}" + (f"\nâ€¢ Guruh: {grp}" if grp else "" ) )
        if not chunk: lines.append ( "Admin topilmadi.")
        nav=[]
        if page>0: nav.append ( InlineKeyboardButton ( "â—€ï¸",callback_data=f"alladmins:{page-1}" ) )
        if off+per<total: nav.append ( InlineKeyboardButton ( "â–¶ï¸",callback_data=f"alladmins:{page+1}" ) )
        kb=[]
        if nav: kb.append ( nav)
        kb.append ( [InlineKeyboardButton ( "â¬…ï¸ Super Ega",callback_data="super" ) ,InlineKeyboardButton ( "ðŸ  Bosh menyu",callback_data="home" ) ])
        return await q.edit_message_text ( "\n\n".join ( lines ) ,reply_markup=InlineKeyboardMarkup ( kb ) )

    if d.startswith ( "botgroups:" ) :
        if not is_super ( u.id ): return
        page=max ( 0,int ( d.split ( ":" ) [1] )  ) ; per=8; off=page*per
        rows=all_ ( "SELECT chat_id,title,owner_id,created_at,demo_until,paid_until,free FROM groups ORDER BY created_at DESC,chat_id DESC LIMIT ? OFFSET ?", ( per,off ) )
        total=one ( "SELECT COUNT ( *) n FROM groups" ) ["n"]
        lines=[f"ðŸ˜ BOT ISHLAYOTGAN GURUHLAR\nJami: {total} | Sahifa: {page+1}\n"]
        for i,r in enumerate ( rows,off+1 ) :
            owner= ( f" | Ega ID: {r['owner_id']}" if r['owner_id'] else "")
            lines.append ( f"{i}. {r['title'] or 'Nomsiz guruh'}\nðŸ†” {r['chat_id']}{owner}")
        if not rows: lines.append ( "Guruh topilmadi.")
        nav=[]
        if page>0: nav.append ( InlineKeyboardButton ( "â—€ï¸",callback_data=f"botgroups:{page-1}" ) )
        if off+per<total: nav.append ( InlineKeyboardButton ( "â–¶ï¸",callback_data=f"botgroups:{page+1}" ) )
        kb=[]
        if nav: kb.append ( nav)
        kb.append ( [InlineKeyboardButton ( "â¬…ï¸ Super Ega",callback_data="super" ) ,InlineKeyboardButton ( "ðŸ  Bosh menyu",callback_data="home" ) ])
        return await q.edit_message_text ( "\n\n".join ( lines ) ,reply_markup=InlineKeyboardMarkup ( kb ) )

    if d.startswith ( "cabs:" ) :
        if not is_super ( u.id ): return
        page=max ( 0,int ( d.split ( ":" ) [1] )  ) ; per=8; off=page*per
        rows=all_ ( "SELECT user_id,username,first_name,wallet FROM users ORDER BY created_at DESC,user_id DESC LIMIT ? OFFSET ?", ( per,off ) )
        total=one ( "SELECT COUNT ( *) n FROM users" ) ["n"]
        kb=[]
        for r in rows:
            name= ( r["first_name"] or r["username"] or str ( r["user_id"] )  ) [:28]
            kb.append ( [InlineKeyboardButton ( f"ðŸ‘¤ {name} Â· {r['wallet']}â­",callback_data=f"cab:{r['user_id']}:{page}" ) ])
        nav=[]
        if page>0: nav.append ( InlineKeyboardButton ( "â—€ï¸",callback_data=f"cabs:{page-1}" ) )
        if off+per<total: nav.append ( InlineKeyboardButton ( "â–¶ï¸",callback_data=f"cabs:{page+1}" ) )
        if nav: kb.append ( nav)
        kb.append ( [InlineKeyboardButton ( "â¬…ï¸ Orqaga",callback_data="super" ) ,InlineKeyboardButton ( "ðŸ  Bosh menyu",callback_data="home" ) ])
        return await q.edit_message_text ( f"ðŸ‘¥ SHAXSIY KABINETLAR\nJami: {total} | Sahifa: {page+1}",reply_markup=InlineKeyboardMarkup ( kb ) )

    if d.startswith ( "cab:" ) :
        if not is_super ( u.id ): return
        _,sid,spage=d.split ( ":" ) ; uid=int ( sid ) ; page=int ( spage)
        r=one ( "SELECT * FROM users WHERE user_id=?", ( uid, ) )
        if not r: return await q.edit_message_text ( "Foydalanuvchi topilmadi.",reply_markup=back_markup ( "super" ) )
        xp,msgs=user_total_stats ( uid)
        mr=one ( "SELECT title FROM members WHERE user_id=? AND title<>'' ORDER BY messages DESC LIMIT 1", ( uid, ) )
        custom=mr["title"] if mr else ""
        uname= ( "@"+r["username"]) if r["username"] else "â€”"
        text= ( f"ðŸ‘¤ SHAXSIY KABINET\n\nIsm: {r['first_name'] or 'â€”'}\nUsername: {uname}\nðŸ†” ID: {uid}\n"
              f"ðŸŽ– Unvon: {title_for ( uid,custom ) }\nâ­ Kredit: {r['wallet']}\nâœ¨ XP: {xp}\nðŸ’¬ Xabarlar: {msgs}\nðŸ“ˆ Level: {level ( xp ) }")
        kb=InlineKeyboardMarkup ( [[InlineKeyboardButton ( "â¬…ï¸ Kabinetlar",callback_data=f"cabs:{page}" ) ,InlineKeyboardButton ( "ðŸ  Bosh menyu",callback_data="home" ) ]])
        return await q.edit_message_text ( text,reply_markup=kb)

async def giveaway_job ( ctx ) :
    rows=all_ ( "SELECT * FROM giveaways WHERE status='open' AND end_at<=?", ( now (  ) , ) )
    for g in rows:
        entries=[r["user_id"] for r in all_ ( "SELECT user_id FROM giveaway_entries WHERE giveaway_id=?", ( g["id"], )  ) ]
        random.shuffle ( entries ) ; winners=entries[:min ( g["winners"],len ( entries )  ) ]
        execute ( "UPDATE giveaways SET status='closed' WHERE id=?", ( g["id"], ) )
        if not winners:
            try: await ctx.bot.send_message ( g["chat_id"],"ðŸŽ‰ Konkurs tugadi. Ishtirokchi yoâ€˜q.")
            except TelegramError: pass
            continue
        sent=[]
        for uid in winners:
            price=int ( g["prize"])
            try:
                gifts=await ctx.bot.get_available_gifts ( )
                cand=next (  ( x for x in gifts.gifts if int ( x.star_count ) ==price and (getattr ( x,"remaining_count",None) is None or getattr ( x,"remaining_count",0 ) >0 )  ) ,None)
                if not cand or wallet ( g["creator_id"] ) <price: continue
                if not wallet_change ( g["creator_id"],-price,"giveaway_gift_pending",uid ) : continue
                try:
                    await ctx.bot.send_gift ( user_id=uid,gift_id=cand.id,text="ðŸ† Veritas Giveaway sovrini")
                    sent.append ( uid)
                except Exception:
                    wallet_change ( g["creator_id"],price,"giveaway_rollback",uid)
            except Exception: pass
        try: await ctx.bot.send_message ( g["chat_id"],"ðŸ† Gâ€˜oliblar: "+", ".join ( str ( x) for x in winners ) + ( "\nðŸŽ Gift yuborildi: "+", ".join ( str ( x) for x in sent) if sent else "\nâš ï¸ Gift yuborish uchun yaratuvchi krediti/Gift mavjudligini tekshiring." ) )
        except TelegramError: pass

async def error_handler ( update,ctx ) :
    log.exception ( "Handler error",exc_info=ctx.error)


# =========================================================
# V8 ROSE FULL â€” advanced moderation compatibility layer
# =========================================================
ROSE_REPEAT_CACHE = {}
ROSE_JOIN_CACHE = {}

def rose_full_init_db():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS rose_settings(
          chat_id INTEGER PRIMARY KEY,
          anti_repeat INTEGER DEFAULT 1, repeat_limit INTEGER DEFAULT 4, repeat_window INTEGER DEFAULT 30,
          anti_raid INTEGER DEFAULT 1, raid_join_limit INTEGER DEFAULT 8, raid_window INTEGER DEFAULT 20,
          raid_mute_seconds INTEGER DEFAULT 300, clean_commands INTEGER DEFAULT 0,
          welcome_text TEXT DEFAULT '', goodbye_text TEXT DEFAULT '',
          lock_forward INTEGER DEFAULT 0, lock_contact INTEGER DEFAULT 0, lock_location INTEGER DEFAULT 0,
          lock_poll INTEGER DEFAULT 0, lock_photo INTEGER DEFAULT 0, lock_video INTEGER DEFAULT 0,
          lock_audio INTEGER DEFAULT 0, lock_voice INTEGER DEFAULT 0, lock_document INTEGER DEFAULT 0,
          lock_sticker INTEGER DEFAULT 0, lock_animation INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS temp_moderation(
          chat_id INTEGER NOT NULL,user_id INTEGER NOT NULL,kind TEXT NOT NULL,until_ts INTEGER NOT NULL,
          PRIMARY KEY(chat_id,user_id,kind)
        );
        CREATE TABLE IF NOT EXISTS owner_messages(
          id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,username TEXT DEFAULT '',first_name TEXT DEFAULT '',
          status TEXT DEFAULT 'new',handled_by INTEGER DEFAULT 0,created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS owner_message_events(
          id INTEGER PRIMARY KEY AUTOINCREMENT,ticket_id INTEGER NOT NULL,sender_id INTEGER NOT NULL,kind TEXT NOT NULL,created_at INTEGER NOT NULL
        );
        """)

def rose_row(chat_id):
    execute("INSERT OR IGNORE INTO rose_settings(chat_id) VALUES(?)",(chat_id,))
    return one("SELECT * FROM rose_settings WHERE chat_id=?",(chat_id,))

def parse_duration(v):
    m=re.fullmatch(r"(\d+)(s|m|h|d|w)?",(v or '').lower())
    if not m:return 0
    n=int(m.group(1)); unit=m.group(2) or 'm'
    return n*{'s':1,'m':60,'h':3600,'d':86400,'w':604800}[unit]

def rose_content_kind(msg):
    if msg.forward_origin:return 'forward'
    if msg.contact:return 'contact'
    if msg.location or msg.venue:return 'location'
    if msg.poll:return 'poll'
    if msg.photo:return 'photo'
    if msg.video:return 'video'
    if msg.audio:return 'audio'
    if msg.voice:return 'voice'
    if msg.document:return 'document'
    if msg.sticker:return 'sticker'
    if msg.animation:return 'animation'
    return ''

async def rose_delete(msg):
    try: await msg.delete(); return True
    except TelegramError:return False

async def rose_advanced_command(update,ctx,cmd,args):
    chat=update.effective_chat; msg=update.effective_message; actor=update.effective_user
    if not chat or chat.type not in ('group','supergroup'): return False
    if cmd not in {'purge','pin','unpin','lockall','unlockall','cleanservice','antirepeat','raid','modlog','setwelcome','setgoodbye','tempban','tempmute'}:
        return False
    if not await can_manage(ctx.bot,chat.id,actor.id):
        await msg.reply_text('â›” Bu buyruq uchun admin huquqi kerak.'); return True
    rose_row(chat.id)
    if cmd=='purge':
        if not msg.reply_to_message:
            await msg.reply_text('â†©ï¸ Boshlanish xabariga reply qilib *purge yozing.'); return True
        start=msg.reply_to_message.message_id; end=msg.message_id; deleted=0
        for mid in range(start,end+1):
            try: await ctx.bot.delete_message(chat.id,mid); deleted+=1
            except TelegramError: pass
        try: await ctx.bot.send_message(chat.id,f'ðŸ§¹ {deleted} ta xabar tozalandi.')
        except TelegramError: pass
        return True
    if cmd=='pin':
        t=msg.reply_to_message
        if not t: await msg.reply_text('â†©ï¸ Pin qilinadigan xabarga reply qiling.'); return True
        try: await ctx.bot.pin_chat_message(chat.id,t.message_id,disable_notification=True); await msg.reply_text('ðŸ“Œ Xabar pin qilindi.')
        except TelegramError as e: await msg.reply_text(f'âŒ Pin boâ€˜lmadi: {e}')
        return True
    if cmd=='unpin':
        try: await ctx.bot.unpin_chat_message(chat.id); await msg.reply_text('ðŸ“Œ Pin olib tashlandi.')
        except TelegramError as e: await msg.reply_text(f'âŒ {e}')
        return True
    if cmd in {'lockall','unlockall'}:
        val=1 if cmd=='lockall' else 0
        cols=['lock_forward','lock_contact','lock_location','lock_poll','lock_photo','lock_video','lock_audio','lock_voice','lock_document','lock_sticker','lock_animation']
        execute('UPDATE rose_settings SET '+','.join(f'{x}=?' for x in cols)+' WHERE chat_id=?',tuple([val]*len(cols)+[chat.id]))
        await msg.reply_text('ðŸ”’ Barcha media lock yoqildi.' if val else 'ðŸ”“ Barcha media lock oâ€˜chirildi.'); return True
    if cmd=='cleanservice':
        if not args or args[0].lower() not in ('on','off'): await msg.reply_text('*cleanservice on/off'); return True
        execute('UPDATE moderation_settings SET clean_service=? WHERE chat_id=?',(1 if args[0].lower()=='on' else 0,chat.id))
        await msg.reply_text('âœ… Service xabarlar sozlamasi saqlandi.'); return True
    if cmd=='antirepeat':
        if not args or args[0].lower() not in ('on','off'): await msg.reply_text('*antirepeat on/off [limit]'); return True
        val=1 if args[0].lower()=='on' else 0; lim=int(args[1]) if len(args)>1 and args[1].isdigit() else 4
        execute('UPDATE rose_settings SET anti_repeat=?,repeat_limit=? WHERE chat_id=?',(val,max(2,min(lim,10)),chat.id))
        await msg.reply_text('ðŸ” Anti-repeat yangilandi.'); return True
    if cmd=='raid':
        if not args or args[0].lower() not in ('on','off'): await msg.reply_text('*raid on/off'); return True
        execute('UPDATE rose_settings SET anti_raid=? WHERE chat_id=?',(1 if args[0].lower()=='on' else 0,chat.id)); await msg.reply_text('ðŸ›¡ Anti-raid yangilandi.'); return True
    if cmd in {'setwelcome','setgoodbye'}:
        txt=' '.join(args).strip()
        if not txt and msg.reply_to_message: txt=msg.reply_to_message.text or msg.reply_to_message.caption or ''
        if not txt: await msg.reply_text(f'*{cmd} <matn>'); return True
        col='welcome_text' if cmd=='setwelcome' else 'goodbye_text'; execute(f'UPDATE rose_settings SET {col}=? WHERE chat_id=?',(txt,chat.id)); await msg.reply_text('âœ… Matn saqlandi.'); return True
    if cmd=='modlog':
        rows=all_('SELECT * FROM moderation_log WHERE chat_id=? ORDER BY id DESC LIMIT 15',(chat.id,))
        if not rows: await msg.reply_text('ðŸ“‹ Moderatsiya logi boâ€˜sh.'); return True
        lines=['ðŸ“‹ SOâ€˜NGGI MODERATSIYA']
        for r in rows: lines.append(f"â€¢ {r['action']} | {r['target_id']} | {r['reason'] or 'sababsiz'}")
        await msg.reply_text('\n'.join(lines)); return True
    if cmd in {'tempmute','tempban'}:
        t=msg.reply_to_message
        if not t or not t.from_user: await msg.reply_text(f'â†©ï¸ Foydalanuvchiga reply qilib *{cmd} 10m [sabab]'); return True
        if not args: await msg.reply_text('â± Vaqt kiriting: 10m, 2h, 1d'); return True
        sec=parse_duration(args[0]); reason=' '.join(args[1:]) or 'Sabab koâ€˜rsatilmagan'
        if sec<=0: await msg.reply_text('âŒ Vaqt formati notoâ€˜gâ€˜ri.'); return True
        until=now()+sec
        try:
            if cmd=='tempmute': await ctx.bot.restrict_chat_member(chat.id,t.from_user.id,ChatPermissions(can_send_messages=False),until_date=datetime.fromtimestamp(until,timezone.utc))
            else: await ctx.bot.ban_chat_member(chat.id,t.from_user.id,until_date=datetime.fromtimestamp(until,timezone.utc))
            execute('INSERT OR REPLACE INTO temp_moderation VALUES(?,?,?,?)',(chat.id,t.from_user.id,cmd,until))
            execute('INSERT INTO moderation_log(chat_id,actor_id,target_id,action,reason,duration,created_at) VALUES(?,?,?,?,?,?,?)',(chat.id,actor.id,t.from_user.id,cmd,reason,sec,now()))
            await msg.reply_text(f"âœ… {t.from_user.first_name}: {cmd} â€” {args[0]}\nðŸ“ {reason}")
        except TelegramError as e: await msg.reply_text(f'âŒ Amal bajarilmadi: {e}')
        return True
    return False

_original_star_text_router=star_text_router
async def star_text_router(update,ctx):
    msg=update.effective_message
    if msg and msg.text and msg.text.startswith('*'):
        parts=msg.text[1:].strip().split(); cmd=parts[0].lower() if parts else ''; args=parts[1:]
        if await rose_advanced_command(update,ctx,cmd,args): return
    return await _original_star_text_router(update,ctx)

_original_passive=passive
async def passive(update,ctx):
    msg=update.effective_message; chat=update.effective_chat; u=update.effective_user
    if msg and chat and u and not u.is_bot and chat.type in ('group','supergroup'):
        ensure_group(chat); rr=rose_row(chat.id)
        if not await protected(ctx.bot,chat.id,u.id) and not one('SELECT 1 FROM approved WHERE chat_id=? AND user_id=?',(chat.id,u.id)):
            kind=rose_content_kind(msg)
            if kind and rr[f'lock_{kind}']:
                await rose_delete(msg); return
            txt=(msg.text or msg.caption or '').strip().lower()
            if rr['anti_repeat'] and txt:
                key=(chat.id,u.id,txt[:500]); ts=now(); arr=[x for x in ROSE_REPEAT_CACHE.get(key,[]) if ts-x<=rr['repeat_window']]; arr.append(ts); ROSE_REPEAT_CACHE[key]=arr
                if len(arr)>=rr['repeat_limit']:
                    await rose_delete(msg)
                    try: await ctx.bot.restrict_chat_member(chat.id,u.id,ChatPermissions(can_send_messages=False),until_date=datetime.now(timezone.utc)+timedelta(minutes=2)); await ctx.bot.send_message(chat.id,f'ðŸ” {u.first_name}: takroriy spam sabab 2 daqiqa mute.')
                    except TelegramError: pass
                    ROSE_REPEAT_CACHE[key]=[]; return
    # Mazgila AI tarmoq chaqiruvi umumiy group handlerni kutdirib qoâ€˜ymasligi uchun
    # alohida taskda ishlaydi. Rose media/anti-repeat tekshiruvlari yuqorida avval bajariladi.
    try:
        asyncio.create_task(mazgila_maybe_reply(update,ctx))
    except Exception:
        log.exception('mazgila passive schedule failed')
    return await _original_passive(update,ctx)

_original_new_members=new_members
async def new_members(update,ctx):
    chat=update.effective_chat; msg=update.effective_message
    if chat and chat.type in ('group','supergroup'):
        ensure_group(chat)
        rr=rose_row(chat.id); ts=now(); arr=[x for x in ROSE_JOIN_CACHE.get(chat.id,[]) if ts-x<=rr['raid_window']]
        arr += [ts]*len(msg.new_chat_members or []); ROSE_JOIN_CACHE[chat.id]=arr
        if rr['anti_raid'] and len(arr)>=rr['raid_join_limit']:
            for nu in msg.new_chat_members or []:
                if not nu.is_bot:
                    try: await ctx.bot.restrict_chat_member(chat.id,nu.id,ChatPermissions(can_send_messages=False),until_date=datetime.now(timezone.utc)+timedelta(seconds=rr['raid_mute_seconds']))
                    except TelegramError: pass
            try: await ctx.bot.send_message(chat.id,'ðŸš¨ Anti-raid ishga tushdi. Yangi aâ€™zolar vaqtincha cheklab qoâ€˜yildi.')
            except TelegramError: pass
        custom=rr['welcome_text']
        if custom:
            names=', '.join(x.first_name for x in msg.new_chat_members or [])
            txt=custom.replace('{first}',names).replace('{chatname}',chat.title or '')
            try: await msg.reply_text(txt)
            except TelegramError: pass
            st=moderation_settings(chat.id)
            if st and st['clean_service']:
                try: await msg.delete()
                except TelegramError: pass
            return
    return await _original_new_members(update,ctx)

_original_left_member=left_member
async def left_member(update,ctx):
    chat=update.effective_chat; msg=update.effective_message
    if chat and chat.type in ('group','supergroup'):
        rr=rose_row(chat.id); custom=rr['goodbye_text']; lu=msg.left_chat_member
        if custom and lu:
            txt=custom.replace('{first}',lu.first_name or '').replace('{chatname}',chat.title or '')
            try: await msg.reply_text(txt)
            except TelegramError: pass
            st=moderation_settings(chat.id)
            if st and st['clean_service']:
                try: await msg.delete()
                except TelegramError: pass
            return
    return await _original_left_member(update,ctx)

async def owner_message_state_handler(update,ctx):
    if ctx.user_data.get("bayram_consumed_message_id")==getattr(update.effective_message,"message_id",None):return
    msg=update.effective_message; u=update.effective_user; chat=update.effective_chat
    if not msg or not u or not chat or chat.type!="private": return
    st=STATE.get(u.id) or {}; mode=st.get("mode")
    if mode not in {"owner_message","owner_reply"}: return
    ctx.user_data["owner_consumed_message_id"]=msg.message_id

    if mode=="owner_message":
        ensure_user(u)
        with db() as c:
            cur=c.execute("INSERT INTO owner_messages(user_id,username,first_name,status,created_at) VALUES(?,?,?,?,?)",
                          (u.id,u.username or '',u.first_name or '',"new",now()))
            tid=cur.lastrowid
            c.execute("INSERT INTO owner_message_events(ticket_id,sender_id,kind,created_at) VALUES(?,?,?,?)",(tid,u.id,"user_message",now()))
        STATE.pop(u.id,None)
        header=(f"ðŸ“¨ YANGI MUROJAAT #{tid}\\nâ”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\\n"
                f"ðŸ‘¤ {u.full_name}\\nðŸ†” {u.id}\\nðŸ”— @{u.username}" if u.username else
                f"ðŸ“¨ YANGI MUROJAAT #{tid}\\nâ”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\\nðŸ‘¤ {u.full_name}\\nðŸ†” {u.id}")
        kb=InlineKeyboardMarkup([
            [InlineKeyboardButton("âœ‰ï¸ Javob berish",callback_data=f"ownerreply:{tid}")],
            [InlineKeyboardButton("âœ… Koâ€˜rildi",callback_data=f"ownerseen:{tid}"),InlineKeyboardButton("ðŸ—‘ Yopish",callback_data=f"ownerclose:{tid}")]
        ])
        delivered=0
        for oid in SUPER_OWNERS:
            try:
                await ctx.bot.send_message(oid,header,reply_markup=kb)
                await msg.copy(chat_id=oid)
                delivered+=1
            except TelegramError:
                pass
        if delivered:
            return await msg.reply_text(f"âœ… Xabaringiz egalariga yuborildi.\\nðŸ“¨ Murojaat raqami: #{tid}",reply_markup=main_menu_markup(u.id))
        return await msg.reply_text("âš ï¸ Xabar saqlandi, lekin egaga Telegram orqali yetkazib boâ€˜lmadi. Ega botga /start bosganini tekshiring.",reply_markup=main_menu_markup(u.id))

    tid=int(st.get("ticket_id",0)); target=int(st.get("target_id",0))
    if u.id not in SUPER_OWNERS or not tid or not target:
        STATE.pop(u.id,None); return
    try:
        await ctx.bot.send_message(target,f"âœ‰ï¸ EGADAN JAVOB â€” murojaat #{tid}")
        await msg.copy(chat_id=target)
        execute("UPDATE owner_messages SET status='answered',handled_by=? WHERE id=?",(u.id,tid))
        execute("INSERT INTO owner_message_events(ticket_id,sender_id,kind,created_at) VALUES(?,?,?,?)",(tid,u.id,"owner_reply",now()))
        STATE.pop(u.id,None)
        return await msg.reply_text(f"âœ… Javob #{tid} murojaat egasiga yuborildi.")
    except TelegramError as e:
        return await msg.reply_text(f"âŒ Javob yuborilmadi: {e}")

async def rose_cleanup_job(ctx):
    rows=all_('SELECT * FROM temp_moderation WHERE until_ts<=?',(now(),))
    for r in rows:
        try:
            if r['kind']=='tempmute': await ctx.bot.restrict_chat_member(r['chat_id'],r['user_id'],ChatPermissions(can_send_messages=True,can_send_audios=True,can_send_documents=True,can_send_photos=True,can_send_videos=True,can_send_video_notes=True,can_send_voice_notes=True,can_send_polls=True,can_send_other_messages=True,can_add_web_page_previews=True,can_invite_users=True))
            elif r['kind']=='tempban': await ctx.bot.unban_chat_member(r['chat_id'],r['user_id'],only_if_banned=True)
        except TelegramError: pass
        execute('DELETE FROM temp_moderation WHERE chat_id=? AND user_id=? AND kind=?',(r['chat_id'],r['user_id'],r['kind']))


# ============================================================
# VERITAS *BAYRAM â€” mustaqil qoâ€˜shimcha; V8/V9 kodiga tegmaydi
# ============================================================
import html as _bayram_html
from PIL import Image, ImageDraw, ImageFont

BAYRAM_WINDOW_SECONDS = 10 * 3600

def bayram_init_db():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS bayram_campaigns(
            id INTEGER PRIMARY KEY AUTOINCREMENT,chat_id INTEGER NOT NULL,
            creator_id INTEGER NOT NULL,winner_count INTEGER DEFAULT 0,
            gift_price INTEGER DEFAULT 0,gift_id TEXT DEFAULT '',
            greeting TEXT DEFAULT '',status TEXT DEFAULT 'draft',
            created_at INTEGER NOT NULL,confirmed_at INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS bayram_winners(
            campaign_id INTEGER NOT NULL,user_id INTEGER NOT NULL,
            msg_count INTEGER NOT NULL,status TEXT DEFAULT 'pending',
            error TEXT DEFAULT '',PRIMARY KEY(campaign_id,user_id));
        CREATE INDEX IF NOT EXISTS idx_bayram_history_time
            ON group_message_history(chat_id,created_at,user_id);
        CREATE TABLE IF NOT EXISTS group_chat_archive(
            chat_id INTEGER NOT NULL,message_id INTEGER NOT NULL,user_id INTEGER NOT NULL,
            display_name TEXT DEFAULT '',username TEXT DEFAULT '',body TEXT DEFAULT '',
            media_type TEXT DEFAULT '',created_at INTEGER NOT NULL,
            PRIMARY KEY(chat_id,message_id));
        CREATE INDEX IF NOT EXISTS idx_group_chat_archive_page
            ON group_chat_archive(chat_id,message_id DESC);
        """)

def archive_group_message(msg,u,chat):
    if not msg or not u or u.is_bot or not chat or chat.type not in ("group","supergroup"):
        return
    body=(msg.text or msg.caption or "").strip()
    media_type=""
    if msg.photo: media_type="photo"
    elif msg.video: media_type="video"
    elif msg.voice: media_type="voice"
    elif msg.audio: media_type="audio"
    elif msg.document: media_type="document"
    elif msg.sticker: media_type="sticker"
    elif msg.animation: media_type="animation"
    if not body and media_type: body=f"[{media_type}]"
    if not body: return
    execute("""INSERT OR REPLACE INTO group_chat_archive
             (chat_id,message_id,user_id,display_name,username,body,media_type,created_at)
             VALUES(?,?,?,?,?,?,?,?)""",
            (chat.id,msg.message_id,u.id,u.full_name or u.first_name or "",u.username or "",body[:8000],media_type,now()))

def chat_archive_groups():
    return all_("""SELECT a.chat_id,COALESCE(g.title,CAST(a.chat_id AS TEXT)) title,COUNT(*) n,MAX(a.created_at) last_at
                  FROM group_chat_archive a LEFT JOIN groups g ON g.chat_id=a.chat_id
                  GROUP BY a.chat_id ORDER BY last_at DESC""")

def chat_archive_page(chat_id,offset=0,limit=30):
    return all_("""SELECT * FROM group_chat_archive WHERE chat_id=?
                  ORDER BY message_id DESC LIMIT ? OFFSET ?""",(chat_id,limit,offset))

def _chat_font(size=26,bold=False):
    """Unicode font for chat screenshots. Tries system/Pillow fonts, then caches Noto Sans."""
    candidates=[]
    try:
        import PIL
        pil_dir=Path(PIL.__file__).resolve().parent
        candidates += [
            str(pil_dir/'fonts'/'DejaVuSans-Bold.ttf' if bold else pil_dir/'fonts'/'DejaVuSans.ttf'),
            str(pil_dir/'DejaVuSans-Bold.ttf' if bold else pil_dir/'DejaVuSans.ttf'),
        ]
    except Exception:
        pass
    candidates += [
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf' if bold else '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf' if bold else '/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf',
        '/usr/share/fonts/opentype/noto/NotoSans-Bold.ttf' if bold else '/usr/share/fonts/opentype/noto/NotoSans-Regular.ttf',
        '/usr/share/fonts/truetype/freefont/FreeSansBold.ttf' if bold else '/usr/share/fonts/truetype/freefont/FreeSans.ttf',
        'DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf',
    ]
    cache=Path('/tmp/veritas_fonts'); cache.mkdir(parents=True,exist_ok=True)
    noto=cache/('NotoSans-Bold.ttf' if bold else 'NotoSans-Regular.ttf')
    candidates.append(str(noto))
    for fp in candidates:
        try:
            return ImageFont.truetype(fp,size)
        except Exception:
            pass
    # Railway image has no Unicode font: fetch a compact Noto font once and cache it.
    try:
        url=('https://raw.githubusercontent.com/googlefonts/noto-fonts/main/hinted/ttf/NotoSans/' +
             ('NotoSans-Bold.ttf' if bold else 'NotoSans-Regular.ttf'))
        urllib.request.urlretrieve(url,str(noto))
        return ImageFont.truetype(str(noto),size)
    except Exception as e:
        log.warning('Chat screenshot Unicode font unavailable: %s',e)
    return ImageFont.load_default()

def _chat_safe_text(text):
    # Keep Uzbek/Russian/Arabic text. Strip only invisible controls that can break Pillow layout.
    import unicodedata
    out=[]
    for ch in str(text or ''):
        if ch in '\n\t': out.append(ch); continue
        if unicodedata.category(ch) in ('Cc','Cf'): continue
        out.append(ch)
    return ''.join(out)

def _wrap_chat_text(draw,text,font,max_width):
    text=_chat_safe_text(text)
    paragraphs=text.splitlines() or ['']
    lines=[]
    for para in paragraphs:
        words=para.split(' ') if para else ['']
        cur=''
        for w in words:
            trial=(cur+' '+w).strip()
            if not cur or draw.textbbox((0,0),trial,font=font)[2] <= max_width:
                cur=trial
            else:
                lines.append(cur)
                cur=w
        if cur or not words: lines.append(cur)
    return lines or ['']

def render_chat_archive_image(rows,title,offset):
    rows=list(reversed(rows))
    W=1080; pad=54
    font=_chat_font(31); small=_chat_font(23); head=_chat_font(36,True); namefont=_chat_font(25,True); timefont=_chat_font(18)
    probe=Image.new('RGB',(W,100)); d=ImageDraw.Draw(probe)
    blocks=[]; total=150
    for r in rows:
        name=_chat_safe_text(r['display_name'] or ('@'+r['username'] if r['username'] else str(r['user_id'])))
        body=_chat_safe_text(r['body'])
        lines=_wrap_chat_text(d,body,font,W-2*pad-56)[:14]
        # Pillow textbbox-based line height so Cyrillic/Arabic accents are not clipped.
        line_h=max(40, d.textbbox((0,0),'AgÐŽÒš',font=font)[3]+10)
        h=58+len(lines)*line_h+42
        blocks.append((r,name,lines,h,line_h)); total+=h+18
    img=Image.new('RGB',(W,max(total+50,360)),(248,249,250)); d=ImageDraw.Draw(img)
    d.text((pad,30),_chat_safe_text(f'Veritas â€¢ {title}'),font=head,fill=(25,28,33))
    d.text((pad,84),f'Xabarlar {offset+1}â€“{offset+len(rows)}',font=small,fill=(100,105,112))
    y=138
    for r,name,lines,h,line_h in blocks:
        d.rounded_rectangle((pad,y,W-pad,y+h),radius=24,fill=(255,255,255),outline=(220,224,228),width=2)
        d.text((pad+24,y+18),name,font=namefont,fill=(30,80,125))
        yy=y+62
        for line in lines:
            d.text((pad+24,yy),line,font=font,fill=(25,28,33)); yy+=line_h
        tm=datetime.fromtimestamp(int(r['created_at']),timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
        tw=d.textbbox((0,0),tm,font=timefont)[2]
        d.text((W-pad-24-tw,y+h-30),tm,font=timefont,fill=(120,125,132))
        y+=h+18
    out=io.BytesIO(); img.save(out,format='PNG',optimize=True); out.seek(0); return out

async def chatshot_callback(update,ctx):
    q=update.callback_query; u=q.from_user; d=q.data or ''
    # Strict: ONLY the two configured Super Owners. Super Admins/group admins are excluded.
    if u.id not in SUPER_OWNERS:
        return await q.answer('Faqat Super Ega uchun.',show_alert=True)
    cq_defer(q)
    if d=='chatshot:list':
        rows=chat_archive_groups(); kb=[]
        for r in rows[:80]:
            kb.append([InlineKeyboardButton(f"ðŸ’¬ {r['title']} ({r['n']})",callback_data=f"chatshot:g:{r['chat_id']}:0")])
        kb.append([InlineKeyboardButton('â¬…ï¸ Super boshqaruv',callback_data='super')])
        return await q.edit_message_text('ðŸ“¸ CHAT RASMLARI\n\nGuruhni tanlang. Faqat arxiv tizimi ishga tushganidan keyingi xabarlar koâ€˜rinadi.',reply_markup=InlineKeyboardMarkup(kb))
    if d.startswith('chatshot:g:'):
        _,_,cid_s,off_s=d.split(':',3); cid=int(cid_s); off=max(0,int(off_s)); rows=chat_archive_page(cid,off,30)
        if not rows:return await q.answer('Bu oraliqda xabar yoâ€˜q.',show_alert=True)
        gr=one('SELECT title FROM groups WHERE chat_id=?',(cid,)); title=gr['title'] if gr else str(cid)
        img=await asyncio.to_thread(render_chat_archive_image,rows,title,off)
        nav=[]
        if off>=30: nav.append(InlineKeyboardButton('â¬‡ï¸ Yangiroq 30 ta',callback_data=f'chatshot:g:{cid}:{max(0,off-30)}'))
        if len(rows)==30: nav.append(InlineKeyboardButton('â¬†ï¸ Oldingi 30 ta',callback_data=f'chatshot:g:{cid}:{off+30}'))
        kb=[]
        if nav:kb.append(nav)
        kb.append([InlineKeyboardButton('ðŸ“‹ Guruhlar',callback_data='chatshot:list')])
        await q.message.reply_photo(photo=img,caption=f'ðŸ“¸ {title}\nXabarlar: {off+1}â€“{off+len(rows)}',reply_markup=InlineKeyboardMarkup(kb))
        return

def bayram_candidates(chat_id,limit):
    # Bot va kanal nomidan yozilgan xabarlar original passive() tomonidan saqlanmaydi.
    return all_("""SELECT h.user_id,COUNT(*) n,COALESCE(u.first_name,'') name,
                    COALESCE(u.username,'') username
                    FROM group_message_history h LEFT JOIN users u ON u.user_id=h.user_id
                    WHERE h.chat_id=? AND h.created_at>=?
                    GROUP BY h.user_id ORDER BY n DESC,h.user_id ASC LIMIT ?""",
                (chat_id,now()-BAYRAM_WINDOW_SECONDS,limit))

def bayram_markup(cid,kind):
    if kind=='count':
        return InlineKeyboardMarkup([[InlineKeyboardButton(f'ðŸ‘¥ {n} kishi',callback_data=f'bayram:count:{cid}:{n}') for n in (10,25,50)],
                                     [InlineKeyboardButton('âŒ Bekor qilish',callback_data=f'bayram:cancel:{cid}')]])
    if kind=='price':
        return InlineKeyboardMarkup([[InlineKeyboardButton(f'ðŸŽ {n} â­',callback_data=f'bayram:price:{cid}:{n}') for n in (25,50)],
                                     [InlineKeyboardButton('âŒ Bekor qilish',callback_data=f'bayram:cancel:{cid}')]])
    if kind=='confirm':
        return InlineKeyboardMarkup([[InlineKeyboardButton('ðŸŽ TASDIQLAYMAN â€” YUBORISH',callback_data=f'bayram:send:{cid}')],
                                     [InlineKeyboardButton('âŒ Bekor qilish',callback_data=f'bayram:cancel:{cid}')]])
    return None

async def bayram_command(update,ctx):
    msg=update.effective_message; chat=update.effective_chat; u=update.effective_user
    if not chat or chat.type not in ('group','supergroup'):
        return await msg.reply_text('ðŸŽ‰ *bayram faqat guruhda ishlaydi.')
    if not await can_manage(ctx.bot,chat.id,u.id):
        return await msg.reply_text('â›” *bayram faqat guruh adminlari va Veritas boshqaruvchilariga ruxsat.')
    candidates=bayram_candidates(chat.id,50)
    if not candidates:
        return await msg.reply_text('â³ Oxirgi 10 soat ichida qayd etilgan faol aâ€™zolar topilmadi. Bot guruhda ishlagan va xabarlarni koâ€˜rgan boâ€˜lishi kerak.')
    with db() as c:
        cid=c.execute('INSERT INTO bayram_campaigns(chat_id,creator_id,created_at) VALUES(?,?,?)',(chat.id,u.id,now())).lastrowid
    return await msg.reply_text(f'ðŸŽ‰ VERITAS BAYRAM\n\nâ± Oxirgi 10 soat\nðŸ‘¥ Faol aâ€™zolar: {len(candidates)} tagacha\n\nNechta gâ€˜olibni taqdirlaymiz?',reply_markup=bayram_markup(cid,'count'))

async def bayram_callback(update,ctx):
    q=update.callback_query; u=q.from_user; d=q.data or ''
    a=d.split(':')
    if len(a)<3:return await q.answer('Notoâ€˜gâ€˜ri tugma.',show_alert=True)
    action=a[1]
    try:cid=int(a[2])
    except ValueError:return await q.answer('Notoâ€˜gâ€˜ri tugma.',show_alert=True)
    camp=one('SELECT * FROM bayram_campaigns WHERE id=?',(cid,))
    if not camp:return await q.answer('Bayram topilmadi.',show_alert=True)
    if u.id!=camp['creator_id'] and u.id not in SUPER_OWNERS:
        return await q.answer('Bu bayramni faqat tashkilotchi boshqaradi.',show_alert=True)
    if camp['status']!='draft':return await q.answer('Bu bayram allaqachon yakunlangan yoki boshlangan.',show_alert=True)
    if action=='cancel':
        execute("UPDATE bayram_campaigns SET status='cancelled' WHERE id=?",(cid,))
        await q.answer();return await q.edit_message_text('âŒ Bayram bekor qilindi.')
    if action=='count':
        n=int(a[3]) if len(a)>3 and a[3].isdigit() else 0
        if n not in (10,25,50):return await q.answer('Notoâ€˜gâ€˜ri tanlov.',show_alert=True)
        execute('UPDATE bayram_campaigns SET winner_count=? WHERE id=?',(n,cid))
        await q.answer();return await q.edit_message_text(f'ðŸŽ‰ Gâ€˜oliblar: {n} kishi\n\nðŸŽ Gift qiymatini tanlang:',reply_markup=bayram_markup(cid,'price'))
    if action=='price':
        price=int(a[3]) if len(a)>3 and a[3].isdigit() else 0
        if price not in (25,50) or camp['winner_count'] not in (10,25,50):return await q.answer('Avval gâ€˜oliblar sonini tanlang.',show_alert=True)
        try:
            available=await ctx.bot.get_available_gifts()
            gifts=[g for g in available.gifts if int(g.star_count)==price and getattr(g,'remaining_count',None)!=0]
        except Exception as e:
            return await q.answer(f'Gift katalogini olishda xato: {str(e)[:100]}',show_alert=True)
        if not gifts:
            return await q.answer(f'Hozir {price} â­ narxli Gift mavjud emas.',show_alert=True)
        execute('UPDATE bayram_campaigns SET gift_price=?,gift_id=? WHERE id=?',(price,str(gifts[0].id),cid))
        STATE[u.id]={'mode':'bayram_greeting','bayram_id':cid}
        await q.answer()
        await q.edit_message_text('ðŸ’Œ TABRIKNOMA\n\nEndi shaxsiy chatda botga tabriknoma matnini yuboring.\nBotga /start bosib qoâ€˜ying, agar avval yozmagan boâ€˜lsangiz.')
        try:await ctx.bot.send_message(u.id,f'ðŸŽ‰ BAYRAM #{cid}\n\nTabriknoma matnini shu yerga yozing. Matn sovgâ€˜aga biriktiriladi va guruhda ham eâ€™lon qilinadi.')
        except TelegramError:
            await q.message.reply_text('âš ï¸ Botga shaxsiy chatda /start bosing, keyin tabriknoma matnini yuboring.')
        return
    if action!='send':return await q.answer('Notoâ€˜gâ€˜ri tugma.',show_alert=True)
    winners=all_('SELECT * FROM bayram_winners WHERE campaign_id=? ORDER BY msg_count DESC,user_id',(cid,))
    if not winners or not camp['greeting'] or not camp['gift_id']:
        return await q.answer('Tabriknoma yoki gâ€˜oliblar tayyor emas.',show_alert=True)
    try:
        available=await ctx.bot.get_available_gifts()
        valid=next((g for g in available.gifts if str(g.id)==camp['gift_id'] and int(g.star_count)==camp['gift_price'] and getattr(g,'remaining_count',None)!=0),None)
        if valid is None:return await q.answer('Tanlangan Gift endi mavjud emas.',show_alert=True)
        balance=await ctx.bot.get_my_star_balance()
        if int(balance.amount)<len(winners)*int(camp['gift_price']):
            return await q.answer('Bot Stars balansida yetarli mablagâ€˜ yoâ€˜q.',show_alert=True)
    except Exception as e:
        return await q.answer(f'Balans/Gift tekshiruvida xato: {str(e)[:110]}',show_alert=True)
    # Atomik status: ikki marta tasdiqlansa takror gift ketmaydi.
    with db() as c:
        changed=c.execute("UPDATE bayram_campaigns SET status='sending',confirmed_at=? WHERE id=? AND status='draft'",(now(),cid)).rowcount
    if not changed:return await q.answer('Bu bayram allaqachon boshlangan.',show_alert=True)
    await q.answer('Sovgâ€˜alar yuborilmoqda...')
    await q.edit_message_text('ðŸŽ Bayram sovgâ€˜alari yuborilmoqda. Natijalar tez orada shu guruhda chiqadi.')
    success=[];failed=[]
    for w in winners:
        uid=int(w['user_id'])
        try:
            await ctx.bot.send_gift(user_id=uid,gift_id=camp['gift_id'],text=camp['greeting'][:120])
            execute("UPDATE bayram_winners SET status='sent' WHERE campaign_id=? AND user_id=?",(cid,uid))
            success.append(uid)
            # Shaxsiy tabrik xabari: foydalanuvchi botni boshlamagan boâ€˜lsa bloklanishi mumkin.
            try:await ctx.bot.send_message(uid,'ðŸŽ‰ VERITAS BAYRAM\n\n'+camp['greeting'][:3500])
            except TelegramError:pass
        except Exception as e:
            failed.append(uid)
            execute("UPDATE bayram_winners SET status='failed',error=? WHERE campaign_id=? AND user_id=?",(str(e)[:250],cid,uid))
        await asyncio.sleep(0.15)
    execute("UPDATE bayram_campaigns SET status='completed' WHERE id=?",(cid,))
    # Faqat HAQIQATDA yuborilgan sovgâ€˜alar gâ€˜olib sifatida eâ€™lon qilinadi.
    lines=[]
    for i,uid in enumerate(success,1):
        row=one('SELECT first_name,username FROM users WHERE user_id=?',(uid,))
        name=(row['first_name'] or row['username'] or str(uid)) if row else str(uid)
        lines.append(f'{i}. <a href="tg://user?id={uid}">{_bayram_html.escape(name)}</a>')
    header=(f'ðŸŽ‰ VERITAS BAYRAM Gâ€˜OLIBLARI\n\nðŸŽ {camp["gift_price"]} â­ Gift\n'
            f'âœ… Sovgâ€˜a yetkazildi: {len(success)} ta\nâŒ Yuborilmadi: {len(failed)} ta\n\n')
    text=header+'\n'.join(lines)+'\n\nðŸ’Œ TABRIKNOMA\n'+_bayram_html.escape(camp['greeting'])
    # HTML teglarini boâ€˜lmasdan, har bir gâ€˜olibni alohida satr sifatida joylaymiz.
    batches=[]; chunk=header
    for line in lines:
        if len(chunk)+len(line)+2>3400:
            batches.append(chunk);chunk=''
        chunk+=line+'\n'
    if chunk:batches.append(chunk)
    batches.append('ðŸ’Œ TABRIKNOMA\n'+_bayram_html.escape(camp['greeting']))
    for part in batches:
        await ctx.bot.send_message(camp['chat_id'],part,parse_mode='HTML')
    if failed:
        await ctx.bot.send_message(camp['chat_id'],f'âš ï¸ {len(failed)} kishiga Gift yuborilmadi. Sarflanmagan Stars bot balansida qoladi. Tafsilotlar Railway logida.')
    return

async def bayram_private_input(update,ctx):
    msg=update.effective_message;u=update.effective_user
    if not msg or not u or msg.chat.type!='private':return
    st=STATE.get(u.id) or {}
    if st.get('mode')!='bayram_greeting':return
    ctx.user_data['bayram_consumed_message_id']=msg.message_id
    greeting=(msg.text or '').strip()
    if not greeting or len(greeting)>120:
        return await msg.reply_text('ðŸ’Œ Gift ichidagi tabriknoma 120 belgidan oshmasin. Iltimos, qisqaroq matn yozing.')
    cid=st['bayram_id'];camp=one('SELECT * FROM bayram_campaigns WHERE id=? AND creator_id=? AND status="draft"',(cid,u.id))
    if not camp:
        STATE.pop(u.id,None);return await msg.reply_text('Bu bayram sessiyasi tugagan.')
    winners=bayram_candidates(camp['chat_id'],camp['winner_count'])
    if not winners:
        return await msg.reply_text('Oxirgi 10 soatda faol aâ€™zolar topilmadi.')
    with db() as c:
        c.execute('DELETE FROM bayram_winners WHERE campaign_id=?',(cid,))
        c.executemany('INSERT INTO bayram_winners(campaign_id,user_id,msg_count) VALUES(?,?,?)',[(cid,r['user_id'],r['n']) for r in winners])
        c.execute('UPDATE bayram_campaigns SET greeting=? WHERE id=?',(greeting,cid))
    STATE.pop(u.id,None)
    count=len(winners);total=count*camp['gift_price']
    await msg.reply_text(f'ðŸŽ‰ BAYRAM TASDIQLASH\n\nðŸ‘¥ Gâ€˜oliblar: {count} kishi\nâ± Oxirgi 10 soat\nðŸŽ Har biriga: {camp["gift_price"]} â­ Gift\nðŸ’° Jami: {total} â­\n\nðŸ’Œ {greeting}\n\nâš ï¸ TASDIQLASH bosilsa botning Stars balansidan haqiqiy Giftlar yuboriladi.',reply_markup=bayram_markup(cid,'confirm'))


# =========================================================
# V9 BAYRAM â€” AI MAZGILA (qitmir hazil rejimi) â€” STABLE
# =========================================================
MAZGILA_CACHE = {}
MAZGILA_SEMAPHORE = asyncio.Semaphore(2)
MAZGILA_COOLDOWN = 45
MAZGILA_CHANCE = 0.75

def mazgila_init_db():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS mazgila_targets(
          chat_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
          username TEXT DEFAULT '', first_name TEXT DEFAULT '',
          enabled INTEGER DEFAULT 1, added_by INTEGER NOT NULL, created_at INTEGER NOT NULL,
          last_reply_at INTEGER DEFAULT 0,
          PRIMARY KEY(chat_id,user_id));
        CREATE INDEX IF NOT EXISTS idx_mazgila_chat_enabled ON mazgila_targets(chat_id,enabled);
        """)
        cols={r[1] for r in c.execute("PRAGMA table_info(mazgila_targets)").fetchall()}
        if "last_reply_at" not in cols:
            c.execute("ALTER TABLE mazgila_targets ADD COLUMN last_reply_at INTEGER DEFAULT 0")

def mazgila_row(chat_id,user_id):
    return one("SELECT * FROM mazgila_targets WHERE chat_id=? AND user_id=? AND enabled=1",(chat_id,user_id))

def mazgila_label(target):
    username=(getattr(target,'username','') or '').strip()
    first=(getattr(target,'first_name','') or '').strip()
    return '@'+username if username else (first or f'ID {getattr(target,"id",0)}')

async def mazgila_target_in_chat(bot,chat_id,user_id):
    try:
        m=await bot.get_chat_member(chat_id,user_id)
        return m.status not in (ChatMemberStatus.LEFT,ChatMemberStatus.BANNED)
    except TelegramError:
        return False

async def mazgila_command(update,ctx,args):
    msg=update.effective_message; chat=update.effective_chat; actor=update.effective_user
    if not msg or not chat or chat.type not in ('group','supergroup'): return
    if not actor or not await can_manage(ctx.bot,chat.id,actor.id):
        return await msg.reply_text('â›” *mazgila faqat guruh boshqaruvchilari uchun.')

    raw=' '.join(args).strip()
    low=raw.lower()
    if low in ('list','royxat','roâ€˜yxat'):
        rows=all_("SELECT user_id,username,first_name FROM mazgila_targets WHERE chat_id=? AND enabled=1 ORDER BY created_at DESC LIMIT 50",(chat.id,))
        if not rows:
            return await msg.reply_text('ðŸ˜‡ Bu guruhda Mazgila rejimi hech kimga yoqilmagan.')
        body=[]
        for i,r in enumerate(rows,1):
            label='@'+r['username'] if r['username'] else (r['first_name'] or f"ID {r['user_id']}")
            body.append(f'{i}. {label}')
        return await msg.reply_text('ðŸ˜ˆ MAZGILA ROâ€˜YXATI\n\n'+'\n'.join(body))

    target=msg.reply_to_message.from_user if msg.reply_to_message and msg.reply_to_message.from_user else None
    off=False
    if low.startswith(('off ','ochir ','oâ€˜chir ','stop ')):
        off=True; raw=raw.split(maxsplit=1)[1] if len(raw.split(maxsplit=1))>1 else ''
    elif low in ('off','ochir','oâ€˜chir','stop'):
        off=True

    if not target and raw:
        uname=raw.split()[0].lstrip('@')
        r=one("SELECT user_id,username,first_name FROM users WHERE lower(username)=lower(?)",(uname,))
        if r:
            class T: pass
            target=T(); target.id=int(r['user_id']); target.username=r['username']; target.first_name=r['first_name']; target.is_bot=False

    if not target:
        return await msg.reply_text('ðŸ˜ˆ Xabariga reply qilib *mazgila yozing.\nYoki shu guruhdagi user: *mazgila @username\nðŸ“‹ Roâ€˜yxat: *mazgila list')
    if getattr(target,'is_bot',False) or target.id==ctx.bot.id:
        return await msg.reply_text('ðŸ¤– Botni mazgilamaymiz ðŸ˜„')
    if not await mazgila_target_in_chat(ctx.bot,chat.id,target.id):
        return await msg.reply_text('âš ï¸ Bu foydalanuvchi hozir shu guruh aâ€™zosi emas yoki bot uni tekshira olmadi. Xabariga reply qilib urinib koâ€˜ring.')
    # Faqat Veritasning 2 ta Super Egasi himoyalangan. Guruh adminlari va Super Adminlar ham nishon boâ€˜lishi mumkin.
    if target.id in SUPER_OWNERS:
        return await msg.reply_text('ðŸ‘‘ Veritas Super Egasini Mazgila nishoniga qoâ€˜yib boâ€˜lmaydi.')

    label=mazgila_label(target)
    if off:
        execute("DELETE FROM mazgila_targets WHERE chat_id=? AND user_id=?",(chat.id,target.id))
        MAZGILA_CACHE.pop((chat.id,target.id),None)
        return await msg.reply_text(f'ðŸ˜‡ Mazgilash rejimi oâ€˜chirildi: {label}')

    execute("""INSERT INTO mazgila_targets(chat_id,user_id,username,first_name,enabled,added_by,created_at,last_reply_at)
               VALUES(?,?,?,?,1,?,?,0)
               ON CONFLICT(chat_id,user_id) DO UPDATE SET username=excluded.username,first_name=excluded.first_name,
               enabled=1,added_by=excluded.added_by,created_at=excluded.created_at""",
            (chat.id,target.id,getattr(target,'username','') or '',getattr(target,'first_name','') or '',actor.id,now()))
    return await msg.reply_text(f'ðŸ˜ˆ AI mazgilash rejimi yoqildi: {label}\nQitmir Veritas ishga tushdi ðŸ˜')

async def mazgila_maybe_reply(update,ctx):
    msg=update.effective_message; chat=update.effective_chat; u=update.effective_user
    if not msg or not chat or not u or u.is_bot or chat.type not in ('group','supergroup'): return False
    row=mazgila_row(chat.id,u.id)
    if not row:return False
    text=(msg.text or msg.caption or '').strip()
    if not text or text.startswith('*'): return False

    # Nishonning aniq opt-out soâ€˜rovi boâ€˜lsa rejim oâ€˜chadi. Bot uzr soâ€˜ramaydi, faqat toâ€˜xtaydi.
    stop_norm=re.sub(r"[^a-zA-ZÊ»â€™' ]+", " ", text.lower()).strip()
    stop_phrases=("mazgila toxta","mazgila toâ€˜xta","mazgila to'xta","mazgilashni toxta",
                  "mazgilashni toâ€˜xta","mazgilashni to'xta","bezovta qilma","meni mazgilama")
    if any(p in stop_norm for p in stop_phrases):
        execute("DELETE FROM mazgila_targets WHERE chat_id=? AND user_id=?",(chat.id,u.id))
        MAZGILA_CACHE.pop((chat.id,u.id),None)
        await msg.reply_text('ðŸ˜ˆ Mazgila toâ€˜xtadi.')
        return True

    # Faqat Veritasning 2 ta Super Egasi himoyalangan. Admin/Super Admin boâ€˜lish Mazgilani toâ€˜xtatmaydi.
    if u.id in SUPER_OWNERS:
        execute("DELETE FROM mazgila_targets WHERE chat_id=? AND user_id=?",(chat.id,u.id))
        MAZGILA_CACHE.pop((chat.id,u.id),None)
        return False

    key=(chat.id,u.id); ts=now()
    last=max(int(row['last_reply_at'] or 0), int(MAZGILA_CACHE.get(key,0) or 0))
    if ts-last < MAZGILA_COOLDOWN or random.random() > MAZGILA_CHANCE:return False

    # AI chaqiruvi boshlanishidan oldin vaqtni DB+RAMga yozamiz: parallel xabarlar dublikat AI chaqirmaydi.
    MAZGILA_CACHE[key]=ts
    execute("UPDATE mazgila_targets SET last_reply_at=? WHERE chat_id=? AND user_id=?",(ts,chat.id,u.id))
    name=u.first_name or u.username or 'doâ€˜stim'
    prompt=("Sen Veritas guruh botisan. Mazgila â€” doâ€˜stona qitmir hazil rejimi.\n"
            f"{name} shunday yozdi: {text[:1200]}\n"
            "Unga Oâ€˜ZBEKCHA 1-2 gaplik juda topqir, qitmir, tishli lekin hazil doirasidagi javob yoz. "
            "Har safar bir xil qolipni takrorlama; uning aynan yozgan gapidan ilib ket. "
            "Haqorat, kamsitish, tahdid, jinsiy mazmun, nafrat, himoyalangan belgilarga tegish, "
            "shaxsiy sir yoki ogâ€˜ir/nozik mavzular boâ€˜lmasin. Qoâ€˜pol soâ€˜kinma. "
            "Oddiy jahllanish yoki eâ€™tirozga javoban uzr soâ€˜rama; qitmir ohangni saqla. "
            "Faqat foydalanuvchi Mazgilani aniq toâ€˜xtatishni soâ€˜rasa tizim alohida oâ€˜chiradi. "
            "Faqat javobni qaytar.")
    try:
        if OPENAI_API_KEY:
            async with MAZGILA_SEMAPHORE:
                ans=await asyncio.to_thread(_openai_response_sync,prompt)
        else:
            ans=random.choice([
                f'{name}, bu fikrni yozguncha Veritas ham bir qarib oldi ðŸ˜',
                f'{name}, gap jiddiy boshlandi-yu, oxiri yana sizga oâ€˜xshab ketdi ðŸ˜„',
                f'{name}, Veritas buni oâ€˜qib â€œdavomi ham bormi?â€ deb qoldi ðŸ˜'])
        if ans:
            await msg.reply_text(ans[:900])
            return True
    except Exception:
        log.exception('mazgila AI reply failed')
    return False

async def group_poster_command(update,ctx,args):
    msg=update.effective_message; chat=update.effective_chat; u=update.effective_user
    if not msg or not chat or not u or chat.type not in ("group","supergroup"):
        return False
    if not await can_manage(ctx.bot,chat.id,u.id):
        await msg.reply_text("âŒ Poster tayyorlash faqat shu guruh adminlari uchun.")
        return True
    ensure_group(chat); ensure_user(u)
    source=" ".join(args).strip()
    if not source:
        await msg.reply_text("ðŸ–¼ Poster uchun matnni shu koâ€˜rinishda yozing:\n*poster E'lon matni")
        return True
    wait=await msg.reply_text("ðŸ¤– AI post matnini tayyorlamoqda...")
    try:
        data=await ai_news_prepare(source)
    except Exception as exc:
        log.exception("group poster prepare failed chat=%s",chat.id)
        await wait.edit_text("âš ï¸ AI postni tayyorlay olmadi: "+str(exc)[:300])
        return True
    with db() as c:
        nid=c.execute("INSERT INTO ai_news_posts(creator_id,source_text,uz_text,ru_text,en_text,status,created_at,target_chat_id,scope) VALUES(?,?,?,?,?,'draft',?,?,?)",
                      (u.id,source,data['uz'],'','',now(),chat.id,'group')).lastrowid
    await wait.edit_text(f"ðŸ“¢ POST #{nid} â€” PREVIEW\n\n{data['uz'][:3300]}",reply_markup=ai_news_group_preview_markup(nid))
    return True

_bayram_old_star_router=star_text_router
async def star_text_router(update,ctx):
    msg=update.effective_message
    raw=(msg.text or '').strip() if msg else ''; low=raw.lower()
    if low in ('*til','*lang','*language'): return await group_lang_command(update,ctx)
    if low=='*bayram': return await bayram_command(update,ctx)
    if low=='*mazgila' or low.startswith('*mazgila '): return await mazgila_command(update,ctx,raw.split()[1:])
    if low=='*poster' or low.startswith('*poster '): return await group_poster_command(update,ctx,raw.split()[1:])
    return await _bayram_old_star_router(update,ctx)

_bayram_old_callback=callback
async def callback(update,ctx):
    data=(update.callback_query.data or '')
    if data=='lang:menu':
        q=update.callback_query;await q.answer();return await q.edit_message_text(L(q.from_user.id,'ðŸŒ Tilni tanlang:','ðŸŒ Ð’Ñ‹Ð±ÐµÑ€Ð¸Ñ‚Ðµ ÑÐ·Ñ‹Ðº:','ðŸŒ Choose language:'),reply_markup=lang_markup())
    if data.startswith('lang:set:'):
        q=update.callback_query;lang=data.rsplit(':',1)[1]
        if lang in LANG_NAMES:
            ensure_user(q.from_user);set_user_lang(q.from_user.id,lang);await q.answer('âœ…');return await q.edit_message_text({'uz':'âœ… Til saqlandi.','ru':'âœ… Ð¯Ð·Ñ‹Ðº ÑÐ¾Ñ…Ñ€Ð°Ð½Ñ‘Ð½.','en':'âœ… Language saved.'}[lang],reply_markup=main_menu_markup(q.from_user.id))
    # V9.1 NEWS: barcha news:* callbacklar bitta asosiy router orqali ishlaydi.
    # Alohida handler bilan to'qnashuv bo'lmasligi uchun shu yerdan bevosita yuboramiz.
    if data.startswith('poster:'):
        return
    # news:* has its own high-priority CallbackQueryHandler (group=-100).
    # Do not process it again in the generic callback router.
    if data.startswith('news:'):
        return
    if data.startswith('glang:'):
        return
    if data.startswith('chatshot:'):
        return await chatshot_callback(update,ctx)
    if data.startswith('bayram:'):
        return await bayram_callback(update,ctx)
    return await _bayram_old_callback(update,ctx)

async def ai_news_menu_direct(update, ctx):
    """Open the Super Owner news sender without passing through broad callback routers."""
    q=update.callback_query
    if not q or (q.data or "")!="news:menu":
        return
    u=q.from_user
    try:
        await q.answer()
    except Exception:
        pass
    if not u or u.id not in SUPER_OWNERS:
        return
    STATE.pop(u.id,None)
    return await _news_edit(q,"ðŸ“¢ AI YANGILIK MARKAZI",reply_markup=ai_news_super_markup())

# =========================================================
# V9.1.1 â€” GURUHLARGA ISHONCHLI YUBORISH
# =========================================================
NEWS_SENDING_NOW=set()   # shu jarayonda hozir yuborilayotgan postlar

def _news_migrate_group(old_id,new_id):
    """Guruh supergroupga aylanganda chat_id o'zgaradi â€” bazada yangilaymiz."""
    try:
        with db() as c:
            if c.execute("SELECT 1 FROM groups WHERE chat_id=?",(new_id,)).fetchone():
                c.execute("DELETE FROM groups WHERE chat_id=?",(old_id,))
            else:
                c.execute("UPDATE groups SET chat_id=? WHERE chat_id=?",(new_id,old_id))
        log.warning("NEWS group migrated %s -> %s",old_id,new_id)
    except Exception:
        log.exception("group migrate update failed %s -> %s",old_id,new_id)

async def _news_call(fn,cid,*args,**kwargs):
    """Bitta Telegram chaqiruvi: flood-limit (RetryAfter) va migratsiyani hisobga oladi.
    Qaytaradi: haqiqiy chat_id (migratsiyadan keyin yangisi bo'lishi mumkin)."""
    for attempt in range(4):
        try:
            await fn(chat_id=cid,*args,**kwargs)
            return cid
        except RetryAfter as exc:
            wait=float(getattr(exc,"retry_after",3) or 3)
            if hasattr(wait,"total_seconds"):wait=wait.total_seconds()
            log.warning("NEWS flood limit chat=%s, %ss kutiladi",cid,wait)
            await asyncio.sleep(min(float(wait),60)+0.5)
        except ChatMigrated as exc:
            new_id=int(exc.new_chat_id)
            _news_migrate_group(cid,new_id)
            cid=new_id
    raise RuntimeError("Telegram flood limit: qayta urinishlar tugadi")

async def ai_news_send_direct(update, ctx):
    """Dedicated, retry-safe news broadcaster for all registered Telegram groups."""
    q = update.callback_query
    if not q:
        return
    u = q.from_user
    d = q.data or ""
    m = re.fullmatch(r"news:send:(\d+)", d)
    if not m:
        return

    # Answer Telegram immediately, before any DB/network work.
    try:
        await q.answer("ðŸ“¤ Guruhlarga yuborish boshlandi")
    except Exception:
        log.exception("NEWS_SEND answerCallbackQuery failed")

    if not u or u.id not in SUPER_OWNERS:
        return

    nid = int(m.group(1))
    log.warning("NEWS_SEND_DIRECT START post=%s uid=%s", nid, u.id)

    try:
        post = one("SELECT * FROM ai_news_posts WHERE id=?", (nid,))
    except Exception as exc:
        log.exception("NEWS_SEND_DIRECT post DB error post=%s", nid)
        return await ctx.bot.send_message(u.id, f"âš ï¸ Post bazadan olinmadi: {str(exc)[:300]}", _skip_i18n=True)
    if not post:
        return await ctx.bot.send_message(u.id, "âš ï¸ Yangilik topilmadi.", _skip_i18n=True)

    # Bot qayta ishga tushgan bo'lsa, 'sending' holatida qotib qolgan postni tiklaymiz.
    if post["status"] == "sending" and nid not in NEWS_SENDING_NOW:
        execute("UPDATE ai_news_posts SET status='draft' WHERE id=? AND status='sending'", (nid,))
        post = one("SELECT * FROM ai_news_posts WHERE id=?", (nid,))
    # Reject duplicate presses; a post can be sent globally only once.
    if post["status"] != "draft":
        return await ctx.bot.send_message(u.id, "âš ï¸ Bu post yuborilgan yoki yuborilmoqda. Takroriy joâ€˜natish toâ€˜xtatildi.", _skip_i18n=True)

    # One-language mode: exactly the prepared Uzbek/source text is sent to every group.
    text = (post["uz_text"] or post["source_text"] or "").strip()
    media_type = (post["media_type"] or "").strip()
    media_file_id = (post["media_file_id"] or "").strip()

    try:
        groups = all_("SELECT chat_id,title FROM groups ORDER BY chat_id")
    except Exception as exc:
        log.exception("NEWS_SEND_DIRECT groups DB error post=%s", nid)
        return await ctx.bot.send_message(u.id, f"âš ï¸ Guruhlar bazadan olinmadi: {str(exc)[:300]}", _skip_i18n=True)

    # Telegram photo is stored on acceptance; ensure it is included in the broadcast.
    poster = one("SELECT file_id FROM ai_news_posters WHERE post_id=?", (nid,))
    if poster and poster["file_id"] and not media_file_id:
        media_type, media_file_id = "photo", poster["file_id"]

    log.warning("NEWS_SEND_DIRECT GROUPS_FOUND post=%s count=%s", nid, len(groups))
    if not groups:
        try:
            execute("UPDATE ai_news_posts SET status='draft' WHERE id=?", (nid,))
        except Exception:
            pass
        return await ctx.bot.send_message(
            u.id,
            "âš ï¸ Bazada yuborish uchun guruh topilmadi. Bot avval guruhda ishlagan boâ€˜lishi kerak.",
            reply_markup=ai_news_ready_markup(nid),
            _skip_i18n=True,
        )

    try:
        with db() as c:
            claimed = c.execute("UPDATE ai_news_posts SET status='sending' WHERE id=? AND status='draft'", (nid,)).rowcount
        if not claimed:
            return await ctx.bot.send_message(u.id, "âš ï¸ Bu post allaqachon yuborilmoqda.", _skip_i18n=True)
    except Exception:
        log.exception("NEWS_SEND_DIRECT could not mark sending post=%s", nid)
    NEWS_SENDING_NOW.add(nid)
    try:
        return await _ai_news_send_direct_body(ctx, q, u, nid, text, media_type, media_file_id, groups)
    finally:
        NEWS_SENDING_NOW.discard(nid)

async def _ai_news_send_direct_body(ctx, q, u, nid, text, media_type, media_file_id, groups):

    try:
        await _news_edit(q, f"ðŸ“¤ {len(groups)} TA GURUHGA YUBORILMOQDA...")
    except Exception:
        log.exception("NEWS_SEND_DIRECT preview edit failed post=%s", nid)

    async def send_group(row):
        cid = int(row["chat_id"])
        title = row["title"] or str(cid)
        try:
            log.warning("NEWS_SEND_DIRECT SENDING post=%s chat=%s title=%s", nid, cid, title)
            if media_type == "photo" and media_file_id:
                cid = await _news_call(ctx.bot.send_photo, cid, photo=media_file_id, _skip_i18n=True)
            elif media_type == "video" and media_file_id:
                cid = await _news_call(ctx.bot.send_video, cid, video=media_file_id, _skip_i18n=True)
            elif media_type == "document" and media_file_id:
                cid = await _news_call(ctx.bot.send_document, cid, document=media_file_id, _skip_i18n=True)
            if text:
                for pos in range(0, len(text), 4000):
                    cid = await _news_call(ctx.bot.send_message, cid, text=text[pos:pos+4000], _skip_i18n=True)
            log.warning("NEWS_SEND_DIRECT OK post=%s chat=%s", nid, cid)
            return True, cid, ""
        except Exception as exc:
            log.exception("NEWS_SEND_DIRECT FAIL post=%s chat=%s: %s", nid, cid, exc)
            return False, cid, str(exc)[:180]

    ok = 0
    fail = 0
    failures = []
    # Small batches are deliberately used to avoid Telegram flood limits.
    for pos in range(0, len(groups), 8):
        results = await asyncio.gather(*(send_group(r) for r in groups[pos:pos+8]))
        for success, cid, err in results:
            if success:
                ok += 1
            else:
                fail += 1
                failures.append(f"{cid}: {err}")
        if pos + 8 < len(groups):
            await asyncio.sleep(0.8)

    final_status = "sent" if ok > 0 else "draft"
    try:
        execute(
            "UPDATE ai_news_posts SET status=?,sent_ok=?,sent_fail=?,sent_at=? WHERE id=?",
            (final_status, ok, fail, now() if ok else 0, nid),
        )
    except Exception:
        log.exception("NEWS_SEND_DIRECT final DB update failed post=%s", nid)

    log.warning("NEWS_SEND_DIRECT DONE post=%s ok=%s fail=%s", nid, ok, fail)
    result = f"âœ… YUBORISH TUGADI\n\nðŸ˜ Yetkazildi: {ok}\nâŒ Yetkazilmadi: {fail}"
    if failures:
        result += "\n\nâš ï¸ Birinchi xatolar:\n" + "\n".join(failures[:5])
    if ok == 0:
        result += "\n\nPost draft holatida qoldi â€” qayta yuborish mumkin."
    await ctx.bot.send_message(
        u.id,
        result,
        reply_markup=ai_news_ready_markup(nid) if ok == 0 else None,
        _skip_i18n=True,
    )

async def ai_news_send_group_direct(update,ctx):
    q=update.callback_query
    if not q:return
    m=re.fullmatch(r"news:sendgroup:(\d+)",q.data or "")
    if not m:return
    u=q.from_user; nid=int(m.group(1))
    post=one("SELECT * FROM ai_news_posts WHERE id=?",(nid,))
    if not post:return await q.answer("Post topilmadi.",show_alert=True)
    cid=int(post["target_chat_id"] or 0)
    if not cid or post["creator_id"]!=u.id or not await can_manage(ctx.bot,cid,u.id):
        return await q.answer("Bu guruhga yuborish huquqingiz yoâ€˜q.",show_alert=True)
    if post["status"] not in ("draft","sending"):
        return await q.answer("Bu post allaqachon yuborilgan yoki bekor qilingan.",show_alert=True)
    await q.answer("ðŸ“¤ Guruhga yuborilmoqda")
    text=(post["uz_text"] or post["source_text"] or "").strip()
    ok=await _news_send_one(ctx.bot,cid,text,post["media_type"],post["media_file_id"])
    if ok:
        execute("UPDATE ai_news_posts SET status='sent',sent_ok=1,sent_fail=0,sent_at=? WHERE id=?",(now(),nid))
        return await ctx.bot.send_message(q.message.chat_id,"âœ… Post shu guruhga yuborildi.",_skip_i18n=True)
    execute("UPDATE ai_news_posts SET status='draft',sent_fail=1 WHERE id=?",(nid,))
    return await ctx.bot.send_message(q.message.chat_id,"âš ï¸ Yuborilmadi. Botning guruhda xabar yuborish huquqini tekshiring.",reply_markup=ai_news_group_ready_markup(nid),_skip_i18n=True)

async def bot_membership_update(update,ctx):
    """Bot guruhga qo'shilganda/admin qilinganda guruhni darhol bazaga yozadi.
    Privacy mode yoqilgan botlar oddiy xabarlarni ko'rmaydi, shuning uchun
    avval guruhlar faqat buyruq yozilganda ro'yxatga tushardi va yangilik ularga yetmasdi."""
    cmu=update.my_chat_member
    if not cmu:return
    chat=cmu.chat
    if not chat or chat.type not in ("group","supergroup"):return
    status=cmu.new_chat_member.status
    if status in (ChatMemberStatus.MEMBER,ChatMemberStatus.ADMINISTRATOR,ChatMemberStatus.RESTRICTED):
        try:ensure_group(chat);log.warning("GROUP registered chat=%s title=%s",chat.id,chat.title)
        except Exception:log.exception("group register failed")

async def group_migration_update(update,ctx):
    msg=update.effective_message
    if msg and msg.migrate_to_chat_id:
        _news_migrate_group(msg.chat.id,int(msg.migrate_to_chat_id))

# =========================================================
# V9.1.1 â€” GLOBAL NAVIGATSIYA (eng yuqori ustuvorlik)
# "ðŸ›¡ Veritas" va "ðŸŽ“ Oâ€˜quv â€¢ Talaba" tugmalari boshqa hech qaysi handlerga
# (AI javob, yangilik kiritish, bayram, kutubxona...) o'tmaydi.
# =========================================================
def _nav_norm(t):
    t=(t or "").replace("\ufe0f","").replace("\u200d","").replace("â€™","'").replace("â€˜","'").replace("`","'")
    return re.sub(r"\s+"," ",t).strip().lower()

async def _nav_send(ctx,chat_id,text,markup):
    try:
        return await ctx.bot.send_message(chat_id,text,reply_markup=markup)
    except Exception:
        log.exception("global nav send failed, retrying without i18n")
        return await ctx.bot.send_message(chat_id,text,reply_markup=markup,_skip_i18n=True)

async def global_nav_input(update,ctx):
    msg=update.effective_message;u=update.effective_user
    if not msg or not u or not msg.chat or msg.chat.type!="private" or not msg.text:return
    t=_nav_norm(msg.text)
    is_veritas = t=="ðŸ›¡ veritas" or (t.startswith("ðŸ›¡") and "veritas" in t and len(t)<=24)
    is_v9 = t=="ðŸŽ“ o'quv â€¢ talaba" or (t.startswith("ðŸŽ“") and "â€¢" in t and len(t)<=32)
    if not (is_veritas or is_v9):return
    ctx.user_data["v9_consumed_message_id"]=msg.message_id
    STATE.pop(u.id,None)
    try:ensure_user(u)
    except Exception:log.exception("global nav ensure_user failed")
    try:
        if is_veritas:
            await _nav_send(ctx,msg.chat.id,"ðŸ›¡ VERITAS\n\nAsosiy boâ€˜lim:",main_menu_markup(u.id))
        else:
            await _nav_send(ctx,msg.chat.id,"ðŸŽ“ Oâ€˜QUV â€¢ TALABA\n\nTaâ€™lim turini tanlang:",v9_entry_markup())
            await _nav_send(ctx,msg.chat.id,"Asosiy panel:",veritas_global_keyboard())
    except Exception:
        log.exception("global nav failed")
    # Bu xabar to'liq qayta ishlandi â€” keyingi guruhlar (AI va boshqalar) ishlamasin.
    raise ApplicationHandlerStop

def main (  ) :
    if not TOKEN: raise RuntimeError ( "BOT_TOKEN kiritilmagan.")
    init_db ( )
    rose_full_init_db()
    v9_init_db()
    bayram_init_db()
    mazgila_init_db()
    ai_news_init_db()
    poster_init_db()
    i18n_init_db()
    app=Application.builder().bot(VeritasI18nBot(token=TOKEN)).build()
    app.add_handler ( CommandHandler ( "start",v9_start_selector ) )
    app.add_handler ( CommandHandler ( "help",cmd_help ) )
    app.add_handler ( CommandHandler ( "id",cmd_id ) )
    app.add_handler ( CommandHandler ( "super",cmd_super ) )
    app.add_handler ( PreCheckoutQueryHandler ( precheckout ) )
    app.add_handler ( MessageHandler ( filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND,global_nav_input ) ,group=-1000)
    app.add_handler ( ChatMemberHandler ( bot_membership_update, ChatMemberHandler.MY_CHAT_MEMBER ) ,group=-900)
    app.add_handler ( MessageHandler ( filters.StatusUpdate.MIGRATE,group_migration_update ) ,group=-900)
    app.add_handler ( MessageHandler ( filters.SUCCESSFUL_PAYMENT,paid ) )
    # NEWS callbacks get a dedicated highest-priority route.
    # This prevents the broad callback router from swallowing the send button.
    # Exact send callback has its own route and cannot be swallowed by any broad callback handler.
    app.add_handler(CallbackQueryHandler(ai_news_menu_direct, pattern=r"^news:menu$"), group=-300)
    app.add_handler(CallbackQueryHandler(ai_news_send_group_direct, pattern=r"^news:sendgroup:\d+$"), group=-250)
    app.add_handler(CallbackQueryHandler(poster_callback, pattern=r"^poster:"), group=-240)
    app.add_handler(CallbackQueryHandler(ai_news_send_direct, pattern=r"^news:send:\d+$"), group=-200)
    # Other news callbacks use the normal news controller; send is deliberately excluded.
    app.add_handler(CallbackQueryHandler(ai_news_callback, pattern=r"^news:(?!send:|sendgroup:|menu$)"), group=-100)
    app.add_handler(CallbackQueryHandler(group_lang_callback, pattern=r"^glang:"), group=-10)
    app.add_handler(CallbackQueryHandler(callback), group=0)
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & ~filters.COMMAND & ~filters.SUCCESSFUL_PAYMENT,ai_news_private_input),group=-7)
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND,bayram_private_input),group=-5)
    app.add_handler ( MessageHandler ( filters.StatusUpdate.NEW_CHAT_MEMBERS,new_members ) )
    app.add_handler ( MessageHandler ( filters.StatusUpdate.LEFT_CHAT_MEMBER,left_member ) )
    app.add_handler ( MessageHandler ( filters.TEXT & filters.Regex ( r"^\*" ) ,star_text_router ) ,group=0)
    # Owner inbox/reply state is checked first; other private workflows remain untouched.
    app.add_handler ( MessageHandler ( filters.ChatType.PRIVATE & ~filters.COMMAND & ~filters.SUCCESSFUL_PAYMENT,v9_private_input ) ,group=-3)
    app.add_handler ( MessageHandler ( filters.ChatType.PRIVATE & ~filters.COMMAND & ~filters.SUCCESSFUL_PAYMENT,owner_message_state_handler ) ,group=-1)
    # Private workflow first. It handles library/hadith upload states.
    app.add_handler ( MessageHandler ( filters.ChatType.PRIVATE & ~filters.COMMAND & ~filters.SUCCESSFUL_PAYMENT,library_private_input ) ,group=1)
    # Vision must be in a DIFFERENT handler group. In the old build it shared group=1
    # with library_private_input, so python-telegram-bot never reached it.
    app.add_handler ( MessageHandler ( filters.ChatType.PRIVATE & (filters.PHOTO | filters.Document.IMAGE),private_ai_media_reply ) ,group=2)
    # Group passive processing is separate.
    app.add_handler ( MessageHandler ( filters.ALL & ~filters.StatusUpdate.ALL & ~filters.SUCCESSFUL_PAYMENT,passive ) ,group=3)
    # Plain private text AI comes last.
    app.add_handler ( MessageHandler ( filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND & ~filters.Regex ( r"^\*" ) ,private_ai_reply ) ,group=4)
    if app.job_queue:
        app.job_queue.run_repeating ( giveaway_job,60,first=10)
        app.job_queue.run_repeating ( rose_cleanup_job,30,first=15)
    app.add_error_handler ( error_handler)
    log.info ( "VERITAS v9.1 FINAL GROUP POSTER starting")
    app.run_polling ( allowed_updates=Update.ALL_TYPES)

if __name__=="__main__":
    main ( )
