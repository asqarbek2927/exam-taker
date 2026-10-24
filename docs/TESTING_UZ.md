# ExamTaker — qo‘lda sinab ko‘rish qo‘llanmasi

Bu qo‘llanma loyihani **o‘zingiz ishga tushirib, hamma qismini** (1–10-bosqich) tekshirib chiqishingiz uchun.

## 1. Ishga tushirish

### Variant A — Docker (eng oson)

```bash
# .env dagi SECRET_KEY ni almashtiring
docker compose up --build -d  # web + finalizer (SQLite umumiy volume’da)
docker compose exec web python manage.py seed_demo --allow-production
```

API: `http://localhost:8000/api/v1/` · Swagger: `http://localhost:8000/api/docs`

### Variant B — lokal

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
# .env dagi SECRET_KEY ni almashtiring
python manage.py migrate
python manage.py seed_demo          # DEBUG muhitda flagsiz ishlaydi
python manage.py runserver
```

## 2. Demo foydalanuvchilar

Parol hammasi uchun: **`Demo-Pass-123!`**

| Rol | Email | Holat |
|---|---|---|
| Super Admin | `admin@examtaker.local` | |
| Teacher | `teacher1@examtaker.local` | Python Foundation (MAIN), Django Backend (MAIN) — barcha savol/imtihon/e’lonlar muallifi |
| Teacher | `teacher2@examtaker.local` | Python Foundation (SUPPORT) |
| Student | `student1@examtaker.local` | G-101. Attempti **PENDING_GRADING** (teacher baholashi kerak) |
| Student | `student2@examtaker.local` | G-101. 2 urinish: 1-chi FAIL, 2-chi PASS (limit tugagan) |
| Student | `student3@examtaker.local` | G-101. Hali topshirmagan → **`start`** qilib ko‘ring |
| Student | `student4@examtaker.local`, `student5@…` | G-102. E’lon **PAUSED** (start bo‘lmaydi) |
| Student | `student6@examtaker.local` | Faqat Django kursida |

Seed 3 ta e’lon yaratadi: **ACTIVE** (G-101, 2 urinish), **SCHEDULED** (butun kurs, 2 kundan keyin),
**PAUSED** (G-102). ID lari buyruq oxirida chop etiladi.

## 3. Swagger (`/api/docs`) orqali

1. `POST /auth/login` → `access_token` ni nusxalang.
2. Sahifa tepasidagi **Authorize** → tokenni qo‘ying (faqat token, `Bearer` so‘zisiz).
3. Endi har qanday endpointni "Try it out" bilan chaqiring. Boshqa rolga o‘tish — qayta login + Authorize.

**Postman/Insomnia:** `docs/openapi.yml` ni import qiling (Bearer token — Authorization tabida).

## 4. Tekshiruv ssenariylari (bosqichlar bo‘yicha)

Qisqartirish uchun: `B=http://localhost:8000/api/v1`, `login` funksiyasi:

```bash
B=http://localhost:8000/api/v1
login() { curl -s -X POST $B/auth/login -H 'Content-Type: application/json' \
  -d "{\"email\":\"$1\",\"password\":\"Demo-Pass-123!\"}" | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])"; }
SH="Authorization: Bearer $(login student3@examtaker.local)"   # student
TH="Authorization: Bearer $(login teacher1@examtaker.local)"   # teacher
AH="Authorization: Bearer $(login admin@examtaker.local)"      # admin
```

### 1–2. Auth, Users, Academics (Super Admin)
```bash
curl -s $B/auth/me -H "$AH"
curl -s -X POST $B/users -H "$AH" -H 'Content-Type: application/json' \
  -d '{"full_name":"Yangi Student","email":"new@examtaker.local","password":"Str0ng-Pass!word1","role":"STUDENT"}'
curl -s "$B/courses" -H "$AH"                       # counts: teachers/students/groups/modules/questions/exams
curl -s "$B/students?search=sardor" -H "$AH"
```
Kutiladigan: Teacher `GET /users` → **403**; tokensiz → **401**; validation xatosi → **422** (`errors` bilan).

### 3. Student o‘z e’lonlarini ko‘radi
```bash
curl -s $B/exam-assignments -H "$SH"
```
`student3`: 2 ta e’lon — `ACTIVE` (`can_start: true`, 2 urinish) va `SCHEDULED` (butun kurs, `can_start: false`).
G-102 ning PAUSED e’loni va boshqa kurs e’lonlari ko‘rinmaydi.

### 4. Student imtihon topshiradi (6–7-bosqich)
```bash
AID=<ACTIVE e’lon ID>
ATT=$(curl -s -X POST $B/exam-assignments/$AID/start -H "$SH"); echo $ATT | python3 -m json.tool | head -60
```
Tekshiring: `questions[*].options` da **`is_correct` yo‘q**; `deadline_at` = hozir + 30 daqiqa; `id` lar — ExamQuestion ID lari.
```bash
ATID=<attempt id>; EQ=<birinchi savol id>; OPT=<option id>
curl -s -X PUT $B/attempts/$ATID/answers/$EQ -H "$SH" -H 'Content-Type: application/json' -d "{\"option_ids\":[\"$OPT\"]}"
curl -s $B/attempts/$ATID -H "$SH"                      # saqlangan javob qaytadi (sahifa yangilansa ham)
curl -s -X POST $B/exam-assignments/$AID/start -H "$SH"  # -> 409 (faol attempt bor)
curl -s -X POST $B/attempts/$ATID/submit -H "$SH"        # natija: PENDING_GRADING yoki GRADED
```
Open-ended savolga matn yozilsa → `PENDING_GRADING` (score `null`); yozilmasa → darhol `GRADED`.

### 5. Teacher qo‘lda baholaydi (8-bosqich)
```bash
curl -s $B/grading/pending -H "$TH"                      # student1 (va siz topshirgan) attemptlar
curl -s $B/attempts/<attempt_id> -H "$TH"                # javoblar + to‘g‘ri variantlar (staff ko‘radi)
curl -s -X PATCH $B/answers/<open_answer_id>/grade -H "$TH" -H 'Content-Type: application/json' \
  -d '{"points_awarded":4,"teacher_feedback":"Yaxshi"}'
```
Javobda `attempt.status: GRADED`, `score/percentage/passed`. Ball maksimumdan oshsa → **400**.

### 6. Natijalar (9-bosqich)
```bash
curl -s "$B/results" -H "$SH"                            # student — faqat o‘ziniki
curl -s "$B/results?latest_only=true" -H "$TH"           # har student/e’lon uchun oxirgi attempt
curl -s "$B/results?course_id=<id>&passed=true&date_from=2026-01-01" -H "$AH"
```
`student2`: 2 ta natija; `latest_only=true` da faqat 2-chisi (PASS), `is_latest: true`.

### 7. Dashboard (10-bosqich)
```bash
curl -s $B/admin/dashboard -H "$AH"
curl -s $B/teacher/dashboard -H "$TH"
curl -s $B/student/dashboard -H "$SH"
```
Har dashboard faqat o‘z roliga (boshqasida **403**). Qiymatlar ta’riflari — `README.md`.

### 8. Boshqa muhim holatlar
* **E’lon boshqaruvi (teacher):** `POST /exam-assignments/<id>/pause` → student `start` → **400** ("to‘xtatilgan"); `resume` → yana ishlaydi.
* **Yangi e’lon:** `POST /exam-assignments` (READY imtihon, `end_at` va `max_attempts` kalitlari majburiy — `null` ruxsat).
* **Edit-lock:** e’lon qilingan imtihonni `PATCH /exams/<id>` (`passing_score_percent`) → **409**.
* **Taymer:** qisqa test uchun e’lon yarating `duration_minutes: 1`, `start` qiling, 70+ soniya kuting va
  `PUT .../answers/...` ni chaqiring → **409** "Vaqt tugadi", attempt avtomatik yopiladi.
  Brauzer yopilgan holat uchun: `python manage.py finalize_expired_attempts` (docker da `finalizer` servisi o‘zi qiladi).
* **Xatolik formati:** hamma xato `{status_code, error, message}` (422 da `errors` bilan).

## 5. Avtomatik testlar

```bash
make test        # ~440 ta test
make lint
make schema      # OpenAPI validatsiyasi
```
Ishlayotgan PostgreSQL serveri bilan (parallel/race testlari ham ishlaydi):
```bash
DATABASE_URL=postgres://examtaker:examtaker@localhost:5432/examtaker \
  DJANGO_SETTINGS_MODULE=config.settings.test pytest --create-db
```
