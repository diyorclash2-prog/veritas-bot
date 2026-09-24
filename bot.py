# VERITAS BOT v7 — single-file build
# Python 3.11+ | python-telegram-bot[job-queue]>=22.5,<23
#
# ENV:
# BOT_TOKEN=...
# SUPER_OWNER_IDS=5859289233,7056675943
# DB_PATH=veritas_v7.sqlite3
#
# Notes:
# - "wallet" below is prepaid bot credit backed by Telegram Stars received by this bot.
# - Telegram Gift/Premium purchases spend the bot's real Stars balance and debit the sender's prepaid credit.
# - No fake "Veritas Ball" exists.
# - Greeting auto-replies intentionally do not exist.

import os, re, sqlite3, time, random, logging, json
from datetime import datetime, timezone, timedelta
from typing import Optional

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions,
    LabeledPrice
)
from telegram.constants import ChatMemberStatus
from telegram.error import TelegramError, BadRequest, Forbidden
from telegram.ext import (
    Application, ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler,
    PreCheckoutQueryHandler, filters
)

TOKEN = os.getenv("BOT_TOKEN", "").strip()
DB_PATH = os.getenv("DB_PATH", "veritas_v7.sqlite3")
SUPER_OWNERS = {int(x) for x in os.getenv("SUPER_OWNER_IDS","").split(",") if x.strip().isdigit()}
VERSION = "7.0"
DEMO_DAYS = 7
WEEK_PRICE = 100
PREMIUM = {3:1000, 6:1500, 12:2500}
TOPUPS = (25,50,100,250,500,1000,2500)
FLOOD_CACHE = {}
STATE = {}
URL_RE = re.compile(r"(https?://|www\.|t\.me/|telegram\.me/|@\w+)", re.I)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("veritas-v7")

def now(): return int(time.time())
def iso(ts=None): return datetime.fromtimestamp(ts or now(), timezone.utc).isoformat()
def db():
    c=sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory=sqlite3.Row
    return c
def execute(sql,args=()):
    with db() as c: return c.execute(sql,args)
def one(sql,args=()):
    with db() as c: return c.execute(sql,args).fetchone()
def all_(sql,args=()):
    with db() as c: return c.execute(sql,args).fetchall()

def init_db():
    schema = """
    PRAGMA journal_mode=WAL;
    CREATE TABLE IF NOT EXISTS users(
      user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, lang TEXT DEFAULT 'uz',
      wallet INTEGER DEFAULT 0, created_at INTEGER, blocked INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS groups(
      chat_id INTEGER PRIMARY KEY, title TEXT, owner_id INTEGER, created_at INTEGER,
      demo_until INTEGER, paid_until INTEGER DEFAULT 0, free INTEGER DEFAULT 0,
      links INTEGER DEFAULT 1, antiflood INTEGER DEFAULT 1, flood_limit INTEGER DEFAULT 5,
      reports INTEGER DEFAULT 1, welcome INTEGER DEFAULT 1, goodbye INTEGER DEFAULT 1,
      rules TEXT DEFAULT '', locks TEXT DEFAULT '{}');
    CREATE TABLE IF NOT EXISTS members(
      chat_id INTEGER,user_id INTEGER,xp INTEGER DEFAULT 0,messages INTEGER DEFAULT 0,
      daily INTEGER DEFAULT 0,weekly INTEGER DEFAULT 0,last_day TEXT,last_week TEXT,
      title TEXT DEFAULT '', PRIMARY KEY(chat_id,user_id));
    CREATE TABLE IF NOT EXISTS vadmins(chat_id INTEGER,user_id INTEGER,PRIMARY KEY(chat_id,user_id));
    CREATE TABLE IF NOT EXISTS approved(chat_id INTEGER,user_id INTEGER,PRIMARY KEY(chat_id,user_id));
    CREATE TABLE IF NOT EXISTS warns(chat_id INTEGER,user_id INTEGER,count INTEGER DEFAULT 0,PRIMARY KEY(chat_id,user_id));
    CREATE TABLE IF NOT EXISTS blacklist(chat_id INTEGER,word TEXT,PRIMARY KEY(chat_id,word));
    CREATE TABLE IF NOT EXISTS notes(chat_id INTEGER,name TEXT,text TEXT,PRIMARY KEY(chat_id,name));
    CREATE TABLE IF NOT EXISTS filters_(chat_id INTEGER,key TEXT,response TEXT,PRIMARY KEY(chat_id,key));
    CREATE TABLE IF NOT EXISTS tx(
      id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,kind TEXT,amount INTEGER,
      target_id INTEGER,ref TEXT,created_at INTEGER,meta TEXT DEFAULT '{}');
    CREATE TABLE IF NOT EXISTS payments(
      charge_id TEXT PRIMARY KEY,user_id INTEGER,amount INTEGER,payload TEXT,created_at INTEGER,refunded INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS subscriptions(
      chat_id INTEGER PRIMARY KEY, payer_id INTEGER, paid_until INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS giveaways(
      id INTEGER PRIMARY KEY AUTOINCREMENT,chat_id INTEGER,creator_id INTEGER,kind TEXT,
      prize TEXT,winners INTEGER,end_at INTEGER,status TEXT DEFAULT 'open',created_at INTEGER);
    CREATE TABLE IF NOT EXISTS giveaway_entries(
      giveaway_id INTEGER,user_id INTEGER,PRIMARY KEY(giveaway_id,user_id));
    CREATE TABLE IF NOT EXISTS books(
      id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT,author TEXT,tags TEXT,file_id TEXT,added_by INTEGER,created_at INTEGER);
    CREATE TABLE IF NOT EXISTS audit(
      id INTEGER PRIMARY KEY AUTOINCREMENT,actor_id INTEGER,chat_id INTEGER,action TEXT,detail TEXT,created_at INTEGER);
    """
    with db() as c: c.executescript(schema)

def ensure_user(u):
    if not u: return
    with db() as c:
        c.execute("""INSERT INTO users(user_id,username,first_name,created_at) VALUES(?,?,?,?)
        ON CONFLICT(user_id) DO UPDATE SET username=excluded.username,first_name=excluded.first_name""",
        (u.id,u.username or "",u.first_name or "",now()))
def ensure_group(chat):
    if not chat or chat.type not in ("group","supergroup"): return
    with db() as c:
        c.execute("""INSERT INTO groups(chat_id,title,created_at,demo_until) VALUES(?,?,?,?)
        ON CONFLICT(chat_id) DO UPDATE SET title=excluded.title""",
        (chat.id,chat.title or "",now(),now()+DEMO_DAYS*86400))
def audit(actor,chat,action,detail=""):
    execute("INSERT INTO audit(actor_id,chat_id,action,detail,created_at) VALUES(?,?,?,?,?)",
            (actor,chat,action,detail,now()))

def wallet(uid): 
    r=one("SELECT wallet FROM users WHERE user_id=?",(uid,)); return int(r["wallet"]) if r else 0
def wallet_change(uid,delta,kind,target=None,ref=None,meta=None):
    with db() as c:
        r=c.execute("SELECT wallet FROM users WHERE user_id=?",(uid,)).fetchone()
        bal=int(r["wallet"]) if r else 0
        if delta<0 and bal+delta<0: return False
        c.execute("UPDATE users SET wallet=wallet+? WHERE user_id=?",(delta,uid))
        c.execute("INSERT INTO tx(user_id,kind,amount,target_id,ref,created_at,meta) VALUES(?,?,?,?,?,?,?)",
                  (uid,kind,delta,target,ref,now(),json.dumps(meta or {},ensure_ascii=False)))
    return True

async def is_tg_admin(bot,chat_id,uid):
    try:
        m=await bot.get_chat_member(chat_id,uid)
        return m.status in (ChatMemberStatus.OWNER,ChatMemberStatus.ADMINISTRATOR)
    except TelegramError: return False
async def can_manage(bot,chat_id,uid):
    if uid in SUPER_OWNERS: return True
    if await is_tg_admin(bot,chat_id,uid): return True
    return bool(one("SELECT 1 FROM vadmins WHERE chat_id=? AND user_id=?",(chat_id,uid)))
async def protected(bot,chat_id,uid):
    return uid in SUPER_OWNERS or await is_tg_admin(bot,chat_id,uid)
def replied(update): return update.effective_message.reply_to_message if update.effective_message else None

def level(xp): return max(1, int((xp/20)**0.5)+1)
def title_for(uid,custom=""):
    if uid in SUPER_OWNERS: return "👑 Super Ega"
    return custom or "A’zo"

async def start(update,ctx):
    ensure_user(update.effective_user)
    u=update.effective_user
    if update.effective_chat.type != "private":
        ensure_group(update.effective_chat)
        await update.effective_message.reply_text("🪶 Veritas v7 ishlayapti. Shaxsiy kabinet uchun botga private yozing.")
        return
    kb=[
      [InlineKeyboardButton("👤 Profil",callback_data="me"),InlineKeyboardButton("⭐ Hisob",callback_data="wallet")],
      [InlineKeyboardButton("🎁 Gift",callback_data="gifts"),InlineKeyboardButton("💎 Premium",callback_data="premium")],
      [InlineKeyboardButton("🏘 Guruhlarim",callback_data="mygroups"),InlineKeyboardButton("📚 Kutubxona",callback_data="library")],
    ]
    if u.id in SUPER_OWNERS: kb.append([InlineKeyboardButton("👑 Super Ega",callback_data="super")])
    await update.effective_message.reply_text("🪶 VERITAS v7\n\nShaxsiy kabinet",reply_markup=InlineKeyboardMarkup(kb))

async def cmd_id(update,ctx):
    ensure_user(update.effective_user)
    await update.effective_message.reply_text(f"👤 ID: {update.effective_user.id}\n💬 Chat ID: {update.effective_chat.id}")

async def cmd_help(update,ctx):
    text="""🪶 VERITAS v7

ASOSIY
*help  *id  *men  *aktiv  *aktiv 10  *top 10  *rules  *admins
*unvon matn  *unvonoff

MODERATSIYA (reply)
*warn  *unwarn  *warns  *clearwarns
*mute  *unmute  *kick  *ban  *unban  *del

VERITAS ADMIN (reply)
*ruxsat  *ruxsatsiz

TELEGRAM ADMIN (reply)
*admin  *unadmin

HIMOYA
*links on/off
*blacklist so‘z  *unblacklist so‘z  *blacklists
*lock links/photo/video/sticker/animation/document/voice/audio
*unlock turi  *locks
*antiflood on/off  *flood 5
*approve  *unapprove  *approved
*report  *reports on/off

FILTER / NOTES
*filter kalit javob  *filters  *stop kalit  *stopall
*save nom matn  *get nom  *notes  *clear nom

SOZLAMA
*welcome on/off  *goodbye on/off  *setrules matn

⭐ REAL STARS KREDITI
*topup 100

🎁 REAL TELEGRAM GIFT
Reply + *give  (mavjud Giftlar)
*give 25 / 50 / 100 — shu narxdagi mavjud Giftni qidiradi.

💎 PREMIUM
Reply + *premium 3 / 6 / 12

🎉 GIVEAWAY
*giveaway gift <narx> <daq> <g‘oliblar>
*join
"""
    await update.effective_message.reply_text(text)

async def cmd_super(update,ctx):
    ensure_user(update.effective_user)
    if update.effective_user.id not in SUPER_OWNERS:
        return await update.effective_message.reply_text("⛔ Bu bo‘lim faqat Super Ega uchun.")
    uc=one("SELECT COUNT(*) n FROM users")["n"]; gc=one("SELECT COUNT(*) n FROM groups")["n"]
    try:
        sb=await ctx.bot.get_my_star_balance()
        real=getattr(sb,"amount",sb)
    except Exception: real="API orqali olinmadi"
    await update.effective_message.reply_text(
        f"👑 VERITAS SUPER EGA\n\nFoydalanuvchilar: {uc}\nGuruhlar: {gc}\nBot real Stars: {real}\n"
        f"Super Egalar: {', '.join(map(str,SUPER_OWNERS))}"
    )

async def topup(update,ctx,amount):
    if update.effective_chat.type!="private":
        return await update.effective_message.reply_text("⭐ Hisobni private kabinetda to‘ldiring.")
    if amount not in TOPUPS:
        return await update.effective_message.reply_text("Miqdor: "+", ".join(map(str,TOPUPS)))
    payload=f"topup:{update.effective_user.id}:{amount}:{now()}"
    await ctx.bot.send_invoice(
        chat_id=update.effective_chat.id,title="Veritas Stars krediti",
        description=f"Veritas kabinetiga {amount} ⭐ kredit",
        payload=payload,currency="XTR",prices=[LabeledPrice("Stars",amount)]
    )

async def precheckout(update,ctx):
    q=update.pre_checkout_query
    ok=q.invoice_payload.startswith("topup:")
    await q.answer(ok=ok,error_message=None if ok else "Noto‘g‘ri to‘lov.")

async def paid(update,ctx):
    ensure_user(update.effective_user)
    p=update.effective_message.successful_payment
    if not p or p.currency!="XTR" or not p.invoice_payload.startswith("topup:"): return
    if one("SELECT 1 FROM payments WHERE charge_id=?",(p.telegram_payment_charge_id,)): return
    with db() as c:
        c.execute("INSERT INTO payments(charge_id,user_id,amount,payload,created_at) VALUES(?,?,?,?,?)",
                  (p.telegram_payment_charge_id,update.effective_user.id,p.total_amount,p.invoice_payload,now()))
    wallet_change(update.effective_user.id,p.total_amount,"topup",ref=p.telegram_payment_charge_id)
    await update.effective_message.reply_text(f"✅ {p.total_amount} ⭐ kredit qo‘shildi.\nBalans: {wallet(update.effective_user.id)} ⭐")

async def show_me(update,ctx):
    u=update.effective_user; ensure_user(u)
    chat=update.effective_chat
    if chat.type in ("group","supergroup"):
        ensure_group(chat)
        r=one("SELECT * FROM members WHERE chat_id=? AND user_id=?",(chat.id,u.id))
        xp=int(r["xp"]) if r else 0; msgs=int(r["messages"]) if r else 0; custom=r["title"] if r else ""
        rank=one("""SELECT 1+COUNT(*) n FROM members WHERE chat_id=? AND messages>
                   COALESCE((SELECT messages FROM members WHERE chat_id=? AND user_id=?),0)""",(chat.id,chat.id,u.id))["n"]
        txt=f"👤 {u.full_name}\n🆔 {u.id}\n🎖 {title_for(u.id,custom)}\n⭐ Kredit: {wallet(u.id)}\n📈 Level: {level(xp)} | XP: {xp}\n💬 Xabarlar: {msgs}\n🏆 Reyting: #{rank}"
    else:
        txt=f"👤 {u.full_name}\n🆔 {u.id}\n🎖 {title_for(u.id)}\n⭐ Kredit: {wallet(u.id)}"
    await update.effective_message.reply_text(txt)


async def title_command(update,ctx,cmd,args):
    chat=update.effective_chat; msg=update.effective_message; actor=update.effective_user
    if chat.type not in ("group","supergroup"):
        return await msg.reply_text("⛔ Unvon faqat guruhda boshqariladi.")
    ensure_group(chat); ensure_user(actor)
    if not await can_manage(ctx.bot,chat.id,actor.id):
        return await msg.reply_text("⛔ Sizda unvon boshqarish huquqi yo‘q.")
    target=replied(update)
    if not target or not target.from_user:
        return await msg.reply_text("↩️ Foydalanuvchi xabariga reply qiling.")
    tu=target.from_user
    if tu.id in SUPER_OWNERS:
        return await msg.reply_text("👑 Super Ega unvonini o‘zgartirib bo‘lmaydi.")
    execute("""INSERT OR IGNORE INTO members(chat_id,user_id,xp,messages,daily,weekly,title)
               VALUES(?,?,0,0,0,0,'')""",(chat.id,tu.id))
    if cmd=="unvon":
        title=" ".join(args).strip()
        if not title: return await msg.reply_text("Misol: *unvon Kitobxon")
        if len(title)>40: return await msg.reply_text("❗ Unvon 40 belgidan uzun bo‘lmasin.")
        if title.casefold().replace("👑","").strip().replace(" ","")=="superega":
            return await msg.reply_text("⛔ «Super Ega» unvoni himoyalangan.")
        execute("UPDATE members SET title=? WHERE chat_id=? AND user_id=?",(title,chat.id,tu.id))
        audit(actor.id,chat.id,"title_set",f"{tu.id}: {title}")
        return await msg.reply_text(f"🎖 {tu.full_name} uchun unvon: «{title}»")
    execute("UPDATE members SET title='' WHERE chat_id=? AND user_id=?",(chat.id,tu.id))
    audit(actor.id,chat.id,"title_removed",str(tu.id))
    await msg.reply_text(f"✅ {tu.full_name}ning unvoni olib tashlandi.")

def display_name_row(r):
    name=(r["first_name"] or "").strip() or "Nomsiz"
    username=(" @"+r["username"]) if (r["username"] or "").strip() else ""
    return name+username

async def top10_menu(update,ctx):
    if update.effective_user.id not in SUPER_OWNERS:
        return await update.effective_message.reply_text("⛔ TOP mukofot paneli faqat Super Ega uchun.")
    kb=InlineKeyboardMarkup([[
        InlineKeyboardButton("🎁 Giftli",callback_data=f"topgift:{update.effective_chat.id}"),
        InlineKeyboardButton("🏆 Giftsiz",callback_data=f"topplain:{update.effective_chat.id}")
    ]])
    await update.effective_message.reply_text(
        "🏆 TOP-10 yakunlash usulini tanlang:\n\n"
        "🎁 Giftli — TOP-3 ga 50 ⭐ lik haqiqiy Telegram Gift.\n"
        "🏆 Giftsiz — faqat TOP-10 natijasi.",
        reply_markup=kb
    )

async def top10_result(bot,chat_id,with_gifts=False,actor_id=None):
    rows=all_("""SELECT m.user_id,m.messages,m.xp,m.title,u.first_name,u.username
                 FROM members m LEFT JOIN users u ON u.user_id=m.user_id
                 WHERE m.chat_id=? ORDER BY m.messages DESC LIMIT 10""",(chat_id,))
    if not rows:
        await bot.send_message(chat_id,"🏆 TOP-10 uchun ma’lumot yo‘q.")
        return
    lines=["🏆 TOP-10"]
    for i,r in enumerate(rows):
        lines.append(f"{i+1}. {display_name_row(r)} — {r['messages']} xabar")
    await bot.send_message(chat_id,"\n".join(lines))
    if not with_gifts: return
    try:
        available=await bot.get_available_gifts()
        gift=next((g for g in available.gifts
                   if int(getattr(g,"star_count",0))==50
                   and (getattr(g,"remaining_count",1) or 0)!=0),None)
    except Exception as e:
        await bot.send_message(chat_id,f"❌ Giftlar olinmadi: {e}"); return
    if not gift:
        await bot.send_message(chat_id,"❌ Hozir 50 ⭐ lik Telegram Gift mavjud emas."); return
    # Gift is paid from the Super Owner's prepaid Veritas credit.
    cost=50*min(3,len(rows))
    if actor_id is None or wallet(actor_id)<cost:
        await bot.send_message(chat_id,f"❌ Super Ega kreditida kamida {cost} ⭐ kerak."); return
    sent=[]
    for r in rows[:3]:
        uid=int(r["user_id"])
        if not wallet_change(actor_id,-50,"top10_gift_pending",uid,meta={"gift_id":str(gift.id)}):
            break
        try:
            await bot.send_gift(user_id=uid,gift_id=gift.id,text="🏆 Veritas TOP-3 mukofoti")
            sent.append(display_name_row(r))
        except Exception:
            wallet_change(actor_id,50,"top10_gift_rollback",uid)
    await bot.send_message(chat_id,
        "🎁 TOP-3 Gift natijasi:\n"+("\n".join("✅ "+x for x in sent) if sent else "Gift yuborilmadi."))

async def group_action(update,ctx,cmd,arg):
    chat=update.effective_chat; u=update.effective_user; msg=update.effective_message
    ensure_group(chat); ensure_user(u)
    if not await can_manage(ctx.bot,chat.id,u.id):
        return await msg.reply_text("⛔ Sizda bu amal uchun ruxsat yo‘q.")
    target=replied(update)
    if cmd in {"warn","unwarn","clearwarns","mute","unmute","kick","ban","unban","del","ruxsat","ruxsatsiz","admin","unadmin","approve","unapprove"} and not target:
        return await msg.reply_text("↩️ Foydalanuvchi xabariga reply qiling.")
    if cmd=="del":
        try: await target.delete(); await msg.delete()
        except TelegramError: pass
        return
    tu=target.from_user if target else None
    if tu and cmd in {"warn","mute","kick","ban"} and await protected(ctx.bot,chat.id,tu.id):
        return await msg.reply_text("🛡 Himoyalangan foydalanuvchi.")
    try:
        if cmd=="warn":
            execute("""INSERT INTO warns(chat_id,user_id,count) VALUES(?,?,1)
            ON CONFLICT(chat_id,user_id) DO UPDATE SET count=count+1""",(chat.id,tu.id))
            n=one("SELECT count FROM warns WHERE chat_id=? AND user_id=?",(chat.id,tu.id))["count"]
            if n>=3:
                await ctx.bot.ban_chat_member(chat.id,tu.id); execute("DELETE FROM warns WHERE chat_id=? AND user_id=?",(chat.id,tu.id))
                return await msg.reply_text(f"🚫 {tu.full_name}: 3 warn → ban.")
            return await msg.reply_text(f"⚠️ {tu.full_name}: {n}/3 warn.")
        if cmd=="unwarn":
            execute("UPDATE warns SET count=MAX(count-1,0) WHERE chat_id=? AND user_id=?",(chat.id,tu.id))
        elif cmd=="clearwarns": execute("DELETE FROM warns WHERE chat_id=? AND user_id=?",(chat.id,tu.id))
        elif cmd=="mute":
            await ctx.bot.restrict_chat_member(chat.id,tu.id,ChatPermissions(can_send_messages=False))
        elif cmd=="unmute":
            await ctx.bot.restrict_chat_member(chat.id,tu.id,ChatPermissions(can_send_messages=True,can_send_audios=True,can_send_documents=True,can_send_photos=True,can_send_videos=True,can_send_video_notes=True,can_send_voice_notes=True,can_send_polls=True,can_send_other_messages=True,can_add_web_page_previews=True,can_invite_users=True))
        elif cmd=="kick":
            await ctx.bot.ban_chat_member(chat.id,tu.id); await ctx.bot.unban_chat_member(chat.id,tu.id)
        elif cmd=="ban": await ctx.bot.ban_chat_member(chat.id,tu.id)
        elif cmd=="unban": await ctx.bot.unban_chat_member(chat.id,tu.id,only_if_banned=True)
        elif cmd=="ruxsat": execute("INSERT OR IGNORE INTO vadmins VALUES(?,?)",(chat.id,tu.id))
        elif cmd=="ruxsatsiz": execute("DELETE FROM vadmins WHERE chat_id=? AND user_id=?",(chat.id,tu.id))
        elif cmd=="approve": execute("INSERT OR IGNORE INTO approved VALUES(?,?)",(chat.id,tu.id))
        elif cmd=="unapprove": execute("DELETE FROM approved WHERE chat_id=? AND user_id=?",(chat.id,tu.id))
        elif cmd=="admin":
            await ctx.bot.promote_chat_member(chat.id,tu.id,can_delete_messages=True,can_restrict_members=True,can_invite_users=True)
        elif cmd=="unadmin":
            await ctx.bot.promote_chat_member(chat.id,tu.id,can_delete_messages=False,can_restrict_members=False,can_invite_users=False,can_promote_members=False,can_change_info=False,can_pin_messages=False)
        audit(u.id,chat.id,cmd,str(tu.id))
        await msg.reply_text("✅ Bajarildi.")
    except TelegramError as e: await msg.reply_text(f"❌ Telegram: {e}")

async def settings_command(update,ctx,cmd,args):
    chat=update.effective_chat; msg=update.effective_message; uid=update.effective_user.id
    ensure_group(chat)
    if not await can_manage(ctx.bot,chat.id,uid): return await msg.reply_text("⛔ Ruxsat yo‘q.")
    if cmd in ("links","antiflood","reports","welcome","goodbye"):
        if not args or args[0].lower() not in ("on","off"): return await msg.reply_text(f"*{cmd} on/off")
        execute(f"UPDATE groups SET {cmd}=? WHERE chat_id=?",(1 if args[0].lower()=="on" else 0,chat.id))
        return await msg.reply_text("✅ Saqlandi.")
    if cmd=="flood":
        n=int(args[0]) if args and args[0].isdigit() else 0
        if not 3<=n<=20: return await msg.reply_text("*flood 3..20")
        execute("UPDATE groups SET flood_limit=? WHERE chat_id=?",(n,chat.id)); return await msg.reply_text("✅ Saqlandi.")
    if cmd=="setrules":
        text=" ".join(args).strip()
        execute("UPDATE groups SET rules=? WHERE chat_id=?",(text,chat.id)); return await msg.reply_text("✅ Qoidalar saqlandi.")
    if cmd=="lock" and args:
        typ=args[0].lower(); r=one("SELECT locks FROM groups WHERE chat_id=?",(chat.id,)); d=json.loads(r["locks"] or "{}"); d[typ]=True
        execute("UPDATE groups SET locks=? WHERE chat_id=?",(json.dumps(d),chat.id)); return await msg.reply_text(f"🔒 {typ}")
    if cmd=="unlock" and args:
        typ=args[0].lower(); r=one("SELECT locks FROM groups WHERE chat_id=?",(chat.id,)); d=json.loads(r["locks"] or "{}"); d.pop(typ,None)
        execute("UPDATE groups SET locks=? WHERE chat_id=?",(json.dumps(d),chat.id)); return await msg.reply_text(f"🔓 {typ}")
    if cmd=="blacklist" and args:
        w=" ".join(args).lower(); execute("INSERT OR IGNORE INTO blacklist VALUES(?,?)",(chat.id,w)); return await msg.reply_text("✅ Blacklistga qo‘shildi.")
    if cmd=="unblacklist" and args:
        w=" ".join(args).lower(); execute("DELETE FROM blacklist WHERE chat_id=? AND word=?",(chat.id,w)); return await msg.reply_text("✅ O‘chirildi.")
    if cmd=="filter" and len(args)>=2:
        key=args[0].lower(); response=" ".join(args[1:])
        execute("INSERT OR REPLACE INTO filters_ VALUES(?,?,?)",(chat.id,key,response)); return await msg.reply_text("✅ Filter saqlandi.")
    if cmd=="stop" and args:
        execute("DELETE FROM filters_ WHERE chat_id=? AND key=?",(chat.id,args[0].lower())); return await msg.reply_text("✅ Filter o‘chirildi.")
    if cmd=="stopall": execute("DELETE FROM filters_ WHERE chat_id=?",(chat.id,)); return await msg.reply_text("✅ Barcha filterlar o‘chirildi.")
    if cmd=="save" and len(args)>=2:
        execute("INSERT OR REPLACE INTO notes VALUES(?,?,?)",(chat.id,args[0].lower()," ".join(args[1:]))); return await msg.reply_text("✅ Note saqlandi.")
    if cmd=="clear" and args:
        execute("DELETE FROM notes WHERE chat_id=? AND name=?",(chat.id,args[0].lower())); return await msg.reply_text("✅ Note o‘chirildi.")

async def info_command(update,ctx,cmd,args):
    chat=update.effective_chat; msg=update.effective_message
    if cmd=="rules":
        r=one("SELECT rules FROM groups WHERE chat_id=?",(chat.id,)); return await msg.reply_text((r["rules"] if r else "") or "Qoidalar hali yozilmagan.")
    if cmd=="admins":
        admins=await ctx.bot.get_chat_administrators(chat.id); va=all_("SELECT user_id FROM vadmins WHERE chat_id=?",(chat.id,))
        s="👮 Telegram adminlar:\n"+"\n".join(f"• {x.user.full_name}" for x in admins)
        if va: s+="\n\n🪶 Veritas admin ID:\n"+"\n".join(str(x["user_id"]) for x in va)
        return await msg.reply_text(s)
    if cmd=="warns":
        t=replied(update); uid=t.from_user.id if t else update.effective_user.id
        r=one("SELECT count FROM warns WHERE chat_id=? AND user_id=?",(chat.id,uid)); return await msg.reply_text(f"⚠️ Warn: {r['count'] if r else 0}/3")
    if cmd=="blacklists":
        rows=all_("SELECT word FROM blacklist WHERE chat_id=? ORDER BY word",(chat.id,)); return await msg.reply_text("🚫 "+(", ".join(r["word"] for r in rows) or "Bo‘sh"))
    if cmd=="locks":
        r=one("SELECT locks FROM groups WHERE chat_id=?",(chat.id,)); d=json.loads(r["locks"] or "{}") if r else {}
        return await msg.reply_text("🔐 "+(", ".join(d.keys()) or "Lock yo‘q"))
    if cmd=="approved":
        rows=all_("SELECT user_id FROM approved WHERE chat_id=?",(chat.id,)); return await msg.reply_text("✅ "+(", ".join(str(r["user_id"]) for r in rows) or "Bo‘sh"))
    if cmd=="filters":
        rows=all_("SELECT key FROM filters_ WHERE chat_id=?",(chat.id,)); return await msg.reply_text("💬 "+(", ".join(r["key"] for r in rows) or "Bo‘sh"))
    if cmd=="notes":
        rows=all_("SELECT name FROM notes WHERE chat_id=?",(chat.id,)); return await msg.reply_text("📝 "+(", ".join(r["name"] for r in rows) or "Bo‘sh"))
    if cmd=="get" and args:
        r=one("SELECT text FROM notes WHERE chat_id=? AND name=?",(chat.id,args[0].lower())); return await msg.reply_text(r["text"] if r else "Topilmadi.")
    if cmd=="aktiv":
        n=min(50,max(1,int(args[0]) if args and args[0].isdigit() else 10))
        rows=all_("""SELECT m.user_id,m.messages,m.title,m.xp,u.first_name,u.username
                     FROM members m LEFT JOIN users u ON u.user_id=m.user_id
                     WHERE m.chat_id=? ORDER BY m.messages DESC LIMIT ?""",(chat.id,n))
        return await msg.reply_text("🏆 Faollik\n"+("\n".join(
            f"{i+1}. {display_name_row(r)} — {r['messages']} | Lv.{level(r['xp'])} {title_for(r['user_id'],r['title'])}"
            for i,r in enumerate(rows)) or "Ma’lumot yo‘q"))

async def report_cmd(update,ctx):
    if not replied(update): return await update.effective_message.reply_text("↩️ Shikoyat qilinadigan xabarga reply qiling.")
    r=one("SELECT reports FROM groups WHERE chat_id=?",(update.effective_chat.id,))
    if r and not r["reports"]: return
    admins=await ctx.bot.get_chat_administrators(update.effective_chat.id)
    tags=" ".join("@"+a.user.username for a in admins if a.user.username)
    await update.effective_message.reply_text(f"📢 Report: {tags or 'adminlar'}")

async def gift_send(update,ctx,args):
    t=replied(update)
    if not t or not t.from_user: return await update.effective_message.reply_text("↩️ Gift oluvchining xabariga reply qiling.")
    sender=update.effective_user.id; target=t.from_user.id
    try:
        gifts=await ctx.bot.get_available_gifts()
        gl=list(gifts.gifts)
    except Exception as e: return await update.effective_message.reply_text(f"❌ Gift ro‘yxati olinmadi: {e}")
    price=int(args[0]) if args and args[0].isdigit() else None
    candidates=[g for g in gl if (price is None or getattr(g,"star_count",None)==price) and (getattr(g,"remaining_count",None) is None or getattr(g,"remaining_count",0)>0)]
    if not candidates:
        prices=sorted({getattr(g,"star_count",0) for g in gl if getattr(g,"star_count",0)})
        return await update.effective_message.reply_text("🎁 Mavjud narxlar: "+", ".join(map(str,prices[:30])))
    g=candidates[0]; cost=int(g.star_count)
    if wallet(sender)<cost: return await update.effective_message.reply_text(f"⭐ Kredit yetarli emas. Kerak: {cost}, sizda: {wallet(sender)}")
    # debit first, restore on API failure
    if not wallet_change(sender,-cost,"gift_pending",target,meta={"gift_id":str(g.id)}): return
    try:
        await ctx.bot.send_gift(user_id=target,gift_id=g.id,text=f"🎁 Veritas orqali {update.effective_user.first_name}dan sovg‘a")
        execute("UPDATE tx SET kind='gift' WHERE id=(SELECT MAX(id) FROM tx WHERE user_id=?)",(sender,))
        await update.effective_message.reply_text(f"✅ Haqiqiy Telegram Gift yuborildi: {cost} ⭐")
    except Exception as e:
        wallet_change(sender,cost,"gift_rollback",target)
        await update.effective_message.reply_text(f"❌ Gift yuborilmadi, kredit qaytarildi.\n{e}")

async def premium_send(update,ctx,args):
    t=replied(update)
    if not t or not t.from_user: return await update.effective_message.reply_text("↩️ Premium oluvchiga reply qiling.")
    m=int(args[0]) if args and args[0].isdigit() else 0
    if m not in PREMIUM: return await update.effective_message.reply_text("*premium 3 / 6 / 12")
    cost=PREMIUM[m]; sender=update.effective_user.id; target=t.from_user.id
    if wallet(sender)<cost: return await update.effective_message.reply_text(f"⭐ Kredit yetarli emas. Kerak: {cost}")
    if not wallet_change(sender,-cost,"premium_pending",target): return
    try:
        await ctx.bot.gift_premium_subscription(user_id=target,month_count=m,star_count=cost,text="💎 Veritas orqali Premium sovg‘a")
        execute("UPDATE tx SET kind='premium' WHERE id=(SELECT MAX(id) FROM tx WHERE user_id=?)",(sender,))
        await update.effective_message.reply_text(f"✅ {m} oylik Telegram Premium yuborildi.")
    except Exception as e:
        wallet_change(sender,cost,"premium_rollback",target)
        await update.effective_message.reply_text(f"❌ Premium yuborilmadi, kredit qaytarildi.\n{e}")

async def star_text_router(update,ctx):
    msg=update.effective_message
    if not msg or not msg.text or not msg.text.startswith("*"): return
    ensure_user(update.effective_user)
    if update.effective_chat.type in ("group","supergroup"): ensure_group(update.effective_chat)
    parts=msg.text[1:].strip().split()
    if not parts: return
    cmd=parts[0].lower(); args=parts[1:]
    if cmd=="help": return await cmd_help(update,ctx)
    if cmd=="id": return await cmd_id(update,ctx)
    if cmd=="men": return await show_me(update,ctx)
    if cmd in {"unvon","unvonoff"}:
        return await title_command(update,ctx,cmd,args)
    if cmd=="top" and args and args[0]=="10":
        return await top10_menu(update,ctx)
    if cmd=="topup":
        a=int(args[0]) if args and args[0].isdigit() else 0
        return await topup(update,ctx,a)
    if update.effective_chat.type not in ("group","supergroup"):
        return await msg.reply_text("Bu buyruq guruh uchun.")
    if cmd in {"warn","unwarn","clearwarns","mute","unmute","kick","ban","unban","del","ruxsat","ruxsatsiz","admin","unadmin","approve","unapprove"}:
        return await group_action(update,ctx,cmd,args)
    if cmd in {"links","antiflood","reports","welcome","goodbye","flood","setrules","lock","unlock","blacklist","unblacklist","filter","stop","stopall","save","clear"}:
        return await settings_command(update,ctx,cmd,args)
    if cmd in {"rules","admins","warns","blacklists","locks","approved","filters","notes","get","aktiv"}:
        return await info_command(update,ctx,cmd,args)
    if cmd=="report": return await report_cmd(update,ctx)
    if cmd=="give": return await gift_send(update,ctx,args)
    if cmd=="premium": return await premium_send(update,ctx,args)
    if cmd=="join":
        g=one("SELECT id FROM giveaways WHERE chat_id=? AND status='open' AND end_at>? ORDER BY id DESC LIMIT 1",(update.effective_chat.id,now()))
        if not g: return await msg.reply_text("Faol konkurs yo‘q.")
        execute("INSERT OR IGNORE INTO giveaway_entries VALUES(?,?)",(g["id"],update.effective_user.id)); return await msg.reply_text("🎉 Ishtirok qabul qilindi.")
    if cmd=="giveaway":
        if not await can_manage(ctx.bot,update.effective_chat.id,update.effective_user.id): return await msg.reply_text("⛔ Ruxsat yo‘q.")
        if len(args)<4 or args[0]!="gift" or not all(x.isdigit() for x in args[1:4]): return await msg.reply_text("*giveaway gift <narx> <daq> <g‘oliblar>")
        price,mins,wins=map(int,args[1:4])
        execute("INSERT INTO giveaways(chat_id,creator_id,kind,prize,winners,end_at,created_at) VALUES(?,?,?,?,?,?,?)",
                (update.effective_chat.id,update.effective_user.id,"gift",str(price),wins,now()+mins*60,now()))
        return await msg.reply_text(f"🎉 Konkurs ochildi: {price} ⭐ Gift | {wins} g‘olib | {mins} daqiqa\n*join bilan qatnashing.")

def media_type(msg):
    if msg.photo:return "photo"
    if msg.video:return "video"
    if msg.sticker:return "sticker"
    if msg.animation:return "animation"
    if msg.document:return "document"
    if msg.voice:return "voice"
    if msg.audio:return "audio"
    return None

async def passive(update,ctx):
    msg=update.effective_message; u=update.effective_user; chat=update.effective_chat
    if not msg or not u or chat.type not in ("group","supergroup"): return
    ensure_user(u); ensure_group(chat)
    # Activity: one XP/message; counters reset lazily by UTC day/week.
    day=datetime.now(timezone.utc).strftime("%Y-%m-%d"); week=datetime.now(timezone.utc).strftime("%G-%V")
    with db() as c:
        r=c.execute("SELECT * FROM members WHERE chat_id=? AND user_id=?",(chat.id,u.id)).fetchone()
        if not r:
            c.execute("INSERT INTO members(chat_id,user_id,xp,messages,daily,weekly,last_day,last_week) VALUES(?,?,1,1,1,1,?,?)",(chat.id,u.id,day,week))
        else:
            daily=(r["daily"] if r["last_day"]==day else 0)+1; weekly=(r["weekly"] if r["last_week"]==week else 0)+1
            c.execute("UPDATE members SET xp=xp+1,messages=messages+1,daily=?,weekly=?,last_day=?,last_week=? WHERE chat_id=? AND user_id=?",(daily,weekly,day,week,chat.id,u.id))
    if await protected(ctx.bot,chat.id,u.id) or one("SELECT 1 FROM approved WHERE chat_id=? AND user_id=?",(chat.id,u.id)): return
    g=one("SELECT * FROM groups WHERE chat_id=?",(chat.id,))
    text=(msg.text or msg.caption or "").lower()
    # blacklist
    for r in all_("SELECT word FROM blacklist WHERE chat_id=?",(chat.id,)):
        if r["word"] in text:
            try: await msg.delete()
            except TelegramError: pass
            return
    # links
    if g and g["links"] and URL_RE.search(text):
        try: await msg.delete()
        except TelegramError: pass
        return
    # locks
    d=json.loads(g["locks"] or "{}") if g else {}
    mt=media_type(msg)
    if (mt and d.get(mt)) or (d.get("links") and URL_RE.search(text)):
        try: await msg.delete()
        except TelegramError: pass
        return
    # flood: N messages / 8 sec
    if g and g["antiflood"]:
        k=(chat.id,u.id); arr=[x for x in FLOOD_CACHE.get(k,[]) if now()-x<=8]; arr.append(now()); FLOOD_CACHE[k]=arr
        if len(arr)>g["flood_limit"]:
            try:
                await ctx.bot.restrict_chat_member(chat.id,u.id,ChatPermissions(can_send_messages=False),until_date=datetime.now(timezone.utc)+timedelta(minutes=1))
                await msg.reply_text(f"🌊 {u.first_name}: flood sabab 1 daqiqa mute.")
            except TelegramError: pass
            FLOOD_CACHE[k]=[]
            return
    # notes via #name
    if msg.text and msg.text.startswith("#"):
        name=msg.text[1:].split()[0].lower()
        r=one("SELECT text FROM notes WHERE chat_id=? AND name=?",(chat.id,name))
        if r: return await msg.reply_text(r["text"])
    # filters
    if text:
        for r in all_("SELECT key,response FROM filters_ WHERE chat_id=?",(chat.id,)):
            if r["key"] in text: return await msg.reply_text(r["response"])

async def new_members(update,ctx):
    g=one("SELECT welcome FROM groups WHERE chat_id=?",(update.effective_chat.id,))
    if g and g["welcome"]:
        names=", ".join(u.first_name for u in update.effective_message.new_chat_members)
        await update.effective_message.reply_text(f"👋 Xush kelibsiz, {names}!")

async def left_member(update,ctx):
    g=one("SELECT goodbye FROM groups WHERE chat_id=?",(update.effective_chat.id,))
    if g and g["goodbye"] and update.effective_message.left_chat_member:
        await update.effective_message.reply_text(f"👋 {update.effective_message.left_chat_member.first_name} guruhni tark etdi.")

async def callback(update,ctx):
    q=update.callback_query; await q.answer(); d=q.data; u=q.from_user; ensure_user(u)
    if d.startswith("topgift:") or d.startswith("topplain:"):
        if u.id not in SUPER_OWNERS:
            return await q.answer("Faqat Super Ega.",show_alert=True)
        chat_id=int(d.split(":",1)[1])
        with_gifts=d.startswith("topgift:")
        await q.edit_message_text("⏳ TOP-10 hisoblanmoqda..." if not with_gifts else "⏳ TOP-10 va TOP-3 Giftlar tayyorlanmoqda...")
        return await top10_result(ctx.bot,chat_id,with_gifts,u.id)
    if d=="me":
        r=one("SELECT wallet FROM users WHERE user_id=?",(u.id,))
        return await q.edit_message_text(f"👤 {u.full_name}\n🆔 {u.id}\n🎖 {title_for(u.id)}\n⭐ Kredit: {r['wallet'] if r else 0}")
    if d=="wallet":
        kb=[[InlineKeyboardButton(f"{x} ⭐",callback_data=f"top:{x}") for x in TOPUPS[i:i+3]] for i in range(0,len(TOPUPS),3)]
        return await q.edit_message_text(f"⭐ Kredit: {wallet(u.id)}\nTo‘ldirish:",reply_markup=InlineKeyboardMarkup(kb))
    if d.startswith("top:"):
        amount=int(d.split(":")[1])
        # send a new invoice; invoices cannot replace callback message
        fake=update
        return await ctx.bot.send_invoice(chat_id=u.id,title="Veritas Stars krediti",description=f"{amount} ⭐ kredit",payload=f"topup:{u.id}:{amount}:{now()}",currency="XTR",prices=[LabeledPrice("Stars",amount)])
    if d=="gifts":
        try:
            gs=await ctx.bot.get_available_gifts()
            prices=sorted({int(g.star_count) for g in gs.gifts})
            return await q.edit_message_text("🎁 Hozirgi Gift narxlari:\n"+", ".join(f"{p} ⭐" for p in prices[:50])+"\n\nGuruhda oluvchiga reply: *give <narx>")
        except Exception as e: return await q.edit_message_text(f"❌ {e}")
    if d=="premium": return await q.edit_message_text("💎 Premium: 3 oy — 1000 ⭐ | 6 oy — 1500 ⭐ | 12 oy — 2500 ⭐\nGuruhda reply: *premium 3")
    if d=="mygroups":
        rows=all_("SELECT chat_id,title FROM groups WHERE owner_id=? OR chat_id IN (SELECT chat_id FROM vadmins WHERE user_id=?)",(u.id,u.id))
        return await q.edit_message_text("🏘 "+("\n".join(f"{r['title']} ({r['chat_id']})" for r in rows) or "Guruh topilmadi."))
    if d=="library":
        rows=all_("SELECT title,author FROM books ORDER BY id DESC LIMIT 20")
        return await q.edit_message_text("📚 "+("\n".join(f"{r['title']} — {r['author']}" for r in rows) or "Kutubxona hozircha bo‘sh."))
    if d=="super":
        if u.id not in SUPER_OWNERS: return await q.edit_message_text("⛔ Ruxsat yo‘q.")
        uc=one("SELECT COUNT(*) n FROM users")["n"]; gc=one("SELECT COUNT(*) n FROM groups")["n"]
        return await q.edit_message_text(f"👑 SUPER EGA\nFoydalanuvchilar: {uc}\nGuruhlar: {gc}")

async def giveaway_job(ctx):
    rows=all_("SELECT * FROM giveaways WHERE status='open' AND end_at<=?",(now(),))
    for g in rows:
        entries=[r["user_id"] for r in all_("SELECT user_id FROM giveaway_entries WHERE giveaway_id=?",(g["id"],))]
        random.shuffle(entries); winners=entries[:min(g["winners"],len(entries))]
        execute("UPDATE giveaways SET status='closed' WHERE id=?",(g["id"],))
        if not winners:
            try: await ctx.bot.send_message(g["chat_id"],"🎉 Konkurs tugadi. Ishtirokchi yo‘q.")
            except TelegramError: pass
            continue
        # creator funds prizes; failures are reported, never silently faked
        sent=[]
        for uid in winners:
            price=int(g["prize"])
            try:
                gifts=await ctx.bot.get_available_gifts()
                cand=next((x for x in gifts.gifts if int(x.star_count)==price and (getattr(x,"remaining_count",None) is None or getattr(x,"remaining_count",0)>0)),None)
                if not cand or wallet(g["creator_id"])<price: continue
                if not wallet_change(g["creator_id"],-price,"giveaway_gift_pending",uid): continue
                try:
                    await ctx.bot.send_gift(user_id=uid,gift_id=cand.id,text="🏆 Veritas Giveaway sovrini")
                    sent.append(uid)
                except Exception:
                    wallet_change(g["creator_id"],price,"giveaway_rollback",uid)
            except Exception: pass
        try: await ctx.bot.send_message(g["chat_id"],"🏆 G‘oliblar: "+", ".join(str(x) for x in winners)+("\n🎁 Gift yuborildi: "+", ".join(str(x) for x in sent) if sent else "\n⚠️ Gift yuborish uchun yaratuvchi krediti/Gift mavjudligini tekshiring."))
        except TelegramError: pass

async def error_handler(update,ctx):
    log.exception("Handler error",exc_info=ctx.error)

def main():
    if not TOKEN: raise RuntimeError("BOT_TOKEN kiritilmagan.")
    init_db()
    app=Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start",start))
    app.add_handler(CommandHandler("help",cmd_help))
    app.add_handler(CommandHandler("id",cmd_id))
    app.add_handler(CommandHandler("super",cmd_super))
    app.add_handler(PreCheckoutQueryHandler(precheckout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT,paid))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS,new_members))
    app.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER,left_member))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r"^\*"),star_text_router),group=0)
    app.add_handler(MessageHandler(filters.ALL & ~filters.StatusUpdate.ALL & ~filters.SUCCESSFUL_PAYMENT,passive),group=1)
    if app.job_queue: app.job_queue.run_repeating(giveaway_job,60,first=10)
    app.add_error_handler(error_handler)
    log.info("VERITAS v7 starting")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__=="__main__":
    main()
