import asyncio
import json
import os
from pathlib import Path
import tempfile
import subprocess
import sys
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, patch
import httpx

from astra_proposer import Proposer
from github_release import GitHub, GitHubError, PREFIX, REPO, PROJECT, SERVICE, ENVIRONMENT
from maintainer_client import signature
from maintainer_service import Store, Controller
from repair_jobs import SOURCE_FILES
from super_settings import SuperSettings

A, B, C = 'a'*40, 'b'*40, 'c'*40


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for name in SOURCE_FILES: (self.root/name).write_text('value = 1\n')


class ProposerTests(Fixture, unittest.IsolatedAsyncioTestCase):
    def test_reads_only_source_and_omits_large_embedded_data(self):
        (self.root/'bot.py').write_text('name = "'+ 'x'*2000+'"\nvalue = 1\n')
        proposer = Proposer(self.root)
        self.assertIn('omitted',proposer.read('bot.py',1,2))
        self.assertIn('2: value = 1',proposer.read('bot.py',1,2))
        for name in ('../bot.py','.env','/etc/passwd'):
            with self.assertRaises(ValueError): proposer.read(name,1,10)
        with self.assertRaises(ValueError): proposer.read('bot.py',1,121)

    def edits(self):
        return [{'path':'bot.py','search':'value = 1','replace':'value = 2'},
                {'path':'test_repair_case_value.py','search':'', 'replace':'import unittest\nfrom bot import value\nclass T(unittest.TestCase):\n def test_value(self): self.assertEqual(value,2)\n'}]

    def test_proposal_does_not_execute_or_write_changed_code(self):
        proposer = Proposer(self.root)
        result = proposer.apply('Taklif',self.edits())
        self.assertIn(b'+value = 2',result['patch'])
        self.assertEqual((self.root/'bot.py').read_text(),'value = 1\n')
        self.assertFalse((self.root/'test_repair_case_value.py').exists())

    def test_protected_files_ambiguous_edits_and_missing_regression_fail(self):
        proposer = Proposer(self.root)
        for edits in ([{'path':'repair_jobs.py','search':'value = 1','replace':'value = 2'}],
                      [{'path':'bot.py','search':'missing','replace':'value = 2'}],self.edits()[:1]):
            with self.assertRaises(ValueError): proposer.apply('Taklif',edits)

    async def test_responses_tools_have_no_execution_or_external_write_capability(self):
        api = AsyncMock()
        api.json.side_effect = [
            {'status':'completed','output':[{'type':'function_call','name':'read_source','call_id':'read',
             'arguments':json.dumps({'path':'bot.py','start_line':1,'count':5})}]},
            {'status':'completed','output':[{'type':'function_call','name':'submit_patch','call_id':'done',
             'arguments':json.dumps({'summary':'Taklif','edits':self.edits()})}]}]
        result = await Proposer(self.root,api).propose('value should be two')
        self.assertEqual(result['status'],'candidate')
        payload = api.json.call_args.kwargs['payload']
        self.assertFalse(payload['store'])
        self.assertEqual(payload['model'],'gpt-6-astra')
        self.assertEqual({t['name'] for t in payload['tools']},{'source_index','read_source','find_source','submit_patch'})


class StoreTests(Fixture):
    def test_authentication_rejects_tampering_expiry_and_replay(self):
        store = Store(self.root/'queue.db'); secret = 'synthetic-credential-for-tests-only'
        body = b'{"id":1}'
        headers = {'X-Timestamp':'1000','X-Nonce':'a'*32}
        headers['X-Signature'] = signature(secret,'1000','a'*32,body)
        self.assertFalse(store.authenticate(headers,b'changed',secret,1000))
        self.assertFalse(store.authenticate(headers,body,secret,1000,'/jobs'))
        self.assertFalse(store.authenticate(headers,body,secret,1200))
        self.assertTrue(store.authenticate(headers,body,secret,1000))
        self.assertFalse(store.authenticate(headers,body,secret,1000))

    def test_job_is_private_durable_idempotent_and_limited(self):
        store = Store(self.root/'queue.db')
        job = {'id':1,'owner':123,'report':'Tugma ishlamayapti token=hidden'}
        store.enqueue(job,{123},1000); store.enqueue(job,{123},1000)
        reopened = Store(self.root/'queue.db')
        self.assertNotIn('hidden',reopened.get(1)['report'])
        with self.assertRaises(ValueError): store.enqueue({**job,'owner':999},{123,999},1000)
        for i in (2,3): store.enqueue({**job,'id':i},{123},1000)
        with self.assertRaises(ValueError): store.enqueue({**job,'id':4},{123},1000)

    def test_heartbeat_must_be_fresh_and_match_exact_commit(self):
        store = Store(self.root/'queue.db'); store.heartbeat(A,1000)
        self.assertTrue(store.healthy(A,900,1050))
        self.assertFalse(store.healthy(B,900,1050))
        self.assertFalse(store.healthy(A,1001,1050))
        self.assertFalse(store.healthy(A,900,1100))


class ControllerTests(Fixture,unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        super().setUp()
        self.store = Store(self.root/'queue.db')
        self.store.enqueue({'id':1,'owner':123,'report':'Tugma ishlamayapti'},{123},1000)
        self.now = 1001
        self.gh = AsyncMock(); self.gh.main.return_value=A; self.gh.deployment.return_value='success'
        self.gh.commit.return_value=B; self.gh.open_pr.return_value=7; self.gh.ci.return_value='pending'
        self.gh.rollback_commit.return_value=C
        self.notify = AsyncMock()
        self.worker = Controller(self.store,self.root/'snapshots',{123},github=self.gh,clock=lambda:self.now,notify=self.notify)

    def state(self,phase,**fields):
        self.store.update(1,1000,phase=phase,base=A,head=B,pr=7,**fields)

    async def tick(self): await self.worker.tick()

    async def test_failed_ci_never_promotes(self):
        self.state('ci'); self.gh.ci.return_value='failure'
        await self.tick()
        self.gh.promote.assert_not_called()
        self.assertEqual(self.store.get(1)['phase'],'failed')

    async def test_exact_ci_is_rechecked_before_promotion(self):
        self.state('promoting'); self.gh.ci.return_value='pending'
        await self.tick()
        self.gh.promote.assert_not_called()

    async def test_changed_main_cannot_publish_old_snapshot(self):
        self.state('publishing'); self.gh.main.return_value=C
        await self.tick(); self.gh.commit.assert_not_called()

    async def test_railway_success_without_bot_heartbeat_is_not_success(self):
        self.state('deploying'); await self.tick()
        self.assertEqual(self.store.get(1)['phase'],'deploying')
        self.notify.assert_not_called()
        self.store.heartbeat(B,1001); await self.tick()
        self.assertEqual(self.store.get(1)['phase'],'verified')
        self.notify.assert_awaited_once()
        await self.tick(); self.notify.assert_awaited_once()

    async def test_bot_deploy_failure_rolls_back_and_waits_for_health(self):
        self.state('deploying'); self.gh.deployment.return_value='failure'
        await self.tick(); self.assertEqual(self.store.get(1)['phase'],'rollback_prepare')
        await self.tick(); self.assertEqual(self.store.get(1)['phase'],'rollback_push')
        await self.tick(); self.gh.promote.assert_awaited_once_with(B,C)
        self.assertEqual(self.store.get(1)['phase'],'rollback_wait')
        self.gh.deployment.return_value='success'; self.store.heartbeat(C,1001)
        await self.tick(); self.assertEqual(self.store.get(1)['phase'],'rolled_back')

    async def test_restart_reconciles_unknown_promotion_and_keeps_job(self):
        self.state('promoting'); self.gh.ci.return_value='success'
        self.gh.promote.side_effect=[GitHubError('network'),B]
        await self.tick(); self.assertEqual(self.store.get(1)['phase'],'promoting')
        reopened=Controller(Store(self.root/'queue.db'),self.root/'snapshots',{123},github=self.gh,clock=lambda:self.now,notify=self.notify)
        await reopened.tick(); self.assertEqual(self.store.get(1)['phase'],'deploying')

    async def test_owner_revocation_stops_actions_and_notifications(self):
        self.state('promoting'); self.worker.owners=frozenset()
        await self.tick(); self.gh.promote.assert_not_called(); self.notify.assert_not_called()

    async def test_draft_restart_does_not_repeat_paid_ai_call(self):
        self.state('drafting'); self.now=1700
        await self.tick(); self.assertEqual(self.store.get(1)['phase'],'failed')
        self.gh.file.assert_not_called()


class GitHubTests(unittest.IsolatedAsyncioTestCase):
    async def test_installation_token_has_only_one_repository_and_required_permissions(self):
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import serialization
        import jwt
        key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        pem=key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode()
        requests=[]
        def route(request):
            requests.append(request)
            if request.url.path.endswith('/access_tokens'):
                token=request.headers['Authorization'].removeprefix('Bearer ')
                claims=jwt.decode(token,key.public_key(),algorithms=['RS256'],options={'verify_exp':False})
                self.assertEqual(claims['iss'],'10')
                self.assertLessEqual(claims['exp']-claims['iat'],600)
                scope=json.loads(request.content)
                self.assertEqual(scope['repositories'],['veritas-bot'])
                self.assertEqual(scope['permissions']['statuses'],'read')
                self.assertNotIn('administration',scope['permissions'])
                return httpx.Response(201,json={'token':'ephemeral-synthetic','expires_at':'2099-01-01T00:00:00Z'})
            return httpx.Response(200,json={'object':{'sha':A}})
        gh=GitHub(transport=httpx.MockTransport(route),clock=lambda:1000)
        with patch.dict(os.environ,{'GH_APP_ID':'10','GH_INSTALLATION_ID':'11','GH_APP_PRIVATE_KEY':pem}):
            self.assertEqual(await gh.main(),A)
            self.assertEqual(await gh.main(),A)
        self.assertEqual(len([r for r in requests if r.url.path.endswith('/access_tokens')]),1)

    async def test_cross_repository_and_redirect_are_rejected(self):
        gh=GitHub(transport=httpx.MockTransport(lambda r:httpx.Response(302,headers={'Location':'https://other.invalid'})))
        with self.assertRaises(ValueError): await gh._request('GET','/repos/other/private/file','test')
        with self.assertRaises(GitHubError): await gh._request('GET',PREFIX+'/test','test')

    async def test_fast_forward_uses_no_force_and_blocks_concurrent_main(self):
        gh=GitHub(); gh.request=AsyncMock(); gh.main=AsyncMock(return_value=A)
        gh.request.side_effect=[{'parents':[{'sha':A}]},{'object':{'sha':B}}]
        await gh.promote(A,B)
        self.assertEqual(gh.request.call_args.args,('PATCH','/git/refs/heads/main',{'sha':B,'force':False}))
        gh.main.return_value=C; gh.request.reset_mock()
        with self.assertRaises(ValueError): await gh.promote(A,B)
        gh.request.assert_not_called()

    async def test_unknown_promotion_is_idempotent(self):
        gh=GitHub(); gh.main=AsyncMock(return_value=B); gh.request=AsyncMock()
        self.assertEqual(await gh.promote(A,B),B); gh.request.assert_not_called()

    async def test_ci_cannot_use_different_commit_repository_or_pr(self):
        gh=GitHub(); gh.request=AsyncMock()
        valid={'head_sha':B,'workflow_id':9,'event':'pull_request','head_repository':{'full_name':REPO},
               'pull_requests':[{'number':7}],'run_number':2,'status':'completed','conclusion':'success'}
        for alteration in ({'head_sha':A},{'head_repository':{'full_name':'other/repo'}},{'pull_requests':[{'number':8}]}):
            gh.request.side_effect=[{'id':9},{'workflow_runs':[{**valid,**alteration}]}]
            self.assertEqual(await gh.ci(B,7),'pending')
        gh.request.side_effect=[{'id':9},{'workflow_runs':[valid]}]
        self.assertEqual(await gh.ci(B,7),'success')

    async def test_deployment_only_accepts_the_configured_railway_service(self):
        gh=GitHub(); gh.request=AsyncMock()
        valid={'context':'triumphant-trust - veritas-bot','state':'success',
               'target_url':f'https://railway.com/project/{PROJECT}/service/{SERVICE}?environmentId={ENVIRONMENT}'}
        gh.request.return_value={'statuses':[{**valid,'target_url':'https://attacker.invalid/'}]}
        self.assertEqual(await gh.deployment(B),'pending')
        gh.request.return_value={'statuses':[valid]}
        self.assertEqual(await gh.deployment(B),'success')

    async def test_rollback_refuses_to_erase_later_changes(self):
        gh=GitHub(); gh.main=AsyncMock(return_value=C); gh.request=AsyncMock()
        with self.assertRaises(ValueError): await gh.rollback_commit(A,B,1,1000)
        gh.request.assert_not_called()


class RemoteBotTests(unittest.IsolatedAsyncioTestCase):
    async def test_remote_queue_survives_missing_connection_and_does_not_start_legacy_agent(self):
        with tempfile.TemporaryDirectory() as tmp:
            app=NS(bot_data={},job_queue=None,running=False)
            bridge=SuperSettings(Path(tmp)/'bot.db',{123},app,ai=AsyncMock(return_value='Tahlil'),clock=lambda:1000)
            report=bridge.reports.submit(123,1,'Tugma ishlamayapti',1000)
            ctx=NS(bot=NS(send_message=AsyncMock()))
            with patch.dict(os.environ,{'VERITAS_AUTOREPAIR_ENABLED':'1','VERITAS_MAINTAINER_URL':'http://maintainer.railway.internal'}):
                await bridge.tick(ctx)
                self.assertIsNone(bridge.repairs.store.get(report,123))
                with patch('maintainer_client.request',side_effect=RuntimeError('network')):
                    await bridge.remote_tick(ctx)
                with bridge.reports.db() as db:
                    self.assertEqual(db.execute('SELECT status FROM super_remote_outbox').fetchone()[0],'pending')
                with patch('maintainer_client.request',new=AsyncMock(return_value={'ok':True,'id':report})):
                    await bridge.remote_tick(ctx)
                with bridge.reports.db() as db:
                    self.assertEqual(db.execute('SELECT status FROM super_remote_outbox').fetchone()[0],'accepted')


class IndependentCITests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.old=self.root/'old'; self.new=self.root/'new'
        self.old.mkdir(); self.new.mkdir()
        (self.old/'bot.py').write_text('value=1\n')
        (self.new/'bot.py').write_text('value=2\n')
        (self.new/'test_repair_case_value.py').write_text('import unittest\nfrom bot import value\nclass T(unittest.TestCase):\n def test_value(self): self.assertEqual(value,2)\n')

    def run_ci(self):
        with patch.dict(os.environ,{'AUTOREPAIR':'true'}):
            return subprocess.run([sys.executable,str(Path(__file__).parent/'.github/repair/verify.py'),str(self.new),str(self.old)],
                                  capture_output=True,timeout=15).returncode

    def test_regression_fails_old_code_and_passes_candidate(self):
        self.assertEqual(self.run_ci(),0)

    def test_regression_that_already_passes_old_code_is_rejected(self):
        (self.old/'bot.py').write_text('value=2\n')
        self.assertNotEqual(self.run_ci(),0)

    def test_protected_file_change_cannot_get_green_ci(self):
        (self.old/'repair_jobs.py').write_text('value=1\n')
        (self.new/'repair_jobs.py').write_text('value=2\n')
        self.assertNotEqual(self.run_ci(),0)


if __name__=='__main__': unittest.main()
