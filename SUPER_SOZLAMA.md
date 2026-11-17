# Joriy avtomatik tuzatish

Codex · Astra, avtomatik test/deploy, $60 oylik sarf nazorati va OpenAI to‘lov
tugmasining amaldagi tartibi [AUTOMATIC_REPAIR.md](AUTOMATIC_REPAIR.md) da.
Quyidagi yozuvlar oldingi integratsiya bosqichlarini ham saqlaydi; 3 ta ish
limiti faqat eski, o‘chirilgan proposal yo‘liga tegishli.

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

## Astra ulanishi — 2026-11-17

Railway ichidagi mavjud OPENAI_API_KEY bilan haqiqiy sinov bajarildi:
- Responses: gpt-6-astra, HTTP 200, completed, ASTRA_CONNECTION_OK.
- 26 input + 8 output = 34 token.
- Agents API: hosted sandbox yaratish HTTP 201; kichik Python xatosi va
  assert tekshiruvlari bilan vazifa completed; proof.txt tekshirildi.
- Sinov sessiyasi tozalandi (HTTP 200). Kalit chiqarilmadi va nusxalanmadi.

VERITAS_SUPPORT_MODEL=gpt-6-astra faqat Super sozlama tahliliga ta’sir qiladi.
Oddiy bot chatining modeli o‘zgarmaydi. Tahlil Responses API bilan store=false,
medium reasoning, 4096 output token chegarasi va 100 soniyalik kutish chegarasida.
API kaliti/ruxsat/model/kredit/limit/ulanish xatolari maxfiy javob tanasisiz
foydalanuvchiga aniq aytiladi. Hech qanday yashirin boshqa modelga o‘tish yo‘q.

## Ajratilgan kod tekshiruvi

VERITAS_REPAIR_ENABLED=1 bo‘lsa, yangi muvaffaqiyatli AI tahlilidan keyin kod
tekshiruvi navbatga qo‘yiladi. Eski murojaatlar qayta ishga tushirilmaydi.
Kuniga jami 3 ta, bir vaqtda 1 ta, vazifaga 10 daqiqalik kuzatuv chegarasi.
Bu xarajatning qat’iy dollar limiti emas; API model/container haqi alohida.

repair_jobs.py faqat belgilangan 9 ta kod/test faylini OpenAI-hosted sandboxga
jo‘natadi. .env, ma’lumotlar bazasi, to‘liq loglar, katalogni umumiy arxivlash
va runtime kalitlari yuborilmaydi. Symlink va kod ichida topilgan kalit eksportni
bekor qiladi. Sandbox tarmog‘i o‘chirilgan, maxfiy env yoki GitHub/Railway
credential berilmagan. Mahalliy kodni bot jarayonida exec/import/subprocess
orqali bajarish yo‘q.

Agentga tegishli kodni tekshirish, tor tuzatish, mavjud offline testlar va yangi
regressiya testini bajarish vazifasi beriladi. Javobdagi o‘zgarishlar faqat bot.py,
lingua_bot_bridge.py, super_settings.py va yangi test_repair_case_*.py fayllarida
qabul qilinadi. Eski testlar va repair modullarini almashtirish rad qilinadi.
Natija JSON shakli, fayl yo‘llari, hajmi, Python sintaksisi va asl fayllarning
SHA-256 qiymatlari tekshiriladi. Asl fayllar o‘zgargan bo‘lsa taklif rad qilinadi.

Kod/takliflar doimiy SQLite bazasida saqlanadi. Restart saqlangan sessiyani davom
ettiradi. Sessiya IDsi vazifa yuborilishidan oldin saqlanadi; vazifa yuborishdagi
noaniq javoblar bir xil idempotency key bilan takrorlanadi. Yaratish natijasi
noma’lum bo‘lsa ikkinchi pullik vazifa boshlanmaydi. Remote cancellation/cleanup
cheklangan urinishlar bilan bajariladi; ulanish uzilishi uni kafolatlamaydi.

Tuzatish .patch fayli faqat murojaat yuborgan Super Egaga keladi. Murojaatlarim
bo‘limidan qayta olish yoki ishlayotgan tekshiruvni bekor qilish mumkin. Telegram
yetkazilishi noma’lum bo‘lsa avtomatik qayta yuborilmaydi.

Agentning test hisoboti mustaqil CI tekshiruvi emas. candidate — faqat taklif;
hech qachon ishlab turgan botdagi xato tuzatildi degani emas.

## Hali ulanmagan: avtomatik GitHub yozuvi va deploy

Bu modul shu ChatGPT suhbatiga xabar yubormaydi. Astra — alohida API agenti.
Botda GitHub yoki Railway avtomatik ijrochi credentiali yo‘q. ChatGPT ichidagi
interaktiv plagin ruxsatlari bot jarayoniga berilmaydi.

Keyingi ulanish: faqat diyorclash2-prog/veritas-bot uchun GitHub App, tekshirilgan
commitga bog‘langan mustaqil CI, Railway deployment natijasini tekshirish va
qaytarish mexanizmi. Hozir patch avtomatik main’ga yozilmaydi va deploy qilmaydi.
GitHub/Railway tokenlarini Telegram xabariga yoki repozitoriyga joylamang.

## Tekshiruv

python -m unittest -q test_lingua_bot_bridge test_super_settings test_astra_support test_repair_jobs

113 offline test o‘tdi. Jonli Astra Responses va kichik hosted sandbox vazifasi
alohida tasdiqlandi. Haqiqiy foydalanuvchi murojaatidan to botdagi ishlab turgan
xatoni avtomatik tuzatishgacha bo‘lgan yo‘l hali to‘liq yoqilmagan.

Rasmiy API manbalari:
https://developers.openai.com/api/docs/models/gpt-6-astra
https://developers.openai.com/api/docs/guides/agents-api/environments/openai-hosted
https://developers.openai.com/api/docs/guides/agents-api/sessions
# Astra suhbat va buyruqlar

Botning shaxsiy chatida `/super_settings` yoki **⚙️ Super sozlama** orqali:

- **💬 Astra bilan suhbat** — ketma-ket savol-javob; oxirgi 6 almashinuv kontekstga kiradi. Har bir Super Eganing tarixi alohida. Faol suhbat 30 daqiqada tugaydi.
- **🛠 Buyruq / tuzatish** — aniq vazifa yoki xatoni saqlaydi, Astra tahlilini qaytaradi. Avtomatik joylash faqat GitHub App ulanishi tekshirilgach yoqiladi.
- **📖 Suhbat tarixi** — o‘zingizning oxirgi javoblaringiz; **🧹 Suhbatni tozalash** — o‘zingizning tarixingizni o‘chiradi.
- **✖️ Bekor qilish** yoki `/super_settings` suhbatdan chiqaradi. Eski `/` va `*` buyruqlar o‘z handlerlariga uzatiladi.

Suhbatda kod yoki server buyruqlari bajarilmaydi. Kod vazifasi alohida tugma orqali yuboriladi; haqiqiy natija **Murojaatlarim**da ko‘rinadi. Suhbat navbati restartdan saqlanadi, noaniq API/Telegram natijasi avtomatik takrorlanmaydi. Maxfiy qiymatlar tozalanadi. Tarix 24 soat bilan cheklangan; bir egaga 20 xabar/soat, jami 100 xabar/kun.

Amaldagi avtomatik tuzatish arxitekturasi: [AUTOMATIC_REPAIR.md](AUTOMATIC_REPAIR.md). Quyidagi eski hosted-proposal yo‘li hozir o‘chirilgan.

GitHub App kaliti ulanmaguncha `VERITAS_REPAIR_ENABLED=1` va `VERITAS_REPAIR_PROVIDER=responses` rejimi ishlatiladi: Astra ruxsat etilgan kodni o‘qib, sintaksisi tekshirilgan `.patch` va yangi test taklifini Super Egaga qaytaradi. Model kodi serverda bajarilmaydi. Bu taklifga mustaqil CI hali qo‘llanmagan va u avtomatik joylanmaydi. `VERITAS_AUTOREPAIR_ENABLED=0` GitHub ulanishi yakunlanmaguncha saqlanadi.
