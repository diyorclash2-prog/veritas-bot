import asyncio
import copy
import json
import io
import secrets
import time
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, patch

from ai_spending import BudgetError, MeteredAPI
from astra_support import ASTRA
from lingua_ai import GenerationQueue, generate, normalized, payload, question
from lingua_learning import Learning, LearningStore, exercise, question_data
from maintainer_service import Store, handler
from maintainer_client import signature

PROFILE = {'source':'uz','target':'en','level':'A1','goal':'travel','tier':0}
QUESTIONS = [
    {'prompt':'Tarjima qiling: Menga xarita kerak.', 'answer':['I','need','a','map.'],
     'wrong':['sleep','blue'], 'explanation':'Need so‘zi kerak degan ma’noni anglatadi.'},
    {'prompt':'Tarjima qiling: Poyezd qayerda?', 'answer':['Where','is','the','train?'],
     'wrong':['drink','green'], 'explanation':'Where joy haqida savol berish uchun ishlatiladi.'},
    {'prompt':'Tarjima qiling: Bu mening sumkam.', 'answer':['This','is','my','bag.'],
     'wrong':['runs','red'], 'explanation':'My egalikni bildiradi.'},
    {'prompt':'Tarjima qiling: Eshikni oching.', 'answer':['Open','the','door.'],
     'wrong':['water','sleep'], 'explanation':'Buyruq gap fe’l bilan boshlanadi.'}]


def response(rows=None):
    return {'status':'completed','model':ASTRA,'service_tier':'default',
            'usage':{'input_tokens':100,'output_tokens':200},
            'output':[{'type':'function_call','name':'submit_lingua_batch',
                       'arguments':json.dumps({'questions':rows or QUESTIONS})}]}


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'test.sqlite3'
        self.store=Store(self.path)
        self.learning=LearningStore(self.path)
        self.learning.configure(101,'uz','en','A1','travel')


class ValidationTests(unittest.IsolatedAsyncioTestCase):
    async def test_bounded_function_envelope_without_execution_tools_or_identity(self):
        api=NS(json=AsyncMock(return_value=response()))
        result=await generate({'profile':PROFILE,'exclude':[]},api)
        self.assertEqual(len(result),4)
        sent=api.json.call_args.kwargs['payload']
        self.assertEqual(sent['model'],ASTRA)
        self.assertFalse(sent['store'])
        self.assertEqual([x['name'] for x in sent['tools']],['submit_lingua_batch'])
        self.assertEqual(json.loads(sent['input']),{'profile':PROFILE,'exclude':[]})
        self.assertLessEqual(sent['max_output_tokens'],4000)

    async def test_incomplete_refusal_unknown_function_and_malformed_rejected(self):
        variants=[{'status':'incomplete'}, {'status':'completed','output':[]},
                  {'status':'completed','output':[{'type':'function_call','name':'execute','arguments':'{}'}]},
                  {'status':'completed','output':[{'type':'function_call','name':'submit_lingua_batch','arguments':'not json'}]}]
        for data in variants:
            with self.subTest(data=data), self.assertRaises((ValueError,RuntimeError)):
                await generate({'profile':PROFILE,'exclude':[]},NS(json=AsyncMock(return_value=data)))

    def test_rejects_invalid_language_pair_profile_and_personal_data_fields(self):
        for change in ({'source':'xx'}, {'target':'uz'}, {'tier':True}, {'tier':6}, {'phone':'private'}, {'goal':'execute'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                payload({'profile':{**PROFILE,**change},'exclude':[]})
        with self.assertRaises(ValueError): payload({'profile':PROFILE,'exclude':['x']*17})

    def test_invalid_distractors_counts_long_text_and_controls_rejected(self):
        for change in ({'wrong':['I','blue']}, {'wrong':['blue','Blue!']}, {'wrong':['one']},
                       {'answer':['two words','okay']}, {'answer':['a']}, {'prompt':'x'*321},
                       {'explanation':'a\nb'}, {'answer':['!','?']}):
            with self.subTest(change=change), self.assertRaises(ValueError): question({**QUESTIONS[0],**change},0)

    async def test_duplicates_and_excluded_prompts_filtered(self):
        rows=[QUESTIONS[0],QUESTIONS[0],QUESTIONS[1],QUESTIONS[2]]
        got=await generate({'profile':PROFILE,'exclude':[QUESTIONS[1]['prompt'].upper()]},NS(json=AsyncMock(return_value=response(rows))))
        self.assertEqual(got,[QUESTIONS[0],QUESTIONS[2]])
        self.assertEqual(normalized(' HELLO, World! '),normalized('hello world'))


class QueueTests(Fixture,unittest.IsolatedAsyncioTestCase):
    def test_private_http_route_requires_signature_owner_and_blocks_replay(self):
        secret='synthetic-test-secret-at-least-32-characters'
        cls=handler(self.store,{999},secret)
        value={'owner':999,'id':'a'*32,'payload':{'profile':PROFILE,'exclude':[]}}
        def invoke(value,auth=True,headers=None):
            body=json.dumps(value).encode(); stamp=str(int(time.time())); nonce=secrets.token_hex(16)
            headers=headers or {'Content-Length':str(len(body)), 'X-Timestamp':stamp,'X-Nonce':nonce,
                'X-Signature':signature(secret,stamp,nonce,body,'/lingua/questions') if auth else 'bad'}
            instance=object.__new__(cls);instance.path='/lingua/questions';instance.headers=headers
            instance.rfile=io.BytesIO(body);instance.connection=NS(settimeout=lambda _:None)
            result=[];instance.reply=lambda status,data:result.append((status,data));instance.do_POST()
            return result[0],headers
        self.assertEqual(invoke(value,auth=False)[0][0],401)
        self.assertEqual(invoke({**value,'owner':111})[0][0],400)
        result,headers=invoke(value);self.assertEqual(result[0],200);self.assertEqual(result[1]['status'],'queued')
        self.assertEqual(invoke(value,headers=headers)[0][0],401)
        self.assertEqual(invoke(value)[0][1]['status'],'queued')

    async def test_idempotent_poll_restart_one_paid_generation_shared_ledger(self):
        upstream=NS(json=AsyncMock(side_effect=[{'input_tokens':100},response()]))
        factory=lambda ident: MeteredAPI(self.store.spending,'lingua:'+ident,upstream=upstream)
        q=GenerationQueue(self.store,api_factory=factory); ident='a'*32
        value={'profile':PROFILE,'exclude':[]}
        self.assertEqual(q.submit(ident,value)['status'],'queued')
        self.assertEqual(q.submit(ident,value)['status'],'queued')
        await q.tick()
        q=GenerationQueue(Store(self.path),api_factory=factory)
        self.assertEqual(len(q.submit(ident,value)['questions']),4)
        await q.tick();self.assertEqual(upstream.json.await_count,2)
        self.assertGreater(self.store.spending.snapshot()['accounted_usd'],0)
        with self.assertRaises(ValueError): q.submit(ident,{'profile':{**PROFILE,'goal':'exam'},'exclude':[]})

    async def test_exhausted_shared_budget_does_not_send_inference(self):
        self.store.spending.reserve(60_000_000_000,'repair:1')
        upstream=NS(json=AsyncMock(return_value={'input_tokens':100}))
        q=GenerationQueue(self.store,api_factory=lambda ident:MeteredAPI(self.store.spending,ident,upstream=upstream))
        value={'profile':PROFILE,'exclude':[]};q.submit('a'*32,value)
        await q.tick()
        self.assertEqual(q.submit('a'*32,value)['code'],'monthly_budget')
        self.assertEqual(upstream.json.await_count,1)
        self.assertEqual(upstream.json.call_args.args[1],'/responses/input_tokens')

    async def test_interrupted_processing_not_automatically_charged_again(self):
        api=NS(json=AsyncMock(return_value=response()))
        q=GenerationQueue(self.store,clock=lambda:1000,api_factory=lambda _:api)
        value={'profile':PROFILE,'exclude':[]};q.submit('b'*32,value)
        with self.store.db() as db: db.execute("UPDATE lingua_generation_jobs SET status='processing',updated=1")
        await q.tick()
        self.assertEqual(q.submit('b'*32,value)['code'],'interrupted')
        api.json.assert_not_awaited()

    def test_queue_bounded_and_poll_existing_not_subject_to_limits(self):
        q=GenerationQueue(self.store);value={'profile':PROFILE,'exclude':[]}
        for i in range(4): self.assertEqual(q.submit(f'{i:032x}',value)['status'],'queued')
        self.assertEqual(q.submit('f'*32,value)['status'],'busy')
        self.assertEqual(q.submit('0'*32,value)['status'],'queued')


class BankTests(Fixture):
    def test_every_seed_prompt_and_word_keyboard_renders_for_all_pairs(self):
        from lingua_learning import DATA, LANGS
        for q in DATA['rows']:
            for source in LANGS:
                for target in LANGS:
                    if source == target:continue
                    row={'qid':q['id'],'source':source,'target':target,'id':'a'*12,'revision':0,
                         'selected':'[]','options':json.dumps(q['answer'][target].split()),'status':'active'}
                    text,markup=exercise(row)
                    self.assertLess(len(text),4096)
                    self.assertTrue(all(len(b.callback_data.encode())<=64 for r in markup.inline_keyboard for b in r))

    def fill(self,rows=QUESTIONS):
        job=self.learning.refill(101)
        self.learning.import_batch(job,rows)
        return job

    def solve(self,row,correct=True):
        words=json.loads(row['options']); answer=question_data(row)['answer']; used=set()
        for word in answer:
            index=next(i for i,w in enumerate(words) if w==word and i not in used)
            if not used and not correct: index=next(i for i,w in enumerate(words) if w not in answer)
            used.add(index);row=self.learning.action(101,row['id'],row['revision'],str(index))
        return self.learning.action(101,row['id'],row['revision'],'check')

    def test_ai_answer_persistent_no_repeat_and_reward_once(self):
        self.fill();row=self.learning.start(101)
        self.assertTrue(row['qid'].startswith('ai_'))
        self.assertEqual(len(json.loads(row['options'])),len(question_data(row)['answer'])+2)
        self.learning=LearningStore(self.path)
        self.assertEqual(self.learning.start(101)['id'],row['id'])
        done=self.solve(row)
        self.assertIn('💡',exercise(done)[0])
        self.assertNotIn('💡',exercise(row)[0])
        self.assertEqual(done['reward'],10)
        with self.assertRaises(ValueError): self.learning.action(101,done['id'],done['revision'],'check')
        self.assertNotEqual(self.learning.start(101)['qid'],row['qid'])

    def test_dedup_across_batches_case_punctuation_answers_and_seed(self):
        job=self.fill()
        self.assertEqual(self.learning.import_batch(job,QUESTIONS),0)
        changed=copy.deepcopy(QUESTIONS)
        for q in changed: q['prompt']=q['prompt'].upper()+'!'
        self.assertEqual(self.learning.import_batch(job,changed),0)
        changed=copy.deepcopy(QUESTIONS)
        for q in changed:q['prompt']='Boshqa: '+q['prompt']
        self.assertEqual(self.learning.import_batch(job,changed),0)

    def test_adaptive_three_success_up_two_errors_down_and_no_xp_loss(self):
        self.fill()
        for _ in range(3):self.solve(self.learning.start(101))
        self.assertEqual(self.learning.profile(101)['tier'],1)
        for _ in range(2):self.solve(self.learning.start(101),False)
        self.assertEqual(self.learning.profile(101)['tier'],0)
        self.assertEqual(self.learning.profiles(101)[0]['xp'],30)

    def test_wrong_and_cross_user_ai_answers_cannot_reward(self):
        self.fill();row=self.learning.start(101)
        with self.assertRaises(ValueError): self.learning.action(202,row['id'],0,'0')
        self.assertEqual(self.solve(row,False)['reward'],0)

    def test_refill_request_survives_restart_and_contains_no_uid(self):
        job=self.learning.refill(101)
        self.assertEqual(LearningStore(self.path).refill(101)['id'],job['id'])
        self.assertNotIn('uid',job['payload']);self.assertNotIn('101',job['payload'])

    def test_old_active_attempt_survives_additive_schema_migration(self):
        row=self.learning.start(101)
        with self.learning.db() as db:
            db.execute('ALTER TABLE tg_lingua_attempts DROP COLUMN question_json')
            for c in ('tier','good','bad'):db.execute('ALTER TABLE tg_lingua_profiles DROP COLUMN '+c)
        self.learning=LearningStore(self.path)
        self.assertEqual(self.learning.start(101)['id'],row['id'])
        self.assertEqual(self.solve(self.learning.start(101))['reward'],10)


class BackgroundTests(Fixture,unittest.IsolatedAsyncioTestCase):
    async def test_prefetch_returns_immediately_coalesces_and_does_not_block_menu(self):
        learning=Learning(self.path,'',lambda *a:None,owners={999})
        gate=asyncio.Event();calls=[];tasks=[]
        async def request(path,value):
            calls.append(value);await gate.wait();return {'status':'done','questions':QUESTIONS}
        def create(coro):
            task=asyncio.create_task(coro);tasks.append(task);return task
        app=NS(create_task=create)
        with patch('maintainer_client.enabled',return_value=True),patch('maintainer_client.request',side_effect=request):
            first=learning.prefetch(101,app)
            self.assertIs(learning.prefetch(101,app),first)
            await asyncio.sleep(0);self.assertFalse(first.done())
            # Rendering a menu and starting a cached exercise never waits on AI.
            self.assertTrue(exercise(learning.store.start(101))[0])
            gate.set();await asyncio.gather(*tasks)
        self.assertEqual(len(calls),1)
        self.assertEqual(calls[0]['owner'],999)
        self.assertNotIn('101',json.dumps(calls[0]))

    async def test_navigation_cancels_late_notification_and_network_retains_job(self):
        learning=Learning(self.path,'',lambda *a:None,owners={999})
        job=learning.store.refill(101)
        with patch('maintainer_client.request',side_effect=RuntimeError('synthetic')):
            self.assertFalse(await learning.fetch_batch(job))
        self.assertEqual(learning.store.refill(101)['id'],job['id'])
        task=asyncio.create_task(asyncio.sleep(0,result=True))
        bot=NS(send_message=AsyncMock())
        up=NS(get_bot=lambda:bot,effective_chat=NS(id=101))
        await learning.notify_ready(task,up,NS(user_data={}), 'cancelled-token')
        bot.send_message.assert_not_awaited()


if __name__=='__main__':unittest.main()
