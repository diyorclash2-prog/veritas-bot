"""Real PTB update dispatch against an isolated DB and offline Telegram transport."""
import asyncio
import json
import os
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, patch

from telegram import Update
from telegram.ext import Application
from telegram.request import BaseRequest
from bot_runtime import OrderedUpdates, FastTranslations, PrivateAnswers
from lingua_learning import LearningStore, DATA, LANGS, exercise


class LearningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'test.sqlite3'
        self.store = LearningStore(self.path)

    def solve(self, row, uid=101):
        answer = next(q for q in DATA['rows'] if q['id'] == row['qid'])['answer'][row['target']].split()
        options, used = json.loads(row['options']), set()
        for word in answer:
            index = next(i for i,v in enumerate(options) if v == word and i not in used)
            used.add(index)
            row = self.store.action(uid,row['id'],row['revision'],str(index))
        return self.store.action(uid,row['id'],row['revision'],'check')

    def test_every_language_pair_has_valid_exercise(self):
        for source in LANGS:
            for target in LANGS:
                if source == target:
                    continue
                with self.subTest(source=source,target=target):
                    self.store.configure(101,source,target,'A0','conversation')
                    row = self.store.start(101)
                    question = next(q for q in DATA['rows'] if q['id'] == row['qid'])
                    self.assertEqual(len(json.loads(row['options'])),len(question['answer'][target].split())+2)
                    text, markup = exercise(row)
                    self.assertLess(len(text),4096)
                    for line in markup.inline_keyboard:
                        for button in line:
                            self.assertLessEqual(len(button.callback_data.encode()),64)
                    done = self.solve(row)
                    self.assertEqual(done['reward'],10)

    def test_answer_replay_and_cross_user_cannot_award(self):
        self.store.configure(101,'ru','ar','A0','travel')
        row = self.store.start(101)
        with self.assertRaises(ValueError): self.store.action(202,row['id'],0,'0')
        moved = self.store.action(101,row['id'],0,'0')
        with self.assertRaises(ValueError): self.store.action(101,row['id'],0,'0')
        self.store.action(101,row['id'],1,'undo')
        done = self.solve(self.store.start(101))
        with self.assertRaises(ValueError): self.store.action(101,done['id'],done['revision'],'check')
        self.assertEqual(self.store.profiles(101)[0]['xp'],10)
        self.assertEqual(self.store.profiles(101)[0]['coins'],2)

    def test_restart_resumes_question_and_preserves_pair_progress(self):
        self.store.configure(101,'en','ar','A1','work')
        row = self.store.start(101)
        self.store = LearningStore(self.path)
        self.assertEqual(self.store.start(101)['id'],row['id'])
        self.solve(row)
        self.store.configure(101,'ru','en','B1','study')
        self.store.configure(101,'en','ar','A1','work')
        self.assertEqual(self.store.profiles(101)[0]['xp'],10)
        self.assertNotEqual(self.store.start(101)['qid'],row['qid'])

    def test_incomplete_answer_does_not_finish_and_wrong_answer_no_reward(self):
        self.store.configure(101,'uz','en','A0','conversation')
        row = self.store.start(101)
        with self.assertRaises(ValueError): self.store.action(101,row['id'],0,'check')
        correct = next(q for q in DATA['rows'] if q['id'] == row['qid'])['answer']['en'].split()
        options = json.loads(row['options'])
        wrong = next(i for i,v in enumerate(options) if v not in correct)
        row = self.store.action(101,row['id'],0,str(wrong))
        for i in [n for n in range(len(options)) if n != wrong][:len(correct)-1]:
            row = self.store.action(101,row['id'],row['revision'],str(i))
        row = self.store.action(101,row['id'],row['revision'],'check')
        self.assertEqual((row['correct'],row['reward']),(0,0))

    def test_difficulty_progresses_and_never_reissues_completed_question(self):
        self.store.configure(101,'uz','en','A0','conversation')
        seen = set()
        for _ in range(4):
            row = self.store.start(101)
            self.assertNotIn(row['qid'],seen); seen.add(row['qid'])
            self.solve(row)
        self.assertGreater(next(q['tier'] for q in DATA['rows'] if q['id']==row['qid']),0)


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_busy_chat_does_not_block_others_and_same_chat_ordered(self):
        proc = OrderedUpdates(); gate = asyncio.Event(); entered = asyncio.Event(); events=[]
        async def slow():
            entered.set(); await gate.wait(); events.append('first')
        async def record(name): events.append(name)
        def up(chat,user): return NS(effective_chat=NS(id=chat),effective_user=NS(id=user))
        a=asyncio.create_task(proc.process_update(up(1,1),slow()))
        await entered.wait()
        b=asyncio.create_task(proc.process_update(up(1,2),record('same')))
        await proc.process_update(up(3,3),record('other'))
        self.assertEqual(events,['other'])
        gate.set(); await asyncio.gather(a,b)
        self.assertEqual(events,['other','first','same']); self.assertEqual(proc.locks,{})

    async def test_same_user_cross_chat_state_is_serialized(self):
        proc=OrderedUpdates(); gate=asyncio.Event(); entered=asyncio.Event(); done=[]
        async def slow(): entered.set(); await gate.wait(); done.append(1)
        async def other(): done.append(2)
        a=asyncio.create_task(proc.process_update(NS(effective_chat=NS(id=1),effective_user=NS(id=1)),slow()))
        await entered.wait()
        b=asyncio.create_task(proc.process_update(NS(effective_chat=NS(id=2),effective_user=NS(id=1)),other()))
        await asyncio.sleep(0); self.assertFalse(done)
        gate.set(); await asyncio.gather(a,b); self.assertEqual(done,[1,2])

    async def test_translation_falls_back_and_bounds_slow_workers(self):
        engine=FastTranslations(timeout=.01,workers=1); gate=threading.Event(); calls=[]
        def slow(text,lang): calls.append(text); gate.wait(1); return 'translated'
        try:
            self.assertEqual(await engine.text('first','ru',lambda *a:None,slow),'first')
            self.assertEqual(await engine.text('second','ru',lambda *a:None,slow),'second')
            self.assertEqual(calls,['first'])
            self.assertEqual(await engine.text('cached','ru',lambda *a:'cache',slow),'cache')
        finally:
            gate.set(); await asyncio.gather(*list(engine.pending.values()))

    async def test_private_ai_returns_control_and_releases_busy_after_failure(self):
        answers=PrivateAnswers(timeout=.01); tasks=[]
        ctx=NS(application=NS(create_task=lambda coro,**kw:tasks.append(asyncio.create_task(coro))))
        up=NS(effective_user=NS(id=1),effective_message=NS(reply_text=AsyncMock()))
        async def slow(*a): await asyncio.Event().wait()
        await answers.submit(up,ctx,slow)
        await answers.submit(up,ctx,slow)
        self.assertEqual(len(tasks),1)
        await asyncio.gather(*tasks)
        self.assertFalse(answers.pending)
        self.assertIn('vaqti tugadi',up.effective_message.reply_text.await_args.args[0])


class TelegramOffline(BaseRequest):
    @property
    def read_timeout(self): return 5
    def __init__(self): self.calls=[]; self.failure=None
    async def initialize(self): pass
    async def shutdown(self): pass
    async def do_request(self,url,method,request_data=None,**kwargs):
        endpoint=url.rsplit('/',1)[-1]; data=request_data.parameters if request_data else {}
        self.calls.append((endpoint,data))
        if self.failure and endpoint==self.failure[0]:
            failure=self.failure; self.failure=None
            return 400,json.dumps({'ok':False,'error_code':400,'description':failure[1]}).encode()
        if endpoint=='getMe': result={'id':900001,'is_bot':True,'first_name':'Offline','username':'offline_bot'}
        elif endpoint=='getUserProfilePhotos': result={'total_count':0,'photos':[]}
        elif endpoint=='answerCallbackQuery': result=True
        else: result={'message_id':int(data.get('message_id',77)), 'date':1,'chat':{'id':int(data.get('chat_id',101)),'type':'private'},'text':data.get('text','')}
        return 200,json.dumps({'ok':True,'result':result}).encode()


class DispatchTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import bot
        self.bot_module=bot
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.request=TelegramOffline(); captured=[]
        self.patches=[patch.object(bot,'DB_PATH',str(Path(self.tmp.name)/'isolated.sqlite3')),
                      patch.object(bot,'TOKEN','123456:TEST_ONLY_NOT_REAL'),patch.object(bot,'SUPER_OWNERS',{101}),
                      patch.object(bot,'OPENAI_API_KEY',''),patch.dict(os.environ,{'VL_PUBLIC_URL':'https://example.org/lingua'})]
        for p in self.patches: p.start(); self.addCleanup(p.stop)
        original=bot.VeritasI18nBot
        def factory(**kwargs): return original(**kwargs,request=self.request,get_updates_request=TelegramOffline())
        with patch.object(bot,'VeritasI18nBot',side_effect=factory), patch.object(Application,'run_polling',lambda app,**kw:captured.append(app)):
            bot.main()
        self.app=captured[0]; self.errors=[]
        async def error(update,context): self.errors.append(context.error)
        self.app.add_error_handler(error)
        await self.app.initialize()
        self.sequence=0
        bot.STATE.clear()

    async def asyncTearDown(self):
        await self.app.shutdown()

    async def send(self,text=None,callback=None,uid=101):
        self.sequence+=1
        user={'id':uid,'first_name':'Synthetic','is_bot':False}
        message={'message_id':self.sequence,'date':1,'chat':{'id':uid,'type':'private'},'text':text or 'menu','from':user}
        data={'update_id':self.sequence}
        if callback:
            data['callback_query']={'id':str(self.sequence),'from':user,'chat_instance':'test','data':callback,'message':message}
        else:
            if text.startswith('/'):
                message['entities']=[{'type':'bot_command','offset':0,'length':len(text.split()[0])}]
            data['message']=message
        up=Update.de_json(data,self.app.bot)
        start=len(self.request.calls)
        await self.app.process_update(up)
        self.assertEqual(self.errors,[])
        return self.request.calls[start:]

    async def test_all_persistent_buttons_bypass_astra_and_cancel_input(self):
        from bot_navigation import KEYS
        bridge=self.app.bot_data['veritas_super_settings_v1']
        for label in KEYS:
            with self.subTest(label=label):
                bridge.chat.open(101)
                self.bot_module.STATE[101]={'mode':'v9_plan_class'}
                calls=await self.send(label)
                self.assertNotIn(101,self.bot_module.STATE)
                self.assertFalse(bridge.chat.awaiting(101))
                self.assertTrue(any(e=='sendMessage' for e,d in calls))

    async def test_all_primary_menu_buttons_respond_for_member_and_owner(self):
        for uid in (101,202):
            await self.send('/start',uid=uid)
            targets=[b.callback_data for row in self.bot_module.main_menu_markup(uid).inline_keyboard for b in row]
            for target in targets:
                with self.subTest(uid=uid,target=target):
                    calls=await self.send(callback=target,uid=uid)
                    self.assertTrue(any(e in ('editMessageText','sendMessage') for e,d in calls),target)

    async def test_lingua_full_real_dispatch_onboarding_answer_restart(self):
        await self.send('/lingua')
        for data in ('setup','source:ru','target:en','level:A0','goal:conversation','practice'):
            await self.send(callback='lingua:'+data)
        store=self.app.bot_data['veritas_lingua_learning'].store
        row=store.start(101); options=json.loads(row['options']); used=set()
        answer=next(q for q in DATA['rows'] if q['id']==row['qid'])['answer']['en'].split()
        for word in answer:
            index=next(i for i,v in enumerate(options) if v==word and i not in used);used.add(index)
            await self.send(callback=f"lingua:a:{row['id']}:{row['revision']}:{index}")
            row=store.start(101)
        await self.send(callback=f"lingua:a:{row['id']}:{row['revision']}:check")
        self.assertEqual(LearningStore(store.path).profiles(101)[0]['xp'],10)
        await self.send(callback='lingua:home')

    async def test_expired_callback_spinner_and_repeated_menu_do_not_abort(self):
        self.request.failure=('answerCallbackQuery','Bad Request: query is too old and response timeout expired or query ID is invalid')
        calls=await self.send(callback='home')
        self.assertTrue(any(e=='editMessageText' for e,d in calls))
        self.request.failure=('editMessageText','Bad Request: Message is not modified')
        await self.send(callback='home')
        self.request.failure=('editMessageText','Bad Request: There is no text in the message to edit')
        calls=await self.send(callback='lingua:home')
        self.assertTrue(any(e=='sendMessage' for e,d in calls))

    async def test_start_and_home_clear_stale_states(self):
        self.bot_module.STATE[101]={'mode':'lib_upload_title'}
        await self.send('/start')
        self.assertNotIn(101,self.bot_module.STATE)
        self.bot_module.STATE[101]={'mode':'owner_reply'}
        await self.send(callback='home')
        self.assertNotIn(101,self.bot_module.STATE)


if __name__ == '__main__': unittest.main()
