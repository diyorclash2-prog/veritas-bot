"""Telegram Lingua practice. Separate tables; no change to web OTP/accounts.

Uses the existing Lingua multilingual seed lessons. Rewards are idempotent,
answers are checked on the server and every callback belongs to its learner.
"""
import json
import asyncio
import hashlib
import logging
import time
from pathlib import Path
import random
import secrets
import sqlite3
from contextlib import contextmanager

from telegram import InlineKeyboardButton as Button, InlineKeyboardMarkup as Markup
from telegram.ext import ApplicationHandlerStop, CallbackQueryHandler
from lingua_ai import normalized, question as validate_question, profile as validate_profile

LANGS = {'uz': '🇺🇿 O‘zbekcha', 'en': '🇬🇧 English', 'ru': '🇷🇺 Русский',
         'ar': '🇸🇦 العربية', 'tr': '🇹🇷 Türkçe', 'es': '🇪🇸 Español',
         'fr': '🇫🇷 Français', 'de': '🇩🇪 Deutsch', 'zh': '🇨🇳 中文',
         'ja': '🇯🇵 日本語', 'ko': '🇰🇷 한국어'}
LEVELS = ('A0', 'A1', 'A2', 'B1', 'B2', 'C1', 'C2')
GOALS = {'conversation': '💬 Suhbat', 'travel': '✈️ Sayohat', 'work': '💼 Ish',
         'study': '🎓 O‘qish', 'exam': '📝 Imtihon'}
DATA = json.loads(Path(__file__).with_name('lingua_lessons.json').read_text(encoding='utf-8'))
TRANSLATE = {'uz':'Tarjima qiling:', 'en':'Translate:', 'ru':'Переведите:', 'ar':'ترجم:',
             'tr':'Çevirin:', 'es':'Traduce:', 'fr':'Traduisez :', 'de':'Übersetze:',
             'zh':'请翻译：', 'ja':'翻訳してください：', 'ko':'번역하세요:'}


class NeedQuestions(ValueError):
    pass


def question_data(row):
    if row.get('question_json'):
        return json.loads(row['question_json'])
    q = next(r for r in DATA['rows'] if r['id'] == row['qid'])
    prompt = q['prompt'][row['source']]
    if q.get('translation'):
        prompt = TRANSLATE[row['source']] + ' ' + prompt
    return {'prompt': prompt, 'answer': q['answer'][row['target']].split(), 'explanation': ''}


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
                CREATE TABLE IF NOT EXISTS tg_lingua_questions (
                  id TEXT PRIMARY KEY,source TEXT NOT NULL,target TEXT NOT NULL,
                  goal TEXT NOT NULL,tier INTEGER NOT NULL,question TEXT NOT NULL,
                  prompt_key TEXT NOT NULL,answer_key TEXT NOT NULL,
                  UNIQUE(source,target,prompt_key),UNIQUE(source,target,answer_key));
                CREATE INDEX IF NOT EXISTS tg_lingua_pool ON tg_lingua_questions(source,target,goal,tier);
                CREATE TABLE IF NOT EXISTS tg_lingua_refills (
                  pool TEXT PRIMARY KEY,id TEXT NOT NULL,payload TEXT NOT NULL,
                  status TEXT NOT NULL,updated INTEGER NOT NULL,code TEXT NOT NULL DEFAULT '');
            ''')
            cols = {r[1] for r in db.execute('PRAGMA table_info(tg_lingua_profiles)')}
            if 'tier' not in cols:
                db.execute('ALTER TABLE tg_lingua_profiles ADD COLUMN tier INTEGER NOT NULL DEFAULT 0')
                for i, level in enumerate(LEVELS):
                    db.execute('UPDATE tg_lingua_profiles SET tier=MIN(5,?+xp/30) WHERE level=?', (max(0,i-1),level))
            for name in ('good', 'bad'):
                if name not in cols:
                    db.execute(f'ALTER TABLE tg_lingua_profiles ADD COLUMN {name} INTEGER NOT NULL DEFAULT 0')
            if 'question_json' not in {r[1] for r in db.execute('PRAGMA table_info(tg_lingua_attempts)')}:
                db.execute("ALTER TABLE tg_lingua_attempts ADD COLUMN question_json TEXT NOT NULL DEFAULT ''")

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
            db.execute('UPDATE tg_lingua_profiles SET tier=?,good=0,bad=0 WHERE uid=? AND source=? AND target=?',
                       (max(0,LEVELS.index(level)-1),uid,source,target))

    def profile(self, uid):
        rows = self.profiles(uid)
        if not rows or not rows[0]['active']:
            raise ValueError('Avval til, daraja va maqsadingizni tanlang.')
        return validate_profile({k: rows[0][k] for k in ('source','target','level','goal','tier')})

    @staticmethod
    def pool(p):
        return ':'.join(str(p[k]) for k in ('source','target','level','goal','tier'))

    def refill(self, uid):
        p = self.profile(uid); pool = self.pool(p); now = int(time.time())
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            count = db.execute('''SELECT COUNT(*) FROM tg_lingua_questions q
                WHERE source=? AND target=? AND goal=? AND tier=? AND NOT EXISTS
                (SELECT 1 FROM tg_lingua_attempts a WHERE a.uid=? AND a.qid=q.id)''',
                (p['source'],p['target'],p['goal'],p['tier'],uid)).fetchone()[0]
            if count >= 3: return None
            row = db.execute('SELECT * FROM tg_lingua_refills WHERE pool=?', (pool,)).fetchone()
            if row and row['status'] == 'pending': return dict(row)
            if row and now-row['updated'] < (60 if row['status']=='done' else 600): return None
            excluded = [json.loads(r[0])['prompt'] for r in db.execute(
                'SELECT question FROM tg_lingua_questions WHERE source=? AND target=? ORDER BY rowid DESC LIMIT 16',
                (p['source'],p['target']))]
            encoded = json.dumps({'profile':p,'exclude':excluded},ensure_ascii=False)
            ident = secrets.token_hex(16)
            db.execute("INSERT OR REPLACE INTO tg_lingua_refills VALUES(?,?,?,'pending',?,'')", (pool,ident,encoded,now))
            return dict(db.execute('SELECT * FROM tg_lingua_refills WHERE pool=?', (pool,)).fetchone())

    def import_batch(self, job, rows):
        p = validate_profile(json.loads(job['payload'])['profile'])
        if not isinstance(rows,list) or not 1 <= len(rows) <= 4: raise ValueError('Invalid batch')
        rows = [validate_question(q,p['tier']) for q in rows]
        inserted = 0
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            for q in rows:
                prompt, answer = normalized(q['prompt']), normalized(' '.join(q['answer']))
                # Seed questions are also excluded from the AI bank.
                if any(normalized(r['answer'][p['target']]) == answer for r in DATA['rows']): continue
                ident = 'ai_'+hashlib.sha256((p['source']+':'+p['target']+':'+prompt).encode()).hexdigest()[:24]
                inserted += db.execute('INSERT OR IGNORE INTO tg_lingua_questions VALUES(?,?,?,?,?,?,?,?)',
                    (ident,p['source'],p['target'],p['goal'],p['tier'],json.dumps(q,ensure_ascii=False),prompt,answer)).rowcount
            db.execute("UPDATE tg_lingua_refills SET status='done',updated=?,code=? WHERE pool=? AND id=?",
                       (int(time.time()),'' if inserted else 'duplicates',job['pool'],job['id']))
        return inserted

    def fail_refill(self, job, code):
        with self.db() as db:
            db.execute("UPDATE tg_lingua_refills SET status='failed',updated=?,code=? WHERE pool=? AND id=?",
                       (int(time.time()),code,job['pool'],job['id']))

    def start(self, uid):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            current = db.execute("SELECT * FROM tg_lingua_attempts WHERE uid=? AND status='active'", (uid,)).fetchone()
            if current:
                return dict(current)
            p = db.execute('SELECT * FROM tg_lingua_profiles WHERE uid=? AND active=1', (uid,)).fetchone()
            if not p:
                raise ValueError('Avval til, daraja va maqsadingizni tanlang.')
            tier = p['tier']
            rows = [r for r in DATA['rows'] if r['tier'] <= tier]
            seen = {r[0] for r in db.execute('SELECT qid FROM tg_lingua_attempts WHERE uid=? AND source=? AND target=?',
                                          (uid,p['source'],p['target']))}
            fresh = [r for r in rows if r['id'] not in seen]
            ai = db.execute('''SELECT q.* FROM tg_lingua_questions q WHERE source=? AND target=? AND goal=? AND tier=?
                AND NOT EXISTS (SELECT 1 FROM tg_lingua_attempts a WHERE a.uid=? AND a.qid=q.id) ORDER BY rowid LIMIT 1''',
                (p['source'],p['target'],p['goal'],tier,uid)).fetchone()
            if not fresh and not ai:
                raise NeedQuestions('Yangi mashqlar tayyorlanmoqda.')
            fresh.sort(key=lambda r: (r['goal'] != p['goal'], -r['tier']))
            if ai:
                qid, snapshot = ai['id'], json.loads(ai['question'])
                words, wrong = snapshot['answer'], snapshot['wrong']
            else:
                q = fresh[0]; qid = q['id']
                snapshot = question_data({'qid':qid,'source':p['source'],'target':p['target']})
                words = snapshot['answer']
                wrong = random.SystemRandom().sample([w for w in DATA['wrong'][p['target']] if w not in words], 2)
            options = words + wrong
            random.SystemRandom().shuffle(options)
            aid = secrets.token_hex(6)
            db.execute('INSERT INTO tg_lingua_attempts(id,uid,source,target,qid,options,question_json) VALUES(?,?,?,?,?,?,?)',
                       (aid,uid,p['source'],p['target'],qid,json.dumps(options, ensure_ascii=False),json.dumps(snapshot,ensure_ascii=False)))
            return dict(db.execute('SELECT * FROM tg_lingua_attempts WHERE id=?', (aid,)).fetchone())

    def action(self, uid, aid, revision, action):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM tg_lingua_attempts WHERE id=? AND uid=?', (aid,uid)).fetchone()
            if not row or row['status'] != 'active' or row['revision'] != revision:
                raise ValueError('Bu tugma eskirgan. Joriy mashqdagi tugmani bosing.')
            row = dict(row)
            options, selected = json.loads(row['options']), json.loads(row['selected'])
            answer = question_data(row)['answer']
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
                p = db.execute('SELECT * FROM tg_lingua_profiles WHERE uid=? AND source=? AND target=?',
                               (uid,row['source'],row['target'])).fetchone()
                good, bad, tier = (p['good']+1 if correct else 0), (0 if correct else p['bad']+1), p['tier']
                if good >= 3: tier, good = min(5,tier+1), 0
                if bad >= 2: tier, bad = max(0,tier-1), 0
                db.execute('UPDATE tg_lingua_profiles SET tier=?,good=?,bad=? WHERE uid=? AND source=? AND target=?',
                           (tier,good,bad,uid,row['source'],row['target']))
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
    question = question_data(row)
    words, selected = json.loads(row['options']), json.loads(row['selected'])
    answer = ' '.join(question['answer'])
    if row['status'] == 'done':
        text = ('✅ To‘g‘ri!' if row['correct'] else '📖 To‘g‘ri javob: '+answer)
        text += f"\n\n✨ +{row['reward']} XP · 🪙 +{2 if row['reward'] else 0}\n" + (' '.join(words[i] for i in selected))
        if question.get('explanation'): text += '\n\n💡 '+question['explanation']
        return text, Markup([[Button('➡️ Keyingi mashq', callback_data='lingua:practice')], [Button('🏠 Lingua', callback_data='lingua:home')]])
    prefix = f"lingua:a:{row['id']}:{row['revision']}:"
    text = (f"🌍 {LANGS[row['source']]} → {LANGS[row['target']]}\n\n"
            f"{'🤖 AI mashqi' if row['qid'].startswith('ai_') else '📚 Mashq'}\n{question['prompt']}\n\n"
            f"{' '.join(words[i] for i in selected) or '…'}\n\n"
            f"{len(answer.split())} ta so‘zni to‘g‘ri tartibda tanlang.")
    buttons = [Button(word, callback_data=prefix+str(i)) for i,word in enumerate(words) if i not in selected]
    kb = [buttons[i:i+3] for i in range(0,len(buttons),3)]
    kb += [[Button('↩️ Qaytarish',callback_data=prefix+'undo'), Button('✅ Tekshirish',callback_data=prefix+'check')],
           [Button('🏠 Lingua',callback_data='lingua:home')]]
    return text, Markup(kb)


class Learning:
    def __init__(self, path, website, cancel, owners=()):
        self.store, self.website, self.cancel = LearningStore(path), website, cancel
        self.owner = min(owners) if owners else None
        self.pending = {}

    def ai_enabled(self):
        from maintainer_client import enabled
        return bool(self.owner and enabled())

    async def fetch_batch(self, job):
        from maintainer_client import request
        try:
            for _ in range(65):
                result = await request('/lingua/questions', {'owner':self.owner,'id':job['id'],
                                                            'payload':json.loads(job['payload'])})
                status = result.get('status')
                if status == 'done':
                    return self.store.import_batch(job,result.get('questions')) > 0
                if status == 'failed':
                    self.store.fail_refill(job,'generation_unavailable')
                    return False
                if status not in ('queued','processing','busy'): raise ValueError('Invalid generation status')
                await asyncio.sleep(3)
        except Exception as exc:
            # Keep the same durable job id after an uncertain network outcome.
            logging.warning('LINGUA_AI_FETCH_RETRY type=%s',type(exc).__name__)
        return False

    def prefetch(self, uid, application):
        if not self.ai_enabled(): return None
        p = self.store.profile(uid); pool = self.store.pool(p)
        task = self.pending.get(pool)
        if task and not task.done(): return task
        if len(self.pending) >= 4: return None
        job = self.store.refill(uid)
        if not job: return None
        task = application.create_task(self.fetch_batch(job))
        self.pending[pool] = task
        task.add_done_callback(lambda done: self.pending.pop(pool,None))
        return task

    async def notify_ready(self, task, update, context, token):
        ready = await asyncio.shield(task)
        if context.user_data.get('lingua_waiting') != token: return
        context.user_data.pop('lingua_waiting',None)
        text = ('✅ Yangi AI mashqlari tayyor. Davom etish tugmasini bosing.' if ready else
                'AI mashqlari hozir tayyor bo‘lmadi. So‘rov saqlangan; keyinroq qayta tekshiring. '
                'Mavjud mashqlar va boshqa menyular ishlashda davom etadi.')
        await update.get_bot().send_message(update.effective_chat.id,text,reply_markup=self.retry_menu(),_skip_i18n=True)

    @staticmethod
    def retry_menu():
        return Markup([[Button('➡️ Davom etish / tekshirish',callback_data='lingua:practice')],
                       [Button('🏠 Lingua',callback_data='lingua:home')]])

    async def show(self, update, text, markup):
        # Learning words must not be translated into the bot UI language.
        if update.callback_query:
            msg = update.callback_query.message
            return await update.get_bot().edit_message_text(text, chat_id=msg.chat.id, message_id=msg.message_id,
                                                           reply_markup=markup, _skip_i18n=True)
        return await update.get_bot().send_message(update.effective_chat.id, text, reply_markup=markup, _skip_i18n=True)

    async def home(self, update, context):
        profiles = self.store.profiles(update.effective_user.id)
        text = ('🌍 VERITAS LINGUA\n\nTil juftligi, daraja va maqsadni tanlang. So‘zlardan javob tuzing. '
                'AI yangi mashqlar va javob izohlarini tayyorlaydi. Natijalar serverda saqlanadi.\n')
        for p in profiles:
            text += f"\n{'▶️ ' if p['active'] else ''}{LANGS[p['source']]} → {LANGS[p['target']]} · {p['level']}\n{GOALS[p['goal']]} · {p['xp']} XP · {p['coins']} tanga · Mashq bosqichi {p['tier']+1}/6\n"
        text += '\n3 ta ketma-ket to‘g‘ri javobdan keyin mashqlar qiyinlashadi; 2 ta xatodan keyin yengillashadi.'
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
                task = self.prefetch(uid, context.application)
                try:
                    text, markup = exercise(self.store.start(uid))
                    await self.show(update,text,markup)
                except NeedQuestions:
                    if task:
                        token = secrets.token_hex(8)
                        context.user_data['lingua_waiting'] = token
                        await self.show(update,'🤖 Darajangiz va maqsadingizga mos yangi AI mashqlari tayyorlanmoqda. '
                                        'Tayyor bo‘lsa xabar beraman. Boshqa menyulardan foydalanishingiz mumkin.',self.retry_menu())
                        context.application.create_task(self.notify_ready(task,update,context,token))
                    else:
                        await self.show(update,'📚 Shu bosqichdagi tayyor mashqlar bajarildi. AI xizmati yoki so‘rov limiti '
                                        'sabab yangi to‘plam hozir mavjud emas. Birozdan so‘ng tekshiring yoki boshqa til juftligini tanlang.',self.retry_menu())
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
    learning = Learning(path, bridge.config.url if bridge else '', lambda ctx,uid: cancel_input(ctx,uid,namespace['STATE']),namespace.get('SUPER_OWNERS',()))
    app.bot_data['veritas_lingua_learning'] = learning
    if bridge:
        bridge.learning = learning
    app.add_handler(CallbackQueryHandler(learning.callback, pattern=r'^lingua:'), group=-32)
    return learning
