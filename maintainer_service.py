"""Separate durable repair controller; only its private HTTP interface accepts work.

Deploy independently of bot.py. Its source is never edited by the coding model.
"""
from __future__ import annotations
import asyncio
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
from pathlib import Path
import re
import socket
import threading
import time
from types import SimpleNamespace
import httpx

from codex_proposer import CodexProposer
from astra_support import AIUnavailable
from ai_spending import Spending, MeteredAPI, BudgetError
from lingua_ai import GenerationQueue, run_worker
from github_release import GitHub, GitHubError, configured, oid
from maintainer_client import signature
from repair_jobs import SOURCE_FILES, source_bundle
from super_settings import Reports, redact

TERMINAL = {'verified', 'rolled_back', 'failed', 'no_change'}


class JobRejected(ValueError):
    def __init__(self, code, status, retry_after=0):
        self.code, self.status, self.retry_after = code, status, retry_after
        super().__init__(code)


class Store(Reports):
    def __init__(self, path):
        super().__init__(path)
        with self.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS maintenance_jobs (
                    id INTEGER PRIMARY KEY, owner INTEGER NOT NULL, report TEXT NOT NULL,
                    phase TEXT NOT NULL DEFAULT 'queued', created INTEGER NOT NULL, updated INTEGER NOT NULL,
                    base TEXT NOT NULL DEFAULT '', head TEXT NOT NULL DEFAULT '', pr INTEGER,
                    rollback TEXT NOT NULL DEFAULT '', files TEXT NOT NULL DEFAULT '[]',
                    summary TEXT NOT NULL DEFAULT '', notified INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS maintenance_nonces (nonce TEXT PRIMARY KEY, stamp INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS maintenance_heartbeats (sha TEXT PRIMARY KEY, stamp INTEGER NOT NULL);
            ''')
        self.spending = Spending(self)

    def authenticate(self, headers, body, secret, now, path='/'):
        stamp, nonce, digest = (headers.get(k, '') for k in ('X-Timestamp','X-Nonce','X-Signature'))
        if len(secret) < 32 or not stamp.isdigit() or abs(now-int(stamp)) > 60:
            return False
        if not re.fullmatch('[a-f0-9]{32}',nonce) or not hmac.compare_digest(signature(secret,stamp,nonce,body,path),digest):
            return False
        with self.db() as db:
            db.execute('DELETE FROM maintenance_nonces WHERE stamp<?',(now-300,))
            if db.execute('SELECT 1 FROM maintenance_nonces WHERE nonce=?',(nonce,)).fetchone(): return False
            db.execute('INSERT INTO maintenance_nonces VALUES(?,?)',(nonce,now))
        return True

    def enqueue(self, job, owners, now):
        ident, owner, report = job.get('id'), job.get('owner'), job.get('report')
        if type(ident) is not int or ident <= 0 or type(owner) is not int or owner not in owners or not isinstance(report,str):
            raise ValueError('Invalid owner or job')
        report = redact(report)
        if not 10 <= len(report) <= 2000: raise ValueError('Invalid incident length')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT owner,report FROM maintenance_jobs WHERE id=?',(ident,)).fetchone()
            if row:
                if row['owner'] != owner or row['report'] != report: raise JobRejected('job_conflict', 409)
                return
            # Number of past jobs is not a spending limit. Every model call is
            # metered by the shared durable ledger before it can be submitted.
            db.execute('INSERT INTO maintenance_jobs(id,owner,report,created,updated) VALUES(?,?,?,?,?)',
                       (ident,owner,report,now,now))

    def get(self, ident):
        with self.db() as db:
            row = db.execute('SELECT * FROM maintenance_jobs WHERE id=?',(ident,)).fetchone()
            return dict(row) if row else None

    def update(self, ident, now, **fields):
        if not fields or not set(fields) <= {'phase','base','head','pr','rollback','files','summary','notified'}:
            raise ValueError('Invalid job mutation')
        with self.db() as db:
            db.execute('UPDATE maintenance_jobs SET '+','.join(k+'=?' for k in fields)+',updated=? WHERE id=?',
                       (*fields.values(),now,ident))

    def active(self):
        with self.db() as db:
            row = db.execute("SELECT * FROM maintenance_jobs WHERE phase NOT IN ('verified','rolled_back','failed','no_change') ORDER BY id LIMIT 1").fetchone()
            return dict(row) if row else None

    def heartbeat(self, sha, now):
        with self.db() as db:
            first = not db.execute('SELECT 1 FROM maintenance_heartbeats WHERE sha=?',(oid(sha),)).fetchone()
            db.execute('INSERT OR REPLACE INTO maintenance_heartbeats VALUES(?,?)',(oid(sha),now))
        if first: logging.warning('VERITAS_MAINTAINER_HEARTBEAT sha=%s',sha)

    def healthy(self, sha, after, now):
        with self.db() as db:
            row = db.execute('SELECT stamp FROM maintenance_heartbeats WHERE sha=?',(sha,)).fetchone()
            return bool(row and row['stamp'] >= after and now-row['stamp'] < 90)


class Controller:
    def __init__(self, store, root, owners, *, github=None, proposer=None, clock=time.time, notify=None):
        self.store, self.root, self.owners = store, Path(root), frozenset(owners)
        self.github, self.proposer, self.clock = github or GitHub(), proposer, clock
        self.store.spending.clock = clock
        self.notify = notify or self.telegram
        self.lock = asyncio.Lock()

    @staticmethod
    async def telegram(owner, text):
        async with httpx.AsyncClient(timeout=20) as client:
            result = await client.post('https://api.telegram.org/bot'+os.environ['BOT_TOKEN']+'/sendMessage',
                                       json={'chat_id':owner,'text':text})
        if result.status_code != 200: raise RuntimeError('Telegram delivery unavailable')

    @staticmethod
    def describe(row, spending=None):
        labels = {'queued':'Navbatda','drafting':'Codex · Astra kodni tekshiryapti','publishing':'Tuzatish tayyorlanmoqda',
                  'opening':'GitHub tekshiruvi ochilmoqda','ci':'Mustaqil testlar ishlayapti',
                  'promoting':'Sinovdan o‘tgan kod joylanmoqda','deploying':'Railway ishga tushishi tekshirilmoqda',
                  'rollback_prepare':'Oldingi kod qaytarilmoqda','rollback_push':'Oldingi kod joylanmoqda',
                  'rollback_wait':'Qaytarilgan bot tekshirilmoqda','verified':'Yangi kod ishga tushdi',
                  'rolled_back':'Yangi versiya ishlamadi; oldingi kod qaytarildi',
                  'failed':'Avtomatik ish to‘xtadi','no_change':'Asoslangan tuzatish topilmadi'}
        cost = spending.snapshot('repair:'+str(row['id'])) if spending else None
        return (f"🛠 Codex · Astra · murojaat #{row['id']}\n{labels[row['phase']]}\n\n{row['summary']}\n"
                + (f"\nAI sarfi (ehtiyotkor hisob): ${cost['task_usd']:.4f}. Oylik qoldiq: ${cost['remaining_usd']:.2f}.\n" if cost else '')
                + (f"\nGitHub: https://github.com/diyorclash2-prog/veritas-bot/pull/{row['pr']}" if row['pr'] else ''))

    async def step(self, row):
        gh, now, ident, phase = self.github, int(self.clock()), row['id'], row['phase']
        def save(**fields): self.store.update(ident,now,**fields)
        if row['owner'] not in self.owners:
            save(phase='failed',summary='Super Ega ruxsati bekor qilingan.'); return
        if phase == 'queued':
            base = await gh.main()
            if await gh.deployment(base) != 'success' or not self.store.healthy(base,0,now):
                if now-row['created'] > 600: save(phase='failed',summary='Boshlang‘ich bot holati tasdiqlanmadi.')
                return
            root = self.root / str(ident)
            root.mkdir(parents=True,exist_ok=True)
            for name in SOURCE_FILES:
                (root/name).write_bytes(await gh.file(name,base))
            source_bundle(root)
            save(phase='drafting',base=base)
            agent = self.proposer(root) if self.proposer else CodexProposer(root,
                api=MeteredAPI(self.store.spending,'repair:'+str(ident)))
            result = await asyncio.wait_for(agent.propose(row['report']),timeout=600)
            save(phase='publishing' if result['files'] else 'no_change',
                 files=json.dumps(result['files']),summary=redact(result['summary'])[:1400])
        elif phase == 'drafting':
            # The controller restarted during an AI call. Do not duplicate paid work.
            if now-row['updated'] > 660: save(phase='failed',summary='Astra vazifasi restartda uzildi; takror pullik so‘rov yuborilmadi.')
        elif phase == 'publishing':
            if await gh.main() != row['base']: raise ValueError('Main changed before publication')
            head = await gh.commit(row['base'],json.loads(row['files']),ident,row['created'])
            save(phase='opening',head=head)
        elif phase == 'opening':
            number = await gh.open_pr(row['head'],ident)
            save(phase='ci',pr=number)
        elif phase == 'ci':
            status = await gh.ci(row['head'],row['pr'])
            if status == 'success': save(phase='promoting')
            elif status == 'failure' or now-row['updated'] > 1200:
                save(phase='failed',summary='Mustaqil CI o‘tmadi yoki vaqti tugadi. Main o‘zgarmadi.')
        elif phase == 'promoting':
            if await gh.ci(row['head'],row['pr']) != 'success': raise ValueError('CI result changed')
            await gh.promote(row['base'],row['head'])
            save(phase='deploying')
        elif phase == 'deploying':
            status = await gh.deployment(row['head'])
            healthy = self.store.healthy(row['head'],row['updated'],now)
            if status == 'success' and healthy:
                save(phase='verified')
            elif status in ('failure','error'):
                save(phase='rollback_prepare',summary='Yangi bot sog‘lom ishga tushmadi; oldingi kod qaytarilmoqda.')
            elif now-row['updated'] > 600:
                if healthy:
                    # A delayed commit status is not evidence of a failed running bot.
                    # Keep strict verification, but never roll back a healthy release for it.
                    save(phase='failed',summary='Botdan yangi ishlash signali olindi, lekin GitHub deploy tasdig‘i kechikdi. '
                         'Kod orqaga qaytarilmadi. Joylash holatini alohida tekshirish kerak.')
                else:
                    save(phase='rollback_prepare',summary='Yangi botning ishlash signali kelmadi; oldingi kod qaytarilmoqda.')
        elif phase == 'rollback_prepare':
            rollback = await gh.rollback_commit(row['base'],row['head'],ident,row['created']+1)
            save(phase='rollback_push',rollback=rollback)
        elif phase == 'rollback_push':
            await gh.promote(row['head'],row['rollback'])
            save(phase='rollback_wait')
        elif phase == 'rollback_wait':
            status = await gh.deployment(row['rollback'])
            if status == 'success' and self.store.healthy(row['rollback'],row['updated'],now):
                save(phase='rolled_back',summary='Oldingi kodning ishga tushgani tasdiqlandi. Ma’lumotlar bazasi orqaga qaytarilmadi.')
            elif status in ('failure','error') or now-row['updated'] > 600:
                save(phase='failed',summary='Oldingi kodni qaytarish tasdiqlanmadi. Qo‘lda tekshirish zarur.')

    async def tick(self):
        if self.lock.locked(): return
        async with self.lock:
            row = self.store.active()
            if row:
                try:
                    await self.step(row)
                except GitHubError as exc:
                    # Unknown network outcomes are reconciled by reading the same commit/branch next time.
                    if exc.status not in ('network',429,500,502,503,504) or self.clock()-row['updated'] > 1200:
                        self.store.update(row['id'],int(self.clock()),phase='failed',summary=str(exc))
                except BudgetError as exc:
                    self.store.update(row['id'],int(self.clock()),phase='failed',summary=exc.user_message)
                except AIUnavailable as exc:
                    self.store.update(row['id'],int(self.clock()),phase='failed',summary=exc.user_message)
                except Exception as exc:
                    logging.warning('Maintainer step failed: %s',type(exc).__name__)
                    self.store.update(row['id'],int(self.clock()),phase='failed',summary='Tekshiruv to‘xtadi: '+type(exc).__name__)
            with self.store.db() as db:
                notice = db.execute("SELECT * FROM maintenance_jobs WHERE phase IN ('verified','rolled_back','failed','no_change') AND notified=0 ORDER BY id LIMIT 1").fetchone()
                if notice:
                    db.execute('UPDATE maintenance_jobs SET notified=1 WHERE id=?',(notice['id'],))
            if notice and notice['owner'] in self.owners:
                try: await self.notify(notice['owner'],self.describe(dict(notice),self.store.spending))
                except Exception: logging.warning('Maintainer notification delivery unconfirmed')


def handler(store, owners, secret):
    lingua = GenerationQueue(store)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def reply(self, code, value):
            body = json.dumps(value,ensure_ascii=False).encode()
            self.send_response(code); self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
        def do_GET(self):
            if self.path == '/health': self.reply(200,{'ok':True,'github_configured':configured(),'lingua_ai':True})
            else: self.reply(404,{'error':'route'})
        def do_POST(self):
            try:
                self.connection.settimeout(10)
                length = int(self.headers.get('Content-Length','0'))
                if not 1 <= length <= 10000: raise ValueError('size')
                body = self.rfile.read(length)
                now = int(time.time())
                if not store.authenticate(self.headers,body,secret,now,self.path):
                    self.reply(401,{'error':'authentication'}); return
                value = json.loads(body)
                if self.path == '/heartbeat':
                    store.heartbeat(value['sha'],now); self.reply(200,{'ok':True}); return
                if value.get('owner') not in owners: raise ValueError('owner')
                if self.path == '/lingua/questions':
                    self.reply(200, lingua.submit(value['id'], value['payload']))
                elif self.path == '/budget':
                    budget = store.spending.snapshot()
                    with store.db() as db:
                        jobs = db.execute('SELECT id FROM maintenance_jobs WHERE owner=? ORDER BY id DESC LIMIT 5',
                                          (value['owner'],)).fetchall()
                    self.reply(200,{'ok':True,'budget':budget,'tasks':[
                        {'id':r['id'],'usd':store.spending.snapshot('repair:'+str(r['id']))['task_usd']} for r in jobs]})
                elif self.path == '/jobs':
                    if not configured(): self.reply(503,{'error':'GitHub App not configured'}); return
                    store.enqueue(value,owners,now)
                    self.reply(200,{'ok':True,'id':value['id']})
                elif self.path == '/status':
                    row = store.get(value['id'])
                    if not row or row['owner'] != value['owner']: self.reply(404,{'error':'job'}); return
                    self.reply(200,{'ok':True,'status':row['phase'],'message':Controller.describe(row,store.spending)})
                else: self.reply(404,{'error':'route'})
            except JobRejected as exc:
                self.reply(exc.status,{'ok':False,'code':exc.code,'retry_after':exc.retry_after})
            except Exception:
                self.reply(400,{'ok':False,'code':'invalid_request'})
    return Handler


def main():
    logging.basicConfig(level=logging.WARNING)
    root = Path(os.getenv('MAINTAINER_DATA','/data'))
    root.mkdir(parents=True,exist_ok=True)
    secret = os.environ['VERITAS_MAINTAINER_SECRET']
    if len(secret) < 32: raise ValueError('Maintainer secret too short')
    owners = {int(x) for x in os.environ['SUPER_OWNER_IDS'].split(',') if x.strip()}
    store = Store(root/'maintainer.sqlite3')
    controller = Controller(store,root/'snapshots',owners)
    async def work():
        while True:
            try:
                if configured(): await controller.tick()
            except Exception as exc:
                logging.warning('Maintainer loop retry: %s',type(exc).__name__)
            await asyncio.sleep(15)
    threading.Thread(target=lambda: asyncio.run(work()),daemon=True).start()
    lingua = GenerationQueue(store)
    threading.Thread(target=lambda: asyncio.run(run_worker(lingua)),daemon=True).start()
    import shutil
    if not shutil.which(os.getenv('VERITAS_CODEX_BIN','codex')):
        raise RuntimeError('Codex runtime missing')
    print('VERITAS_MAINTAINER_READY github_configured='+str(configured())+' codex=True lingua_ai=True monthly_budget_usd=60',flush=True)
    class PrivateServer(ThreadingHTTPServer):
        address_family = socket.AF_INET6
        daemon_threads = True
        def server_bind(self):
            self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
            super().server_bind()
    PrivateServer(('::',int(os.getenv('PORT','8080'))),handler(store,owners,secret)).serve_forever()


if __name__ == '__main__': main()
