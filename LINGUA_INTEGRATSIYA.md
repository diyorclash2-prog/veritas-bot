# VERITAS bot + LINGUA: ishchi versiya

Bu paket ishlayotgan `diyorclash2-prog/veritas-bot` uchun alohida LINGUA modulidir.
GitHubdagi `main` va Railway o‘zgartirilmagan. Hech bir haqiqiy kanalga xabar yuborilmadi.
Kod `work/lingua-daily-promo` ishchi tarmog‘ida ko‘rib chiqish uchun tayyorlangan.

Tekshirilgan asos: `f649c596448e4ae790fdd7e85e5034cf5cd93243`.
Botning asosiy fayliga faqat modulni ulovchi ikki satr qo‘shiladi; mavjud o‘yinlar,
kitoblar, Zakovat, admin va boshqa routerlar almashtirilmaydi.

## Qo‘shilgan imkoniyatlar

- `/lingua` yoki `*lingua`: VERITAS LINGUA sayti uchun ochish tugmasi.
- Bot biladigan va post yozish huquqiga ega bo‘lgan barcha kanallarga kunlik reklama.
- Har kanal va mahalliy sana uchun doimiy SQLite qaydi: odatiy qayta ishga tushish yoki
  bitta bazadan foydalanuvchi parallel ishchilar postni takrorlamaydi.
- Super Ega shaxsiy chatda yoqadi/o‘chiradi, vaqtni tanlaydi, kanal qo‘shadi/chiqaradi,
  reklama namunasini va yuborish holatini ko‘radi.
- Telegram yuborish tezligini cheklasa, barcha reklama yuborishlari talab qilingan
  muddatga to‘xtaydi. Kutish vaqti qayta ishga tushganda ham saqlanadi.

## Reklama manzili va matni

Hozirgi manzil: https://veritas-lingua-telefon-20261113.grittysardine4.chatgpt.site/

Sayt hozir sinov versiyasi. Shu sabab reklamada natijalar brauzerda saqlanishi,
jonli AI va SMS hali ulanmagani ochiq yozilgan. Haqiqiy server ishga tushgach,
`VL_PUBLIC_URL` orqali manzilni va `ad_text()` orqali matnni yangilash mumkin.

Reklama kanalga mos oddiy URL tugmasidan foydalanadi. Telefon ekraniga o‘rnatish
tugmasi yoki tayyor mobil ilova borligi va’da qilinmaydi.

## Tayyor birlashtirilgan kod

Ushbu ishchi tarmoqda **to‘liq `bot.py` allaqachon birlashtirilgan**.
Siz undan ikki satr qidirib qo‘shishingiz yoki eski bot kodini qo‘lda qayta yozishingiz
kerak emas. Asl botning barcha kodi saqlanib, faqat LINGUA modulini ulovchi ikki satr
qo‘shilgan. `lingua_bot_bridge.py` fayli ham uning yonida tayyor.

Ishga tegishli fayllar:

- `bot.py` — mavjud bot + tayyor LINGUA integratsiyasi.
- `lingua_bot_bridge.py` — sayt tugmasi va kunlik reklama moduli.
- `veritas_games_bridge.py` — mavjud o‘yin moduli, o‘zgartirilmagan.
- `requirements.txt` — mavjud kutubxonalar ro‘yxati, o‘zgartirilmagan.
- `test_lingua_bot_bridge.py` — yangi modulning 44 ta avtomatik testi.

Bu kod GitHubdagi `f649c596448e4ae790fdd7e85e5034cf5cd93243` versiyasiga mos.
Keyinchalik `main` o‘zgarsa, yangi kodni shu o‘zgarishlar bilan qayta birlashtirish
kerak. Ushbu o‘zgarishlar hech qanday `.env`, bot tokeni yoki foydalanuvchilar bazasini o‘z
ichiga olmaydi. Mavjud muhit sozlamalari va bazani saqlash zarur.

Ishchi tarmoqda tekshirish buyruqlari:

```bash
python -m unittest -v test_lingua_bot_bridge
python -m py_compile bot.py lingua_bot_bridge.py veritas_games_bridge.py
```

.gitignore qoidalari maxfiy fayllar, bazalar va loglarni GitHubga tasodifan yuborishdan saqlaydi.

O‘zgarishlar alohida ishchi tarmoqda ko‘rib chiqiladi.
`main` ga birlashtirish va Railway deploy hali bajarilmagan; ularga loyiha
egasining alohida aniq tasdig‘i talab etiladi.

Repozitoriyning mavjud `requirements.txt` faylidagi
`python-telegram-bot[job-queue]>=22.5,<23` yetarli; yangi server xizmati talab qilinmaydi.
Windows muhitida IANA vaqt zonalari topilmasa `python -m pip install tzdata` kerak bo‘lishi mumkin.

## Deploy tasdiqlangandan keyin boshqarish

Standart holatda avtomatik reklama o‘chiq. Rejadagi standart vaqt: har kuni
**19:00, America/New_York**. Bu vaqt taklif sifatida qo‘yilgan, o‘zgartiriladi.
Bot har 60 soniyada navbatni tekshiradi; ishga tushgach birinchi tekshiruv 20 soniyadan keyin.
Belgilangan vaqt o‘tib ketgan bo‘lsa, bot o‘sha kunning reklamasini keyingi tekshiruvda
yuboradi. Oldingi kunlar uchun yig‘ilib qolgan reklamalar yuborilmaydi.

Super Ega botning shaxsiy chatida:

| Buyruq | Vazifasi |
| --- | --- |
| `/lingua` | Saytni ochish tugmasi |
| `/lingua_ads preview` | Reklama matnini faqat shu chatda ko‘rish |
| `/lingua_ads channels` | Aniqlangan kanallar ro‘yxati |
| `/lingua_ads add @kanal_username` | Kanal va post huquqini tekshirib qo‘shish |
| `/lingua_ads add -1001234567890` | Yopiq kanalni o‘zining ID si bilan qo‘shish; bu ID namunadir |
| `/lingua_ads remove -1001234567890` | Kanalni avtomatik reklamadan chiqarish |
| `/lingua_ads time 19:00 Asia/Tashkent` | Toshkent vaqti bilan soat 19:00 ga sozlash |
| `/lingua_ads time 19:00 America/New_York` | Nyu-York vaqti bilan soat 19:00 ga sozlash |
| `/lingua_ads on` | Kunlik reklamani yoqish |
| `/lingua_ads off` | Keyingi reklamalarni to‘xtatish |
| `/lingua_ads status` | Holat, vaqt, bugungi muvaffaqiyatlar va xatolar |

Kanal ro‘yxati mavjud rebus/kitob kanal bog‘lanishlaridan, botning kanalga
administrator bo‘lib qo‘shilish yangilanishidan va yangi kanal postlaridan yig‘iladi.
Eski kanallarning hammasi mahalliy ro‘yxatda bo‘lishi kafolatlanmaydi: `channels`
orqali tekshirib, yetishmaganlarini `add` orqali qo‘shish kerak. Bot kanalda
administrator va post yozish huquqiga ega bo‘lishi shart. Guruhlar va foydalanuvchilar
jadvalidan reklama oluvchilar olinmaydi. O‘chirilgan kanal yangi post sababli
avtomatik ravishda qayta yoqilmaydi; faqat `add` uni qayta yoqadi.

## Sozlash va doimiy saqlash

Ixtiyoriy muhit o‘zgaruvchilari:

```text
VL_PUBLIC_URL=https://veritas-lingua-telefon-20261113.grittysardine4.chatgpt.site/
VL_LINGUA_AD_TIME=19:00
VL_LINGUA_AD_TZ=America/New_York
VL_LINGUA_ADS_ENABLED=0
```

Vaqt, vaqt zonasi va yoqilgan/o‘chirilgan holat bazaga birinchi marta yaratilganda
shu qiymatlardan olinadi. Keyinchalik botdagi boshqaruv buyruqlari saqlangan holatni
o‘zgartiradi; har restartda muhit qiymati foydalanuvchi sozlamasini bosib ketmaydi.
`VL_PUBLIC_URL` esa har ishga tushishda muhitdan olinadi.

Modul botning mavjud `DB_PATH` bazasiga faqat `lingua_ad_*` nomli to‘rtta jadval
qo‘shadi. Mavjud jadvallar va foydalanuvchilar ma’lumotlari o‘zgartirilmaydi.
**Bazani saqlaydigan doimiy disk zarur**: baza yo‘qolsa, oldingi yuborish qaydlari
ham yo‘qoladi. Turli ishchilar alohida baza bilan ishlasa, o‘zaro takrorni oldini
ololmaydi. Bu o‘zgarish Railway konfiguratsiyasini o‘zgartirmaydi.

Yuborish qaydi Telegramga murojaat qilishdan oldin yoziladi. Aloqa uzilib,
yuborilgan-yuborilmagani noma’lum qolsa, shu kun uchun avtomatik qayta yuborilmaydi.
Bu takrorni kamaytiradi, lekin bunday holatda bir kunlik reklama tushib qolishi
mumkin; statusda `Kutilayotgan tekshiruv` ko‘rinadi. Faqat Telegramning aniq
`RetryAfter` javobi olinganda, kutishdan so‘ng bir kunda jami uch urinishgacha ruxsat
beriladi. Telegram va server uzilishlarida har kuni aynan bir post kafolatlanmaydi.

## Orqaga qaytarish

Avval `/lingua_ads off`. Kodni qaytarish kerak bo‘lsa, alohida tasdiqlangan
o‘zgarishda `bot.py` dagi ikki yangi satrni olib tashlash kifoya. Bazani o‘chirmang:
qaydlar va eski funksiyalar ma’lumotlari saqlanib qolishi kerak.

Tekshiruvlar sintetik vaqtinchalik bazalar va Telegram javoblari bilan o‘tkazildi.
Haqiqiy bot, jonli kanal, foydalanuvchi hisobi va Railway muhiti sinovdan o‘tkazilmadi.
