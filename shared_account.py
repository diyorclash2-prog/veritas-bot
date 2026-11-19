"""One Telegram identity and one Games coin balance for the three Veritas apps."""
import asyncio
import base64
import logging
import os
import re
import time

import httpx
from telegram import (CopyTextButton, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton,
                      ReplyKeyboardMarkup, ReplyKeyboardRemove, WebAppInfo)
from telegram.error import TelegramError
from telegram.ext import ApplicationHandlerStop, CallbackQueryHandler, CommandHandler, MessageHandler, filters

LOG = logging.getLogger(__name__)


def site_invite(bot, *, private=False, site=None):
    url = site or os.getenv('VL_PUBLIC_URL') or 'https://veritas-lingua-ai-production.up.railway.app'
    if private:
        button = InlineKeyboardButton('🌐 Veritas saytiga kirish', web_app=WebAppInfo(url))
    else:
        username = getattr(bot, 'username', None) or 'Veritas71_Bot'
        button = InlineKeyboardButton('🌐 Veritas saytiga kirish', url=f'https://t.me/{username}?start=lingua_login')
    return InlineKeyboardMarkup([[button]])


class SharedAccount:
    def __init__(self, store):
        self.store = store
        self.site = os.environ['VL_PUBLIC_URL'].rstrip('/')
        self.games = os.environ['GAMES_SERVER_URL'].rstrip('/')
        self.account_key = os.environ['VERITAS_ACCOUNT_KEY']
        self.wallet_key = os.environ['VERITAS_BOT_WALLET_KEY']
        if not self.site.startswith('https://') or not self.games.startswith('https://'):
            raise ValueError('Veritas requires HTTPS service URLs')
        with store.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS tg_shared_receipts(uid INTEGER PRIMARY KEY, credited INTEGER NOT NULL)')

    async def balance(self, uid, name='', username=''):
        with self.store.db() as db:
            earned = db.execute('SELECT COALESCE(SUM(coins),0) FROM tg_lingua_profiles WHERE uid=?',(uid,)).fetchone()[0]
        try:
            async with httpx.AsyncClient(timeout=5,trust_env=False) as client:
                response = await client.post(self.games+'/api/bot/wallet',
                    headers={'X-Veritas-Bot-Key':self.wallet_key},
                    json={'telegram_id':uid,'earned':earned,'name':name,'username':username})
                response.raise_for_status()
                data = response.json()
                if type(data.get('coins')) != int or type(data.get('credited')) != int or data['credited'] < earned:
                    raise ValueError('Incomplete wallet reply')
        except (httpx.HTTPError, ValueError):
            return None
        with self.store.db() as db:
            db.execute('''INSERT INTO tg_shared_receipts VALUES(?,?) ON CONFLICT(uid)
                DO UPDATE SET credited=MAX(excluded.credited,credited)''',(uid,data['credited']))
        return data['coins']

    async def summary(self, user):
        amount = await self.balance(user.id,user.full_name,user.username or '')
        return f'🪙 Umumiy balans: {amount} tanga' if amount is not None else '🪙 Balans yangilanmoqda.'

    async def retry(self, context):
        with self.store.db() as db:
            ids = [r[0] for r in db.execute('''SELECT p.uid FROM tg_lingua_profiles p
                LEFT JOIN tg_shared_receipts r ON r.uid=p.uid GROUP BY p.uid
                HAVING SUM(p.coins)>COALESCE(MAX(r.credited),0) ORDER BY p.uid LIMIT 100''')]
        for start in range(0,len(ids),5):
            await asyncio.gather(*(self.balance(uid) for uid in ids[start:start+5]))

    async def wallet(self, update, context):
        await update.effective_message.reply_text(await self.summary(update.effective_user))
        raise ApplicationHandlerStop

    async def launch_games(self, update, context):
        await update.effective_message.reply_text('🎮 Veritas Mini Games',reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton('O‘ynash',web_app=WebAppInfo(self.games))]]))
        raise ApplicationHandlerStop

    async def website(self, update, context):
        if update.callback_query:
            await update.callback_query.answer()
        private = update.effective_chat.type == 'private'
        await update.effective_message.reply_text(
            'Veritas saytiga xush kelibsiz!',
            reply_markup=site_invite(context.bot, private=private, site=self.site))
        raise ApplicationHandlerStop

    async def browser_code(self, update, context, phone=''):
        user = update.effective_user
        if update.callback_query:
            await update.callback_query.answer()
        if update.effective_chat.type != 'private' or update.effective_chat.id != user.id:
            raise ApplicationHandlerStop
        data = {'telegram_id':user.id,'name':user.full_name,'username':user.username or '', 'phone':phone}
        try:
            photos = await context.bot.get_user_profile_photos(user.id,limit=1)
            if photos.photos:
                img = photos.photos[0][0]
                if img.file_size and img.file_size < 130000:
                    file = await context.bot.get_file(img.file_id)
                    raw = await file.download_as_bytearray()
                    if len(raw)<130000 and raw[:2]==b'\xff\xd8':
                        data['avatar']='data:image/jpeg;base64,'+base64.b64encode(raw).decode()
        except (TelegramError,OSError):
            pass
        try:
            async with httpx.AsyncClient(timeout=7,trust_env=False) as client:
                resp = await client.post(self.site+'/api/auth/telegram/bot/issue', json=data,
                                         headers={'X-Veritas-Account-Key':self.account_key})
            if resp.status_code == 400 and resp.json().get('detail') == 'phone':
                context.user_data['veritas_own_contact_until'] = time.time()+300
                await update.effective_message.reply_text(
                    'Mavjud Lingua profilingizni topish yoki yangisini ochish uchun o‘z raqamingizni bir marta tasdiqlang.',
                    reply_markup=ReplyKeyboardMarkup([[KeyboardButton('📱 O‘z raqamimni tasdiqlash',request_contact=True)]],
                                                     resize_keyboard=True,one_time_keyboard=True))
                raise ApplicationHandlerStop
            resp.raise_for_status()
            code = resp.json()['code']
        except (httpx.HTTPError,ValueError,KeyError):
            await update.effective_message.reply_text('Saytga ulanish hozir amalga oshmadi. /sayt orqali qayta urinib ko‘ring.')
            raise ApplicationHandlerStop
        context.user_data.pop('veritas_own_contact_until',None)
        if phone:
            await update.effective_message.reply_text('✅ Raqamingiz tasdiqlandi.',reply_markup=ReplyKeyboardRemove())
        grouped = '-'.join(code[start:start + 4] for start in range(0, len(code), 4))
        await context.bot.send_message(
            update.effective_chat.id,
            f'Lingua saytiga kirish kodi (5 daqiqa)\n{grouped}',
            _skip_i18n=True, protect_content=True,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton('🌍 Telegram orqali avtomatik kirish', web_app=WebAppInfo(self.site))],
                [InlineKeyboardButton('Kodni nusxalash', copy_text=CopyTextButton(code)),
                 InlineKeyboardButton('Kodni .txt saqlash', callback_data='veritas_login_save')],
                [InlineKeyboardButton('Brauzerda ochish', url=self.site)],
                [InlineKeyboardButton('🎮 Mini Games', web_app=WebAppInfo(self.games))],
            ]),
        )
        raise ApplicationHandlerStop

    async def save_login_code(self, update, context):
        query = update.callback_query
        msg = query.message
        if (not msg or update.effective_chat.type != 'private'
                or update.effective_chat.id != query.from_user.id
                or getattr(getattr(msg, 'from_user', None), 'id', None) != context.bot.id
                or getattr(msg, 'forward_origin', None)):
            await query.answer('Kodni bot bilan shaxsiy chatda oching.', show_alert=True)
            raise ApplicationHandlerStop
        match = re.fullmatch(r'Lingua saytiga kirish kodi \(5 daqiqa\)\n([A-Z2-9]{4}(?:-[A-Z2-9]{4}){2,3})',
                             msg.text or '')
        if not match or not 0 <= time.time() - msg.date.timestamp() < 300:
            await query.answer('Yangi kod uchun /sayt tugmasini bosing.', show_alert=True)
            raise ApplicationHandlerStop
        await query.answer()
        code = match.group(1).replace('-', '')
        await context.bot.send_document(
            msg.chat_id, document=(code + '\n').encode('ascii'),
            filename='veritas-kirish-kodi.txt', _skip_i18n=True,
            caption='Shaxsiy kirish kodi. Muddati birinchi xabardan boshlab 5 daqiqa.',
        )
        raise ApplicationHandlerStop

    async def contact(self, update, context):
        if context.user_data.get('veritas_own_contact_until',0)<time.time():
            return
        msg = update.effective_message
        if msg.contact.user_id != update.effective_user.id or msg.forward_origin:
            await msg.reply_text('Tugma orqali o‘z raqamingizni yuboring.')
            raise ApplicationHandlerStop
        await self.browser_code(update,context,msg.contact.phone_number)

    def register(self, app):
        private = filters.ChatType.PRIVATE
        app.add_handler(CommandHandler('start',self.website,filters=private & filters.Regex(r'^/start(?:@\w+)?\s+lingua_login$')),group=-401)
        app.add_handler(CommandHandler('start',self.launch_games,filters=private & filters.Regex(r'^/start(?:@\w+)?\s+veritas_games$')),group=-401)
        app.add_handler(CommandHandler('start',self.browser_code,filters=private & filters.Regex(r'^/start(?:@\w+)?\s+lingua_code$')),group=-401)
        app.add_handler(CommandHandler('sayt',self.website),group=-401)
        app.add_handler(CommandHandler(['tanga','balans'],self.wallet,filters=private),group=-401)
        app.add_handler(MessageHandler(private & filters.CONTACT,self.contact),group=-401)
        app.add_handler(CallbackQueryHandler(self.save_login_code,pattern=r'^veritas_login_save$'),group=-401)
        app.add_handler(CallbackQueryHandler(self.website,pattern=r'^veritas_site$'),group=-401)
        if app.job_queue:
            app.job_queue.run_repeating(self.retry,interval=30,first=3,name='shared-coins',
                                        job_kwargs={'max_instances':1,'coalesce':True})
