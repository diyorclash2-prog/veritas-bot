import base64
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, patch

from telegram.error import TimedOut
from astra_support import AIUnavailable
from super_settings import Reports
from repair_jobs import (RepairStore, RepairWorker, SOURCE_FILES, source_bundle,
                         validate_result, repair_payload)


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for name in SOURCE_FILES:
            (self.root/name).write_text('value = 1\n')
        self.files, self.manifest = source_bundle(self.root)

    def result(self, files=None, status='candidate'):
        return json.dumps({'status': status, 'summary': 'Tuzatish taklifi',
                          'tests': [{'command': 'python -m unittest', 'exit_code': 0}],
                          'files': files if files is not None else [{'path': 'bot.py', 'content': 'value = 2\n'}]})

    def test_source_allowlist_excludes_live_data_and_dotenv(self):
        (self.root/'.env').write_text('private-key')
        (self.root/'users.db').write_text('private-phone')
        files, manifest = source_bundle(self.root)
        self.assertEqual(set(manifest), set(SOURCE_FILES))
        self.assertNotIn('private', str(files))

    def test_symlinks_are_rejected(self):
        (self.root/'bot.py').unlink()
        (self.root/'bot.py').symlink_to(self.root/'super_settings.py')
        with self.assertRaises(ValueError): source_bundle(self.root)

    def test_runtime_credentials_in_code_abort_export(self):
        (self.root/'bot.py').write_text("secret = 'runtime-private-value'\n")
        with patch.dict(os.environ, {'BOT_TOKEN': 'runtime-private-value'}):
            with self.assertRaises(ValueError): source_bundle(self.root)

    def test_sandbox_has_no_network_environment_or_live_credentials(self):
        payload = repair_payload('report', self.files)
        self.assertEqual(payload['environment']['network']['access'], 'disabled')
        self.assertNotIn('env', payload['environment'])
        self.assertNotIn('tools', payload['agent'])
        self.assertEqual(payload['agent']['model'], 'gpt-6-astra')

    def test_candidate_is_diff_only_and_does_not_modify_live_source(self):
        result = validate_result(self.result(), self.manifest, self.root)
        self.assertIn(b'+value = 2', result['patch'])
        self.assertEqual((self.root/'bot.py').read_text(), 'value = 1\n')

    def test_disallowed_files_and_path_traversal_are_rejected(self):
        for name in ('../bot.py', '/tmp/bot.py', '.env', 'users.db', 'test_super_settings.py', 'repair_jobs.py'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate_result(self.result([{'path': name, 'content': 'value = 2\n'}]), self.manifest, self.root)

    def test_changed_baseline_is_rejected(self):
        (self.root/'super_settings.py').write_text('value = 3\n')
        with self.assertRaises(ValueError): validate_result(self.result(), self.manifest, self.root)

    def test_invalid_python_and_duplicate_changes_are_rejected(self):
        with self.assertRaises(ValueError):
            validate_result(self.result([{'path': 'bot.py', 'content': 'def invalid('}]), self.manifest, self.root)
        with self.assertRaises(ValueError):
            validate_result(self.result([{'path': 'bot.py', 'content': 'x=2'}, {'path': 'bot.py', 'content': 'x=3'}]), self.manifest, self.root)

    def test_no_change_cannot_claim_modifications(self):
        with self.assertRaises(ValueError): validate_result(self.result(status='no_change'), self.manifest, self.root)
        result = validate_result(self.result([], 'no_change'), self.manifest, self.root)
        self.assertEqual(result['patch'], b'')

    def test_new_regression_test_is_allowed_without_running_it_locally(self):
        content = "raise RuntimeError('must never execute on live host')\n"
        result = validate_result(self.result([{'path': 'test_repair_case_bug.py', 'content': content}]), self.manifest, self.root)
        self.assertIn(b'must never execute', result['patch'])
        self.assertFalse((self.root/'test_repair_case_bug.py').exists())


class WorkerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for name in SOURCE_FILES:
            (self.root/name).write_text('value = 1\n')
        self.reports = Reports(self.root/'runtime.db')
        self.report_id = self.reports.submit(123, 1, 'Test tugmasi ishlamayapti', 1000)
        self.api = AsyncMock()
        self.api.create.return_value = 'session_test'
        self.api.state.return_value = {'status': 'idle', 'required_actions': []}
        self.api.turn.return_value = None
        self.stamp = 1000
        self.worker = RepairWorker(self.reports, {123}, root=self.root, api=self.api, clock=lambda: self.stamp)
        self.ctx = NS(bot=NS(send_message=AsyncMock(), send_document=AsyncMock()))
        self.worker.store.enqueue(self.report_id, 123, 1000)

    async def start(self):
        await self.worker.tick(self.ctx)
        await self.worker.tick(self.ctx)

    async def test_queue_is_owner_scoped_idempotent_and_limited(self):
        self.worker.store.enqueue(self.report_id, 123, 1000)
        self.assertIsNone(self.worker.store.get(self.report_id, 999))
        with self.assertRaises(ValueError): self.worker.store.enqueue(self.report_id, 999, 1000)
        for n in (2, 3):
            rid = self.reports.submit(123, n, 'Test tugmasi ishlamayapti', 1000)
            self.worker.store.enqueue(rid, 123, 1000)
        rid = self.reports.submit(123, 4, 'Test tugmasi ishlamayapti', 1000)
        with self.assertRaises(ValueError): self.worker.store.enqueue(rid, 123, 1000)

    async def test_restart_resumes_saved_session_without_duplicate_create(self):
        await self.worker.tick(self.ctx)
        self.assertEqual(self.worker.store.get(self.report_id, 123)['status'], 'prepared')
        self.worker = RepairWorker(self.reports, {123}, root=self.root, api=self.api, clock=lambda: self.stamp)
        await self.worker.tick(self.ctx)
        await self.worker.tick(self.ctx)
        self.api.create.assert_awaited_once()
        self.api.submit.assert_awaited_once()

    async def test_lost_submit_response_retries_same_idempotency_key(self):
        await self.worker.tick(self.ctx)
        self.api.submit.side_effect = [AIUnavailable('network'), None]
        await self.worker.tick(self.ctx)
        await self.worker.tick(self.ctx)
        self.assertEqual(self.api.submit.call_args_list[0], self.api.submit.call_args_list[1])
        self.api.create.assert_awaited_once()

    async def test_unknown_creation_result_is_not_retried(self):
        self.api.create.side_effect = AIUnavailable('network')
        await self.worker.tick(self.ctx)
        await self.worker.tick(self.ctx)
        self.api.create.assert_awaited_once()
        self.assertEqual(self.worker.store.get(self.report_id, 123)['status'], 'failed')

    async def test_removed_owner_has_no_api_or_notification(self):
        self.worker.owners = frozenset()
        await self.worker.tick(self.ctx)
        self.api.create.assert_not_called()
        self.ctx.bot.send_message.assert_not_called()

    async def test_idle_session_is_not_a_completed_repair(self):
        await self.start()
        await self.worker.tick(self.ctx)
        self.assertEqual(self.worker.store.get(self.report_id, 123)['status'], 'running')
        self.api.artifact.assert_not_called()

    async def test_completed_proposal_downloads_patch_and_never_deploys(self):
        await self.start()
        self.api.turn.return_value = {'id': 'turn_test', 'status': 'completed'}
        self.api.artifact.return_value = json.dumps({'status': 'candidate', 'summary': 'Taklif tayyor',
             'tests': [{'command': 'python -m unittest', 'exit_code': 0}],
             'files': [{'path': 'bot.py', 'content': 'value = 2\n'}]}).encode()
        await self.worker.tick(self.ctx)
        await self.worker.tick(self.ctx)
        self.assertEqual(self.worker.store.get(self.report_id, 123)['status'], 'candidate')
        self.ctx.bot.send_document.assert_awaited_once()
        self.assertEqual((self.root/'bot.py').read_text(), 'value = 1\n')
        self.assertIn('o‘zgarmadi', self.ctx.bot.send_message.call_args.kwargs['text'])

    async def test_deadline_cancels_remote_work(self):
        await self.start()
        self.stamp += 601
        await self.worker.tick(self.ctx)
        self.api.cancel.assert_awaited()
        self.assertEqual(self.worker.store.get(self.report_id, 123)['status'], 'failed')

    async def test_owner_cannot_cancel_another_owners_work(self):
        await self.start()
        self.assertFalse(await self.worker.cancel(self.report_id, 999))
        self.api.cancel.assert_not_called()
        self.assertTrue(await self.worker.cancel(self.report_id, 123))

    async def test_unknown_telegram_delivery_is_not_repeated(self):
        self.worker.store.finish(self.report_id, 'failed', 'Sinov xatosi')
        self.ctx.bot.send_message.side_effect = TimedOut()
        await self.worker.tick(self.ctx)
        await self.worker.tick(self.ctx)
        self.ctx.bot.send_message.assert_awaited_once()

    async def test_crashed_start_lease_does_not_resubmit(self):
        self.worker.store.active_or_claim(1000)
        self.stamp = 1121
        await self.worker.tick(self.ctx)
        self.api.create.assert_not_called()
        self.assertEqual(self.worker.store.get(self.report_id, 123)['status'], 'failed')

    async def test_cancel_during_create_retains_session_for_cleanup_without_submit(self):
        async def create(payload):
            self.worker.store.finish(self.report_id, 'cancelled', 'Bekor qilindi')
            return 'session_test'
        self.api.create.side_effect = create
        await self.worker.tick(self.ctx)
        await self.worker.tick(self.ctx)
        self.api.submit.assert_not_called()
        self.api.delete.assert_awaited_once_with('session_test')
        self.assertEqual(self.worker.store.get(self.report_id, 123)['status'], 'cancelled')

    async def test_cleanup_deletes_even_when_cancel_says_no_active_turn(self):
        await self.start()
        self.worker.store.finish(self.report_id, 'failed', 'Xato')
        self.api.cancel.side_effect = AIUnavailable('api_error', 400)
        await self.worker.tick(self.ctx)
        self.api.delete.assert_awaited_once_with('session_test')

    async def test_cleanup_retries_are_bounded(self):
        await self.start()
        self.worker.store.finish(self.report_id, 'failed', 'Xato')
        self.api.delete.side_effect = AIUnavailable('network')
        for _ in range(5):
            await self.worker.tick(self.ctx)
        self.assertEqual(self.api.delete.await_count, 3)

    async def test_responses_proposal_returns_patch_without_hosted_session_or_source_write(self):
        from astra_proposer import Proposer
        proposed=Proposer(self.root).apply('Taklif',[
            {'path':'bot.py','search':'value = 1','replace':'value = 2'},
            {'path':'test_repair_case_value.py','search':'','replace':'import unittest\nfrom bot import value\nclass T(unittest.TestCase):\n def test_value(self): self.assertEqual(value,2)\n'}])
        proposer=NS(propose=AsyncMock(return_value=proposed))
        self.worker.proposer=lambda root:proposer
        with patch.dict(os.environ,{'VERITAS_REPAIR_PROVIDER':'responses'}):
            await self.worker.tick(self.ctx); await self.worker.tick(self.ctx)
        proposer.propose.assert_awaited_once()
        self.api.create.assert_not_awaited()
        self.assertEqual((self.root/'bot.py').read_text(),'value = 1\n')
        self.ctx.bot.send_document.assert_awaited_once()
        self.assertIn('CI',self.ctx.bot.send_message.call_args.kwargs['text'])
        self.assertEqual(self.worker.store.get(self.report_id,123)['test_evidence'],'[]')

    async def test_responses_timeout_has_no_second_paid_job(self):
        proposer=NS(propose=AsyncMock(side_effect=TimeoutError()))
        self.worker.proposer=lambda root:proposer
        with patch.dict(os.environ,{'VERITAS_REPAIR_PROVIDER':'responses'}):
            await self.worker.tick(self.ctx); await self.worker.tick(self.ctx)
        proposer.propose.assert_awaited_once()
        self.assertEqual(self.worker.store.get(self.report_id,123)['status'],'failed')

    async def test_responses_cancel_during_generation_is_not_overwritten(self):
        async def propose(report):
            await self.worker.cancel(self.report_id,123)
            return {'status':'candidate','summary':'Taklif','patch':b'example'}
        self.worker.proposer=lambda root:NS(propose=propose)
        with patch.dict(os.environ,{'VERITAS_REPAIR_PROVIDER':'responses'}): await self.worker.tick(self.ctx)
        self.assertEqual(self.worker.store.get(self.report_id,123)['status'],'cancelled')
        self.ctx.bot.send_document.assert_not_awaited()

    async def test_responses_restart_waits_then_fails_without_resubmission(self):
        self.worker.store.active_or_claim(self.stamp)
        self.worker.store.drafting(self.report_id)
        proposer=NS(propose=AsyncMock())
        self.worker.proposer=lambda root:proposer
        with patch.dict(os.environ,{'VERITAS_REPAIR_PROVIDER':'responses'}):
            await self.worker.tick(self.ctx)
            self.assertEqual(self.worker.store.get(self.report_id,123)['status'],'drafting')
            self.stamp+=661
            await self.worker.tick(self.ctx)
        proposer.propose.assert_not_awaited()
        self.assertEqual(self.worker.store.get(self.report_id,123)['status'],'failed')


if __name__ == '__main__':
    unittest.main()
