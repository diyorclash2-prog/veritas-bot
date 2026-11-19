"""A button catalogue on top of the bot's existing, permission-checked commands."""
import logging
import secrets
import time

from telegram import (BotCommand, BotCommandScopeAllGroupChats, BotCommandScopeAllPrivateChats,
                      ForceReply, InlineKeyboardButton as Button, InlineKeyboardMarkup as Markup)
from telegram.error import TelegramError
from telegram.ext import ApplicationHandlerStop, CallbackQueryHandler, CommandHandler, MessageHandler, filters

from veritas_games_bridge import GAME_NAMES, games_command

SECTIONS = {
 'account': ('👤 Kabinet', 'men Profilim|id Telegram ID|ak Faollik reytingi|qadr Qadr reytingi|top O‘ntalik|sayt Saytga kirish|balans Tangalarim|tanga Tanga hisobi|topup Stars olish|help Yordam|start Bosh menyu|cancel Bekor qilish|paysupport To‘lov bo‘yicha yordam'),
 'learn': ('📚 Ta’lim', 'lingua Til o‘rganish|hadis Hadis izlash|kitobai Kitobga savol|avtokitob Avtokutubxona|add.hadis Hadis qo‘shish|del.hadis Hadisni o‘chirish|bookadmins Kitob boshqaruvchilari|hadisadmins Hadis boshqaruvchilari'),
 'play': ('🎮 O‘yinlar', 'games O‘yinlar|game Xona ochish|gamescore Xona natijasi|zakovat Zakovat boshlash|znatija Zakovat natijasi|zdavom Davom ettirish|zball Ball berish|zsertifikat Sertifikat|zstop O‘yinni yakunlash|rebus Rebus|giveaway Sovrinli tanlov|join Tanlovga kirish'),
 'ai': ('🪶 Veritas AI', 'ai AI kabineti|aiyordam AI yordami|aisuhbat Tabiiy suhbat|aixotira Guruh xotirasi|aizakovat O‘yin takliflari|sticker_status Stiker holati|sticker_mode Stiker faolligi|sticker_on Stikerni yoqish|sticker_off Stikerni o‘chirish|sticker_test Stikerni sinash|reaction_on Reaksiyani yoqish|reaction_off Reaksiyani o‘chirish|standards Guruh odobi'),
 'group': ('👥 Guruh', 'rules Qoidalar|admins Adminlar|aktiv Faol a’zolar|warns Ogohlantirishlar|report Shikoyat|notes Qaydlar|get Qaydni ochish|filters Javoblar|approved Ruxsatli a’zolar|blacklists Taqiqlangan so‘zlar|locks Cheklovlar|vse O‘z xabarlarimni tozalash|lang Guruh tili|unvon Unvon berish|unvonoff Unvonni olish'),
 'manage': ('🛡 Moderatsiya', 'warn Ogohlantirish|unwarn Ogohlantirishni olish|clearwarns Ogohlantirishlarni tozalash|mute Yozishni cheklash|unmute Yozishga ruxsat|ban Bloklash|unban Blokdan olish|kick Chiqarish|tempmute Vaqtincha cheklash|tempban Vaqtincha bloklash|del Xabarni o‘chirish|purge Xabarlarni tozalash|pin Biriktirish|unpin Biriktirishni olish|admin Admin tayinlash|unadmin Adminlikni olish|approve Istisno qo‘shish|unapprove Istisnoni olish|ruxsat Ruxsat berish|ruxsatsiz Ruxsatni olish|modlog Amallar jurnali'),
 'settings': ('⚙️ Sozlamalar', 'setrules Qoidalarni yozish|links Havola himoyasi|antiflood Xabar oqimi himoyasi|flood Xabar limiti|antirepeat Takroriy xabarlar|reports Shikoyatlar|welcome Kutib olish|goodbye Kuzatish|setwelcome Salomlashuv matni|setgoodbye Xayrlashuv matni|cleanservice Xizmat xabarlari|warnlimit Ogohlantirish limiti|warnaction Jazo turi|raid Reyd himoyasi|lock Turini cheklash|unlock Cheklovni olish|lockall Barchasini cheklash|unlockall Cheklovlarni ochish|blacklist So‘zni taqiqlash|unblacklist Taqiqni olish|save Qayd yozish|clear Qaydni o‘chirish|filter Avtojavob qo‘shish|stop Avtojavobni olish|stopall Javoblarni tozalash'),
 'gifts': ('🎁 Sovg‘alar', 'give Telegram sovg‘asi|premium Premium sovg‘asi|ai.p Shaxsiy AI sovg‘asi|stars Stars oynasi|bayram Bayram tabrigi|poster Poster|mazgila Mazgila'),
 'owner': ('👑 Boshqaruv', 'super Ega kabineti|super_settings Super sozlama|superadmins Boshqaruvchilar|superadmin Super admin qo‘shish|unsuperadmin Super adminni olish|ad.book Kitob admini berish|unad.book Kitob adminini olish|ad.hadis Hadis admini berish|unad.hadis Hadis adminini olish|post Umumiy xabarnoma|lingua_ads Lingua e’lonlari'),
}
ITEMS={}; CATEGORIES={}
for key, (title,entries) in SECTIONS.items():
    CATEGORIES[key]=[]
    for entry in entries.split('|'):
        cmd,label=entry.split(' ',1)
        ITEMS[cmd]=label
        CATEGORIES[key].append(cmd)

V11=set('aiyordam aisuhbat aixotira aizakovat kitobai zakovat znatija zdavom zball zsertifikat zstop'.split())
PRIVATE=set('sayt balans tanga topup paysupport super_settings lingua_ads'.split())
GROUP=set(CATEGORIES['group']+CATEGORIES['manage']+CATEGORIES['settings']+'game gamescore aisuhbat aizakovat zakovat znatija zdavom zball zsertifikat zstop join giveaway give premium'.split())
TARGET=set('warn unwarn clearwarns mute unmute ban unban kick tempmute tempban del purge pin approve unapprove admin unadmin ruxsat ruxsatsiz report give premium ai.p stars unvon unvonoff superadmin unsuperadmin ad.book unad.book ad.hadis unad.hadis zball'.split())
CONFIRM=TARGET | set('post stopall clear lockall unlockall zstop vse del.hadis giveaway'.split())
OPTIONS={
 'top':['10'], 'topup':['25','50','100','250','500','1000','2500'],'premium':['3','6','12'],
 'sticker_mode':['calm','normal','active'],'sticker_test':['1','2','3'],
 'aixotira':['on','off','clear'], 'avtokitob':['status','run'],'game':list(GAME_NAMES),
 'zakovat':['5','10','30'], 'warnlimit':['2','3','5'], 'warnaction':['ban','kick','mute'],
 'give':['50','100'], 'stars':['50','100'],'flood':['3','5','10'],
 'lock':'photo video sticker animation document voice audio links'.split(),
 'unlock':'photo video sticker animation document voice audio links'.split(),
 'tempmute':['10m','1h','1d'],'tempban':['1h','1d','7d'],
}
for cmd in 'aisuhbat aizakovat links antiflood antirepeat reports welcome goodbye cleanservice raid'.split():
    OPTIONS[cmd]=['on','off']
PROMPTS={'gamescore':'Xona kodini', 'setrules':'Yangi qoidalarni','setwelcome':'Kutib olish matnini',
 'setgoodbye':'Xayrlashuv matnini','unvon':'Unvonni','get':'Qayd nomini','save':'Nom va matnni',
 'clear':'Qayd nomini','filter':'Kalit so‘z va javobni','stop':'Kalit so‘zni','blacklist':'Taqiqlanadigan so‘zni',
 'unblacklist':'Ruxsat beriladigan so‘zni','kitobai':'Kitob ID raqami va savolni','post':'Xabarnoma matnini',
 'giveaway':'Sovrin, daqiqa va g‘oliblar sonini (masalan, gift 50 30 1)','hadis':'Hadis raqami yoki izlanadigan so‘zni',
 'poster':'Poster mavzusini','mazgila':'Sozlama yoki matnni','lingua_ads':'E’lon amalini (status, on yoki off)',
 'del.hadis':'Hadis raqamini'}
RULES='🛡 Guruh odobi\n\nSo‘kinish, ochiq +18 kontent, chekish va spirtli ichimlik tasvirlariga birinchi safar ogohlantirish beriladi. Takrorlansa, a’zo shu guruhda bloklanadi.'
PANEL='🧭 Veritas buyruqlari\n\nKerakli bo‘limni tanlang.'
LABEL={'on':'Yoqish','off':'O‘chirish','clear':'Xotirani tozalash','status':'Holat','run':'Hozir izlash','normal':'Odatiy','calm':'Sokin','active':'Faol'}


def grid(buttons):
    return [buttons[i:i+2] for i in range(0,len(buttons),2)]


def home_markup():
    return Markup(grid([Button(title,callback_data='panel:s:'+key) for key,(title,_) in SECTIONS.items()]))


def action_keyboard(rows):
    return Markup(rows+[[Button('🧭 Bo‘limlar',callback_data='panel:home')]])


async def publish_commands(app):
    base=[('menu','Buyruqlarni tugmalar bilan ochish'),('start','Bosh menyu'),('help','Yordam'),
          ('ai','Veritas AI'),('games','O‘yinlar'),('lingua','Til o‘rganish')]
    for scope,commands in [(None,base),(BotCommandScopeAllPrivateChats(), base+[('balans','Tangalarim'),('sayt','Saytga kirish'),('paysupport','Stars bo‘yicha yordam')]),
                           (BotCommandScopeAllGroupChats(),base+[('zakovat','Zakovatni boshlash'),('qoidalar','Guruh odobi')])]:
        try:
            await app.bot.set_my_commands([BotCommand(k,v) for k,v in commands],scope=scope)
        except TelegramError as exc:
            logging.getLogger(__name__).warning('Telegram command menu registration failed: %s',type(exc).__name__)


def register(app, ns):
    def cache(ctx):
        data=ctx.user_data.setdefault('command_panel',{})
        for key in list(data):
            if data[key]['expires'] < time.monotonic():
                data.pop(key)
        return data

    async def execute(update,ctx,cmd,args,source,target=None):
        # Reuse authorization and workflows. Telegram's callback message is authored by the bot;
        # use the actual clicker as actor and only the real, selected message as the target.
        actor=update.effective_user
        text='*'+cmd+(' '+args if args else '')
        msg=ns['V12View'](source,text=text,from_user=actor,reply_to_message=target,sender_chat=None)
        view=ns['V12View'](update,message=msg,effective_message=msg,callback_query=None)
        ns['ensure_user'](actor)
        if msg.chat.type!='private':
            ns['ensure_group'](msg.chat)
        ctx.args=args.split()
        if cmd=='standards': return await msg.reply_text(RULES)
        if cmd=='ai' and msg.chat.type=='private':
            return await msg.reply_text('🪶 Shaxsiy Veritas AI',reply_markup=Markup([[Button('AI kabineti',callback_data='ai_private')]]))
        if cmd in ('start','cancel'): return await ns['v9_start_selector'](view,ctx)
        if cmd=='paysupport':
            return await msg.reply_text('Stars bo‘yicha savol yoki to‘lov raqamini egaga yuboring.',reply_markup=Markup([[Button('📨 Egaga yozish',callback_data='owner:message')]]))
        if cmd in ('sayt','tanga','balans'):
            shared=ctx.application.bot_data['veritas_lingua_learning'].shared
            return await (shared.website if cmd=='sayt' else shared.wallet)(view,ctx)
        if cmd in ('games','game','gamescore'):return await games_command(view,ctx)
        if cmd in V11:return await ns['v11_commands'](view,ctx)
        if cmd.startswith(('sticker_','reaction_')):return await ns['greenlezard_command'](view,ctx)
        if cmd=='rebus':
            if msg.chat.type=='private':
                return await msg.reply_text('🧩 Rebus',reply_markup=Markup([[Button('Rebusni ochish',callback_data='rebus:start')]]))
            return await ns['_start_group_rebus_flow'](view,ctx)
        if cmd=='vse':return await ns['vse_self_clean'](view,ctx)
        if cmd=='super':return await ns['cmd_super'](view,ctx)
        if cmd in ('lingua','lingua_ads','super_settings'):
            # The real slash handler already locates services and checks its owner rights.
            for handlers in ctx.application.handlers.values():
                for handler in handlers:
                    if isinstance(handler,CommandHandler) and cmd in handler.commands:
                        return await handler.callback(view,ctx)
        return await ns['star_text_router'](view,ctx)

    async def open_panel(update,ctx):
        src=update.effective_message
        if src.chat.type=='private':
            from bot_navigation import cancel_input
            cancel_input(ctx,update.effective_user.id,ns['STATE'])
        cache(ctx).pop('flow',None)
        m=await src.reply_text(PANEL,reply_markup=home_markup())
        cache(ctx)['anchor']={'id':m.message_id,'target':src.reply_to_message,'chat':src.chat_id,'expires':time.monotonic()+600}
        raise ApplicationHandlerStop

    async def shortcut(update,ctx):
        src=update.effective_message
        cmd=src.text.split()[0].split('@')[0][1:]
        await execute(update,ctx,{'qoidalar':'standards'}.get(cmd,cmd),' '.join(ctx.args or []),src,src.reply_to_message)
        raise ApplicationHandlerStop

    async def click(update,ctx):
        q=update.callback_query
        await q.answer()
        src=q.message
        if not src: raise ApplicationHandlerStop
        private=src.chat.type=='private'
        data=cache(ctx)
        parts=q.data.split(':')
        async def show(text,kb): await q.edit_message_text(text,reply_markup=kb)
        if parts[1]=='home':
            data.pop('flow',None)
            await show(PANEL,home_markup())
        elif parts[1]=='s' and parts[2] in CATEGORIES:
            key=parts[2]
            if key=='owner' and not ns['is_super'](update.effective_user.id):
                await src.reply_text('Bu bo‘lim loyiha boshqaruvchilari uchun.')
                raise ApplicationHandlerStop
            entries=[Button(ITEMS[c],callback_data='panel:c:'+c) for c in CATEGORIES[key] if c not in (GROUP if private else PRIVATE)]
            await show(SECTIONS[key][0] if entries else 'Bu bo‘limni guruhda oching.',action_keyboard(grid(entries)))
        elif parts[1]=='c' and parts[2] in ITEMS:
            cmd=parts[2]
            if cmd in (GROUP if private else PRIVATE):
                await src.reply_text('Bu amalni '+('guruhda' if private else 'shaxsiy chatda')+' oching.')
                raise ApplicationHandlerStop
            anchor=data.get('anchor',{})
            target=anchor.get('target') if (anchor.get('chat'),anchor.get('id'))==(src.chat_id,src.message_id) else None
            if cmd in TARGET and not target:
                await src.reply_text('Kerakli a’zoning xabariga javob berish rejimini oching. Menyudan /menu ni tanlab, shu amalni bosing.')
                raise ApplicationHandlerStop
            if cmd in ('rebus','vse') and not private and not target:
                target=src  # These two legacy routes explicitly require a reply to Veritas itself.
            token=secrets.token_hex(5)
            flow={'token':token,'cmd':cmd,'target':target,'chat':src.chat_id,'expires':time.monotonic()+300,'args':''}
            data['flow']=flow
            if cmd in OPTIONS:
                buttons=[Button(GAME_NAMES.get(v,LABEL.get(v,v)) if cmd=='game' else LABEL.get(v,v),callback_data=f'panel:o:{token}:{i}') for i,v in enumerate(OPTIONS[cmd])]
                if cmd not in ('top','game','premium','topup'):
                    buttons.append(Button('✏️ Boshqa qiymat',callback_data=f'panel:i:{token}'))
                await src.reply_text(ITEMS[cmd],reply_markup=action_keyboard(grid(buttons)))
            elif cmd in PROMPTS:
                await ask(src,flow)
            else:
                await finish(update,ctx,src,flow)
        elif parts[1] in ('o','i','yes'):
            flow=data.get('flow',{})
            if flow.get('token')!=parts[2] or flow.get('chat')!=src.chat_id:
                await src.reply_text('Bu tanlov eskirgan yoki boshqa a’zoga tegishli. Menyuni qayta oching.')
            elif parts[1]=='i':
                await ask(src,flow)
            elif parts[1]=='o' and parts[-1].isdigit() and int(parts[-1])<len(OPTIONS.get(flow['cmd'],())):
                flow['args']=OPTIONS[flow['cmd']][int(parts[-1])]
                await finish(update,ctx,src,flow)
            elif parts[1]=='yes' and flow.get('confirm')==src.message_id:
                data.pop('flow',None)
                await execute(update,ctx,flow['cmd'],flow['args'],src,flow['target'])
        raise ApplicationHandlerStop

    async def ask(src,flow):
        prompt=PROMPTS.get(flow['cmd'],'Qiymatni')
        sent=await src.reply_text(prompt+' javob qilib yuboring.',reply_markup=ForceReply())
        flow['prompt']=sent.message_id

    async def finish(update,ctx,src,flow):
        cmd=flow['cmd']
        if cmd in CONFIRM:
            who=getattr(getattr(flow['target'],'from_user',None),'full_name','')
            sent=await src.reply_text('Tasdiqlaysizmi?\n'+' · '.join(filter(None,[ITEMS[cmd],who,flow['args'][:180]])),
                                      reply_markup=action_keyboard([[Button('Tasdiqlash',callback_data='panel:yes:'+flow['token'])]]))
            flow['confirm']=sent.message_id
        else:
            cache(ctx).pop('flow',None)
            await execute(update,ctx,cmd,flow['args'],src,flow['target'])

    async def input_value(update,ctx):
        src=update.effective_message
        if not update.effective_user or not src.reply_to_message: return
        flow=cache(ctx).get('flow')
        if not flow or flow.get('chat')!=src.chat_id or flow.get('prompt')!=src.reply_to_message.message_id: return
        if src.text.startswith(('/','*')): return
        flow.pop('prompt',None);flow['args']=src.text.strip()[:1400]
        await finish(update,ctx,src,flow)
        raise ApplicationHandlerStop

    app.add_handler(CommandHandler('menu',open_panel),group=-405)
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex('^🧭 Buyruqlar$'),open_panel),group=-405)
    app.add_handler(CommandHandler(['ai','zakovat','qoidalar','paysupport'],shortcut),group=-405)
    app.add_handler(CallbackQueryHandler(click,pattern='^panel:'),group=-405)
    app.add_handler(MessageHandler(filters.TEXT & filters.REPLY,input_value),group=-404)
