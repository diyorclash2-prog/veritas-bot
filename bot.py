# VERITAS BOT v8 — Vasatiya Library build
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
from telegram.error import TelegramError
from telegram.ext import (
    Application, ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler,
    PreCheckoutQueryHandler, filters
)

TOKEN = os.getenv ( "BOT_TOKEN", "" ) .strip ( )
DB_PATH = os.getenv ( "DB_PATH", "veritas_v7.sqlite3")
SUPER_OWNERS = {int ( x) for x in os.getenv ( "SUPER_OWNER_IDS","" ) .split ( ",") if x.strip (  ) .isdigit (  ) }
VERSION = "8.0"
OPENAI_API_KEY = os.getenv ( "OPENAI_API_KEY", "" ) .strip ( )
OPENAI_MODEL = os.getenv ( "OPENAI_MODEL", "gpt-5.6-luna" ) .strip ( ) or "gpt-5.6-luna"
REBUS_IMAGE_MODEL = os.getenv ( "REBUS_IMAGE_MODEL", "gpt-image-2" ) .strip ( ) or "gpt-image-2"
TG_API_ID = int ( os.getenv ( "TG_API_ID", "0") or 0)
TG_API_HASH = os.getenv ( "TG_API_HASH", "" ) .strip ( )
TG_SESSION = os.getenv ( "TG_SESSION", "" ) .strip ( )
TG_STORAGE_CHAT_ID = int ( os.getenv ( "TG_STORAGE_CHAT_ID", "0") or 0)
DEMO_DAYS = 7
WEEK_PRICE = 100
PREMIUM = {3:1000, 6:1500, 12:2500}
TOPUPS = (25,50,100,250,500,1000,2500)
AI_PRIVATE_PRICE = 10
AI_PRIVATE_DAYS = 30
AI_GROUP_PLANS = {30:100}
AI_RATE_CACHE = {}
TRANSLATION_SEMAPHORE = asyncio.Semaphore ( 2)
FLOOD_CACHE = {}
STATE = {}
URL_RE = re.compile ( r" ( https?://|www\.|t\.me/|telegram\.me/|@\w+ ) ", re.I)

logging.basicConfig ( level=logging.INFO)
log = logging.getLogger ( "veritas-v8")

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
      created_at INTEGER NOT NULL,PRIMARY KEY ( chat_id,message_id) ) ;
    CREATE INDEX IF NOT EXISTS idx_group_message_history_user
      ON group_message_history ( chat_id,user_id,message_id ) ;
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
    CREATE INDEX IF NOT EXISTS idx_moderation_log_chat ON moderation_log ( chat_id,created_at ) ;
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
      PRIMARY KEY ( target_user_id,voter_user_id) ) ;
    CREATE INDEX IF NOT EXISTS idx_profile_likes_target ON profile_likes ( target_user_id ) ;
    CREATE TABLE IF NOT EXISTS profile_dislikes(
      target_user_id INTEGER NOT NULL,
      voter_user_id INTEGER NOT NULL,
      created_at INTEGER NOT NULL,
      PRIMARY KEY ( target_user_id,voter_user_id) ) ;
    CREATE INDEX IF NOT EXISTS idx_profile_dislikes_target ON profile_dislikes ( target_user_id ) ;
    CREATE TABLE IF NOT EXISTS ai_book_translations(
      id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, book_id INTEGER NOT NULL,
      target_lang TEXT NOT NULL, status TEXT DEFAULT 'running', started_at INTEGER NOT NULL,
      completed_at INTEGER DEFAULT 0 ) ;
    CREATE INDEX IF NOT EXISTS idx_ai_book_translation_user_done ON ai_book_translations ( user_id,completed_at ) ;
    -- V8: AI rasmli rebus. Kanalga post qilinadi, javob bog‘langan guruhda tekshiriladi.
    CREATE TABLE IF NOT EXISTS rebus_channels(
      owner_id INTEGER PRIMARY KEY, channel_id INTEGER NOT NULL, channel_title TEXT DEFAULT '',
      answer_group_id INTEGER NOT NULL, answer_group_title TEXT DEFAULT '', updated_at INTEGER NOT NULL ) ;
    CREATE TABLE IF NOT EXISTS rebuses(
      id INTEGER PRIMARY KEY AUTOINCREMENT, creator_id INTEGER NOT NULL, channel_id INTEGER NOT NULL,
      answer_group_id INTEGER NOT NULL, answer TEXT NOT NULL, answer_norm TEXT NOT NULL,
      hint TEXT DEFAULT '', channel_message_id INTEGER DEFAULT 0, status TEXT DEFAULT 'active',
      winner_id INTEGER DEFAULT 0, created_at INTEGER NOT NULL, solved_at INTEGER DEFAULT 0 ) ;
    CREATE INDEX IF NOT EXISTS idx_rebus_active_group ON rebuses ( answer_group_id,status,id ) ;
    CREATE TABLE IF NOT EXISTS rebus_sessions(
      id INTEGER PRIMARY KEY AUTOINCREMENT, creator_id INTEGER NOT NULL,
      group_id INTEGER NOT NULL, target_chat_id INTEGER NOT NULL,
      total INTEGER NOT NULL, current_no INTEGER DEFAULT 0,
      status TEXT DEFAULT 'active', created_at INTEGER NOT NULL ) ;
    CREATE TABLE IF NOT EXISTS rebus_session_items(
      session_id INTEGER NOT NULL, item_no INTEGER NOT NULL, answer TEXT NOT NULL,
      rebus_id INTEGER DEFAULT 0, status TEXT DEFAULT 'waiting',
      PRIMARY KEY ( session_id,item_no) ) ;
    CREATE TABLE IF NOT EXISTS rebus_session_scores(
      session_id INTEGER NOT NULL, user_id INTEGER NOT NULL, first_name TEXT DEFAULT '',
      wins INTEGER DEFAULT 0, PRIMARY KEY ( session_id,user_id) ) ;
    CREATE INDEX IF NOT EXISTS idx_rebus_session_group ON rebus_sessions ( group_id,status,id ) ;
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

    -- V8: Vasatiya kutubxonasi. Eski books jadvali o‘zgartirilmaydi.
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
        cols={r[1] for r in c.execute ( "PRAGMA table_info ( library_books ) " ) .fetchall (  ) }
        for col,decl in (
            ("book_file_id","TEXT DEFAULT ''" ) ,
            ("book_unique_id","TEXT DEFAULT ''" ) ,
            ("book_file_name","TEXT DEFAULT ''" ) ,
            ("book_format","TEXT DEFAULT ''" ) ,
            ("book_file_size","INTEGER DEFAULT 0")
        ):
            if col not in cols:
                c.execute ( f"ALTER TABLE library_books ADD COLUMN {col} {decl}")
        c.execute ( "CREATE INDEX IF NOT EXISTS idx_library_book_unique ON library_books ( book_unique_id ) ")
        # Existing PDF records automatically become universal file records too.
        c.execute ( """UPDATE library_books
                     SET book_file_id=pdf_file_id,
                         book_unique_id=pdf_unique_id,
                         book_format=CASE WHEN COALESCE ( book_format,'' ) ='' THEN 'pdf' ELSE book_format END
                     WHERE COALESCE ( book_file_id,'' ) ='' AND COALESCE ( pdf_file_id,'' ) <>''""")

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
    if uid in SUPER_OWNERS: return "👑 Super Ega"
    if is_super_admin ( uid ): return "🛡 Super Admin"
    return "A’zo"

def ai_actor_context ( u ) :
    if not u: return ""
    # Asosiy yaratuvchilar Telegram ID orqali aniq taniladi.
    creator_names={5859289233:"Sakranum",7056675943:"Vasatiya"}
    if u.id in creator_names:
        return f"\n\nTIZIM KONTEKSTI: Hozir yozayotgan foydalanuvchi {creator_names[u.id]} (Telegram ID {u.id} ) . U Veritasni yaratgan Super Egalardan biri."
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
    if uid in SUPER_OWNERS: return "👑 Super Ega"
    if is_super_admin ( uid ): return "🛡 Super Admin"
    return custom or "A’zo"


# =========================================================
# VERITAS V9 — START
# V8 MUZLATILGAN. V9 faqat v9_* jadvallar va v9:/root: callbacklaridan foydalanadi.
# =========================================================
def v9_init_db (  ) :
    with db ( ) as c:
        c.executescript ( """
        CREATE TABLE IF NOT EXISTS v9_profiles ( user_id INTEGER PRIMARY KEY,institution_type TEXT DEFAULT '',role TEXT DEFAULT '',created_at INTEGER NOT NULL ) ;
        CREATE TABLE IF NOT EXISTS v9_groups ( id INTEGER PRIMARY KEY AUTOINCREMENT,teacher_id INTEGER NOT NULL,institution_type TEXT NOT NULL,title TEXT NOT NULL,subject TEXT DEFAULT '',join_code TEXT NOT NULL UNIQUE,is_active INTEGER DEFAULT 1,created_at INTEGER NOT NULL ) ;
        CREATE INDEX IF NOT EXISTS idx_v9_groups_teacher ON v9_groups ( teacher_id ) ;
        CREATE TABLE IF NOT EXISTS v9_group_members ( group_id INTEGER NOT NULL,user_id INTEGER NOT NULL,joined_at INTEGER NOT NULL,is_active INTEGER DEFAULT 1,PRIMARY KEY ( group_id,user_id )  ) ;
        CREATE INDEX IF NOT EXISTS idx_v9_members_user ON v9_group_members ( user_id ) ;
        CREATE TABLE IF NOT EXISTS v9_lessons ( id INTEGER PRIMARY KEY AUTOINCREMENT,group_id INTEGER NOT NULL,teacher_id INTEGER NOT NULL,title TEXT NOT NULL,material_type TEXT DEFAULT 'text',material_file_id TEXT DEFAULT '',material_text TEXT DEFAULT '',ai_mode TEXT DEFAULT 'material_only',status TEXT DEFAULT 'draft',created_at INTEGER NOT NULL ) ;
        CREATE TABLE IF NOT EXISTS v9_lesson_progress ( lesson_id INTEGER NOT NULL,user_id INTEGER NOT NULL,stage TEXT DEFAULT 'new',score INTEGER DEFAULT 0,updated_at INTEGER NOT NULL,PRIMARY KEY ( lesson_id,user_id )  ) ;
        CREATE TABLE IF NOT EXISTS v9_points ( group_id INTEGER NOT NULL,user_id INTEGER NOT NULL,points INTEGER DEFAULT 0,updated_at INTEGER NOT NULL,PRIMARY KEY ( group_id,user_id )  ) ;
        CREATE TABLE IF NOT EXISTS v9_test_results ( id INTEGER PRIMARY KEY AUTOINCREMENT,lesson_id INTEGER NOT NULL,group_id INTEGER NOT NULL,user_id INTEGER NOT NULL,score INTEGER DEFAULT 0,max_score INTEGER DEFAULT 100,correct_count INTEGER DEFAULT 0,total_count INTEGER DEFAULT 0,details TEXT DEFAULT '',created_at INTEGER NOT NULL ) ;
        CREATE TABLE IF NOT EXISTS v9_lesson_materials(
          id INTEGER PRIMARY KEY AUTOINCREMENT,lesson_id INTEGER NOT NULL,kind TEXT NOT NULL,
          file_id TEXT DEFAULT '',file_name TEXT DEFAULT '',mime_type TEXT DEFAULT '',
          extracted_text TEXT DEFAULT '',created_at INTEGER NOT NULL ) ;
        CREATE TABLE IF NOT EXISTS v9_tests(
          id INTEGER PRIMARY KEY AUTOINCREMENT,lesson_id INTEGER NOT NULL,questions_json TEXT NOT NULL,
          created_at INTEGER NOT NULL ) ;
        """)

def root_choice_markup (  ) :
    return InlineKeyboardMarkup ( [[InlineKeyboardButton ( "🛡 Veritas",callback_data="root:v8" ) ],[InlineKeyboardButton ( "🎓 O‘quv • Talaba",callback_data="root:v9" ) ]])

def v9_entry_markup (  ) :
    return InlineKeyboardMarkup ( [[InlineKeyboardButton ( "🏫 Maktab",callback_data="v9:inst:school" ) ],[InlineKeyboardButton ( "🏛 Institut",callback_data="v9:inst:institute" ) ,InlineKeyboardButton ( "🎓 Universitet",callback_data="v9:inst:university" ) ],[InlineKeyboardButton ( "⬅️ Veritas tanlash",callback_data="root:choose" ) ]])

def v9_role_markup ( inst ) :
    return InlineKeyboardMarkup ( [[InlineKeyboardButton ( "👨‍🏫 Ustoz",callback_data=f"v9:role:{inst}:teacher" ) ,InlineKeyboardButton ( "👨‍🎓 O‘quvchi / Talaba",callback_data=f"v9:role:{inst}:student" ) ],[InlineKeyboardButton ( "⬅️ Orqaga",callback_data="v9:home" ) ]])

def v9_teacher_markup (  ) :
    return InlineKeyboardMarkup ( [[InlineKeyboardButton ( "➕ Yangi guruh",callback_data="v9:teacher:newgroup" ) ],[InlineKeyboardButton ( "👥 Guruhlarim",callback_data="v9:teacher:groups" ) ],[InlineKeyboardButton ( "📊 Natijalar / Jurnal",callback_data="v9:teacher:journal" ) ],[InlineKeyboardButton ( "⬅️ Veritas tanlash",callback_data="root:choose" ) ]])

def v9_student_markup (  ) :
    return InlineKeyboardMarkup ( [[InlineKeyboardButton ( "➕ Guruhga qo‘shilish",callback_data="v9:student:join" ) ],[InlineKeyboardButton ( "📚 Guruhlarim / Darslarim",callback_data="v9:student:groups" ) ],[InlineKeyboardButton ( "🏆 Ballarim",callback_data="v9:student:points" ) ],[InlineKeyboardButton ( "⬅️ Veritas tanlash",callback_data="root:choose" ) ]])

async def v9_start_selector ( update,ctx ) :
    ensure_user ( update.effective_user)
    await update.effective_message.reply_text(
        "🪶 VERITAS\n\nAsosiy menyu pastda doim turadi.",
        reply_markup=veritas_global_keyboard ( )
    )
    await update.effective_message.reply_text(
        "Qaysi bo‘limga kirishni xohlaysiz?",
        reply_markup=root_choice_markup ( )
    )

async def v9_callback ( update,ctx ) :
    q=update.callback_query
    if not q or not q.data:return
    d=q.data; u=q.from_user
    await q.answer (  ) ; ensure_user ( u)
    if d=="root:choose": return await q.edit_message_text ( "🪶 VERITAS\n\nQaysi bo‘limga kirishni xohlaysiz?",reply_markup=root_choice_markup (  ) )
    if d=="root:v8": return await q.edit_message_text ( "🛡 VERITAS\n\nAsosiy bo‘lim:",reply_markup=main_menu_markup ( u.id ) )
    if d in ("root:v9","v9:home" ) : return await q.edit_message_text ( "🎓 VERITAS V9 — O‘QUV • TALABA\n\nTa’lim turini tanlang:",reply_markup=v9_entry_markup (  ) )
    if d.startswith ( "v9:inst:" ) :
        inst=d.rsplit ( ":",1 ) [1]
        if inst in {"school","institute","university"}: return await q.edit_message_text ( "Sizning rolingiz:",reply_markup=v9_role_markup ( inst ) )
    if d.startswith ( "v9:role:" ) :
        _,_,inst,role=d.split ( ":",3)
        if inst not in {"school","institute","university"} or role not in {"teacher","student"}: return
        with db ( ) as c:c.execute ( "INSERT INTO v9_profiles ( user_id,institution_type,role,created_at) VALUES ( ?,?,?,?) ON CONFLICT ( user_id) DO UPDATE SET institution_type=excluded.institution_type,role=excluded.role", ( u.id,inst,role,now (  )  ) )
        if role=="teacher": return await q.edit_message_text ( "👨‍🏫 USTOZ KABINETI\n\nGuruh yarating, dars materiallarini bering va natijalarni kuzating.",reply_markup=v9_teacher_markup (  ) )
        return await q.edit_message_text ( "👨‍🎓 O‘QUVCHI / TALABA KABINETI\n\nGuruhga qo‘shiling, AI bilan dars o‘rganing va ball to‘plang.",reply_markup=v9_student_markup (  ) )
    if d=="v9:teacher:home": return await q.edit_message_text ( "👨‍🏫 USTOZ KABINETI",reply_markup=v9_teacher_markup (  ) )
    if d=="v9:student:home": return await q.edit_message_text ( "👨‍🎓 O‘QUVCHI / TALABA KABINETI",reply_markup=v9_student_markup (  ) )
    if d=="v9:teacher:newgroup":
        STATE[u.id]={"mode":"v9_new_group_title"}
        return await q.edit_message_text ( "➕ YANGI GURUH\n\nGuruh nomini yozing.\nMasalan: Matematika — 1-kurs",reply_markup=InlineKeyboardMarkup ( [[InlineKeyboardButton ( "⬅️ Kabinet",callback_data="v9:teacher:home" ) ]] ) )
    if d=="v9:student:join":
        STATE[u.id]={"mode":"v9_join_group"}
        return await q.edit_message_text ( "🔑 GURUHGA QO‘SHILISH\n\nUstoz bergan guruh kodini yuboring.",reply_markup=InlineKeyboardMarkup ( [[InlineKeyboardButton ( "⬅️ Kabinet",callback_data="v9:student:home" ) ]] ) )
    if d=="v9:teacher:groups":
        rows=all_ ( "SELECT id,title FROM v9_groups WHERE teacher_id=? AND is_active=1 ORDER BY id DESC", ( u.id, ) )
        if not rows:return await q.edit_message_text ( "👥 Hali guruh yaratmagansiz.",reply_markup=v9_teacher_markup (  ) )
        kb=[[InlineKeyboardButton ( "📚 "+r["title"][:45],callback_data=f"v9:group:{r['id']}" ) ] for r in rows[:30]]+[[InlineKeyboardButton ( "⬅️ Kabinet",callback_data="v9:teacher:home" ) ]]
        return await q.edit_message_text ( "👥 GURUHLARIM",reply_markup=InlineKeyboardMarkup ( kb ) )
    if d=="v9:student:groups":
        rows=all_ ( "SELECT g.id,g.title FROM v9_groups g JOIN v9_group_members m ON m.group_id=g.id WHERE m.user_id=? AND m.is_active=1 AND g.is_active=1 ORDER BY g.id DESC", ( u.id, ) )
        if not rows:return await q.edit_message_text ( "📚 Siz hali guruhga qo‘shilmagansiz.",reply_markup=v9_student_markup (  ) )
        kb=[[InlineKeyboardButton ( "📚 "+r["title"][:45],callback_data=f"v9:group:{r['id']}" ) ] for r in rows[:30]]+[[InlineKeyboardButton ( "⬅️ Kabinet",callback_data="v9:student:home" ) ]]
        return await q.edit_message_text ( "📚 GURUHLARIM / DARSLARIM",reply_markup=InlineKeyboardMarkup ( kb ) )
    if d=="v9:student:points":
        rows=all_ ( "SELECT g.title,p.points FROM v9_points p JOIN v9_groups g ON g.id=p.group_id WHERE p.user_id=? ORDER BY p.points DESC", ( u.id, ) )
        body="\n".join ( f"🏆 {r['title']}: {r['points']} ball" for r in rows) or "Hozircha ball yo‘q."
        return await q.edit_message_text ( "🏆 BALLARIM\n\n"+body,reply_markup=v9_student_markup (  ) )
    if d.startswith ( "v9:group:" ) :
        gid=int ( d.rsplit ( ":",1 ) [1] ) ; g=one ( "SELECT * FROM v9_groups WHERE id=? AND is_active=1", ( gid, ) )
        if not g:return await q.answer ( "Guruh topilmadi.",show_alert=True)
        teacher=int ( g["teacher_id"] ) ==u.id; member=one ( "SELECT 1 FROM v9_group_members WHERE group_id=? AND user_id=? AND is_active=1", ( gid,u.id ) )
        if not teacher and not member:return await q.answer ( "Bu guruhga kirish huquqingiz yo‘q.",show_alert=True)
        count=one ( "SELECT COUNT ( *) n FROM v9_group_members WHERE group_id=? AND is_active=1", ( gid, )  ) ["n"]
        kb=InlineKeyboardMarkup ( [[InlineKeyboardButton ( "➕ Yangi dars",callback_data=f"v9:lesson:new:{gid}" ) ],[InlineKeyboardButton ( "📚 Darslar",callback_data=f"v9:lessons:{gid}" ) ,InlineKeyboardButton ( "📊 Natijalar",callback_data=f"v9:results:{gid}" ) ],[InlineKeyboardButton ( "⬅️ Guruhlarim",callback_data="v9:teacher:groups" ) ]]) if teacher else InlineKeyboardMarkup ( [[InlineKeyboardButton ( "📚 Darslar",callback_data=f"v9:lessons:{gid}" ) ],[InlineKeyboardButton ( "🏆 Guruh reytingi",callback_data=f"v9:ranking:{gid}" ) ],[InlineKeyboardButton ( "⬅️ Guruhlarim",callback_data="v9:student:groups" ) ]])
        return await q.edit_message_text ( f"📚 {g['title']}\n📖 Fan: {g['subject'] or 'Kiritilmagan'}\n👥 Talabalar: {count}\n🔑 Guruh kodi: {g['join_code']}",reply_markup=kb)

    if d.startswith ( "v9:lesson:new:" ) :
        gid=int ( d.rsplit ( ":",1 ) [1])
        g=one ( "SELECT * FROM v9_groups WHERE id=? AND teacher_id=? AND is_active=1", ( gid,u.id ) )
        if not g:return await q.answer ( "Bu guruh sizga tegishli emas.",show_alert=True)
        STATE[u.id]={"mode":"v9_lesson_title","group_id":gid}
        return await q.edit_message_text(
            f"➕ YANGI DARS\n\n📚 Guruh: {g['title']}\n\n1/3 — Dars nomini yozing.",
            reply_markup=InlineKeyboardMarkup ( [[InlineKeyboardButton ( "❌ Bekor qilish",callback_data=f"v9:group:{gid}" ) ]] ) )

    if d.startswith ( "v9:lessonmode:" ) :
        mode_choice=d.rsplit ( ":",1 ) [1]
        st=STATE.get ( u.id) or {}
        if st.get ( "mode" ) !="v9_lesson_mode" or mode_choice not in {"material_only","ai_plus"}:
            return await q.answer ( "Dars yaratish sessiyasi topilmadi.",show_alert=True)
        gid=int ( st["group_id"] ) ; g=one ( "SELECT * FROM v9_groups WHERE id=? AND teacher_id=?", ( gid,u.id ) )
        if not g:return await q.answer ( "Ruxsat yo‘q.",show_alert=True)
        mat=st["material"]; title=st["title"]
        with db ( ) as c:
            lid=c.execute ( """INSERT INTO v9_lessons ( group_id,teacher_id,title,material_type,material_file_id,material_text,ai_mode,status,created_at)
                             VALUES ( ?,?,?,?,?,?,?,'published',? ) """,
                          (gid,u.id,title,mat["kind"],mat["file_id"],mat["text"],mode_choice,now (  )  )  ) .lastrowid
            c.execute ( """INSERT INTO v9_lesson_materials ( lesson_id,kind,file_id,file_name,mime_type,extracted_text,created_at)
                         VALUES ( ?,?,?,?,?,?,? ) """, ( lid,mat["kind"],mat["file_id"],mat["file_name"],mat["mime"],mat["text"],now (  )  ) )
        STATE.pop ( u.id,None)
        await q.edit_message_text(
            f"✅ DARS E’LON QILINDI\n\n📖 {title}\n📚 {g['title']}\n"
            + ( "🔒 AI faqat darslikdan javob beradi." if mode_choice=="material_only" else "🧠 AI darslikni asos qilib qo‘shimcha tushuntiradi." ) ,
            reply_markup=InlineKeyboardMarkup ( [[InlineKeyboardButton ( "📖 Darsni ochish",callback_data=f"v9:lesson:view:{lid}" ) ],[InlineKeyboardButton ( "⬅️ Guruh",callback_data=f"v9:group:{gid}" ) ]] ) )
        return
    if d.startswith ( "v9:lessons:" ) :
        gid=int ( d.rsplit ( ":",1 ) [1])
        g=one ( "SELECT * FROM v9_groups WHERE id=? AND is_active=1", ( gid, ) )
        if not g:return await q.answer ( "Guruh topilmadi.",show_alert=True)
        teacher=int ( g["teacher_id"] ) ==u.id
        member=one ( "SELECT 1 FROM v9_group_members WHERE group_id=? AND user_id=? AND is_active=1", ( gid,u.id ) )
        if not teacher and not member:return await q.answer ( "Ruxsat yo‘q.",show_alert=True)
        rows=all_ ( "SELECT id,title,status FROM v9_lessons WHERE group_id=? AND status='published' ORDER BY id DESC", ( gid, ) )
        if not rows:
            back=f"v9:group:{gid}"
            return await q.edit_message_text ( "📚 Hozircha e’lon qilingan dars yo‘q.",reply_markup=InlineKeyboardMarkup ( [[InlineKeyboardButton ( "⬅️ Guruh",callback_data=back ) ]] ) )
        kb=[[InlineKeyboardButton (  ( "👨‍🏫 " if teacher else "📖 " ) +r["title"][:45],callback_data=f"v9:lesson:view:{r['id']}" ) ] for r in rows[:40]]
        kb.append ( [InlineKeyboardButton ( "⬅️ Guruh",callback_data=f"v9:group:{gid}" ) ])
        return await q.edit_message_text ( "📚 DARSLAR",reply_markup=InlineKeyboardMarkup ( kb ) )

    if d.startswith ( "v9:lesson:view:" ) :
        lid=int ( d.rsplit ( ":",1 ) [1])
        l=one ( """SELECT l.*,g.title group_title,g.teacher_id group_teacher
                 FROM v9_lessons l JOIN v9_groups g ON g.id=l.group_id
                 WHERE l.id=? AND l.status='published'""", ( lid, ) )
        if not l:return await q.answer ( "Dars topilmadi.",show_alert=True)
        teacher=int ( l["group_teacher"] ) ==u.id
        member=one ( "SELECT 1 FROM v9_group_members WHERE group_id=? AND user_id=? AND is_active=1", ( l["group_id"],u.id ) )
        if not teacher and not member:return await q.answer ( "Ruxsat yo‘q.",show_alert=True)
        mode="🔒 Faqat darslikdan" if l["ai_mode"]=="material_only" else "🧠 Darslik + AI tushuntirishi"
        if teacher:
            kb=InlineKeyboardMarkup ( [
              [InlineKeyboardButton ( "📄 Material",callback_data=f"v9:lesson:material:{lid}" ) ,
               InlineKeyboardButton ( "📝 Test yaratish",callback_data=f"v9:test:make:{lid}" ) ],
              [InlineKeyboardButton ( "📊 Natijalar",callback_data=f"v9:lesson:results:{lid}" ) ],
              [InlineKeyboardButton ( "⬅️ Darslar",callback_data=f"v9:lessons:{l['group_id']}" ) ]])
        else:
            kb=InlineKeyboardMarkup ( [
              [InlineKeyboardButton ( "🤖 AI bilan o‘rganish",callback_data=f"v9:learn:{lid}" ) ],
              [InlineKeyboardButton ( "📝 Yakuniy test",callback_data=f"v9:test:start:{lid}" ) ],
              [InlineKeyboardButton ( "⬅️ Darslar",callback_data=f"v9:lessons:{l['group_id']}" ) ]])
        return await q.edit_message_text(
            f"📖 {l['title']}\n📚 {l['group_title']}\n{mode}",
            reply_markup=kb)

    if d.startswith ( "v9:lesson:material:" ) :
        lid=int ( d.rsplit ( ":",1 ) [1])
        l=one ( "SELECT * FROM v9_lessons WHERE id=? AND teacher_id=?", ( lid,u.id ) )
        if not l:return await q.answer ( "Ruxsat yo‘q.",show_alert=True)
        mats=all_ ( "SELECT kind,file_name,extracted_text FROM v9_lesson_materials WHERE lesson_id=? ORDER BY id", ( lid, ) )
        lines=[]
        for i,m in enumerate ( mats,1 ) :
            nm=m["file_name"] or ("Yozma material" if m["kind"]=="text" else m["kind"])
            lines.append ( f"{i}. {nm} — {len ( m['extracted_text'] or '' ) } belgi")
        return await q.edit_message_text ( "📄 DARS MATERIALLARI\n\n"+ ( "\n".join ( lines) or "Material yo‘q." ) ,reply_markup=InlineKeyboardMarkup ( [[InlineKeyboardButton ( "⬅️ Dars",callback_data=f"v9:lesson:view:{lid}" ) ]] ) )

    if d.startswith ( "v9:learn:" ) :
        lid=int ( d.rsplit ( ":",1 ) [1])
        l=one ( "SELECT * FROM v9_lessons WHERE id=? AND status='published'", ( lid, ) )
        if not l:return await q.answer ( "Dars topilmadi.",show_alert=True)
        member=one ( "SELECT 1 FROM v9_group_members WHERE group_id=? AND user_id=? AND is_active=1", ( l["group_id"],u.id ) )
        if not member:return await q.answer ( "Siz bu guruh talabasi emassiz.",show_alert=True)
        material=v9_lesson_context ( lid)
        if not material:return await q.answer ( "Dars materiali bo‘sh.",show_alert=True)
        STATE[u.id]={"mode":"v9_ai_lesson","lesson_id":lid,"group_id":l["group_id"]}
        with db ( ) as c:
            c.execute ( """INSERT INTO v9_lesson_progress ( lesson_id,user_id,stage,score,updated_at)
                         VALUES ( ?,?,'learning',0,?)
                         ON CONFLICT ( lesson_id,user_id) DO UPDATE SET stage='learning',updated_at=excluded.updated_at""", ( lid,u.id,now (  )  ) )
        intro=await v9_ai_teach ( l,material,"Darsni boshlang. Avval mavzuni sodda va qiziqarli qilib tushuntiring, keyin menga bitta tekshiruvchi savol bering.")
        await q.edit_message_text ( f"🤖 AI USTOZ — {l['title']}\n\n{intro[:3500]}",reply_markup=InlineKeyboardMarkup ( [[InlineKeyboardButton ( "📝 Testga o‘tish",callback_data=f"v9:test:start:{lid}" ) ],[InlineKeyboardButton ( "⬅️ Dars",callback_data=f"v9:lesson:view:{lid}" ) ]] ) )
        return

    if d.startswith ( "v9:test:make:" ) :
        lid=int ( d.rsplit ( ":",1 ) [1])
        l=one ( "SELECT * FROM v9_lessons WHERE id=? AND teacher_id=?", ( lid,u.id ) )
        if not l:return await q.answer ( "Ruxsat yo‘q.",show_alert=True)
        await q.edit_message_text ( "🧠 AI test tayyorlamoqda...")
        qs=await v9_make_test ( lid,10)
        if not qs:return await q.edit_message_text ( "⚠️ Test yaratilmadi.",reply_markup=InlineKeyboardMarkup ( [[InlineKeyboardButton ( "⬅️ Dars",callback_data=f"v9:lesson:view:{lid}" ) ]] ) )
        with db ( ) as c:c.execute ( "INSERT INTO v9_tests ( lesson_id,questions_json,created_at) VALUES ( ?,?,? ) ", ( lid,json.dumps ( qs,ensure_ascii=False ) ,now (  )  ) )
        return await q.edit_message_text ( f"✅ {len ( qs ) } ta savolli test tayyorlandi.\n\nTalabalar endi dars ichidan testni topshira oladi.",reply_markup=InlineKeyboardMarkup ( [[InlineKeyboardButton ( "⬅️ Dars",callback_data=f"v9:lesson:view:{lid}" ) ]] ) )

    if d.startswith ( "v9:test:start:" ) :
        lid=int ( d.rsplit ( ":",1 ) [1])
        l=one ( "SELECT * FROM v9_lessons WHERE id=? AND status='published'", ( lid, ) )
        if not l:return await q.answer ( "Dars topilmadi.",show_alert=True)
        member=one ( "SELECT 1 FROM v9_group_members WHERE group_id=? AND user_id=? AND is_active=1", ( l["group_id"],u.id ) )
        if not member:return await q.answer ( "Siz bu guruh talabasi emassiz.",show_alert=True)
        tr=one ( "SELECT * FROM v9_tests WHERE lesson_id=? ORDER BY id DESC LIMIT 1", ( lid, ) )
        if not tr:
            qs=await v9_make_test ( lid,10)
            if not qs:return await q.answer ( "Test hali tayyor emas.",show_alert=True)
            with db ( ) as c:
                tid=c.execute ( "INSERT INTO v9_tests ( lesson_id,questions_json,created_at) VALUES ( ?,?,? ) ", ( lid,json.dumps ( qs,ensure_ascii=False ) ,now (  )  )  ) .lastrowid
        else:
            tid=tr["id"]; qs=json.loads ( tr["questions_json"])
        STATE[u.id]={"mode":"v9_test","lesson_id":lid,"group_id":l["group_id"],"test_id":tid,"questions":qs,"index":0,"correct":0}
        return await v9_send_test_question ( q.message,u.id)

    if d.startswith ( "v9:ans:" ) :
        parts=d.split ( ":")
        if len ( parts ) !=4:return
        lid=int ( parts[2] ) ; chosen=int ( parts[3])
        st=STATE.get ( u.id) or {}
        if st.get ( "mode" ) !="v9_test" or int ( st.get ( "lesson_id",0 )  ) !=lid:return await q.answer ( "Bu test sessiyasi tugagan.",show_alert=True)
        qs=st["questions"]; idx=int ( st["index"])
        if idx>=len ( qs ) :return
        correct=int ( qs[idx]["answer"])
        if chosen==correct: st["correct"]=int ( st.get ( "correct",0 )  ) +1
        st["index"]=idx+1; STATE[u.id]=st
        await q.answer ( "✅ To‘g‘ri!" if chosen==correct else f"❌ To‘g‘ri javob: {correct+1}")
        if st["index"]>=len ( qs ) :
            total=len ( qs ) ; corr=int ( st["correct"] ) ; score=round ( corr*100/total) if total else 0
            with db ( ) as c:
                c.execute ( """INSERT INTO v9_test_results ( lesson_id,group_id,user_id,score,max_score,correct_count,total_count,details,created_at)
                             VALUES ( ?,?,?,?,100,?,?,?,? ) """, ( lid,st["group_id"],u.id,score,corr,total,json.dumps ( {"test_id":st["test_id"]} ) ,now (  )  ) )
                c.execute ( """INSERT INTO v9_points ( group_id,user_id,points,updated_at) VALUES ( ?,?,?,?)
                             ON CONFLICT ( group_id,user_id) DO UPDATE SET points=points+excluded.points,updated_at=excluded.updated_at""", ( st["group_id"],u.id,score,now (  )  ) )
                c.execute ( """INSERT INTO v9_lesson_progress ( lesson_id,user_id,stage,score,updated_at)
                             VALUES ( ?,?,'completed',?,?)
                             ON CONFLICT ( lesson_id,user_id) DO UPDATE SET stage='completed',score=excluded.score,updated_at=excluded.updated_at""", ( lid,u.id,score,now (  )  ) )
            STATE.pop ( u.id,None)
            return await q.edit_message_text ( f"🏁 TEST TUGADI\n\n✅ To‘g‘ri: {corr}/{total}\n🎯 Natija: {score}/100\n🏆 Guruh balliga: +{score}",reply_markup=InlineKeyboardMarkup ( [[InlineKeyboardButton ( "📖 Darsga qaytish",callback_data=f"v9:lesson:view:{lid}" ) ]] ) )
        return await v9_send_test_question ( q.message,u.id,edit=True)

    if d.startswith ( "v9:lesson:results:" ) :
        lid=int ( d.rsplit ( ":",1 ) [1])
        l=one ( "SELECT * FROM v9_lessons WHERE id=? AND teacher_id=?", ( lid,u.id ) )
        if not l:return await q.answer ( "Ruxsat yo‘q.",show_alert=True)
        rows=all_ ( """SELECT r.user_id,MAX ( r.score) score,MAX ( r.correct_count) correct_count,MAX ( r.total_count) total_count,
                    COALESCE ( us.first_name,'') first_name,COALESCE ( us.username,'') username
                    FROM v9_test_results r LEFT JOIN users us ON us.user_id=r.user_id
                    WHERE r.lesson_id=? GROUP BY r.user_id ORDER BY score DESC""", ( lid, ) )
        body="\n".join ( f"{i}. {r['first_name'] or ('@'+r['username'] if r['username'] else r['user_id'] ) } — {r['score']}/100" for i,r in enumerate ( rows,1 ) ) or "Hali test topshirgan talaba yo‘q."
        return await q.edit_message_text ( f"📊 {l['title']} — NATIJALAR\n\n{body[:3500]}",reply_markup=InlineKeyboardMarkup ( [[InlineKeyboardButton ( "⬅️ Dars",callback_data=f"v9:lesson:view:{lid}" ) ]] ) )

    if d.startswith ( "v9:results:" ) :
        gid=int ( d.rsplit ( ":",1 ) [1])
        g=one ( "SELECT * FROM v9_groups WHERE id=? AND teacher_id=?", ( gid,u.id ) )
        if not g:return await q.answer ( "Ruxsat yo‘q.",show_alert=True)
        rows=all_ ( """SELECT m.user_id,COALESCE ( us.first_name,'') first_name,COALESCE ( us.username,'') username,
                    COALESCE ( p.points,0) points,COALESCE ( AVG ( r.score ) ,0) avg_score
                    FROM v9_group_members m LEFT JOIN users us ON us.user_id=m.user_id
                    LEFT JOIN v9_points p ON p.group_id=m.group_id AND p.user_id=m.user_id
                    LEFT JOIN v9_test_results r ON r.group_id=m.group_id AND r.user_id=m.user_id
                    WHERE m.group_id=? AND m.is_active=1 GROUP BY m.user_id ORDER BY points DESC""", ( gid, ) )
        body="\n".join ( f"{i}. {r['first_name'] or ('@'+r['username'] if r['username'] else r['user_id'] ) } — 🏆 {r['points']} | 📝 {round ( r['avg_score'] ) }" for i,r in enumerate ( rows,1 ) ) or "Talabalar natijasi hali yo‘q."
        return await q.edit_message_text ( f"📊 {g['title']} — JURNAL\n\n{body[:3500]}",reply_markup=InlineKeyboardMarkup ( [[InlineKeyboardButton ( "⬅️ Guruh",callback_data=f"v9:group:{gid}" ) ]] ) )

    if d.startswith ( "v9:ranking:" ) :
        gid=int ( d.rsplit ( ":",1 ) [1])
        rows=all_ ( """SELECT p.user_id,p.points,COALESCE ( us.first_name,'') first_name,COALESCE ( us.username,'') username
                     FROM v9_points p LEFT JOIN users us ON us.user_id=p.user_id
                     WHERE p.group_id=? ORDER BY p.points DESC LIMIT 30""", ( gid, ) )
        body="\n".join ( f"{i}. {r['first_name'] or ('@'+r['username'] if r['username'] else r['user_id'] ) } — {r['points']} ball" for i,r in enumerate ( rows,1 ) ) or "Hali ballar yo‘q."
        return await q.edit_message_text ( "🏆 GURUH REYTINGI\n\n"+body,reply_markup=InlineKeyboardMarkup ( [[InlineKeyboardButton ( "⬅️ Guruh",callback_data=f"v9:group:{gid}" ) ]] ) )

    if d=="v9:teacher:journal":
        rows=all_ ( "SELECT id,title FROM v9_groups WHERE teacher_id=? AND is_active=1 ORDER BY id DESC", ( u.id, ) )
        if not rows:return await q.edit_message_text ( "📊 Hali guruh yo‘q.",reply_markup=v9_teacher_markup (  ) )
        kb=[[InlineKeyboardButton ( "📊 "+r["title"][:45],callback_data=f"v9:results:{r['id']}" ) ] for r in rows]
        kb.append ( [InlineKeyboardButton ( "⬅️ Kabinet",callback_data="v9:teacher:home" ) ])
        return await q.edit_message_text ( "📊 NATIJALAR / JURNAL\n\nGuruhni tanlang:",reply_markup=InlineKeyboardMarkup ( kb ) )


def veritas_global_keyboard (  ) :
    return ReplyKeyboardMarkup(
        [[KeyboardButton ( "🛡 Veritas" ) , KeyboardButton ( "🎓 O‘quv • Talaba" ) ]],
        resize_keyboard=True,
        is_persistent=True
    )

def v9_teacher_keyboard (  ) :
    return veritas_global_keyboard ( )

def v9_student_keyboard (  ) :
    return veritas_global_keyboard ( )

def v9_lesson_context ( lid,limit=30000 ) :
    rows=all_ ( "SELECT extracted_text FROM v9_lesson_materials WHERE lesson_id=? ORDER BY id", ( lid, ) )
    text="\n\n".join (  ( r["extracted_text"] or "" ) .strip ( ) for r in rows if (r["extracted_text"] or "" ) .strip (  ) )
    if not text:
        l=one ( "SELECT material_text FROM v9_lessons WHERE id=?", ( lid, ) )
        text= ( l["material_text"] or "") if l else ""
    return text[:limit]

def v9_extract_pdf ( raw ) :
    if fitz is None:return ""
    doc=fitz.open ( stream=raw,filetype="pdf")
    parts=[]
    for page in doc:
        parts.append ( page.get_text ( "text" ) )
        if sum ( len ( x) for x in parts ) >45000:break
    doc.close ( )
    return "\n".join ( parts ) [:45000]

async def v9_ai_teach ( lesson,material,user_text ) :
    if not OPENAI_API_KEY:
        return "⚠️ OPENAI_API_KEY sozlanmagan."
    rule= ( "FAQAT berilgan dars materiali doirasida javob ber. Materialda javob bo‘lmasa, "
          "“Bu ma’lumot ustoz bergan darslikda yo‘q” deb ayt.") if lesson["ai_mode"]=="material_only" else (
          "Asosiy manba ustoz bergan material bo‘lsin. Tushuntirish uchun umumiy bilimdan foydalanishingiz mumkin, "
          "lekin materialdan tashqari qo‘shimchani aniq ajratib ko‘rsating.")
    prompt=f"""Siz Veritas V9 AI Ustozsiz.
Dars: {lesson['title']}
QOIDA: {rule}
Talabaga yoshiga mos, sodda, bosqichma-bosqich va interaktiv tarzda o‘rgating.
Keraksiz uzun javob bermang.

USTOZ BERGAN MATERIAL:
{material}

TALABA:
{user_text}
"""
    try:return await asyncio.to_thread ( _openai_response_sync,prompt)
    except Exception as e:
        log.exception ( "V9 AI teach: %s",e)
        return "⚠️ AI Ustoz vaqtincha javob bera olmadi."

async def v9_make_test ( lid,count=10 ) :
    l=one ( "SELECT * FROM v9_lessons WHERE id=?", ( lid, ) )
    material=v9_lesson_context ( lid)
    if not l or not material or not OPENAI_API_KEY:return []
    prompt=f"""Quyidagi dars materialidan aynan {count} ta 4 variantli test tuzing.
Faqat materialga tayangan savollar bo‘lsin. JSONdan boshqa hech narsa yozmang.
Format:
[{{"q":"savol","options":["A","B","C","D"],"answer":0}}]
answer 0..3 oralig‘idagi to‘g‘ri variant indeksi.

DARS: {l['title']}
MATERIAL:
{material[:28000]}
"""
    try:
        raw=await asyncio.to_thread ( _openai_response_sync,prompt)
        m=re.search ( r"\[[\s\S]*\]",raw)
        data=json.loads ( m.group ( 0) if m else raw)
        good=[]
        for x in data:
            if isinstance ( x,dict) and isinstance ( x.get ( "q" ) ,str) and isinstance ( x.get ( "options" ) ,list) and len ( x["options"] ) ==4 and str ( x.get ( "answer","" )  ) .isdigit (  ) :
                a=int ( x["answer"])
                if 0<=a<4:good.append ( {"q":x["q"][:500],"options":[str ( z ) [:200] for z in x["options"]],"answer":a})
        return good[:count]
    except Exception as e:
        log.exception ( "V9 test generation: %s",e ) ;return []

async def v9_send_test_question ( msg,uid,edit=False ) :
    st=STATE.get ( uid) or {}; qs=st.get ( "questions") or []; idx=int ( st.get ( "index",0 ) )
    if idx>=len ( qs ) :return
    x=qs[idx]; lid=st["lesson_id"]
    kb=InlineKeyboardMarkup ( [[InlineKeyboardButton ( f"{i+1}. {opt}",callback_data=f"v9:ans:{lid}:{i}" ) ] for i,opt in enumerate ( x["options"] ) ])
    text=f"📝 TEST — {idx+1}/{len ( qs ) }\n\n{x['q']}"
    if edit:return await msg.edit_text ( text,reply_markup=kb)
    return await msg.reply_text ( text,reply_markup=kb)

async def v9_show_teacher_home ( msg,uid ) :
    await msg.reply_text ( "👨‍🏫 USTOZ KABINETI\n\nTezkor menyu pastda doim turadi.",reply_markup=v9_teacher_keyboard (  ) )
    await msg.reply_text ( "Kerakli bo‘lim:",reply_markup=v9_teacher_markup (  ) )

async def v9_show_student_home ( msg,uid ) :
    await msg.reply_text ( "👨‍🎓 O‘QUVCHI / TALABA KABINETI\n\nTezkor menyu pastda doim turadi.",reply_markup=v9_student_keyboard (  ) )
    await msg.reply_text ( "Kerakli bo‘lim:",reply_markup=v9_student_markup (  ) )

async def v9_private_input ( update,ctx ) :
    msg=update.effective_message;u=update.effective_user
    if not msg or not u or msg.chat.type!="private":return
    st=STATE.get ( u.id) or {};mode=st.get ( "mode")
    if str ( mode ) .startswith ( "v9_" ) :
        ctx.user_data["v9_consumed_message_id"]=msg.message_id
    # V9 doimiy tezkor menyu
    txt= ( msg.text or "" ) .strip ( )
    prof=one ( "SELECT role FROM v9_profiles WHERE user_id=?", ( u.id, ) )
    role=prof["role"] if prof else ""

    # GLOBAL NAVIGATSIYA — V8/V9 ichida qayerda bo‘lishidan qat’i nazar.
    if txt=="🛡 Veritas":
        STATE.pop ( u.id,None)
        ctx.user_data.pop ( "v9_consumed_message_id",None)
        await msg.reply_text ( "🛡 VERITAS\n\nAsosiy bo‘lim:",reply_markup=main_menu_markup ( u.id ) )
        return await msg.reply_text ( "Asosiy panel:",reply_markup=veritas_global_keyboard (  ) )

    if txt=="🎓 O‘quv • Talaba":
        STATE.pop ( u.id,None)
        ctx.user_data.pop ( "v9_consumed_message_id",None)
        await msg.reply_text ( "🎓 O‘QUV • TALABA\n\nTa’lim turini tanlang:",reply_markup=v9_entry_markup (  ) )
        return await msg.reply_text ( "Asosiy panel:",reply_markup=veritas_global_keyboard (  ) )

    if txt=="🏠 Bosh menyu" and role:
        STATE.pop ( u.id,None)
        if role=="teacher": return await v9_show_teacher_home ( msg,u.id)
        return await v9_show_student_home ( msg,u.id)

    if txt=="👥 Guruhlarim" and role=="teacher":
        STATE.pop ( u.id,None)
        rows=all_ ( "SELECT id,title FROM v9_groups WHERE teacher_id=? AND is_active=1 ORDER BY id DESC", ( u.id, ) )
        kb=[[InlineKeyboardButton ( "📚 "+r["title"][:45],callback_data=f"v9:group:{r['id']}" ) ] for r in rows[:30]]
        if not kb:return await msg.reply_text ( "👥 Hali guruh yaratmagansiz.",reply_markup=v9_teacher_keyboard (  ) )
        return await msg.reply_text ( "👥 GURUHLARIM",reply_markup=InlineKeyboardMarkup ( kb ) )

    if txt=="➕ Dars berish" and role=="teacher":
        STATE.pop ( u.id,None)
        rows=all_ ( "SELECT id,title FROM v9_groups WHERE teacher_id=? AND is_active=1 ORDER BY id DESC", ( u.id, ) )
        if not rows:return await msg.reply_text ( "Avval guruh yarating.",reply_markup=v9_teacher_keyboard (  ) )
        kb=[[InlineKeyboardButton ( "➕ "+r["title"][:45],callback_data=f"v9:lesson:new:{r['id']}" ) ] for r in rows]
        return await msg.reply_text ( "Qaysi guruhga dars berasiz?",reply_markup=InlineKeyboardMarkup ( kb ) )

    if txt=="📊 Jurnal" and role=="teacher":
        STATE.pop ( u.id,None)
        rows=all_ ( "SELECT id,title FROM v9_groups WHERE teacher_id=? AND is_active=1 ORDER BY id DESC", ( u.id, ) )
        kb=[[InlineKeyboardButton ( "📊 "+r["title"][:45],callback_data=f"v9:results:{r['id']}" ) ] for r in rows]
        return await msg.reply_text ( "📊 JURNAL\n\nGuruhni tanlang:",reply_markup=InlineKeyboardMarkup ( kb) if kb else v9_teacher_keyboard (  ) )

    if txt=="📚 Darslarim" and role=="student":
        STATE.pop ( u.id,None)
        rows=all_ ( "SELECT g.id,g.title FROM v9_groups g JOIN v9_group_members m ON m.group_id=g.id WHERE m.user_id=? AND m.is_active=1 AND g.is_active=1", ( u.id, ) )
        kb=[[InlineKeyboardButton ( "📚 "+r["title"][:45],callback_data=f"v9:lessons:{r['id']}" ) ] for r in rows]
        return await msg.reply_text ( "📚 DARSLARIM\n\nGuruhni tanlang:",reply_markup=InlineKeyboardMarkup ( kb) if kb else v9_student_keyboard (  ) )

    if txt=="⭐ Ballarim" and role=="student":
        STATE.pop ( u.id,None)
        rows=all_ ( "SELECT g.title,p.points FROM v9_points p JOIN v9_groups g ON g.id=p.group_id WHERE p.user_id=? ORDER BY p.points DESC", ( u.id, ) )
        body="\n".join ( f"🏆 {r['title']}: {r['points']} ball" for r in rows) or "Hozircha ball yo‘q."
        return await msg.reply_text ( "⭐ BALLARIM\n\n"+body,reply_markup=v9_student_keyboard (  ) )

    if txt=="🤖 AI Ustoz" and role=="student":
        active=st if st.get ( "mode" ) =="v9_ai_lesson" else None
        if active:
            l=one ( "SELECT title FROM v9_lessons WHERE id=?", ( active["lesson_id"], ) )
            return await msg.reply_text ( f"🤖 AI Ustoz faol: {l['title'] if l else 'dars'}\nSavolingizni yozavering.",reply_markup=v9_student_keyboard (  ) )
        rows=all_ ( """SELECT l.id,l.title FROM v9_lessons l JOIN v9_group_members m ON m.group_id=l.group_id
                     WHERE m.user_id=? AND m.is_active=1 AND l.status='published' ORDER BY l.id DESC LIMIT 20""", ( u.id, ) )
        kb=[[InlineKeyboardButton ( "🤖 "+r["title"][:45],callback_data=f"v9:learn:{r['id']}" ) ] for r in rows]
        return await msg.reply_text ( "🤖 Qaysi dars bo‘yicha AI Ustoz kerak?",reply_markup=InlineKeyboardMarkup ( kb) if kb else v9_student_keyboard (  ) )

    # Yangi dars: nom -> material -> AI rejimi
    if mode=="v9_lesson_title":
        if not msg.text or len ( txt ) <2:return await msg.reply_text ( "Dars nomini yozing.")
        st["title"]=txt[:150];st["mode"]="v9_lesson_material";STATE[u.id]=st
        return await msg.reply_text(
            "2/3 — Dars materialini yuboring.\n\n"
            "📝 Oddiy matn\n📄 PDF\n🖼 Rasm yoki skrinshot\n\n"
            "Veritas materialni o‘qib, talabaga o‘rgatish uchun tayyorlaydi.",
            reply_markup=v9_teacher_keyboard (  ) )

    if mode=="v9_lesson_material":
        kind=""; file_id=""; file_name=""; mime=""; extracted=""
        try:
            if msg.text:
                kind="text";extracted=txt
            elif msg.document and (msg.document.mime_type or "" ) .lower (  ) =="application/pdf":
                kind="pdf";file_id=msg.document.file_id;file_name=msg.document.file_name or "dars.pdf";mime="application/pdf"
                tg=await ctx.bot.get_file ( file_id ) ;raw=bytes ( await tg.download_as_bytearray (  ) )
                extracted=v9_extract_pdf ( raw)
                if not extracted.strip (  ) :
                    return await msg.reply_text ( "⚠️ Bu PDFdan matn olinmadi. Agar skan PDF bo‘lsa, sahifalarni rasm qilib yuboring.")
            elif msg.photo or (msg.document and (msg.document.mime_type or "" ) .lower (  ) .startswith ( "image/" )  ) :
                obj=msg.photo[-1] if msg.photo else msg.document
                kind="image";file_id=obj.file_id;file_name=getattr ( obj,"file_name",None) or "screenshot.jpg";mime=getattr ( obj,"mime_type",None) or "image/jpeg"
                tg=await ctx.bot.get_file ( file_id ) ;raw=bytes ( await tg.download_as_bytearray (  ) )
                if not OPENAI_API_KEY:return await msg.reply_text ( "⚠️ Rasmni o‘qish uchun OPENAI_API_KEY kerak.")
                extracted=await asyncio.to_thread ( _openai_image_response_sync,raw,mime,"Rasmdagi darslik matni, formulalar, jadval va asosiy ma’lumotlarni aniq ko‘chirib/tavsiflab bering. Hech narsa uydirmang.")
            else:
                return await msg.reply_text ( "PDF, rasm/skrinshot yoki yozma dars yuboring.")
        except Exception as e:
            log.exception ( "V9 material: %s",e)
            return await msg.reply_text ( "⚠️ Materialni o‘qishda xato bo‘ldi. Boshqa fayl yoki matn bilan urinib ko‘ring.")
        st["material"]={"kind":kind,"file_id":file_id,"file_name":file_name,"mime":mime,"text":extracted[:45000]}
        st["mode"]="v9_lesson_mode";STATE[u.id]=st
        kb=InlineKeyboardMarkup ( [
          [InlineKeyboardButton ( "🔒 Faqat darslikdan",callback_data="v9:lessonmode:material_only" ) ],
          [InlineKeyboardButton ( "🧠 Darslik + AI tushuntirishi",callback_data="v9:lessonmode:ai_plus" ) ]])
        return await msg.reply_text ( f"✅ Material qabul qilindi ({len ( extracted ) } belgi ) .\n\n3/3 — AI qanday o‘qitsin?",reply_markup=kb)

    if mode=="v9_ai_lesson" and msg.text:
        lid=int ( st["lesson_id"] ) ;l=one ( "SELECT * FROM v9_lessons WHERE id=? AND status='published'", ( lid, ) )
        if not l:return
        material=v9_lesson_context ( lid)
        answer=await v9_ai_teach ( l,material,txt)
        ctx.user_data["v9_consumed_message_id"]=msg.message_id
        return await msg.reply_text ( answer[:4000],reply_markup=v9_student_keyboard (  ) )
    if mode=="v9_new_group_title":
        if not msg.text or len ( msg.text.strip (  )  ) <2:return await msg.reply_text ( "Guruh nomini matn qilib yozing.")
        st["title"]=msg.text.strip (  ) [:120];st["mode"]="v9_new_group_subject";STATE[u.id]=st
        return await msg.reply_text ( "📖 Endi fan nomini yozing.\nMasalan: Matematika")
    if mode=="v9_new_group_subject":
        if not msg.text or len ( msg.text.strip (  )  ) <2:return await msg.reply_text ( "Fan nomini matn qilib yozing.")
        import secrets
        prof=one ( "SELECT institution_type FROM v9_profiles WHERE user_id=?", ( u.id, )  ) ;inst=prof["institution_type"] if prof else "school"
        title=st.get ( "title","Yangi guruh" ) ;subject=msg.text.strip (  ) [:100];gid=None
        for _ in range ( 10 ) :
            code="V9-"+secrets.token_hex ( 3 ) .upper ( )
            try:
                with db ( ) as c:gid=c.execute ( "INSERT INTO v9_groups ( teacher_id,institution_type,title,subject,join_code,is_active,created_at) VALUES ( ?,?,?,?,?,1,? ) ", ( u.id,inst,title,subject,code,now (  )  )  ) .lastrowid
                break
            except sqlite3.IntegrityError:pass
        if not gid:return await msg.reply_text ( "Guruh kodi yaratilmadi. Qayta urinib ko‘ring.")
        STATE.pop ( u.id,None)
        return await msg.reply_text ( f"✅ GURUH YARATILDI\n\n📚 {title}\n📖 {subject}\n🔑 Kod: {code}\n\nTalabalarga shu kodni bering.",reply_markup=InlineKeyboardMarkup ( [[InlineKeyboardButton ( "📚 Guruhni ochish",callback_data=f"v9:group:{gid}" ) ]] ) )
    if mode=="v9_join_group":
        if not msg.text:return await msg.reply_text ( "Ustoz bergan guruh kodini yozing.")
        code=msg.text.strip (  ) .upper (  ) ;g=one ( "SELECT id,title,teacher_id FROM v9_groups WHERE upper ( join_code ) =? AND is_active=1", ( code, ) )
        if not g:return await msg.reply_text ( "❌ Bunday faol guruh kodi topilmadi.")
        if int ( g["teacher_id"] ) ==u.id:STATE.pop ( u.id,None ) ;return await msg.reply_text ( "Siz bu guruhning ustozisiz.")
        with db ( ) as c:
            c.execute ( "INSERT INTO v9_group_members ( group_id,user_id,joined_at,is_active) VALUES ( ?,?,?,1) ON CONFLICT ( group_id,user_id) DO UPDATE SET is_active=1", ( g["id"],u.id,now (  )  ) )
            c.execute ( "INSERT INTO v9_points ( group_id,user_id,points,updated_at) VALUES ( ?,?,0,?) ON CONFLICT ( group_id,user_id) DO NOTHING", ( g["id"],u.id,now (  )  ) )
        STATE.pop ( u.id,None)
        return await msg.reply_text ( f"✅ {g['title']} guruhiga qo‘shildingiz.",reply_markup=InlineKeyboardMarkup ( [[InlineKeyboardButton ( "📚 Guruhni ochish",callback_data=f"v9:group:{g['id']}" ) ]] ) )
# =========================================================
# VERITAS V9 — END
# =========================================================

def main_menu_markup ( uid ) :
    kb=[
      [InlineKeyboardButton ( "👤 Profil",callback_data="me" ) ,InlineKeyboardButton ( "⭐ Hisob",callback_data="wallet" ) ],
      [InlineKeyboardButton ( "🎁 Gift",callback_data="gifts" ) ,InlineKeyboardButton ( "💎 Premium",callback_data="premium" ) ],
      [InlineKeyboardButton ( "🏘 Guruhlarim",callback_data="mygroups" ) ],
      [InlineKeyboardButton ( "🌐 Global aktiv",callback_data="globalactive" ) ],
      [InlineKeyboardButton ( "🔎 A’zo profili",callback_data="profilefind" ) ,InlineKeyboardButton ( "💠 Qadr TOP",callback_data="qadrtop" ) ],
      [InlineKeyboardButton ( "🤖 Veritas AI",callback_data="ai_private" ) ],
      [InlineKeyboardButton ( "🧩 AI Rebus",callback_data="rebus:start" ) ],
      [InlineKeyboardButton ( "📚 Vasatiya kutubxonasi",callback_data="library" ) ,InlineKeyboardButton ( "📜 Sahih Hadislar",callback_data="hadith" ) ],
      [InlineKeyboardButton ( "📨 Egaga xabar qoldirish",callback_data="owner:message" ) ],
      [InlineKeyboardButton ( "ℹ️ Veritas haqida",callback_data="about" ) ],
    ]
    if is_super ( uid ):
        kb.append ( [InlineKeyboardButton ( "👑 Super Ega",callback_data="super" ) ])
    return InlineKeyboardMarkup ( kb)

def back_markup ( target="home" ) :
    return InlineKeyboardMarkup ( [[InlineKeyboardButton ( "⬅️ Orqaga",callback_data=target ) ,InlineKeyboardButton ( "🏠 Bosh menyu",callback_data="home" ) ]])

def super_menu_markup (  ) :
    return InlineKeyboardMarkup ( [
        [InlineKeyboardButton ( "👥 Kabinetlar",callback_data="cabs:0" ) ],
        [InlineKeyboardButton ( "🛡 Barcha adminlar",callback_data="alladmins:0" ) ],
        [InlineKeyboardButton ( "🏘 Bot ishlayotgan guruhlar",callback_data="botgroups:0" ) ],
        [InlineKeyboardButton ( "⬅️ Orqaga",callback_data="home" ) ,InlineKeyboardButton ( "🏠 Bosh menyu",callback_data="home" ) ]
    ])

def user_total_stats ( uid ) :
    # GLOBAL: foydalanuvchining Veritas ishlayotgan barcha guruhlaridagi natija jamlanadi.
    r=one ( "SELECT COALESCE ( SUM ( xp ) ,0) xp,COALESCE ( SUM ( messages ) ,0) messages FROM members WHERE user_id=?", ( uid, ) )
    return (int ( r["xp"] ) ,int ( r["messages"] ) ) if r else (0,0)

def activity_degree ( lvl ) :
    if lvl >= 251: return "🦅 Afsona"
    if lvl >= 151: return "⚜️ Ustoz darajasi"
    if lvl >= 101: return "🌟 Veritas faxri"
    if lvl >= 76: return "👑 Elita a’zo"
    if lvl >= 51: return "🏆 Faollar sardori"
    if lvl >= 31: return "💎 Yuksak faol"
    if lvl >= 21: return "🔥 Super Aktiv"
    if lvl >= 11: return "✨ Ilmga intiluvchi"
    if lvl >= 6: return "📖 Faol a’zo"
    return "🌱 Ilm izlovchi"

def content_contributions ( uid ) :
    b=one ( "SELECT COUNT ( *) n FROM library_books WHERE added_by=? AND status='approved'", ( uid, ) )
    h=one ( "SELECT COUNT ( *) n FROM hadiths WHERE added_by=? AND status='approved'", ( uid, ) )
    return int ( b["n"] if b else 0 ),int ( h["n"] if h else 0 )

def knowledge_medal ( books,hadiths ) :
    total=int ( books ) +int ( hadiths )
    if total >=100: return "🏆 Ilm fidoyisi"
    if total >=50: return "🌟 Ilm elchisi"
    if total >=20: return "🏅 Ilm tarqatuvchi"
    if total >=1: return "📚 Ilm xizmatida"
    return "—"

def bot_roles ( uid ) :
    roles=[]
    if uid in SUPER_OWNERS: roles.append ( "👑 Super Ega" )
    elif is_super_admin ( uid ): roles.append ( "🛡 Super Admin" )
    if one ( "SELECT 1 FROM library_admins WHERE user_id=?", ( uid, ) ): roles.append ( "📚 Kutubxona admini" )
    if one ( "SELECT 1 FROM hadith_admins WHERE user_id=?", ( uid, ) ): roles.append ( "📜 Hadis admini" )
    vg=one ( "SELECT COUNT ( *) n FROM vadmins WHERE user_id=?", ( uid, ) )
    if vg and int ( vg["n"] ) >0: roles.append ( f"🛡 Veritas admini ({int ( vg['n'] )} guruh ) " )
    return ", ".join ( roles ) if roles else "A’zo"

def global_profile_text ( u ) :
    xp,msgs=user_total_stats ( u.id )
    lvl=level ( xp )
    books,hadiths=content_contributions ( u.id )
    ai_until=ai_user_until ( u.id )
    ai_status=( "👑 Cheksiz (Super boshqaruv ) " if is_super ( u.id ) else ( "✅ FAOL — "+fmt_until ( ai_until ) if ai_until>now ( ) else "❌ YO‘Q" ) )
    return (
        f"👤 {u.full_name}\n"
        f"🆔 {u.id}\n"
        f"🛡 Botdagi roli: {bot_roles ( u.id )}\n"
        f"⭐ Kredit: {wallet ( u.id )}\n"
        f"🌐 Umumiy XP: {xp}\n"
        f"💬 Umumiy xabarlar: {msgs}\n"
        f"📈 Level: {lvl}\n"
        f"🔥 Aktivlik darajasi: {activity_degree ( lvl )}\n"
        f"📚 Qo‘shgan kitoblari: {books} ta\n"
        f"📜 Qo‘shgan hadislari: {hadiths} ta\n"
        f"🏅 Ilm medali: {knowledge_medal ( books,hadiths )}\n\n"
        f"🤖 AI Premium: {ai_status}"
    )

def global_active_rows ( limit=10 ) :
    # Global TOP faqat haqiqiy foydalanuvchilar uchun.
    # Telegram botlari/channel senderlari bazada users sifatida saqlanib qolgan bo‘lsa ham,
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
    if not rows: return "🌐 VERITAS — GLOBAL AKTIV\n\nHozircha ma’lumot yo‘q."
    lines=[]
    medals=["🥇","🥈","🥉"]
    for i,r in enumerate ( rows ) :
        mark=medals[i] if i<3 else f"{i+1}."
        lvl=level ( int ( r["xp"] or 0 ) )
        lines.append ( f"{mark} {display_name_row ( r )} — {int ( r['messages'] or 0 )} xabar | LVL {lvl} {activity_degree ( lvl )}" )
    return "🌐 VERITAS — GLOBAL AKTIV TOP 10\n\n"+"\n".join ( lines )+"\n\n👥 Faqat foydalanuvchilar reytingi.\n📊 Barcha guruhlardagi aktivlik jamlangan."

def fmt_until ( ts ) :
    if not ts: return "—"
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
    # Bir foydalanuvchiga faqat bir marta. Transaction race-conditionni ham to‘sadi.
    ts=now ( )
    with db ( ) as c:
        try:
            c.execute ( "INSERT INTO ai_user_trials ( user_id,claimed_at) VALUES ( ?,? ) ", ( uid,ts ) )
        except sqlite3.IntegrityError:
            return 0
        old=c.execute ( "SELECT paid_until FROM ai_user_subscriptions WHERE user_id=?", ( uid, ) ).fetchone ( )
        base=max ( ts,int ( old["paid_until"] ) if old else 0 )
        until=base+30*86400
        c.execute ( "INSERT INTO ai_user_subscriptions ( user_id,paid_until,updated_at) VALUES ( ?,?,?) "
                    "ON CONFLICT ( user_id) DO UPDATE SET paid_until=excluded.paid_until,updated_at=excluded.updated_at",
                    ( uid,until,ts ) )
    return until

def claim_ai_group_trial ( chat_id,uid ) :
    # Har bir guruhga faqat bir marta 30 kun bepul.
    ts=now ( )
    with db ( ) as c:
        try:
            c.execute ( "INSERT INTO ai_group_trials ( chat_id,claimed_at,claimed_by) VALUES ( ?,?,? ) ", ( chat_id,ts,uid ) )
        except sqlite3.IntegrityError:
            return 0
        old=c.execute ( "SELECT paid_until FROM ai_group_subscriptions WHERE chat_id=?", ( chat_id, ) ).fetchone ( )
        base=max ( ts,int ( old["paid_until"] ) if old else 0 )
        until=base+30*86400
        c.execute ( "INSERT INTO ai_group_subscriptions ( chat_id,payer_id,paid_until,source,updated_at) VALUES ( ?,?,?,?,?) "
                    "ON CONFLICT ( chat_id) DO UPDATE SET payer_id=excluded.payer_id,paid_until=excluded.paid_until,"
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
    k= ( scope_id,uid ) ; t=time.time ( ); last=AI_RATE_CACHE.get ( k,0 )
    if t-last < seconds: return False
    AI_RATE_CACHE[k]=t; return True

def ai_group_menu ( chat_id,uid ) :
    kb=[]
    if not ai_group_trial_used ( chat_id ):
        kb.append ( [InlineKeyboardButton ( "🎁 30 kun BEPUL",callback_data=f"aigtrial:{chat_id}" ) ] )
    else:
        kb.append ( [InlineKeyboardButton ( "⭐ 100 — 30 kun",callback_data=f"aigbuy:{chat_id}:30" ) ] )
    if is_super ( uid ):
        kb += [
          [InlineKeyboardButton ( "👑 Bepul 1 kun",callback_data=f"aigfree:{chat_id}:1" ) ,InlineKeyboardButton ( "👑 7 kun",callback_data=f"aigfree:{chat_id}:7" ) ,InlineKeyboardButton ( "👑 30 kun",callback_data=f"aigfree:{chat_id}:30" ) ],
          [InlineKeyboardButton ( "⛔ AI ni o‘chirish",callback_data=f"aigoff:{chat_id}" ) ]
        ]
    return InlineKeyboardMarkup ( kb )


def is_library_admin ( uid ) :
    return is_super ( uid ) or bool ( one ( "SELECT 1 FROM library_admins WHERE user_id=?", ( uid, )  ) )

def lib_lang_name ( code ) :
    return {"uz":"🇺🇿 O‘zbekcha","ru":"🇷🇺 Русский","en":"🇬🇧 English"}.get ( code,code)

def profile_like_count ( uid ) :
    r=one ( "SELECT COUNT ( *) n FROM profile_likes WHERE target_user_id=?", ( uid, ) )
    return int ( r["n"] if r else 0 )


def profile_liked_by ( target_uid,voter_uid ) :
    return bool ( one ( "SELECT 1 FROM profile_likes WHERE target_user_id=? AND voter_user_id=?", ( target_uid,voter_uid ) ) )


def profile_dislike_count ( uid ) :
    r=one ( "SELECT COUNT ( *) n FROM profile_dislikes WHERE target_user_id=?", ( uid, ) )
    return int ( r["n"] if r else 0 )


def profile_disliked_by ( target_uid,voter_uid ) :
    return bool ( one ( "SELECT 1 FROM profile_dislikes WHERE target_user_id=? AND voter_user_id=?", ( target_uid,voter_uid ) ) )


def public_profile_text ( uid ) :
    r=one ( "SELECT user_id,username,first_name FROM users WHERE user_id=?", ( uid, ) )
    if not r: return None
    xp,msgs=user_total_stats ( uid )
    lvl=level ( xp )
    shown_lvl="+99" if uid in SUPER_OWNERS else str ( lvl)
    books,hadiths=content_contributions ( uid )
    ai_until=ai_user_until ( uid )
    ai_status=( "👑 Cheksiz (Super boshqaruv ) " if is_super ( uid ) else ( "✅ FAOL — "+fmt_until ( ai_until ) if ai_until>now ( ) else "❌ YO‘Q" ) )
    name=r["first_name"] or ( "@"+r["username"] if r["username"] else f"ID {uid}" )
    username= ( " @"+r["username"]) if r["username"] else ""
    return (
        f"👤 {name}{username}\n"
        f"🆔 {uid}\n"
        f"🛡 Botdagi roli: {bot_roles ( uid )}\n"
        f"⭐ Kredit: {wallet ( uid )}\n"
        f"🤖 AI Premium: {ai_status}\n\n"
        f"🌐 Umumiy XP: {xp}\n"
        f"💬 Umumiy xabarlar: {msgs}\n"
        f"📈 Level: {shown_lvl}\n"
        f"🔥 Aktivlik darajasi: {activity_degree ( lvl )}\n"
        f"📚 Qo‘shgan kitoblari: {books} ta\n"
        f"📜 Qo‘shgan hadislari: {hadiths} ta\n"
        f"🏅 Ilm medali: {knowledge_medal ( books,hadiths )}\n"
        f"💠 Qadr: {profile_like_count ( uid )}\n"
        f"⚖️ E’tiroz: {profile_dislike_count ( uid )}"
    )


def qadr_top_text ( limit=10 ) :
    rows=all_ ( """SELECT u.user_id,u.first_name,u.username,COUNT ( pl.voter_user_id) qadr
                    FROM profile_likes pl JOIN users u ON u.user_id=pl.target_user_id
                    GROUP BY u.user_id,u.first_name,u.username
                    ORDER BY qadr DESC,u.user_id ASC LIMIT ?""", ( int ( limit ) , ) )
    if not rows:
        return "🏆 VERITAS — QADR TOP 10\n\nHozircha Qadr berilmagan."
    medals=["🥇","🥈","🥉"]
    lines=["🏆 VERITAS — QADR TOP 10",""]
    for i,r in enumerate ( rows,1 ) :
        mark=medals[i-1] if i<=3 else f"{i}."
        name=r["first_name"] or ( ( "@"+r["username"]) if r["username"] else f"ID {r['user_id']}")
        lines.append ( f"{mark} {name} — 💠 {int ( r['qadr'] ) } Qadr")
    return "\n".join ( lines)


def public_profile_markup ( target_uid,viewer_uid ) :
    liked=profile_liked_by ( target_uid,viewer_uid )
    disliked=profile_disliked_by ( target_uid,viewer_uid )
    like_text= ( "↩️ Qadrni olish" if liked else "💠 Qadr" ) +f" · {profile_like_count ( target_uid )}"
    dislike_text= ( "↩️ E’tirozni olish" if disliked else "⚖️ E’tiroz" ) +f" · {profile_dislike_count ( target_uid )}"
    kb=[]
    # Like/Dizlayk tugmalari har bir profilda ko‘rinadi.
    # O‘z profilida ham tugmalar ko‘rinadi, ammo callback ovoz berishni bloklaydi.
    kb.append ( [
        InlineKeyboardButton ( like_text,callback_data=f"plike:{target_uid}" ),
        InlineKeyboardButton ( dislike_text,callback_data=f"pdislike:{target_uid}" )
    ] )
    kb.append ( [InlineKeyboardButton ( "🔎 Boshqa a’zoni topish",callback_data="profilefind" )] )
    kb.append ( [InlineKeyboardButton ( "⬅️ Orqaga",callback_data="home" ),InlineKeyboardButton ( "🏠 Bosh menyu",callback_data="home" )] )
    return InlineKeyboardMarkup ( kb )


async def send_public_profile ( ctx,chat_id,target_uid,viewer_uid,old_message=None ) :
    text=public_profile_text ( target_uid )
    if not text:
        if old_message:
            return await old_message.reply_text ( "❌ A’zo topilmadi." )
        return await ctx.bot.send_message ( chat_id,"❌ A’zo topilmadi." )
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
      [InlineKeyboardButton ( "🤖 AI Kitob qidirish",callback_data="libaisearch" ) ],
      [InlineKeyboardButton ( "🔎 Oddiy qidirish",callback_data="libsearch" ) ,InlineKeyboardButton ( "🗂 Kategoriyalar",callback_data="libcats:0" ) ],
      [InlineKeyboardButton ( "🆕 Yangi kitoblar",callback_data="libnew:0" ) ,InlineKeyboardButton ( "❤️ Sevimlilar",callback_data="libfav:0" ) ],
      [InlineKeyboardButton ( "🇺🇿",callback_data="liblang:uz:0" ) ,InlineKeyboardButton ( "🇷🇺",callback_data="liblang:ru:0" ) ,InlineKeyboardButton ( "🇬🇧",callback_data="liblang:en:0" ) ],
    ]
    if is_library_admin ( uid ) :
        kb.append ( [InlineKeyboardButton ( "➕ Kitob qo‘shish",callback_data="libadd" ) ])
    kb.append ( [InlineKeyboardButton ( "⬅️ Orqaga",callback_data="home" ) ,InlineKeyboardButton ( "🏠 Bosh menyu",callback_data="home" ) ])
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
    return (f"📖 {r['title']}\n"
            f"✍️ Muallif: {r['author'] or '—'}\n"
            f"🌐 Til: {lib_lang_name ( r['lang'] ) }\n"
            f"🗂 Kategoriya: {', '.join ( cats) if cats else '—'}\n"
            f"👤 Qo‘shgan: {added}\n"
            f"👁 Ko‘rildi: {r['views']} | ⬇️ Yuklandi: {r['downloads']}\n\n"
            f"{r['description'] or 'Tavsif mavjud emas.'}")

def library_book_markup ( uid,book_id,back="library" ) :
    fav=bool ( one ( "SELECT 1 FROM library_favorites WHERE user_id=? AND book_id=?", ( uid,book_id )  ) )
    r=one ( "SELECT pdf_file_id,audio_file_id,book_file_id,book_format FROM library_books WHERE id=?", ( book_id, ) )
    kb=[]
    row=[]
    if r and (r["book_file_id"] or r["pdf_file_id"] ) : row.append ( InlineKeyboardButton ( "📥 Kitobni olish",callback_data=f"libfile:{book_id}" ) )
    if r and r["audio_file_id"]: row.append ( InlineKeyboardButton ( "🎧 Audio",callback_data=f"libaudio:{book_id}" ) )
    if row: kb.append ( row)
    if r and r["pdf_file_id"]:
        kb.append ( [InlineKeyboardButton ( "🧠 Test tuzish",callback_data=f"libquiz:{book_id}" ) ])
        kb.append ( [InlineKeyboardButton ( "🌐 AI Tarjima",callback_data=f"libtranslate:{book_id}" ) ])
    kb.append ( [InlineKeyboardButton ( "💔 Sevimlidan olish" if fav else "❤️ Sevimliga",callback_data=f"libfavtoggle:{book_id}" ) ])
    if is_library_admin ( uid ) :
        kb.append ( [InlineKeyboardButton ( "✏️ Tahrirlash",callback_data=f"libedit:{book_id}" ) ,InlineKeyboardButton ( "🗑 O‘chirish",callback_data=f"libdelask:{book_id}" ) ])
    kb.append ( [InlineKeyboardButton ( "⬅️ Kutubxona",callback_data=back ) ,InlineKeyboardButton ( "🏠 Bosh menyu",callback_data="home" ) ])
    return InlineKeyboardMarkup ( kb)

async def library_show_book ( q,ctx,book_id,back="library" ) :
    r=one ( "SELECT * FROM library_books WHERE id=? AND status='approved'", ( book_id, ) )
    if not r: return await q.edit_message_text ( "❌ Kitob topilmadi.",reply_markup=back_markup ( "library" ) )
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
        kb.append ( [InlineKeyboardButton ( "📖 "+title,callback_data=f"libbook:{r['id']}" ) ])
    nav=[]
    if page>0: nav.append ( InlineKeyboardButton ( "◀️",callback_data=f"{prefix}:{extra+':' if extra else ''}{page-1}" ) )
    if (page+1 ) *per<total: nav.append ( InlineKeyboardButton ( "▶️",callback_data=f"{prefix}:{extra+':' if extra else ''}{page+1}" ) )
    if nav: kb.append ( nav)
    kb.append ( [InlineKeyboardButton ( "⬅️ Kutubxona",callback_data="library" ) ,InlineKeyboardButton ( "🏠 Bosh menyu",callback_data="home" ) ])
    return InlineKeyboardMarkup ( kb)


def _compact ( s, n=180 ) :
    return re.sub ( r"\s+"," ",str ( s or "" )  ) .strip (  ) [:n]

def _ids_from_ai ( text, allowed ) :
    found=[]
    for x in re.findall ( r"\b\d+\b", text or "" ) :
        i=int ( x)
        if i in allowed and i not in found:
            found.append ( i)
    return found[:8]

async def ai_library_search ( query ) :
    """AI may rank only rows that actually exist in Vasatiya library."""
    rows=all_ ( """SELECT b.id,b.title,b.author,b.description,b.lang,
                       COALESCE ( GROUP_CONCAT ( c.name, ', ' ) ,'') cats
                FROM library_books b
                LEFT JOIN library_book_categories bc ON bc.book_id=b.id
                LEFT JOIN library_categories c ON c.id=bc.category_id
                WHERE b.status='approved'
                GROUP BY b.id ORDER BY b.id DESC LIMIT 1200""")
    if not rows: return []
    q= ( query or "" ) .strip (  ) .lower ( )
    words=[w for w in re.findall ( r"[\wʻ’'-]+",q,re.U) if len ( w ) >2]
    scored=[]
    for r in rows:
        hay=" ".join ( [r["title"] or "",r["author"] or "",r["description"] or "",r["cats"] or ""] ) .lower ( )
        score=sum ( 5 if w in (r["title"] or "" ) .lower ( ) else 2 if w in hay else 0 for w in words)
        if score: scored.append (  ( score,r ) )
    scored.sort ( key=lambda x: ( -x[0],-int ( x[1]["id"] )  ) )
    # Give AI a real catalog, never open web/external books.
    pool=[x[1] for x in scored[:120]]
    if len ( pool ) <80:
        seen={int ( r["id"]) for r in pool}
        for r in rows:
            if int ( r["id"]) not in seen:
                pool.append ( r ) ; seen.add ( int ( r["id"] ) )
            if len ( pool ) >=160: break
    if OPENAI_API_KEY:
        catalog="\n".join(
            f"ID={r['id']} | { _compact ( r['title'],90) } | { _compact ( r['author'],55) } | "
            f"{ _compact ( r['cats'],55) } | { _compact ( r['description'],120) }"
            for r in pool
        )
        prompt=(
            "Vazifa: foydalanuvchi so‘roviga mos kitoblarni FAQAT quyidagi Vasatiya katalogidan tanla. "
            "Katalogda yo‘q kitobni uydirma. Eng mos 1-8 ta kitob ID sini moslik tartibida qaytar. "
            "Javob formati faqat vergul bilan IDlar, masalan: 12,5,91. Mos kitob bo‘lmasa NONE.\n\n"
            f"So‘rov: {query}\n\nKATALOG:\n{catalog}"
        )
        try:
            ans=await asyncio.to_thread ( _openai_response_sync,prompt)
            ids=_ids_from_ai ( ans,{int ( r["id"]) for r in pool})
            if ids:
                byid={int ( r["id"] ) :r for r in rows}
                return [byid[i] for i in ids if i in byid]
        except Exception:
            log.exception ( "AI library search failed; lexical fallback used")
    return [r for _,r in scored[:8]]

async def ai_hadith_search ( query ) :
    """AI may rank only hadiths stored in Veritas hadith DB."""
    rows=all_ ( """SELECT id,collection,number,translation,explanation,source
                 FROM hadiths WHERE status='approved'
                 ORDER BY id DESC LIMIT 1600""")
    if not rows: return []
    q= ( query or "" ) .strip (  ) .lower ( )
    words=[w for w in re.findall ( r"[\wʻ’'-]+",q,re.U) if len ( w ) >2]
    scored=[]
    for r in rows:
        hay=" ".join ( [r["collection"] or "",str ( r["number"] ) ,r["translation"] or "",r["explanation"] or "",r["source"] or ""] ) .lower ( )
        score=sum ( 3 if w in hay else 0 for w in words)
        if score: scored.append (  ( score,r ) )
    scored.sort ( key=lambda x: ( -x[0],-int ( x[1]["id"] )  ) )
    pool=[x[1] for x in scored[:140]]
    if len ( pool ) <100:
        seen={int ( r["id"]) for r in pool}
        for r in rows:
            if int ( r["id"]) not in seen:
                pool.append ( r ) ; seen.add ( int ( r["id"] ) )
            if len ( pool ) >=180: break
    if OPENAI_API_KEY:
        catalog="\n".join(
            f"ID={r['id']} | { _compact ( r['collection'],35) } {r['number']} | "
            f"{ _compact ( r['translation'],150) } | { _compact ( r['explanation'],90) }"
            for r in pool
        )
        prompt=(
            "Vazifa: foydalanuvchi mavzusiga mos hadislarni FAQAT quyidagi Veritas hadis bazasidan tanla. "
            "Tashqaridan hadis keltirma, raqam yoki matn uydirma. Eng mos 1-8 ta IDni qaytar. "
            "Format faqat IDlar vergul bilan. Mos kelmasa NONE.\n\n"
            f"So‘rov: {query}\n\nHADIS BAZASI:\n{catalog}"
        )
        try:
            ans=await asyncio.to_thread ( _openai_response_sync,prompt)
            ids=_ids_from_ai ( ans,{int ( r["id"]) for r in pool})
            if ids:
                byid={int ( r["id"] ) :r for r in rows}
                return [byid[i] for i in ids if i in byid]
        except Exception:
            log.exception ( "AI hadith search failed; lexical fallback used")
    return [r for _,r in scored[:8]]

async def send_ai_library_results ( msg, query ) :
    rows=await ai_library_search ( query)
    if not rows:
        return await msg.reply_text(
            "🤖 Vasatiya AI bu so‘rovga mos kitobni o‘z kutubxonamizdan topmadi.\n"
            "Boshqa kalit so‘z yoki mavzu bilan urinib ko‘ring.",
            reply_markup=library_home_markup ( msg.from_user.id)
        )
    kb=[]
    for r in rows[:8]:
        title=_compact ( r["title"],42)
        author=_compact ( r["author"],24)
        label=f"📖 {title}" + (f" — {author}" if author else "")
        kb.append ( [InlineKeyboardButton ( label,callback_data=f"libbook:{r['id']}" ) ])
    kb.append ( [InlineKeyboardButton ( "🤖 Yana AI qidiruv",callback_data="libaisearch" ) ,
               InlineKeyboardButton ( "📚 Kutubxona",callback_data="library" ) ])
    return await msg.reply_text(
        f"🤖 VASATIYA AI QIDIRUV\n\n🔎 So‘rov: {query}\n"
        f"📚 Faqat Vasatiya kutubxonasidagi kitoblardan {len ( rows[:8] ) } ta mos natija:",
        reply_markup=InlineKeyboardMarkup ( kb)
    )

async def send_ai_hadith_results ( msg, query ) :
    rows=await ai_hadith_search ( query)
    if not rows:
        return await msg.reply_text(
            "🤖 AI bu mavzuga mos hadisni faqat biz qo‘shgan hadislar orasidan topmadi.",
            reply_markup=back_markup ( "hadith")
        )
    kb=[]
    for r in rows[:8]:
        kb.append ( [InlineKeyboardButton(
            f"📜 {r['collection']} — {r['number']}",
            callback_data=f"hshow:{r['id']}"
        )])
    kb.append ( [InlineKeyboardButton ( "🤖 Yana AI qidiruv",callback_data="hadaisearch" ) ,
               InlineKeyboardButton ( "📜 Hadislar",callback_data="hadith" ) ])
    return await msg.reply_text(
        f"🤖 AI HADIS QIDIRUV\n\n🔎 Mavzu: {query}\n"
        f"📜 Faqat Veritas bazasidagi hadislardan {len ( rows[:8] ) } ta mos natija:",
        reply_markup=InlineKeyboardMarkup ( kb)
    )

async def library_private_input ( update,ctx ) :
    if update.effective_chat.type!="private": return
    uid=update.effective_user.id; st=STATE.get ( uid)
    if st: ctx.user_data["workflow_message_id"]=update.effective_message.message_id
    if st and str ( st.get ( "mode","" )  ) .startswith ( "had_" ) :
        return await hadith_private_input ( update,ctx)
    if st and st.get ( "mode" ) =="profile_find":
        msg=update.effective_message
        if not msg.text: return await msg.reply_text ( "A’zoning @username yoki Telegram ID sini yozing.")
        value=msg.text.strip (  ) ; target_uid=0
        if value.isdigit (  ) :
            target_uid=int ( value)
        elif value.startswith ( "@" ) :
            r=one ( "SELECT user_id FROM users WHERE lower ( username ) =lower ( ? ) ", ( value[1:], ) )
            target_uid=int ( r["user_id"]) if r else 0
        if not target_uid or not one ( "SELECT 1 FROM users WHERE user_id=?", ( target_uid, )  ) :
            return await msg.reply_text ( "❌ Veritas bazasida bunday a’zo topilmadi.")
        STATE.pop ( uid,None)
        return await send_public_profile ( ctx,msg.chat.id,target_uid,uid)

    if st and st.get ( "mode" ) =="lib_ai_search":
        msg=update.effective_message
        if not msg.text: return await msg.reply_text ( "🔎 Qidirayotgan kitob mavzusini matn qilib yozing.")
        query=msg.text.strip ( )
        if len ( query ) <2: return await msg.reply_text ( "So‘rov juda qisqa.")
        STATE.pop ( uid,None)
        await msg.reply_text ( "🤖 Vasatiya AI kutubxonamiz ichidan qidirmoqda...")
        return await send_ai_library_results ( msg,query)

    if st and st.get ( "mode" ) =="had_ai_search":
        msg=update.effective_message
        if not msg.text: return await msg.reply_text ( "🔎 Hadis mavzusini matn qilib yozing.")
        query=msg.text.strip ( )
        if len ( query ) <2: return await msg.reply_text ( "So‘rov juda qisqa.")
        STATE.pop ( uid,None)
        await msg.reply_text ( "🤖 AI faqat Veritasga qo‘shilgan hadislar ichidan qidirmoqda...")
        return await send_ai_hadith_results ( msg,query)
    if st and str ( st.get ( "mode","" )  ) .startswith ( "rebus_" ) :
        msg=update.effective_message
        mode=st["mode"]
        if not msg.text:
            return await msg.reply_text ( "Matn ko‘rinishida yuboring.")
        value=msg.text.strip ( )
        if mode=="rebus_group_count":
            if not value.isdigit (  ) :
                return await msg.reply_text ( "❌ Son yozing. Masalan: 5 yoki 10")
            count=int ( value)
            if count<1 or count>20:
                return await msg.reply_text ( "❌ 1 dan 20 tagacha rebus tanlang.")
            st["count"]=count
            st["answers"]=[]
            st["mode"]="rebus_group_answers"
            return await msg.reply_text(
                f"✅ {count} ta rebus.\n\n1/{count}-rebusning JAVOBINI yozing.\nMasalan: OLMA"
            )

        if mode=="rebus_group_answers":
            if len ( value ) >120:
                return await msg.reply_text ( "❌ Javob juda uzun. 120 belgidan qisqa yozing.")
            answers=st.setdefault ( "answers",[])
            answers.append ( value)
            count=int ( st["count"])
            if len ( answers ) <count:
                return await msg.reply_text(
                    f"✅ Qabul qilindi.\n\n{len ( answers ) +1}/{count}-rebusning JAVOBINI yozing."
                )

            group_id=int ( st["group_id"])
            target_chat_id=int ( st["target_chat_id"])
            answers=list ( answers)
            with db ( ) as c:
                cur=c.execute(
                    "INSERT INTO rebus_sessions ( creator_id,group_id,target_chat_id,total,current_no,status,created_at) "
                    "VALUES ( ?,?,?,?,0,'active',? ) ",
                    (uid,group_id,target_chat_id,count,now (  ) )
                )
                session_id=cur.lastrowid
                for n,ans in enumerate ( answers,1 ) :
                    c.execute(
                        "INSERT INTO rebus_session_items ( session_id,item_no,answer,status) VALUES ( ?,?,?,'waiting' ) ",
                        (session_id,n,ans)
                    )
            STATE.pop ( uid,None)
            await msg.reply_text(
                f"✅ {count} ta javob qabul qilindi.\n\n🎨 1/{count}-rebus tayyorlanmoqda. "
                "Birinchisi topilgach, keyingisi avtomatik chiqadi."
            )
            task=asyncio.create_task ( _launch_session_item ( ctx,session_id,1 ) )
            def _first_rebus_done ( t ) :
                try: t.result ( )
                except asyncio.CancelledError: pass
                except Exception: log.exception ( "First rebus task failed")
            task.add_done_callback ( _first_rebus_done)
            return
        if mode=="rebus_channel":
            try:
                raw=value.strip ( )
                # t.me/kanal_nomi, https://t.me/kanal_nomi yoki @kanal_nomi qabul qilinadi.
                m=re.fullmatch ( r" ( ?:https?:// ) ? ( ?:www\. ) ?t\.me/ ( [A-Za-z0-9_]{5,} )  ( ?:/ ) ? ( ?:\?.* ) ?",raw,re.I)
                if m:
                    target="@"+m.group ( 1)
                elif re.fullmatch ( r"-?\d+",raw ) :
                    target=int ( raw)
                else:
                    target=raw if raw.startswith ( "@") else "@"+raw.lstrip ( "@")
                ch=await ctx.bot.get_chat ( target)
                if ch.type!="channel":
                    return await msg.reply_text ( "❌ Bu kanal emas. Kanal @username yoki -100... ID yuboring.")
                me=await ctx.bot.get_chat_member ( ch.id,ctx.bot.id)
                if me.status not in (ChatMemberStatus.ADMINISTRATOR,ChatMemberStatus.OWNER ) :
                    return await msg.reply_text ( "❌ Veritas bu kanalda admin emas. Avval botni kanalga admin qiling.")
                linked=getattr ( ch,"linked_chat_id",None)
                st["channel_id"]=ch.id
                st["channel_title"]=ch.title or str ( ch.id)
                if linked:
                    try:
                        gr=await ctx.bot.get_chat ( linked)
                        st["group_id"]=gr.id
                        st["group_title"]=gr.title or str ( gr.id)
                        st["mode"]="rebus_topic"
                        return await msg.reply_text(
                            f"✅ Kanal: {st['channel_title']}\n👥 Javob guruhi: {st['group_title']}\n\n"
                            "Endi rebus javobi bo‘ladigan so‘z/ibora yoki mavzuni yozing.\n"
                            "Masalan: KITOB yoki Islom tarixi"
                        )
                    except TelegramError:
                        pass
                st["mode"]="rebus_group"
                return await msg.reply_text(
                    "✅ Kanal qabul qilindi.\n\nBu kanalga bog‘langan muhokama guruhini topmadim.\n"
                    "Javob tekshiriladigan guruhning @username yoki -100... ID sini yuboring."
                )
            except TelegramError:
                return await msg.reply_text ( "❌ Kanal topilmadi. Kanal linkini tekshiring va Veritas botni kanalga admin qiling.")
        if mode=="rebus_group":
            try:
                target=int ( value) if re.fullmatch ( r"-?\d+",value) else value
                gr=await ctx.bot.get_chat ( target)
                if gr.type not in ("group","supergroup" ) :
                    return await msg.reply_text ( "❌ Bu guruh emas.")
                member=await ctx.bot.get_chat_member ( gr.id,ctx.bot.id)
                if member.status not in (ChatMemberStatus.ADMINISTRATOR,ChatMemberStatus.OWNER ) :
                    return await msg.reply_text ( "❌ Veritas bu guruhda ishlamayapti.")
                st["group_id"]=gr.id
                st["group_title"]=gr.title or str ( gr.id)
                st["mode"]="rebus_topic"
                return await msg.reply_text(
                    f"👥 Javob guruhi: {st['group_title']}\n\n"
                    "Endi rebus javobi bo‘ladigan so‘z/ibora yoki mavzuni yozing."
                )
            except TelegramError:
                return await msg.reply_text ( "❌ Guruh topilmadi. Veritas guruhda bo‘lishi kerak.")
        if mode=="rebus_topic":
            channel_id=st["channel_id"]; group_id=st["group_id"]
            execute(
                "INSERT INTO rebus_channels ( owner_id,channel_id,channel_title,answer_group_id,answer_group_title,updated_at) "
                "VALUES ( ?,?,?,?,?,?) ON CONFLICT ( owner_id) DO UPDATE SET channel_id=excluded.channel_id,"
                "channel_title=excluded.channel_title,answer_group_id=excluded.answer_group_id,"
                "answer_group_title=excluded.answer_group_title,updated_at=excluded.updated_at",
                (uid,channel_id,st.get ( "channel_title","" ) ,group_id,st.get ( "group_title","" ) ,now (  ) )
            )
            STATE.pop ( uid,None)
            await msg.reply_text ( "🎨 AI rebus tayyorlayapti...\nBotdan foydalanishda davom etishingiz mumkin.")
            task=asyncio.create_task ( _create_and_post_rebus ( ctx,uid,channel_id,group_id,value,msg.chat.id ) )
            def _rebus_done ( t ) :
                try: t.result ( )
                except asyncio.CancelledError: pass
                except Exception: log.exception ( "Rebus background task failed")
            task.add_done_callback ( _rebus_done)
            return
        return
    if not st or not str ( st.get ( "mode","" )  ) .startswith ( "lib_" ) : return
    msg=update.effective_message
    mode=st["mode"]
    if mode=="lib_search":
        if not msg.text: return await msg.reply_text ( "🔎 Qidiruv uchun matn yuboring.")
        q=msg.text.strip (  ) ; STATE.pop ( uid,None)
        rows=all_ ( """SELECT * FROM library_books WHERE status='approved' AND
                     (title LIKE ? OR author LIKE ? OR description LIKE ?)
                     ORDER BY id DESC LIMIT 20""", ( f"%{q}%",f"%{q}%",f"%{q}%" ) )
        kb=[[InlineKeyboardButton ( "📖 "+r["title"][:38],callback_data=f"libbook:{r['id']}" ) ] for r in rows]
        kb.append ( [InlineKeyboardButton ( "⬅️ Kutubxona",callback_data="library" ) ])
        return await msg.reply_text ( f"🔎 «{q}» bo‘yicha: {len ( rows ) } ta natija",reply_markup=InlineKeyboardMarkup ( kb ) )
    if not is_library_admin ( uid ) :
        STATE.pop ( uid,None ) ; return await msg.reply_text ( "⛔ Kutubxona boshqaruv huquqi yo‘q.")
    data=st.setdefault ( "data",{})
    if mode.startswith ( "lib_edit_" ) :
        bid=int ( data.get ( "book_id",0 ) )
        if not bid or not one ( "SELECT 1 FROM library_books WHERE id=? AND status='approved'", ( bid, ) ) :
            STATE.pop ( uid,None ) ; return await msg.reply_text ( "❌ Kitob topilmadi." )
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
            elif msg.text and msg.text.casefold ( ).replace ( "‘","'" ).replace ( "’","'" ) in {"o'chirish","ochirish","o'tkazish","otkazish"}: fid=""
            else: return await msg.reply_text ( "🖼 Yangi rasm yuboring. Muqovani olib tashlash uchun «o‘chirish» yozing." )
            execute ( "UPDATE library_books SET cover_file_id=? WHERE id=?", ( fid,bid ) )
        elif field=="pdf":
            if not msg.document:
                return await msg.reply_text ( "📄 Yangi kitob faylini Document sifatida yuboring.\nPDF, EPUB, DOCX, TXT, FB2, MOBI yoki DJVU." )
            doc=msg.document; name= ( doc.file_name or "" ) .lower ( ).strip ( )
            allowed= ( ".pdf",".epub",".docx",".txt",".fb2",".mobi",".djvu")
            if not name.endswith ( allowed ) :
                return await msg.reply_text ( "❌ Format qabul qilinmaydi.\nPDF, EPUB, DOCX, TXT, FB2, MOBI yoki DJVU yuboring." )
            uniq=doc.file_unique_id or ""
            dup=one ( "SELECT id FROM library_books WHERE pdf_unique_id=? AND id<>? AND status<>'deleted'", ( uniq,bid ) ) if uniq else None
            if dup: return await msg.reply_text ( f"⚠️ Bu fayl boshqa kitobda mavjud. ID: {dup['id']}" )
            fmt=name.rsplit ( ".",1 ) [-1] if "." in name else "file"
            execute ( """UPDATE library_books
                         SET pdf_file_id=?,pdf_unique_id=?,book_file_id=?,book_unique_id=?,
                             book_file_name=?,book_format=?,book_file_size=?
                         WHERE id=?""",
                      ( doc.file_id,uniq,doc.file_id,uniq,doc.file_name or "",fmt,int ( doc.file_size or 0 ) ,bid ) )
        elif field=="audio":
            af=None
            if msg.audio: af=msg.audio
            elif msg.voice: af=msg.voice
            elif msg.document:
                d=msg.document; name= ( d.file_name or "" ) .lower ( ); mime= ( d.mime_type or "" ) .lower ( )
                if mime.startswith ( "audio/" ) or name.endswith ( ( ".mp3",".m4a",".m4b",".aac",".ogg",".opus",".wav",".flac",".wma" ) ): af=d
            if msg.text and msg.text.casefold ( ).replace ( "‘","'" ).replace ( "’","'" ) in {"o'chirish","ochirish","o'tkazish","otkazish"}:
                execute ( "UPDATE library_books SET audio_file_id='',audio_unique_id='' WHERE id=?", ( bid, ) )
            elif af:
                execute ( "UPDATE library_books SET audio_file_id=?,audio_unique_id=? WHERE id=?", ( af.file_id,af.file_unique_id or "",bid ) )
            else: return await msg.reply_text ( "🎧 Yangi audio/voice/audio-fayl yuboring. Olib tashlash uchun «o‘chirish» yozing." )
        else: return
        STATE.pop ( uid,None ) ; audit ( uid,0,"library_edit",f"{bid}:{field}" )
        return await msg.reply_text ( "✅ Kitob ma’lumoti yangilandi.",reply_markup=InlineKeyboardMarkup ( [[InlineKeyboardButton ( "📖 Kitobni ochish",callback_data=f"libbook:{bid}" ) ,InlineKeyboardButton ( "📚 Kutubxona",callback_data="library" ) ]] ) )
    if mode=="lib_quick_file":
        doc=msg.document
        if not doc:
            return await msg.reply_text(
                "📎 Kitob faylini Document/Fayl sifatida yuboring.\n\n"
                "Qabul qilinadi: PDF, EPUB, DOCX, TXT, FB2, MOBI, DJVU."
            )
        filename= ( doc.file_name or "Nomsiz kitob" ) .strip ( )
        low=filename.lower ( )
        allowed= ( ".pdf",".epub",".docx",".txt",".fb2",".mobi",".djvu")
        if not low.endswith ( allowed ) :
            return await msg.reply_text(
                "❌ Bu format hozir kutubxona uchun qabul qilinmaydi.\n"
                "PDF, EPUB, DOCX, TXT, FB2, MOBI yoki DJVU yuboring."
            )
        uniq=doc.file_unique_id or ""
        if uniq:
            dup=one ( "SELECT id,title FROM library_books WHERE pdf_unique_id=? AND status<>'deleted'", (uniq, ) )
            if dup:
                STATE.pop ( uid,None)
                return await msg.reply_text(
                    f"⚠️ Bu fayl kutubxonada avval qo‘shilgan.\n📖 {dup['title']}\nID: {dup['id']}",
                    reply_markup=library_home_markup ( uid)
                )

        # Fayl nomidan kitob nomini avtomatik chiqaramiz.
        title=re.sub ( r"\. ( pdf|epub|docx|txt|fb2|mobi|djvu ) $", "", filename, flags=re.I)
        title=title.replace ( "_"," " ) .replace ( "-"," ")
        title=re.sub ( r"\s+"," ",title ) .strip (  ) [:250] or "Nomsiz kitob"

        with db ( ) as c:
            cur=c.execute(
                """INSERT INTO library_books
                (title,author,lang,description,cover_file_id,pdf_file_id,pdf_unique_id,
                 audio_file_id,audio_unique_id,added_by,status,created_at,
                 book_file_id,book_unique_id,book_file_name,book_format,book_file_size)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,? ) """,
                (title,"","uz","","",doc.file_id,uniq,"","",uid,"approved",now (  ) ,
                 doc.file_id,uniq,filename,filename.rsplit ( ".",1 ) [-1].lower ( ) if "." in filename else "file",
                 int ( doc.file_size or 0 ) )
            )
            bid=cur.lastrowid

        STATE.pop ( uid,None)
        audit ( uid,0,"library_add_quick",str ( bid ) )
        kb=InlineKeyboardMarkup ( [
            [InlineKeyboardButton ( "✏️ Nomi / muallif / kategoriya", callback_data=f"libedit:{bid}" ) ],
            [InlineKeyboardButton ( "📖 Kitobni ochish", callback_data=f"libbook:{bid}" ) ,
             InlineKeyboardButton ( "➕ Yana kitob", callback_data="libadd" ) ],
            [InlineKeyboardButton ( "📚 Kutubxona", callback_data="library" ) ]
        ])
        return await msg.reply_text(
            "✅ KITOB QO‘SHILDI\n\n"
            f"📖 Nomi avtomatik: {title}\n"
            f"📎 Fayl: {filename}\n\n"
            "Kerak bo‘lsa pastdagi ✏️ tugma orqali nomi, muallifi, tili, "
            "kategoriyasi, tavsifi yoki muqovasini tahrirlang.",
            reply_markup=kb
        )

    if mode=="lib_add_title":
        if not msg.text: return await msg.reply_text ( "Kitob nomini matn qilib yuboring.")
        data["title"]=msg.text.strip (  ) [:250]; st["mode"]="lib_add_author"
        return await msg.reply_text ( "✍️ Muallif nomini yuboring:")
    if mode=="lib_add_author":
        if not msg.text: return await msg.reply_text ( "Muallif nomini matn qilib yuboring.")
        data["author"]=msg.text.strip (  ) [:250]
        dup=one ( "SELECT id FROM library_books WHERE lower ( title ) =lower ( ?) AND lower ( author ) =lower ( ?) AND status<>'deleted'", ( data["title"],data["author"] ) )
        if dup:
            STATE.pop ( uid,None ) ; return await msg.reply_text ( f"⚠️ Bu kitob kutubxonada mavjud. ID: {dup['id']}",reply_markup=library_home_markup ( uid ) )
        st["mode"]="lib_add_lang"
        kb=InlineKeyboardMarkup ( [[InlineKeyboardButton ( "🇺🇿 O‘zbekcha",callback_data="libaddlang:uz" ) ,InlineKeyboardButton ( "🇷🇺 Русский",callback_data="libaddlang:ru" ) ,InlineKeyboardButton ( "🇬🇧 English",callback_data="libaddlang:en" ) ]])
        return await msg.reply_text ( "🌐 Kitob tilini tanlang:",reply_markup=kb)
    if mode=="lib_add_categories":
        if not msg.text: return await msg.reply_text ( "Kategoriyalarni matn qilib yuboring.")
        data["categories"]=[x.strip (  ) [:80] for x in msg.text.split ( ",") if x.strip (  ) ][:10]
        st["mode"]="lib_add_description"
        return await msg.reply_text ( "📝 Kitob tavsifini yuboring:")
    if mode=="lib_add_description":
        if not msg.text: return await msg.reply_text ( "Tavsifni matn qilib yuboring.")
        data["description"]=msg.text.strip (  ) [:3000]; st["mode"]="lib_add_cover"
        return await msg.reply_text ( "🖼 Muqova rasmini yuboring. Muqova bo‘lmasa: o'tkazish")
    if mode=="lib_add_cover":
        if msg.photo:
            data["cover_file_id"]=msg.photo[-1].file_id
        elif msg.text and msg.text.lower (  ) .replace ( "‘","'" ) .replace ( "’","'") in ("o'tkazish","otkazish" ) :
            data["cover_file_id"]=""
        else: return await msg.reply_text ( "🖼 Rasm yuboring yoki «o'tkazish» deb yozing.")
        st["mode"]="lib_add_pdf"; return await msg.reply_text ( "📄 Endi PDF faylni yuboring:")
    if mode=="lib_add_pdf":
        # Faylning o‘zini Railway'ga yuklamaymiz; Telegram file_id saqlanadi.
        doc=msg.document
        if not doc:
            return await msg.reply_text ( "📄 PDF hujjatni 📎 Fayl/Document sifatida yuboring.\n\n⚠️ Rasm yoki boshqa turdagi xabar PDF sifatida qabul qilinmaydi.")
        name= ( doc.file_name or "" ) .lower (  ) .strip (  ) ; mime= ( doc.mime_type or "" ) .lower (  ) .strip ( )
        if not (name.endswith ( ".pdf") or mime=="application/pdf" ) :
            return await msg.reply_text ( f"❌ Bu PDF emas.\nFayl: {doc.file_name or 'nomsiz'}\nTuri: {doc.mime_type or 'noma’lum'}\n\nPDF fayl yuboring.")
        uniq=doc.file_unique_id or ""
        if uniq and one ( "SELECT id FROM library_books WHERE pdf_unique_id=? AND status<>'deleted'", ( uniq, )  ) :
            STATE.pop ( uid,None)
            return await msg.reply_text ( "⚠️ Aynan shu PDF avval qo‘shilgan.",reply_markup=library_home_markup ( uid ) )
        data["pdf_file_id"]=doc.file_id; data["pdf_unique_id"]=uniq
        data["pdf_file_name"]=doc.file_name or ""; data["pdf_file_size"]=int ( doc.file_size or 0)
        st["mode"]="lib_add_audio"
        size_mb= ( int ( doc.file_size or 0 ) / ( 1024*1024 ) ) if doc.file_size else 0
        kb=InlineKeyboardMarkup ( [[InlineKeyboardButton ( "⏭ Audio yo‘q — o‘tkazish",callback_data="libskipaudio" ) ]])
        return await msg.reply_text(
            f"✅ PDF qabul qilindi" + (f" ({size_mb:.1f} MB ) " if size_mb else "") +
            "\n\n🎧 Endi audio kitobni yuboring.\nMP3, M4A, M4B, OGG, OPUS, WAV, FLAC yoki voice qabul qilinadi.", reply_markup=kb)
    if mode=="lib_add_audio":
        af=None
        if msg.audio: af=msg.audio
        elif msg.voice: af=msg.voice
        elif msg.document:
            d=msg.document
            name= ( d.file_name or "" ) .lower (  ) .strip (  ) ; mime= ( d.mime_type or "" ) .lower (  ) .strip ( )
            audio_ext= ( ".mp3",".m4a",".m4b",".aac",".ogg",".opus",".wav",".flac",".wma")
            if mime.startswith ( "audio/") or name.endswith ( audio_ext ) : af=d
            else: return await msg.reply_text ( "❌ Bu audio fayl emas.\nMP3/M4A/M4B/OGG/OPUS/WAV/FLAC yuboring yoki «o'tkazish» deb yozing.")
        elif msg.text and msg.text.lower (  ) .replace ( "‘","'" ) .replace ( "’","'") in ("o'tkazish","otkazish" ) :
            data["audio_file_id"]=""; data["audio_unique_id"]=""
        else:
            return await msg.reply_text ( "🎧 Audio, voice yoki audio-fayl yuboring.\nAudio kerak bo‘lmasa «o'tkazish» deb yozing.")
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
        return await msg.reply_text ( f"✅ Kitob Vasatiya kutubxonasiga qo‘shildi.\n📖 {data['title']}\nID: {bid}",reply_markup=library_home_markup ( uid ) )

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
    parts=[f"📜 {r['collection']} — {r['number']}-hadis"]
    if r["arabic"]: parts += ["",r["arabic"]]
    parts += ["",f"🇺🇿 {r['translation']}"]
    if r["explanation"]: parts += ["",f"📝 Sharh: {r['explanation']}"]
    if r["source"]: parts += ["",f"📚 Manba: {r['source']}"]
    return "\n".join ( parts)

def hadith_markup ( r,back="hadith" ) :
    uploader=one ( "SELECT first_name,username FROM users WHERE user_id=?", ( r["added_by"], ) )
    name= ( uploader["first_name"] if uploader and uploader["first_name"] else f"ID {r['added_by']}")
    kb=[[InlineKeyboardButton ( f"👤 Qo‘shdi: {name[:40]}",url=f"tg://user?id={r['added_by']}" ) ]]
    kb.append ( [InlineKeyboardButton ( "⬅️ Hadislar",callback_data=back ) ,InlineKeyboardButton ( "🏠 Bosh menyu",callback_data="home" ) ])
    return InlineKeyboardMarkup ( kb)

async def send_hadith ( chat_id,ctx,r,reply_to=None ) :
    if not r: return
    await ctx.bot.send_message ( chat_id,hadith_text ( r ) ,reply_markup=hadith_markup ( r ) ,reply_to_message_id=reply_to)

async def hadith_command ( update,ctx,args ) :
    msg=update.effective_message
    if not args:
        r=one ( "SELECT * FROM hadiths WHERE status='approved' ORDER BY RANDOM ( ) LIMIT 1")
        if not r: return await msg.reply_text ( "📜 Hozircha hadis bazasi bo‘sh.")
        return await send_hadith ( update.effective_chat.id,ctx,r,msg.message_id)
    if not args[-1].isdigit (  ) :
        return await msg.reply_text ( "Misol: *hadis buxoriy 1")
    num=int ( args[-1] ) ; collection=hadith_collection_key ( " ".join ( args[:-1] ) )
    r=one ( "SELECT * FROM hadiths WHERE lower ( collection ) =lower ( ?) AND number=? AND status='approved'", ( collection,num ) )
    if not r: return await msg.reply_text ( f"❌ {collection} {num} topilmadi.")
    return await send_hadith ( update.effective_chat.id,ctx,r,msg.message_id)

async def content_admin_command ( update,ctx,cmd ) :
    msg=update.effective_message; uid=update.effective_user.id
    if not is_super ( uid ): return await msg.reply_text ( "⛔ Bu buyruq faqat Super Ega uchun.")
    t=replied ( update)
    if cmd in {"ad.book","unad.book","ad.hadis","unad.hadis"}:
        if not t or not t.from_user: return await msg.reply_text ( "↩️ Foydalanuvchi xabariga reply qiling.")
        ensure_user ( t.from_user ) ; target=t.from_user.id
        if cmd=="ad.book":
            execute ( "INSERT OR REPLACE INTO library_admins ( user_id,added_by,created_at) VALUES ( ?,?,? ) ", ( target,uid,now (  )  ) )
            return await msg.reply_text ( f"✅ {t.from_user.full_name} — kutubxona admini qilindi.")
        if cmd=="unad.book":
            execute ( "DELETE FROM library_admins WHERE user_id=?", ( target, ) )
            return await msg.reply_text ( f"✅ {t.from_user.full_name}ning kutubxona adminligi olib tashlandi.")
        if cmd=="ad.hadis":
            execute ( "INSERT OR REPLACE INTO hadith_admins ( user_id,added_by,created_at) VALUES ( ?,?,? ) ", ( target,uid,now (  )  ) )
            return await msg.reply_text ( f"✅ {t.from_user.full_name} — hadis admini qilindi.")
        execute ( "DELETE FROM hadith_admins WHERE user_id=?", ( target, ) )
        return await msg.reply_text ( f"✅ {t.from_user.full_name}ning hadis adminligi olib tashlandi.")
    table="library_admins" if cmd=="bookadmins" else "hadith_admins"
    rows=all_ ( f"SELECT a.user_id,u.first_name,u.username FROM {table} a LEFT JOIN users u ON u.user_id=a.user_id ORDER BY a.created_at")
    title="📚 Kutubxona adminlari" if cmd=="bookadmins" else "📜 Hadis adminlari"
    lines=[title]
    for i,r in enumerate ( rows,1 ) :
        nm= ( r["first_name"] or "Nomsiz") + ( ( " @"+r["username"]) if r["username"] else "")
        lines.append ( f"{i}. {nm} — {r['user_id']}")
    if len ( lines ) ==1: lines.append ( "Hozircha admin yo‘q.")
    await msg.reply_text ( "\n".join ( lines ) )

async def add_hadith_command ( update,ctx ) :
    msg=update.effective_message; uid=update.effective_user.id
    if not is_hadith_admin ( uid ) : return await msg.reply_text ( "⛔ Hadis qo‘shish huquqi yo‘q.")
    if update.effective_chat.type != "private":
        return await msg.reply_text ( "📜 Hadis qo‘shish xavfsiz va qulay bo‘lishi uchun botning private chatida *add.hadis yozing.")
    STATE[uid]={"mode":"had_add_collection","data":{}}
    await msg.reply_text ( "📜 HADIS QO‘SHISH — 1/6\n\nTo‘plam nomini yuboring.\nMisol: Buxoriy")

async def hadith_private_input ( update,ctx ) :
    uid=update.effective_user.id; msg=update.effective_message; st=STATE.get ( uid)
    if not st or not str ( st.get ( "mode","" )  ) .startswith ( "had_" ) : return
    if not is_hadith_admin ( uid ) :
        STATE.pop ( uid,None ) ; return await msg.reply_text ( "⛔ Hadis boshqaruv huquqi yo‘q.")
    if not msg.text:
        return await msg.reply_text ( "✍️ Bu bosqichda matn yuboring.")
    text=msg.text.strip (  ) ; data=st.setdefault ( "data",{} ) ; mode=st["mode"]
    if text.casefold ( ) in {"bekor","cancel","/cancel"}:
        STATE.pop ( uid,None ) ; return await msg.reply_text ( "❌ Hadis qo‘shish bekor qilindi.",reply_markup=main_menu_markup ( uid ) )
    if mode.startswith ( "had_edit_" ) :
        hid=int ( data.get ( "hadith_id",0 ) )
        if not hid or not one ( "SELECT 1 FROM hadiths WHERE id=? AND status='approved'", ( hid, ) ) :
            STATE.pop ( uid,None ) ; return await msg.reply_text ( "❌ Hadis topilmadi." )
        field=mode[9:]
        if field=="collection": value=hadith_collection_key ( text )
        elif field=="number":
            if not text.isdigit ( ) or int ( text ) <=0: return await msg.reply_text ( "❌ Musbat raqam yuboring." )
            value=int ( text )
        elif field in {"arabic","explanation","source"}:
            value="" if text.casefold ( ).replace ( "‘","'" ).replace ( "’","'" ) in {"o'tkazish","otkazish","o'chirish","ochirish"} else text
        elif field=="translation": value=text
        else: return
        current=one ( "SELECT collection,number FROM hadiths WHERE id=?", ( hid, ) )
        col=value if field=="collection" else current["collection"]; num=value if field=="number" else current["number"]
        dup=one ( "SELECT id FROM hadiths WHERE lower ( collection ) =lower ( ?) AND number=? AND id<>? AND status<>'deleted'", ( col,num,hid ) )
        if dup: return await msg.reply_text ( f"⚠️ {col} {num} boshqa hadis sifatida bazada mavjud. ID: {dup['id']}" )
        execute ( f"UPDATE hadiths SET {field}=? WHERE id=?", ( value,hid ) )
        STATE.pop ( uid,None ) ; audit ( uid,0,"hadith_edit",f"{hid}:{field}" )
        r=one ( "SELECT * FROM hadiths WHERE id=?", ( hid, ) )
        kb=InlineKeyboardMarkup ( [[InlineKeyboardButton ( "✏️ Yana tahrirlash",callback_data=f"hedit:{hid}" ) ],[InlineKeyboardButton ( "📜 Hadislar",callback_data="hadith" ) ]] )
        return await msg.reply_text ( "✅ Hadis yangilandi.\n\n"+hadith_text ( r ),reply_markup=kb )
    if mode=="had_add_collection":
        data["collection"]=hadith_collection_key ( text ) ; st["mode"]="had_add_number"
        return await msg.reply_text ( "📜 2/6 — Hadis raqamini yuboring.\nMisol: 1")
    if mode=="had_add_number":
        if not text.isdigit ( ) or int ( text ) <=0: return await msg.reply_text ( "❌ Musbat raqam yuboring. Misol: 1")
        data["number"]=int ( text)
        existing=one ( "SELECT * FROM hadiths WHERE lower ( collection ) =lower ( ?) AND number=? AND status<>'deleted'", ( data["collection"],data["number"] )  )
        if existing:
            STATE.pop ( uid,None )
            kb=InlineKeyboardMarkup ( [[InlineKeyboardButton ( "✏️ Mavjud hadisni tahrirlash",callback_data=f"hedit:{existing['id']}" ) ],[InlineKeyboardButton ( "❌ Bekor",callback_data="hadith" ) ]] )
            return await msg.reply_text ( f"⚠️ {data['collection']} {data['number']} bazada mavjud.\n\nYangi nusxa qo‘shilmaydi. Mavjud hadisni tahrirlashingiz mumkin.",reply_markup=kb )
        st["mode"]="had_add_arabic"
        return await msg.reply_text ( "📜 3/6 — Hadisning arabcha asl matnini yuboring.\nArabcha matn bo‘lmasa: o'tkazish")
    if mode=="had_add_arabic":
        data["arabic"]="" if text.casefold (  ) .replace ( "‘","'" ) .replace ( "’","'") in {"o'tkazish","otkazish"} else text
        st["mode"]="had_add_translation"
        return await msg.reply_text ( "📜 4/6 — O‘zbekcha tarjimasini yuboring:")
    if mode=="had_add_translation":
        data["translation"]=text; st["mode"]="had_add_explanation"
        return await msg.reply_text ( "📜 5/6 — Qisqa sharh yuboring.\nSharh bo‘lmasa: o'tkazish")
    if mode=="had_add_explanation":
        data["explanation"]="" if text.casefold (  ) .replace ( "‘","'" ) .replace ( "’","'") in {"o'tkazish","otkazish"} else text
        st["mode"]="had_add_source"
        return await msg.reply_text ( "📜 6/6 — Manbani yuboring.\nMisol: Sahih al-Buxoriy, Kitob ...")
    if mode=="had_add_source":
        data["source"]=text
        try:
            execute ( "INSERT INTO hadiths ( collection,number,arabic,translation,explanation,source,added_by,status,created_at) VALUES ( ?,?,?,?,?,?,?,?,? ) ",
                    (data["collection"],data["number"],data.get ( "arabic","" ) ,data["translation"],data.get ( "explanation","" ) ,data["source"],uid,"approved",now (  )  ) )
        except sqlite3.IntegrityError:
            STATE.pop ( uid,None ) ; return await msg.reply_text ( "⚠️ Bu hadis bazada mavjud.",reply_markup=main_menu_markup ( uid ) )
        audit ( uid,update.effective_chat.id,"hadith_add",f"{data['collection']} {data['number']}")
        r=one ( "SELECT * FROM hadiths WHERE lower ( collection ) =lower ( ?) AND number=?", ( data["collection"],data["number"] ) )
        STATE.pop ( uid,None)
        await msg.reply_text ( "✅ Hadis saqlandi.")
        return await send_hadith ( update.effective_chat.id,ctx,r)

async def delete_hadith_command ( update,ctx,args ) :
    msg=update.effective_message; uid=update.effective_user.id
    if not is_hadith_admin ( uid ) : return await msg.reply_text ( "⛔ Hadis o‘chirish huquqi yo‘q.")
    if len ( args ) <2 or not args[-1].isdigit (  ) : return await msg.reply_text ( "Misol: *del.hadis buxoriy 1")
    num=int ( args[-1] ) ; collection=hadith_collection_key ( " ".join ( args[:-1] ) )
    r=one ( "SELECT id,collection,number FROM hadiths WHERE lower ( collection ) =lower ( ?) AND number=? AND status='approved'", ( collection,num ) )
    if not r: return await msg.reply_text ( "❌ Hadis topilmadi.")
    kb=InlineKeyboardMarkup ( [[InlineKeyboardButton ( "✅ O‘chirish",callback_data=f"hdel:{r['id']}" ) ,InlineKeyboardButton ( "❌ Bekor",callback_data="hadith" ) ]])
    await msg.reply_text ( f"🗑 {r['collection']} {r['number']} hadisni o‘chirishni tasdiqlaysizmi?",reply_markup=kb)

async def broadcast_command ( update,ctx,args ) :
    msg=update.effective_message; uid=update.effective_user.id
    if not is_super ( uid ):
        return await msg.reply_text ( "⛔ *post faqat Super Ega uchun.")
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
        return await msg.reply_text ( "📢 Xabar yuborish:\n1) Post/xabarga reply qilib *post yozing\nyoki\n2) *post Xabaringiz")
    sent=0; failed=0
    status=await msg.reply_text ( f"📢 Yuborish boshlandi...\nQabul qiluvchilar: {len ( targets ) }")
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
    await status.edit_text ( f"✅ Xabarnoma tugadi.\n\n📨 Yuborildi: {sent}\n⚠️ Yetib bormadi: {failed}")

async def stars_cmd ( update, ctx, args ) :
    uid = update.effective_user.id
    msg = update.effective_message
    if not is_super ( uid ):
        return await msg.reply_text ( "⛔ *stars faqat Super Ega uchun.")
    t = replied ( update)
    if not t or not t.from_user:
        return await msg.reply_text ( "↩️ Stars oluvchining xabariga reply qiling.\nMisol: *stars 100")
    if not args or not args[0].isdigit (  ) :
        return await msg.reply_text ( "Misol: *stars 100")
    stars = int ( args[0])
    if stars <= 0:
        return await msg.reply_text ( "❌ Stars miqdori 0 dan katta bo‘lishi kerak.")
    target = t.from_user
    username = f"@{target.username}" if target.username else "username mavjud emas"
    kb = InlineKeyboardMarkup ( [[
        InlineKeyboardButton ( "⭐ Telegram orqali Stars sovg‘a qilish", url="tg://settings/stars/gift")
    ]])
    await msg.reply_text(
        f"⭐ Stars sovg‘asi\n\n"
        f"👤 Oluvchi: {target.full_name}\n"
        f"🔗 Username: {username}\n"
        f"🆔 ID: {target.id}\n"
        f"⭐ Miqdor: {stars}\n\n"
        f"Quyidagi tugmani bosing.\n"
        f"Telegramning rasmiy Stars Gift oynasi ochiladi.\n"
        f"U yerdan oluvchini tanlab, {stars} ⭐ paketini tanlang va to‘lovni tasdiqlang.",
        reply_markup=kb
    )

async def start ( update,ctx ) :
    ensure_user ( update.effective_user)
    u=update.effective_user
    if update.effective_chat.type != "private":
        ensure_group ( update.effective_chat)
        await update.effective_message.reply_text ( "🪶 Veritas v8 ishlayapti. Shaxsiy kabinet uchun botga private yozing.")
        return
    await update.effective_message.reply_text ( "🪶 VERITAS v8\n\nShaxsiy kabinet",reply_markup=main_menu_markup ( u.id ) )

async def cmd_id ( update,ctx ) :
    ensure_user ( update.effective_user)
    await update.effective_message.reply_text ( f"👤 ID: {update.effective_user.id}\n💬 Chat ID: {update.effective_chat.id}")

async def cmd_help ( update,ctx ) :
    await update.effective_message.reply_text(
        "❓ VERITAS V8 — YORDAM MARKAZI\n\n"
        "🪶 Veritas qila oladigan barcha asosiy ishlar shu yerda jamlangan.\n"
        "Kerakli bo‘limni tanlang:",
        reply_markup=help_home_markup ( )
    )

def help_home_markup (  ) :
    return InlineKeyboardMarkup ( [
        [InlineKeyboardButton ( "📌 Asosiy",callback_data="help:main" ) , InlineKeyboardButton ( "👤 Profil / Faollik",callback_data="help:profile" ) ],
        [InlineKeyboardButton ( "🤖 Veritas AI",callback_data="help:ai" ) , InlineKeyboardButton ( "🧩 AI Rebus",callback_data="help:rebus" ) ],
        [InlineKeyboardButton ( "📚 Vasatiya",callback_data="help:library" ) , InlineKeyboardButton ( "📜 Hadislar",callback_data="help:hadith" ) ],
        [InlineKeyboardButton ( "🛡 Moderatsiya",callback_data="help:moderation" ) , InlineKeyboardButton ( "⏱ Vaqtli jazolar",callback_data="help:tempmod" ) ],
        [InlineKeyboardButton ( "🔐 Himoya / Lock",callback_data="help:security" ) , InlineKeyboardButton ( "🌊 Anti-spam / Raid",callback_data="help:antispam" ) ],
        [InlineKeyboardButton ( "👋 Welcome / Goodbye",callback_data="help:welcome" ) , InlineKeyboardButton ( "💬 Filter / Notes",callback_data="help:filters" ) ],
        [InlineKeyboardButton ( "🛡 Adminlar",callback_data="help:admins" ) , InlineKeyboardButton ( "👑 Super boshqaruv",callback_data="help:superadmins" ) ],
        [InlineKeyboardButton ( "⭐ Stars / Gift",callback_data="help:stars" ) , InlineKeyboardButton ( "🎉 Giveaway",callback_data="help:giveaway" ) ],
        [InlineKeyboardButton ( "📢 Xabarnoma",callback_data="help:broadcast" ) , InlineKeyboardButton ( "📨 Egaga xabar",callback_data="help:owner" ) ],
        [InlineKeyboardButton ( "⚙️ Guruh sozlamalari",callback_data="help:settings" ) ],
        [InlineKeyboardButton ( "🏠 Bosh menyu",callback_data="home" ) ]
    ])

def help_menu_markup (  ) :
    return InlineKeyboardMarkup ( [
        [InlineKeyboardButton ( "⬅️ Yordam bo‘limlari",callback_data="help:home" ) , InlineKeyboardButton ( "🏠 Bosh menyu",callback_data="home" ) ]
    ])

def help_text ( section ) :
    data={
      "main":"📌 ASOSIY BUYRUQLAR\n━━━━━━━━━━━━━━━━━━\n*help — barcha yordam bo‘limlarini ochadi.\n*id — sizning Telegram ID va joriy chat ID sini ko‘rsatadi.\n*men — shaxsiy/global profilingizni ko‘rsatadi.\n*qadr — Qadr TOP-10 ni ko‘rsatadi.\n💠 Qadr / ⚖️ E’tiroz — a’zoning ochiq profilidan baholash.\n*rules — guruh qoidalarini chiqaradi.\n*admins — guruh va Veritas adminlarini ko‘rsatadi.\n*vse — Veritas xabariga reply qilib yozilganda a’zoning Veritas qayd etgan oldingi xabarlarini tozalaydi.\n\n🏠 Shaxsiy chatdagi bosh menyudan AI, kutubxona, hadis, profil, Stars, Rebus va Egaga xabar bo‘limlari ochiladi.",
      "profile":"👤 PROFIL VA FAOLLIK\n━━━━━━━━━━━━━━━━━━\n*men — rol, XP, level, xabarlar, ilm hissasi va kabinet ma’lumotlari.\n*ak — barcha Veritas guruhlari bo‘yicha Global TOP-10.\n*aktiv — global faollik TOP ro‘yxati.\n*top 10 — TOP paneli.\n*unvon <nom> — maxsus unvon o‘rnatadi.\n*unvonoff — maxsus unvonni olib tashlaydi.\n\n📈 Veritas guruhlardagi faollikni jamlab profilga qo‘shadi.",
      "ai":"🤖 VERITAS AI\n━━━━━━━━━━━━━━━━━━\nShaxsiy menyudagi «🤖 Veritas AI» — AI yordamchi.\n*ai — guruhdagi AI holati va tarifini ochadi.\n*ai.p — replydagi foydalanuvchiga AI Premium sovg‘a qiladi.\n\n🎁 Shaxsiy AI: birinchi 30 kun bepul, keyin 10 ⭐ / 30 kun.\n🎁 Guruh AI: birinchi 30 kun bepul, keyin 100 ⭐ / 30 kun.\n🖼 AI rasmni ko‘rib tahlil qila oladi.\n📚 Kutubxona PDFlaridan AI test yaratish imkoniyatlari ham mavjud.",
      "rebus":"🧩 AI REBUS\n━━━━━━━━━━━━━━━━━━\nGuruhda Veritas xabariga reply qilib *rebus yozing.\nBot private chatda rebuslar soni va javoblarini so‘raydi.\nAI rasmli rebus yaratadi; to‘g‘ri javob topilgach keyingisi chiqadi.\n🏆 Yakunda g‘oliblar natijasi chiqariladi.\n📍 Bog‘langan kanal bo‘lsa rebus kanalga, aks holda guruhga joylanadi.",
      "library":"📚 VASATIYA KUTUBXONASI\n━━━━━━━━━━━━━━━━━━\n🔎 Kitob qidirish, kategoriya, yangi kitoblar va sevimlilar.\n📄 PDF/audio kitoblar va kitob boshqaruvi.\n*ad.book — replydagi odamga kutubxona adminligi beradi.\n*unad.book — kutubxona adminligini oladi.\n*bookadmins — kutubxona adminlarini ko‘rsatadi.\n\n✏️ Kitob admini nom, muallif, til, kategoriya, tavsif, muqova, PDF va audioni boshqaradi.",
      "hadith":"📜 SAHIH HADISLAR\n━━━━━━━━━━━━━━━━━━\n*hadis — tasodifiy hadis chiqaradi.\n🤖 AI Hadis qidirish — faqat Veritasga qo‘shilgan hadislar orasidan mavzu bo‘yicha topadi.\n*hadis buxoriy 1 — aniq hadisni topadi.\n*add.hadis — private chatda yangi hadis qo‘shadi.\n*del.hadis buxoriy 1 — hadisni o‘chiradi.\n*ad.hadis — hadis adminligi beradi.\n*unad.hadis — huquqni oladi.\n*hadisadmins — hadis adminlari ro‘yxati.\n✏️ Mavjud hadisni tahrirlash ham mumkin.",
      "moderation":"🛡 MODERATSIYA\n━━━━━━━━━━━━━━━━━━\n*warn [sabab] — replydagi a’zoga ogohlantirish beradi.\n*unwarn — bitta warnni olib tashlaydi.\n*warns — warnlar sonini ko‘rsatadi.\n*clearwarns — barcha warnlarni tozalaydi.\n*mute — replydagi a’zoni yozishdan cheklaydi.\n*unmute — mute holatini ochadi.\n*kick — a’zoni guruhdan chiqaradi.\n*ban — a’zoni bloklaydi.\n*unban — ban holatini ochadi.\n*del — reply qilingan xabarni o‘chiradi.\n*purge — reply qilingan joydan buyruqqacha xabarlarni tozalaydi.\n*pin — replydagi xabarni pin qiladi.\n*unpin — joriy pinni olib tashlaydi.\n*modlog — so‘nggi moderatsiya amallarini ko‘rsatadi.\n\nℹ️ Jazolash buyruqlarini foydalanuvchi xabariga reply qilib ishlating.",
      "tempmod":"⏱ VAQTLI JAZOLAR\n━━━━━━━━━━━━━━━━━━\n*tempmute 10m [sabab] — replydagi a’zoni 10 daqiqaga mute qiladi.\n*tempban 2h [sabab] — replydagi a’zoni 2 soatga ban qiladi.\n\n⏰ Vaqt: s=soniya, m=daqiqa, h=soat, d=kun, w=hafta.\nMisol: *tempmute 1d flood\nMuddat tugaganda Veritas jazoni avtomatik ochadi.",
      "security":"🔐 HIMOYA VA LOCKLAR\n━━━━━━━━━━━━━━━━━━\n*links on/off — havolalarni nazorat qiladi.\n*blacklist <so‘z> — taqiqlangan so‘z qo‘shadi.\n*unblacklist <so‘z> — blacklistdan olib tashlaydi.\n*blacklists — blacklist ro‘yxati.\n*lock <turi> — turdagi kontentni bloklaydi.\n*unlock <turi> — lockni ochadi.\n*locks — faol locklarni ko‘rsatadi.\n*lockall — media locklarning barchasini yoqadi.\n*unlockall — media locklarning barchasini o‘chiradi.\n\n🔒 Rose Full media himoyasi: forward, contact, location, poll, photo, video, audio, voice, document, sticker, animation.",
      "antispam":"🌊 ANTI-SPAM / ANTI-RAID\n━━━━━━━━━━━━━━━━━━\n*antiflood on/off — flood himoyasini yoqadi/o‘chiradi.\n*flood 5 — flood chegarasini belgilaydi.\n*antirepeat on/off [limit] — bir xil xabarni takrorlashdan himoya qiladi.\n*raid on/off — ko‘p odam birdan kirgandagi raid himoyasi.\n*report — adminlarni yordamga chaqiradi.\n*reports on/off — report tizimini boshqaradi.\n\n🛡 Approved va admin foydalanuvchilar himoya filtrlari uchun istisno qilinishi mumkin.",
      "welcome":"👋 WELCOME / GOODBYE\n━━━━━━━━━━━━━━━━━━\n*welcome on/off — kirish xabarini yoqadi/o‘chiradi.\n*goodbye on/off — chiqish xabarini yoqadi/o‘chiradi.\n*setwelcome <matn> — maxsus welcome matni.\n*setgoodbye <matn> — maxsus goodbye matni.\n*cleanservice on/off — join/leave servis xabarlarini tozalaydi.\n\n🧩 Matnda {first} — ism, {chatname} — guruh nomi sifatida ishlatiladi.",
      "filters":"💬 FILTER VA NOTES\n━━━━━━━━━━━━━━━━━━\n*filter <kalit> <javob> — kalit so‘zga avtomatik javob saqlaydi.\n*filters — filterlar ro‘yxati.\n*stop <kalit> — bitta filterni o‘chiradi.\n*stopall — barcha filterlarni tozalaydi.\n*save <nom> <matn> — note saqlaydi.\n*get <nom> — note chiqaradi.\n*notes — notelar ro‘yxati.\n*clear <nom> — noteni o‘chiradi.",
      "admins":"🛡 ADMIN BOSHQARUVI\n━━━━━━━━━━━━━━━━━━\n*ruxsat — replydagi a’zoga Veritas boshqaruv huquqi beradi.\n*ruxsatsiz — Veritas huquqini oladi.\n*admin — Telegram admini qiladi.\n*unadmin — Telegram adminligini oladi.\n*approve — a’zoni himoya filtrlari uchun tasdiqlaydi.\n*unapprove — approve holatini olib tashlaydi.\n*approved — tasdiqlangan a’zolar ro‘yxati.\n*ad.book / *unad.book — kutubxona admini.\n*ad.hadis / *unad.hadis — hadis admini.",
      "superadmins":"👑 SUPER BOSHQARUV\n━━━━━━━━━━━━━━━━━━\n*superadmin — replydagi foydalanuvchini Super Admin qiladi.\n*unsuperadmin — Super Admin huquqini oladi.\n*superadmins — Super Egalar va Super Adminlar ro‘yxati.\n*post — global xabarnoma yuboradi.\n*ai.p — replydagi foydalanuvchiga AI Premium beradi.\n\n👑 Super Admin qo‘shish/olish faqat haqiqiy Super Ega uchun.",
      "stars":"⭐ STARS / GIFT / PREMIUM\n━━━━━━━━━━━━━━━━━━\n*topup 100 — Veritas kabinetiga Stars kredit oladi.\n*stars 100 — Telegram Stars bilan bog‘liq oynani ochadi (ruxsatga qarab ) .\n*give <narx> — replydagi foydalanuvchiga real Telegram Gift yuboradi.\n*premium 3/6/12 — replydagi foydalanuvchiga Telegram Premium sovg‘a qiladi.\n⭐ Kabinet balansi bosh menyudagi «Hisob» bo‘limida ko‘rinadi.",
      "giveaway":"🎉 GIVEAWAY\n━━━━━━━━━━━━━━━━━━\n*giveaway gift <narx> <daq> <g‘oliblar> — guruhda Gift konkursini ochadi.\n*join — faol konkursga qatnashadi.\n🏆 Vaqt tugaganda Veritas g‘oliblarni avtomatik tanlaydi.",
      "broadcast":"📢 GLOBAL XABARNOMA\n━━━━━━━━━━━━━━━━━━\n*post <matn> — barcha foydalanuvchi va guruhlarga matn yuboradi.\n*post — biror post/xabarga reply qilib ishlatilsa, o‘sha xabarni nusxalaydi.\n🔐 Faqat Super boshqaruv uchun.",
      "owner":"📨 EGAGA XABAR QOLDIRISH\n━━━━━━━━━━━━━━━━━━\nBosh menyudan «📨 Egaga xabar qoldirish» tugmasini bosing.\nKeyin matn, rasm, video, voice, audio, sticker yoki hujjat yuborishingiz mumkin.\n📬 Xabar Super Egalarga yetkaziladi.\n✉️ Ega «Javob berish» tugmasi orqali sizga Veritas ichidan javob beradi.\n✅ «Ko‘rildi» — murojaat ko‘rilganini belgilaydi.\n🗑 «Yopish» — murojaatni yakunlaydi.",
      "settings":"⚙️ GURUH SOZLAMALARI\n━━━━━━━━━━━━━━━━━━\n*setrules <matn> — guruh qoidalarini saqlaydi.\n*welcome on/off — welcome tizimi.\n*goodbye on/off — goodbye tizimi.\n*cleanservice on/off — servis xabarlarini tozalash.\n*links on/off — link himoyasi.\n*antiflood on/off — flood himoyasi.\n*reports on/off — report tizimi.\n\n🪶 Barcha sozlamalar guruh bo‘yicha alohida saqlanadi."
    }
    return data.get ( section,"Bo‘lim topilmadi.")

async def cmd_super ( update,ctx ) :
    ensure_user ( update.effective_user)
    if not is_super ( update.effective_user.id ):
        return await update.effective_message.reply_text ( "⛔ Bu bo‘lim faqat Super Ega uchun.")
    uc=one ( "SELECT COUNT ( *) n FROM users" ) ["n"]; gc=one ( "SELECT COUNT ( *) n FROM groups" ) ["n"]
    try:
        sb=await ctx.bot.get_my_star_balance ( )
        real=getattr ( sb,"amount",sb)
    except Exception: real="API orqali olinmadi"
    await update.effective_message.reply_text(
        f"👑 VERITAS SUPER EGA\n\nFoydalanuvchilar: {uc}\nGuruhlar: {gc}\nBot real Stars: {real}\n"
        f"Super Egalar: {', '.join ( map ( str,SUPER_OWNERS )  ) }"
    )

async def topup ( update,ctx,amount ) :
    if update.effective_chat.type!="private":
        return await update.effective_message.reply_text ( "⭐ Hisobni private kabinetda to‘ldiring.")
    if amount not in TOPUPS:
        return await update.effective_message.reply_text ( "Miqdor: "+", ".join ( map ( str,TOPUPS )  ) )
    payload=f"topup:{update.effective_user.id}:{amount}:{now (  ) }"
    await ctx.bot.send_invoice(
        chat_id=update.effective_chat.id,title="Veritas Stars krediti",
        description=f"Veritas kabinetiga {amount} ⭐ kredit",
        payload=payload,currency="XTR",prices=[LabeledPrice ( "Stars",amount ) ]
    )

async def precheckout ( update,ctx ) :
    q=update.pre_checkout_query
    ok=q.invoice_payload.startswith ( "topup:")
    await q.answer ( ok=ok,error_message=None if ok else "Noto‘g‘ri to‘lov.")

async def paid ( update,ctx ) :
    ensure_user ( update.effective_user)
    p=update.effective_message.successful_payment
    if not p or p.currency!="XTR" or not p.invoice_payload.startswith ( "topup:" ) : return
    if one ( "SELECT 1 FROM payments WHERE charge_id=?", ( p.telegram_payment_charge_id, )  ) : return
    with db ( ) as c:
        c.execute ( "INSERT INTO payments ( charge_id,user_id,amount,payload,created_at) VALUES ( ?,?,?,?,? ) ",
                  (p.telegram_payment_charge_id,update.effective_user.id,p.total_amount,p.invoice_payload,now (  )  ) )
    wallet_change ( update.effective_user.id,p.total_amount,"topup",ref=p.telegram_payment_charge_id)
    await update.effective_message.reply_text ( f"✅ {p.total_amount} ⭐ kredit qo‘shildi.\nBalans: {wallet ( update.effective_user.id ) } ⭐")

async def show_me ( update,ctx ) :
    u=update.effective_user; ensure_user ( u)
    chat=update.effective_chat
    txt=global_profile_text ( u )
    if chat.type in ("group","supergroup" ) :
        ensure_group ( chat )
        r=one ( "SELECT title FROM members WHERE chat_id=? AND user_id=?", ( chat.id,u.id ) )
        custom=( r["title"] if r else "" ) or ""
        if custom:
            txt += f"\n🎖 Guruh unvoni: {custom}"
    await update.effective_message.reply_text ( txt)

async def title_command ( update,ctx,cmd,args ) :
    chat=update.effective_chat; msg=update.effective_message; actor=update.effective_user
    if chat.type not in ("group","supergroup" ) :
        return await msg.reply_text ( "⛔ Unvon faqat guruhda boshqariladi.")
    ensure_group ( chat ) ; ensure_user ( actor)
    if not await can_manage ( ctx.bot,chat.id,actor.id ) :
        return await msg.reply_text ( "⛔ Sizda unvon boshqarish huquqi yo‘q.")
    target=replied ( update)
    if not target or not target.from_user:
        return await msg.reply_text ( "↩️ Foydalanuvchi xabariga reply qiling.")
    tu=target.from_user
    if tu.id in SUPER_OWNERS:
        return await msg.reply_text ( "👑 Super Ega unvonini o‘zgartirib bo‘lmaydi.")
    execute ( """INSERT OR IGNORE INTO members ( chat_id,user_id,xp,messages,daily,weekly,title)
               VALUES ( ?,?,0,0,0,0,'' ) """, ( chat.id,tu.id ) )
    if cmd=="unvon":
        title=" ".join ( args ) .strip ( )
        if not title: return await msg.reply_text ( "Misol: *unvon Kitobxon")
        if len ( title ) >40: return await msg.reply_text ( "❗ Unvon 40 belgidan uzun bo‘lmasin.")
        if title.casefold (  ) .replace ( "👑","" ) .strip (  ) .replace ( " ","" ) =="superega":
            return await msg.reply_text ( "⛔ «Super Ega» unvoni himoyalangan.")
        execute ( "UPDATE members SET title=? WHERE chat_id=? AND user_id=?", ( title,chat.id,tu.id ) )
        audit ( actor.id,chat.id,"title_set",f"{tu.id}: {title}")
        return await msg.reply_text ( f"🎖 {tu.full_name} uchun unvon: «{title}»")
    execute ( "UPDATE members SET title='' WHERE chat_id=? AND user_id=?", ( chat.id,tu.id ) )
    audit ( actor.id,chat.id,"title_removed",str ( tu.id ) )
    await msg.reply_text ( f"✅ {tu.full_name}ning unvoni olib tashlandi.")

def display_name_row ( r ) :
    name= ( r["first_name"] or "" ) .strip ( ) or "Nomsiz"
    username= ( " @"+r["username"]) if (r["username"] or "" ) .strip ( ) else ""
    return name+username

async def top10_menu ( update,ctx ) :
    if not is_super ( update.effective_user.id ):
        return await update.effective_message.reply_text ( "⛔ TOP mukofot paneli faqat Super Ega uchun.")
    kb=InlineKeyboardMarkup ( [[
        InlineKeyboardButton ( "🎁 Giftli",callback_data=f"topgift:{update.effective_chat.id}" ) ,
        InlineKeyboardButton ( "🏆 Giftsiz",callback_data=f"topplain:{update.effective_chat.id}")
    ]])
    await update.effective_message.reply_text(
        "🏆 TOP-10 yakunlash usulini tanlang:\n\n"
        "🎁 Giftli — TOP-3 ga 50 ⭐ lik haqiqiy Telegram Gift.\n"
        "🏆 Giftsiz — faqat TOP-10 natijasi.",
        reply_markup=kb
    )

async def top10_result ( bot,chat_id,with_gifts=False,actor_id=None ) :
    rows=all_ ( """SELECT m.user_id,m.messages,m.xp,m.title,u.first_name,u.username
                 FROM members m LEFT JOIN users u ON u.user_id=m.user_id
                 WHERE m.chat_id=? ORDER BY m.messages DESC LIMIT 10""", ( chat_id, ) )
    if not rows:
        await bot.send_message ( chat_id,"🏆 TOP-10 uchun ma’lumot yo‘q.")
        return
    lines=["🏆 TOP-10"]
    for i,r in enumerate ( rows ) :
        lines.append ( f"{i+1}. {display_name_row ( r ) } — {r['messages']} xabar")
    await bot.send_message ( chat_id,"\n".join ( lines ) )
    if not with_gifts: return
    try:
        available=await bot.get_available_gifts ( )
        gift=next (  ( g for g in available.gifts
                   if int ( getattr ( g,"star_count",0 )  ) ==50
                   and (getattr ( g,"remaining_count",None) is None or getattr ( g,"remaining_count",0 ) >0 )  ) ,None)
    except Exception as e:
        await bot.send_message ( chat_id,f"❌ Giftlar olinmadi: {e}" ) ; return
    if not gift:
        await bot.send_message ( chat_id,"❌ Hozir 50 ⭐ lik Telegram Gift mavjud emas." ) ; return
    cost=50*min ( 3,len ( rows ) )
    if actor_id is None or wallet ( actor_id ) <cost:
        await bot.send_message ( chat_id,f"❌ Super Ega kreditida kamida {cost} ⭐ kerak." ) ; return
    sent=[]
    for r in rows[:3]:
        uid=int ( r["user_id"])
        if not wallet_change ( actor_id,-50,"top10_gift_pending",uid,meta={"gift_id":str ( gift.id ) } ) :
            break
        try:
            await bot.send_gift ( user_id=uid,gift_id=gift.id,text="🏆 Veritas TOP-3 mukofoti")
            sent.append ( display_name_row ( r ) )
        except Exception:
            wallet_change ( actor_id,50,"top10_gift_rollback",uid)
    await bot.send_message ( chat_id,
        "🎁 TOP-3 Gift natijasi:\n"+ ( "\n".join ( "✅ "+x for x in sent) if sent else "Gift yuborilmadi." ) )

def parse_duration ( value ) :
    """10m, 2h, 1d, 1w kabi vaqtni sekundga aylantiradi."""
    if not value: return 0
    m=re.fullmatch ( r" ( \d+ )  ( s|m|h|d|w ) ",str ( value ) .strip (  ) .lower (  ) )
    if not m: return 0
    n=int ( m.group ( 1 )  ) ; unit=m.group ( 2)
    return n*{"s":1,"m":60,"h":3600,"d":86400,"w":604800}[unit]

def moderation_settings ( chat_id ) :
    execute ( "INSERT OR IGNORE INTO moderation_settings ( chat_id) VALUES ( ? ) ", ( chat_id, ) )
    return one ( "SELECT * FROM moderation_settings WHERE chat_id=?", ( chat_id, ) )

def modlog ( chat_id,actor_id,target_id,action,reason="",duration=0 ) :
    execute ( "INSERT INTO moderation_log ( chat_id,actor_id,target_id,action,reason,duration,created_at) VALUES ( ?,?,?,?,?,?,? ) ",
            (chat_id,actor_id or 0,target_id or 0,action,reason or "",int ( duration or 0 ) ,now (  )  ) )

async def purge_command ( update,ctx,args ) :
    chat=update.effective_chat; msg=update.effective_message; actor=update.effective_user
    if chat.type not in ("group","supergroup" ) : return
    if not await can_manage ( ctx.bot,chat.id,actor.id ) :
        return await msg.reply_text ( "⛔ Ruxsat yo‘q.")
    limit=0
    if args and args[0].isdigit (  ) : limit=min ( 200,max ( 1,int ( args[0] )  ) )
    elif msg.reply_to_message: limit=max ( 1,msg.message_id-msg.reply_to_message.message_id+1)
    else: return await msg.reply_text ( "Misol: *purge 20 yoki eski xabarga reply qilib *purge")
    deleted=0
    start=max ( 1,msg.message_id-limit+1)
    for mid in range ( msg.message_id,start-1,-1 ) :
        try:
            await ctx.bot.delete_message ( chat.id,mid ) ; deleted+=1
        except TelegramError: pass
    modlog ( chat.id,actor.id,0,"purge",f"{deleted} xabar")

async def moderation_config_command ( update,ctx,cmd,args ) :
    chat=update.effective_chat; msg=update.effective_message; actor=update.effective_user
    if chat.type not in ("group","supergroup" ) : return await msg.reply_text ( "Bu buyruq guruh uchun.")
    if not await can_manage ( ctx.bot,chat.id,actor.id ) : return await msg.reply_text ( "⛔ Ruxsat yo‘q.")
    st=moderation_settings ( chat.id)
    if cmd=="warnlimit":
        if not args or not args[0].isdigit ( ) or not 1<=int ( args[0] ) <=10: return await msg.reply_text ( "Misol: *warnlimit 3")
        execute ( "UPDATE moderation_settings SET warn_limit=? WHERE chat_id=?", ( int ( args[0] ) ,chat.id )  ) ; return await msg.reply_text ( "✅ Warn limiti saqlandi.")
    if cmd=="warnaction":
        if not args or args[0].lower ( ) not in {"ban","kick","mute"}: return await msg.reply_text ( "Misol: *warnaction ban / kick / mute")
        execute ( "UPDATE moderation_settings SET warn_action=? WHERE chat_id=?", ( args[0].lower (  ) ,chat.id )  ) ; return await msg.reply_text ( "✅ Warn jazosi saqlandi.")
    if cmd in {"cleanservice","antirepeat"}:
        if not args or args[0].lower ( ) not in {"on","off"}: return await msg.reply_text ( f"*{cmd} on/off")
        col="clean_service" if cmd=="cleanservice" else "antirepeat"
        execute ( f"UPDATE moderation_settings SET {col}=? WHERE chat_id=?", ( 1 if args[0].lower (  ) =="on" else 0,chat.id )  ) ; return await msg.reply_text ( "✅ Saqlandi.")
    if cmd=="modlog":
        rows=all_ ( "SELECT * FROM moderation_log WHERE chat_id=? ORDER BY id DESC LIMIT 15", ( chat.id, ) )
        if not rows: return await msg.reply_text ( "📋 Moderatsiya logi bo‘sh.")
        lines=["📋 SO‘NGGI MODERATSIYA AMALLARI"]
        for r in rows: lines.append ( f"• {r['action']} | target {r['target_id']} | admin {r['actor_id']}"+ ( f" | {r['reason']}" if r['reason'] else "" ) )
        return await msg.reply_text ( "\n".join ( lines ) )

async def group_action ( update,ctx,cmd,arg ) :
    chat=update.effective_chat; u=update.effective_user; msg=update.effective_message
    ensure_group ( chat ) ; ensure_user ( u)
    if not await can_manage ( ctx.bot,chat.id,u.id ) :
        return await msg.reply_text ( "⛔ Sizda bu amal uchun ruxsat yo‘q.")
    target=replied ( update)
    if cmd in {"warn","unwarn","clearwarns","mute","unmute","kick","ban","unban","del","ruxsat","ruxsatsiz","admin","unadmin","approve","unapprove"} and not target:
        return await msg.reply_text ( "↩️ Foydalanuvchi xabariga reply qiling.")
    if cmd=="del":
        try: await target.delete (  ) ; await msg.delete ( )
        except TelegramError: pass
        return
    tu=target.from_user if target else None
    if tu and cmd in {"warn","mute","kick","ban"} and await protected ( ctx.bot,chat.id,tu.id ) :
        return await msg.reply_text ( "🛡 Himoyalangan foydalanuvchi.")
    try:
        if cmd=="warn":
            reason=" ".join ( arg ) .strip ( ) or "Sabab ko‘rsatilmagan"
            execute ( """INSERT INTO warns ( chat_id,user_id,count) VALUES ( ?,?,1)
            ON CONFLICT ( chat_id,user_id) DO UPDATE SET count=count+1""", ( chat.id,tu.id ) )
            execute ( "INSERT INTO warn_records ( chat_id,user_id,actor_id,reason,created_at) VALUES ( ?,?,?,?,? ) ", ( chat.id,tu.id,u.id,reason,now (  )  ) )
            n=one ( "SELECT count FROM warns WHERE chat_id=? AND user_id=?", ( chat.id,tu.id )  ) ["count"]
            st=moderation_settings ( chat.id ) ; limit=int ( st["warn_limit"] or 3 ) ; action=st["warn_action"] or "ban"
            modlog ( chat.id,u.id,tu.id,"warn",reason)
            if n>=limit:
                execute ( "DELETE FROM warns WHERE chat_id=? AND user_id=?", ( chat.id,tu.id ) )
                if action=="kick":
                    await ctx.bot.ban_chat_member ( chat.id,tu.id ) ; await ctx.bot.unban_chat_member ( chat.id,tu.id)
                elif action=="mute":
                    sec=int ( st["warn_mute_seconds"] or 3600)
                    await ctx.bot.restrict_chat_member ( chat.id,tu.id,ChatPermissions ( can_send_messages=False ) ,until_date=datetime.now ( timezone.utc ) +timedelta ( seconds=sec ) )
                else: await ctx.bot.ban_chat_member ( chat.id,tu.id)
                modlog ( chat.id,u.id,tu.id,"warn_"+action,reason)
                return await msg.reply_text ( f"⚠️ {tu.full_name}: {limit}/{limit} warn → {action}.\nSabab: {reason}")
            return await msg.reply_text ( f"⚠️ {tu.full_name}: {n}/{limit} warn.\nSabab: {reason}")
        if cmd=="unwarn":
            execute ( "UPDATE warns SET count=MAX ( count-1,0) WHERE chat_id=? AND user_id=?", ( chat.id,tu.id ) )
        elif cmd=="clearwarns": execute ( "DELETE FROM warns WHERE chat_id=? AND user_id=?", ( chat.id,tu.id ) )
        elif cmd=="mute":
            sec=parse_duration ( arg[0]) if arg else 0
            until= ( datetime.now ( timezone.utc ) +timedelta ( seconds=sec ) ) if sec else None
            await ctx.bot.restrict_chat_member ( chat.id,tu.id,ChatPermissions ( can_send_messages=False ) ,until_date=until)
            reason=" ".join ( arg[1:] if sec else arg ) .strip ( )
            modlog ( chat.id,u.id,tu.id,"mute",reason,sec)
        elif cmd=="unmute":
            await ctx.bot.restrict_chat_member ( chat.id,tu.id,ChatPermissions ( can_send_messages=True,can_send_audios=True,can_send_documents=True,can_send_photos=True,can_send_videos=True,can_send_video_notes=True,can_send_voice_notes=True,can_send_polls=True,can_send_other_messages=True,can_add_web_page_previews=True,can_invite_users=True ) )
        elif cmd=="kick":
            await ctx.bot.ban_chat_member ( chat.id,tu.id ) ; await ctx.bot.unban_chat_member ( chat.id,tu.id)
        elif cmd=="ban":
            sec=parse_duration ( arg[0]) if arg else 0
            until= ( datetime.now ( timezone.utc ) +timedelta ( seconds=sec ) ) if sec else None
            await ctx.bot.ban_chat_member ( chat.id,tu.id,until_date=until)
            reason=" ".join ( arg[1:] if sec else arg ) .strip ( )
            modlog ( chat.id,u.id,tu.id,"ban",reason,sec)
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
        await msg.reply_text ( "✅ Bajarildi.")
    except TelegramError as e: await msg.reply_text ( f"❌ Telegram: {e}")

async def settings_command ( update,ctx,cmd,args ) :
    chat=update.effective_chat; msg=update.effective_message; uid=update.effective_user.id
    ensure_group ( chat)
    if not await can_manage ( ctx.bot,chat.id,uid ) : return await msg.reply_text ( "⛔ Ruxsat yo‘q.")
    if cmd in ("links","antiflood","reports","welcome","goodbye" ) :
        if not args or args[0].lower ( ) not in ("on","off" ) : return await msg.reply_text ( f"*{cmd} on/off")
        execute ( f"UPDATE groups SET {cmd}=? WHERE chat_id=?", ( 1 if args[0].lower (  ) =="on" else 0,chat.id ) )
        return await msg.reply_text ( "✅ Saqlandi.")
    if cmd=="flood":
        n=int ( args[0]) if args and args[0].isdigit ( ) else 0
        if not 3<=n<=20: return await msg.reply_text ( "*flood 3..20")
        execute ( "UPDATE groups SET flood_limit=? WHERE chat_id=?", ( n,chat.id )  ) ; return await msg.reply_text ( "✅ Saqlandi.")
    if cmd=="setrules":
        text=" ".join ( args ) .strip ( )
        execute ( "UPDATE groups SET rules=? WHERE chat_id=?", ( text,chat.id )  ) ; return await msg.reply_text ( "✅ Qoidalar saqlandi.")
    if cmd=="lock" and args:
        typ=args[0].lower (  ) ; r=one ( "SELECT locks FROM groups WHERE chat_id=?", ( chat.id, )  ) ; d=json.loads ( r["locks"] or "{}" ) ; d[typ]=True
        execute ( "UPDATE groups SET locks=? WHERE chat_id=?", ( json.dumps ( d ) ,chat.id )  ) ; return await msg.reply_text ( f"🔒 {typ}")
    if cmd=="unlock" and args:
        typ=args[0].lower (  ) ; r=one ( "SELECT locks FROM groups WHERE chat_id=?", ( chat.id, )  ) ; d=json.loads ( r["locks"] or "{}" ) ; d.pop ( typ,None)
        execute ( "UPDATE groups SET locks=? WHERE chat_id=?", ( json.dumps ( d ) ,chat.id )  ) ; return await msg.reply_text ( f"🔓 {typ}")
    if cmd=="blacklist" and args:
        w=" ".join ( args ) .lower (  ) ; execute ( "INSERT OR IGNORE INTO blacklist VALUES ( ?,? ) ", ( chat.id,w )  ) ; return await msg.reply_text ( "✅ Blacklistga qo‘shildi.")
    if cmd=="unblacklist" and args:
        w=" ".join ( args ) .lower (  ) ; execute ( "DELETE FROM blacklist WHERE chat_id=? AND word=?", ( chat.id,w )  ) ; return await msg.reply_text ( "✅ O‘chirildi.")
    if cmd=="filter" and len ( args ) >=2:
        key=args[0].lower (  ) ; response=" ".join ( args[1:])
        execute ( "INSERT OR REPLACE INTO filters_ VALUES ( ?,?,? ) ", ( chat.id,key,response )  ) ; return await msg.reply_text ( "✅ Filter saqlandi.")
    if cmd=="stop" and args:
        execute ( "DELETE FROM filters_ WHERE chat_id=? AND key=?", ( chat.id,args[0].lower (  )  )  ) ; return await msg.reply_text ( "✅ Filter o‘chirildi.")
    if cmd=="stopall": execute ( "DELETE FROM filters_ WHERE chat_id=?", ( chat.id, )  ) ; return await msg.reply_text ( "✅ Barcha filterlar o‘chirildi.")
    if cmd=="save" and len ( args ) >=2:
        execute ( "INSERT OR REPLACE INTO notes VALUES ( ?,?,? ) ", ( chat.id,args[0].lower (  ) ," ".join ( args[1:] )  )  ) ; return await msg.reply_text ( "✅ Note saqlandi.")
    if cmd=="clear" and args:
        execute ( "DELETE FROM notes WHERE chat_id=? AND name=?", ( chat.id,args[0].lower (  )  )  ) ; return await msg.reply_text ( "✅ Note o‘chirildi.")

async def info_command ( update,ctx,cmd,args ) :
    chat=update.effective_chat; msg=update.effective_message
    if cmd=="rules":
        r=one ( "SELECT rules FROM groups WHERE chat_id=?", ( chat.id, )  ) ; return await msg.reply_text (  ( r["rules"] if r else "") or "Qoidalar hali yozilmagan.")
    if cmd=="admins":
        admins=await ctx.bot.get_chat_administrators ( chat.id ) ; va=all_ ( "SELECT user_id FROM vadmins WHERE chat_id=?", ( chat.id, ) )
        s="👮 Telegram adminlar:\n"+"\n".join ( f"• {x.user.full_name}" for x in admins)
        if va: s+="\n\n🪶 Veritas admin ID:\n"+"\n".join ( str ( x["user_id"]) for x in va)
        return await msg.reply_text ( s)
    if cmd=="warns":
        t=replied ( update ) ; uid=t.from_user.id if t else update.effective_user.id
        r=one ( "SELECT count FROM warns WHERE chat_id=? AND user_id=?", ( chat.id,uid )  ) ; return await msg.reply_text ( f"⚠️ Warn: {r['count'] if r else 0}/3")
    if cmd=="blacklists":
        rows=all_ ( "SELECT word FROM blacklist WHERE chat_id=? ORDER BY word", ( chat.id, )  ) ; return await msg.reply_text ( "🚫 "+ ( ", ".join ( r["word"] for r in rows) or "Bo‘sh" ) )
    if cmd=="locks":
        r=one ( "SELECT locks FROM groups WHERE chat_id=?", ( chat.id, )  ) ; d=json.loads ( r["locks"] or "{}") if r else {}
        return await msg.reply_text ( "🔐 "+ ( ", ".join ( d.keys (  ) ) or "Lock yo‘q" ) )
    if cmd=="approved":
        rows=all_ ( "SELECT user_id FROM approved WHERE chat_id=?", ( chat.id, )  ) ; return await msg.reply_text ( "✅ "+ ( ", ".join ( str ( r["user_id"]) for r in rows) or "Bo‘sh" ) )
    if cmd=="filters":
        rows=all_ ( "SELECT key FROM filters_ WHERE chat_id=?", ( chat.id, )  ) ; return await msg.reply_text ( "💬 "+ ( ", ".join ( r["key"] for r in rows) or "Bo‘sh" ) )
    if cmd=="notes":
        rows=all_ ( "SELECT name FROM notes WHERE chat_id=?", ( chat.id, )  ) ; return await msg.reply_text ( "📝 "+ ( ", ".join ( r["name"] for r in rows) or "Bo‘sh" ) )
    if cmd=="get" and args:
        r=one ( "SELECT text FROM notes WHERE chat_id=? AND name=?", ( chat.id,args[0].lower (  )  )  ) ; return await msg.reply_text ( r["text"] if r else "Topilmadi.")
    if cmd=="aktiv":
        n=min ( 50,max ( 1,int ( args[0]) if args and args[0].isdigit ( ) else 10 ) )
        return await msg.reply_text ( global_active_text ( min ( n,10 ) ) )

async def report_cmd ( update,ctx ) :
    if not replied ( update ) : return await update.effective_message.reply_text ( "↩️ Shikoyat qilinadigan xabarga reply qiling.")
    r=one ( "SELECT reports FROM groups WHERE chat_id=?", ( update.effective_chat.id, ) )
    if r and not r["reports"]: return
    admins=await ctx.bot.get_chat_administrators ( update.effective_chat.id)
    tags=" ".join ( "@"+a.user.username for a in admins if a.user.username)
    await update.effective_message.reply_text ( f"📢 Report: {tags or 'adminlar'}")

async def gift_send ( update,ctx,args ) :
    t=replied ( update)
    if not t or not t.from_user: return await update.effective_message.reply_text ( "↩️ Gift oluvchining xabariga reply qiling.")
    sender=update.effective_user.id; target=t.from_user.id
    try:
        gifts=await ctx.bot.get_available_gifts ( )
        gl=list ( gifts.gifts)
    except Exception as e: return await update.effective_message.reply_text ( f"❌ Gift ro‘yxati olinmadi: {e}")
    price=int ( args[0]) if args and args[0].isdigit ( ) else None
    candidates=[g for g in gl if (price is None or getattr ( g,"star_count",None ) ==price) and (getattr ( g,"remaining_count",None) is None or getattr ( g,"remaining_count",0 ) >0 ) ]
    if not candidates:
        prices=sorted ( {getattr ( g,"star_count",0) for g in gl if getattr ( g,"star_count",0 ) })
        return await update.effective_message.reply_text ( "🎁 Mavjud narxlar: "+", ".join ( map ( str,prices[:30] )  ) )
    g=candidates[0]; cost=int ( g.star_count)
    if wallet ( sender ) <cost: return await update.effective_message.reply_text ( f"⭐ Kredit yetarli emas. Kerak: {cost}, sizda: {wallet ( sender ) }")
    tx_ref=f"gift:{sender}:{target}:{now (  ) }:{random.randint ( 100000,999999 ) }"
    if not wallet_change ( sender,-cost,"gift_pending",target,ref=tx_ref,meta={"gift_id":str ( g.id ) } ) : return
    try:
        await ctx.bot.send_gift ( user_id=target,gift_id=g.id,text=f"🎁 Veritas orqali {update.effective_user.first_name}dan sovg‘a")
        execute ( "UPDATE tx SET kind='gift' WHERE user_id=? AND ref=? AND kind='gift_pending'", ( sender,tx_ref ) )
        await update.effective_message.reply_text ( f"✅ Haqiqiy Telegram Gift yuborildi: {cost} ⭐")
    except Exception as e:
        wallet_change ( sender,cost,"gift_rollback",target)
        await update.effective_message.reply_text ( f"❌ Gift yuborilmadi, kredit qaytarildi.\n{e}")

async def premium_send ( update,ctx,args ) :
    t=replied ( update)
    if not t or not t.from_user: return await update.effective_message.reply_text ( "↩️ Premium oluvchiga reply qiling.")
    m=int ( args[0]) if args and args[0].isdigit ( ) else 0
    if m not in PREMIUM: return await update.effective_message.reply_text ( "*premium 3 / 6 / 12")
    cost=PREMIUM[m]; sender=update.effective_user.id; target=t.from_user.id
    if wallet ( sender ) <cost: return await update.effective_message.reply_text ( f"⭐ Kredit yetarli emas. Kerak: {cost}")
    tx_ref=f"premium:{sender}:{target}:{now (  ) }:{random.randint ( 100000,999999 ) }"
    if not wallet_change ( sender,-cost,"premium_pending",target,ref=tx_ref ) : return
    try:
        await ctx.bot.gift_premium_subscription ( user_id=target,month_count=m,star_count=cost,text="💎 Veritas orqali Premium sovg‘a")
        execute ( "UPDATE tx SET kind='premium' WHERE user_id=? AND ref=? AND kind='premium_pending'", ( sender,tx_ref ) )
        await update.effective_message.reply_text ( f"✅ {m} oylik Telegram Premium yuborildi.")
    except Exception as e:
        wallet_change ( sender,cost,"premium_rollback",target)
        await update.effective_message.reply_text ( f"❌ Premium yuborilmadi, kredit qaytarildi.\n{e}")

async def superadmin_command ( update,ctx,cmd ) :
    msg=update.effective_message; actor=update.effective_user
    if not msg or not actor: return
    if cmd=="superadmins":
        rows=all_ ( "SELECT user_id,added_by,created_at FROM super_admins ORDER BY created_at" )
        lines=["👑 SUPER EGALAR"]
        creator_names={5859289233:"Sakranum",7056675943:"Vasatiya"}
        for sid in sorted ( SUPER_OWNERS ): lines.append ( f"• {creator_names.get ( sid,'Super Ega' ) } — {sid}" )
        lines.append ( "\n🛡 SUPER ADMINLAR" )
        if not rows: lines.append ( "• Hozircha yo‘q" )
        else:
            for r in rows:
                try:
                    ch=await ctx.bot.get_chat ( r["user_id"] ); name=ch.full_name or ch.title or str ( r["user_id"])
                except Exception: name=str ( r["user_id"] )
                lines.append ( f"• {name} — {r['user_id']}" )
        return await msg.reply_text ( "\n".join ( lines ) )
    # Xavfsizlik: tayinlash va olib tashlash faqat haqiqiy Super Ega tomonidan.
    if actor.id not in SUPER_OWNERS:
        return await msg.reply_text ( "⛔ Super Admin qo‘shish yoki olish faqat Super Ega uchun." )
    t=replied ( update )
    if not t or not t.from_user:
        return await msg.reply_text ( "↩️ Foydalanuvchining xabariga reply qiling.\nMisol: *superadmin" if cmd=="superadmin" else "↩️ Super Admin xabariga reply qilib *unsuperadmin yozing." )
    target=t.from_user
    ensure_user ( target )
    if target.id in SUPER_OWNERS:
        return await msg.reply_text ( "👑 Bu foydalanuvchi Super Ega. Uning huquqi bu buyruq bilan o‘zgarmaydi." )
    if cmd=="superadmin":
        execute ( "INSERT INTO super_admins ( user_id,added_by,created_at) VALUES ( ?,?,? ) ON CONFLICT ( user_id ) DO UPDATE SET added_by=excluded.added_by,created_at=excluded.created_at", ( target.id,actor.id,now ( ) ) )
        audit ( actor.id,update.effective_chat.id,"superadmin_add",str ( target.id ) )
        return await msg.reply_text ( f"🛡 {target.full_name} Super Admin qilindi.\n🆔 {target.id}" )
    execute ( "DELETE FROM super_admins WHERE user_id=?", ( target.id, ) )
    audit ( actor.id,update.effective_chat.id,"superadmin_remove",str ( target.id ) )
    return await msg.reply_text ( f"✅ {target.full_name} Super Adminlikdan olindi.\n🆔 {target.id}" )

async def ai_premium_gift_command ( update, ctx ) :
    msg = update.effective_message
    actor = update.effective_user
    if not actor:
        return
    t = replied ( update)
    if not t or not t.from_user:
        return await msg.reply_text ( "↩️ AI Premium oluvchining xabariga reply qilib *ai.p yozing.")
    target = t.from_user
    if target.is_bot:
        return await msg.reply_text ( "❌ Botga AI Premium sovg‘a qilib bo‘lmaydi.")
    if target.id == actor.id:
        return await msg.reply_text ( "❌ AI Premiumni o‘zingizga *ai.p orqali sovg‘a qilib bo‘lmaydi.")
    ensure_user ( target)
    # Super boshqaruv AI'dan allaqachon cheksiz foydalanadi.
    if is_super ( target.id ) :
        return await msg.reply_text ( f"👑 {target.full_name} uchun AI allaqachon cheksiz faol.")
    ts = now ( )
    with db ( ) as c:
        r = c.execute ( "SELECT wallet FROM users WHERE user_id=?", (actor.id, )  ) .fetchone ( )
        bal = int ( r["wallet"]) if r else 0
        if bal < AI_PRIVATE_PRICE:
            return await msg.reply_text ( f"❌ Kredit yetarli emas. Kerak: {AI_PRIVATE_PRICE} ⭐\nBalans: {bal} ⭐")
        old = c.execute ( "SELECT paid_until FROM ai_user_subscriptions WHERE user_id=?", (target.id, )  ) .fetchone ( )
        old_until = int ( old["paid_until"]) if old else 0
        until = max ( ts, old_until) + AI_PRIVATE_DAYS * 86400
        c.execute ( "UPDATE users SET wallet=wallet-? WHERE user_id=?", (AI_PRIVATE_PRICE, actor.id ) )
        c.execute ( "INSERT INTO tx ( user_id,kind,amount,target_id,ref,created_at,meta) VALUES ( ?,?,?,?,?,?,? ) ",
                  (actor.id, "ai_private_gift_30d", -AI_PRIVATE_PRICE, target.id, None, ts, json.dumps ( {"days": AI_PRIVATE_DAYS}, ensure_ascii=False )  ) )
        c.execute ( "INSERT INTO ai_user_subscriptions ( user_id,paid_until,updated_at) VALUES ( ?,?,?) "
                  "ON CONFLICT ( user_id) DO UPDATE SET paid_until=excluded.paid_until,updated_at=excluded.updated_at",
                  (target.id, until, ts ) )
    audit ( actor.id, update.effective_chat.id, "ai_private_gift", f"target={target.id},days={AI_PRIVATE_DAYS}")
    return await msg.reply_text(
        f"🎁 {target.full_name}ga Veritas AI Premium berildi.\n"
        f"💎 {AI_PRIVATE_PRICE} ⭐ yechildi\n"
        f"📅 {AI_PRIVATE_DAYS} kun — {fmt_until ( until ) } gacha\n"
        f"⭐ Qolgan balans: {wallet ( actor.id ) } ⭐"
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
        return await msg.reply_text ( qadr_top_text ( 10 ) )
    if cmd=="hadis":
        return await hadith_command ( update,ctx,args)
    if cmd=="add.hadis":
        return await add_hadith_command ( update,ctx)
    if cmd=="del.hadis":
        return await delete_hadith_command ( update,ctx,args)
    if cmd=="ai":
        if update.effective_chat.type not in ("group","supergroup" ) :
            return await msg.reply_text ( "🤖 Shaxsiy Veritas AI uchun bosh menyudagi «Veritas AI» tugmasidan foydalaning." )
        until=ai_group_until ( update.effective_chat.id )
        status=( "✅ FAOL\n📅 "+fmt_until ( until ) ) if until>now ( ) else "❌ FAOL EMAS"
        trial= ( "🎁 Birinchi 30 kun — BEPUL" if not ai_group_trial_used ( update.effective_chat.id ) else "⭐ Keyingi 30 kun — 100 ⭐")
        return await msg.reply_text ( f"🤖 VERITAS AI — GURUH\n\n{status}\n\n{trial}",reply_markup=ai_group_menu ( update.effective_chat.id,update.effective_user.id ) )
    if update.effective_chat.type not in ("group","supergroup" ) :
        return await msg.reply_text ( "Bu buyruq guruh uchun.")
    if cmd=="purge": return await purge_command ( update,ctx,args)
    if cmd in {"warnlimit","warnaction","cleanservice","antirepeat","modlog"}:
        return await moderation_config_command ( update,ctx,cmd,args)
    if cmd=="pin":
        if not await can_manage ( ctx.bot,update.effective_chat.id,update.effective_user.id ) : return await msg.reply_text ( "⛔ Ruxsat yo‘q.")
        t=replied ( update)
        if not t: return await msg.reply_text ( "↩️ Pin qilinadigan xabarga reply qiling.")
        await ctx.bot.pin_chat_message ( update.effective_chat.id,t.message_id ) ; modlog ( update.effective_chat.id,update.effective_user.id,0,"pin" ) ; return await msg.reply_text ( "📌 Pin qilindi.")
    if cmd=="unpin":
        if not await can_manage ( ctx.bot,update.effective_chat.id,update.effective_user.id ) : return await msg.reply_text ( "⛔ Ruxsat yo‘q.")
        await ctx.bot.unpin_chat_message ( update.effective_chat.id ) ; modlog ( update.effective_chat.id,update.effective_user.id,0,"unpin" ) ; return await msg.reply_text ( "📌 Pin olib tashlandi.")
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
        if not g: return await msg.reply_text ( "Faol konkurs yo‘q.")
        execute ( "INSERT OR IGNORE INTO giveaway_entries VALUES ( ?,? ) ", ( g["id"],update.effective_user.id )  ) ; return await msg.reply_text ( "🎉 Ishtirok qabul qilindi.")
    if cmd=="giveaway":
        if not await can_manage ( ctx.bot,update.effective_chat.id,update.effective_user.id ) : return await msg.reply_text ( "⛔ Ruxsat yo‘q.")
        if len ( args ) <4 or args[0]!="gift" or not all ( x.isdigit ( ) for x in args[1:4] ) : return await msg.reply_text ( "*giveaway gift <narx> <daq> <g‘oliblar>")
        price,mins,wins=map ( int,args[1:4])
        execute ( "INSERT INTO giveaways ( chat_id,creator_id,kind,prize,winners,end_at,created_at) VALUES ( ?,?,?,?,?,?,? ) ",
                (update.effective_chat.id,update.effective_user.id,"gift",str ( price ) ,wins,now (  ) +mins*60,now (  )  ) )
        return await msg.reply_text ( f"🎉 Konkurs ochildi: {price} ⭐ Gift | {wins} g‘olib | {mins} daqiqa\n*join bilan qatnashing.")


def _norm_rebus_answer ( text ) :
    text= ( text or "" ) .lower (  ) .strip ( )
    text=text.replace ( "ʻ","'" ) .replace ( "’","'" ) .replace ( "`","'")
    return re.sub ( r"[^a-z0-9а-яёқғҳў' ]+","",text,flags=re.I ) .strip ( )

def _rebus_plan_sync ( answer ) :
    answer= ( answer or "" ) .strip ( )
    prompt=(
        "Telegram uchun rasmli rebus dizaynini tuzing. "
        f"Rebusning ANIQ JAVOBI: {answer}. "
        "Javobni o‘zgartirmang. Faqat JSON qaytaring: "
        '{"hint":"...", "image_prompt":"..."}. '
        "image_prompt rasm generatoriga mo‘ljallangan bo‘lsin: 1:1 kvadrat, chiroyli, kitobiy va toza dizayn; "
        "javobni rasmlar, belgilar, harflarni qo‘shish/ayirish yoki vizual mantiq orqali ifodalasin. "
        "JAVOBNING O‘ZINI rasmga yozmasin. Yuqorida faqat 'VERITAS REBUS' yozuvi bo‘lishi mumkin."
    )
    raw=_openai_response_sync ( prompt ) .strip ( )
    raw=re.sub ( r"^``` ( ?:json ) ?\\s*|\\s*```$","",raw,flags=re.I|re.S)
    try:
        data=json.loads ( raw)
    except Exception:
        m=re.search ( r"\\{.*\\}",raw,re.S)
        if not m: raise RuntimeError ( "AI rebus rejasini JSON ko‘rinishda qaytarmadi")
        data=json.loads ( m.group ( 0 ) )
    hint=str ( data.get ( "hint","" )  ) .strip ( )
    image_prompt=str ( data.get ( "image_prompt","" )  ) .strip ( )
    if not image_prompt:
        raise RuntimeError ( "AI rebus rejasi to‘liq emas")
    return answer,hint,image_prompt

def _rebus_image_sync ( image_prompt ) :
    if not OPENAI_API_KEY:
        raise RuntimeError ( "OPENAI_API_KEY sozlanmagan")
    payload=json.dumps ( {
        "model":REBUS_IMAGE_MODEL,
        "prompt":image_prompt,
        "size":"1024x1024",
        "quality":"medium"
    },ensure_ascii=False ) .encode ( "utf-8")
    req=urllib.request.Request(
        "https://api.openai.com/v1/images/generations",
        data=payload,
        headers={"Authorization":f"Bearer {OPENAI_API_KEY}","Content-Type":"application/json"},
        method="POST"
    )
    with urllib.request.urlopen ( req,timeout=180) as resp:
        data=json.loads ( resp.read (  ) .decode ( "utf-8" ) )
    item= ( data.get ( "data") or [{}] ) [0]
    if item.get ( "b64_json" ) :
        return base64.b64decode ( item["b64_json"])
    if item.get ( "url" ) :
        with urllib.request.urlopen ( item["url"],timeout=120) as resp:
            return resp.read ( )
    raise RuntimeError ( "Rasm generatori rasm qaytarmadi")

async def _remember_rebus_channel_from_group ( ctx,group_id ) :
    """Discussion groupdan unga bog‘langan kanalni topib, DBga saqlaydi."""
    try:
        gr=await ctx.bot.get_chat ( group_id)
        channel_id=getattr ( gr,"linked_chat_id",None)
        if not channel_id:
            return None
        ch=await ctx.bot.get_chat ( channel_id)
        me=await ctx.bot.get_chat_member ( channel_id,ctx.bot.id)
        if me.status not in (ChatMemberStatus.ADMINISTRATOR,ChatMemberStatus.OWNER ) :
            return None
        execute(
            "INSERT INTO rebus_group_channels ( group_id,channel_id,channel_title,updated_at) VALUES ( ?,?,?,?) "
            "ON CONFLICT ( group_id) DO UPDATE SET channel_id=excluded.channel_id,"
            "channel_title=excluded.channel_title,updated_at=excluded.updated_at",
            (group_id,channel_id,ch.title or str ( channel_id ) ,now (  ) )
        )
        return channel_id
    except Exception:
        return None

async def _start_group_rebus_flow ( update,ctx ) :
    msg=update.effective_message; u=update.effective_user; chat=update.effective_chat
    if not msg or not u or chat.type not in ("group","supergroup" ) :
        return False
    if not msg.reply_to_message or not msg.reply_to_message.from_user or msg.reply_to_message.from_user.id!=ctx.bot.id:
        return False
    if (msg.text or "" ) .strip (  ) .lower (  ) !="*rebus":
        return False
    if not is_super ( u.id ) :
        await msg.reply_text ( "⛔ AI Rebus yaratish hozircha Super Ega yoki Super Admin uchun.")
        return True

    # Kanal bog‘langan va Veritas u yerda admin bo‘lsa — kanalga.
    # Aks holda — rebus bevosita shu guruhga joylanadi.
    channel_id=await _remember_rebus_channel_from_group ( ctx,chat.id)
    target_chat_id=int ( channel_id or chat.id)
    STATE[u.id]={
        "mode":"rebus_group_count",
        "group_id":chat.id,
        "group_title":chat.title or str ( chat.id ) ,
        "target_chat_id":target_chat_id,
        "answers":[]
    }
    try:
        place="bog‘langan kanalga" if channel_id else "shu guruhning o‘ziga"
        await ctx.bot.send_message(
            u.id,
            f"🧩 AI REBUS MUSOBAQASI\n\n👥 Guruh: {chat.title or chat.id}\n"
            f"📍 Rebuslar: {place}\n\n"
            "Nechta rebus o‘tkazilsin?\nMasalan: 5 yoki 10"
        )
        await msg.reply_text ( "📩 Shaxsiy chatga yubordim. Rebuslar sonini o‘sha yerda yozing.")
    except TelegramError:
        STATE.pop ( u.id,None)
        await msg.reply_text ( "📩 Avval Veritasning shaxsiy chatiga kirib /start bosing, keyin *rebus ni qayta yuboring.")
    return True

async def _create_and_post_rebus ( ctx,uid,target_chat_id,group_id,answer_text,progress_chat_id,session_id=0,item_no=0 ) :
    try:
        answer,hint,image_prompt=await asyncio.to_thread ( _rebus_plan_sync,answer_text)
        image_bytes=await asyncio.to_thread ( _rebus_image_sync,image_prompt)
        with db ( ) as c:
            cur=c.execute(
                "INSERT INTO rebuses (creator_id,channel_id,answer_group_id,answer,answer_norm,hint,created_at) VALUES (?,?,?,?,?,?,? ) ",
                (uid,target_chat_id,group_id,answer,_norm_rebus_answer ( answer ) ,hint,now (  ) )
            )
            rid=cur.lastrowid
            if session_id and item_no:
                c.execute(
                    "UPDATE rebus_session_items SET rebus_id=?,status='active' WHERE session_id=? AND item_no=?",
                    (rid,session_id,item_no)
                )
                c.execute ( "UPDATE rebus_sessions SET current_no=? WHERE id=?", ( item_no,session_id ) )
        caption=(
            f"🧩 VERITAS REBUS #{rid}"
            + (f" — {item_no}" if session_id else "") +
            "\n\nRasmga qarab yashiringan so‘z yoki iborani toping!\n"
            "💬 Javobni guruhga yozing."
        )
        if hint:
            caption+=f"\n\n💡 Ishora: {hint}"
        sent=await ctx.bot.send_photo(
            chat_id=target_chat_id, photo=io.BytesIO ( image_bytes ) , caption=caption
        )
        execute ( "UPDATE rebuses SET channel_message_id=? WHERE id=?", ( sent.message_id,rid ) )
        if progress_chat_id:
            where="kanalga" if target_chat_id!=group_id else "guruhga"
            await ctx.bot.send_message(
                progress_chat_id,
                f"✅ {item_no if item_no else ''}-rebus {where} joylandi. Javob guruhda tekshiriladi."
            )
        return rid
    except Exception:
        log.exception ( "AI rebus yaratish xatosi")
        if session_id and item_no:
            execute ( "UPDATE rebus_session_items SET status='error' WHERE session_id=? AND item_no=?", ( session_id,item_no ) )
        if progress_chat_id:
            await ctx.bot.send_message ( progress_chat_id,"⚠️ Rebus yaratishda xato bo‘ldi. Qayta urinib ko‘ring.")
        return 0

async def _launch_session_item ( ctx,session_id,item_no ) :
    ses=one ( "SELECT * FROM rebus_sessions WHERE id=? AND status='active'", ( session_id, ) )
    item=one ( "SELECT * FROM rebus_session_items WHERE session_id=? AND item_no=?", ( session_id,item_no ) )
    if not ses or not item: return
    await _create_and_post_rebus(
        ctx,int ( ses["creator_id"] ) ,int ( ses["target_chat_id"] ) ,int ( ses["group_id"] ) ,
        item["answer"],int ( ses["creator_id"] ) ,session_id,item_no
    )

async def _finish_rebus_session ( ctx,session_id,group_id ) :
    execute ( "UPDATE rebus_sessions SET status='done' WHERE id=?", ( session_id, ) )
    scores=all_(
        "SELECT first_name,wins FROM rebus_session_scores WHERE session_id=? ORDER BY wins DESC, first_name COLLATE NOCASE",
        (session_id,)
    )
    if scores:
        lines=["🏁 REBUS MUSOBAQASI YAKUNLANDI",""]
        for i,r in enumerate ( scores,1 ) :
            lines.append ( f"{i}. {r['first_name'] or 'Ishtirokchi'} — {r['wins']} ta")
        await ctx.bot.send_message ( group_id,"\n".join ( lines ) )
    else:
        await ctx.bot.send_message ( group_id,"🏁 Rebus musobaqasi yakunlandi.")

async def _check_rebus_answer ( update,ctx ) :
    msg=update.effective_message; u=update.effective_user; chat=update.effective_chat
    if not msg or not u or u.is_bot or not msg.text or chat.type not in ("group","supergroup" ) :
        return False
    r=one(
        "SELECT * FROM rebuses WHERE answer_group_id=? AND status='active' ORDER BY id DESC LIMIT 1",
        (chat.id,)
    )
    if not r: return False
    guess=_norm_rebus_answer ( msg.text)
    if not guess or guess!=r["answer_norm"]:
        return False

    with db ( ) as c:
        cur=c.execute(
            "UPDATE rebuses SET status='solved',winner_id=?,solved_at=? WHERE id=? AND status='active'",
            (u.id,now (  ) ,r["id"])
        )
        if cur.rowcount!=1: return False
        c.execute(
            "INSERT INTO members (chat_id,user_id,xp,messages,daily,weekly,last_day,last_week) VALUES (?,?,10,0,0,0,'','') "
            "ON CONFLICT ( chat_id,user_id) DO UPDATE SET xp=xp+10",
            (chat.id,u.id)
        )
        item=c.execute(
            "SELECT session_id,item_no FROM rebus_session_items WHERE rebus_id=?", ( r["id"],)
        ).fetchone ( )
        if item:
            c.execute(
                "UPDATE rebus_session_items SET status='solved' WHERE session_id=? AND item_no=?",
                (item["session_id"],item["item_no"])
            )
            c.execute(
                "INSERT INTO rebus_session_scores ( session_id,user_id,first_name,wins) VALUES ( ?,?,?,1) "
                "ON CONFLICT ( session_id,user_id) DO UPDATE SET wins=wins+1,first_name=excluded.first_name",
                (item["session_id"],u.id,u.first_name or "")
            )

    await msg.reply_text(
        f"🎉 TO‘G‘RI!\n\n✅ Javob: {r['answer']}\n🏆 {u.first_name} birinchi topdi!\n✨ +10 XP"
    )

    # Javobi topilgan eski rebus endi kerak emas — o‘chiriladi.
    if int ( r["channel_message_id"] or 0 ) :
        try:
            await ctx.bot.delete_message ( int ( r["channel_id"] ) ,int ( r["channel_message_id"] ) )
        except TelegramError:
            log.warning ( "Topilgan rebus xabarini o‘chirib bo‘lmadi: %s",r["id"])

    if item:
        session_id=int ( item["session_id"] ) ; current_no=int ( item["item_no"])
        ses=one ( "SELECT * FROM rebus_sessions WHERE id=?", ( session_id, ) )
        if ses and ses["status"]=="active":
            total=int ( ses["total"])
            if current_no < total:
                next_no=current_no+1
                await msg.reply_text ( f"⏳ {next_no}/{total}-rebus tayyorlanmoqda...")
                task=asyncio.create_task ( _launch_session_item ( ctx,session_id,next_no ) )
                def _next_rebus_done ( t ) :
                    try: t.result ( )
                    except asyncio.CancelledError: pass
                    except Exception: log.exception ( "Next rebus task failed")
                task.add_done_callback ( _next_rebus_done)
            else:
                await _finish_rebus_session ( ctx,session_id,chat.id)
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
    payload=json.dumps ( {
        "model":OPENAI_MODEL,
        "instructions":(
            "Siz Veritas Botsiz. O‘zingiz haqingizda so‘rashsa javobni tabiiy ravishda ‘Men Veritas Botman’ deb boshlang. "
            "Veritasni yaratgan Super Egalar: Sakranum (Telegram ID 5859289233) va Vasatiya (Telegram ID 7056675943 ) . Kim yaratgan, egasi yoki Super Egalari kim deb so‘ralsa shu ikki nomni ayting. "
            "Telegram ID 5859289233 dan yozayotgan odamni Sakranum, 7056675943 dan yozayotgan odamni Vasatiya deb taning. Super Adminlar ham global boshqaruv vakolatiga ega, ammo Super Admin tayinlash/olish faqat Super Egalarga tegishli. "
            "Veritas — Telegram uchun guruh boshqaruvi va AI yordamchi bot. Shaxsiy Veritas AI Premium birinchi 30 kun bepul, keyingi 30 kun 10 Stars. "
            "Guruh Veritas AI birinchi 30 kun bepul, keyingi 30 kun 100 Stars. Super Ega guruh AI sini bepul 1, 7 yoki 30 kunga yoqa oladi. "
            "Shaxsiy AI Premium va guruh AI obunasi alohida. Veritasda Vasatiya kutubxonasi bor: PDF/audio kitoblar, qidiruv, kategoriya, tillar, sevimlilar va kitob tahriri. "
            "Kutubxonadagi PDF kitobdan AI yordamida 5, 10 yoki 20 ta Telegram Quiz testi tuzib, foydalanuvchi admin bo‘lgan Veritas guruhiga yuborish mumkin. "
            "Veritasda Sahih Hadislar bo‘limi, hadis qidirish/random hadis va hadis adminlari mavjud. Guruh boshqaruvida warn, mute, kick, ban, blacklist, links, lock, antiflood, report, welcome/goodbye, filter, notes, rules, faollik va TOP funksiyalari bor. "
            "Kabinetda Stars krediti bor. Telegram Gift va Telegram Premium sovg‘a qilish funksiyalari Veritas AI Premiumdan boshqa xizmat. *help yordam markazini ochadi, *ai guruh AI holati/tariflarini ko‘rsatadi. "
            "Mavjud bo‘lmagan Veritas funksiyasini uydirmang. Aniq bilmagan sozlama bo‘lsa *help yoki menyuni tekshirishni ayting. "
            "Foydalanuvchi qaysi tilda yozsa, asosan o‘sha tilda javob bering. Javob Telegram uchun aniq va ortiqcha uzun bo‘lmasin. "
            "Diniy, tibbiy, huquqiy yoki moliyaviy mavzularda noaniqlik bo‘lsa buni ochiq ayting."
        ),
        "input":prompt,
        "max_output_tokens":700
    },ensure_ascii=False ) .encode ( "utf-8")
    req=urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=payload,
        headers={"Authorization":f"Bearer {OPENAI_API_KEY}","Content-Type":"application/json"},
        method="POST"
    )
    with urllib.request.urlopen ( req,timeout=45) as resp:
        data=json.loads ( resp.read (  ) .decode ( "utf-8" ) )
    if data.get ( "output_text" ) :
        return str ( data["output_text"] ) .strip ( )
    parts=[]
    for item in data.get ( "output",[] ) :
        for content in item.get ( "content",[] ) :
            if content.get ( "type" ) =="output_text" and content.get ( "text" ) :
                parts.append ( content["text"])
    return "\n".join ( parts ) .strip ( )



def _openai_image_response_sync ( image_bytes, mime_type, user_text ) :
    if not OPENAI_API_KEY:
        raise RuntimeError ( "OPENAI_API_KEY sozlanmagan")
    import base64 as _b64
    data_url=f"data:{mime_type};base64,"+_b64.b64encode ( image_bytes ) .decode ( "ascii")
    payload=json.dumps ( {
        "model":OPENAI_MODEL,
        "instructions":(
            "Siz Veritas Botsiz. O‘zingiz haqingizda so‘rashsa ‘Men Veritas Botman’ deb boshlang. "
            "Veritasni yaratgan Super Egalar Sakranum (5859289233) va Vasatiya (7056675943 ) . Kim yaratgan deb so‘ralsa shu ikki nomni ayting. "
            "Foydalanuvchi yuborgan rasmni diqqat bilan ko‘ring. Undagi matn, jadval, diagramma, kitob sahifasi "
            "yoki boshqa ko‘rinadigan ma’lumotni tahlil qiling. Ko‘rinmagan narsani uydirmang. "
            "Foydalanuvchi qaysi tilda yozsa o‘sha tilda javob bering."
        ),
        "input":[{
            "role":"user",
            "content":[
                {"type":"input_image","image_url":data_url,"detail":"auto"},
                {"type":"input_text","text":user_text or "Bu rasmni ko‘rib, undagi ma’lumotni tushuntirib bering."}
            ]
        }],
        "max_output_tokens":900
    },ensure_ascii=False ) .encode ( "utf-8")
    req=urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=payload,
        headers={"Authorization":f"Bearer {OPENAI_API_KEY}","Content-Type":"application/json"},
        method="POST"
    )
    with urllib.request.urlopen ( req,timeout=90) as resp:
        data=json.loads ( resp.read (  ) .decode ( "utf-8" ) )
    return _extract_response_text ( data) or "Rasm tahlil qilindi, lekin javob hosil bo‘lmadi."

async def private_ai_media_reply ( update,ctx ) :
    if ctx.user_data.get ( "owner_consumed_message_id" ) ==getattr ( update.effective_message,"message_id",None ) :
        return

    msg=update.effective_message; u=update.effective_user; chat=update.effective_chat
    if not msg or not u or chat.type!="private" or u.is_bot:
        return
    if STATE.get ( u.id ) :
        return
    # Only image support in this first safe phase; PDF large-file downloader follows separately.
    photo = msg.photo[-1] if msg.photo else None
    image_doc = None
    if msg.document and (msg.document.mime_type or "" ) .lower (  ) .startswith ( "image/" ) :
        image_doc=msg.document
    if not photo and not image_doc:
        return
    ensure_user ( u)
    if not ai_user_active ( u.id ) :
        kb=InlineKeyboardMarkup ( [[InlineKeyboardButton ( "💎 10 ⭐ — 30 kun",callback_data="aipbuy" ) ],
                                 [InlineKeyboardButton ( "⭐ Hisobni to‘ldirish",callback_data="wallet" ) ]])
        return await msg.reply_text ( "🔒 Rasmni Veritas AI bilan tahlil qilish AI Premium uchun.\n\n💎 10 ⭐ — 30 kun",reply_markup=kb)
    if not OPENAI_API_KEY:
        return await msg.reply_text ( "⚠️ Veritas AI kaliti sozlanmagan.")
    try:
        await ctx.bot.send_chat_action ( chat.id,"typing")
        obj=photo or image_doc
        tgfile=await ctx.bot.get_file ( obj.file_id)
        raw=bytes ( await tgfile.download_as_bytearray (  ) )
        mime= ( getattr ( image_doc,"mime_type",None) or "image/jpeg")
        prompt= ( msg.caption or "" ) .strip ( ) or "Bu rasmni ko‘rib, undagi ma’lumotni tushuntirib bering."
        answer=await asyncio.to_thread ( _openai_image_response_sync,raw,mime,prompt)
        for i in range ( 0,len ( answer ) ,4000 ) :
            await msg.reply_text ( answer[i:i+4000])
    except Exception as e:
        log.exception ( "Private AI image error: %s",e)
        await msg.reply_text ( "⚠️ Rasmni tahlil qilishda xatolik bo‘ldi.")


def _openai_upload_pdf_sync ( pdf_bytes,filename ) :
    boundary="----VeritasBoundary"+str ( int ( time.time ( ) *1000 ) )
    safe= ( filename or "book.pdf" ) .replace ( '"','' ) .replace ( "\r","" ) .replace ( "\n","")
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
    t= ( text or "" ) .strip ( )
    if t.startswith ( "```" ):
        t=re.sub ( r"^``` ( ?:json ) ?\s*","",t,flags=re.I )
        t=re.sub ( r"\s*```$","",t )
    a=t.find ( "[" ) ; b=t.rfind ( "]" )
    return t[a:b+1] if a>=0 and b>a else t

def _openai_book_quiz_sync ( pdf_bytes,filename,title,count ) :
    """Matnli yoki skaner PDFni Responses API orqali o'qib, kitobning o'zidan quiz tuzadi."""
    if not OPENAI_API_KEY:
        raise RuntimeError ( "OPENAI_API_KEY sozlanmagan")
    if not pdf_bytes or not pdf_bytes.startswith ( b"%PDF" ) :
        raise RuntimeError ( "Fayl haqiqiy PDF emas")
    if len ( pdf_bytes) > 45 * 1024 * 1024:
        raise RuntimeError ( "PDF 45 MB dan katta")

    safe= ( filename or "book.pdf" ) .replace ( '"','' ) .replace ( "\r","" ) .replace ( "\n","")
    file_data="data:application/pdf;base64,"+base64.b64encode ( pdf_bytes ) .decode ( "ascii")
    instruction=(
      f"Bu PDF — ‘{title}’ kitobi. PDFni to‘liq tahlil qiling va FAQAT shu kitob mazmuniga tayangan holda aynan {count} ta test tuzing. "
      "Agar PDF skanerlangan bo‘lsa, sahifa rasmlaridagi matnni ham o‘qing. Tashqi bilim qo‘shmang. "
      "Har savolda aynan 4 ta variant bo‘lsin va faqat bittasi to‘g‘ri bo‘lsin. "
      "Savollar takrorlanmasin, kitobni o‘qiganlikni tekshiradigan mazmunli savollar bo‘lsin. "
      "Savol va variantlarni o‘zbek tilida yozing. "
      "Faqat JSON massiv qaytaring. Har element: "
      '{"question":"...","options":["...","...","...","..."],"correct":0,"explanation":"..."}. '
      "correct faqat 0,1,2,3 dan biri. explanation kitobdagi javobga tayangan juda qisqa izoh. "
      "Markdown yoki JSONdan tashqari hech qanday matn yozmang."
    )
    payload=json.dumps ( {
      "model":OPENAI_MODEL,
      "input":[{
        "role":"user",
        "content":[
          {"type":"input_file","filename":safe,"file_data":file_data,"detail":"low"},
          {"type":"input_text","text":instruction}
        ]
      }],
      "max_output_tokens":max ( 2200,count*320)
    },ensure_ascii=False ) .encode ( "utf-8")

    req=urllib.request.Request(
      "https://api.openai.com/v1/responses",
      data=payload,
      headers={"Authorization":f"Bearer {OPENAI_API_KEY}","Content-Type":"application/json"},
      method="POST"
    )
    try:
        with urllib.request.urlopen ( req,timeout=180) as resp:
            data=json.loads ( resp.read (  ) .decode ( "utf-8" ) )
    except urllib.error.HTTPError as e:
        detail=""
        try: detail=e.read (  ) .decode ( "utf-8","replace" ) [:3000]
        except Exception: pass
        log.error ( "Book quiz OpenAI HTTP %s: %s",getattr ( e,"code","?" ) ,detail)
        raise RuntimeError ( f"OpenAI HTTP {getattr ( e,'code','?' ) }: {detail[:600]}")
    except Exception as e:
        log.exception ( "Book quiz OpenAI connection error")
        raise RuntimeError ( f"OpenAI ulanish xatosi: {e}")

    raw_text=_extract_response_text ( data)
    if not raw_text:
        log.error ( "Book quiz empty OpenAI response: %s",str ( data ) [:3000])
        raise RuntimeError ( "AI bo‘sh javob qaytardi")
    raw=_clean_json_text ( raw_text)
    try:
        items=json.loads ( raw)
    except Exception:
        log.error ( "Book quiz invalid JSON: %s",raw_text[:5000])
        raise RuntimeError ( "AI testlarni JSON formatida qaytarmadi")
    if not isinstance ( items,list ) :
        raise RuntimeError ( "AI JSON massiv qaytarmadi")

    out=[]
    for x in items:
        if not isinstance ( x,dict ) : continue
        q=str ( x.get ( "question","" )  ) .strip (  ) [:300]
        opts=x.get ( "options",[])
        try: correct=int ( x.get ( "correct",-1 ) )
        except Exception: correct=-1
        exp=str ( x.get ( "explanation","" )  ) .strip (  ) [:190]
        if q and isinstance ( opts,list) and len ( opts ) ==4 and 0<=correct<4:
            opts=[str ( z ) .strip (  ) [:100] for z in opts]
            if all ( opts ) :
                out.append ( {"question":q,"options":opts,"correct":correct,"explanation":exp})
        if len ( out ) >=count: break
    if len ( out ) <count:
        raise RuntimeError ( f"AI {len ( out ) } ta yaroqli test qaytardi, {count} ta kerak")
    return out[:count]


def _openai_quiz_from_context_sync ( context, title, count ) :
    """Extracted book context -> grounded Telegram quiz JSON."""
    if not OPENAI_API_KEY:
        raise RuntimeError ( "OPENAI_API_KEY sozlanmagan")
    if not context or len ( context.strip (  ) ) < 300:
        raise RuntimeError ( "PDFdan test uchun yetarli matn olinmadi")
    instruction = (
        f"Quyidagi material ‘{title}’ kitobidan olingan. FAQAT berilgan materialga tayangan holda "
        f"aynan {count} ta test tuzing. Tashqi bilim qo‘shmang. "
        "Har savolda aynan 4 ta variant va faqat bitta to‘g‘ri javob bo‘lsin. "
        "Savollar takrorlanmasin. Savol va variantlar o‘zbek tilida bo‘lsin. "
        "Faqat JSON massiv qaytaring. Har element: "
        '{"question":"...","options":["...","...","...","..."],"correct":0,"explanation":"..."}. '
        "correct 0,1,2,3 dan biri. explanation juda qisqa bo‘lsin.\n\n"
        "KITOBDAN OLINGAN MATERIAL:\n" + context
    )
    payload = json.dumps ( {
        "model": OPENAI_MODEL,
        "input": instruction,
        "max_output_tokens": max ( 2200, count * 320)
    }, ensure_ascii=False ) .encode ( "utf-8")
    req = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=payload,
        headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen ( req, timeout=180) as resp:
            data = json.loads ( resp.read (  ) .decode ( "utf-8" ) )
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read (  ) .decode ( "utf-8", "replace" ) [:3000]
        except Exception:
            pass
        raise RuntimeError ( f"OpenAI HTTP {getattr ( e,'code','?' ) }: {detail[:600]}")
    raw_text = _extract_response_text ( data)
    raw = _clean_json_text ( raw_text)
    try:
        items = json.loads ( raw)
    except Exception:
        log.error ( "Large PDF quiz invalid JSON: %s", raw_text[:5000])
        raise RuntimeError ( "AI testlarni JSON formatida qaytarmadi")
    out = []
    if isinstance ( items, list ) :
        for x in items:
            if not isinstance ( x, dict ) :
                continue
            question = str ( x.get ( "question", "" )  ) .strip (  ) [:300]
            opts = x.get ( "options", [])
            try:
                correct = int ( x.get ( "correct", -1 ) )
            except Exception:
                correct = -1
            explanation = str ( x.get ( "explanation", "" )  ) .strip (  ) [:190]
            if question and isinstance ( opts, list) and len ( opts) == 4 and 0 <= correct < 4:
                opts = [str ( z ) .strip (  ) [:100] for z in opts]
                if all ( opts ) :
                    out.append ( {
                        "question": question,
                        "options": opts,
                        "correct": correct,
                        "explanation": explanation
                    })
            if len ( out) >= count:
                break
    if len ( out) < count:
        raise RuntimeError ( f"AI {len ( out ) } ta yaroqli test qaytardi, {count} ta kerak")
    return out[:count]


def _even_page_indexes ( total, wanted ) :
    if total <= 0:
        return []
    wanted = max ( 1, min ( int ( wanted ) , total ) )
    if wanted == total:
        return list ( range ( total ) )
    if wanted == 1:
        return [total // 2]
    return sorted ( set ( round ( i * (total - 1) / (wanted - 1 ) ) for i in range ( wanted )  ) )


def _extract_large_pdf_context_sync ( path, title, count ) :
    """
    Large PDF is never loaded fully into RAM.
    Text PDFs: read all pages, keep evenly distributed bounded excerpts.
    Scanned PDFs: render evenly distributed pages and let Vision read them in small batches.
    """
    if fitz is None:
        raise RuntimeError ( "PyMuPDF o‘rnatilmagan")
    doc = fitz.open ( path)
    try:
        total = doc.page_count
        if total < 1:
            raise RuntimeError ( "PDF sahifalari topilmadi")

        # First determine whether this is a text PDF.
        probe_ids = _even_page_indexes ( total, min ( 12, total ) )
        probe_chars = 0
        for pno in probe_ids:
            try:
                probe_chars += len (  ( doc.load_page ( pno ) .get_text ( "text") or "" ) .strip (  ) )
            except Exception:
                pass

        # TEXT PDF: extract across the whole book without keeping the whole PDF in memory.
        if probe_chars >= max ( 800, len ( probe_ids) * 120 ) :
            page_budget = 2200
            max_chars = 110000 if count >= 20 else (85000 if count >= 10 else 60000)
            pieces = []
            used = 0
            for pno in range ( total ) :
                try:
                    t = (doc.load_page ( pno ) .get_text ( "text") or "" ) .strip ( )
                except Exception:
                    t = ""
                if not t:
                    continue
                # Keep a bounded excerpt from every page so coverage spans the whole book.
                if len ( t) > page_budget:
                    half = page_budget // 2
                    t = t[:half] + "\n...\n" + t[-half:]
                block = f"\n--- {pno+1}-sahifa / {total} ---\n{t}\n"
                if used + len ( block) > max_chars:
                    # Once budget is full, switch to evenly sampled remaining pages.
                    break
                pieces.append ( block)
                used += len ( block)

            # If early pages filled the budget, rebuild with even page coverage.
            if len ( pieces) < total and used >= max_chars * 0.85:
                pieces = []
                used = 0
                sample_n = min ( total, 48 if count >= 20 else (36 if count >= 10 else 28 ) )
                for pno in _even_page_indexes ( total, sample_n ) :
                    try:
                        t = (doc.load_page ( pno ) .get_text ( "text") or "" ) .strip ( )
                    except Exception:
                        t = ""
                    if not t:
                        continue
                    per = max ( 900, max_chars // max ( 1, sample_n ) )
                    if len ( t) > per:
                        half = per // 2
                        t = t[:half] + "\n...\n" + t[-half:]
                    block = f"\n--- {pno+1}-sahifa / {total} ---\n{t}\n"
                    if used + len ( block) > max_chars:
                        break
                    pieces.append ( block)
                    used += len ( block)

            context = "".join ( pieces ) .strip ( )
            if len ( context) < 500:
                raise RuntimeError ( "PDF matni juda kam")
            return context, total, "text"

        # SCANNED PDF: Vision reads evenly distributed pages.
        sample_n = min ( total, 18 if count >= 20 else (14 if count >= 10 else 10 ) )
        page_ids = _even_page_indexes ( total, sample_n)
        vision_notes = []
        for idx, pno in enumerate ( page_ids, 1 ) :
            page = doc.load_page ( pno)
            pix = page.get_pixmap ( matrix=fitz.Matrix ( 1.35, 1.35 ) , alpha=False)
            img = pix.tobytes ( "jpeg", jpg_quality=72)
            prompt = (
                f"Bu ‘{title}’ kitobining {pno+1}/{total}-sahifasi. "
                "Sahifadagi TEST tuzishga yaroqli aniq faktlar, ta’riflar, voqealar, ism va tushunchalarni "
                "o‘zbekcha ixcham konspekt qiling. Faqat ko‘rinayotgan sahifadagi ma’lumotni yozing; uydirmang."
            )
            note = _openai_image_response_sync ( img, "image/jpeg", prompt)
            if note:
                vision_notes.append ( f"\n--- {pno+1}-sahifa / {total} ---\n{note.strip (  ) }\n")
        context = "".join ( vision_notes ) .strip ( )
        if len ( context) < 500:
            raise RuntimeError ( "Skan PDFdan yetarli mazmun o‘qilmadi")
        return context, total, "scan"
    finally:
        doc.close ( )


def _build_book_quiz_from_path_sync ( path, title, count ) :
    size = Path ( path ) .stat (  ) .st_size
    # Small PDFs keep the direct PDF path; large PDFs use streaming/chunk extraction.
    if size <= 45 * 1024 * 1024:
        pdf_bytes = Path ( path ) .read_bytes ( )
        return _openai_book_quiz_sync ( pdf_bytes, Path ( path ) .name, title, count ) , None
    context, pages, mode = _extract_large_pdf_context_sync ( path, title, count)
    quizzes = _openai_quiz_from_context_sync ( context, title, count)
    return quizzes, {"pages": pages, "mode": mode, "size": size}


async def quiz_replace_message ( q, ctx, text, reply_markup=None ) :
    """Quiz menyusini rasmli yoki oddiy xabardan ishonchli ochadi."""
    msg = q.message
    try:
        # Kitob kartasi cover rasmi bilan yuborilgan bo'lsa edit_message_text ishlamaydi.
        if msg and (msg.photo or msg.video or msg.document or msg.audio or msg.animation ) :
            chat_id = msg.chat.id
            try:
                await msg.delete ( )
            except Exception:
                pass
            return await ctx.bot.send_message ( chat_id, text, reply_markup=reply_markup)
        return await q.edit_message_text ( text, reply_markup=reply_markup)
    except TelegramError:
        return await ctx.bot.send_message ( q.message.chat.id, text, reply_markup=reply_markup)

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

async def _download_large_telegram_file ( ctx, file_id, path ) :
    """
    Bot API getFile katta faylni bermasa:
    1) bot file_id orqali PDFni maxsus storage guruhiga server-side yuboradi;
    2) Telethon user session shu xabarni MTProto orqali yuklab oladi.
    Bot va TG_SESSION egasi storage guruhida bo‘lishi kerak.
    """
    if not (TelegramClient and StringSession ) :
        raise RuntimeError ( "Telethon o‘rnatilmagan")
    if not TG_API_ID or not TG_API_HASH or not TG_SESSION:
        raise RuntimeError ( "TG_API_ID/TG_API_HASH/TG_SESSION sozlanmagan")
    if not TG_STORAGE_CHAT_ID:
        raise RuntimeError ( "TG_STORAGE_CHAT_ID sozlanmagan")

    storage_msg = await ctx.bot.send_document(
        chat_id=TG_STORAGE_CHAT_ID,
        document=file_id,
        caption="Veritas AI vaqtinchalik PDF"
    )
    client = TelegramClient ( StringSession ( TG_SESSION ) , TG_API_ID, TG_API_HASH)
    try:
        await client.connect ( )
        if not await client.is_user_authorized (  ) :
            raise RuntimeError ( "TG_SESSION avtorizatsiyadan chiqib qolgan")
        entity = await client.get_entity ( TG_STORAGE_CHAT_ID)
        msg = await client.get_messages ( entity, ids=storage_msg.message_id)
        if not msg:
            raise RuntimeError ( "Storage guruhidagi PDF xabari topilmadi")
        saved = await client.download_media ( msg, file=path)
        if not saved or not Path ( path ) .exists (  ) :
            raise RuntimeError ( "MTProto PDFni yuklay olmadi")
        return path
    finally:
        await client.disconnect ( )
        try:
            await ctx.bot.delete_message ( TG_STORAGE_CHAT_ID, storage_msg.message_id)
        except Exception:
            pass

async def _make_and_send_book_quiz ( q,ctx,bid,chat_id,count ) :
    u=q.from_user
    r=one ( "SELECT title,pdf_file_id FROM library_books WHERE id=? AND status='approved'", ( bid,) )
    if not r or not r["pdf_file_id"]:
        return await q.edit_message_text ( "❌ Kitob PDF’i topilmadi.",reply_markup=back_markup ( "library" ) )
    if count not in (5,10,20 ) :
        return await q.answer ( "Test soni noto‘g‘ri.",show_alert=True)
    if not is_super ( u.id ) and not await is_tg_admin ( ctx.bot,chat_id,u.id ) :
        return await q.answer ( "Bu guruhda admin emassiz.",show_alert=True)
    if not OPENAI_API_KEY:
        return await q.edit_message_text ( "⚠️ Veritas AI kaliti sozlanmagan.",reply_markup=back_markup ( "library" ) )

    await q.edit_message_text(
        f"🧠 ‘{r['title']}’ kitobi o‘qilmoqda...\n\n"
        f"{count} ta test tayyorlanadi. Matnli yoki skaner PDF bo‘lishi mumkin.\nBiroz kuting."
    )
    path=f"/tmp/veritas_book_{bid}_{u.id}.pdf"
    try:
        try:
            tgfile=await ctx.bot.get_file ( r["pdf_file_id"])
            await tgfile.download_to_drive ( custom_path=path)
        except TelegramError as e:
            if "File is too big" not in str ( e ) :
                raise
            log.info ( "Bot API file too big; MTProto fallback boshlandi.")
            await _download_large_telegram_file ( ctx, r["pdf_file_id"], path)

        with open ( path, "rb") as _fh:
            if _fh.read ( 4) != b"%PDF":
                raise RuntimeError ( "Telegramdan olingan fayl PDF emas")

        quizzes, pdf_meta = await asyncio.to_thread(
            _build_book_quiz_from_path_sync, path, r["title"], count
        )
        if pdf_meta:
            log.info(
                "Large PDF processed: %.1f MB, %s pages, mode=%s",
                pdf_meta["size"] / (1024 * 1024 ) , pdf_meta["pages"], pdf_meta["mode"]
            )

        await ctx.bot.send_message(
            chat_id,
            f"🧠 VASATIYA KITOB TESTI\n\n📖 {r['title']}\n📝 {len ( quizzes ) } ta savol\n\nTestni boshlaymiz 👇"
        )
        sent=0
        for i,x in enumerate ( quizzes,1 ) :
            await ctx.bot.send_poll(
                chat_id=chat_id,
                question=f"{i}. {x['question']}"[:300],
                options=x["options"],
                type="quiz",
                correct_option_id=x["correct"],
                is_anonymous=False,
                explanation= ( x["explanation"] or None ) ,
                protect_content=False
            )
            sent+=1
            await asyncio.sleep ( 0.4)

        return await q.edit_message_text(
            f"✅ Tayyor!\n\n📖 {r['title']}\n🧠 {sent} ta test guruhga yuborildi.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton ( "📖 Kitobga qaytish",callback_data=f"libbook:{bid}" ) ]]
            )
        )
    except Exception as e:
        log.exception ( "Book quiz error: %s",e)
        s=str ( e)
        if "401" in s:
            msg="⚠️ OpenAI kaliti qabul qilinmadi. Railway’dagi OPENAI_API_KEY ni tekshiring."
        elif "429" in s:
            msg="⚠️ OpenAI limiti yoki balans sabab test tuzilmadi. API balansini tekshiring."
        elif "PyMuPDF" in s:
            msg="⚠️ Katta PDF moduli uchun PyMuPDF kutubxonasi o‘rnatilmagan."
        elif "Skan PDF" in s or "PDF matni juda kam" in s:
            msg="⚠️ PDF o‘qildi, lekin test tuzish uchun yetarli mazmun ajratilmadi."
        elif "JSON" in s or "yaroqli test" in s:
            msg="⚠️ AI kitobni o‘qidi, lekin test formatini to‘g‘ri qaytarmadi. Qayta urinib ko‘ring."
        elif "TG_STORAGE_CHAT_ID" in s:
            msg="⚠️ Katta PDF uchun storage guruh hali sozlanmagan."
        elif "Telethon" in s:
            msg="⚠️ Katta PDF moduli uchun Telethon kutubxonasi kerak."
        elif "TG_API_ID" in s or "TG_SESSION" in s:
            msg="⚠️ Katta PDF uchun Telegram MTProto sozlamalari to‘liq emas."
        else:
            msg="⚠️ Kitobdan test tuzishda xatolik bo‘ldi. Aniq sabab Railway logiga yozildi."
        return await q.edit_message_text ( msg,reply_markup=back_markup ( "library" ) )
    finally:
        try: Path ( path ) .unlink ( missing_ok=True)
        except Exception: pass


def _translation_last_completed ( uid ) :
    r=one ( "SELECT MAX ( completed_at) AS t FROM ai_book_translations WHERE user_id=? AND status='done'", (uid, ) )
    return int ( r["t"] or 0) if r else 0

def _translation_wait_seconds ( uid ) :
    last=_translation_last_completed ( uid)
    return max ( 0, last + 86400 - now (  ) ) if last else 0

def _translation_running ( uid ) :
    return bool ( one ( "SELECT 1 FROM ai_book_translations WHERE user_id=? AND status='running' LIMIT 1", (uid, )  ) )

def _translate_text_sync ( text, target_lang, title, part_no, total_parts ) :
    names={"uz":"O‘zbekcha","ru":"Ruscha","en":"English"}; lang=names.get ( target_lang,target_lang)
    payload=json.dumps ( {"model":OPENAI_MODEL,"instructions":f"Berilgan kitob matnini {lang} tiliga to‘liq va sodiq tarjima qiling. Qisqartirmang, sharh va yangi ma’lumot qo‘shmang. Tuzilma va raqamlarni saqlang. Faqat tarjimani qaytaring.","input":f"Kitob: {title}\nQism: {part_no}/{total_parts}\n\n{text}","max_output_tokens":7000},ensure_ascii=False ) .encode ( "utf-8")
    req=urllib.request.Request ( "https://api.openai.com/v1/responses",data=payload,headers={"Authorization":f"Bearer {OPENAI_API_KEY}","Content-Type":"application/json"},method="POST")
    with urllib.request.urlopen ( req,timeout=180) as resp: data=json.loads ( resp.read (  ) .decode ( "utf-8" ) )
    out=_extract_response_text ( data)
    if not out.strip (  ) : raise RuntimeError ( "AI tarjima qaytarmadi")
    return out.strip ( )

def _split_translation_text ( text,max_chars=9000 ) :
    chunks=[]; cur=""
    for para in re.split ( r"\n\s*\n", ( text or "" ) .strip (  )  ) :
        para=para.strip ( )
        if not para: continue
        for piece in [para[i:i+max_chars] for i in range ( 0,len ( para ) ,max_chars ) ]:
            cand= ( cur+"\n\n"+piece ) .strip ( ) if cur else piece
            if len ( cand ) >max_chars and cur: chunks.append ( cur ) ; cur=piece
            else: cur=cand
    if cur: chunks.append ( cur)
    return chunks

def _find_unicode_font (  ) :
    for x in ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf","/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf","/usr/share/fonts/opentype/noto/NotoSans-Regular.ttf","/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"]:
        if Path ( x ) .exists (  ) : return x
    return None

def _write_translation_pdf_sync ( out_path,title,target_lang,parts ) :
    if fitz is None: raise RuntimeError ( "PyMuPDF o‘rnatilmagan")
    doc=fitz.open (  ) ; fontfile=_find_unicode_font (  ) ; fontname="veritasfont" if fontfile else "helv"
    def page_new (  ) :
        p=doc.new_page ( width=595,height=842)
        if fontfile: p.insert_font ( fontname=fontname,fontfile=fontfile)
        return p
    page=page_new (  ) ; y=55; text=f"{title}\nAI tarjima · {target_lang}\n\n"+"\n\n".join ( parts)
    lines=[]
    for para in text.splitlines (  ) :
        if not para: lines.append ( "" ) ; continue
        line=""
        for w in para.split (  ) :
            c= ( line+" "+w ) .strip ( )
            if len ( c ) >88 and line: lines.append ( line ) ; line=w
            else: line=c
        if line: lines.append ( line)
    for line in lines:
        if y>790: page=page_new (  ) ; y=55
        if not line: y+=9; continue
        try: page.insert_text (  ( 45,y ) ,line,fontsize=10.5,fontname=fontname)
        except Exception: page.insert_text (  ( 45,y ) ,line.encode ( "latin-1","replace" ) .decode ( "latin-1" ) ,fontsize=10.5,fontname="helv")
        y+=14
    doc.save ( out_path,garbage=3,deflate=True ) ; doc.close ( )

def _translate_pdf_path_sync ( path,out_path,title,target_lang ) :
    if fitz is None: raise RuntimeError ( "PyMuPDF o‘rnatilmagan")
    doc=fitz.open ( path ) ; pages=[]; chars=0
    try:
        for pno in range ( doc.page_count ) :
            t= ( doc.load_page ( pno ) .get_text ( "text") or "" ) .strip ( )
            if t: pages.append ( f"--- {pno+1}-sahifa ---\n{t}" ) ; chars+=len ( t)
    finally: doc.close ( )
    if chars<500: raise RuntimeError ( "SCAN_TRANSLATION_NOT_READY")
    chunks=_split_translation_text ( "\n\n".join ( pages ) )
    translated=[_translate_text_sync ( ch,target_lang,title,i,len ( chunks ) ) for i,ch in enumerate ( chunks,1 ) ]
    _write_translation_pdf_sync ( out_path,title,target_lang,translated)
    return len ( chunks)

async def _run_book_translation ( q,ctx,bid,target_lang ) :
    u=q.from_user
    if not ai_user_active ( u.id ) : return await q.answer ( "🔒 AI Premium kerak: birinchi 30 kun bepul, keyin 10 ⭐ / 30 kun",show_alert=True)
    if _translation_running ( u.id ) : return await q.answer ( "⏳ Sizda boshqa tarjima davom etmoqda.",show_alert=True)
    wait=_translation_wait_seconds ( u.id)
    if wait>0: return await q.answer ( f"⏳ Kunlik limit ishlatilgan. Taxminan { ( wait+3599 ) //3600} soat qoldi.",show_alert=True)
    if target_lang not in {"uz","ru","en"}: return await q.answer ( "Til noto‘g‘ri",show_alert=True)
    r=one ( "SELECT title,pdf_file_id FROM library_books WHERE id=? AND status='approved'", ( bid, ) )
    if not r or not r["pdf_file_id"]: return await q.answer ( "Kitob fayli mavjud emas",show_alert=True)
    cur=execute ( "INSERT INTO ai_book_translations ( user_id,book_id,target_lang,status,started_at) VALUES ( ?,?,?,?,? ) ", ( u.id,bid,target_lang,"running",now (  )  )  ) ; job_id=cur.lastrowid
    names={"uz":"🇺🇿 O‘zbekcha","ru":"🇷🇺 Ruscha","en":"🇬🇧 English"}
    await quiz_replace_message ( q,ctx,f"🌐 AI TARJIMA\n\n📖 {r['title']}\n➡️ {names[target_lang]}\n\nTarjima qilinmoqda. Katta kitob vaqt olishi mumkin...")
    src=f"/tmp/veritas_translate_{bid}_{u.id}.pdf"; out=f"/tmp/veritas_translated_{bid}_{u.id}_{target_lang}.pdf"
    try:
        async with TRANSLATION_SEMAPHORE:
            try:
                tgfile=await ctx.bot.get_file ( r["pdf_file_id"] ) ; await tgfile.download_to_drive ( custom_path=src)
            except TelegramError as e:
                if "File is too big" not in str ( e ) : raise
                await _download_large_telegram_file ( ctx,r["pdf_file_id"],src)
            parts=await asyncio.to_thread ( _translate_pdf_path_sync,src,out,r["title"],target_lang)
        execute ( "UPDATE ai_book_translations SET status='done',completed_at=? WHERE id=?", ( now (  ) ,job_id ) )
        with open ( out,"rb") as fh:
            await ctx.bot.send_document ( u.id,document=fh,filename=f"translated_{bid}_{target_lang}.pdf",caption=f"✅ AI tarjima tayyor\n📖 {r['title']}\n🌐 {names[target_lang]}\n🧩 {parts} qism.\n\nKeyingi kitob: 24 soatdan keyin.")
    except Exception as e:
        log.exception ( "Book translation error: %s",e ) ; execute ( "UPDATE ai_book_translations SET status='failed' WHERE id=?", ( job_id, ) )
        msg="⚠️ Tarjima tugamadi. Kunlik limitingiz sarflanmadi."
        if "SCAN_TRANSLATION_NOT_READY" in str ( e ) : msg="⚠️ Bu PDF skaner/rasm ko‘rinishida. Hozirgi bosqich matnli PDFlarni tarjima qiladi. Kunlik limitingiz sarflanmadi."
        await ctx.bot.send_message ( u.id,msg)
    finally:
        Path ( src ) .unlink ( missing_ok=True ) ; Path ( out ) .unlink ( missing_ok=True)


def ai_cabinet_name_context ( uid ) :
    r=one ( "SELECT first_name,username FROM users WHERE user_id=?", ( uid, ) )
    if not r:
        return ""
    nick= ( r["first_name"] or "" ) .strip ( )
    if not nick and r["username"]:
        nick="@"+r["username"]
    if not nick:
        return ""
    return (
        f"\n\nVERITAS KABINET KONTEKSTI: Bu foydalanuvchining kabinetdagi niki/ismi: {nick}. "
        f"Suhbatda uni tabiiy ravishda {nick} deb taning va kerak bo‘lganda shu nom bilan murojaat qiling. "
        "Boshqa foydalanuvchining nomi bilan adashtirmang."
    )

async def group_ai_reply ( update,ctx ) :
    msg=update.effective_message; chat=update.effective_chat; u=update.effective_user
    if not msg or not u or chat.type not in ("group","supergroup") : return False
    if u.is_bot or not msg.reply_to_message or not msg.text: return False
    replied_msg=msg.reply_to_message
    if not replied_msg.from_user or replied_msg.from_user.id!=ctx.bot.id: return False
    question=msg.text.strip ( )
    if not question or question.startswith ( "*" ) : return False
    if not ai_group_active ( chat.id ) :
        await msg.reply_text ( "🔒 Bu guruhda Veritas AI obunasi faol emas.\n\n*ai yozib tariflarni oching: birinchi 30 kun bepul, keyin 100 ⭐ / 30 kun." )
        return True
    if not ai_rate_ok ( chat.id,u.id,5 ) :
        await msg.reply_text ( "⏳ Juda tez so‘rov yuborildi. 5 soniyadan keyin qayta yozing." )
        return True
    if not OPENAI_API_KEY:
        await msg.reply_text ( "⚠️ Veritas AI kaliti sozlanmagan.")
        return True
    try:
        await ctx.bot.send_chat_action ( chat.id,"typing")
        previous= ( replied_msg.text or replied_msg.caption or "" ) .strip ( )
        prompt= ( f"Oldingi Veritas xabari:\n{previous[:2500]}\n\n" if previous else "") + f"Foydalanuvchi savoli:\n{question[:4000]}" + ai_actor_context ( u ) + ai_cabinet_name_context ( u.id)
        answer=await asyncio.to_thread ( _openai_response_sync,prompt)
        if not answer: answer="Hozir javob hosil bo‘lmadi. Qayta urinib ko‘ring."
        for i in range ( 0,len ( answer ) ,4000 ) : await msg.reply_text ( answer[i:i+4000])
    except urllib.error.HTTPError as e:
        detail=""
        try: detail=e.read (  ) .decode ( "utf-8" ) [:700]
        except Exception: pass
        log.error ( "OpenAI HTTP error %s: %s",getattr ( e,"code","?" ) ,detail)
        await msg.reply_text ( "⚠️ Veritas AI hozir javob bera olmadi. Keyinroq qayta urinib ko‘ring.")
    except Exception:
        log.exception ( "Veritas AI error")
        await msg.reply_text ( "⚠️ Veritas AI bilan ulanishda xatolik bo‘ldi.")
    return True

async def private_ai_reply ( update,ctx ) :
    if ctx.user_data.get ( "v9_consumed_message_id" ) ==getattr ( update.effective_message,"message_id",None ) :
        return
    if ctx.user_data.get ( "owner_consumed_message_id" ) ==getattr ( update.effective_message,"message_id",None ) :
        return

    msg=update.effective_message; u=update.effective_user; chat=update.effective_chat
    if not msg or not u or chat.type!="private" or u.is_bot or not msg.text: return
    text=msg.text.strip ( )
    if not text or text.startswith ( "*" ) or text.startswith ( "/" ): return
    if STATE.get ( u.id ): return
    if ctx.user_data.get ( "workflow_message_id" )==msg.message_id: return
    ensure_user ( u )
    if not ai_user_active ( u.id ) :
        kb=InlineKeyboardMarkup ( [[InlineKeyboardButton ( "💎 10 ⭐ — 30 kun",callback_data="aipbuy" ) ],[InlineKeyboardButton ( "⭐ Hisobni to‘ldirish",callback_data="wallet" ) ]] )
        return await msg.reply_text ( "🔒 Shaxsiy Veritas AI faqat AI Premium a’zolar uchun.\n\n💎 10 ⭐ — 30 kun",reply_markup=kb )
    if not ai_rate_ok ( "private",u.id,4 ) : return await msg.reply_text ( "⏳ 4 soniyadan keyin yana yozing." )
    if not OPENAI_API_KEY: return await msg.reply_text ( "⚠️ Veritas AI kaliti sozlanmagan." )
    try:
        await ctx.bot.send_chat_action ( chat.id,"typing" )
        previous=""
        if msg.reply_to_message and msg.reply_to_message.from_user and msg.reply_to_message.from_user.id==ctx.bot.id:
            previous= ( msg.reply_to_message.text or msg.reply_to_message.caption or "" ) [:2500]
        prompt= ( f"Oldingi Veritas javobi:\n{previous}\n\n" if previous else "" ) +f"Foydalanuvchi:\n{text[:4000]}"+ai_actor_context ( u )
        answer=await asyncio.to_thread ( _openai_response_sync,prompt )
        if not answer: answer="Hozir javob hosil bo‘lmadi. Qayta urinib ko‘ring."
        for i in range ( 0,len ( answer ),4000 ): await msg.reply_text ( answer[i:i+4000] )
    except Exception:
        log.exception ( "Private Veritas AI error" )
        await msg.reply_text ( "⚠️ Veritas AI hozir javob bera olmadi." )

async def vse_self_clean ( update,ctx ) :
    msg=update.effective_message; u=update.effective_user; chat=update.effective_chat
    if not msg or not u or chat.type not in ("group","supergroup" ) :
        return False
    if (msg.text or "" ) .strip (  ) .lower (  ) !="*vse":
        return False
    # Buyruq faqat Veritasning xabariga reply qilinganda ishlaydi.
    if not msg.reply_to_message or not msg.reply_to_message.from_user or msg.reply_to_message.from_user.id!=ctx.bot.id:
        return False

    rows=all_(
        "SELECT message_id FROM group_message_history WHERE chat_id=? AND user_id=? ORDER BY message_id DESC",
        (chat.id,u.id)
    )
    deleted=0
    # *vse xabarining o‘zini ham o‘chirishga harakat qilamiz.
    ids=[msg.message_id]+[int ( r["message_id"]) for r in rows if int ( r["message_id"] ) !=msg.message_id]
    for mid in ids:
        try:
            await ctx.bot.delete_message ( chat.id,mid)
            deleted+=1
        except TelegramError:
            pass
    execute ( "DELETE FROM group_message_history WHERE chat_id=? AND user_id=?", ( chat.id,u.id ) )
    try:
        await ctx.bot.send_message ( chat.id,f"🧹 {u.first_name}: {deleted} ta Veritas qayd etgan xabar o‘chirildi.")
        # Qisqa xizmat xabari guruhda qoladi; job-queue bo‘lmasa ham asosiy funksiya buzilmaydi.
    except TelegramError:
        pass
    return True

async def passive ( update,ctx ) :
    msg=update.effective_message; u=update.effective_user; chat=update.effective_chat
    if msg and u and not u.is_bot and chat and chat.type in ("group","supergroup" ) :
        try:
            execute(
                "INSERT OR IGNORE INTO group_message_history ( chat_id,user_id,message_id,created_at) VALUES ( ?,?,?,? ) ",
                (chat.id,u.id,msg.message_id,now (  ) )
            )
        except Exception:
            log.exception ( "group message history save failed")
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
    if await vse_self_clean ( update,ctx ) : return
    if await _check_rebus_answer ( update,ctx ) : return
    if await _start_group_rebus_flow ( update,ctx ) : return
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
                await msg.reply_text ( f"🌊 {u.first_name}: flood sabab 1 daqiqa mute.")
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
    st=moderation_settings ( update.effective_chat.id)
    g=one ( "SELECT welcome FROM groups WHERE chat_id=?", ( update.effective_chat.id, ) )
    if g and g["welcome"]:
        names=", ".join ( u.first_name for u in update.effective_message.new_chat_members)
        await update.effective_message.reply_text ( f"👋 Xush kelibsiz, {names}!")
    if st and st["clean_service"]:
        try: await update.effective_message.delete ( )
        except TelegramError: pass

async def left_member ( update,ctx ) :
    st=moderation_settings ( update.effective_chat.id)
    g=one ( "SELECT goodbye FROM groups WHERE chat_id=?", ( update.effective_chat.id, ) )
    if g and g["goodbye"] and update.effective_message.left_chat_member:
        await update.effective_message.reply_text ( f"👋 {update.effective_message.left_chat_member.first_name} guruhni tark etdi.")
    if st and st["clean_service"]:
        try: await update.effective_message.delete ( )
        except TelegramError: pass

async def callback ( update,ctx ) :
    q=update.callback_query; d=q.data; u=q.from_user

    # V9/root tugmalari shu yagona callback router ichidan boshqariladi.
    # Bu V8 callbacklariga tegmaydi va alohida handler guruhlari to'qnashuvini yo'q qiladi.
    if d and (d.startswith ( "v9:") or d.startswith ( "root:" )  ) :
        return await v9_callback ( update,ctx)

    ensure_user ( u)
    await q.answer ( )

    if d=="owner:message":
        if q.message.chat.type != "private":
            return await q.edit_message_text ( "📨 Egaga xabar faqat botning shaxsiy chatida ishlaydi.",reply_markup=back_markup ( "home" ) )
        STATE[u.id]={"mode":"owner_message"}
        return await q.edit_message_text(
            "📨 EGAGA XABAR QOLDIRISH\n\nXabaringizni yuboring. Matn, rasm, video, voice, audio, sticker yoki hujjat bo‘lishi mumkin.\n\n❌ Bekor qilish uchun /start bosing.",
            reply_markup=back_markup ( "home")
        )

    if d.startswith ( "ownerreply:" ) :
        if u.id not in SUPER_OWNERS:
            return await q.answer ( "Faqat Super Ega uchun.",show_alert=True)
        tid=int ( d.split ( ":",1 ) [1] ) ; row=one ( "SELECT * FROM owner_messages WHERE id=?", ( tid, ) )
        if not row: return await q.answer ( "Murojaat topilmadi.",show_alert=True)
        STATE[u.id]={"mode":"owner_reply","ticket_id":tid,"target_id":int ( row["user_id"] ) }
        return await q.message.reply_text ( f"✉️ #{tid} murojaatga javobingizni yuboring. Matn yoki media mumkin.")

    if d.startswith ( "ownerseen:" ) :
        if u.id not in SUPER_OWNERS: return await q.answer ( "Faqat Super Ega uchun.",show_alert=True)
        tid=int ( d.split ( ":",1 ) [1] ) ; execute ( "UPDATE owner_messages SET status='seen',handled_by=? WHERE id=?", ( u.id,tid ) )
        return await q.answer ( "✅ Ko‘rildi deb belgilandi.",show_alert=True)

    if d.startswith ( "ownerclose:" ) :
        if u.id not in SUPER_OWNERS: return await q.answer ( "Faqat Super Ega uchun.",show_alert=True)
        tid=int ( d.split ( ":",1 ) [1] ) ; execute ( "UPDATE owner_messages SET status='closed',handled_by=? WHERE id=?", ( u.id,tid ) )
        return await q.answer ( "🗑 Murojaat yopildi.",show_alert=True)

    if d=="help:home":
        return await q.edit_message_text(
            "❓ VERITAS V8 — YORDAM MARKAZI\n\n🪶 Veritas qila oladigan barcha asosiy ishlar shu yerda jamlangan.\nKerakli bo‘limni tanlang:",
            reply_markup=help_home_markup ( )
        )

    if d.startswith ( "help:" ) :
        return await q.edit_message_text ( help_text ( d.split ( ":",1 )[1] ),reply_markup=help_menu_markup ( ) )

    if d=="rebus:start":
        if not is_super ( u.id ) :
            return await q.edit_message_text(
                "⛔ AI Rebus yaratish hozircha Super Ega yoki Super Admin boshqaruvida.",
                reply_markup=back_markup ( "home")
            )
        return await q.edit_message_text(
            "🧩 AI REBUS\n\n"
            "1️⃣ Veritas ishlayotgan muhokama guruhiga kiring.\n"
            "2️⃣ Veritasning xabariga reply qilib: *rebus deb yozing.\n"
            "3️⃣ Shaxsiy chatda nechta rebus kerakligini yozing: masalan 5 yoki 10.\n"
            "4️⃣ Veritas javoblarni birma-bir so‘raydi.\n"
            "5️⃣ 1-rebus chiqadi; topilgach o‘chadi va 2-rebus chiqadi.\n"
            "6️⃣ Kanal bog‘langan bo‘lsa kanalga, bo‘lmasa guruhning o‘ziga joylanadi.\n"
            "7️⃣ Oxirida umumiy natija chiqadi.",
            reply_markup=back_markup ( "home")
        )

    if d=="me":
        return await send_public_profile ( ctx,q.message.chat.id,u.id,u.id,q.message)

    if d=="profilefind":
        STATE[u.id]={"mode":"profile_find"}
        return await q.edit_message_text(
            "🔎 A’ZONI TOPISH\n\nA’zoning @username yoki Telegram ID sini yozing.",
            reply_markup=back_markup ( "home")
        )

    if d.startswith ( "plike:" ) :
        target_uid=int ( d.split ( ":",1 ) [1])
        if target_uid==u.id: return await q.answer ( "O‘z profilingizga Qadr berib bo‘lmaydi.",show_alert=True)
        if profile_liked_by ( target_uid,u.id ) :
            execute ( "DELETE FROM profile_likes WHERE target_user_id=? AND voter_user_id=?", ( target_uid,u.id ) )
            notice="Qadr olib tashlandi."
        else:
            execute ( "DELETE FROM profile_dislikes WHERE target_user_id=? AND voter_user_id=?", ( target_uid,u.id ) )
            execute ( "INSERT OR IGNORE INTO profile_likes ( target_user_id,voter_user_id,created_at) VALUES ( ?,?,? ) ", ( target_uid,u.id,now (  )  ) )
            notice="💠 Qadr berildi."
        await q.answer ( notice)
        return await send_public_profile ( ctx,q.message.chat.id,target_uid,u.id,q.message)

    if d.startswith ( "pdislike:" ) :
        target_uid=int ( d.split ( ":",1 ) [1])
        if target_uid==u.id: return await q.answer ( "O‘z profilingizga E’tiroz berib bo‘lmaydi.",show_alert=True)
        if profile_disliked_by ( target_uid,u.id ) :
            execute ( "DELETE FROM profile_dislikes WHERE target_user_id=? AND voter_user_id=?", ( target_uid,u.id ) )
            notice="E’tiroz olib tashlandi."
        else:
            execute ( "DELETE FROM profile_likes WHERE target_user_id=? AND voter_user_id=?", ( target_uid,u.id ) )
            execute ( "INSERT OR IGNORE INTO profile_dislikes ( target_user_id,voter_user_id,created_at) VALUES ( ?,?,? ) ", ( target_uid,u.id,now (  )  ) )
            notice="⚖️ E’tiroz bildirildi."
        await q.answer ( notice)
        return await send_public_profile ( ctx,q.message.chat.id,target_uid,u.id,q.message)

    if d=="libaisearch":
        STATE[u.id]={"mode":"lib_ai_search"}
        return await q.edit_message_text(
            "🤖 AI KITOB QIDIRUV\n\n"
            "Qanday kitob kerakligini oddiy gap bilan yozing.\n"
            "Masalan: “Sabr haqida kitob”, “qiziqarli tarixiy kitob”, "
            "“bolalar tarbiyasi haqida”.\n\n"
            "🔒 AI faqat Vasatiya kutubxonasiga qo‘shilgan kitoblardan topadi.",
            reply_markup=back_markup ( "library")
        )

    if d=="hadaisearch":
        STATE[u.id]={"mode":"had_ai_search"}
        return await q.edit_message_text(
            "🤖 AI HADIS QIDIRUV\n\n"
            "Mavzuni oddiy gap bilan yozing. Masalan: “sabr haqida”, “ota-ona haqqi”.\n\n"
            "🔒 AI faqat Veritasga qo‘shilgan hadislar ichidan topadi.",
            reply_markup=back_markup ( "hadith")
        )

    if d=="home":
        try:
            if q.message.photo or q.message.video or q.message.document or q.message.audio or q.message.animation:
                await q.message.delete ( )
                return await ctx.bot.send_message ( q.message.chat.id,"🪶 VERITAS v8\n\nShaxsiy kabinet",reply_markup=main_menu_markup ( u.id ) )
            return await q.edit_message_text ( "🪶 VERITAS v8\n\nShaxsiy kabinet",reply_markup=main_menu_markup ( u.id ) )
        except TelegramError:
            return await ctx.bot.send_message ( q.message.chat.id,"🪶 VERITAS v8\n\nShaxsiy kabinet",reply_markup=main_menu_markup ( u.id ) )

    if d.startswith ( "topgift:") or d.startswith ( "topplain:" ) :
        if not is_super ( u.id ): return
        chat_id=int ( d.split ( ":",1 ) [1] ) ; with_gifts=d.startswith ( "topgift:")
        await q.edit_message_text ( "⏳ TOP-10 hisoblanmoqda..." if not with_gifts else "⏳ TOP-10 va TOP-3 Giftlar tayyorlanmoqda...")
        return await top10_result ( ctx.bot,chat_id,with_gifts,u.id)

    if d=="me":
        return await q.edit_message_text ( global_profile_text ( u ),reply_markup=back_markup ( ) )

    if d=="qadrtop":
        return await q.edit_message_text ( qadr_top_text ( 10 ) ,reply_markup=back_markup ( "home" ) )

    if d=="globalactive":
        return await q.edit_message_text ( global_active_text ( 10 ),reply_markup=back_markup ( ) )

    if d=="ai_private":
        until=ai_user_until ( u.id )
        if is_super ( u.id ): status="👑 FAOL — "+super_role ( u.id )
        elif until>now ( ): status="✅ FAOL\n📅 "+fmt_until ( until )
        else: status="❌ FAOL EMAS"
        if not ai_user_trial_used ( u.id ) and not is_super ( u.id ):
            kb=InlineKeyboardMarkup ( [[InlineKeyboardButton ( "🎁 30 kun BEPUL",callback_data="aiptrial" ) ],[InlineKeyboardButton ( "⬅️ Orqaga",callback_data="home" ) ]] )
            price_text="🎁 Birinchi 30 kun — BEPUL\nKeyingi 30 kun — 10 ⭐"
        else:
            kb=InlineKeyboardMarkup ( [[InlineKeyboardButton ( "💎 10 ⭐ — 30 kun",callback_data="aipbuy" ) ],[InlineKeyboardButton ( "⬅️ Orqaga",callback_data="home" ) ]] )
            price_text="Premium narxi: 10 ⭐ / 30 kun."
        return await q.edit_message_text ( f"🤖 VERITAS AI — SHAXSIY YORDAMCHI\n\n{status}\n\n{price_text}\nFaol bo‘lsa botga oddiy xabar yozishingiz kifoya.",reply_markup=kb )

    if d=="aiptrial":
        if is_super ( u.id ): return await q.answer ( "Super boshqaruv uchun AI allaqachon faol.",show_alert=True )
        until=claim_ai_user_trial ( u.id )
        if not until: return await q.answer ( "Bepul 30 kunlik muddat avval ishlatilgan.",show_alert=True )
        return await q.edit_message_text ( f"🎁 Shaxsiy Veritas AI Premium 30 kun BEPUL yoqildi.\n📅 {fmt_until ( until )} gacha\n\nKeyingi 30 kun — 10 ⭐",reply_markup=back_markup ( "home" ) )

    if d=="aipbuy":
        if is_super ( u.id ): return await q.answer ( "Super boshqaruv uchun AI allaqachon faol.",show_alert=True )
        if not ai_user_trial_used ( u.id ):
            return await q.answer ( "Avval bepul 30 kunlik muddatdan foydalaning.",show_alert=True )
        if wallet ( u.id ) <AI_PRIVATE_PRICE: return await q.answer ( "Kredit yetarli emas. Hisobni Stars bilan to‘ldiring.",show_alert=True )
        if not wallet_change ( u.id,-AI_PRIVATE_PRICE,"ai_private_30d",u.id ): return
        until=extend_ai_user ( u.id,AI_PRIVATE_DAYS )
        return await q.edit_message_text ( f"✅ Shaxsiy Veritas AI Premium yoqildi.\n💎 {AI_PRIVATE_PRICE} ⭐\n📅 {fmt_until ( until )} gacha",reply_markup=back_markup ( "home" ) )

    if d.startswith ( "aigtrial:" ) :
        chat_id=int ( d.split ( ":" )[1] )
        until=claim_ai_group_trial ( chat_id,u.id )
        if not until: return await q.answer ( "Bu guruhning bepul 30 kuni avval ishlatilgan.",show_alert=True )
        return await q.edit_message_text ( f"🎁 Veritas AI guruh uchun 30 kun BEPUL yoqildi.\n📅 {fmt_until ( until )} gacha\n\nKeyingi 30 kun — 100 ⭐",reply_markup=ai_group_menu ( chat_id,u.id ) )

    if d.startswith ( "aigbuy:" ) :
        _,schat,sdays=d.split ( ":" ); chat_id=int ( schat ); days=int ( sdays ); price=AI_GROUP_PLANS.get ( days )
        if not price: return
        if not ai_group_trial_used ( chat_id ):
            return await q.answer ( "Avval guruh uchun bepul 30 kunlik muddatni yoqing.",show_alert=True )
        if wallet ( u.id ) <price: return await q.answer ( f"Kredit yetarli emas. Kerak: {price} ⭐",show_alert=True )
        if not wallet_change ( u.id,-price,f"ai_group_{days}d",chat_id ): return
        until=extend_ai_group ( chat_id,days,u.id,"paid" )
        return await q.edit_message_text ( f"✅ Veritas AI guruh uchun yoqildi.\n⭐ {price}\n📅 {fmt_until ( until )} gacha",reply_markup=ai_group_menu ( chat_id,u.id ) )

    if d.startswith ( "aigfree:" ) :
        if not is_super ( u.id ): return await q.answer ( "Faqat Super Ega.",show_alert=True )
        _,schat,sdays=d.split ( ":" ); chat_id=int ( schat ); days=int ( sdays )
        if days not in ( 1,7,30 ): return
        until=extend_ai_group ( chat_id,days,u.id,"super_free" )
        return await q.edit_message_text ( f"👑 Guruhga Veritas AI bepul yoqildi.\n📅 {days} kun — {fmt_until ( until )} gacha",reply_markup=ai_group_menu ( chat_id,u.id ) )

    if d.startswith ( "aigoff:" ) :
        if not is_super ( u.id ): return await q.answer ( "Faqat Super Ega.",show_alert=True )
        chat_id=int ( d.split ( ":" )[1] ); execute ( "UPDATE ai_group_subscriptions SET paid_until=0,updated_at=? WHERE chat_id=?", ( now ( ),chat_id ) )
        return await q.edit_message_text ( "⛔ Bu guruh uchun Veritas AI o‘chirildi.",reply_markup=ai_group_menu ( chat_id,u.id ) )

    if d=="wallet":
        kb=[[InlineKeyboardButton ( f"{x} ⭐",callback_data=f"top:{x}") for x in TOPUPS[i:i+3]] for i in range ( 0,len ( TOPUPS ) ,3 ) ]
        kb.append ( [InlineKeyboardButton ( "⬅️ Orqaga",callback_data="home" ) ,InlineKeyboardButton ( "🏠 Bosh menyu",callback_data="home" ) ])
        return await q.edit_message_text ( f"⭐ Kredit: {wallet ( u.id ) }\nTo‘ldirish:",reply_markup=InlineKeyboardMarkup ( kb ) )

    if d.startswith ( "top:" ) :
        amount=int ( d.split ( ":" ) [1])
        return await ctx.bot.send_invoice ( chat_id=u.id,title="Veritas Stars krediti",description=f"{amount} ⭐ kredit",payload=f"topup:{u.id}:{amount}:{now (  ) }",currency="XTR",prices=[LabeledPrice ( "Stars",amount ) ])

    if d=="gifts":
        try:
            gs=await ctx.bot.get_available_gifts (  ) ; prices=sorted ( {int ( g.star_count) for g in gs.gifts})
            return await q.edit_message_text ( "🎁 Hozirgi Gift narxlari:\n"+", ".join ( f"{p} ⭐" for p in prices[:50] ) +"\n\nGuruhda oluvchiga reply: *give <narx>",reply_markup=back_markup (  ) )
        except Exception as e: return await q.edit_message_text ( f"❌ {e}",reply_markup=back_markup (  ) )

    if d=="premium":
        return await q.edit_message_text ( "💎 Premium: 3 oy — 1000 ⭐ | 6 oy — 1500 ⭐ | 12 oy — 2500 ⭐\nGuruhda reply: *premium 3",reply_markup=back_markup (  ) )

    if d=="mygroups":
        rows=all_ ( "SELECT chat_id,title FROM groups WHERE owner_id=? OR chat_id IN (SELECT chat_id FROM vadmins WHERE user_id=? ) ", ( u.id,u.id ) )
        return await q.edit_message_text ( "🏘 "+ ( "\n".join ( f"{r['title']} ({r['chat_id']} ) " for r in rows) or "Guruh topilmadi." ) ,reply_markup=back_markup (  ) )

    if d=="about":
        text= ( "ℹ️ VERITAS v8\n\n"
              "Veritas — guruh boshqaruvi, faollik, Stars/Gift/Premium va Vasatiya kutubxonasini bir joyga jamlaydigan Telegram bot.\n\n"
              "📚 Vasatiya kutubxonasi — PDF va audio kitoblar, tillar, kategoriyalar, qidiruv va sevimlilar.\n"
              "📜 Sahih Hadislar — hadis bazasi, to‘plamlar va random hadis.\n"
              "🛡 Guruhlar — moderatsiya, blacklist, lock, antiflood, filter va notes.\n"
              "⭐ Kabinet — Stars krediti, Telegram Gift va Premium.\n\n"
              "Buyruqlar uchun: *help")
        return await q.edit_message_text ( text,reply_markup=back_markup (  ) )

    if d=="hadith":
        total=one ( "SELECT COUNT ( *) n FROM hadiths WHERE status='approved'" ) ["n"]
        cols=all_ ( "SELECT collection,COUNT ( *) n FROM hadiths WHERE status='approved' GROUP BY collection ORDER BY collection")
        kb=[[InlineKeyboardButton ( f"📚 {r['collection']} · {r['n']}",callback_data=f"hcol:{r['collection']}:0" ) ] for r in cols[:20]]
        kb.append ( [InlineKeyboardButton ( "🤖 AI Hadis qidirish",callback_data="hadaisearch" ) ])
        kb.append ( [InlineKeyboardButton ( "🎲 Random hadis",callback_data="hrandom" ) ])
        if is_hadith_admin ( u.id ) : kb.append ( [InlineKeyboardButton ( "➕ Hadis qo‘shish",callback_data="hadd" ) ])
        kb.append ( [InlineKeyboardButton ( "⬅️ Orqaga",callback_data="home" ) ,InlineKeyboardButton ( "🏠 Bosh menyu",callback_data="home" ) ])
        txt=f"📜 SAHIH HADISLAR\n\nJami hadislar: {total}\nTo‘plamni tanlang yoki random hadis o‘qing."
        try:
            if q.message.photo or q.message.video or q.message.document or q.message.audio or q.message.animation:
                await q.message.delete (  ) ; return await ctx.bot.send_message ( q.message.chat.id,txt,reply_markup=InlineKeyboardMarkup ( kb ) )
            return await q.edit_message_text ( txt,reply_markup=InlineKeyboardMarkup ( kb ) )
        except TelegramError:
            return await ctx.bot.send_message ( q.message.chat.id,txt,reply_markup=InlineKeyboardMarkup ( kb ) )

    if d=="hadd":
        if not is_hadith_admin ( u.id ) : return await q.answer ( "Ruxsat yo‘q",show_alert=True)
        STATE[u.id]={"mode":"had_add_collection","data":{}}
        return await q.edit_message_text ( "📜 HADIS QO‘SHISH — 1/6\n\nTo‘plam nomini yuboring.\nMisol: Buxoriy")

    if d=="hrandom":
        r=one ( "SELECT * FROM hadiths WHERE status='approved' ORDER BY RANDOM ( ) LIMIT 1")
        if not r: return await q.edit_message_text ( "📜 Hozircha hadis bazasi bo‘sh.",reply_markup=back_markup ( "home" ) )
        return await q.edit_message_text ( hadith_text ( r ) ,reply_markup=hadith_markup ( r ) )

    if d.startswith ( "hcol:" ) :
        _,collection,spage=d.split ( ":",2 ) ; page=max ( 0,int ( spage )  ) ; per=10; off=page*per
        total=one ( "SELECT COUNT ( *) n FROM hadiths WHERE collection=? AND status='approved'", ( collection, )  ) ["n"]
        rows=all_ ( "SELECT id,number FROM hadiths WHERE collection=? AND status='approved' ORDER BY number LIMIT ? OFFSET ?", ( collection,per,off ) )
        kb=[[InlineKeyboardButton ( f"📜 {collection} {r['number']}",callback_data=f"hshow:{r['id']}" ) ] for r in rows]
        nav=[]
        if page>0: nav.append ( InlineKeyboardButton ( "◀️",callback_data=f"hcol:{collection}:{page-1}" ) )
        if off+per<total: nav.append ( InlineKeyboardButton ( "▶️",callback_data=f"hcol:{collection}:{page+1}" ) )
        if nav: kb.append ( nav)
        kb.append ( [InlineKeyboardButton ( "⬅️ Hadislar",callback_data="hadith" ) ])
        return await q.edit_message_text ( f"📚 {collection} · {total} ta hadis",reply_markup=InlineKeyboardMarkup ( kb ) )

    if d.startswith ( "hshow:" ) :
        hid=int ( d.split ( ":" ) [1] ) ; r=one ( "SELECT * FROM hadiths WHERE id=? AND status='approved'", ( hid, ) )
        if not r: return await q.edit_message_text ( "❌ Hadis topilmadi.",reply_markup=back_markup ( "hadith" ) )
        if is_hadith_admin ( u.id ) :
            uploader=one ( "SELECT first_name FROM users WHERE user_id=?", ( r["added_by"], ) ); nm= ( uploader["first_name"] if uploader and uploader["first_name"] else f"ID {r['added_by']}")
            kb=InlineKeyboardMarkup ( [[InlineKeyboardButton ( f"👤 Qo‘shdi: {nm[:35]}",url=f"tg://user?id={r['added_by']}" ) ],[InlineKeyboardButton ( "✏️ Tahrirlash",callback_data=f"hedit:{r['id']}" ) ,InlineKeyboardButton ( "🗑 O‘chirish",callback_data=f"hdelask:{r['id']}" ) ],[InlineKeyboardButton ( "⬅️ Hadislar",callback_data="hadith" ) ,InlineKeyboardButton ( "🏠 Bosh menyu",callback_data="home" ) ]] )
            return await q.edit_message_text ( hadith_text ( r ),reply_markup=kb )
        return await q.edit_message_text ( hadith_text ( r ) ,reply_markup=hadith_markup ( r ) )

    if d.startswith ( "hedit:" ) :
        if not is_hadith_admin ( u.id ) : return await q.answer ( "Ruxsat yo‘q",show_alert=True )
        hid=int ( d.split ( ":" )[1] ); r=one ( "SELECT * FROM hadiths WHERE id=? AND status='approved'", ( hid, ) )
        if not r: return await q.edit_message_text ( "❌ Hadis topilmadi.",reply_markup=back_markup ( "hadith" ) )
        kb=InlineKeyboardMarkup ( [
          [InlineKeyboardButton ( "📚 To‘plam",callback_data=f"heditfield:{hid}:collection" ) ,InlineKeyboardButton ( "🔢 Raqam",callback_data=f"heditfield:{hid}:number" ) ],
          [InlineKeyboardButton ( "🇸🇦 Arabcha",callback_data=f"heditfield:{hid}:arabic" ) ,InlineKeyboardButton ( "🇺🇿 Tarjima",callback_data=f"heditfield:{hid}:translation" ) ],
          [InlineKeyboardButton ( "📝 Sharh",callback_data=f"heditfield:{hid}:explanation" ) ,InlineKeyboardButton ( "📖 Manba",callback_data=f"heditfield:{hid}:source" ) ],
          [InlineKeyboardButton ( "⬅️ Hadis",callback_data=f"hshow:{hid}" ) ] ] )
        return await q.edit_message_text ( "✏️ HADISNI TAHRIRLASH\n\nQaysi qismini o‘zgartirasiz?",reply_markup=kb )

    if d.startswith ( "heditfield:" ) :
        if not is_hadith_admin ( u.id ) : return await q.answer ( "Ruxsat yo‘q",show_alert=True )
        _,shid,field=d.split ( ":",2 ); hid=int ( shid )
        prompts={"collection":"Yangi to‘plam nomini yuboring:","number":"Yangi hadis raqamini yuboring:","arabic":"Yangi arabcha matnni yuboring. Olib tashlash uchun: o‘chirish","translation":"Yangi o‘zbekcha tarjimani yuboring:","explanation":"Yangi sharhni yuboring. Olib tashlash uchun: o‘chirish","source":"Yangi manbani yuboring. Olib tashlash uchun: o‘chirish"}
        if field not in prompts: return
        STATE[u.id]={"mode":f"had_edit_{field}","data":{"hadith_id":hid}}
        return await q.edit_message_text ( "✏️ "+prompts[field],reply_markup=back_markup ( f"hedit:{hid}" ) )

    if d.startswith ( "hdelask:" ) :
        if not is_hadith_admin ( u.id ) : return await q.answer ( "Ruxsat yo‘q",show_alert=True )
        hid=int ( d.split ( ":" )[1] ); r=one ( "SELECT collection,number FROM hadiths WHERE id=?", ( hid, ) )
        if not r: return
        kb=InlineKeyboardMarkup ( [[InlineKeyboardButton ( "✅ O‘chirish",callback_data=f"hdel:{hid}" ) ,InlineKeyboardButton ( "❌ Bekor",callback_data=f"hshow:{hid}" ) ]] )
        return await q.edit_message_text ( f"🗑 {r['collection']} {r['number']} hadisni o‘chirishni tasdiqlaysizmi?",reply_markup=kb )

    if d.startswith ( "hdel:" ) :
        if not is_hadith_admin ( u.id ) : return await q.answer ( "Ruxsat yo‘q",show_alert=True)
        hid=int ( d.split ( ":" ) [1] ) ; r=one ( "SELECT collection,number FROM hadiths WHERE id=? AND status='approved'", ( hid, ) )
        if not r: return await q.edit_message_text ( "❌ Hadis topilmadi.",reply_markup=back_markup ( "hadith" ) )
        execute ( "UPDATE hadiths SET status='deleted' WHERE id=?", ( hid, )  ) ; audit ( u.id,0,"hadith_delete",f"{r['collection']} {r['number']}")
        return await q.edit_message_text ( f"✅ {r['collection']} {r['number']} o‘chirildi.",reply_markup=back_markup ( "hadith" ) )

    if d=="libskipaudio":
        st=STATE.get ( u.id)
        if not st or st.get ( "mode" ) !="lib_add_audio":
            return await q.answer ( "Kitob qo‘shish jarayoni faol emas.",show_alert=True)
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
        return await q.edit_message_text ( f"✅ Kitob Vasatiya kutubxonasiga qo‘shildi.\n📖 {data['title']}\nID: {bid}",reply_markup=library_home_markup ( u.id ) )

    if d=="library":
        total=one ( "SELECT COUNT ( *) n FROM library_books WHERE status='approved'" ) ["n"]
        txt=f"📚 VASATIYA KUTUBXONASI\n\nJami kitoblar: {total}\nTil, kategoriya yoki qidiruv orqali kitob toping."
        try:
            if q.message.photo or q.message.video or q.message.document or q.message.audio or q.message.animation:
                await q.message.delete ( )
                return await ctx.bot.send_message ( q.message.chat.id,txt,reply_markup=library_home_markup ( u.id ) )
            return await q.edit_message_text ( txt,reply_markup=library_home_markup ( u.id ) )
        except TelegramError:
            return await ctx.bot.send_message ( q.message.chat.id,txt,reply_markup=library_home_markup ( u.id ) )

    if d=="libsearch":
        STATE[u.id]={"mode":"lib_search"}
        return await q.edit_message_text ( "🔎 Kitob nomi, muallif yoki kalit so‘zni yuboring:",reply_markup=back_markup ( "library" ) )

    if d=="libadd":
        if not is_library_admin ( u.id ) : return await q.edit_message_text ( "⛔ Ruxsat yo‘q.",reply_markup=back_markup ( "library" ) )
        STATE[u.id]={"mode":"lib_quick_file","data":{}}
        return await q.edit_message_text(
            "➕ KITOB QO‘SHISH\n\n"
            "📎 Kitob faylini yuboring — nomini Veritas avtomatik oladi va kitobni darhol saqlaydi.\n\n"
            "✅ PDF • EPUB • DOCX • TXT • FB2 • MOBI • DJVU\n\n"
            "Saqlangandan keyin nomi, muallifi, tili, kategoriya, tavsif va muqovani "
            "✏️ Tahrirlash orqali o‘zgartirishingiz mumkin.",
            reply_markup=back_markup ( "library" )
        )

    if d.startswith ( "libaddlang:" ) :
        st=STATE.get ( u.id)
        if not st or st.get ( "mode" ) !="lib_add_lang": return await q.edit_message_text ( "Jarayon eskirgan. Qaytadan boshlang.",reply_markup=back_markup ( "library" ) )
        lang=d.split ( ":",1 ) [1]
        if lang not in ("uz","ru","en" ) : return
        st["data"]["lang"]=lang; st["mode"]="lib_add_categories"
        return await q.edit_message_text ( "🗂 Kategoriyalarni vergul bilan yuboring.\nMisol: Islomiy, Hadis, Tarix")

    if d.startswith ( "libnew:" ) :
        page=max ( 0,int ( d.split ( ":" ) [1] )  ) ; per=8; off=page*per
        total=one ( "SELECT COUNT ( *) n FROM library_books WHERE status='approved'" ) ["n"]
        rows=all_ ( "SELECT id,title FROM library_books WHERE status='approved' ORDER BY id DESC LIMIT ? OFFSET ?", ( per,off ) )
        return await q.edit_message_text ( f"🆕 Yangi kitoblar · {page+1}-sahifa",reply_markup=library_list_markup ( rows,page,"libnew",total ) )

    if d.startswith ( "liblang:" ) :
        _,lang,spage=d.split ( ":" ) ; page=max ( 0,int ( spage )  ) ; per=8; off=page*per
        total=one ( "SELECT COUNT ( *) n FROM library_books WHERE status='approved' AND lang=?", ( lang, )  ) ["n"]
        rows=all_ ( "SELECT id,title FROM library_books WHERE status='approved' AND lang=? ORDER BY id DESC LIMIT ? OFFSET ?", ( lang,per,off ) )
        return await q.edit_message_text ( f"{lib_lang_name ( lang ) } · {total} ta kitob",reply_markup=library_list_markup ( rows,page,"liblang",total,lang ) )

    if d.startswith ( "libfav:" ) :
        page=max ( 0,int ( d.split ( ":" ) [1] )  ) ; per=8; off=page*per
        total=one ( "SELECT COUNT ( *) n FROM library_favorites f JOIN library_books b ON b.id=f.book_id WHERE f.user_id=? AND b.status='approved'", ( u.id, )  ) ["n"]
        rows=all_ ( """SELECT b.id,b.title FROM library_favorites f JOIN library_books b ON b.id=f.book_id
                     WHERE f.user_id=? AND b.status='approved' ORDER BY f.created_at DESC LIMIT ? OFFSET ?""", ( u.id,per,off ) )
        return await q.edit_message_text ( f"❤️ Sevimlilar · {total} ta",reply_markup=library_list_markup ( rows,page,"libfav",total ) )

    if d=="libcats:0" or d.startswith ( "libcats:" ) :
        page=max ( 0,int ( d.split ( ":" ) [1] )  ) ; per=10; off=page*per
        total=one ( "SELECT COUNT ( *) n FROM library_categories" ) ["n"]
        rows=all_ ( "SELECT id,name FROM library_categories ORDER BY name LIMIT ? OFFSET ?", ( per,off ) )
        kb=[[InlineKeyboardButton ( "🗂 "+r["name"][:35],callback_data=f"libcat:{r['id']}:0" ) ] for r in rows]
        nav=[]
        if page>0: nav.append ( InlineKeyboardButton ( "◀️",callback_data=f"libcats:{page-1}" ) )
        if off+per<total: nav.append ( InlineKeyboardButton ( "▶️",callback_data=f"libcats:{page+1}" ) )
        if nav: kb.append ( nav)
        kb.append ( [InlineKeyboardButton ( "⬅️ Kutubxona",callback_data="library" ) ])
        return await q.edit_message_text ( "🗂 KATEGORIYALAR",reply_markup=InlineKeyboardMarkup ( kb ) )

    if d.startswith ( "libcat:" ) :
        _,scid,spage=d.split ( ":" ) ; cid=int ( scid ) ; page=max ( 0,int ( spage )  ) ; per=8; off=page*per
        cr=one ( "SELECT name FROM library_categories WHERE id=?", ( cid, ) )
        if not cr: return await q.edit_message_text ( "Kategoriya topilmadi.",reply_markup=back_markup ( "library" ) )
        total=one ( """SELECT COUNT ( *) n FROM library_book_categories bc JOIN library_books b ON b.id=bc.book_id
                     WHERE bc.category_id=? AND b.status='approved'""", ( cid, )  ) ["n"]
        rows=all_ ( """SELECT b.id,b.title FROM library_book_categories bc JOIN library_books b ON b.id=bc.book_id
                     WHERE bc.category_id=? AND b.status='approved' ORDER BY b.id DESC LIMIT ? OFFSET ?""", ( cid,per,off ) )
        kb=[]
        for r in rows: kb.append ( [InlineKeyboardButton ( "📖 "+r["title"][:38],callback_data=f"libbook:{r['id']}" ) ])
        nav=[]
        if page>0: nav.append ( InlineKeyboardButton ( "◀️",callback_data=f"libcat:{cid}:{page-1}" ) )
        if off+per<total: nav.append ( InlineKeyboardButton ( "▶️",callback_data=f"libcat:{cid}:{page+1}" ) )
        if nav: kb.append ( nav)
        kb.append ( [InlineKeyboardButton ( "⬅️ Kategoriyalar",callback_data="libcats:0" ) ])
        return await q.edit_message_text ( f"🗂 {cr['name']} · {total} ta",reply_markup=InlineKeyboardMarkup ( kb ) )

    if d.startswith ( "libtranslate:" ) :
        bid=int ( d.split ( ":" ) [1])
        if not ai_user_active ( u.id ) :
            kb=InlineKeyboardMarkup ( [[InlineKeyboardButton ( "💎 10 ⭐ — 30 kun",callback_data="aipbuy" ) ],[InlineKeyboardButton ( "⬅️ Kitob",callback_data=f"libbook:{bid}" ) ]])
            return await quiz_replace_message ( q,ctx,"🔒 AI KITOB TARJIMASI — Premium funksiya.\n\n💎 10 ⭐ / 30 kun\nPremium a’zo 24 soatda 1 ta kitob tarjima qila oladi.",reply_markup=kb)
        wait=_translation_wait_seconds ( u.id)
        if wait>0: return await q.answer ( f"⏳ Kunlik limit ishlatilgan. Taxminan { ( wait+3599 ) //3600} soat qoldi.",show_alert=True)
        kb=InlineKeyboardMarkup ( [[InlineKeyboardButton ( "🇺🇿 O‘zbekcha",callback_data=f"libtrun:{bid}:uz" ) ],[InlineKeyboardButton ( "🇷🇺 Ruscha",callback_data=f"libtrun:{bid}:ru" ) ,InlineKeyboardButton ( "🇬🇧 English",callback_data=f"libtrun:{bid}:en" ) ],[InlineKeyboardButton ( "⬅️ Kitob",callback_data=f"libbook:{bid}" ) ]])
        return await quiz_replace_message ( q,ctx,"🌐 AI KITOB TARJIMASI\n\nTarjima tilini tanlang.\nPremium: 24 soatda 1 ta muvaffaqiyatli kitob tarjimasi.",reply_markup=kb)

    if d.startswith ( "libtrun:" ) :
        _,sbid,lang=d.split ( ":")
        task=asyncio.create_task ( _run_book_translation ( q,ctx,int ( sbid ) ,lang ) )
        def _translation_task_done ( t ) :
            try:
                t.result ( )
            except asyncio.CancelledError:
                pass
            except Exception:
                log.exception ( "Background book translation task failed")
        task.add_done_callback ( _translation_task_done)
        return

    if d.startswith ( "libquiz:" ) :
        bid=int ( d.split ( ":" )[1] )
        r=one ( "SELECT title,pdf_file_id FROM library_books WHERE id=? AND status='approved'", ( bid,) )
        if not r or not r["pdf_file_id"]: return await q.answer ( "Kitob fayli mavjud emas",show_alert=True )
        groups=await _quiz_allowed_groups ( ctx,u.id )
        if not groups:
            return await quiz_replace_message ( q,ctx,"👥 Test yuborish uchun Veritas ishlayotgan kamida bitta guruhda admin bo‘lishingiz kerak.",reply_markup=InlineKeyboardMarkup ( [[InlineKeyboardButton ( "⬅️ Kitob",callback_data=f"libbook:{bid}" ) ]] ) )
        kb=[]
        for cid,title in groups[:20]: kb.append ( [InlineKeyboardButton ( "👥 "+title[:35],callback_data=f"libqgrp:{bid}:{cid}" ) ] )
        kb.append ( [InlineKeyboardButton ( "⬅️ Kitob",callback_data=f"libbook:{bid}" ) ] )
        return await quiz_replace_message ( q,ctx,f"🧠 TEST TUZISH\n\n📖 {r['title']}\n\nTest qaysi guruhga yuborilsin?",reply_markup=InlineKeyboardMarkup ( kb ) )

    if d.startswith ( "libqgrp:" ) :
        _,sbid,schat=d.split ( ":" ); bid=int ( sbid ); chat_id=int ( schat )
        if not is_super ( u.id ) and not await is_tg_admin ( ctx.bot,chat_id,u.id ):
            return await q.answer ( "Bu guruhda admin emassiz.",show_alert=True )
        gr=one ( "SELECT title FROM groups WHERE chat_id=?", ( chat_id,) ); book=one ( "SELECT title FROM library_books WHERE id=?", ( bid,) )
        if not gr or not book: return await q.answer ( "Kitob yoki guruh topilmadi.",show_alert=True )
        kb=InlineKeyboardMarkup ( [[InlineKeyboardButton ( "5 ta",callback_data=f"libqrun:{bid}:{chat_id}:5" ),InlineKeyboardButton ( "10 ta",callback_data=f"libqrun:{bid}:{chat_id}:10" ),InlineKeyboardButton ( "20 ta",callback_data=f"libqrun:{bid}:{chat_id}:20" )],[InlineKeyboardButton ( "⬅️ Guruhlar",callback_data=f"libquiz:{bid}" ) ]] )
        return await quiz_replace_message ( q,ctx,f"🧠 TEST TUZISH\n\n📖 {book['title']}\n👥 {gr['title']}\n\nNechta test tuzilsin?",reply_markup=kb )

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

    if d.startswith ( "libfile:" ) :
        bid=int ( d.split ( ":" ) [1])
        r=one ( """SELECT title,book_file_id,book_file_name,book_format,pdf_file_id
                 FROM library_books WHERE id=? AND status='approved'""", ( bid, ) )
        if not r: return await q.answer ( "Kitob topilmadi",show_alert=True)
        fid=r["book_file_id"] or r["pdf_file_id"]
        if not fid: return await q.answer ( "Kitob fayli mavjud emas",show_alert=True)
        execute ( "UPDATE library_books SET downloads=downloads+1 WHERE id=?", ( bid, ) )
        try:
            return await ctx.bot.send_document(
                u.id,fid,
                caption=f"📚 {r['title']}\n📁 { ( r['book_format'] or 'PDF' ) .upper (  ) }\nVasatiya kutubxonasi"
            )
        except TelegramError:
            log.exception ( "Library file send failed: %s",bid)
            return await q.answer ( "⚠️ Faylni yuborishda xato.",show_alert=True)

    if d.startswith ( "libpdf:" ) :
        bid=int ( d.split ( ":" ) [1] ) ; r=one ( "SELECT title,pdf_file_id FROM library_books WHERE id=? AND status='approved'", ( bid, ) )
        if not r or not r["pdf_file_id"]: return await q.answer ( "Kitob fayli mavjud emas",show_alert=True)
        execute ( "UPDATE library_books SET downloads=downloads+1 WHERE id=?", ( bid, ) )
        await ctx.bot.send_document ( u.id,r["pdf_file_id"],caption=f"📚 {r['title']}\nVasatiya kutubxonasi")
        return

    if d.startswith ( "libaudio:" ) :
        bid=int ( d.split ( ":" ) [1] ) ; r=one ( "SELECT title,audio_file_id FROM library_books WHERE id=? AND status='approved'", ( bid, ) )
        if not r or not r["audio_file_id"]: return await q.answer ( "Audio mavjud emas",show_alert=True)
        execute ( "UPDATE library_books SET downloads=downloads+1 WHERE id=?", ( bid, ) )
        try: await ctx.bot.send_audio ( u.id,r["audio_file_id"],caption=f"🎧 {r['title']}\nVasatiya kutubxonasi")
        except Exception: await ctx.bot.send_document ( u.id,r["audio_file_id"],caption=f"🎧 {r['title']}")
        return

    if d.startswith ( "libedit:" ) :
        if not is_library_admin ( u.id ) : return await q.answer ( "Ruxsat yo‘q",show_alert=True )
        bid=int ( d.split ( ":" )[1] ); r=one ( "SELECT id,title FROM library_books WHERE id=? AND status='approved'", ( bid, ) )
        if not r: return await q.edit_message_text ( "❌ Kitob topilmadi.",reply_markup=back_markup ( "library" ) )
        kb=InlineKeyboardMarkup ( [
          [InlineKeyboardButton ( "📖 Nomi",callback_data=f"libeditfield:{bid}:title" ) ,InlineKeyboardButton ( "✍️ Muallif",callback_data=f"libeditfield:{bid}:author" ) ],
          [InlineKeyboardButton ( "🌐 Til",callback_data=f"libeditfield:{bid}:lang" ) ,InlineKeyboardButton ( "🗂 Kategoriya",callback_data=f"libeditfield:{bid}:categories" ) ],
          [InlineKeyboardButton ( "📝 Tavsif",callback_data=f"libeditfield:{bid}:description" ) ,InlineKeyboardButton ( "🖼 Muqova",callback_data=f"libeditfield:{bid}:cover" ) ],
          [InlineKeyboardButton ( "📄 Kitob fayli",callback_data=f"libeditfield:{bid}:pdf" ) ,InlineKeyboardButton ( "🎧 Audio",callback_data=f"libeditfield:{bid}:audio" ) ],
          [InlineKeyboardButton ( "⬅️ Kitob",callback_data=f"libbook:{bid}" ) ] ] )
        txt=f"✏️ KITOBNI TAHRIRLASH\n\n📖 {r['title']}\nQaysi qismini o‘zgartirasiz?"
        try:
            if q.message.photo or q.message.video or q.message.document or q.message.audio or q.message.animation:
                await q.message.delete ( )
                return await ctx.bot.send_message ( q.message.chat.id,txt,reply_markup=kb )
            return await q.edit_message_text ( txt,reply_markup=kb )
        except TelegramError:
            return await ctx.bot.send_message ( q.message.chat.id,txt,reply_markup=kb )

    if d.startswith ( "libeditfield:" ) :
        if not is_library_admin ( u.id ) : return await q.answer ( "Ruxsat yo‘q",show_alert=True )
        _,sbid,field=d.split ( ":",2 ); bid=int ( sbid )
        if field=="lang":
            kb=InlineKeyboardMarkup ( [[InlineKeyboardButton ( "🇺🇿 O‘zbekcha",callback_data=f"libeditlang:{bid}:uz" ) ,InlineKeyboardButton ( "🇷🇺 Русский",callback_data=f"libeditlang:{bid}:ru" ) ,InlineKeyboardButton ( "🇬🇧 English",callback_data=f"libeditlang:{bid}:en" ) ],[InlineKeyboardButton ( "⬅️ Orqaga",callback_data=f"libedit:{bid}" ) ]] )
            return await q.edit_message_text ( "🌐 Yangi tilni tanlang:",reply_markup=kb )
        prompts={"title":"Yangi kitob nomini yuboring:","author":"Yangi muallif nomini yuboring:","categories":"Yangi kategoriyalarni vergul bilan yuboring:","description":"Yangi tavsifni yuboring:","cover":"Yangi muqova rasmini yuboring. Olib tashlash uchun: o‘chirish","pdf":"Yangi kitob faylini yuboring (PDF/EPUB/DOCX/TXT/FB2/MOBI/DJVU ) :","audio":"Yangi audio/voice/audio-fayl yuboring. Olib tashlash uchun: o‘chirish"}
        if field not in prompts: return
        STATE[u.id]={"mode":f"lib_edit_{field}","data":{"book_id":bid}}
        return await q.edit_message_text ( "✏️ "+prompts[field],reply_markup=back_markup ( f"libedit:{bid}" ) )

    if d.startswith ( "libeditlang:" ) :
        if not is_library_admin ( u.id ) : return await q.answer ( "Ruxsat yo‘q",show_alert=True )
        _,sbid,lang=d.split ( ":",2 ); bid=int ( sbid )
        if lang not in {"uz","ru","en"}: return
        execute ( "UPDATE library_books SET lang=? WHERE id=?", ( lang,bid ) ); audit ( u.id,0,"library_edit",f"{bid}:lang" )
        return await q.edit_message_text ( "✅ Kitob tili yangilandi.",reply_markup=InlineKeyboardMarkup ( [[InlineKeyboardButton ( "✏️ Tahrirlash",callback_data=f"libedit:{bid}" ) ,InlineKeyboardButton ( "📖 Kitob",callback_data=f"libbook:{bid}" ) ]] ) )

    if d.startswith ( "libdelask:" ) :
        if not is_library_admin ( u.id ) : return
        bid=int ( d.split ( ":" ) [1] ) ; r=one ( "SELECT title FROM library_books WHERE id=?", ( bid, ) )
        if not r: return
        kb=InlineKeyboardMarkup ( [[InlineKeyboardButton ( "✅ Ha, o‘chirish",callback_data=f"libdel:{bid}" ) ,InlineKeyboardButton ( "❌ Bekor",callback_data=f"libbook:{bid}" ) ]])
        return await q.edit_message_text ( f"🗑 «{r['title']}» kitobini o‘chirishni tasdiqlaysizmi?",reply_markup=kb)

    if d.startswith ( "libdel:" ) :
        if not is_library_admin ( u.id ) : return
        bid=int ( d.split ( ":" ) [1] ) ; execute ( "UPDATE library_books SET status='deleted' WHERE id=?", ( bid, )  ) ; audit ( u.id,0,"library_delete",str ( bid ) )
        return await q.edit_message_text ( "✅ Kitob kutubxonadan olib tashlandi.",reply_markup=library_home_markup ( u.id ) )

    if d=="super":
        if not is_super ( u.id ): return await q.edit_message_text ( "⛔ Ruxsat yo‘q.")
        uc=one ( "SELECT COUNT ( *) n FROM users" ) ["n"]; gc=one ( "SELECT COUNT ( *) n FROM groups" ) ["n"]
        return await q.edit_message_text ( f"👑 SUPER BOSHQARUV\n🎖 {super_role ( u.id )}\nFoydalanuvchilar: {uc}\nGuruhlar: {gc}",reply_markup=super_menu_markup (  ) )

    if d.startswith ( "alladmins:" ) :
        if not is_super ( u.id ): return
        page=max ( 0,int ( d.split ( ":" ) [1] )  ) ; per=8
        entries=[]
        for sid in sorted ( SUPER_OWNERS ) :
            ur=one ( "SELECT first_name,username FROM users WHERE user_id=?", ( sid, ) )
            nm= ( ur["first_name"] if ur and ur["first_name"] else str ( sid ) )
            if ur and ur["username"]: nm += " @"+ur["username"]
            entries.append (  ( "👑 Super Ega",sid,nm,"" ) )
        for r in all_ ( "SELECT a.user_id,u.first_name,u.username FROM super_admins a LEFT JOIN users u ON u.user_id=a.user_id ORDER BY a.created_at DESC" ) :
            nm=( r["first_name"] or str ( r["user_id"] ) ) + ( ( " @"+r["username"] ) if r["username"] else "" )
            entries.append ( ( "🛡 Super Admin",int ( r["user_id"] ),nm,"" ) )
        for r in all_ ( "SELECT a.user_id,u.first_name,u.username FROM library_admins a LEFT JOIN users u ON u.user_id=a.user_id ORDER BY a.created_at DESC" ) :
            nm= ( r["first_name"] or str ( r["user_id"] ) ) + ( ( " @"+r["username"]) if r["username"] else "")
            entries.append (  ( "📚 Kitob admini",int ( r["user_id"] ) ,nm,"" ) )
        for r in all_ ( "SELECT a.user_id,u.first_name,u.username FROM hadith_admins a LEFT JOIN users u ON u.user_id=a.user_id ORDER BY a.created_at DESC" ) :
            nm= ( r["first_name"] or str ( r["user_id"] ) ) + ( ( " @"+r["username"]) if r["username"] else "")
            entries.append (  ( "📜 Hadis admini",int ( r["user_id"] ) ,nm,"" ) )
        for r in all_ ( """SELECT v.user_id,v.chat_id,u.first_name,u.username,g.title FROM vadmins v
                         LEFT JOIN users u ON u.user_id=v.user_id LEFT JOIN groups g ON g.chat_id=v.chat_id
                         ORDER BY g.title,u.first_name""" ) :
            nm= ( r["first_name"] or str ( r["user_id"] ) ) + ( ( " @"+r["username"]) if r["username"] else "")
            entries.append (  ( "🪶 Veritas admini",int ( r["user_id"] ) ,nm,r["title"] or str ( r["chat_id"] )  ) )
        # Bir odam bir necha rolga ega bo‘lishi mumkin — rollar alohida ko‘rsatiladi.
        total=len ( entries ) ; off=page*per; chunk=entries[off:off+per]
        lines=[f"🛡 BARCHA ADMINLAR\nJami rollar: {total} | Sahifa: {page+1}\n"]
        for role,uid2,nm,grp in chunk:
            lines.append ( f"{role}\n• {nm}\n• ID: {uid2}" + (f"\n• Guruh: {grp}" if grp else "" ) )
        if not chunk: lines.append ( "Admin topilmadi.")
        nav=[]
        if page>0: nav.append ( InlineKeyboardButton ( "◀️",callback_data=f"alladmins:{page-1}" ) )
        if off+per<total: nav.append ( InlineKeyboardButton ( "▶️",callback_data=f"alladmins:{page+1}" ) )
        kb=[]
        if nav: kb.append ( nav)
        kb.append ( [InlineKeyboardButton ( "⬅️ Super Ega",callback_data="super" ) ,InlineKeyboardButton ( "🏠 Bosh menyu",callback_data="home" ) ])
        return await q.edit_message_text ( "\n\n".join ( lines ) ,reply_markup=InlineKeyboardMarkup ( kb ) )

    if d.startswith ( "botgroups:" ) :
        if not is_super ( u.id ): return
        page=max ( 0,int ( d.split ( ":" ) [1] )  ) ; per=8; off=page*per
        rows=all_ ( "SELECT chat_id,title,owner_id,created_at,demo_until,paid_until,free FROM groups ORDER BY created_at DESC,chat_id DESC LIMIT ? OFFSET ?", ( per,off ) )
        total=one ( "SELECT COUNT ( *) n FROM groups" ) ["n"]
        lines=[f"🏘 BOT ISHLAYOTGAN GURUHLAR\nJami: {total} | Sahifa: {page+1}\n"]
        for i,r in enumerate ( rows,off+1 ) :
            owner= ( f" | Ega ID: {r['owner_id']}" if r['owner_id'] else "")
            lines.append ( f"{i}. {r['title'] or 'Nomsiz guruh'}\n🆔 {r['chat_id']}{owner}")
        if not rows: lines.append ( "Guruh topilmadi.")
        nav=[]
        if page>0: nav.append ( InlineKeyboardButton ( "◀️",callback_data=f"botgroups:{page-1}" ) )
        if off+per<total: nav.append ( InlineKeyboardButton ( "▶️",callback_data=f"botgroups:{page+1}" ) )
        kb=[]
        if nav: kb.append ( nav)
        kb.append ( [InlineKeyboardButton ( "⬅️ Super Ega",callback_data="super" ) ,InlineKeyboardButton ( "🏠 Bosh menyu",callback_data="home" ) ])
        return await q.edit_message_text ( "\n\n".join ( lines ) ,reply_markup=InlineKeyboardMarkup ( kb ) )

    if d.startswith ( "cabs:" ) :
        if not is_super ( u.id ): return
        page=max ( 0,int ( d.split ( ":" ) [1] )  ) ; per=8; off=page*per
        rows=all_ ( "SELECT user_id,username,first_name,wallet FROM users ORDER BY created_at DESC,user_id DESC LIMIT ? OFFSET ?", ( per,off ) )
        total=one ( "SELECT COUNT ( *) n FROM users" ) ["n"]
        kb=[]
        for r in rows:
            name= ( r["first_name"] or r["username"] or str ( r["user_id"] )  ) [:28]
            kb.append ( [InlineKeyboardButton ( f"👤 {name} · {r['wallet']}⭐",callback_data=f"cab:{r['user_id']}:{page}" ) ])
        nav=[]
        if page>0: nav.append ( InlineKeyboardButton ( "◀️",callback_data=f"cabs:{page-1}" ) )
        if off+per<total: nav.append ( InlineKeyboardButton ( "▶️",callback_data=f"cabs:{page+1}" ) )
        if nav: kb.append ( nav)
        kb.append ( [InlineKeyboardButton ( "⬅️ Orqaga",callback_data="super" ) ,InlineKeyboardButton ( "🏠 Bosh menyu",callback_data="home" ) ])
        return await q.edit_message_text ( f"👥 SHAXSIY KABINETLAR\nJami: {total} | Sahifa: {page+1}",reply_markup=InlineKeyboardMarkup ( kb ) )

    if d.startswith ( "cab:" ) :
        if not is_super ( u.id ): return
        _,sid,spage=d.split ( ":" ) ; uid=int ( sid ) ; page=int ( spage)
        r=one ( "SELECT * FROM users WHERE user_id=?", ( uid, ) )
        if not r: return await q.edit_message_text ( "Foydalanuvchi topilmadi.",reply_markup=back_markup ( "super" ) )
        xp,msgs=user_total_stats ( uid)
        mr=one ( "SELECT title FROM members WHERE user_id=? AND title<>'' ORDER BY messages DESC LIMIT 1", ( uid, ) )
        custom=mr["title"] if mr else ""
        uname= ( "@"+r["username"]) if r["username"] else "—"
        text= ( f"👤 SHAXSIY KABINET\n\nIsm: {r['first_name'] or '—'}\nUsername: {uname}\n🆔 ID: {uid}\n"
              f"🎖 Unvon: {title_for ( uid,custom ) }\n⭐ Kredit: {r['wallet']}\n✨ XP: {xp}\n💬 Xabarlar: {msgs}\n📈 Level: {level ( xp ) }")
        kb=InlineKeyboardMarkup ( [[InlineKeyboardButton ( "⬅️ Kabinetlar",callback_data=f"cabs:{page}" ) ,InlineKeyboardButton ( "🏠 Bosh menyu",callback_data="home" ) ]])
        return await q.edit_message_text ( text,reply_markup=kb)

async def giveaway_job ( ctx ) :
    rows=all_ ( "SELECT * FROM giveaways WHERE status='open' AND end_at<=?", ( now (  ) , ) )
    for g in rows:
        entries=[r["user_id"] for r in all_ ( "SELECT user_id FROM giveaway_entries WHERE giveaway_id=?", ( g["id"], )  ) ]
        random.shuffle ( entries ) ; winners=entries[:min ( g["winners"],len ( entries )  ) ]
        execute ( "UPDATE giveaways SET status='closed' WHERE id=?", ( g["id"], ) )
        if not winners:
            try: await ctx.bot.send_message ( g["chat_id"],"🎉 Konkurs tugadi. Ishtirokchi yo‘q.")
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
                    await ctx.bot.send_gift ( user_id=uid,gift_id=cand.id,text="🏆 Veritas Giveaway sovrini")
                    sent.append ( uid)
                except Exception:
                    wallet_change ( g["creator_id"],price,"giveaway_rollback",uid)
            except Exception: pass
        try: await ctx.bot.send_message ( g["chat_id"],"🏆 G‘oliblar: "+", ".join ( str ( x) for x in winners ) + ( "\n🎁 Gift yuborildi: "+", ".join ( str ( x) for x in sent) if sent else "\n⚠️ Gift yuborish uchun yaratuvchi krediti/Gift mavjudligini tekshiring." ) )
        except TelegramError: pass

async def error_handler ( update,ctx ) :
    log.exception ( "Handler error",exc_info=ctx.error)


# =========================================================
# V8 ROSE FULL — advanced moderation compatibility layer
# =========================================================
ROSE_REPEAT_CACHE = {}
ROSE_JOIN_CACHE = {}

def rose_full_init_db (  ) :
    with db ( ) as c:
        c.executescript ( """
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
          PRIMARY KEY ( chat_id,user_id,kind)
        );
        CREATE TABLE IF NOT EXISTS owner_messages(
          id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,username TEXT DEFAULT '',first_name TEXT DEFAULT '',
          status TEXT DEFAULT 'new',handled_by INTEGER DEFAULT 0,created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS owner_message_events(
          id INTEGER PRIMARY KEY AUTOINCREMENT,ticket_id INTEGER NOT NULL,sender_id INTEGER NOT NULL,kind TEXT NOT NULL,created_at INTEGER NOT NULL
        );
        """)

def rose_row ( chat_id ) :
    execute ( "INSERT OR IGNORE INTO rose_settings ( chat_id) VALUES ( ? ) ", ( chat_id, ) )
    return one ( "SELECT * FROM rose_settings WHERE chat_id=?", ( chat_id, ) )

def parse_duration ( v ) :
    m=re.fullmatch ( r" ( \d+ )  ( s|m|h|d|w ) ?", ( v or '' ) .lower (  ) )
    if not m:return 0
    n=int ( m.group ( 1 )  ) ; unit=m.group ( 2) or 'm'
    return n*{'s':1,'m':60,'h':3600,'d':86400,'w':604800}[unit]

def rose_content_kind ( msg ) :
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

async def rose_delete ( msg ) :
    try: await msg.delete (  ) ; return True
    except TelegramError:return False

async def rose_advanced_command ( update,ctx,cmd,args ) :
    chat=update.effective_chat; msg=update.effective_message; actor=update.effective_user
    if not chat or chat.type not in ('group','supergroup' ) : return False
    if cmd not in {'purge','pin','unpin','lockall','unlockall','cleanservice','antirepeat','raid','modlog','setwelcome','setgoodbye','tempban','tempmute'}:
        return False
    if not await can_manage ( ctx.bot,chat.id,actor.id ) :
        await msg.reply_text ( '⛔ Bu buyruq uchun admin huquqi kerak.' ) ; return True
    rose_row ( chat.id)
    if cmd=='purge':
        if not msg.reply_to_message:
            await msg.reply_text ( '↩️ Boshlanish xabariga reply qilib *purge yozing.' ) ; return True
        start=msg.reply_to_message.message_id; end=msg.message_id; deleted=0
        for mid in range ( start,end+1 ) :
            try: await ctx.bot.delete_message ( chat.id,mid ) ; deleted+=1
            except TelegramError: pass
        try: await ctx.bot.send_message ( chat.id,f'🧹 {deleted} ta xabar tozalandi.')
        except TelegramError: pass
        return True
    if cmd=='pin':
        t=msg.reply_to_message
        if not t: await msg.reply_text ( '↩️ Pin qilinadigan xabarga reply qiling.' ) ; return True
        try: await ctx.bot.pin_chat_message ( chat.id,t.message_id,disable_notification=True ) ; await msg.reply_text ( '📌 Xabar pin qilindi.')
        except TelegramError as e: await msg.reply_text ( f'❌ Pin bo‘lmadi: {e}')
        return True
    if cmd=='unpin':
        try: await ctx.bot.unpin_chat_message ( chat.id ) ; await msg.reply_text ( '📌 Pin olib tashlandi.')
        except TelegramError as e: await msg.reply_text ( f'❌ {e}')
        return True
    if cmd in {'lockall','unlockall'}:
        val=1 if cmd=='lockall' else 0
        cols=['lock_forward','lock_contact','lock_location','lock_poll','lock_photo','lock_video','lock_audio','lock_voice','lock_document','lock_sticker','lock_animation']
        execute ( 'UPDATE rose_settings SET '+','.join ( f'{x}=?' for x in cols ) +' WHERE chat_id=?',tuple ( [val]*len ( cols ) +[chat.id] ) )
        await msg.reply_text ( '🔒 Barcha media lock yoqildi.' if val else '🔓 Barcha media lock o‘chirildi.' ) ; return True
    if cmd=='cleanservice':
        if not args or args[0].lower ( ) not in ('on','off' ) : await msg.reply_text ( '*cleanservice on/off' ) ; return True
        execute ( 'UPDATE moderation_settings SET clean_service=? WHERE chat_id=?', ( 1 if args[0].lower (  ) =='on' else 0,chat.id ) )
        await msg.reply_text ( '✅ Service xabarlar sozlamasi saqlandi.' ) ; return True
    if cmd=='antirepeat':
        if not args or args[0].lower ( ) not in ('on','off' ) : await msg.reply_text ( '*antirepeat on/off [limit]' ) ; return True
        val=1 if args[0].lower (  ) =='on' else 0; lim=int ( args[1]) if len ( args ) >1 and args[1].isdigit ( ) else 4
        execute ( 'UPDATE rose_settings SET anti_repeat=?,repeat_limit=? WHERE chat_id=?', ( val,max ( 2,min ( lim,10 )  ) ,chat.id ) )
        await msg.reply_text ( '🔁 Anti-repeat yangilandi.' ) ; return True
    if cmd=='raid':
        if not args or args[0].lower ( ) not in ('on','off' ) : await msg.reply_text ( '*raid on/off' ) ; return True
        execute ( 'UPDATE rose_settings SET anti_raid=? WHERE chat_id=?', ( 1 if args[0].lower (  ) =='on' else 0,chat.id )  ) ; await msg.reply_text ( '🛡 Anti-raid yangilandi.' ) ; return True
    if cmd in {'setwelcome','setgoodbye'}:
        txt=' '.join ( args ) .strip ( )
        if not txt and msg.reply_to_message: txt=msg.reply_to_message.text or msg.reply_to_message.caption or ''
        if not txt: await msg.reply_text ( f'*{cmd} <matn>' ) ; return True
        col='welcome_text' if cmd=='setwelcome' else 'goodbye_text'; execute ( f'UPDATE rose_settings SET {col}=? WHERE chat_id=?', ( txt,chat.id )  ) ; await msg.reply_text ( '✅ Matn saqlandi.' ) ; return True
    if cmd=='modlog':
        rows=all_ ( 'SELECT * FROM moderation_log WHERE chat_id=? ORDER BY id DESC LIMIT 15', ( chat.id, ) )
        if not rows: await msg.reply_text ( '📋 Moderatsiya logi bo‘sh.' ) ; return True
        lines=['📋 SO‘NGGI MODERATSIYA']
        for r in rows: lines.append ( f"• {r['action']} | {r['target_id']} | {r['reason'] or 'sababsiz'}")
        await msg.reply_text ( '\n'.join ( lines )  ) ; return True
    if cmd in {'tempmute','tempban'}:
        t=msg.reply_to_message
        if not t or not t.from_user: await msg.reply_text ( f'↩️ Foydalanuvchiga reply qilib *{cmd} 10m [sabab]' ) ; return True
        if not args: await msg.reply_text ( '⏱ Vaqt kiriting: 10m, 2h, 1d' ) ; return True
        sec=parse_duration ( args[0] ) ; reason=' '.join ( args[1:]) or 'Sabab ko‘rsatilmagan'
        if sec<=0: await msg.reply_text ( '❌ Vaqt formati noto‘g‘ri.' ) ; return True
        until=now (  ) +sec
        try:
            if cmd=='tempmute': await ctx.bot.restrict_chat_member ( chat.id,t.from_user.id,ChatPermissions ( can_send_messages=False ) ,until_date=datetime.fromtimestamp ( until,timezone.utc ) )
            else: await ctx.bot.ban_chat_member ( chat.id,t.from_user.id,until_date=datetime.fromtimestamp ( until,timezone.utc ) )
            execute ( 'INSERT OR REPLACE INTO temp_moderation VALUES ( ?,?,?,? ) ', ( chat.id,t.from_user.id,cmd,until ) )
            execute ( 'INSERT INTO moderation_log ( chat_id,actor_id,target_id,action,reason,duration,created_at) VALUES ( ?,?,?,?,?,?,? ) ', ( chat.id,actor.id,t.from_user.id,cmd,reason,sec,now (  )  ) )
            await msg.reply_text ( f"✅ {t.from_user.first_name}: {cmd} — {args[0]}\n📝 {reason}")
        except TelegramError as e: await msg.reply_text ( f'❌ Amal bajarilmadi: {e}')
        return True
    return False

_original_star_text_router=star_text_router
async def star_text_router ( update,ctx ) :
    msg=update.effective_message
    if msg and msg.text and msg.text.startswith ( '*' ) :
        parts=msg.text[1:].strip (  ) .split (  ) ; cmd=parts[0].lower ( ) if parts else ''; args=parts[1:]
        if await rose_advanced_command ( update,ctx,cmd,args ) : return
    return await _original_star_text_router ( update,ctx)

_original_passive=passive
async def passive ( update,ctx ) :
    msg=update.effective_message; chat=update.effective_chat; u=update.effective_user
    if msg and chat and u and not u.is_bot and chat.type in ('group','supergroup' ) :
        ensure_group ( chat ) ; rr=rose_row ( chat.id)
        if not await protected ( ctx.bot,chat.id,u.id) and not one ( 'SELECT 1 FROM approved WHERE chat_id=? AND user_id=?', ( chat.id,u.id )  ) :
            kind=rose_content_kind ( msg)
            if kind and rr[f'lock_{kind}']:
                await rose_delete ( msg ) ; return
            txt= ( msg.text or msg.caption or '' ) .strip (  ) .lower ( )
            if rr['anti_repeat'] and txt:
                key= ( chat.id,u.id,txt[:500] ) ; ts=now (  ) ; arr=[x for x in ROSE_REPEAT_CACHE.get ( key,[]) if ts-x<=rr['repeat_window']]; arr.append ( ts ) ; ROSE_REPEAT_CACHE[key]=arr
                if len ( arr ) >=rr['repeat_limit']:
                    await rose_delete ( msg)
                    try: await ctx.bot.restrict_chat_member ( chat.id,u.id,ChatPermissions ( can_send_messages=False ) ,until_date=datetime.now ( timezone.utc ) +timedelta ( minutes=2 )  ) ; await ctx.bot.send_message ( chat.id,f'🔁 {u.first_name}: takroriy spam sabab 2 daqiqa mute.')
                    except TelegramError: pass
                    ROSE_REPEAT_CACHE[key]=[]; return
    return await _original_passive ( update,ctx)

_original_new_members=new_members
async def new_members ( update,ctx ) :
    chat=update.effective_chat; msg=update.effective_message
    if chat and chat.type in ('group','supergroup' ) :
        rr=rose_row ( chat.id ) ; ts=now (  ) ; arr=[x for x in ROSE_JOIN_CACHE.get ( chat.id,[]) if ts-x<=rr['raid_window']]
        arr += [ts]*len ( msg.new_chat_members or [] ) ; ROSE_JOIN_CACHE[chat.id]=arr
        if rr['anti_raid'] and len ( arr ) >=rr['raid_join_limit']:
            for nu in msg.new_chat_members or []:
                if not nu.is_bot:
                    try: await ctx.bot.restrict_chat_member ( chat.id,nu.id,ChatPermissions ( can_send_messages=False ) ,until_date=datetime.now ( timezone.utc ) +timedelta ( seconds=rr['raid_mute_seconds'] ) )
                    except TelegramError: pass
            try: await ctx.bot.send_message ( chat.id,'🚨 Anti-raid ishga tushdi. Yangi a’zolar vaqtincha cheklab qo‘yildi.')
            except TelegramError: pass
        custom=rr['welcome_text']
        if custom:
            names=', '.join ( x.first_name for x in msg.new_chat_members or [])
            txt=custom.replace ( '{first}',names ) .replace ( '{chatname}',chat.title or '')
            try: await msg.reply_text ( txt)
            except TelegramError: pass
            st=moderation_settings ( chat.id)
            if st and st['clean_service']:
                try: await msg.delete ( )
                except TelegramError: pass
            return
    return await _original_new_members ( update,ctx)

_original_left_member=left_member
async def left_member ( update,ctx ) :
    chat=update.effective_chat; msg=update.effective_message
    if chat and chat.type in ('group','supergroup' ) :
        rr=rose_row ( chat.id ) ; custom=rr['goodbye_text']; lu=msg.left_chat_member
        if custom and lu:
            txt=custom.replace ( '{first}',lu.first_name or '' ) .replace ( '{chatname}',chat.title or '')
            try: await msg.reply_text ( txt)
            except TelegramError: pass
            st=moderation_settings ( chat.id)
            if st and st['clean_service']:
                try: await msg.delete ( )
                except TelegramError: pass
            return
    return await _original_left_member ( update,ctx)

async def owner_message_state_handler ( update,ctx ) :
    msg=update.effective_message; u=update.effective_user; chat=update.effective_chat
    if not msg or not u or not chat or chat.type!="private": return
    st=STATE.get ( u.id) or {}; mode=st.get ( "mode")
    if mode not in {"owner_message","owner_reply"}: return
    ctx.user_data["owner_consumed_message_id"]=msg.message_id

    if mode=="owner_message":
        ensure_user ( u)
        with db ( ) as c:
            cur=c.execute ( "INSERT INTO owner_messages ( user_id,username,first_name,status,created_at) VALUES ( ?,?,?,?,? ) ",
                          (u.id,u.username or '',u.first_name or '',"new",now (  )  ) )
            tid=cur.lastrowid
            c.execute ( "INSERT INTO owner_message_events ( ticket_id,sender_id,kind,created_at) VALUES ( ?,?,?,? ) ", ( tid,u.id,"user_message",now (  )  ) )
        STATE.pop ( u.id,None)
        header= ( f"📨 YANGI MUROJAAT #{tid}\\n━━━━━━━━━━━━━━━━━━\\n"
                f"👤 {u.full_name}\\n🆔 {u.id}\\n🔗 @{u.username}" if u.username else
                f"📨 YANGI MUROJAAT #{tid}\\n━━━━━━━━━━━━━━━━━━\\n👤 {u.full_name}\\n🆔 {u.id}")
        kb=InlineKeyboardMarkup ( [
            [InlineKeyboardButton ( "✉️ Javob berish",callback_data=f"ownerreply:{tid}" ) ],
            [InlineKeyboardButton ( "✅ Ko‘rildi",callback_data=f"ownerseen:{tid}" ) ,InlineKeyboardButton ( "🗑 Yopish",callback_data=f"ownerclose:{tid}" ) ]
        ])
        delivered=0
        for oid in SUPER_OWNERS:
            try:
                await ctx.bot.send_message ( oid,header,reply_markup=kb)
                await msg.copy ( chat_id=oid)
                delivered+=1
            except TelegramError:
                pass
        if delivered:
            return await msg.reply_text ( f"✅ Xabaringiz egalariga yuborildi.\\n📨 Murojaat raqami: #{tid}",reply_markup=main_menu_markup ( u.id ) )
        return await msg.reply_text ( "⚠️ Xabar saqlandi, lekin egaga Telegram orqali yetkazib bo‘lmadi. Ega botga /start bosganini tekshiring.",reply_markup=main_menu_markup ( u.id ) )

    tid=int ( st.get ( "ticket_id",0 )  ) ; target=int ( st.get ( "target_id",0 ) )
    if u.id not in SUPER_OWNERS or not tid or not target:
        STATE.pop ( u.id,None ) ; return
    try:
        await ctx.bot.send_message ( target,f"✉️ EGADAN JAVOB — murojaat #{tid}")
        await msg.copy ( chat_id=target)
        execute ( "UPDATE owner_messages SET status='answered',handled_by=? WHERE id=?", ( u.id,tid ) )
        execute ( "INSERT INTO owner_message_events ( ticket_id,sender_id,kind,created_at) VALUES ( ?,?,?,? ) ", ( tid,u.id,"owner_reply",now (  )  ) )
        STATE.pop ( u.id,None)
        return await msg.reply_text ( f"✅ Javob #{tid} murojaat egasiga yuborildi.")
    except TelegramError as e:
        return await msg.reply_text ( f"❌ Javob yuborilmadi: {e}")

async def rose_cleanup_job ( ctx ) :
    rows=all_ ( 'SELECT * FROM temp_moderation WHERE until_ts<=?', ( now (  ) , ) )
    for r in rows:
        try:
            if r['kind']=='tempmute': await ctx.bot.restrict_chat_member ( r['chat_id'],r['user_id'],ChatPermissions ( can_send_messages=True,can_send_audios=True,can_send_documents=True,can_send_photos=True,can_send_videos=True,can_send_video_notes=True,can_send_voice_notes=True,can_send_polls=True,can_send_other_messages=True,can_add_web_page_previews=True,can_invite_users=True ) )
            elif r['kind']=='tempban': await ctx.bot.unban_chat_member ( r['chat_id'],r['user_id'],only_if_banned=True)
        except TelegramError: pass
        execute ( 'DELETE FROM temp_moderation WHERE chat_id=? AND user_id=? AND kind=?', ( r['chat_id'],r['user_id'],r['kind'] ) )

def main (  ) :
    if not TOKEN: raise RuntimeError ( "BOT_TOKEN kiritilmagan.")
    init_db ( )
    rose_full_init_db ( )
    v9_init_db ( )
    app=Application.builder (  ) .token ( TOKEN ) .build ( )
    app.add_handler ( CommandHandler ( "start",v9_start_selector ) )
    app.add_handler ( CommandHandler ( "help",cmd_help ) )
    app.add_handler ( CommandHandler ( "id",cmd_id ) )
    app.add_handler ( CommandHandler ( "super",cmd_super ) )
    app.add_handler ( PreCheckoutQueryHandler ( precheckout ) )
    app.add_handler ( MessageHandler ( filters.SUCCESSFUL_PAYMENT,paid ) )
    app.add_handler ( CallbackQueryHandler ( callback ) )
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
    app.add_handler ( MessageHandler ( filters.ChatType.PRIVATE & (filters.PHOTO | filters.Document.IMAGE ) ,private_ai_media_reply ) ,group=2)
    # Group passive processing is separate.
    app.add_handler ( MessageHandler ( filters.ALL & ~filters.StatusUpdate.ALL & ~filters.SUCCESSFUL_PAYMENT,passive ) ,group=3)
    # Plain private text AI comes last.
    app.add_handler ( MessageHandler ( filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND & ~filters.Regex ( r"^\*" ) ,private_ai_reply ) ,group=4)
    if app.job_queue:
        app.job_queue.run_repeating ( giveaway_job,60,first=10)
        app.job_queue.run_repeating ( rose_cleanup_job,30,first=15)
    app.add_error_handler ( error_handler)
    log.info ( "VERITAS v8 starting")
    app.run_polling ( allowed_updates=Update.ALL_TYPES)

if __name__=="__main__":
    main ( )
