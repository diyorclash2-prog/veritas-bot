"""Opt-in group adapter for existing Veritas-X bot (python-telegram-bot 22.x).
Does NOT start another bot or create a polling conflict. Import register_games_handlers
from this file in the existing bot and call it once before app.run_polling().
"""
import asyncio
import json
import os
import urllib.request
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatMemberStatus
from telegram.ext import CommandHandler, MessageHandler, ApplicationHandlerStop, filters

BASE=os.environ.get('GAMES_SERVER_URL','').rstrip('/')
SECRET=os.environ.get('GAMES_BRIDGE_SECRET','')
GAME_NAMES={
    'word':'🔤 So‘z yasash','math':'⚡ Tezkor hisob',
    'puzzle':'🔢 15-talik','sudoku':'🧩 Sudoku',
    'memory':'🧠 Xotira','sequence':'🔗 Sonlar zanjiri',
    'code':'🐂 Buqa va sigir','merge':'🟨 2048',
    'ladder':'🏆 Zakovat zinapoyasi'
}


def _bridge(route,payload):
    if not BASE.startswith('https://') or not SECRET:
        raise RuntimeError('GAMES_SERVER_URL (HTTPS) va GAMES_BRIDGE_SECRET sozlanmagan.')
    req=urllib.request.Request(BASE+route,data=json.dumps(payload,ensure_ascii=False).encode(),
          headers={'Content-Type':'application/json','X-Games-Bridge-Secret':SECRET},method='POST')
    with urllib.request.urlopen(req,timeout=10) as response:
        data=json.loads(response.read(25000))
    if data.get('error'):raise ValueError(data['error'])
    return data

async def games_command(update,ctx):
    msg=update.effective_message; chat=update.effective_chat; user=update.effective_user
    if not msg or not chat or not user:return
    content=(msg.text or '').strip()
    # Commands: /games, *games, /game math, *game math, /gamescore CODE
    cmd,_,rest=content.partition(' ')
    key=cmd.split('@')[0].lstrip('/*').lower()
    rest=rest.strip()
    if chat.type=='private':
        if key in ('games','oyinlar','o‘yinlar') and not rest:
            bot_info=await ctx.bot.get_me()
            username=getattr(bot_info,'username',None)
            if not username:
                return await msg.reply_text('⚠️ Telegram bot username topilmadi.')
            url=f'https://t.me/{username}?startapp'
            return await msg.reply_text(
                '🎮 VERITAS GAMES\n\n9 ta o‘yin, haftalik reyting, kunlik sovg‘a va Veritas AI.\n'
                'Mini Appni quyidagi tugma orqali oching:',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🎮 Veritas Games’ni ochish',url=url)]]))
        return await msg.reply_text('🎮 Guruhda o‘yin ochish: *games yoki *game math.\n'
                                    'Shaxsiy chatda o‘yinlarni ochish: /games')
    if chat.type not in ('group','supergroup'): return
    if key in ('games','oyinlar','o‘yinlar') and not rest:
        lines='\n'.join('• '+name+' — `*game '+game+'`' for game,name in GAME_NAMES.items())
        return await msg.reply_text('🎮 VERITAS GAMES\n\n'+lines+'\n\n'+
          'Guruh administratori `*game math` deb xona ochadi. Ishtirokchilar tugma orqali kiradi.', parse_mode='Markdown')
    if key=='gamescore':
        code=rest[:24]
        if not code: return await msg.reply_text('Misol: *gamescore AB12CDEF')
        try:
            result=await asyncio.to_thread(_bridge,'/api/bridge/room_scores',{'code':code})
            if int(result.get('chat_id') or 0)!=chat.id:
                return await msg.reply_text('Bu xona boshqa guruhga tegishli.')
            scores=result['scores'];names='\n'.join(f"{i}. {p['name']} — {p['score']} ball" for i,p in enumerate(scores,1)) or 'Hali natija yo‘q.'
            return await msg.reply_text('🏆 XONA NATIJALARI\n\n'+names+'\n🎮 '+result['game'])
        except Exception as e:return await msg.reply_text('⚠️ '+str(e)[:200])
    if key not in ('game','oyin','o‘yin'):return
    game=rest.lower().strip()
    if game not in GAME_NAMES:
        return await msg.reply_text('O‘yin nomi noto‘g‘ri. `*games` ro‘yxatini oching.',parse_mode='Markdown')
    member=await ctx.bot.get_chat_member(chat.id,user.id)
    if member.status not in (ChatMemberStatus.OWNER,ChatMemberStatus.ADMINISTRATOR):
        return await msg.reply_text('🛡 Guruhda yangi o‘yin xonasini faqat administrator ochadi.')
    try:
        r=await asyncio.to_thread(_bridge,'/api/bridge/room_create',
             {'game':game,'chat_id':chat.id,'chat_title':chat.title or 'Guruh', 'created_by':user.id})
        url=r['url']
        if not url.startswith('https://'):raise ValueError('BOT_USERNAME yoki APP_PUBLIC_URL sozlanmagan.')
        return await msg.reply_text(
          f'🎮 VERITAS GAMES — GURUH BELLASHUVI\n\n{GAME_NAMES[game]}\n'
          '👥 50 nafargacha o‘yinchi • 2 soat faol\n🏆 Har kimning natijasi guruhga qaytadi.\n'
          f'🔑 Xona: {r["code"]}\n📊 Natija: *gamescore {r["code"]}\n\n'
          '👇 Tugmani bosib o‘yinni oching:',
          reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🎮 O‘yinga kirish',url=url)]]))
    except Exception as e:
        return await msg.reply_text('⚠️ Veritas Games xonasini ochib bo‘lmadi: '+str(e)[:200])


async def games_entry(update,ctx):
    await games_command(update,ctx)
    raise ApplicationHandlerStop()


def register_games_handlers(application):
    """Call only once, before run_polling(). Does not change any existing handlers."""
    pattern=r'^\*(?:games|game|gamescore|oyinlar|oyin|o‘yin|o‘yinlar)(?:\s|$)'
    application.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.TEXT & filters.Regex(pattern),games_entry),group=-24)
    application.add_handler(CommandHandler('games',games_entry),group=-24)
    application.add_handler(CommandHandler('game',games_entry),group=-24)
    application.add_handler(CommandHandler('gamescore',games_entry),group=-24)
