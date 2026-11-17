"""Repository-scoped publisher. Generated code never receives this client's token."""
from __future__ import annotations
import base64
from datetime import datetime, timezone
import os
import re
import time
from urllib.parse import urlparse, parse_qs
import httpx
import jwt

REPO = 'diyorclash2-prog/veritas-bot'
PREFIX = '/repos/' + REPO
RAILWAY_CONTEXT = 'triumphant-trust - veritas-bot'
PROJECT = '27e1131c-f4ab-49c3-9986-f1ae3d02aa93'
SERVICE = 'dbdbf051-f800-49c8-a2a3-2c1d8f22229d'
ENVIRONMENT = 'aecd69c7-3c78-400f-9fda-2752ff26634f'


class GitHubError(RuntimeError):
    def __init__(self, status):
        self.status = status
        super().__init__('GitHub request failed: ' + str(status))


def oid(value):
    if not isinstance(value, str) or not re.fullmatch('[a-f0-9]{40}', value):
        raise ValueError('Invalid commit SHA')
    return value


def configured():
    return all(os.getenv(k) for k in ('GH_APP_ID', 'GH_INSTALLATION_ID', 'GH_APP_PRIVATE_KEY'))


class GitHub:
    def __init__(self, *, transport=None, clock=time.time):
        self.transport, self.clock = transport, clock
        self.token, self.token_until = '', 0

    async def _request(self, method, path, token, payload=None):
        if not (path.startswith(PREFIX + '/') or re.fullmatch('/app/installations/[0-9]+/access_tokens', path)):
            raise ValueError('Repository boundary')
        if '..' in path or '://' in path:
            raise ValueError('Invalid API path')
        try:
            async with httpx.AsyncClient(timeout=45, follow_redirects=False, transport=self.transport) as client:
                r = await client.request(method, 'https://api.github.com' + path, json=payload,
                    headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json',
                             'X-GitHub-Api-Version': '2026-03-10'})
            if not 200 <= r.status_code < 300:
                raise GitHubError(r.status_code)
            if len(r.content) > 5_000_000:
                raise ValueError('GitHub response exceeds bound')
            return r.json() if r.content else {}
        except httpx.HTTPError:
            raise GitHubError('network') from None

    async def request(self, method, suffix, payload=None):
        if not suffix.startswith('/') or '..' in suffix or '://' in suffix:
            raise ValueError('Invalid repository path')
        if self.clock() >= self.token_until:
            app = os.environ['GH_APP_ID']
            installation = os.environ['GH_INSTALLATION_ID']
            if not app.isdigit() or not installation.isdigit():
                raise ValueError('Invalid installation configuration')
            now = int(self.clock())
            signed = jwt.encode({'iat': now-30, 'exp': now+540, 'iss': app},
                                os.environ['GH_APP_PRIVATE_KEY'], algorithm='RS256')
            data = await self._request('POST', '/app/installations/'+installation+'/access_tokens', signed,
                {'repositories': ['veritas-bot'], 'permissions': {'contents': 'write', 'pull_requests': 'write',
                    'actions': 'read', 'checks': 'read', 'statuses': 'read'}})
            self.token = data['token']
            expiry = datetime.fromisoformat(data['expires_at'].replace('Z','+00:00')).timestamp()
            self.token_until = min(expiry-60, self.clock()+3000)
        return await self._request(method, PREFIX+suffix, self.token, payload)

    async def main(self):
        return oid((await self.request('GET','/git/ref/heads/main'))['object']['sha'])

    async def file(self, path, sha):
        from repair_jobs import SOURCE_FILES
        if path not in SOURCE_FILES:
            raise ValueError('Source allowlist')
        data = await self.request('GET', '/contents/'+path+'?ref='+oid(sha))
        if data.get('type') != 'file' or data.get('encoding') != 'base64' or data.get('size', 9_000_000) > 1_500_000:
            raise ValueError('Invalid source response')
        return base64.b64decode(data['content'], validate=False)

    async def commit(self, base, files, job_id, stamp):
        from repair_jobs import EDITABLE, has_secret
        tree = []
        for item in files:
            name, content = item['path'], item['content']
            if name not in EDITABLE and not re.fullmatch(r'test_repair_case_[a-z0-9_]+\.py', name):
                raise ValueError('Publish path not allowed')
            if has_secret(content):
                raise ValueError('Credential in proposed source')
            tree.append({'path': name, 'mode': '100644', 'type': 'blob', 'content': content})
        if not 1 <= len(tree) <= 6 or len({x['path'] for x in tree}) != len(tree):
            raise ValueError('Invalid file set')
        parent = await self.request('GET', '/git/commits/'+oid(base))
        new_tree = await self.request('POST', '/git/trees', {'base_tree': parent['tree']['sha'], 'tree': tree})
        author = {'name': 'VERITAS Maintainer', 'email': 'veritas-maintainer@users.noreply.github.com',
                  'date': datetime.fromtimestamp(stamp, timezone.utc).isoformat()}
        data = await self.request('POST','/git/commits', {'message': f'Fix reported bot issue #{int(job_id)}',
            'tree': new_tree['sha'], 'parents': [base], 'author': author, 'committer': author})
        return oid(data['sha'])

    async def open_pr(self, head, job_id):
        branch = 'auto/repair-'+str(int(job_id))+'-'+oid(head)[:12]
        try:
            current = await self.request('GET', '/git/ref/heads/'+branch)
            if current['object']['sha'] != head:
                raise ValueError('Unexpected branch contents')
        except GitHubError as exc:
            if exc.status != 404: raise
            await self.request('POST','/git/refs', {'ref': 'refs/heads/'+branch, 'sha': head})
        existing = await self.request('GET', '/pulls?state=all&head=diyorclash2-prog:'+branch+'&base=main')
        if existing:
            pr = existing[0]
        else:
            pr = await self.request('POST','/pulls', {'head': branch, 'base': 'main',
                'title': f'Astra repair #{int(job_id)}',
                'body': 'Automatically prepared source repair. Private incident text is not published. '
                        'Independent CI must pass for this exact commit before release.'})
        if pr['head']['sha'] != head:
            raise ValueError('PR head changed')
        return int(pr['number'])

    async def ci(self, head, pr_number):
        workflow = await self.request('GET','/actions/workflows/veritas-repair.yml')
        runs = await self.request('GET','/actions/workflows/'+str(int(workflow['id']))+
            '/runs?head_sha='+oid(head)+'&event=pull_request&per_page=30')
        matching = [r for r in runs.get('workflow_runs', []) if r.get('head_sha') == head
            and r.get('workflow_id') == workflow['id'] and r.get('event') == 'pull_request'
            and (r.get('head_repository') or {}).get('full_name') == REPO
            and any(p.get('number') == pr_number for p in r.get('pull_requests', []))]
        if not matching: return 'pending'
        latest = max(matching, key=lambda r: (r['run_number'], r.get('run_attempt', 1)))
        if latest['status'] != 'completed': return 'pending'
        return 'success' if latest.get('conclusion') == 'success' else 'failure'

    async def promote(self, base, head):
        # A non-forced fast-forward cannot overwrite a concurrent main change.
        if await self.main() == head: return head
        if await self.main() != base: raise ValueError('Main changed; regenerate and retest')
        commit = await self.request('GET', '/git/commits/'+oid(head))
        if [p['sha'] for p in commit['parents']] != [base]:
            raise ValueError('Unexpected candidate ancestry')
        result = await self.request('PATCH','/git/refs/heads/main', {'sha': head, 'force': False})
        if result['object']['sha'] != head: raise ValueError('Promotion mismatch')
        return head

    async def deployment(self, sha):
        data = await self.request('GET','/commits/'+oid(sha)+'/status?per_page=100')
        for status in data.get('statuses', []):
            if status.get('context') != RAILWAY_CONTEXT: continue
            u = urlparse(status.get('target_url') or '')
            q = parse_qs(u.query)
            if (u.scheme, u.hostname, u.path) != ('https','railway.com',f'/project/{PROJECT}/service/{SERVICE}'):
                continue
            if q.get('environmentId') != [ENVIRONMENT]: continue
            return status['state']
        return 'pending'

    async def rollback_commit(self, base, bad, job_id, stamp):
        if await self.main() != bad: raise ValueError('Main advanced; automatic rollback stopped')
        original = await self.request('GET', '/git/commits/'+oid(base))
        author = {'name':'VERITAS Maintainer','email':'veritas-maintainer@users.noreply.github.com',
                  'date':datetime.fromtimestamp(stamp, timezone.utc).isoformat()}
        result = await self.request('POST','/git/commits', {'message':f'Restore code before repair #{int(job_id)}',
            'tree':original['tree']['sha'], 'parents':[oid(bad)], 'author':author, 'committer':author})
        return oid(result['sha'])
