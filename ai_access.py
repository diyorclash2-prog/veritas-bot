"""Stars credit and permanent private assistant access, committed atomically."""
from telegram import InlineKeyboardButton as Button, InlineKeyboardMarkup as Markup

PRICE = 100
# A fixed timestamp recognized by the existing subscription and profile schema.
LIFETIME = 253402300799


def unlock(db, payer, recipient, now):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        row = c.execute('SELECT paid_until FROM ai_user_subscriptions WHERE user_id=?', (recipient,)).fetchone()
        if row and row[0] >= LIFETIME:
            return 'active'
        changed = c.execute('UPDATE users SET wallet=wallet-? WHERE user_id=? AND wallet>=?',
                            (PRICE, payer, PRICE)).rowcount
        if not changed:
            return 'funds'
        c.execute('INSERT INTO ai_user_subscriptions(user_id,paid_until,updated_at) VALUES(?,?,?) '
                  'ON CONFLICT(user_id) DO UPDATE SET paid_until=excluded.paid_until,updated_at=excluded.updated_at',
                  (recipient, LIFETIME, now))
        c.execute('INSERT INTO tx(user_id,kind,amount,target_id,created_at) VALUES(?,?,?,?,?)',
                  (payer, 'ai_lifetime', -PRICE, recipient, now))
        return 'unlocked'


def offer():
    return Markup([[Button('✨ AI’ni faollashtirish · 100 ⭐', callback_data='aipactivate100')],
                   [Button('⭐ Hisobni to‘ldirish', callback_data='wallet')],
                   [Button('🏠 Bosh menyu', callback_data='home')]])


def valid_invoice(payload, uid, amount, currency, topups):
    parts = payload.split(':')
    return (currency == 'XTR' and amount in topups and len(parts) == 4 and
            parts[:3] == ['topup', str(uid), str(amount)] and parts[3].isascii() and parts[3].isdigit())


def credit_topup(db, uid, payment, now):
    with db() as c:
        saved = c.execute('INSERT OR IGNORE INTO payments(charge_id,user_id,amount,payload,created_at) '
                          'VALUES(?,?,?,?,?)', (payment.telegram_payment_charge_id, uid, payment.total_amount,
                                                payment.invoice_payload, now))
        if not saved.rowcount:
            return False
        changed = c.execute('UPDATE users SET wallet=wallet+? WHERE user_id=?',
                            (payment.total_amount, uid)).rowcount
        if changed != 1:
            raise ValueError('Missing wallet')
        c.execute('INSERT INTO tx(user_id,kind,amount,ref,created_at) VALUES(?,?,?,?,?)',
                  (uid, 'topup', payment.total_amount, payment.telegram_payment_charge_id, now))
        return True
