"""Bounded update scheduling and fast, cache-backed UI translation."""
import asyncio
from contextlib import AsyncExitStack
from telegram.ext import BaseUpdateProcessor


class OrderedUpdates(BaseUpdateProcessor):
    """Different chats may progress; shared chat/user state stays serialized."""
    def __init__(self, limit=16):
        super().__init__(limit)
        self.locks = {}

    async def initialize(self):
        pass

    async def shutdown(self):
        self.locks.clear()

    async def do_process_update(self, update, coroutine):
        chat = getattr(update, 'effective_chat', None)
        user = getattr(update, 'effective_user', None)
        keys = []
        if chat:
            keys.append(('chat', chat.id))
        if user:
            keys.append(('user', user.id))
        entries = []
        for key in sorted(keys):
            entry = self.locks.setdefault(key, [asyncio.Lock(), 0])
            entry[1] += 1
            entries.append((key, entry))
        started = False
        try:
            async with AsyncExitStack() as stack:
                for _, entry in entries:
                    await stack.enter_async_context(entry[0])
                started = True
                await coroutine
        finally:
            if not started and hasattr(coroutine, 'close'):
                coroutine.close()
            for key, entry in entries:
                entry[1] -= 1
                if not entry[1]:
                    self.locks.pop(key, None)


class FastTranslations:
    """Never wait a full model request per button; bound in-flight workers."""
    def __init__(self, timeout=1.5, workers=2):
        self.timeout, self.workers = timeout, workers
        self.pending = {}

    async def text(self, text, lang, cached, translate):
        if not text or lang == 'uz':
            return text
        found = cached(text, lang)
        if found:
            return found
        key = (lang, text)
        task = self.pending.get(key)
        if task is None:
            if len(self.pending) >= self.workers:
                return text
            task = asyncio.create_task(asyncio.to_thread(translate, text, lang))
            self.pending[key] = task
            def done(finished):
                self.pending.pop(key, None)
                if not finished.cancelled():
                    finished.exception()  # Retrieve errors even after fallback.
            task.add_done_callback(done)
        try:
            return await asyncio.wait_for(asyncio.shield(task), self.timeout) or text
        except Exception:
            return text


class PrivateAnswers:
    """Keep menu navigation responsive while a private AI reply is pending."""
    def __init__(self, limit=4, timeout=55):
        self.pending = {}
        self.limit, self.timeout = limit, timeout

    async def submit(self, update, context, answer):
        uid = update.effective_user.id
        if uid in self.pending:
            await update.effective_message.reply_text('⏳ Oldingi savolingizga javob tayyorlanmoqda. Menyudan foydalanishingiz mumkin.')
            return
        if len(self.pending) >= self.limit:
            await update.effective_message.reply_text('⏳ AI hozir band. Birozdan keyin qayta yozing; menyular ishlayapti.')
            return
        self.pending[uid] = True
        async def run():
            try:
                await asyncio.wait_for(answer(update, context), timeout=self.timeout)
            except TimeoutError:
                await update.effective_message.reply_text('⏱ Javob kutish vaqti tugadi. Savolingizni qayta yuboring yoki /start orqali menyuni oching.')
            finally:
                self.pending.pop(uid, None)
        context.application.create_task(run(), update=update)
