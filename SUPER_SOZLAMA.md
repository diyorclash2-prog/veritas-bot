# Guruh reklamasi va Super sozlama

2026-11-17. Avvalgi kanal reklamasi guruh va superguruhlarga kengaytirildi.
Vaqt, yoqilgan/o‘chirilgan holat va yuborish tarixi saqlanadi. `groups` jadvalidagi
manfiy Telegram chat IDlar ro‘yxatga olinadi; shaxsiy akkauntlarga reklama yuborilmaydi.
Har yuborishda bot a’zoligi va yozish huquqi tekshiriladi. Telegram botlar uchun
barcha chatlarni bir so‘rovda ro‘yxatlash API bermaydi: eski `groups` jadvali,
a’zolik hodisalari va bot ko‘rgan guruh xabarlari manba bo‘ladi.

`/lingua_ads channels` yoki `/lingua_ads chats` endi kanal va guruhlarni ko‘rsatadi.
`/lingua_ads add -100...` bilan yetishmayotgan guruh qo‘shiladi. `remove` orqali
chiqarish qayta aniqlashda ham saqlanadi. Guruh superguruhga ko‘chirilganda kunlik
yuborish tarixi va o‘chirish holati ko‘chiriladi.

## Super Ega uchun

`/super` menyusida **⚙️ Super sozlama**, yoki bevosita `/super_settings`:

- Xatoni yuborish: 10 daqiqalik matn kiritish oynasi, 10–2000 belgi.
- Murojaatlarim: oxirgi 5 ta shaxsiy murojaat va natijasi.
- Bot holati: bazani o‘qish, Lingua va rejalashtiruvchi mavjudligi.
- Reklamani yoqish/o‘chirish va holatini ko‘rish.

Faqat `SUPER_OWNER_IDS` dagi foydalanuvchilar, faqat shaxsiy chatda.
Super Adminning o‘zi yetarli emas. Callback soxtalashtirish ham tekshiriladi.
Har egaga 24 soatda 5 murojaat. Takror Telegram update bitta yozuvga olib keladi.
Maxfiy kalitlar, havolalar va kontaktlar saqlash/yuborish oldidan niqoblanadi;
bu barcha mumkin bo‘lgan shaxsiy ma’lumotlarni aniqlash kafolati emas — ularni
murojaatga yozmang. Murojaatlar faqat Railway doimiy SQLite bazasida saqlanadi,
ochiq GitHub issue yoki repozitoriyga yuborilmaydi.

## Ishlaydigan AI tahlili

Bot mavjud `OPENAI_API_KEY` bilan OpenAI Responses API ga murojaat matni va
cheklangan diagnostikani yuboradi. `VERITAS_SUPPORT_MODEL` → `OPENAI_MODEL` →
botdagi mavjud standart model tartibi ishlatiladi. API uchun yangi kalit kodda yo‘q.
`store=false`; hech qanday shell, fayl yoki deploy vositasi modelga berilmaydi.
Diagnostika foydalanuvchilar jadvallari, xabarlar tarixi, `.env` yoki to‘liq
loglarni o‘qimaydi. Xato loglaridan faqat xato turi, modul/funksiya/satr olinadi.
Natija murojaat muallifiga Telegramda qaytadi. Yetkazish natijasi noma’lum bo‘lsa,
takror yuborilmaydi; saqlangan javobni **Murojaatlarim** dan ko‘rish mumkin.
Kalit/model/ulanish ishlamasa, murojaat saqlanib, tahlil bajarilmagani ochiq aytiladi.

## Hali ulanmagan: avtomatik kod tuzatish va deploy

Bu modul ChatGPT suhbatiga xabar yubormaydi va o‘zini tuzatadigan agent emas.
AI javobi diagnostik taxmin; kod o‘zgargani yoki xato tuzalgani haqida dalil emas.
UI har natijada kod o‘zgartirilmaganini ko‘rsatadi.

To‘liq avtomatik ta’mirlash uchun alohida izolyatsiyalangan worker zarur: shaxsiy
murojaat navbatiga kirish, GitHub App orqali shu repozitoriyga yozish, test muhiti,
Railway deploy/rollback ruxsati, tekshirilgan commit/deploy natijasini navbatga
qaytarish. ChatGPT’da ulangan interaktiv plaginlar botga avtomatik credential bermaydi.
GitHub/Railway tokenlarini bot xabariga yoki ochiq repozitoriyga joylamang.
Worker ulanmaguncha `reviewed` holati faqat “tahlil tayyor; tuzatish kutilmoqda”.

## Tekshiruv

`python -m unittest -q test_lingua_bot_bridge test_super_settings`

73 test o‘tdi: kanal/guruh ruxsatlari, kunlik takrorni bostirish, migratsiya,
restart, eski jadvalni saqlash, private chatga reklama yubormaslik, Super Ega
chegarasi, kiritish sessiyasi, limit/dedup, credential niqoblash, navbat claimi,
AI xatosi, Telegram timeout, muallifga qayta xabar, begona murojaatlarni bermaslik.
Testlar sintetik bazalar va soxta API javoblari bilan; jonli AI yoki barcha
eski bot funksiyalari uchun to‘liq regressiya testi emas.

OpenAI API manbasi: https://developers.openai.com/api/reference/resources/responses/methods/create
