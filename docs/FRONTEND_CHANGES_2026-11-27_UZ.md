# Backend o'zgarishlari — frontend uchun (2026-11-27)

**Qisqasi:** savollarni import qilish uchun XLSX'dan tashqari **JSON** format qo'shildi.
Hech narsa olib tashlanmagan yoki nomi o'zgarmagan — mavjud XLSX oqimi avvalgidek ishlaydi.

## Frontda nima qilish kerak

1. Import sahifasiga **"Скачать шаблон JSON"** tugmasini qo'shing (XLSX tugmasi yonida).
2. Fayl tanlash maydonida `.json` ga ham ruxsat bering: `accept=".xlsx,.json"`.
3. Yuklash so'rovi **o'zgarmaydi** — o'sha endpoint, o'sha `file` maydoni.

## 1. Yangi endpoint: JSON shablon

```http
GET /api/v1/questions/import-template-json?course_id=<UUID>&module_id=<UUID>
Authorization: Bearer <token>
```

- XLSX shablon (`/questions/import-template`) bilan bir xil parametrlar, huquqlar va xatolar
  (kursga biriktirilmagan teacher → `403`, arxivlangan kurs → `400`).
- Javob: `Content-Type: application/json`,
  `Content-Disposition: attachment; filename="questions-<course_id>-<module_id>.json"`.
- Faylni XLSX dagi kabi blob qilib yuklab bering. Nomini kurs/modul nomi bilan qo'yish
  tavsiya etiladi, masalan `Python - Module 1 - savollar.json`.

Fayl ichidagi tuzilma (front uni o'qishi shart emas, faqat yuklab beradi):

```json
{
  "format": "examtaker-questions",
  "version": 1,
  "course": {"id": "...", "name": "Python"},
  "module": {"id": "...", "title": "Module 1"},
  "instructions": {"steps_uz": "...", "prompt_uz": "...", "prompt_ru": "...", "rules": ["..."]},
  "example_questions": ["... import qilinmaydi ..."],
  "questions": []
}
```

## 2. Import: `.json` fayl ham qabul qilinadi

```http
POST /api/v1/questions/import        (multipart/form-data, maydon: file)
```

- Format fayl kengaytmasidan aniqlanadi: `.xlsx` yoki `.json`.
- Muvaffaqiyatli javob **o'zgarmagan**: `201 {"created_count", "course_id", "module_id", "question_ids"}`.
- Xato formati **o'zgarmagan**:
  - `errors.file` — ro'yxat (bir nechta xabar bo'lishi mumkin — hammasini ko'rsating);
  - `errors.rows` — `[{"row": "3", "errors": {...}}]`.
- Farqi faqat matnda: JSON uchun `row` — **savol raqami** (`questions` ro'yxatidagi tartib,
  1 dan), xabarlarda `"3-savol: ..."` (XLSX da `"3-qator: ..."`).
- Noto'g'ri kengaytma xabari endi: `"Faqat .xlsx yoki .json formatidagi fayl qabul qilinadi."`

## Tekshirish ro'yxati

- [ ] "Скачать шаблон JSON" — fayl yuklanadi, ichida tanlangan kurs/modul.
- [ ] `docs/xlsx_test/exam_5_savol.json` (ID'larni o'zingiznikiga almashtirib) — `201`, 5 ta savol.
- [ ] Buzuq JSON (masalan, bitta qavs o'chirilgan) — `422`, `errors.file` da qator/ustun bilan xabar.
- [ ] XLSX import avvalgidek ishlaydi.
