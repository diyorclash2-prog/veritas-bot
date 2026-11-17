# VERITAS avtomatik texnik yordam

2026-11-17. Super Ega bergan ruxsat doirasida bot xatolarini tekshirish,
testdan o‘tgan kodni joylash va natijani qaytarish uchun alohida boshqaruvchi.

## Ishlash tartibi

1. Super Ega botning shaxsiy chatida `/super_settings` orqali xatoni yuboradi.
2. Murojaat niqoblanadi va doimiy outbox orqali Railway private networkdagi
   `veritas-maintainer` xizmatiga HMAC bilan imzolanib yuboriladi.
3. Boshqaruvchi GitHub main commitini, Railway natijasini va botdan kelgan
   sog‘lomlik xabarini tekshiradi. Faqat belgilangan kod fayllaridan nusxa oladi.
4. Astra Responses API orqali kodni o‘qiydi va aniq matn almashtirishlarini
   taklif qiladi. Modelda shell, GitHub tokeni yoki deploy vositasi yo‘q.
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

OpenAI hosted coding sessiondagi beqarorlikka bog‘lanmaslik uchun yangi yo‘l
Responses API + mustaqil GitHub CI dan foydalanadi. Eski hosted proposal moduli
saqlangan, lekin `VERITAS_REPAIR_ENABLED=0` bo‘lib qoladi.

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
Build: `pip install -r requirements-maintainer.txt`. Public domain kerak emas.
Botda `VERITAS_MAINTAINER_URL` private hostname, imzolash kaliti esa reference.

GitHub App ulanib, jonli tekshiruvlar o‘tganidan so‘ng botda
`VERITAS_AUTOREPAIR_ENABLED=1`. Ungacha 0. Yangi murojaatlar uchun kuniga jami
3 ta avtomatik ish, bir vaqtda bittadan; AI uchun 12 so‘rov va 10 daqiqa chegarasi.
Bu API xarajatining qat’iy dollar limiti emas.

Tahlil restartda uzilsa ikkinchi pullik ish avtomatik boshlanmaydi. Commit/PR
yozish javobi uzilsa mavjud branch/commit tekshirilib, davom ettiriladi.
CI/deploy timeoutlari ochiq xabar qilinadi; o‘chirilgan nazorat yoki yashirin
test bypassi yo‘q. Barcha eski bot funksiyalari to‘liq isbotlangan degani emas:
139 test amaldagi bridge, owner, transport va avtomatik boshqaruv ssenariylarini qamraydi.

Tekshiruv: `python -m unittest -q test_lingua_bot_bridge test_super_settings test_astra_support test_repair_jobs test_maintainer`.
