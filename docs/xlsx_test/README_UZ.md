# XLSX orqali savol qo'shishni test qilish

Bu papkada qo'lda test qilish uchun 3 ta tayyor fayl bor. Ular avtomatik test
(`apps/questions/tests/test_xlsx_test_files.py`) bilan ham tekshiriladi, ya'ni har doim
shu yerda yozilgandek ishlaydi.

| Fayl | Nimani tekshiradi | Kutilgan natija |
|---|---|---|
| `1_togri_savollar.xlsx` | 5 xil tur va import qulayliklari (12 ta savol) | **201**, `created_count: 12` |
| `2_xatoli_javob_harflari.xlsx` | Javob harfi xatolari | **422**, `errors.file` ichida 4 ta xato birdaniga |
| `3_xatoli_qiymatlar.xlsx` | Matn, ball va variantlardagi xatolar | **422**, `errors.rows` ichida 8 ta qator |

Xato bo'lsa, faylda to'g'ri qatorlar bo'lsa ham **hech bir savol saqlanmaydi**.

---

## 0. Tayyorgarlik

- Server ishlab turgan bo'lishi kerak: `python manage.py runserver` → `http://localhost:8000`.
- **Kim import qila oladi:** Super Admin yoki shu kursga biriktirilgan Teacher/Support teacher.
- **Qanday kurs va modulga:** kurs arxivlanmagan, modul esa `ACTIVE` holatda bo'lishi kerak.
- Lokal bazada kurs yo'q bo'lsa, demo ma'lumot yaratish mumkin (faqat lokal uchun):

```powershell
python manage.py seed_demo
```

> `seed_demo` bazaga demo userlar, kurslar va modullar **qo'shadi**. Uni production'da
> ishlatmang.

## 1. API'lar

Hamma so'rovlarda `Authorization: Bearer <access_token>` sarlavhasi bo'lishi kerak.

| # | Metod | URL | Vazifasi |
|---|---|---|---|
| 1 | POST | `/api/v1/auth/login` | Token olish |
| 2 | GET | `/api/v1/courses` | Kurslar ro'yxati, bu yerdan `id` olinadi |
| 3 | GET | `/api/v1/courses/{course_id}/modules` | Kurs modullari, bu yerdan `id` olinadi |
| 4 | GET | `/api/v1/questions/import-template?course_id=..&module_id=..` | ID'lari yozilgan tayyor shablon (`.xlsx`) |
| 5 | POST | `/api/v1/questions/import` (`multipart/form-data`, maydon: `file`) | Faylni import qilish |
| 6 | GET | `/api/v1/questions?module_id=..` | Import qilingan savollarni ko'rish |

Swagger'da ham sinab ko'rish mumkin: `http://localhost:8000/api/docs`
(`questions` bo'limi → `import-template` va `import`).

## 2. PowerShell bilan qadamma-qadam

**1) Login qilish.** Login va parolni o'zingizniki bilan almashtiring:

```powershell
$BASE = "http://localhost:8000/api/v1"
$login = Invoke-RestMethod -Method Post -Uri "$BASE/auth/login" -ContentType "application/json" -Body '{"username_or_email":"LOGIN","password":"PAROL"}'
$H = @{ Authorization = "Bearer $($login.access_token)" }
```

**2) Kurs va modul ID'larini olish:**

```powershell
(Invoke-RestMethod -Uri "$BASE/courses" -Headers $H).data | Select-Object id, name, status
```

```powershell
$COURSE = "<kurs id>"
(Invoke-RestMethod -Uri "$BASE/courses/$COURSE/modules" -Headers $H).data | Select-Object id, title, status
```

```powershell
$MODULE = "<modul id>"
```

**3) Shablonni yuklab olish.** Bu ixtiyoriy: test fayllarida ID'ni qo'lda yozsangiz ham bo'ladi.

```powershell
Invoke-WebRequest -Uri "$BASE/questions/import-template?course_id=$COURSE&module_id=$MODULE" -Headers $H -OutFile "shablon.xlsx"
```

**4) Test faylini tayyorlash.** Faylni Excel'da oching → `Ma'lumot` varag'i →
sariq rangdagi **B2** katakka kurs ID'sini, **B4** katakka modul ID'sini yozing → saqlang.

**5) Import qilish.** Windows'da `curl.exe` deb yozing, shunchaki `curl` emas:

```powershell
curl.exe -s -X POST "$BASE/questions/import" -H "Authorization: Bearer $($login.access_token)" -F "file=@docs/xlsx_test/1_togri_savollar.xlsx"
```

**6) Natijani ko'rish:**

```powershell
(Invoke-RestMethod -Uri "$BASE/questions?module_id=$MODULE" -Headers $H).data | Select-Object type, text, default_points
```

Postman'da: `POST {{BASE}}/questions/import` → Authorization: Bearer Token → Body: `form-data`,
key `file`, turini **File** qilib faylni tanlang.

## 3. Faylning ko'rinishi (format)

Fayl 3 ta varaqdan iborat:

- **`Ma'lumot`** — B2 = Kurs ID, B4 = Modul ID. Boshqa qatorlar faqat ma'lumot uchun.
- **`Savollar`** — savollar shu yerga yoziladi. 1-qatordagi sarlavhalarni **o'zgartirmang**.
- **`Namuna`** — misollar, bu varaq import qilinmaydi.

`Savollar` varag'ining ustunlari (A–K):

| T/r | Turi | Savol | Variant A | Variant B | Variant C | Variant D | Variant E | Variant F | To'g'ri javob | Ball |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | SINGLE_CHOICE | Python'da list qaysi qavs bilan yoziladi? | ( ) | [ ] | { } | < > | | | B | 2 |
| 2 | MULTIPLE_CHOICE | Qaysilari immutable turlar? | list | tuple | str | dict | | | B,C | 3 |
| 3 | TRUE_FALSE | Python'da indekslash 0 dan boshlanadi. | To'g'ri | Noto'g'ri | | | | | A | 1 |
| 4 | OPEN_ENDED | List va tuple farqini tushuntiring. | | | | | | | | 5 |
| 5 | PYTHON_CODE | `add(a, b)` funksiyasini yozing. | | | | | | | | 5 |

### Qoidalar

| Tur | Variantlar | To'g'ri javob | Baholash |
|---|---|---|---|
| `SINGLE_CHOICE` | kamida 2 ta | aynan 1 ta harf | avtomatik |
| `MULTIPLE_CHOICE` | kamida 2 ta | 1 yoki undan ko'p harf | avtomatik (qisman ball) |
| `TRUE_FALSE` | aynan 2 ta | aynan 1 ta harf | avtomatik |
| `OPEN_ENDED` | bo'sh | bo'sh | teacher qo'lda baholaydi |
| `PYTHON_CODE` | bo'sh | bo'sh | teacher qo'lda baholaydi (kod serverda ishga tushirilmaydi) |

- **Ball:** `1` dan `100` gacha, majburiy. `2.5` yoki `2,5` ko'rinishida kasr ham bo'ladi.
- **Variantlar matni:** bir savol ichida takrorlanmasligi kerak (katta-kichik harf farqi hisobga olinmaydi).
- **Hajm:** bitta faylda ko'pi bilan 500 ta savol va 5 MB.

### Import nimalarni o'zi to'g'rilaydi

| Yozilgani | Tushuniladi |
|---|---|
| `single choice`, `Single-Choice`, ` SINGLE_CHOICE ` | `SINGLE_CHOICE` |
| `a, c` / `A;C` / `A C` / `AC` | `A` va `C` |
| kirillcha `А`, `В`, `С`, `Е` (rus klaviaturasi) | lotincha `A`, `B`, `C`, `E` |
| `2,5` | `2.5` |
| pastgacha tortilgan formatlash (bo'sh qatorlar) | hisobga olinmaydi |

AI (ChatGPT va h.k.) to'ldirgan fayllar uchun qo'shimcha qulayliklar va tayyor prompt —
`docs/QUESTION_IMPORT_UZ.md` dagi "Tayyor savollarni AI bilan ko'chirish" bo'limida va shablondagi
`AI uchun yo'riqnoma` varag'ida.

## 4. Kutilgan javoblar

**`1_togri_savollar.xlsx` → 201:**

```json
{"created_count": 12, "course_id": "...", "module_id": "...", "question_ids": ["...", "..."]}
```

**`2_xatoli_javob_harflari.xlsx` → 422.** Hamma harf xatolari bitta javobda keladi:

```json
{"status_code": 422, "message": "Validation failed", "errors": {"file": [
  "3-qator: javob (C) mavjud bo'lmagan variantni ko'rsatgan.",
  "4-qator: javob (D) mavjud bo'lmagan variantni ko'rsatgan.",
  "5-qator: OPEN_ENDED savolda to'g'ri javob harfi bo'lmasligi kerak.",
  "6-qator: PYTHON_CODE savolda to'g'ri javob harfi bo'lmasligi kerak."
]}}
```

**`3_xatoli_qiymatlar.xlsx` → 422.** Har bir xato qator alohida keladi (`row` = Excel'dagi qator raqami):

| Qator | Xato |
|---|---|
| 2 | `text`: savol matni bo'sh |
| 3 | `default_points`: ball yozilmagan |
| 4 | `options`: SINGLE_CHOICE'da 2 ta to'g'ri javob |
| 5 | `options`: TRUE_FALSE'da 3 ta variant |
| 6 | `default_points`: 150, maksimum 100 |
| 7 | `options`: variantlar takrorlangan |
| 8 | `type`: noma'lum tur `ESSAY` |
| 9 | `options`: OPEN_ENDED savolga variant yozilgan |

**B2 va B4 ga ID yozilmasa → 422:**

```json
{"errors": {"course_id": ["Fayldagi Kurs ID topilmadi. Shablonni `import-template` orqali shu kurs uchun qayta yuklab oling."]}}
```

> Eslatma: javob harfi xatolari (`errors.file`) avval tekshiriladi. Faylda ikkala turdagi
> xato bo'lsa, avval harf xatolari ko'rsatiladi, ular tuzatilgandan keyin `errors.rows`
> xatolari chiqadi.

## 5. Boshqa xato holatlari

| Holat | Javob |
|---|---|
| `.xlsx` bo'lmagan fayl | 422 `file`: "Faqat .xlsx formatidagi fayl qabul qilinadi." |
| 5 MB dan katta fayl | 422 `file`: "XLSX fayl hajmi 5 MB dan oshmasligi kerak." |
| `Savollar` varag'i sarlavhalari o'zgartirilgan | 422 `file`: "ustun nomlari o'zgartirilgan" |
| 500 tadan ko'p savol | 422 `file`: "ko'pi bilan 500 ta savol" |
| Teacher shu kursga biriktirilmagan | 403 |
| Kurs arxivlangan yoki modul arxivlangan | 400 (biznes qoida xatosi) |
| Token yo'q yoki muddati o'tgan | 401 |
