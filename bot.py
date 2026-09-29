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

import os, re, sqlite3, time, random, logging, json, asyncio, base64
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
    Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions,
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
TG_API_ID = int ( os.getenv ( "TG_API_ID", "0") or 0)
TG_API_HASH = os.getenv ( "TG_API_HASH", "" ) .strip ( )
TG_SESSION = os.getenv ( "TG_SESSION", "" ) .strip ( )
TG_STORAGE_CHAT_ID = int ( os.getenv ( "TG_STORAGE_CHAT_ID", "0") or 0)
DEMO_DAYS = 7
WEEK_PRICE = 100
PREMIUM = {3:1000, 6:1500, 12:2500}
TOPUPS = (25,50,100,250,500,1000,2500)
AI_PRIVATE_PRICE = 100
AI_PRIVATE_DAYS = 30
AI_GROUP_PLANS = {7:250, 30:500}
AI_RATE_CACHE = {}
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
    CREATE TABLE IF NOT EXISTS approved ( chat_id INTEGER,user_id INTEGER,PRIMARY KEY ( chat_id,user_id )  ) ;
    CREATE TABLE IF NOT EXISTS warns ( chat_id INTEGER,user_id INTEGER,count INTEGER DEFAULT 0,PRIMARY KEY ( chat_id,user_id )  ) ;
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
    with db ( ) as c: c.executescript ( schema)

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

async def is_tg_admin ( bot,chat_id,uid ) :
    try:
        m=await bot.get_chat_member ( chat_id,uid)
        return m.status in (ChatMemberStatus.OWNER,ChatMemberStatus.ADMINISTRATOR)
    except TelegramError: return False
async def can_manage ( bot,chat_id,uid ) :
    if uid in SUPER_OWNERS: return True
    if await is_tg_admin ( bot,chat_id,uid ) : return True
    return bool ( one ( "SELECT 1 FROM vadmins WHERE chat_id=? AND user_id=?", ( chat_id,uid )  ) )
async def protected ( bot,chat_id,uid ) :
    return uid in SUPER_OWNERS or await is_tg_admin ( bot,chat_id,uid)
def replied ( update ) : return update.effective_message.reply_to_message if update.effective_message else None

def level ( xp ) : return max ( 1, int (  ( xp/20 ) **0.5 ) +1)
def title_for ( uid,custom="" ) :
    if uid in SUPER_OWNERS: return "👑 Super Ega"
    return custom or "A’zo"

def main_menu_markup ( uid ) :
    kb=[
      [InlineKeyboardButton ( "👤 Profil",callback_data="me" ) ,InlineKeyboardButton ( "⭐ Hisob",callback_data="wallet" ) ],
      [InlineKeyboardButton ( "🎁 Gift",callback_data="gifts" ) ,InlineKeyboardButton ( "💎 Premium",callback_data="premium" ) ],
      [InlineKeyboardButton ( "🏘 Guruhlarim",callback_data="mygroups" ) ],
      [InlineKeyboardButton ( "🤖 Veritas AI",callback_data="ai_private" ) ],
      [InlineKeyboardButton ( "📚 Vasatiya kutubxonasi",callback_data="library" ) ,InlineKeyboardButton ( "📜 Sahih Hadislar",callback_data="hadith" ) ],
      [InlineKeyboardButton ( "ℹ️ Veritas haqida",callback_data="about" ) ],
    ]
    if uid in SUPER_OWNERS:
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
    r=one ( "SELECT COALESCE ( SUM ( xp ) ,0) xp,COALESCE ( SUM ( messages ) ,0) messages FROM members WHERE user_id=?", ( uid, ) )
    return (int ( r["xp"] ) ,int ( r["messages"] ) ) if r else (0,0)

def fmt_until ( ts ) :
    if not ts: return "—"
    return datetime.fromtimestamp ( int ( ts ),timezone.utc ) .strftime ( "%d.%m.%Y %H:%M UTC" )

def ai_user_until ( uid ) :
    r=one ( "SELECT paid_until FROM ai_user_subscriptions WHERE user_id=?", ( uid, ) )
    return int ( r["paid_until"] ) if r else 0

def ai_user_active ( uid ) :
    return uid in SUPER_OWNERS or ai_user_until ( uid ) > now ( )

def ai_group_until ( chat_id ) :
    r=one ( "SELECT paid_until FROM ai_group_subscriptions WHERE chat_id=?", ( chat_id, ) )
    return int ( r["paid_until"] ) if r else 0

def ai_group_active ( chat_id ) :
    return ai_group_until ( chat_id ) > now ( )

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
    kb=[
      [InlineKeyboardButton ( "⭐ 250 — 7 kun",callback_data=f"aigbuy:{chat_id}:7" ) ,InlineKeyboardButton ( "⭐ 500 — 30 kun",callback_data=f"aigbuy:{chat_id}:30" ) ]
    ]
    if uid in SUPER_OWNERS:
        kb += [
          [InlineKeyboardButton ( "👑 Bepul 1 kun",callback_data=f"aigfree:{chat_id}:1" ) ,InlineKeyboardButton ( "👑 7 kun",callback_data=f"aigfree:{chat_id}:7" ) ,InlineKeyboardButton ( "👑 30 kun",callback_data=f"aigfree:{chat_id}:30" ) ],
          [InlineKeyboardButton ( "⛔ AI ni o‘chirish",callback_data=f"aigoff:{chat_id}" ) ]
        ]
    return InlineKeyboardMarkup ( kb )


def is_library_admin ( uid ) :
    return uid in SUPER_OWNERS or bool ( one ( "SELECT 1 FROM library_admins WHERE user_id=?", ( uid, )  ) )

def lib_lang_name ( code ) :
    return {"uz":"🇺🇿 O‘zbekcha","ru":"🇷🇺 Русский","en":"🇬🇧 English"}.get ( code,code)

def library_home_markup ( uid ) :
    kb=[
      [InlineKeyboardButton ( "🔎 Qidirish",callback_data="libsearch" ) ,InlineKeyboardButton ( "🗂 Kategoriyalar",callback_data="libcats:0" ) ],
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
    r=one ( "SELECT pdf_file_id,audio_file_id FROM library_books WHERE id=?", ( book_id, ) )
    kb=[]
    row=[]
    if r and r["pdf_file_id"]: row.append ( InlineKeyboardButton ( "📄 PDF",callback_data=f"libpdf:{book_id}" ) )
    if r and r["audio_file_id"]: row.append ( InlineKeyboardButton ( "🎧 Audio",callback_data=f"libaudio:{book_id}" ) )
    if row: kb.append ( row)
    if r and r["pdf_file_id"]:
        kb.append ( [InlineKeyboardButton ( "🧠 Test tuzish",callback_data=f"libquiz:{book_id}" ) ])
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

async def library_private_input ( update,ctx ) :
    if update.effective_chat.type!="private": return
    uid=update.effective_user.id; st=STATE.get ( uid)
    if st: ctx.user_data["workflow_message_id"]=update.effective_message.message_id
    if st and str ( st.get ( "mode","" )  ) .startswith ( "had_" ) :
        return await hadith_private_input ( update,ctx)
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
            if not msg.document: return await msg.reply_text ( "📄 Yangi PDFni Document sifatida yuboring." )
            doc=msg.document; name= ( doc.file_name or "" ) .lower ( ); mime= ( doc.mime_type or "" ) .lower ( )
            if not (name.endswith ( ".pdf" ) or mime=="application/pdf" ) : return await msg.reply_text ( "❌ Bu PDF emas." )
            uniq=doc.file_unique_id or ""
            dup=one ( "SELECT id FROM library_books WHERE pdf_unique_id=? AND id<>? AND status<>'deleted'", ( uniq,bid ) ) if uniq else None
            if dup: return await msg.reply_text ( f"⚠️ Bu PDF boshqa kitobda mavjud. ID: {dup['id']}" )
            execute ( "UPDATE library_books SET pdf_file_id=?,pdf_unique_id=? WHERE id=?", ( doc.file_id,uniq,bid ) )
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
    return uid in SUPER_OWNERS or bool ( one ( "SELECT 1 FROM hadith_admins WHERE user_id=?", ( uid, )  ) )

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
    if uid not in SUPER_OWNERS: return await msg.reply_text ( "⛔ Bu buyruq faqat Super Ega uchun.")
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
    if uid not in SUPER_OWNERS:
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
    if uid not in SUPER_OWNERS:
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
    kb=InlineKeyboardMarkup ( [
        [InlineKeyboardButton ( "📚 Vasatiya",callback_data="help:library" ) ,InlineKeyboardButton ( "📜 Hadislar",callback_data="help:hadith" ) ],
        [InlineKeyboardButton ( "🛡 Adminlar",callback_data="help:admins" ) ,InlineKeyboardButton ( "👥 Moderatsiya",callback_data="help:moderation" ) ],
        [InlineKeyboardButton ( "🔐 Himoya",callback_data="help:security" ) ,InlineKeyboardButton ( "💬 Filter / Notes",callback_data="help:filters" ) ],
        [InlineKeyboardButton ( "⚙️ Guruh sozlamalari",callback_data="help:settings" ) ],
        [InlineKeyboardButton ( "⭐ Stars / Gift",callback_data="help:stars" ) ,InlineKeyboardButton ( "🎉 Giveaway",callback_data="help:giveaway" ) ],
        [InlineKeyboardButton ( "📢 Xabarnoma",callback_data="help:broadcast" ) ,InlineKeyboardButton ( "📌 Asosiy",callback_data="help:main" ) ],
        [InlineKeyboardButton ( "🏠 Bosh menyu",callback_data="home" ) ]
    ] )
    await update.effective_message.reply_text ( "❓ VERITAS YORDAM MARKAZI\n\nKerakli bo‘limni tanlang:",reply_markup=kb )

def help_menu_markup (  ) :
    return InlineKeyboardMarkup ( [[InlineKeyboardButton ( "⬅️ Yordam bo‘limlari",callback_data="help:home" ) ,InlineKeyboardButton ( "🏠 Bosh menyu",callback_data="home" ) ]] )

def help_text ( section ) :
    data={
      "main":"📌 ASOSIY\n\n*help — yordam markazi\n*id — Telegram ID va chat ID\n*men — profil va faollik\n*aktiv — faol a’zolar\n*top 10 — Super Ega TOP paneli\n*rules — guruh qoidalari\n*admins — adminlar\n*unvon <nom> / *unvonoff — unvon boshqaruvi",
      "library":"📚 VASATIYA KUTUBXONASI\n\nMenyudan kitob qidirish, kategoriya, yangi kitoblar va sevimlilar ishlaydi.\n\n*ad.book — replydagi odamga kutubxona adminligi\n*unad.book — huquqni olish\n*bookadmins — kutubxona adminlari\n\nKitob admini kitob qo‘shishi, ✏️ Tahrirlash orqali nom, muallif, til, kategoriya, tavsif, muqova, PDF va audioni yangilashi mumkin.",
      "hadith":"📜 SAHIH HADISLAR\n\n*hadis — random hadis\n*hadis buxoriy 1 — aniq hadis\n*add.hadis — private chatda hadis qo‘shish\n*del.hadis buxoriy 1 — o‘chirish\n*ad.hadis / *unad.hadis — hadis admini huquqi\n*hadisadmins — hadis adminlari\n\nMavjud hadis topilsa uni ✏️ Tahrirlash mumkin.",
      "admins":"🛡 ADMINLAR\n\n*ruxsat / *ruxsatsiz — Veritas admini\n*admin / *unadmin — Telegram admini\n*approve / *unapprove / *approved — himoyalangan a’zolar\n*ad.book / *unad.book — kutubxona admini\n*ad.hadis / *unad.hadis — hadis admini",
      "moderation":"👥 MODERATSIYA\n\nReply orqali: *warn, *unwarn, *warns, *clearwarns, *mute, *unmute, *kick, *ban, *unban, *del",
      "security":"🔐 HIMOYA\n\n*links on/off\n*blacklist <so‘z> / *unblacklist <so‘z> / *blacklists\n*lock <turi> / *unlock <turi> / *locks\n*antiflood on/off\n*flood 5\n*report / *reports on/off",
      "filters":"💬 FILTER VA NOTES\n\n*filter <kalit> <javob> / *filters / *stop <kalit> / *stopall\n*save <nom> <matn> / *get <nom> / *notes / *clear <nom>",
      "settings":"⚙️ GURUH SOZLAMALARI\n\n*welcome on/off\n*goodbye on/off\n*setrules <matn>",
      "stars":"⭐ STARS / SOVG‘A\n\n*topup 100 — kabinet krediti\n*stars 100 — Telegram Stars Gift oynasi (Super Ega ) \n*give <narx> — real Gift\n*premium 3/6/12 — Premium sovg‘asi",
      "giveaway":"🎉 GIVEAWAY\n\n*giveaway gift <narx> <daq> <g‘oliblar> — konkurs ochish\n*join — konkursga qo‘shilish",
      "broadcast":"📢 XABARNOMA\n\n*post <matn> — barcha foydalanuvchi va guruhlarga matn\n*post — xabar/postga reply qilinsa o‘sha xabarni hammaga nusxalaydi\n\nFaqat Super Ega uchun."
    }
    return data.get ( section,"Bo‘lim topilmadi." )

async def cmd_super ( update,ctx ) :
    ensure_user ( update.effective_user)
    if update.effective_user.id not in SUPER_OWNERS:
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
    if chat.type in ("group","supergroup" ) :
        ensure_group ( chat)
        r=one ( "SELECT * FROM members WHERE chat_id=? AND user_id=?", ( chat.id,u.id ) )
        xp=int ( r["xp"]) if r else 0; msgs=int ( r["messages"]) if r else 0; custom=r["title"] if r else ""
        rank=one ( """SELECT 1+COUNT ( *) n FROM members WHERE chat_id=? AND messages>
                   COALESCE (  ( SELECT messages FROM members WHERE chat_id=? AND user_id=? ) ,0 ) """, ( chat.id,chat.id,u.id )  ) ["n"]
        txt=f"👤 {u.full_name}\n🆔 {u.id}\n🎖 {title_for ( u.id,custom ) }\n⭐ Kredit: {wallet ( u.id ) }\n📈 Level: {level ( xp ) } | XP: {xp}\n💬 Xabarlar: {msgs}\n🏆 Reyting: #{rank}"
    else:
        ai_until=ai_user_until ( u.id )
        ai_status=( "👑 Cheksiz (Super Ega ) " if u.id in SUPER_OWNERS else ( "✅ FAOL — "+fmt_until ( ai_until ) if ai_until>now ( ) else "❌ YO‘Q" ) )
        txt=f"👤 {u.full_name}\n🆔 {u.id}\n🎖 {title_for ( u.id ) }\n⭐ Kredit: {wallet ( u.id ) }\n🤖 AI Premium: {ai_status}"
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
    if update.effective_user.id not in SUPER_OWNERS:
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
            execute ( """INSERT INTO warns ( chat_id,user_id,count) VALUES ( ?,?,1)
            ON CONFLICT ( chat_id,user_id) DO UPDATE SET count=count+1""", ( chat.id,tu.id ) )
            n=one ( "SELECT count FROM warns WHERE chat_id=? AND user_id=?", ( chat.id,tu.id )  ) ["count"]
            if n>=3:
                await ctx.bot.ban_chat_member ( chat.id,tu.id ) ; execute ( "DELETE FROM warns WHERE chat_id=? AND user_id=?", ( chat.id,tu.id ) )
                return await msg.reply_text ( f"🚫 {tu.full_name}: 3 warn → ban.")
            return await msg.reply_text ( f"⚠️ {tu.full_name}: {n}/3 warn.")
        if cmd=="unwarn":
            execute ( "UPDATE warns SET count=MAX ( count-1,0) WHERE chat_id=? AND user_id=?", ( chat.id,tu.id ) )
        elif cmd=="clearwarns": execute ( "DELETE FROM warns WHERE chat_id=? AND user_id=?", ( chat.id,tu.id ) )
        elif cmd=="mute":
            await ctx.bot.restrict_chat_member ( chat.id,tu.id,ChatPermissions ( can_send_messages=False ) )
        elif cmd=="unmute":
            await ctx.bot.restrict_chat_member ( chat.id,tu.id,ChatPermissions ( can_send_messages=True,can_send_audios=True,can_send_documents=True,can_send_photos=True,can_send_videos=True,can_send_video_notes=True,can_send_voice_notes=True,can_send_polls=True,can_send_other_messages=True,can_add_web_page_previews=True,can_invite_users=True ) )
        elif cmd=="kick":
            await ctx.bot.ban_chat_member ( chat.id,tu.id ) ; await ctx.bot.unban_chat_member ( chat.id,tu.id)
        elif cmd=="ban": await ctx.bot.ban_chat_member ( chat.id,tu.id)
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
        rows=all_ ( """SELECT m.user_id,m.messages,m.title,m.xp,u.first_name,u.username
                     FROM members m LEFT JOIN users u ON u.user_id=m.user_id
                     WHERE m.chat_id=? ORDER BY m.messages DESC LIMIT ?""", ( chat.id,n ) )
        return await msg.reply_text ( "🏆 Faollik\n"+ ( "\n".join(
            f"{i+1}. {display_name_row ( r ) } — {r['messages']} | Lv.{level ( r['xp'] ) } {title_for ( r['user_id'],r['title'] ) }"
            for i,r in enumerate ( rows ) ) or "Ma’lumot yo‘q" ) )

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
    if not wallet_change ( sender,-cost,"gift_pending",target,meta={"gift_id":str ( g.id ) } ) : return
    try:
        await ctx.bot.send_gift ( user_id=target,gift_id=g.id,text=f"🎁 Veritas orqali {update.effective_user.first_name}dan sovg‘a")
        execute ( "UPDATE tx SET kind='gift' WHERE id= ( SELECT MAX ( id) FROM tx WHERE user_id=? ) ", ( sender, ) )
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
    if not wallet_change ( sender,-cost,"premium_pending",target ) : return
    try:
        await ctx.bot.gift_premium_subscription ( user_id=target,month_count=m,star_count=cost,text="💎 Veritas orqali Premium sovg‘a")
        execute ( "UPDATE tx SET kind='premium' WHERE id= ( SELECT MAX ( id) FROM tx WHERE user_id=? ) ", ( sender, ) )
        await update.effective_message.reply_text ( f"✅ {m} oylik Telegram Premium yuborildi.")
    except Exception as e:
        wallet_change ( sender,cost,"premium_rollback",target)
        await update.effective_message.reply_text ( f"❌ Premium yuborilmadi, kredit qaytarildi.\n{e}")

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
    if cmd in {"ad.book","unad.book","bookadmins","ad.hadis","unad.hadis","hadisadmins"}:
        return await content_admin_command ( update,ctx,cmd)
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
        return await msg.reply_text ( f"🤖 VERITAS AI — GURUH\n\n{status}\n\n250 ⭐ — 7 kun\n500 ⭐ — 30 kun",reply_markup=ai_group_menu ( update.effective_chat.id,update.effective_user.id ) )
    if update.effective_chat.type not in ("group","supergroup" ) :
        return await msg.reply_text ( "Bu buyruq guruh uchun.")
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
            "Veritas — Telegram uchun guruh boshqaruvi va AI yordamchi bot. Shaxsiy Veritas AI Premium 100 Stars va 30 kun ishlaydi. "
            "Guruh Veritas AI obunasi 250 Stars/7 kun yoki 500 Stars/30 kun. Super Ega guruh AI sini bepul 1, 7 yoki 30 kunga yoqa oladi. "
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
        kb=InlineKeyboardMarkup ( [[InlineKeyboardButton ( "💎 100 ⭐ — 30 kun",callback_data="aipbuy" ) ],
                                 [InlineKeyboardButton ( "⭐ Hisobni to‘ldirish",callback_data="wallet" ) ]])
        return await msg.reply_text ( "🔒 Rasmni Veritas AI bilan tahlil qilish AI Premium uchun.\n\n💎 100 ⭐ — 30 kun",reply_markup=kb)
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
        if uid in SUPER_OWNERS:
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
    if u.id not in SUPER_OWNERS and not await is_tg_admin ( ctx.bot,chat_id,u.id ) :
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


async def group_ai_reply ( update,ctx ) :
    msg=update.effective_message; chat=update.effective_chat; u=update.effective_user
    if not msg or not u or chat.type not in ("group","supergroup") : return False
    if u.is_bot or not msg.reply_to_message or not msg.text: return False
    replied_msg=msg.reply_to_message
    if not replied_msg.from_user or replied_msg.from_user.id!=ctx.bot.id: return False
    question=msg.text.strip ( )
    if not question or question.startswith ( "*" ) : return False
    if not ai_group_active ( chat.id ) :
        await msg.reply_text ( "🔒 Bu guruhda Veritas AI obunasi faol emas.\n\n*ai yozib tariflarni oching: 250 ⭐ / 7 kun yoki 500 ⭐ / 30 kun." )
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
        prompt= ( f"Oldingi Veritas xabari:\n{previous[:2500]}\n\n" if previous else "") + f"Foydalanuvchi savoli:\n{question[:4000]}"
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
    msg=update.effective_message; u=update.effective_user; chat=update.effective_chat
    if not msg or not u or chat.type!="private" or u.is_bot or not msg.text: return
    text=msg.text.strip ( )
    if not text or text.startswith ( "*" ) or text.startswith ( "/" ): return
    if STATE.get ( u.id ): return
    if ctx.user_data.get ( "workflow_message_id" )==msg.message_id: return
    ensure_user ( u )
    if not ai_user_active ( u.id ) :
        kb=InlineKeyboardMarkup ( [[InlineKeyboardButton ( "💎 100 ⭐ — 30 kun",callback_data="aipbuy" ) ],[InlineKeyboardButton ( "⭐ Hisobni to‘ldirish",callback_data="wallet" ) ]] )
        return await msg.reply_text ( "🔒 Shaxsiy Veritas AI faqat AI Premium a’zolar uchun.\n\n💎 100 ⭐ — 30 kun",reply_markup=kb )
    if not ai_rate_ok ( "private",u.id,4 ) : return await msg.reply_text ( "⏳ 4 soniyadan keyin yana yozing." )
    if not OPENAI_API_KEY: return await msg.reply_text ( "⚠️ Veritas AI kaliti sozlanmagan." )
    try:
        await ctx.bot.send_chat_action ( chat.id,"typing" )
        previous=""
        if msg.reply_to_message and msg.reply_to_message.from_user and msg.reply_to_message.from_user.id==ctx.bot.id:
            previous= ( msg.reply_to_message.text or msg.reply_to_message.caption or "" ) [:2500]
        prompt= ( f"Oldingi Veritas javobi:\n{previous}\n\n" if previous else "" ) +f"Foydalanuvchi:\n{text[:4000]}"
        answer=await asyncio.to_thread ( _openai_response_sync,prompt )
        if not answer: answer="Hozir javob hosil bo‘lmadi. Qayta urinib ko‘ring."
        for i in range ( 0,len ( answer ),4000 ): await msg.reply_text ( answer[i:i+4000] )
    except Exception:
        log.exception ( "Private Veritas AI error" )
        await msg.reply_text ( "⚠️ Veritas AI hozir javob bera olmadi." )

async def passive ( update,ctx ) :
    msg=update.effective_message; u=update.effective_user; chat=update.effective_chat
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
    g=one ( "SELECT welcome FROM groups WHERE chat_id=?", ( update.effective_chat.id, ) )
    if g and g["welcome"]:
        names=", ".join ( u.first_name for u in update.effective_message.new_chat_members)
        await update.effective_message.reply_text ( f"👋 Xush kelibsiz, {names}!")

async def left_member ( update,ctx ) :
    g=one ( "SELECT goodbye FROM groups WHERE chat_id=?", ( update.effective_chat.id, ) )
    if g and g["goodbye"] and update.effective_message.left_chat_member:
        await update.effective_message.reply_text ( f"👋 {update.effective_message.left_chat_member.first_name} guruhni tark etdi.")

async def callback ( update,ctx ) :
    q=update.callback_query; d=q.data; u=q.from_user; ensure_user ( u)
    await q.answer ( )

    if d=="help:home":
        kb=InlineKeyboardMarkup ( [
            [InlineKeyboardButton ( "📚 Vasatiya",callback_data="help:library" ) ,InlineKeyboardButton ( "📜 Hadislar",callback_data="help:hadith" ) ],
            [InlineKeyboardButton ( "🛡 Adminlar",callback_data="help:admins" ) ,InlineKeyboardButton ( "👥 Moderatsiya",callback_data="help:moderation" ) ],
            [InlineKeyboardButton ( "🔐 Himoya",callback_data="help:security" ) ,InlineKeyboardButton ( "💬 Filter / Notes",callback_data="help:filters" ) ],
            [InlineKeyboardButton ( "⚙️ Guruh sozlamalari",callback_data="help:settings" ) ],
            [InlineKeyboardButton ( "⭐ Stars / Gift",callback_data="help:stars" ) ,InlineKeyboardButton ( "🎉 Giveaway",callback_data="help:giveaway" ) ],
            [InlineKeyboardButton ( "📢 Xabarnoma",callback_data="help:broadcast" ) ,InlineKeyboardButton ( "📌 Asosiy",callback_data="help:main" ) ],
            [InlineKeyboardButton ( "🏠 Bosh menyu",callback_data="home" ) ]
        ] )
        return await q.edit_message_text ( "❓ VERITAS YORDAM MARKAZI\n\nKerakli bo‘limni tanlang:",reply_markup=kb )

    if d.startswith ( "help:" ) :
        return await q.edit_message_text ( help_text ( d.split ( ":",1 )[1] ),reply_markup=help_menu_markup ( ) )

    if d=="home":
        try:
            if q.message.photo or q.message.video or q.message.document or q.message.audio or q.message.animation:
                await q.message.delete ( )
                return await ctx.bot.send_message ( q.message.chat.id,"🪶 VERITAS v8\n\nShaxsiy kabinet",reply_markup=main_menu_markup ( u.id ) )
            return await q.edit_message_text ( "🪶 VERITAS v8\n\nShaxsiy kabinet",reply_markup=main_menu_markup ( u.id ) )
        except TelegramError:
            return await ctx.bot.send_message ( q.message.chat.id,"🪶 VERITAS v8\n\nShaxsiy kabinet",reply_markup=main_menu_markup ( u.id ) )

    if d.startswith ( "topgift:") or d.startswith ( "topplain:" ) :
        if u.id not in SUPER_OWNERS: return
        chat_id=int ( d.split ( ":",1 ) [1] ) ; with_gifts=d.startswith ( "topgift:")
        await q.edit_message_text ( "⏳ TOP-10 hisoblanmoqda..." if not with_gifts else "⏳ TOP-10 va TOP-3 Giftlar tayyorlanmoqda...")
        return await top10_result ( ctx.bot,chat_id,with_gifts,u.id)

    if d=="me":
        xp,msgs=user_total_stats ( u.id)
        r=one ( "SELECT wallet FROM users WHERE user_id=?", ( u.id, ) )
        ai_until=ai_user_until ( u.id )
        ai_status=( "👑 Cheksiz (Super Ega ) " if u.id in SUPER_OWNERS else ( "✅ FAOL — "+fmt_until ( ai_until ) if ai_until>now ( ) else "❌ YO‘Q" ) )
        return await q.edit_message_text ( f"👤 {u.full_name}\n🆔 {u.id}\n🎖 {title_for ( u.id ) }\n⭐ Kredit: {r['wallet'] if r else 0}\n✨ XP: {xp}\n💬 Xabarlar: {msgs}\n\n🤖 AI Premium: {ai_status}",reply_markup=back_markup (  ) )

    if d=="ai_private":
        until=ai_user_until ( u.id )
        if u.id in SUPER_OWNERS: status="👑 FAOL — Super Ega"
        elif until>now ( ): status="✅ FAOL\n📅 "+fmt_until ( until )
        else: status="❌ FAOL EMAS"
        kb=InlineKeyboardMarkup ( [[InlineKeyboardButton ( "💎 100 ⭐ — 30 kun",callback_data="aipbuy" ) ],[InlineKeyboardButton ( "⬅️ Orqaga",callback_data="home" ) ]] )
        return await q.edit_message_text ( f"🤖 VERITAS AI — SHAXSIY YORDAMCHI\n\n{status}\n\nPremium narxi: 100 ⭐ / 30 kun.\nFaol bo‘lsa botga oddiy xabar yozishingiz kifoya.",reply_markup=kb )

    if d=="aipbuy":
        if u.id in SUPER_OWNERS: return await q.answer ( "Super Ega uchun AI allaqachon faol.",show_alert=True )
        if wallet ( u.id ) <AI_PRIVATE_PRICE: return await q.answer ( "Kredit yetarli emas. Hisobni Stars bilan to‘ldiring.",show_alert=True )
        if not wallet_change ( u.id,-AI_PRIVATE_PRICE,"ai_private_30d",u.id ): return
        until=extend_ai_user ( u.id,AI_PRIVATE_DAYS )
        return await q.edit_message_text ( f"✅ Shaxsiy Veritas AI Premium yoqildi.\n💎 {AI_PRIVATE_PRICE} ⭐\n📅 {fmt_until ( until )} gacha",reply_markup=back_markup ( "home" ) )

    if d.startswith ( "aigbuy:" ) :
        _,schat,sdays=d.split ( ":" ); chat_id=int ( schat ); days=int ( sdays ); price=AI_GROUP_PLANS.get ( days )
        if not price: return
        if wallet ( u.id ) <price: return await q.answer ( f"Kredit yetarli emas. Kerak: {price} ⭐",show_alert=True )
        if not wallet_change ( u.id,-price,f"ai_group_{days}d",chat_id ): return
        until=extend_ai_group ( chat_id,days,u.id,"paid" )
        return await q.edit_message_text ( f"✅ Veritas AI guruh uchun yoqildi.\n⭐ {price}\n📅 {fmt_until ( until )} gacha",reply_markup=ai_group_menu ( chat_id,u.id ) )

    if d.startswith ( "aigfree:" ) :
        if u.id not in SUPER_OWNERS: return await q.answer ( "Faqat Super Ega.",show_alert=True )
        _,schat,sdays=d.split ( ":" ); chat_id=int ( schat ); days=int ( sdays )
        if days not in ( 1,7,30 ): return
        until=extend_ai_group ( chat_id,days,u.id,"super_free" )
        return await q.edit_message_text ( f"👑 Guruhga Veritas AI bepul yoqildi.\n📅 {days} kun — {fmt_until ( until )} gacha",reply_markup=ai_group_menu ( chat_id,u.id ) )

    if d.startswith ( "aigoff:" ) :
        if u.id not in SUPER_OWNERS: return await q.answer ( "Faqat Super Ega.",show_alert=True )
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
        STATE[u.id]={"mode":"lib_add_title","data":{}}
        return await q.edit_message_text ( "➕ KITOB QO‘SHISH\n\n1/7 — 📖 Kitob nomini yuboring:",reply_markup=back_markup ( "library" ) )

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

    if d.startswith ( "libquiz:" ) :
        bid=int ( d.split ( ":" )[1] )
        r=one ( "SELECT title,pdf_file_id FROM library_books WHERE id=? AND status='approved'", ( bid,) )
        if not r or not r["pdf_file_id"]: return await q.answer ( "PDF mavjud emas",show_alert=True )
        groups=await _quiz_allowed_groups ( ctx,u.id )
        if not groups:
            return await quiz_replace_message ( q,ctx,"👥 Test yuborish uchun Veritas ishlayotgan kamida bitta guruhda admin bo‘lishingiz kerak.",reply_markup=InlineKeyboardMarkup ( [[InlineKeyboardButton ( "⬅️ Kitob",callback_data=f"libbook:{bid}" ) ]] ) )
        kb=[]
        for cid,title in groups[:20]: kb.append ( [InlineKeyboardButton ( "👥 "+title[:35],callback_data=f"libqgrp:{bid}:{cid}" ) ] )
        kb.append ( [InlineKeyboardButton ( "⬅️ Kitob",callback_data=f"libbook:{bid}" ) ] )
        return await quiz_replace_message ( q,ctx,f"🧠 TEST TUZISH\n\n📖 {r['title']}\n\nTest qaysi guruhga yuborilsin?",reply_markup=InlineKeyboardMarkup ( kb ) )

    if d.startswith ( "libqgrp:" ) :
        _,sbid,schat=d.split ( ":" ); bid=int ( sbid ); chat_id=int ( schat )
        if u.id not in SUPER_OWNERS and not await is_tg_admin ( ctx.bot,chat_id,u.id ):
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

    if d.startswith ( "libpdf:" ) :
        bid=int ( d.split ( ":" ) [1] ) ; r=one ( "SELECT title,pdf_file_id FROM library_books WHERE id=? AND status='approved'", ( bid, ) )
        if not r or not r["pdf_file_id"]: return await q.answer ( "PDF mavjud emas",show_alert=True)
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
          [InlineKeyboardButton ( "📄 PDF",callback_data=f"libeditfield:{bid}:pdf" ) ,InlineKeyboardButton ( "🎧 Audio",callback_data=f"libeditfield:{bid}:audio" ) ],
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
        prompts={"title":"Yangi kitob nomini yuboring:","author":"Yangi muallif nomini yuboring:","categories":"Yangi kategoriyalarni vergul bilan yuboring:","description":"Yangi tavsifni yuboring:","cover":"Yangi muqova rasmini yuboring. Olib tashlash uchun: o‘chirish","pdf":"Yangi PDF faylni Document sifatida yuboring:","audio":"Yangi audio/voice/audio-fayl yuboring. Olib tashlash uchun: o‘chirish"}
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
        if u.id not in SUPER_OWNERS: return await q.edit_message_text ( "⛔ Ruxsat yo‘q.")
        uc=one ( "SELECT COUNT ( *) n FROM users" ) ["n"]; gc=one ( "SELECT COUNT ( *) n FROM groups" ) ["n"]
        return await q.edit_message_text ( f"👑 SUPER EGA\nFoydalanuvchilar: {uc}\nGuruhlar: {gc}",reply_markup=super_menu_markup (  ) )

    if d.startswith ( "alladmins:" ) :
        if u.id not in SUPER_OWNERS: return
        page=max ( 0,int ( d.split ( ":" ) [1] )  ) ; per=8
        entries=[]
        for sid in sorted ( SUPER_OWNERS ) :
            ur=one ( "SELECT first_name,username FROM users WHERE user_id=?", ( sid, ) )
            nm= ( ur["first_name"] if ur and ur["first_name"] else str ( sid ) )
            if ur and ur["username"]: nm += " @"+ur["username"]
            entries.append (  ( "👑 Super Ega",sid,nm,"" ) )
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
        if u.id not in SUPER_OWNERS: return
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
        if u.id not in SUPER_OWNERS: return
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
        if u.id not in SUPER_OWNERS: return
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

def main (  ) :
    if not TOKEN: raise RuntimeError ( "BOT_TOKEN kiritilmagan.")
    init_db ( )
    app=Application.builder (  ) .token ( TOKEN ) .build ( )
    app.add_handler ( CommandHandler ( "start",start ) )
    app.add_handler ( CommandHandler ( "help",cmd_help ) )
    app.add_handler ( CommandHandler ( "id",cmd_id ) )
    app.add_handler ( CommandHandler ( "super",cmd_super ) )
    app.add_handler ( PreCheckoutQueryHandler ( precheckout ) )
    app.add_handler ( MessageHandler ( filters.SUCCESSFUL_PAYMENT,paid ) )
    app.add_handler ( CallbackQueryHandler ( callback ) )
    app.add_handler ( MessageHandler ( filters.StatusUpdate.NEW_CHAT_MEMBERS,new_members ) )
    app.add_handler ( MessageHandler ( filters.StatusUpdate.LEFT_CHAT_MEMBER,left_member ) )
    app.add_handler ( MessageHandler ( filters.TEXT & filters.Regex ( r"^\*" ) ,star_text_router ) ,group=0)
    # Private workflow first. It handles library/hadith upload states.
    app.add_handler ( MessageHandler ( filters.ChatType.PRIVATE & ~filters.COMMAND & ~filters.SUCCESSFUL_PAYMENT,library_private_input ) ,group=1)
    # Vision must be in a DIFFERENT handler group. In the old build it shared group=1
    # with library_private_input, so python-telegram-bot never reached it.
    app.add_handler ( MessageHandler ( filters.ChatType.PRIVATE & (filters.PHOTO | filters.Document.IMAGE ) ,private_ai_media_reply ) ,group=2)
    # Group passive processing is separate.
    app.add_handler ( MessageHandler ( filters.ALL & ~filters.StatusUpdate.ALL & ~filters.SUCCESSFUL_PAYMENT,passive ) ,group=3)
    # Plain private text AI comes last.
    app.add_handler ( MessageHandler ( filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND & ~filters.Regex ( r"^\*" ) ,private_ai_reply ) ,group=4)
    if app.job_queue: app.job_queue.run_repeating ( giveaway_job,60,first=10)
    app.add_error_handler ( error_handler)
    log.info ( "VERITAS v8 starting")
    app.run_polling ( allowed_updates=Update.ALL_TYPES)

if __name__=="__main__":
    main ( )
