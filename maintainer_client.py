"""Authenticated bot-to-maintainer messages over Railway private networking."""
import hashlib
import hmac
import json
import os
import secrets
import time
from urllib.parse import urlparse
import httpx


def enabled():
    return os.getenv('VERITAS_AUTOREPAIR_ENABLED') == '1'


def signature(secret, timestamp, nonce, body, path='/'):
    return hmac.new(secret.encode(), path.encode()+b'\n'+timestamp.encode()+b'\n'+nonce.encode()+b'\n'+body, hashlib.sha256).hexdigest()


async def request(path, value):
    if path not in ('/jobs', '/status', '/heartbeat'): raise ValueError('Invalid maintainer route')
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
    if response.status_code != 200: raise RuntimeError('Maintainer request failed')
    return response.json()
