# Savollarni XLSX yoki JSON orqali import qilish

Ikki format bor va ikkalasi bir xil ishlaydi: **XLSX** (Excel) va **JSON**. Shablon
tanlangan kurs/modul uchun yuklab olinadi, to'ldiriladi va bitta endpoint orqali
yuklanadi — format fayl kengaytmasidan (`.xlsx` / `.json`) aniqlanadi.

Import fayli bitta kurs va bitta modulga tegishli bo'ladi. `difficulty` faylda
yozilmaydi; barcha import qilingan savollar uchun u avtomatik `MEDIUM` bo'ladi.
`Ball` esa har bir savol uchun majburiy.

## 1. Shablonni yuklab olish

```http
GET /api/v1/questions/import-template?course_id=<UUID>&module_id=<UUID>
Authorization: Bearer <token>
```

Backend kurs va modul nomi hamda ID'lari yozilgan `.xlsx` fayl qaytaradi.
O'qituvchi faqat o'zi biriktirilgan kurs uchun shablon olishi mumkin.

Fayldagi varaqlar:

- `Ma'lumot` — kurs va modul nomi/ID'si; bu qiymatlarni o'zgartirmaslik kerak.
- `Savollar` — import qilinadigan savollar shu yerga yoziladi.
- `Namuna` — to'ldirish misollari; bu varaq import qilinmaydi.

## 2. `Savollar` ustunlari

| Ustun | Qoida |
|---|---|
| `T/r` | Ixtiyoriy tartib raqami |
| `Turi` | `SINGLE_CHOICE`, `MULTIPLE_CHOICE`, `TRUE_FALSE`, `OPEN_ENDED` yoki `PYTHON_CODE` (katta-kichik harf, probel yoki `-` farqi yo'q: `single choice` ham bo'ladi) |
| `Savol` | Savol matni |
| `Variant A`–`Variant F` | Javob variantlari; `OPEN_ENDED` va `PYTHON_CODE` uchun bo'sh |
| `To'g'ri javob` | `A`; bir nechta javob uchun `A,C` (`a, c`, `A;C`, `AC` ham bo'ladi; kirillcha `А/В/С/Е` lotinchaga o'giriladi); `OPEN_ENDED` va `PYTHON_CODE` uchun bo'sh |
| `Ball` | `1` dan `100` gacha, majburiy; kasr `2.5` yoki `2,5` |

## Tayyor savollarni AI (ChatGPT, Gemini, Claude) bilan ko'chirish

Ustozda savollar allaqachon tayyor bo'ladi (Word, PDF, boshqa Excel yoki matn). AI **o'zi savol
yaratmaydi** — faqat ustozning savollarini shablon formatiga ko'chiradi. Shablondagi
**`AI uchun yo'riqnoma`** varag'ida o'zbekcha va ruscha tayyor prompt hamda AI uchun aniq
qoidalar yozilgan.

1. AI'ga ikkita fayl yuklang: yuklab olingan shablon va o'zingizning savollar faylingiz.
2. Yo'riqnomadagi promptni nusxalang va unda to'g'ri javoblar qanday belgilanganini yozing
   (masalan: `*` belgisi, qalin shrift yoki alohida javoblar ro'yxati).
3. AI qaytargan faylni **tekshiring** — ayniqsa to'g'ri javoblarni — va platformaga yuklang.
   Xato chiqsa, xato matnini AI'ga berib tuzattiring va qayta yuklang.

Manbada biror savolning to'g'ri javobi ko'rsatilmagan bo'lsa, AI uni taxmin qilmaydi va javob
ustuniga `?` yozadi. Import bunday qatorlarni qabul qilmaydi va aniq ko'rsatadi:
`5-qator: to'g'ri javob ko'rsatilmagan (?). Manbadan tekshirib, javob harfini yozing.`

Savollar juda ko'p bo'lsa (100+), AI'ga 30–50 tadan bo'lib bering — AI uzun javobni yarmida
to'xtatib qo'yishi mumkin.

Import AI'ning odatiy "xatolari"ni o'zi to'g'rilaydi:

| AI yozgani | Tushuniladi |
|---|---|
| `Savollar` varag'i boshqa nom bilan (`Questions`) | sarlavhalari mos yagona varaq import qilinadi (`Namuna` hech qachon emas) |
| `Ma’lumot`, `To‘g‘ri javob` ("aqlli" tirnoqlar), ortiqcha probel | `Ma'lumot`, `To'g'ri javob` |
| `Ma'lumot` varag'ida qatorlar joyi o'zgargan | Kurs ID / Modul ID A ustunidagi yorliq bo'yicha topiladi |
| Javob `B)`, `(A)`, `C.` | `B`, `A`, `C` |
| Javob variant matni bilan: `tuple, str`, `To'g'ri` | mos variant harflari |
| Variantlar `A) list`, `B) tuple` | `list`, `tuple` (faqat hamma variantda prefiks bo'lsa) |
| Turi `Python code`, `Multiple choice` | `PYTHON_CODE`, `MULTIPLE_CHOICE` |

Agar AI faylni noldan yaratib, `Ma'lumot` varag'ini (Kurs ID / Modul ID) tashlab yuborsa —
import aniq xato beradi; bunday holda shablonni qayta yuklab, AI'dan aynan shu faylni
to'ldirishni so'rang.

## JSON format

### Shablonni yuklab olish

```http
GET /api/v1/questions/import-template-json?course_id=<UUID>&module_id=<UUID>
Authorization: Bearer <token>
```

Javob — `.json` fayl (huquqlar va arxiv qoidasi XLSX shablon bilan bir xil):

```json
{
  "format": "examtaker-questions",
  "version": 1,
  "course": {"id": "<kurs id>", "name": "Python"},
  "module": {"id": "<modul id>", "title": "Module 1"},
  "instructions": {"steps_uz": "...", "prompt_uz": "...", "prompt_ru": "...", "rules": ["..."]},
  "example_questions": [ ... 5 ta namuna, import qilinmaydi ... ],
  "questions": []
}
```

Faqat `questions` ro'yxati to'ldiriladi; `course`, `module` ni o'zgartirmang.

### Savol ko'rinishi

```json
{"type": "SINGLE_CHOICE",   "text": "len([1, 2, 3]) = ?", "options": ["2", "3", "4"], "correct": ["B"], "points": 2}
{"type": "MULTIPLE_CHOICE", "text": "Immutable turlar?",  "options": ["list", "tuple", "str"], "correct": ["B", "C"], "points": 3}
{"type": "TRUE_FALSE",      "text": "Indeks 0 dan boshlanadi.", "options": ["To'g'ri", "Noto'g'ri"], "correct": ["A"], "points": 1}
{"type": "OPEN_ENDED",      "text": "List va tuple farqi?", "options": [], "correct": [], "points": 5}
{"type": "PYTHON_CODE",     "text": "sum_even(numbers) funksiyasini yozing.", "options": [], "correct": [], "points": 5}
```

| Maydon | Qoida |
|---|---|
| `type` | XLSX dagi `Turi` bilan bir xil |
| `text` | Savol matni |
| `options` | Variant matnlari (2–6 ta); `OPEN_ENDED` / `PYTHON_CODE` uchun `[]` |
| `correct` | To'g'ri variant harflari: 1-variant = `"A"`, 2-variant = `"B"`...; `OPEN_ENDED` / `PYTHON_CODE` uchun `[]`; javob noma'lum bo'lsa `["?"]` |
| `points` | `1` dan `100` gacha |

Import XLSX dagi kabi AI'ning odatiy "xatolari"ni ham qabul qiladi: natija ` ```json ` ichiga
o'ralgan bo'lsa, kalitlar boshqacha (`question`, `answer`, `ball`, `variants`), variantlar
`{"A": "...", "B": "..."}` yoki `[{"text": "...", "is_correct": true}]` ko'rinishida, javob
`"A, C"` qatori yoki variant matni bilan yozilgan bo'lsa.

Xatolarda qator raqami o'rniga **savol raqami** ko'rsatiladi (`questions` ro'yxatidagi tartib,
1 dan boshlab): `errors.file` da `3-savol: ...`, `errors.rows` da `"row": "3"`.

Namunalar: [question_import_namuna.json](question_import_namuna.json) (bo'sh shablon) va
[xlsx_test/exam_5_savol.json](xlsx_test/exam_5_savol.json) (5 ta savol, ID'lar o'rniga
`SHU_YERGA_...` — o'zingiznikini yozing).

## 3. Faylni import qilish

```http
POST /api/v1/questions/import
Authorization: Bearer <token>
Content-Type: multipart/form-data

file=<to'ldirilgan questions.xlsx yoki questions.json>
```

Muvaffaqiyatli javob:

```json
{
  "created_count": 30,
  "course_id": "...",
  "module_id": "...",
  "question_ids": ["...", "..."]
}
```

Avval barcha qatorlar tekshiriladi. Bitta qator xato bo'lsa ham hech qaysi savol
yaratilmaydi va javobda xato qatorining Excel raqami ko'rsatiladi. Fayl hajmi
5 MB va savollar soni 500 tadan oshmasligi kerak.

`PYTHON_CODE` savollari qo'lda baholanadi: student kodi serverda ishga tushirilmaydi.

Savollar soni faqat to'ldirilgan qatorlar bo'yicha hisoblanadi — formatlangan bo'sh
qatorlar (masalan, Excel yoki Google Sheets'da pastgacha tortilgan formatlash) hisobga
olinmaydi.

Ulashish uchun tayyor misol: [question_import_namuna.xlsx](question_import_namuna.xlsx).
Bu faqat **misol**: undagi Kurs ID va Modul ID soxta, uni to'g'ridan-to'g'ri import qilib
bo'lmaydi. Har doim o'z kursingiz uchun shablonni `import-template` orqali yuklab oling.
