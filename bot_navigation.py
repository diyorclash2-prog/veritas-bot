"""Single private navigation path, including keyboards from older releases."""
import re
from telegram import InlineKeyboardButton as Button, InlineKeyboardMarkup as Markup
from telegram.ext import (ApplicationHandlerStop, CallbackQueryHandler, CommandHandler,
                          MessageHandler, filters)

KEYS = {
    '🛡 Veritas': 'home', '🎓 O‘quv • Talaba': 'school',
    '📝 Test': 'tests', '❓ Savol-javob': 'qa', '❓ Savol-javoblar': 'qa',
    '🧩 Rebus': 'rebus', '📣 Avtopost': 'post', '📢 Avtopost': 'post',
    '❓ V10 Yordam': 'help', '🌍 Til o‘rganish': 'lingua',
    '🌍 VERITAS LINGUA': 'lingua', '🏠 Bosh menyu': 'home',
    '❌ Bekor qilish': 'home', '❌ Отмена': 'home', '❌ Cancel': 'home',
}
MENUS = {'home', 'root:choose', 'root:v8', 'root:v9', 'library', 'hadith',
         'ai_private', 'help:home', 'rebus:start', 'v9:home',
         'v9:teacher:home', 'v9:student:home', 'nav:tests', 'nav:qa', 'lingua:home'}


def cancel_input(context, uid, state):
    state.pop(uid, None)
    bridge = context.application.bot_data.get('veritas_super_settings_v1')
    if bridge:
        bridge.chat.close(uid)
        bridge.reports.cancel(uid)
    context.user_data.pop('lingua_setup', None)
    context.user_data.pop('lingua_waiting', None)


def section(kind):
    if kind == 'tests':
        return ('📝 TESTLAR\n\nDars yoki kitob asosida testni tanlang. Til mashqlari ham shu yerdan ochiladi.', Markup([
            [Button('🎓 Darslar va testlar', callback_data='root:v9')],
            [Button('📚 Kitobdan test', callback_data='library')],
            [Button('🌍 Til mashqlari', callback_data='lingua:home')],
            [Button('⬅️ Bosh menyu', callback_data='home')]]))
    return ('❓ SAVOL-JAVOB\n\nAIga savol bering yoki guruhdagi Zakovat bo‘limini oching.', Markup([
        [Button('🤖 AI bilan savol-javob', callback_data='ai_private')],
        [Button('🏆 Guruhda Zakovat', callback_data='z11:help:0')],
        [Button('📚 Kitob bo‘yicha savol-javob', callback_data='library')],
        [Button('🌍 Til mashqlari', callback_data='lingua:home')],
        [Button('⬅️ Bosh menyu', callback_data='home')]]))


def register_navigation(app, namespace):
    state = namespace['STATE']

    async def text_menu(update, context):
        msg, user = update.effective_message, update.effective_user
        if not msg or not user or update.effective_chat.type != 'private':
            return
        text = (msg.text or '').strip()
        cmd = text.split('@', 1)[0].split()[0] if text else ''
        kind = KEYS.get(text)
        if cmd in ('/start', '/cancel'):
            kind = 'start' if cmd == '/start' else 'home'
        if not kind:
            return
        cancel_input(context, user.id, state)
        namespace['ensure_user'](user)
        if kind == 'start':
            await namespace['v9_start_selector'](update, context)
        elif kind == 'home':
            await msg.reply_text('🛡 VERITAS\n\nAsosiy bo‘lim:', reply_markup=namespace['main_menu_markup'](user.id))
        elif kind == 'school':
            await msg.reply_text('🎓 O‘QUV • TALABA\n\nTa’lim turini tanlang:', reply_markup=namespace['v9_entry_markup']())
        elif kind in ('tests', 'qa'):
            title, markup = section(kind)
            await msg.reply_text(title, reply_markup=markup)
        elif kind == 'lingua':
            await app.bot_data['veritas_lingua_learning'].home(update, context)
        elif kind == 'post':
            if user.id in namespace['SUPER_OWNERS']:
                await msg.reply_text('📢 AVTOPOST', reply_markup=namespace['ai_news_super_markup']())
            else:
                await msg.reply_text('📢 Avtopostni Super Ega boshqaradi.', reply_markup=namespace['back_markup']())
        elif kind == 'rebus':
            await msg.reply_text('🧩 REBUS\n\nRebus bo‘limini oching:', reply_markup=Markup([
                [Button('🧩 Rebusni ochish', callback_data='rebus:start')],
                [Button('⬅️ Bosh menyu', callback_data='home')]]))
        else:
            await msg.reply_text('❓ YORDAM', reply_markup=namespace['help_home_markup']())
        raise ApplicationHandlerStop

    async def menu_callback(update, context):
        query = update.callback_query
        if not query or not query.message or query.message.chat.type != 'private':
            return
        if query.data in MENUS:
            cancel_input(context, query.from_user.id, state)
        if query.data in ('nav:tests', 'nav:qa'):
            await query.answer()
            text, markup = section(query.data.split(':')[1])
            await query.edit_message_text(text, reply_markup=markup)
            raise ApplicationHandlerStop

    app.add_handler(CommandHandler(['start', 'cancel'], text_menu, filters=filters.ChatType.PRIVATE), group=-40)
    pattern = '^(' + '|'.join(re.escape(x) for x in KEYS) + ')$'
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & filters.Regex(pattern), text_menu), group=-40)
    app.add_handler(CallbackQueryHandler(menu_callback), group=-40)
