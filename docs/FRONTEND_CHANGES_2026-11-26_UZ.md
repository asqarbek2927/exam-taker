# Backend o'zgarishlari — frontend uchun (2026-11-26)

Production (`exam-taker.uz`) ga 2026-11-26 da deploy qilindi.

**Qisqasi:** hech bir endpoint, maydon yoki status kodi olib tashlanmagan yoki nomi
o'zgarmagan. Faqat **qo'shimchalar** va xatolarni to'g'rilash. Hozirgi front kodi ishlashda
davom etadi. Pastdagi 1-bo'lim (refresh) va 4-bo'lim (XLSX xatolari) — frontda o'zgartirish
tavsiya etiladigan joylar.

| # | Nima | Frontda kerakmi? |
|---|---|---|
| 1 | Imtihon o'rtasida 30 daqiqada logout bo'lib qolish tuzatildi | **Ha, tavsiya** — refreshni "single-flight" qiling |
| 2 | `GET /questions/summary` ga `python_code` qo'shildi | Ixtiyoriy |
| 3 | PYTHON_CODE to'liq tayyor (handoff bo'yicha) | Yo'q — tekshirish |
| 4 | XLSX import: bir nechta xato birdaniga keladi | **Ha** — `errors.file` ro'yxatini to'liq ko'rsating |
| 5 | `revision` juda katta bo'lsa 500 o'rniga 422 | Yo'q |
| 6 | Fokus chegarasi serverda sozlanadigan bo'ldi | **Ha, tavsiya** — `threshold` ni javobdan oling |

---

## 1. Refresh token — imtihon o'rtasida logout (MUHIM)

**Muammo edi:** access token 30 daqiqa yashaydi. Tugaganda bir nechta parallel so'rov
(autosave, events, attempt detail) bir vaqtda `401` oladi va har biri **bir xil** refresh
token bilan `POST /api/v1/auth/refresh` yuboradi. Rotation sababli birinchisidan keyin eski
token bekor bo'lardi, qolganlari `401` olardi → front studentni login sahifasiga yuborardi.

**Backend endi:**

- Bir xil refresh token **60 soniya ichida** qayta kelsa, `401` o'rniga **aynan o'sha**
  `access_token` + `refresh_token` juftligi qaytadi (yangi session yaratilmaydi). Qaysi
  javobni oxirida saqlasangiz ham to'g'ri bo'ladi.
- Refresh limiti endi **user bo'yicha** (30/min) + keng IP limiti (1000/min). Oldin butun
  sinf (bitta NAT IP) uchun umumiy 120/min edi.
- 60 soniyadan keyin eski token → `401` (oldingidek). Logout va parol almashtirish bilan
  bekor qilingan tokenlarga grace berilmaydi.
- Request/response o'zgarmadi: `{"refresh_token": "..."}` → `{"access_token": "...", "refresh_token": "..."}`.

**Frontda tavsiya (to'g'ri yechim):** bir vaqtda faqat **bitta** refresh so'rovi bo'lsin,
qolgan `401` olgan so'rovlar shu natijani kutib, qayta yuborilsin:

```ts
let refreshing: Promise<string> | null = null;

async function getFreshAccessToken(): Promise<string> {
  if (!refreshing) {
    refreshing = api
      .post("/auth/refresh", { refresh_token: storage.refreshToken })
      .then(({ data }) => {
        storage.accessToken = data.access_token;
        storage.refreshToken = data.refresh_token;
        return data.access_token;
      })
      .finally(() => { refreshing = null; });
  }
  return refreshing;
}

// interceptor: 401 bo'lsa -> await getFreshAccessToken() -> so'rovni 1 marta qayta yuborish.
// Refresh o'zi 401 qaytarsagina logout qiling. 429 bo'lsa logout QILMANG — kutib qayta urining.
```

Muhim: refresh `429` (So'rovlar soni oshib ketdi) qaytarsa — bu logout sababi emas.

## 2. `GET /api/v1/questions/summary` — yangi maydon

```json
{"active_questions": 10, "choice_questions": 6, "open_ended": 2, "python_code": 2, "archived": 1}
```

`python_code` — faol PYTHON_CODE savollar soni. `open_ended` ma'nosi o'zgarmadi (faqat
OPEN_ENDED). Question bank kartalarida ko'rsatish mumkin.

## 3. PYTHON_CODE — handoff bo'yicha holat

Frontend bergan "Python code question: backend handoff" hujjatidagi hamma band bajarilgan va
API orqali avtomatik test bilan tekshirilgan (savol yaratish → imtihonga qo'shish → e'lon →
start → saqlash → reload → submit → baholash → review rejimlari).

Bitta nuance — **`revision`** (barcha savol turlari uchun bir xil, o'zgartirilmadi):

| So'rov | Javobdagi `revision` |
|---|---|
| Birinchi saqlash `"revision": 0` | `0` |
| Keyingi saqlash — oxirgi javobdagi `revision` ni yuboring, matn boshqa | server `+1` qiladi |
| Xuddi o'sha matn qayta yuborilsa | o'zgarmaydi |
| Joriydan kichik `revision` | `409` (eskirgan yozuv) |

Ya'ni har doim **oxirgi javobdagi `revision`** ni yuborish kifoya — konflikt bo'lmaydi.

## 4. XLSX import (`POST /api/v1/questions/import`) — xatolar

`errors.file` — **ro'yxat**, endi unda **bir nechta** xabar bo'lishi mumkin (oldin bitta
edi). Ro'yxatning **hammasini** ko'rsating, aks holda ustoz faylni qayta-qayta yuklaydi:

```json
{"status_code": 422, "message": "Validation failed", "errors": {"file": [
  "3-qator: javob (C) mavjud bo'lmagan variantni ko'rsatgan.",
  "5-qator: OPEN_ENDED savolda to'g'ri javob harfi bo'lmasligi kerak."
]}}
```

`errors.rows` formati o'zgarmadi: `[{"row": "4", "errors": {"options": ["..."]}}, ...]`.

Boshqa o'zgarishlar (front kodi o'zgarmaydi):

- Avval rad etilgan to'g'ri fayllar endi qabul qilinadi: pastgacha formatlangan bo'sh
  qatorlar, Google Sheets/boshqa dasturlarda saqlangan fayllar, kirillcha `А/В/С/Е` javob
  harflari, `a, c` / `AC`, `single choice`, ball `2,5`.
- Kurs/modul ID topilmasa — xabar matni tushunarliroq (kalitlar o'sha: `course_id` / `module_id`).
- Shablonda PYTHON_CODE misoli va turlar ro'yxati qo'shildi.
- Tartib: avval `errors.file` (harf xatolari), ular tuzatilgach `errors.rows` chiqadi.

Test uchun tayyor fayllar va qo'llanma: `docs/xlsx_test/README_UZ.md`.

## 5. Autosave — juda katta `revision`

`PUT /api/v1/attempts/{id}/answers/{examQuestionId}` da `revision > 2147483646` bo'lsa endi
`422` (`errors.revision`) qaytadi (oldin `500`). Oddiy ishlashda bunga duch kelinmaydi.

## 6. Fokus nazorati — `threshold`

`POST /api/v1/attempts/{id}/events` javobidagi `threshold` endi serverda sozlanadi (hozir `3`,
o'zgarmagan). Frontda `3` ni qattiq yozib qo'ymang — ogohlantirishda (`2/3` kabi) javobdagi
`threshold` dan foydalaning.

---

## Front uchun tekshirish ro'yxati

- [ ] Imtihonni 30+ daqiqa davom ettirish (yoki `JWT_ACCESS_MINUTES=1` bo'lgan test serverda
      2–3 daqiqa) — student chiqib ketmaydi; Network'da refresh `200` lar.
- [ ] PYTHON_CODE: yaratish, imtihonda kod yozish, reload, submit, teacher baholashi, natija.
- [ ] XLSX: `docs/xlsx_test/2_xatoli_javob_harflari.xlsx` — 4 ta xato birdaniga ko'rinadi.
- [ ] Question bank kartalari — `python_code` (agar qo'shilsa).
