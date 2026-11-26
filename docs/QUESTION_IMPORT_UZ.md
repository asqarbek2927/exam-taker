# Savollarni XLSX orqali import qilish

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

## 3. Faylni import qilish

```http
POST /api/v1/questions/import
Authorization: Bearer <token>
Content-Type: multipart/form-data

file=<to'ldirilgan questions.xlsx>
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
