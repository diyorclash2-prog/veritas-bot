# Lingua AI — Telegram learning continuation

The `/lingua` flow now obtains new word-order exercises from the existing Astra
integration. Prompts and explanations use the learner's source language; answer
words use the target language. All 11 existing languages remain selectable in
either direction. Each generated exercise has the answer words plus exactly two
distractors. Explanations appear after grading, never before it.

Three consecutive correct answers advance difficulty by one of six tiers; two
incorrect answers lower it. The selected CEFR level remains visible separately.
XP and coins remain server-checked and idempotent. Existing accounts, seed
attempts, progress and bot modules survive additive SQLite migrations. Telegram
profiles remain separate from the web application's phone/OTP accounts.

## Generation and availability

The bot prefetches four-question batches in background tasks. Cached exercises
open immediately. When the pool is empty, a waiting screen offers navigation and
a retry button; a completion message is sent only while the learner is still
waiting there. Slow AI requests never hold the Telegram update handler.

Questions are cached by language pair, goal and difficulty. Issued question IDs
are never reissued to the same learner, including cancelled attempts. Normalized
prompt and answer uniqueness prevents exact/case/punctuation duplicates across
the question bank. The model is also asked to avoid paraphrases and trivial
variations; semantic novelty and teaching correctness cannot be guaranteed by
these structural checks alone.

The generator uses `gpt-6-astra` through Responses with one strict function output
envelope. That function only returns question data; it cannot run commands,
access files or use external tools. The service validates word counts, token
lengths, distinct distractors and response size before accepting a batch.
No learner name, phone, Telegram identity, chat history or database is sent to
the model. The generation request contains only the language profile and recent
public curriculum prompts.

## Deployment and cost control

Deploy the updated maintainer first, then the bot. Both use the existing private
Railway HMAC connection and owner allowlist. `/lingua/questions` enqueues/polls a
durable request; it never exposes the API key. No new credentials are required.
The bot needs the existing `VERITAS_AUTOREPAIR_ENABLED=1` private integration.

Generation runs in a separate maintainer worker from code repair. It shares the
existing durable $60/month conservative model-cost ledger with repair requests.
It does not create an additional $60 allowance. This ledger is not an OpenAI
invoice and does not cover unrelated existing AI callers. Each new request is
reserved before inference. Unknown billing outcomes retain their reservation.

Additional generation limits: four queued/processing batches, 12 new batches per
hour and 40 per rolling day. The bot has a maximum of four active refill tasks.
Failed batches have a ten-minute cooldown. Limits, exhausted funds or unavailable
AI leave cached exercises usable and explain that new content is unavailable;
the app does not promise an unlimited supply when the API cannot serve it.

Queue IDs persist through retries/restarts. A lost response is polled with the
same ID rather than blindly requesting another paid generation. Interrupted
in-flight work is marked failed after its lease, never automatically repeated.

## Verification

Run `python -m unittest discover -q`. Tests cover model-output validation,
refusals, duplicates, budgets, authentication and replay, queue recovery,
additive migrations, adaptive grading, reward replay, all language pairs,
background responsiveness and cancellation of late notifications. Existing
navigation, repair, ads, owner chat and spending tests remain in the suite.
