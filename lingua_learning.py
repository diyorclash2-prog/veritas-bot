"""Telegram Lingua practice. Separate tables; no change to web OTP/accounts.

Uses the existing Lingua multilingual seed lessons. Rewards are idempotent,
answers are checked on the server and every callback belongs to its learner.
"""
import json
from pathlib import Path
import random
import secrets
import sqlite3
from contextlib import contextmanager

from telegram import InlineKeyboardButton as Button, InlineKeyboardMarkup as Markup
from telegram.ext import ApplicationHandlerStop, CallbackQueryHandler

LANGS = {'uz': '🇺🇿 O‘zbekcha', 'en': '🇬🇧 English', 'ru': '🇷🇺 Русский',
         'ar': '🇸🇦 العربية', 'tr': '🇹🇷 Türkçe', 'es': '🇪🇸 Español',
         'fr': '🇫🇷 Français', 'de': '🇩🇪 Deutsch', 'zh': '🇨🇳 中文',
         'ja': '🇯🇵 日本語', 'ko': '🇰🇷 한국어'}
LEVELS = ('A0', 'A1', 'A2', 'B1', 'B2', 'C1', 'C2')
GOALS = {'conversation': '💬 Suhbat', 'travel': '✈️ Sayohat', 'work': '💼 Ish',
         'study': '🎓 O‘qish', 'exam': '📝 Imtihon'}
DATA = json.loads(Path(__file__).with_name('lingua_lessons.json').read_text(encoding='utf-8'))


class LearningStore:
    def __init__(self, path):
        self.path = str(path)
        with self.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS tg_lingua_profiles (
                  uid INTEGER NOT NULL, source TEXT NOT NULL, target TEXT NOT NULL,
                  level TEXT NOT NULL, goal TEXT NOT NULL, xp INTEGER NOT NULL DEFAULT 0,
                  coins INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1,
                  PRIMARY KEY(uid,source,target));
                CREATE TABLE IF NOT EXISTS tg_lingua_attempts (
                  id TEXT PRIMARY KEY, uid INTEGER NOT NULL, source TEXT NOT NULL,
                  target TEXT NOT NULL, qid TEXT NOT NULL, options TEXT NOT NULL,
                  selected TEXT NOT NULL DEFAULT '[]', revision INTEGER NOT NULL DEFAULT 0,
                  status TEXT NOT NULL DEFAULT 'active', correct INTEGER,
                  reward INTEGER NOT NULL DEFAULT 0);
                CREATE UNIQUE INDEX IF NOT EXISTS tg_lingua_active_attempt
                  ON tg_lingua_attempts(uid) WHERE status='active';
                CREATE TABLE IF NOT EXISTS tg_lingua_rewards (
                  uid INTEGER NOT NULL, source TEXT NOT NULL,target TEXT NOT NULL,qid TEXT NOT NULL,
                  PRIMARY KEY(uid,source,target,qid));
            ''')

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def profiles(self, uid):
        with self.db() as db:
            return [dict(r) for r in db.execute('SELECT * FROM tg_lingua_profiles WHERE uid=? ORDER BY active DESC,target', (uid,))]

    def configure(self, uid, source, target, level, goal):
        if source not in LANGS or target not in LANGS or source == target or level not in LEVELS or goal not in GOALS:
            raise ValueError('Til, daraja yoki maqsad noto‘g‘ri.')
        with self.db() as db:
            db.execute('UPDATE tg_lingua_profiles SET active=0 WHERE uid=?', (uid,))
            db.execute('''INSERT INTO tg_lingua_profiles(uid,source,target,level,goal) VALUES(?,?,?,?,?)
                       ON CONFLICT(uid,source,target) DO UPDATE SET level=excluded.level,goal=excluded.goal,active=1''',
                       (uid,source,target,level,goal))
            db.execute("UPDATE tg_lingua_attempts SET status='cancelled' WHERE uid=? AND status='active'", (uid,))

    def start(self, uid):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            current = db.execute("SELECT * FROM tg_lingua_attempts WHERE uid=? AND status='active'", (uid,)).fetchone()
            if current:
                return dict(current)
            p = db.execute('SELECT * FROM tg_lingua_profiles WHERE uid=? AND active=1', (uid,)).fetchone()
            if not p:
                raise ValueError('Avval til, daraja va maqsadingizni tanlang.')
            tier = min(5, max(0, LEVELS.index(p['level'])-1) + p['xp']//30)
            rows = [r for r in DATA['rows'] if r['tier'] <= tier]
            seen = {r[0] for r in db.execute('SELECT qid FROM tg_lingua_attempts WHERE uid=? AND source=? AND target=? AND status=?',
                                          (uid,p['source'],p['target'],'done'))}
            fresh = [r for r in rows if r['id'] not in seen]
            if not fresh:
                raise ValueError('Bu bosqichdagi mashqlar bajarildi. Tillar/daraja bo‘limida keyingi darajani tanlang yoki saytni oching.')
            fresh.sort(key=lambda r: (r['goal'] != p['goal'], -r['tier']))
            question = fresh[0]
            words = question['answer'][p['target']].split()
            wrong = [w for w in DATA['wrong'][p['target']] if w not in words]
            options = words + random.SystemRandom().sample(wrong, 2)
            random.SystemRandom().shuffle(options)
            aid = secrets.token_hex(6)
            db.execute('INSERT INTO tg_lingua_attempts(id,uid,source,target,qid,options) VALUES(?,?,?,?,?,?)',
                       (aid,uid,p['source'],p['target'],question['id'],json.dumps(options, ensure_ascii=False)))
            return dict(db.execute('SELECT * FROM tg_lingua_attempts WHERE id=?', (aid,)).fetchone())

    def action(self, uid, aid, revision, action):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM tg_lingua_attempts WHERE id=? AND uid=?', (aid,uid)).fetchone()
            if not row or row['status'] != 'active' or row['revision'] != revision:
                raise ValueError('Bu tugma eskirgan. Joriy mashqdagi tugmani bosing.')
            row = dict(row)
            options, selected = json.loads(row['options']), json.loads(row['selected'])
            question = next(r for r in DATA['rows'] if r['id'] == row['qid'])
            answer = question['answer'][row['target']].split()
            if action == 'undo':
                selected = selected[:-1]
            elif action == 'check':
                if len(selected) != len(answer):
                    raise ValueError(f'{len(answer)} ta so‘zni tartib bilan tanlang.')
                correct = [options[i] for i in selected] == answer
                reward = 0
                if correct:
                    reward = db.execute('INSERT OR IGNORE INTO tg_lingua_rewards VALUES(?,?,?,?)',
                                        (uid,row['source'],row['target'],row['qid'])).rowcount * 10
                    db.execute('UPDATE tg_lingua_profiles SET xp=xp+?,coins=coins+? WHERE uid=? AND source=? AND target=?',
                               (reward,2 if reward else 0,uid,row['source'],row['target']))
                db.execute("UPDATE tg_lingua_attempts SET status='done',correct=?,reward=? WHERE id=?", (int(correct),reward,aid))
            elif action.isdigit():
                index = int(action)
                if index >= len(options) or index in selected or len(selected) >= len(answer):
                    raise ValueError('Tanlov qabul qilinmadi. Kerak bo‘lsa oxirgi so‘zni qaytaring.')
                selected.append(index)
            else:
                raise ValueError('Noto‘g‘ri amal.')
            db.execute('UPDATE tg_lingua_attempts SET selected=?,revision=revision+1 WHERE id=?', (json.dumps(selected),aid))
            return dict(db.execute('SELECT * FROM tg_lingua_attempts WHERE id=?', (aid,)).fetchone())


def exercise(row):
    question = next(r for r in DATA['rows'] if r['id'] == row['qid'])
    words, selected = json.loads(row['options']), json.loads(row['selected'])
    answer = question['answer'][row['target']]
    if row['status'] == 'done':
        text = ('✅ To‘g‘ri!' if row['correct'] else '📖 To‘g‘ri javob: '+answer)
        text += f"\n\n✨ +{row['reward']} XP · 🪙 +{2 if row['reward'] else 0}\n" + (' '.join(words[i] for i in selected))
        return text, Markup([[Button('➡️ Keyingi mashq', callback_data='lingua:practice')], [Button('🏠 Lingua', callback_data='lingua:home')]])
    prefix = f"lingua:a:{row['id']}:{row['revision']}:"
    text = (f"🌍 {LANGS[row['source']]} → {LANGS[row['target']]}\n\n"
            f"{question['prompt'][row['source']]}\n\n"
            f"{' '.join(words[i] for i in selected) or '…'}\n\n"
            f"{len(answer.split())} ta so‘zni to‘g‘ri tartibda tanlang.")
    buttons = [Button(word, callback_data=prefix+str(i)) for i,word in enumerate(words) if i not in selected]
    kb = [buttons[i:i+3] for i in range(0,len(buttons),3)]
    kb += [[Button('↩️ Qaytarish',callback_data=prefix+'undo'), Button('✅ Tekshirish',callback_data=prefix+'check')],
           [Button('🏠 Lingua',callback_data='lingua:home')]]
    return text, Markup(kb)


class Learning:
    def __init__(self, path, website, cancel):
        self.store, self.website, self.cancel = LearningStore(path), website, cancel

    async def show(self, update, text, markup):
        # Learning words must not be translated into the bot UI language.
        if update.callback_query:
            msg = update.callback_query.message
            return await update.get_bot().edit_message_text(text, chat_id=msg.chat.id, message_id=msg.message_id,
                                                           reply_markup=markup, _skip_i18n=True)
        return await update.get_bot().send_message(update.effective_chat.id, text, reply_markup=markup, _skip_i18n=True)

    async def home(self, update, context):
        profiles = self.store.profiles(update.effective_user.id)
        text = '🌍 VERITAS LINGUA\n\nBot ichida til juftligi, daraja va maqsadni tanlang. So‘zlardan javob tuzing. Natijalar serverda saqlanadi.\n'
        for p in profiles:
            text += f"\n{'▶️ ' if p['active'] else ''}{LANGS[p['source']]} → {LANGS[p['target']]} · {p['level']}\n{GOALS[p['goal']]} · {p['xp']} XP · {p['coins']} tanga\n"
        text += '\nTelegram mashqlari va saytdagi akkaunt hozir alohida hisoblanadi.'
        kb = [[Button('📚 Mashqni boshlash / davom etish', callback_data='lingua:practice')],
              [Button('⚙️ Tillar, daraja va maqsad', callback_data='lingua:setup')]]
        if self.website:
            kb.append([Button('🌐 Lingua saytini ochish', url=self.website)])
        kb.append([Button('⬅️ Veritas', callback_data='home')])
        return await self.show(update, text, Markup(kb))

    async def launcher(self, update, context):
        if update.effective_chat.type != 'private':
            await update.effective_message.reply_text('🌍 Shaxsiy til mashqlari uchun botning shaxsiy chatida /lingua yozing.')
        else:
            self.cancel(context, update.effective_user.id)
            await self.home(update, context)
        raise ApplicationHandlerStop

    async def callback(self, update, context):
        q = update.callback_query
        if not q.message or q.message.chat.type != 'private':
            await q.answer('Lingua mashqlari shaxsiy chatda ishlaydi.', show_alert=True)
            raise ApplicationHandlerStop
        await q.answer()
        uid = update.effective_user.id
        parts = q.data.split(':')
        try:
            action = parts[1]
            if action == 'home':
                self.cancel(context, uid)
                await self.home(update, context)
            elif action == 'setup':
                self.cancel(context, uid)
                context.user_data['lingua_setup'] = {}
                await self.show(update, '🌐 Siz biladigan tilni tanlang:', self.language_menu('source'))
            elif action in ('source', 'target') and len(parts) == 3:
                value = parts[2]
                plan = context.user_data.get('lingua_setup')
                if plan is None or value not in LANGS:
                    raise ValueError('Til sozlamasini qayta oching.')
                if action == 'source':
                    plan.clear(); plan['source'] = value
                    await self.show(update, '🎯 O‘rganadigan tilni tanlang:', self.language_menu('target', value))
                else:
                    if not plan.get('source') or plan['source'] == value:
                        raise ValueError('Ikki xil tilni tanlang.')
                    plan['target'] = value
                    await self.show(update, '📊 Hozirgi darajangiz qanday?', Markup([[Button(x,callback_data='lingua:level:'+x) for x in LEVELS[:4]], [Button(x,callback_data='lingua:level:'+x) for x in LEVELS[4:]]]))
            elif action == 'level' and len(parts) == 3:
                plan = context.user_data.get('lingua_setup', {})
                if not plan.get('target') or parts[2] not in LEVELS:
                    raise ValueError('Avval til juftligini tanlang.')
                plan['level'] = parts[2]
                await self.show(update, '🎯 Tilni nima uchun o‘rganmoqchisiz?', Markup([[Button(v,callback_data='lingua:goal:'+k)] for k,v in GOALS.items()]))
            elif action == 'goal' and len(parts) == 3:
                plan = context.user_data.get('lingua_setup', {})
                if not all(k in plan for k in ('source','target','level')):
                    raise ValueError('Sozlash tugamagan. Tillarni qayta tanlang.')
                self.store.configure(uid,plan['source'],plan['target'],plan['level'],parts[2])
                context.user_data.pop('lingua_setup',None)
                await self.home(update,context)
            elif action == 'practice':
                self.cancel(context, uid)
                text, markup = exercise(self.store.start(uid))
                await self.show(update,text,markup)
            elif action == 'a' and len(parts) == 5 and parts[3].isdigit():
                text, markup = exercise(self.store.action(uid,parts[2],int(parts[3]),parts[4]))
                await self.show(update,text,markup)
            else:
                raise ValueError('Bu tugma eskirgan. /lingua orqali qayta oching.')
        except ValueError as exc:
            await update.get_bot().send_message(q.message.chat.id, str(exc), reply_markup=Markup([[Button('🏠 Lingua',callback_data='lingua:home')]]), _skip_i18n=True)
        raise ApplicationHandlerStop

    @staticmethod
    def language_menu(action, exclude=None):
        buttons = [Button(v, callback_data=f'lingua:{action}:{k}') for k,v in LANGS.items() if k != exclude]
        return Markup([buttons[i:i+2] for i in range(0,len(buttons),2)] + [[Button('⬅️ Lingua',callback_data='lingua:home')]])


def register_learning(app, path, namespace):
    from bot_navigation import cancel_input
    from lingua_bot_bridge import STATE_KEY
    bridge = app.bot_data.get(STATE_KEY)
    learning = Learning(path, bridge.config.url if bridge else '', lambda ctx,uid: cancel_input(ctx,uid,namespace['STATE']))
    app.bot_data['veritas_lingua_learning'] = learning
    if bridge:
        bridge.learning = learning
    app.add_handler(CallbackQueryHandler(learning.callback, pattern=r'^lingua:'), group=-32)
    return learning
