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
| `Turi` | `SINGLE_CHOICE`, `MULTIPLE_CHOICE`, `TRUE_FALSE` yoki `OPEN_ENDED` |
| `Savol` | Savol matni |
| `Variant A`–`Variant F` | Javob variantlari; `OPEN_ENDED` uchun bo'sh |
| `To'g'ri javob` | `A`; bir nechta javob uchun `A,C`; `OPEN_ENDED` uchun bo'sh |
| `Ball` | `1` dan `100` gacha, majburiy |

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

Ulashish uchun tayyor misol: [question_import_namuna.xlsx](question_import_namuna.xlsx).
