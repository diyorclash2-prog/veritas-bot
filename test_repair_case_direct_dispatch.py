"""Owner reports enter real code inspection, independent of advisory AI calls."""
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, patch

from telegram.ext import ApplicationHandlerStop
from super_settings import ErrorSummary, SuperSettings
from test_super_settings import update


class DirectRepairTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'bot.db'
        self.app = NS(bot_data={}, job_queue=None, running=False)
        self.ai = AsyncMock(side_effect=RuntimeError('ADVISORY MUST NOT RUN'))
        self.bridge = SuperSettings(self.path, {123}, self.app, ai=self.ai, clock=lambda:1000)
        self.ctx = NS(bot=NS(send_message=AsyncMock()), args=None)
        self.env = patch.dict(os.environ, {'VERITAS_AUTOREPAIR_ENABLED':'1',
            'VERITAS_MAINTAINER_URL':'http://maintainer.railway.internal'})
        self.env.start()
        self.addCleanup(self.env.stop)

    def submit(self):
        return self.bridge.reports.submit(123, 1, 'The test button does not work', 1000)

    async def test_advisory_outage_cannot_block_real_code_inspection(self):
        ident = self.submit()
        await self.bridge.tick(self.ctx)
        await self.bridge.tick(self.ctx)
        self.ai.assert_not_awaited()
        self.assertIsNone(self.bridge.repairs.store.get(ident,123))
        self.assertEqual(self.bridge.reports.recent(123)[0]['status'],'repairing')
        self.ctx.bot.send_message.assert_awaited_once()
        self.assertIn('Avtomatik tuzatish',self.ctx.bot.send_message.call_args.kwargs['text'])
        self.assertNotIn('Bu AI tahlili',self.ctx.bot.send_message.call_args.kwargs['text'])

    async def test_evidence_is_persisted_redacted_and_retries_are_identical(self):
        self.submit()
        self.bridge.errors.events.append({'error':'TimeoutError','module':'bot',
                                         'function':'autobook_job','line':8061})
        await self.bridge.tick(self.ctx)
        # A changed snapshot after restart must not cause a remote job identity conflict.
        restarted = SuperSettings(self.path,{123},self.app,ai=self.ai,clock=lambda:1010)
        calls = []
        async def network(path,value):
            if path == '/jobs':
                calls.append(value)
                if len(calls)==1: raise RuntimeError('unknown network outcome')
                return {'ok':True,'id':value['id']}
            return {'ok':True,'status':'drafting','message':'Astra kodni tekshiryapti'}
        with patch('maintainer_client.request',new=network):
            await restarted.remote_tick(self.ctx)
            await restarted.remote_tick(self.ctx)
        self.assertEqual(len(calls),2)
        self.assertEqual(calls[0],calls[1])
        self.assertIn('autobook_job',calls[0]['report'])
        self.assertIn('TimeoutError',calls[0]['report'])
        self.assertLessEqual(len(calls[0]['report']),2000)

    async def test_snapshot_failure_does_not_block_dispatch(self):
        self.submit()
        self.bridge.snapshot = lambda: (_ for _ in ()).throw(RuntimeError('private failure'))
        await self.bridge.tick(self.ctx)
        request = AsyncMock(side_effect=[{'ok':True,'id':1},
            {'ok':True,'status':'ci','message':'Mustaqil testlar ishlayapti'}])
        with patch('maintainer_client.request',new=request):
            await self.bridge.remote_tick(self.ctx)
        self.assertEqual(request.call_args_list[0].args[0],'/jobs')
        self.assertNotIn('private failure',request.call_args_list[0].args[1]['report'])

    async def test_live_state_replaces_old_advisory_in_history_and_is_cached(self):
        ident = self.submit()
        await self.bridge.tick(self.ctx)
        with self.bridge.reports.db() as db:
            db.execute("UPDATE super_incidents SET status='reviewed',result='NO FILESYSTEM ACCESS' WHERE id=?",(ident,))
            db.execute("UPDATE super_remote_outbox SET status='accepted' WHERE id=?",(ident,))
        up = update(data='supercfg:reports')
        with patch('maintainer_client.request',new=AsyncMock(return_value={
                'ok':True,'status':'verified','message':'Yangi kod ishga tushdi'})):
            with self.assertRaises(ApplicationHandlerStop):
                await self.bridge.callback(up,self.ctx)
        up.callback_query.message.reply_text.assert_awaited_once()
        self.assertIn('Yangi kod ishga tushdi',up.callback_query.message.reply_text.call_args.args[0])
        self.assertNotIn('NO FILESYSTEM',up.callback_query.message.reply_text.call_args.args[0])
        restarted = SuperSettings(self.path,{123},self.app,clock=lambda:1010)
        self.assertIn('Yangi kod ishga tushdi',restarted.report_text(restarted.reports.recent(123)[0]))

    async def test_no_change_is_not_reported_as_a_verified_fix(self):
        self.submit()
        await self.bridge.tick(self.ctx)
        row = self.bridge.reports.recent(123)[0]
        with patch('maintainer_client.request',new=AsyncMock(return_value={
                'ok':True,'status':'no_change','message':'Asoslangan tuzatish topilmadi'})):
            await self.bridge.refresh_remote(row)
        self.assertIn('topilmadi',self.bridge.report_text(row))
        self.assertNotIn('Yangi kod ishga tushdi',self.bridge.report_text(row))

    async def test_expired_delivery_is_reported_and_never_submitted(self):
        self.submit()
        await self.bridge.tick(self.ctx)
        self.bridge.clock = lambda:5001
        request = AsyncMock()
        with patch('maintainer_client.request',new=request):
            await self.bridge.remote_tick(self.ctx)
        request.assert_not_awaited()
        self.assertIn('yuborilmadi',self.bridge.report_text(self.bridge.reports.recent(123)[0]))

    async def test_evidence_excludes_contacts_secrets_and_arbitrary_snapshot_values(self):
        self.bridge.snapshot = lambda:{'database_readable':True,'phone':'PRIVATE_PHONE',
            'advertisements':{'message':'PRIVATE_TEXT'},'recent_errors':[{
                'error':'TimeoutError','module':'bot','function':'autobook_job','line':8061,
                'args':'PRIVATE_ARGS','locals':'PRIVATE_LOCALS',
                'frames':[{'module':'bot','function':'autobook_run','line':8051,'secret':'PRIVATE_KEY'}]}]}
        evidence = self.bridge.repair_evidence()
        self.assertNotIn('PRIVATE',evidence)
        self.assertIn('autobook_run',evidence)
        json.loads(evidence)

    async def test_revoked_owner_is_not_dispatched(self):
        self.submit()
        await self.bridge.tick(self.ctx)
        self.bridge.owners = frozenset()
        request = AsyncMock()
        with patch('maintainer_client.request',new=request):
            await self.bridge.remote_tick(self.ctx)
        request.assert_not_awaited()


class TraceMetadataTests(unittest.TestCase):
    def test_trace_has_source_location_but_never_exception_text_or_locals(self):
        handler = ErrorSummary()
        try:
            exec(compile('def broken():\n secret="PRIVATE_LOCAL"\n raise TimeoutError("PRIVATE_ERROR")\nbroken()',
                         'bot.py','exec'),{})
        except TimeoutError:
            record = logging.LogRecord('bot',logging.ERROR,'bot.py',8061,
                                       'PRIVATE_LOG',(),sys.exc_info())
        handler.emit(record)
        event = handler.events[0]
        self.assertIn('frames',event)
        self.assertEqual(event['frames'][-1],{'module':'bot','function':'broken','line':3})
        self.assertNotIn('PRIVATE',json.dumps(event))


if __name__ == '__main__':
    unittest.main()
