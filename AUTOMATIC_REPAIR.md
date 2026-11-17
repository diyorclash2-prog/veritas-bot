# VERITAS avtomatik texnik yordam

2026-11-17. Super Ega bergan ruxsat doirasida bot xatolarini tekshirish,
testdan o‘tgan kodni joylash va natijani qaytarish uchun alohida boshqaruvchi.

## Ishlash tartibi

1. Super Ega botning shaxsiy chatida «Zakovat javoblarini qabul qilishni tuzat»
   kabi buyruq yozadi yoki `/super_settings` → Buyruq / tuzatishdan foydalanadi.
   Aniq topshiriq testdan o‘tgan o‘zgarishni joylashga ham ruxsat hisoblanadi;
   qayta tasdiq so‘ralmaydi.
2. Murojaat niqoblanadi va doimiy outbox orqali Railway private networkdagi
   `veritas-maintainer` xizmatiga HMAC bilan imzolanib yuboriladi.
3. Boshqaruvchi GitHub main commitini, Railway natijasini va botdan kelgan
   sog‘lomlik xabarini tekshiradi. Faqat belgilangan kod fayllaridan nusxa oladi.
4. Codex app-server (`0.167.0-alpha.4`) Astra modelini ishlatadi. Kodni o‘qish,
   qidirish va aniq matn almashtirishlari uchun to‘rtta cheklangan vosita beriladi.
   Mahalliy shell, filesystem muhiti va tashqi vositalar o‘chirilgan. Codex
   jarayoni faqat loopback gateway tokenini oladi; OpenAI/GitHub kalitlarini olmaydi.
5. Yo‘llar, hajm, sintaksis, maxfiy qiymatlar va asl fayllar SHA-256 tekshiriladi.
   Yangi regressiya testi shart. Qabul qilingan taklif alohida branch/PRga yoziladi.
6. GitHub Actions maxfiy kalitlarsiz, tarmoqsiz, yozish cheklangan Docker ichida
   test qiladi. Yangi regressiya testi oldingi kodda yiqilishi, yangi kodda esa
   barcha mavjud testlar bilan o‘tishi kerak.
7. Aynan shu head SHA, PR va workflow natijasi tekshiriladi. Main o‘zgarmagan
   bo‘lsa faqat fast-forward yoziladi (`force=false`); boshqa ish ustidan yozilmaydi.
8. Railway main o‘zgarishidan botni deploy qiladi. Boshqaruvchi aynan bot xizmati
   va production environment uchun commit holatini hamda yangi botning imzolangan
   sog‘lomlik xabarini kutadi. Faqat ikkalasi tasdiqlansa natija muvaffaqiyatli.
9. Deploy yoki bot sog‘lomligi tasdiqlanmasa oldingi tree yangi revert commit
   sifatida qaytariladi. Main oldinga ketgan bo‘lsa avtomatik qaytarish to‘xtaydi.
   Bu **faqat kod rollbacki**, ma’lumotlar bazasini orqaga qaytarmaydi.
10. Natija faqat murojaat egasiga Telegram orqali yuboriladi; Murojaatlarimdan
    qayta ko‘riladi. Yetkazilishi noma’lum xabarlar avtomatik takrorlanmaydi.

## Xizmatlar va maxfiy ma’lumotlar

Bot va boshqaruvchining alohida SQLite bazasi va volume’i bor. Botning foydalanuvchi
bazasi, telefonlari, .env va to‘liq loglari boshqaruvchiga yoki GitHub’ga berilmaydi.
Boshqaruvchi navbatida faqat niqoblangan murojaat, yuborgan egasi, kod taklifi va
chiqarish holatlari saqlanadi. Public PR matni umumiy; shaxsiy murojaat kiritilmaydi.

Boshqaruvchi alohida tekshirilgan commitga pin qilinadi. AI faqat bot.py,
lingua_bot_bridge.py, super_settings.py va yangi test_repair_case_*.py bilan
ishlaydi; o‘z ijrochisi, CI, dependency yoki credential sozlamalarini o‘zgartira olmaydi.

Codex model chaqiruvlari mahalliy gateway orqali Responses APIga yuboriladi.
Testlarni Codex ichida emas, mustaqil GitHub CI bajaradi. Eski hosted proposal
moduli saqlangan, lekin `VERITAS_REPAIR_ENABLED=0` bo‘lib qoladi.

## GitHub App uchun aniq vakolat

Faqat **diyorclash2-prog/veritas-bot** repozitoriyiga o‘rnatiladi:

| Repository permission | Daraja | Maqsad |
|---|---|---|
| Contents | Read and write | Kod nusxasi, branch/commit, tekshirilgan release va rollback |
| Pull requests | Read and write | Alohida tekshiruv PRlari |
| Actions | Read-only | Aynan kerakli workflow natijasi |
| Checks | Read-only | Tekshiruv ma’lumotlari |
| Commit statuses | Read-only | Railway natijasi |
| Metadata | Read-only | GitHub majburiy metadata |

Administration, Workflows write, boshqa repozitoriylar va Railway hisobiga
umumiy token berilmaydi. Railway uchun yangi API token kerak emas: mavjud
GitHub ulanishi deploy qiladi, holati esa commit status orqali kuzatiladi.

`GH_APP_ID`, `GH_INSTALLATION_ID`, `GH_APP_PRIVATE_KEY` faqat boshqaruvchining
Railway Variables bo‘limida saqlanadi. GitHub installation tokeni xotirada,
faqat shu bitta repo va yuqoridagi vakolatlarga cheklangan holda yaratiladi.
Kalitni Telegram yoki repozitoriyga joylamang.

## Faollashtirish

Boshqaruvchi: `python maintainer_service.py`, `/data` volume, `PORT=8080`.
Build: `Dockerfile.maintainer`; Codex versiyasi aniq mahkamlangan va image build
paytida haqiqiy Codex jarayoni soxta API bilan tekshiriladi. Public domain kerak emas.
Botda `VERITAS_MAINTAINER_URL` private hostname, imzolash kaliti esa reference.

GitHub App ulanib, jonli tekshiruvlar o‘tganidan so‘ng botda
`VERITAS_AUTOREPAIR_ENABLED=1`. Bir vaqtda bittadan ish; vazifaga 24 model
so‘rovi va 10 daqiqa chegarasi. Kunlik 3 ta ish limiti o‘rniga quyidagi dollar
hisobi ishlatiladi.

## Sarf hisobi va to‘lov havolasi

`ai_spending.py` har pullik model so‘rovidan oldin bepul input-token count
oladi va SQLite tranzaksiyasida maksimal xarajatni band qiladi. Band qilish
oylik $60 chegaradan oshsa, generatsiya yuborilmaydi. Oy America/New_York
bo‘yicha almashadi; yakunlanmagan rezervlar restart va yangi oyda saqlanadi.
Noma’lum pullik natija yangi chaqiruvlarni to‘xtatadi; qo‘lda billing bilan
solishtirmasdan rezervni olib tashlamang. Oxirgi 120 soniyada yangi pullik
chaqiruv boshlanmaydi. Model timeouti 95 soniya.

Narxlar 2026-11-17 kuni rasmiy Astra sahifasi bilan tekshirildi: barcha input
uchun konservativ $12.50/million (eng qimmat qisqa-context cache-write), output
uchun $50/million; input 200,000, output 8,000 tokendan oshmaydi. Hosted pullik
tools, background va priority tier qabul qilinmaydi. Narx o‘zgarsa koddagi
stavkalarni yangilash kerak; bu OpenAI hisobiga qo‘yilgan global billing limiti emas.

Super sozlamada «Codex xarajatlari»: joriy oy, hisoblangan va band qilingan
summa, qolgan chegara va oxirgi 5 vazifa ko‘rsatiladi. Hisob faollashgan
paytdan boshlanadi; avvalgi sarf, botning boshqa AI suhbatlari, soliq va Railway
unga kirmaydi. Haqiqiy yechilgan pul/balans deb ko‘rsatilmaydi.
«OpenAI balansini to‘ldirish» tugmasi faqat rasmiy sahifani ochadi:
https://platform.openai.com/settings/organization/billing/overview
Karta yoki to‘lov ma’lumotlari Telegramda olinmaydi; to‘lovni foydalanuvchi bajaradi.

Tahlil restartda uzilsa ikkinchi pullik ish avtomatik boshlanmaydi. Commit/PR
yozish javobi uzilsa mavjud branch/commit tekshirilib, davom ettiriladi.
CI/deploy timeoutlari ochiq xabar qilinadi; o‘chirilgan nazorat yoki yashirin
test bypassi yo‘q. Barcha eski bot funksiyalari to‘liq isbotlangan degani emas:
Sinovlar bridge, owner, transport, Codex protokoli, budget va boshqaruv ssenariylarini qamraydi.

Tekshiruv: `python -m unittest discover -q`.
