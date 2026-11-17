# Telegram navigation and Lingua integration

Legacy persistent buttons now have an explicit private navigation handler before
the owner chat/report handler. `/start`, `/cancel` and main section navigation
clear only that member's input sessions. Existing permission checks remain in the
destination handlers. Test and Q&A panels lead to the existing lessons, library
tests and group Zakovat; they do not create games or send advertisements.

Updates use bounded concurrency with both chat and user serialization. A long
request in one chat no longer stalls every chat. Private AI answers run as bounded
tasks (one per member, four total, 55-second deadline), so menu navigation can
continue. Dynamic translation falls back after 1.5 seconds and limits background
requests to two; inline labels use the cache and reply-command labels remain
stable. Expired query acknowledgements and unchanged-message edits are handled.

`/lingua` and the language button open native Telegram practice and the existing
website link. Onboarding saves source language, target language, stated level and
goal. There are 11 languages, hence 110 distinct source/target combinations.
The 16 multilingual seed lessons are copied from the existing Lingua project.
Each question uses its answer words plus two distractors. The server validates
the ordered answer, ownership, callback revision and one-time XP/coin awards.
Progress and in-progress questions survive restart in separate `tg_lingua_*`
tables. Difficulty rises with successful practice; completed seed questions are
not silently recycled. When a tier is exhausted the UI says so.

This is starter practice, not unlimited AI-generated lessons or a certified level
assessment. Telegram progress is separate from the web account; no OTP bypass,
phone identity merge, promo access change or automatic reward transfer is added.
The website launcher remains available for the full existing web interface.

Validation: full local unittest suite passes, including real PTB dispatch using a
network-forbidden Telegram transport and a disposable database; all primary menus
for member/owner; legacy navigation while Astra chat is active; full Lingua
onboarding and grading; 110 language combinations; replay/cross-user rejection;
restart persistence; difficulty progression; concurrent ordering; slow translation
fallback; expired callbacks and media-message navigation. This is not evidence
that paid Telegram transactions, every external provider or all group permissions
were exercised live. Independent CI must pass before release.
