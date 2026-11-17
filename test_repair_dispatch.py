import asyncio
import json
import os
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import httpx
import maintainer_client
from maintainer_client import MaintainerError, signature
from maintainer_service import Store, JobRejected, handler
from super_settings import SuperSettings


class RejectionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.now = 100000
        self.bridge = SuperSettings(Path(self.tmp.name)/'bot.db', {123},
                                   NS(bot_data={},job_queue=None,running=False),clock=lambda:self.now)
        self.ctx = NS(bot=NS(send_message=AsyncMock()))
        self.env = patch.dict(os.environ,{'VERITAS_AUTOREPAIR_ENABLED':'1',
            'VERITAS_MAINTAINER_URL':'http://maintainer.railway.internal'})
        self.env.start(); self.addCleanup(self.env.stop)

    async def queue(self, message_id=1):
        ident = self.bridge.reports.submit(123,message_id,'Botdagi tugmani tekshirib tuzat',self.now)
        await self.bridge.tick(self.ctx)
        self.ctx.bot.send_message.reset_mock()
        return ident

    def state(self, ident):
        with self.bridge.reports.db() as db:
            return db.execute('SELECT status FROM super_remote_outbox WHERE id=?',(ident,)).fetchone()[0]

    async def test_daily_limit_replies_once_without_retrying_or_running_ai(self):
        ident = await self.queue()
        with patch('maintainer_client.request',new=AsyncMock(side_effect=MaintainerError(429,'daily_limit',7200))) as remote:
            await self.bridge.remote_tick(self.ctx)
            await self.bridge.tick(self.ctx)
            await self.bridge.remote_tick(self.ctx)
            await self.bridge.tick(self.ctx)
        self.assertEqual(self.state(ident),'failed')
        remote.assert_awaited_once()
        self.ctx.bot.send_message.assert_awaited_once()
        message = self.ctx.bot.send_message.call_args.kwargs
        self.assertEqual(message['chat_id'],123)
        self.assertIn('3 ta',message['text'])
        self.assertIn('120 daqiqa',message['text'])
        self.assertIsNone(self.bridge.repairs.store.get(ident,123))
        with self.bridge.reports.db() as db:
            self.assertEqual(db.execute('SELECT notification FROM super_incidents WHERE id=?',(ident,)).fetchone()[0],'sent')

    async def test_permanent_rejection_does_not_block_later_pending_job(self):
        first, second = await self.queue(1), await self.queue(2)
        with patch('maintainer_client.request',new=AsyncMock(side_effect=MaintainerError(400,'invalid_request'))):
            await self.bridge.remote_tick(self.ctx)
        with patch('maintainer_client.request',new=AsyncMock(return_value={'ok':True,'id':second})):
            await self.bridge.remote_tick(self.ctx)
        self.assertEqual(self.state(first),'failed')
        self.assertEqual(self.state(second),'accepted')

    async def test_transient_submission_failure_still_refreshes_accepted_job(self):
        accepted = await self.queue(1)
        with self.bridge.reports.db() as db:
            db.execute("UPDATE super_remote_outbox SET status='accepted' WHERE id=?",(accepted,))
        pending = await self.queue(2)
        async def remote(path,value):
            if path == '/jobs': raise MaintainerError(503)
            return {'ok':True,'status':'verified','message':'Tasdiqlangan natija'}
        with patch('maintainer_client.request',new=AsyncMock(side_effect=remote)):
            await self.bridge.remote_tick(self.ctx)
        self.assertEqual(self.state(pending),'pending')
        self.assertEqual(self.state(accepted),'verified')

    async def test_expired_dispatch_gets_terminal_explanation(self):
        ident = await self.queue()
        self.now += 3601
        with patch('maintainer_client.request',new=AsyncMock()) as remote:
            await self.bridge.remote_tick(self.ctx)
            await self.bridge.tick(self.ctx)
        remote.assert_not_awaited()
        self.assertEqual(self.state(ident),'failed')
        self.assertIn('muddati tugadi',self.ctx.bot.send_message.call_args.kwargs['text'])

    async def test_revoked_owner_does_not_get_rejection_notification(self):
        ident = await self.queue()
        self.bridge.owners = frozenset()
        with patch('maintainer_client.request',new=AsyncMock()) as remote:
            await self.bridge.remote_tick(self.ctx)
            await self.bridge.tick(self.ctx)
        remote.assert_not_awaited()
        self.ctx.bot.send_message.assert_not_awaited()
        self.assertEqual(self.state(ident),'failed')


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_client_retains_only_safe_error_metadata(self):
        cases = [
            (429,{'code':'daily_limit','retry_after':90,'error':'SECRET'},True,'daily_limit'),
            (429,{'error':'SECRET'},False,''),
            (503,{'error':'SECRET'},False,''),
            (400,{'code':['SECRET'],'retry_after':'SECRET'},True,''),
            (401,{'code':'authentication'},True,'authentication'),
            (409,{'code':'job_conflict'},True,'job_conflict'),
        ]
        for status, body, permanent, code in cases:
            with self.subTest(status=status,body=body):
                client = httpx.AsyncClient(transport=httpx.MockTransport(lambda req:httpx.Response(status,json=body)))
                with patch.dict(os.environ,{'VERITAS_MAINTAINER_URL':'http://maintainer.railway.internal',
                    'VERITAS_MAINTAINER_SECRET':'synthetic-secret-for-protocol-tests-only'}), patch('maintainer_client.httpx.AsyncClient',return_value=client):
                    with self.assertRaises(MaintainerError) as caught:
                        await maintainer_client.request('/jobs',{'id':1})
                error = caught.exception
                self.assertEqual(error.permanent,permanent)
                self.assertEqual(error.code,code)
                self.assertNotIn('SECRET',str(error)+error.user_message)

    def test_store_preserves_limit_idempotency_and_expiry(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp)/'queue.db')
            for ident in (1,2,3):
                store.enqueue({'id':ident,'owner':123,'report':'Tugma ishlamayapti'},{123},1000+ident)
            job = {'id':4,'owner':123,'report':'Tugma ishlamayapti'}
            with self.assertRaises(JobRejected) as caught: store.enqueue(job,{123},1004)
            self.assertEqual((caught.exception.code,caught.exception.status,caught.exception.retry_after),('daily_limit',429,86397))
            self.assertIsNone(store.get(4))
            store.enqueue({**job,'id':1},{123},1004)
            with self.assertRaises(JobRejected) as conflict:
                store.enqueue({**job,'id':1,'report':'Boshqa tugma ishlamayapti'},{123},1004)
            self.assertEqual(conflict.exception.status,409)
            store.enqueue(job,{123},87401)
            self.assertIsNotNone(store.get(4))

    def test_http_handler_explains_limit_without_leaking_report(self):
        import io
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp)/'queue.db')
            for ident in (1,2,3):
                store.enqueue({'id':ident,'owner':123,'report':'Private test incident'},{123},1000)
            body = json.dumps({'id':4,'owner':123,'report':'PRIVATE CONTENT'}).encode()
            secret, nonce, stamp = 'synthetic-secret-for-handler-test-only','a'*32,'1001'
            headers = {'Content-Length':str(len(body)),'X-Timestamp':stamp,'X-Nonce':nonce,
                       'X-Signature':signature(secret,stamp,nonce,body,'/jobs')}
            request = NS(path='/jobs',headers=headers,rfile=io.BytesIO(body),
                         connection=NS(settimeout=lambda timeout:None),reply=lambda code,value: replies.append((code,value)))
            replies = []
            with patch('maintainer_service.time.time',return_value=1001),patch('maintainer_service.configured',return_value=True):
                handler(store,{123},secret).do_POST(request)
            self.assertEqual(replies,[(429,{'ok':False,'code':'daily_limit','retry_after':86399})])
            self.assertNotIn('PRIVATE',json.dumps(replies))
            self.assertIsNone(store.get(4))


if __name__ == '__main__': unittest.main()
