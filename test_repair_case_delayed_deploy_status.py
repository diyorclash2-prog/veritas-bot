"""Delayed provider metadata cannot roll back an otherwise healthy release."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock

from maintainer_service import Controller, Store


class DelayedDeployTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.store=Store(self.root/'jobs.db')
        self.store.enqueue({'id':1,'owner':123,'report':'Synthetic incident report'},{123},1000)
        self.store.update(1,1000,phase='deploying',base='a'*40,head='b'*40,pr=1)
        self.gh=AsyncMock()
        self.gh.deployment.return_value='pending'
        self.notice=AsyncMock()
        self.controller=Controller(self.store,self.root,{123},github=self.gh,
                                   clock=lambda:1701,notify=self.notice)

    async def test_pending_status_with_fresh_matching_heartbeat_does_not_rollback(self):
        self.store.heartbeat('b'*40,1700)
        await self.controller.tick()
        row=self.store.get(1)
        self.assertEqual(row['phase'],'failed')
        self.assertIn('qaytarilmadi',row['summary'])
        self.gh.rollback_commit.assert_not_awaited()
        self.gh.promote.assert_not_awaited()
        self.assertNotIn('Yangi kod ishga tushdi',self.notice.call_args.args[1])

    async def test_pending_status_without_health_still_rolls_back(self):
        await self.controller.tick()
        self.assertEqual(self.store.get(1)['phase'],'rollback_prepare')

    async def test_stale_or_different_commit_heartbeat_cannot_preserve_unhealthy_release(self):
        self.store.heartbeat('b'*40,1500)
        self.store.heartbeat('a'*40,1700)
        await self.controller.tick()
        self.assertEqual(self.store.get(1)['phase'],'rollback_prepare')

    async def test_explicit_provider_failure_still_rolls_back_even_with_heartbeat(self):
        self.store.heartbeat('b'*40,1700)
        self.gh.deployment.return_value='failure'
        await self.controller.tick()
        self.assertEqual(self.store.get(1)['phase'],'rollback_prepare')

    async def test_verified_still_requires_provider_success_and_exact_fresh_heartbeat(self):
        self.store.heartbeat('b'*40,1700)
        self.gh.deployment.return_value='success'
        await self.controller.tick()
        self.assertEqual(self.store.get(1)['phase'],'verified')


if __name__=='__main__': unittest.main()
