"""Durable reservations for this service's model calls, not an OpenAI invoice.

No request is sent without an atomic reservation. Unknown outcomes keep their
reservation across restarts/month boundaries. All amounts are integer nanodollars.
"""
from __future__ import annotations
import asyncio
from datetime import datetime
import json
import time
import uuid
from zoneinfo import ZoneInfo

from astra_support import AIUnavailable, ASTRA, OpenAITransport

UNIT = 1_000_000_000
LIMIT = 60 * UNIT
TZ = ZoneInfo('America/New_York')
# Standard, short-context Astra prices checked 2026-11-17. Treat ALL input as
# the most expensive 30-minute cache write; actual invoices can be lower.
INPUT_RATE = 12_500  # $12.50 / million, in nanodollars/token
OUTPUT_RATE = 50_000
MAX_INPUT = 200_000
MAX_OUTPUT = 8_000


class BudgetError(AIUnavailable):
    def __init__(self, code='monthly_budget'):
        super().__init__(code)

    @property
    def user_message(self):
        return {
            'monthly_budget': 'Oylik $60 AI sarf chegarasida bu so‘rovga mablag‘ yetmaydi. Yangi pullik so‘rov yuborilmadi.',
            'budget_uncertain': 'Oldingi AI so‘rovi xarajati tasdiqlanmadi. Ortiqcha sarf bo‘lmasligi uchun yangi pullik so‘rovlar to‘xtatildi.',
            'budget_rollover': 'Hisob oyi almashmoqda. Bir necha daqiqadan keyin qayta yuboring.',
            'budget_pricing': 'AI narxi yoki hisob formati tekshiruvni talab qiladi. Yangi pullik so‘rov yuborilmadi.',
        }.get(self.code, 'AI sarf nazorati so‘rovni to‘xtatdi.')


def period(stamp):
    now = datetime.fromtimestamp(stamp, TZ)
    year, month = (now.year+1, 1) if now.month == 12 else (now.year, now.month+1)
    return now.strftime('%Y-%m'), datetime(year, month, 1, tzinfo=TZ).timestamp()


class Spending:
    def __init__(self, database, *, clock=time.time):
        self.database, self.clock = database, clock
        with database.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS ai_spending (
                    id TEXT PRIMARY KEY, period TEXT NOT NULL, scope TEXT NOT NULL,
                    created INTEGER NOT NULL, reserved INTEGER NOT NULL,
                    charged INTEGER NOT NULL DEFAULT 0, state TEXT NOT NULL DEFAULT 'reserved');
                CREATE TABLE IF NOT EXISTS ai_spending_meta (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL);
            ''')
            db.execute("INSERT OR IGNORE INTO ai_spending_meta VALUES('started',?)", (str(int(clock())),))

    def reserve(self, amount, scope):
        if type(amount) is not int or not 0 < amount <= LIMIT:
            raise BudgetError()
        now = self.clock()
        month, end = period(now)
        if end-now < 120: raise BudgetError('budget_rollover')
        with self.database.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute("SELECT 1 FROM ai_spending_meta WHERE key='blocked'").fetchone():
                raise BudgetError('budget_uncertain')
            used = db.execute("SELECT COALESCE(SUM(CASE WHEN state='reserved' THEN reserved ELSE charged END),0) "
                              "FROM ai_spending WHERE period=? OR state='reserved'", (month,)).fetchone()[0]
            if used+amount > LIMIT: raise BudgetError()
            ident = uuid.uuid4().hex
            db.execute('INSERT INTO ai_spending(id,period,scope,created,reserved) VALUES(?,?,?,?,?)',
                       (ident, month, str(scope)[:80], int(now), amount))
        return ident

    def block(self):
        with self.database.db() as db:
            db.execute("INSERT OR IGNORE INTO ai_spending_meta VALUES('blocked','1')")

    def settle(self, ident, charge):
        with self.database.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM ai_spending WHERE id=?', (ident,)).fetchone()
            if not row or row['state'] != 'reserved': raise ValueError('Unknown reservation')
            if type(charge) is not int or not 0 <= charge <= row['reserved']:
                db.execute("INSERT OR IGNORE INTO ai_spending_meta VALUES('blocked','1')")
                invalid = True
            else:
                db.execute("UPDATE ai_spending SET charged=?,state='settled' WHERE id=?", (charge,ident))
                invalid = False
        if invalid: raise BudgetError('budget_uncertain')

    def snapshot(self, scope=None):
        month, _ = period(self.clock())
        with self.database.db() as db:
            rows = db.execute("SELECT * FROM ai_spending WHERE period=? OR state='reserved'", (month,)).fetchall()
            started = db.execute("SELECT value FROM ai_spending_meta WHERE key='started'").fetchone()[0]
            blocked = bool(db.execute("SELECT 1 FROM ai_spending_meta WHERE key='blocked'").fetchone())
            task = db.execute("SELECT COALESCE(SUM(CASE WHEN state='reserved' THEN reserved ELSE charged END),0) "
                              "FROM ai_spending WHERE scope=?", (scope,)).fetchone()[0] if scope else None
        charged = sum(r['charged'] for r in rows if r['state']=='settled')
        reserved = sum(r['reserved'] for r in rows if r['state']=='reserved')
        return {'period':month, 'limit_usd':60, 'accounted_usd':charged/UNIT,
                'reserved_usd':reserved/UNIT, 'remaining_usd':max(0,LIMIT-charged-reserved)/UNIT,
                'task_usd':task/UNIT if task is not None else None,
                'blocked':blocked, 'started':int(started), 'basis':'conservative_model_cost'}


class MeteredAPI(OpenAITransport):
    def __init__(self, spending, scope, *, upstream=None):
        self.spending, self.scope = spending, scope
        self.upstream = upstream or OpenAITransport()

    async def json(self, method, path, *, payload=None, **kwargs):
        if method != 'POST' or path != '/responses' or kwargs:
            raise BudgetError('budget_pricing')
        # No hosted tools, uploads, cache retention upgrades, background jobs or
        # unknown models can bypass the model-only accounting policy.
        allowed = {'model','input','instructions','tools','tool_choice','parallel_tool_calls',
                   'reasoning','include','max_output_tokens','store','service_tier'}
        if (not isinstance(payload,dict) or set(payload)-allowed or payload.get('model') != ASTRA
                or len(json.dumps(payload)) > 900_000
                or any(t.get('type')!='function' for t in payload.get('tools',[]))):
            raise BudgetError('budget_pricing')
        output = payload.get('max_output_tokens',MAX_OUTPUT)
        if type(output) is not int or not 1 <= output <= MAX_OUTPUT:
            raise BudgetError('budget_pricing')
        count_fields = {'model','input','instructions','tools','tool_choice','parallel_tool_calls','reasoning'}
        counted = await self.upstream.json('POST','/responses/input_tokens',
            payload={k:v for k,v in payload.items() if k in count_fields})
        n = counted.get('input_tokens')
        if type(n) is not int or not 0 <= n <= MAX_INPUT: raise BudgetError('budget_pricing')
        # Small protocol/tokenizer margin; cap input below long-context pricing.
        bound = min(MAX_INPUT, n+1024)
        reserved = bound*INPUT_RATE + output*OUTPUT_RATE
        ident = self.spending.reserve(reserved,self.scope)
        request = {**payload,'service_tier':'default','store':False,'max_output_tokens':output}
        try:
            data = await asyncio.wait_for(self.upstream.json('POST','/responses',payload=request),timeout=95)
            usage = data.get('usage') or {}
            incoming, outgoing = usage.get('input_tokens'), usage.get('output_tokens')
            if (data.get('model') != ASTRA or data.get('service_tier') != 'default'
                    or type(incoming) is not int or not 0 <= incoming <= bound
                    or type(outgoing) is not int or not 0 <= outgoing <= output):
                raise BudgetError('budget_uncertain')
            self.spending.settle(ident,incoming*INPUT_RATE+outgoing*OUTPUT_RATE)
        except AIUnavailable as exc:
            if exc.code in {'authentication','permission','quota','rate_limit','model_not_found'}:
                # Explicit pre-generation rejection: no inference ran. Funding
                # or fixing the key should not require erasing an unknown bill.
                self.spending.settle(ident,0)
            else:
                self.spending.block()
            raise
        except BaseException:
            self.spending.block()
            raise
        return data
