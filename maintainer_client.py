"""Authenticated bot-to-maintainer messages over Railway private networking."""
import hashlib
import hmac
import json
import os
import secrets
import time
from urllib.parse import urlparse
import httpx


class MaintainerError(RuntimeError):
    """Safe protocol metadata only; never expose response bodies or credentials."""
    def __init__(self, status, code='', retry_after=0):
        self.status = status
        self.code = code if isinstance(code, str) and code in {'daily_limit', 'job_conflict', 'invalid_request', 'authentication'} else ''
        self.retry_after = min(max(retry_after, 0), 86400) if type(retry_after) is int else 0
        super().__init__(f'Maintainer HTTP {status}')

    @property
    def permanent(self):
        return (400 <= self.status < 500 and self.status not in (408, 429)) or self.code == 'daily_limit'

    @property
    def user_message(self):
        if self.code == 'daily_limit':
            minutes = max(1, (self.retry_after + 59) // 60)
            wait = f'Taxminan {minutes} daqiqadan keyin' if self.retry_after else 'Keyinroq'
            return ('24 soatlik 3 ta avtomatik kod tuzatish limiti tugagan. '
                    f'{wait} qayta yuborishingiz mumkin. '
                    'Bu murojaat bajarilmadi. Oddiy Astra suhbati alohida ishlaydi.')
        if self.code == 'job_conflict':
            return 'Murojaat raqami avvalgi vazifaga mos kelmadi. Bu murojaat bajarilmadi; yangi murojaat yuboring.'
        return 'Tuzatish xizmati murojaatni qabul qilmadi. Murojaat saqlangan, kod o‘zgartirilmadi.'


def enabled():
    return os.getenv('VERITAS_AUTOREPAIR_ENABLED') == '1'


def signature(secret, timestamp, nonce, body, path='/'):
    return hmac.new(secret.encode(), path.encode()+b'\n'+timestamp.encode()+b'\n'+nonce.encode()+b'\n'+body, hashlib.sha256).hexdigest()


async def request(path, value):
    if path not in ('/jobs', '/status', '/heartbeat', '/budget', '/lingua/questions'): raise ValueError('Invalid maintainer route')
    url = os.getenv('VERITAS_MAINTAINER_URL', '').rstrip('/')
    parsed = urlparse(url)
    if parsed.scheme != 'http' or not (parsed.hostname or '').endswith('.railway.internal') or parsed.path:
        raise ValueError('Maintainer must use Railway private networking')
    secret = os.getenv('VERITAS_MAINTAINER_SECRET', '')
    if len(secret) < 32: raise ValueError('Maintainer credential missing')
    body = json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()
    timestamp, nonce = str(int(time.time())), secrets.token_hex(16)
    async with httpx.AsyncClient(timeout=12, follow_redirects=False) as client:
        response = await client.post(url+path, content=body, headers={'Content-Type': 'application/json',
            'X-Timestamp': timestamp, 'X-Nonce': nonce, 'X-Signature': signature(secret,timestamp,nonce,body,path)})
    if response.status_code != 200:
        try:
            error = response.json()
        except (ValueError, UnicodeError):
            error = {}
        if not isinstance(error, dict): error = {}
        raise MaintainerError(response.status_code, error.get('code'), error.get('retry_after', 0))
    return response.json()
