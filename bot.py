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

import os, re, sqlite3, time, random, logging, json
from datetime import datetime, timezone, timedelta

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
DEMO_DAYS = 7
WEEK_PRICE = 100
PREMIUM = {3:1000, 6:1500, 12:2500}
TOPUPS = (25,50,100,250,500,1000,2500)
FLOOD_CACHE = {}
STATE = {}
URL_RE = re.compile ( r" ( https?://|www\.|t\.me/|telegram\.me/|@\w+ ) ", re.I)

logging.basicConfig(level=logging.INFO)
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
    kb.append ( [InlineKeyboardButton ( "💔 Sevimlidan olish" if fav else "❤️ Sevimliga",callback_data=f"libfavtoggle:{book_id}" ) ])
    if is_library_admin ( uid ) : kb.append ( [InlineKeyboardButton ( "🗑 O‘chirish",callback_data=f"libdelask:{book_id}" ) ])
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
        if not msg.document: return await msg.reply_text ( "📄 PDF hujjat yuboring.")
        name= ( msg.document.file_name or "" ) .lower (  ) ; mime= ( msg.document.mime_type or "" ) .lower ( )
        if not (name.endswith ( ".pdf") or mime=="application/pdf" ) : return await msg.reply_text ( "❌ Faqat PDF fayl qabul qilinadi.")
        uniq=msg.document.file_unique_id or ""
        if uniq and one ( "SELECT id FROM library_books WHERE pdf_unique_id=? AND status<>'deleted'", ( uniq, )  ) :
            STATE.pop ( uid,None ) ; return await msg.reply_text ( "⚠️ Aynan shu PDF avval qo‘shilgan.",reply_markup=library_home_markup ( uid ) )
        data["pdf_file_id"]=msg.document.file_id; data["pdf_unique_id"]=uniq
        st["mode"]="lib_add_audio"
        return await msg.reply_text ( "🎧 Audio kitob bo‘lsa audio fayl yuboring. Bo‘lmasa: o'tkazish")
    if mode=="lib_add_audio":
        if msg.audio:
            data["audio_file_id"]=msg.audio.file_id; data["audio_unique_id"]=msg.audio.file_unique_id or ""
        elif msg.voice:
            data["audio_file_id"]=msg.voice.file_id; data["audio_unique_id"]=msg.voice.file_unique_id or ""
        elif msg.text and msg.text.lower (  ) .replace ( "‘","'" ) .replace ( "’","'") in ("o'tkazish","otkazish" ) :
            data["audio_file_id"]=""; data["audio_unique_id"]=""
        else: return await msg.reply_text ( "🎧 Audio/voice yuboring yoki «o'tkazish» deb yozing.")
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
    raw=msg.text or ""
    body=raw[len ( "*add.hadis" ) :].strip ( )
    parts=[x.strip ( ) for x in body.split ( "|" ) ]
    if len ( parts ) <3:
        return await msg.reply_text ( "Format:\n*add.hadis buxoriy 1 | arabcha matn | tarjima | sharh | manba\n\nArabcha bo‘lmasa ham | | joyini qoldiring.")
    head=parts[0].split ( )
    if len ( head ) <2 or not head[-1].isdigit (  ) : return await msg.reply_text ( "❌ Avval to‘plam va raqam yozing. Misol: buxoriy 1")
    num=int ( head[-1] ) ; collection=hadith_collection_key ( " ".join ( head[:-1] ) )
    arabic=parts[1]; translation=parts[2]
    explanation=parts[3] if len ( parts ) >3 else ""; source=parts[4] if len ( parts ) >4 else ""
    if not translation: return await msg.reply_text ( "❌ Tarjima bo‘sh bo‘lmasin.")
    try:
        execute ( "INSERT INTO hadiths ( collection,number,arabic,translation,explanation,source,added_by,status,created_at) VALUES ( ?,?,?,?,?,?,?,?,? ) ",
                (collection,num,arabic,translation,explanation,source,uid,"approved",now (  )  ) )
    except sqlite3.IntegrityError:
        return await msg.reply_text ( f"⚠️ {collection} {num} bazada allaqachon mavjud.")
    audit ( uid,update.effective_chat.id,"hadith_add",f"{collection} {num}")
    r=one ( "SELECT * FROM hadiths WHERE lower ( collection ) =lower ( ?) AND number=?", ( collection,num ) )
    await msg.reply_text ( "✅ Hadis qo‘shildi.")
    await send_hadith ( update.effective_chat.id,ctx,r)

async def delete_hadith_command ( update,ctx,args ) :
    msg=update.effective_message; uid=update.effective_user.id
    if not is_hadith_admin ( uid ) : return await msg.reply_text ( "⛔ Hadis o‘chirish huquqi yo‘q.")
    if len ( args ) <2 or not args[-1].isdigit (  ) : return await msg.reply_text ( "Misol: *del.hadis buxoriy 1")
    num=int ( args[-1] ) ; collection=hadith_collection_key ( " ".join ( args[:-1] ) )
    r=one ( "SELECT id,collection,number FROM hadiths WHERE lower ( collection ) =lower ( ?) AND number=? AND status='approved'", ( collection,num ) )
    if not r: return await msg.reply_text ( "❌ Hadis topilmadi.")
    kb=InlineKeyboardMarkup ( [[InlineKeyboardButton ( "✅ O‘chirish",callback_data=f"hdel:{r['id']}" ) ,InlineKeyboardButton ( "❌ Bekor",callback_data="hadith" ) ]])
    await msg.reply_text ( f"🗑 {r['collection']} {r['number']} hadisni o‘chirishni tasdiqlaysizmi?",reply_markup=kb)

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
    text="""🪶 VERITAS v8 — BUYRUQLAR

📌 ASOSIY
*help — barcha buyruqlarni ko‘rsatadi
*id — Telegram ID va chat IDni ko‘rsatadi
*men — profil va faollikni ko‘rsatadi
*aktiv — guruhdagi eng faol 10 a’zo
*aktiv 20 — ko‘rsatiladigan TOP sonini tanlaydi
*top 10 — Super Ega uchun TOP-10 yakunlash paneli
*rules — guruh qoidalarini ko‘rsatadi
*admins — Telegram va Veritas adminlarini ko‘rsatadi
*unvon <nom> — reply qilingan a’zoga unvon beradi
*unvonoff — reply qilingan a’zoning unvonini olib tashlaydi

📚 VASATIYA KUTUBXONASI
*ad.book — reply qilingan odamga kitob qo‘shish huquqi beradi (Super Ega)
*unad.book — kitob qo‘shish huquqini olib tashlaydi (Super Ega)
*bookadmins — kutubxona adminlarini ko‘rsatadi (Super Ega)

📜 SAHIH HADISLAR
*hadis — bazadan bitta random hadis chiqaradi
*hadis buxoriy 1 — aynan Buxoriy 1-hadisni chiqaradi
*add.hadis ... — yangi hadis qo‘shadi (hadis admini)
*del.hadis buxoriy 1 — hadisni tasdiqlab o‘chiradi (hadis admini)
*ad.hadis — reply qilingan odamga hadis qo‘shish huquqi beradi (Super Ega)
*unad.hadis — hadis huquqini olib tashlaydi (Super Ega)
*hadisadmins — hadis adminlarini ko‘rsatadi (Super Ega)

🛡 MODERATSIYA — reply orqali
*warn — ogohlantirish beradi; 3 warn = ban
*unwarn — bitta warnni kamaytiradi
*warns — warn sonini ko‘rsatadi
*clearwarns — barcha warnlarni tozalaydi
*mute — yozishni taqiqlaydi
*unmute — yozish huquqini qaytaradi
*kick — guruhdan chiqaradi
*ban — guruhdan bloklaydi
*unban — bandan chiqaradi
*del — reply qilingan xabarni o‘chiradi

👮 RUXSAT / ADMIN
*ruxsat — reply qilingan odamni Veritas admin qiladi
*ruxsatsiz — Veritas admin huquqini oladi
*admin — Telegram admin huquqi beradi
*unadmin — Telegram admin huquqini oladi
*approve — a’zoni himoya ro‘yxatiga qo‘shadi
*unapprove — himoyadan chiqaradi
*approved — himoyalanganlar IDlarini ko‘rsatadi

🔐 HIMOYA
*links on/off — link himoyasini yoqadi/o‘chiradi
*blacklist <so‘z> — taqiqlangan so‘z qo‘shadi
*unblacklist <so‘z> — taqiqlangan so‘zni olib tashlaydi
*blacklists — blacklistni ko‘rsatadi
*lock <turi> — media/link turini qulflaydi
*unlock <turi> — qulfni ochadi
*locks — faol qulflarni ko‘rsatadi
*antiflood on/off — flood himoyasini boshqaradi
*flood 5 — flood chegarasini belgilaydi
*report — reply qilingan xabarni adminlarga bildiradi
*reports on/off — report funksiyasini boshqaradi

💬 FILTER VA NOTES
*filter <kalit> <javob> — avtomatik javob qo‘shadi
*filters — filterlarni ko‘rsatadi
*stop <kalit> — bitta filterni o‘chiradi
*stopall — barcha filterlarni o‘chiradi
*save <nom> <matn> — note saqlaydi
*get <nom> — noteni chiqaradi
*notes — notelarni ko‘rsatadi
*clear <nom> — noteni o‘chiradi

⚙️ GURUH SOZLAMALARI
*welcome on/off — kutib olish xabarini boshqaradi
*goodbye on/off — xayrlashuv xabarini boshqaradi
*setrules <matn> — guruh qoidalarini saqlaydi

⭐ STARS / SOVG‘A
*topup 100 — Veritas Stars kreditini to‘ldiradi
*stars 100 — replydagi odam uchun Telegram Stars Gift oynasini ochadi (Super Ega)
*give <narx> — replydagi odamga real Telegram Gift yuboradi
*premium 3/6/12 — replydagi odamga Telegram Premium sovg‘a qiladi

🎉 GIVEAWAY
*giveaway gift <narx> <daq> <g‘oliblar> — Gift konkursini ochadi
*join — faol konkursga qo‘shiladi

📜 Hadis qo‘shish namunasi:
*add.hadis buxoriy 1 | arabcha matn | o‘zbekcha tarjima | qisqa sharh | manba"""
    await update.effective_message.reply_text ( text)

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
        txt=f"👤 {u.full_name}\n🆔 {u.id}\n🎖 {title_for ( u.id ) }\n⭐ Kredit: {wallet ( u.id ) }"
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
    if cmd in {"ad.book","unad.book","bookadmins","ad.hadis","unad.hadis","hadisadmins"}:
        return await content_admin_command ( update,ctx,cmd)
    if cmd=="hadis":
        return await hadith_command ( update,ctx,args)
    if cmd=="add.hadis":
        return await add_hadith_command ( update,ctx)
    if cmd=="del.hadis":
        return await delete_hadith_command ( update,ctx,args)
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

    if d=="home":
        return await q.edit_message_text ( "🪶 VERITAS v8\n\nShaxsiy kabinet",reply_markup=main_menu_markup ( u.id ) )

    if d.startswith ( "topgift:") or d.startswith ( "topplain:" ) :
        if u.id not in SUPER_OWNERS: return
        chat_id=int ( d.split ( ":",1 ) [1] ) ; with_gifts=d.startswith ( "topgift:")
        await q.edit_message_text ( "⏳ TOP-10 hisoblanmoqda..." if not with_gifts else "⏳ TOP-10 va TOP-3 Giftlar tayyorlanmoqda...")
        return await top10_result ( ctx.bot,chat_id,with_gifts,u.id)

    if d=="me":
        xp,msgs=user_total_stats ( u.id)
        r=one ( "SELECT wallet FROM users WHERE user_id=?", ( u.id, ) )
        return await q.edit_message_text ( f"👤 {u.full_name}\n🆔 {u.id}\n🎖 {title_for ( u.id ) }\n⭐ Kredit: {r['wallet'] if r else 0}\n✨ XP: {xp}\n💬 Xabarlar: {msgs}",reply_markup=back_markup (  ) )

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
        kb.append ( [InlineKeyboardButton ( "⬅️ Orqaga",callback_data="home" ) ,InlineKeyboardButton ( "🏠 Bosh menyu",callback_data="home" ) ])
        return await q.edit_message_text ( f"📜 SAHIH HADISLAR\n\nJami hadislar: {total}\nTo‘plamni tanlang yoki random hadis o‘qing.",reply_markup=InlineKeyboardMarkup ( kb ) )

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
        return await q.edit_message_text ( hadith_text ( r ) ,reply_markup=hadith_markup ( r ) )

    if d.startswith ( "hdel:" ) :
        if not is_hadith_admin ( u.id ) : return await q.answer ( "Ruxsat yo‘q",show_alert=True)
        hid=int ( d.split ( ":" ) [1] ) ; r=one ( "SELECT collection,number FROM hadiths WHERE id=? AND status='approved'", ( hid, ) )
        if not r: return await q.edit_message_text ( "❌ Hadis topilmadi.",reply_markup=back_markup ( "hadith" ) )
        execute ( "UPDATE hadiths SET status='deleted' WHERE id=?", ( hid, )  ) ; audit ( u.id,0,"hadith_delete",f"{r['collection']} {r['number']}")
        return await q.edit_message_text ( f"✅ {r['collection']} {r['number']} o‘chirildi.",reply_markup=back_markup ( "hadith" ) )

    if d=="library":
        total=one ( "SELECT COUNT ( *) n FROM library_books WHERE status='approved'" ) ["n"]
        return await q.edit_message_text ( f"📚 VASATIYA KUTUBXONASI\n\nJami kitoblar: {total}\nTil, kategoriya yoki qidiruv orqali kitob toping.",reply_markup=library_home_markup ( u.id ) )

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
    app.add_handler ( MessageHandler ( filters.ChatType.PRIVATE & ~filters.COMMAND & ~filters.SUCCESSFUL_PAYMENT,library_private_input ) ,group=1)
    app.add_handler ( MessageHandler ( filters.ALL & ~filters.StatusUpdate.ALL & ~filters.SUCCESSFUL_PAYMENT,passive ) ,group=2)
    if app.job_queue: app.job_queue.run_repeating ( giveaway_job,60,first=10)
    app.add_error_handler ( error_handler)
    log.info ( "VERITAS v8 starting")
    app.run_polling ( allowed_updates=Update.ALL_TYPES)

if __name__=="__main__":
    main ( )
