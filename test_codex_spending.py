import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import io
from pathlib import Path
import shutil
import tempfile
import unittest
import urllib.request
import urllib.error
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace as NS

from ai_spending import BudgetError, Spending, MeteredAPI, UNIT, LIMIT, INPUT_RATE, OUTPUT_RATE
from astra_support import ASTRA, AIUnavailable
from codex_proposer import CodexProposer, ModelGateway, response_events, source_only_input, TOOL_CHOICE
from repair_jobs import SOURCE_FILES
from super_settings import Reports, menu, API_BILLING_URL, SuperSettings
from maintainer_service import Store, handler
from maintainer_client import signature
from test_super_settings import update
from telegram.ext import ApplicationHandlerStop

NOW = datetime(2026,11,17,18,tzinfo=timezone.utc).timestamp()


class SpendingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.db = Reports(Path(self.tmp.name)/'budget.db')
        self.book = Spending(self.db,clock=lambda:NOW)
        self.api = AsyncMock()
        self.api.json.side_effect = [
            {'input_tokens':100},
            {'status':'completed','model':ASTRA,'service_tier':'default','output':[],
             'usage':{'input_tokens':100,'output_tokens':20}}]
        self.payload = {'model':ASTRA,'input':'Test task','max_output_tokens':100}

    async def test_counts_before_atomic_reservation_then_settles_including_reasoning(self):
        await MeteredAPI(self.book,'repair:1',upstream=self.api).json('POST','/responses',payload=self.payload)
        self.assertEqual(self.api.json.call_args_list[0].args[1],'/responses/input_tokens')
        self.assertEqual(self.book.snapshot()['accounted_usd'],(100*INPUT_RATE+20*OUTPUT_RATE)/UNIT)
        self.assertEqual(self.book.snapshot()['reserved_usd'],0)
        self.assertEqual(self.api.json.call_args.kwargs['payload']['service_tier'],'default')

    async def test_full_budget_does_not_send_generation(self):
        self.book.reserve(LIMIT,'prior')
        with self.assertRaises(BudgetError):
            await MeteredAPI(self.book,'repair:1',upstream=self.api).json('POST','/responses',payload=self.payload)
        self.api.json.assert_awaited_once()

    async def test_unknown_outcome_blocks_new_work_and_survives_restart(self):
        self.api.json.side_effect = [{'input_tokens':100},TimeoutError()]
        with self.assertRaises(TimeoutError):
            await MeteredAPI(self.book,'repair:1',upstream=self.api).json('POST','/responses',payload=self.payload)
        reopened = Spending(self.db,clock=lambda:NOW)
        self.assertGreater(reopened.snapshot()['reserved_usd'],0)
        with self.assertRaises(BudgetError): reopened.reserve(UNIT,'second')

    async def test_unknown_model_or_hosted_tool_cannot_start_request(self):
        for change in ({'model':'unknown'},{'tools':[{'type':'web_search'}]},
                       {'max_output_tokens':100000},{'background':True}):
            with self.assertRaises(BudgetError):
                await MeteredAPI(self.book,'repair:1',upstream=self.api).json(
                    'POST','/responses',payload={**self.payload,**change})
        self.api.json.assert_not_awaited()

    async def test_rejected_credit_request_can_resume_after_funding(self):
        self.api.json.side_effect = [{'input_tokens':100},AIUnavailable('quota',429)]
        with self.assertRaises(AIUnavailable):
            await MeteredAPI(self.book,'repair:1',upstream=self.api).json('POST','/responses',payload=self.payload)
        self.assertEqual(self.book.snapshot()['remaining_usd'],60)
        self.assertFalse(self.book.snapshot()['blocked'])

    def test_previous_month_task_total_survives_month_reset(self):
        ident = self.book.reserve(UNIT,'repair:old')
        self.book.settle(ident,UNIT)
        book = Spending(self.db,clock=lambda:datetime(2026,12,5,tzinfo=timezone.utc).timestamp())
        self.assertEqual(book.snapshot('repair:old')['task_usd'],1)
        self.assertEqual(book.snapshot()['remaining_usd'],60)

    def test_concurrent_workers_cannot_reserve_same_dollars(self):
        def reserve(_):
            try: return self.book.reserve(40*UNIT,'job')
            except BudgetError: return None
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(reserve,[1,2]))
        self.assertEqual(sum(r is not None for r in results),1)
        self.assertEqual(self.book.snapshot()['remaining_usd'],20)

    def test_unknown_reservation_is_not_forgotten_next_month(self):
        self.book.reserve(50*UNIT,'prior')
        future = datetime(2026,12,5,tzinfo=timezone.utc).timestamp()
        book = Spending(self.db,clock=lambda:future)
        self.assertEqual(book.snapshot()['remaining_usd'],10)

    def test_new_york_month_and_rollover_guard(self):
        # UTC December 1 still belongs to November in New York.
        stamp = datetime(2026,12,1,4,59,tzinfo=timezone.utc).timestamp()
        book = Spending(self.db,clock=lambda:stamp)
        self.assertEqual(book.snapshot()['period'],'2026-11')
        with self.assertRaises(BudgetError): book.reserve(UNIT,'boundary')

    def test_official_billing_button_has_no_payment_callback(self):
        buttons = [b for row in menu().inline_keyboard for b in row if b.url==API_BILLING_URL]
        self.assertEqual(len(buttons),1)
        self.assertIsNone(buttons[0].callback_data)


class BudgetInterfaceTests(unittest.IsolatedAsyncioTestCase):
    async def test_budget_menu_only_available_to_private_owner_and_keeps_payment_link(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge = SuperSettings(Path(tmp)/'bot.db',{123},NS(bot_data={},job_queue=None))
            book = Spending(bridge.reports,clock=lambda:NOW)
            data={'ok':True,'budget':book.snapshot(),'tasks':[{'id':7,'usd':1.25}]}
            with patch('maintainer_client.request',new=AsyncMock(return_value=data)) as remote:
                for owner,kind in ((999,'private'),(123,'group'),(123,'private')):
                    up=update(owner=owner,chat_type=kind,data='supercfg:budget')
                    with self.assertRaises(ApplicationHandlerStop): await bridge.callback(up,NS())
                    if kind=='private' and owner==123:
                        args=up.effective_message.reply_text.call_args
                        self.assertIn('#7: $1.2500',args.args[0])
                        self.assertIn('rasmiy hisob-faktura yoki API balansi emas',args.args[0])
                        self.assertTrue(any(b.url==API_BILLING_URL for row in args.kwargs['reply_markup'].inline_keyboard for b in row))
                    else: up.effective_message.reply_text.assert_not_awaited()
                remote.assert_awaited_once_with('/budget',{'owner':123})

    def test_budget_endpoint_authentication_and_owner_isolation(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'service.db'); store.spending.clock=lambda:NOW
            store.enqueue({'id':1,'owner':123,'report':'Private owner task'},{123},NOW)
            store.enqueue({'id':2,'owner':456,'report':'Other owner task'},{456},NOW)
            secret='synthetic-long-secret-for-budget-test'
            def request(owner,nonce,valid=True):
                body=json.dumps({'owner':owner}).encode(); stamp=str(int(NOW)); replies=[]
                headers={'Content-Length':str(len(body)),'X-Timestamp':stamp,'X-Nonce':nonce,
                         'X-Signature':signature(secret,stamp,nonce,body,'/budget') if valid else 'bad'}
                req=NS(path='/budget',headers=headers,rfile=io.BytesIO(body),
                       connection=NS(settimeout=lambda _:None),reply=lambda code,value:replies.append((code,value)))
                with patch('maintainer_service.time.time',return_value=NOW): handler(store,{123,456},secret).do_POST(req)
                return replies[0]
            self.assertEqual(request(123,'a'*32,False)[0],401)
            self.assertEqual(request(999,'b'*32)[0],400)
            code,value=request(123,'c'*32)
            self.assertEqual(code,200)
            self.assertEqual([t['id'] for t in value['tasks']],[1])
            self.assertNotIn('Private owner task',json.dumps(value))


class CodexTests(unittest.IsolatedAsyncioTestCase):
    def test_native_catalog_removed_but_owner_and_source_history_preserved(self):
        history=[{'role':'user','content':'Inspect bot'},
                 {'type':'reasoning','encrypted_content':'synthetic'},
                 {'type':'function_call','name':'read_source','call_id':'c1','arguments':'{}'},
                 {'type':'function_call_output','call_id':'c1','output':'value=1'}]
        catalog={'type':'additional_tools','tools':[{'type':'custom','name':'exec'}]}
        self.assertEqual(source_only_input([catalog,{'role':'developer','content':'Use exec'},
                                           {'role':'system','content':'Native harness'},*history]),history)
        for item in ({'type':'custom_tool_call','name':'exec'},
                     {'type':'function_call','name':'exec_command'},None):
            with self.subTest(item=item),self.assertRaises(AIUnavailable): source_only_input([item])

    def test_native_tool_response_is_never_forwarded_to_codex(self):
        for kind in ('custom_tool_call','computer_call','shell_call'):
            with self.assertRaises(ValueError): response_events({'output':[{'type':kind}]})
        with self.assertRaises(ValueError):
            response_events({'output':[{'type':'function_call','name':'exec_command'}]})

    @unittest.skipUnless(shutil.which('codex'),'Real Codex binary not installed in this test environment')
    async def test_real_codex_process_uses_bounded_source_tools_with_mock_provider(self):
        await self.run_codex_scenario(reject_native=False)

    @unittest.skipUnless(shutil.which('codex'),'Real Codex binary not installed in this test environment')
    async def test_real_codex_recovers_from_native_exec_without_executing_it(self):
        await self.run_codex_scenario(reject_native=True)

    async def run_codex_scenario(self, *, reject_native):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in SOURCE_FILES: (root/name).write_text('value = 1\n')
            edits = [{'path':'bot.py','search':'value = 1','replace':'value = 2'},
                {'path':'test_repair_case_codex.py','search':'','replace':
                 'import unittest\nfrom bot import value\nclass T(unittest.TestCase):\n def test_value(self): self.assertEqual(value,2)\n'}]
            calls=[]
            async def response(method,path,*,payload):
                calls.append(payload)
                n=len(calls)
                if reject_native and n==2:
                    return {'status':'completed','output':[{'type':'custom_tool_call',
                        'id':'native_exec','call_id':'native_call','name':'exec',
                        'input':"raise RuntimeError('UNTRUSTED_NATIVE_COMMAND')"}]}
                name,args = ('read_source',{'path':'bot.py','start_line':1,'count':10}) if n==1 else (
                    'submit_patch',{'summary':'Qiymat tuzatildi.','edits':edits})
                return {'id':'resp_'+str(n),'object':'response','status':'completed',
                    'model':ASTRA,'service_tier':'default','usage':{'input_tokens':100,'output_tokens':30,'total_tokens':130},
                    'output':[{'id':'fc_'+str(n),'type':'function_call','status':'completed',
                               'call_id':'call_'+str(n),'name':name,'arguments':json.dumps(args)}]}
            api=AsyncMock(); api.json.side_effect=response
            result=await asyncio.wait_for(CodexProposer(root,api=api).propose('Botdagi qiymatni tuzat'),timeout=40)
            self.assertIn(b'+value = 2',result['patch'])
            self.assertEqual((root/'bot.py').read_text(),'value = 1\n')
            self.assertEqual(len(calls),3 if reject_native else 2)
            self.assertTrue(all(t['type']=='function' for p in calls for t in p['tools']))
            self.assertTrue(all(p['tool_choice']==TOOL_CHOICE for p in calls))
            for p in calls:
                self.assertTrue(all(i.get('type')!='additional_tools' for i in p['input']))
                self.assertFalse(any(i.get('role') in {'developer','system'} for i in p['input'][:-1]))
            if reject_native:
                self.assertIn('was NOT executed',calls[2]['input'][-1]['content'])
                self.assertNotIn('UNTRUSTED_NATIVE_COMMAND',json.dumps(calls))


class GatewayRecoveryTests(unittest.TestCase):
    def request(self,gateway):
        request=urllib.request.Request(gateway.url+'/responses',
            data=json.dumps({'model':ASTRA,'input':[{'role':'user','content':'Repair task'}]}).encode(),
            headers={'Authorization':'Bearer '+gateway.token,'Content-Type':'application/json'})
        try:
            with urllib.request.urlopen(request,timeout=5) as response: return response.status,response.read()
        except urllib.error.HTTPError as exc: return exc.code,exc.read()

    def test_persistent_native_calls_stop_with_safe_reason_and_all_attempts_are_metered(self):
        with tempfile.TemporaryDirectory() as tmp:
            book=Spending(Reports(Path(tmp)/'spend.db'),clock=lambda:NOW)
            upstream=AsyncMock()
            async def respond(method,path,*,payload):
                if path.endswith('/input_tokens'): return {'input_tokens':100}
                return {'model':ASTRA,'service_tier':'default','status':'completed',
                    'usage':{'input_tokens':100,'output_tokens':20},
                    'output':[{'type':'custom_tool_call','name':'exec','input':'SECRET_COMMAND'}]}
            upstream.json.side_effect=respond
            with ModelGateway(MeteredAPI(book,'repair:5',upstream=upstream)) as gateway:
                status,body=self.request(gateway)
                self.assertEqual(status,502)
                self.assertEqual(gateway.calls,2)
                self.assertIsInstance(gateway.error,AIUnavailable)
                self.assertEqual(gateway.error.code,'unsupported_tool')
                self.assertNotIn(b'SECRET_COMMAND',body)
            self.assertEqual(book.snapshot()['accounted_usd'],2*(100*INPUT_RATE+20*OUTPUT_RATE)/UNIT)
            self.assertEqual(book.snapshot()['reserved_usd'],0)
            self.assertFalse(book.snapshot()['blocked'])

    def test_retry_cannot_exceed_twenty_four_total_model_calls(self):
        api=AsyncMock(); api.json.return_value={'status':'completed','output':[{'type':'custom_tool_call'}]}
        with ModelGateway(api) as gateway:
            gateway.calls=23
            self.assertEqual(self.request(gateway)[0],502)
            self.assertEqual(gateway.calls,24)
            self.assertEqual(gateway.error.code,'coding_call_limit')
            api.json.assert_awaited_once()

    def test_entire_response_validated_before_forwarding_even_when_valid_call_comes_first(self):
        for bad in (None,[],[None],[{'type':'message','content':[]}],
                    [{'type':'function_call','name':'read_source'},{'type':'shell_call'}]):
            with self.subTest(output=bad),self.assertRaises(ValueError):
                response_events({'output':bad})


if __name__=='__main__': unittest.main()
