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
  -d "{\"emailOrUsername\":\"$1\",\"password\":\"Demo-Pass-123!\"}" | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])"; }
SH="Authorization: Bearer $(login student3@examtaker.local)"   # student
TH="Authorization: Bearer $(login teacher1@examtaker.local)"   # teacher
AH="Authorization: Bearer $(login admin@examtaker.local)"      # admin
```

### 1–2. Auth, Users, Academics (Super Admin)
```bash
curl -s $B/auth/me -H "$AH"
curl -s "$B/admin/accounts?role=SUPPORT_TEACHER" -H "$AH"
curl -s "$B/courses" -H "$AH"                       # counts: teachers/students/groups/modules/questions/exams
curl -s "$B/students?search=sardor" -H "$AH"
```
Kutiladigan: Teacher `GET /admin/accounts` → **403**; tokensiz → **401**; validation xatosi → **422** (`errors` bilan).

Avatar barcha rollar uchun bir xil endpoint orqali multipart yuboriladi:

```bash
curl -s -X POST $B/profile/photo -H "$SH" -F "image=@avatar.png"
curl -s $B/profile -H "$SH"                         # avatar_url saqlangan URL
```

Canonical multipart kaliti `image`; eski frontend yuboradigan `avatar` kaliti ham qabul qilinadi.
AWS deployda Nginx 12 MBgacha requestni Django’ga uzatadi; backend avatar faylini 5 MB bilan
cheklaydi va undan kattasiga JSON `422` qaytaradi.

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

### 9. TZ Admin Accounts (#10–19)

Account yaratish — admin parol yubormaydi; server temporary password beradi:

```bash
ACC=$(curl -s -X POST $B/admin/accounts -H "$AH" -H 'Content-Type: application/json' \
  -d '{"full_name":"Madina Karimova","email":"madina@example.com","role":"STUDENT","avatar_url":"https://cdn.example.com/madina.png","phone_number":"+998901234567","location":"Tashkent"}')
echo "$ACC" | python3 -m json.tool
```

Tekshiring:

- response `account`, top-level `temporary_password` va `temporary_password_expires_at`dan iborat;
- `temporary_password` faqat shu create/reset javobida bir marta chiqadi;
- `account.must_change_password=true`, `version=1`;
- `password`, `course_ids`, `group_ids` yuborilsa `422`.
- optional `avatar_url` public HTTP(S) rasmni backendga yuklatadi; local/private URL, noto‘g‘ri
  format yoki 5 MB dan katta rasm `422` qaytaradi.

Keyingi amallar (`ID` va `VERSION`ni response’dan oling):

```bash
ID=<account id>; VERSION=1
curl -s $B/admin/accounts/$ID -H "$AH"
curl -s -X PATCH $B/admin/accounts/$ID -H "$AH" -H 'Content-Type: application/json' \
  -d "{\"full_name\":\"Madina K.\",\"email\":\"madina.new@example.com\",\"location\":\"Samarkand\",\"version\":$VERSION}"
curl -s -X PUT $B/admin/accounts/$ID -H "$AH" \
  -F "avatar=@avatar.png" -F "version=2"
curl -s -X DELETE "$B/admin/accounts/$ID/photo?version=3" -H "$AH"
curl -s -X PUT $B/admin/accounts/$ID/status -H "$AH" -H 'Content-Type: application/json' \
  -d '{"status":"INACTIVE","version":4}'
curl -s -X POST $B/admin/accounts/$ID/temporary-password -H "$AH"
curl -s $B/admin/accounts/$ID/courses -H "$AH"
curl -s $B/admin/accounts/$ID/activity -H "$AH"
```

Student account uchun `/admin/accounts/$ID/courses` har bir kursda `teacher_name` va
`progress` qaytaradi. Progress formulasi/modeli hali belgilanmagani uchun `progress: null`.
`teacher_name` MAIN teacher’dan, u bo‘lmasa birinchi SUPPORT teacher’dan olinadi; kursga umuman
teacher biriktirilmagan bo‘lsa `null`.

Teacher sahifasi faqat admin accounts API orqali:

```bash
curl -s "$B/admin/accounts?role=TEACHER&course_id=<course-uuid>&ordering=-students_count&page=1&limit=20" -H "$AH"
curl -s "$B/admin/accounts/summary?role=TEACHER" -H "$AH"
curl -s "$B/admin/accounts/summary?role=SUPPORT_TEACHER" -H "$AH"
```

List teacher elementida `assigned_courses`, `courses_count`, distinct `students_count` va
`exams_count` bor. Summary paginationdan mustaqil hisoblanadi. Eski `/teachers` endpointlari
Super-admin Teacher sahifasida ishlatilmaydi.

Teacher course assignmentini transactionally almashtirish:

```bash
TID=<teacher account id>; TVERSION=<current version>
curl -s -X PUT $B/admin/accounts/$TID/teaching-courses -H "$AH" \
  -H 'Content-Type: application/json' \
  -d "{\"course_ids\":[\"<course id>\"],\"main_course_ids\":[\"<course id>\"],\"version\":$TVERSION}"
```

`SUPPORT_TEACHER` uchun `main_course_ids` bo‘sh bo‘lishi shart. Eski `version` yuborilsa
`409 VERSION_CONFLICT`. Soft delete:

```bash
curl -s -X DELETE $B/admin/accounts/$ID -H "$AH" -H 'Content-Type: application/json' \
  -d '{"version":<current version>}'
```

Delete hard-delete emas: status `DELETED`, tarixiy attempt/result saqlanadi, login va refresh bloklanadi.
Faol guruhning MAIN teacheri avval boshqa teacherga o‘tkazilmasa delete `409` qaytaradi.

### 10. TZ Courses, Modules va Enrollments (#20–33)

```bash
CID=<course id>; SID=<student id>; MID=<module id>
curl -s "$B/courses?q=python&status=ACTIVE&teacherId=<teacher id>" -H "$AH"
curl -s -X PUT $B/courses/$CID/status -H "$AH" -H 'Content-Type: application/json' \
  -d '{"status":"ACTIVE","version":1}'
curl -s -X PUT $B/courses/$CID/modules/$MID/status -H "$TH" \
  -H 'Content-Type: application/json' -d '{"status":"ARCHIVED"}'
curl -s -X PUT $B/courses/$CID/modules/order -H "$TH" \
  -H 'Content-Type: application/json' -d '{"moduleIds":["<module-1>","<module-2>"]}'
curl -s -X POST $B/courses/$CID/enrollments -H "$AH" \
  -H 'Content-Type: application/json' -d "{\"studentId\":\"$SID\"}"
curl -s -X DELETE $B/courses/$CID/enrollments/$SID -H "$AH"
curl -s $B/students/me/courses -H "$SH"
```

`moduleIds` kursdagi barcha modullarning takrorlanmagan aniq to‘plami bo‘lishi kerak. Enrollment
faqat `ACTIVE` kurs va faol student uchun; takroriy POST bir xil representation qaytaradi. Eski
`/courses/{id}/students` endpointlari backward compatibility uchun ishlashda davom etadi.

### 11. TZ Groups (#34–41)

```bash
GID=<group id>; SID=<student id>; GVERSION=1
curl -s "$B/groups?courseId=$CID&status=ACTIVE&q=backend" -H "$AH"
curl -s -X POST $B/groups -H "$AH" -H 'Content-Type: application/json' \
  -d "{\"name\":\"Backend A\",\"courseId\":\"$CID\",\"status\":\"ACTIVE\"}"
curl -s -X PATCH $B/groups/$GID -H "$AH" -H 'Content-Type: application/json' \
  -d "{\"name\":\"Backend B\",\"version\":$GVERSION}"
curl -s -X PUT $B/groups/$GID/status -H "$AH" -H 'Content-Type: application/json' \
  -d '{"status":"ARCHIVED","version":2}'
curl -s "$B/groups/$GID/eligible-students?q=madina" -H "$AH"
curl -s -X POST $B/groups/$GID/students -H "$AH" -H 'Content-Type: application/json' \
  -d "{\"studentId\":\"$SID\"}"
curl -s -X DELETE $B/groups/$GID/students/$SID -H "$AH"
```

Student guruhga qo‘shilishidan oldin shu kursga `ACTIVE` enrollmentga ega bo‘lishi kerak. Group va
course ham `ACTIVE` bo‘ladi. Bir student bir kursda faqat bitta `ACTIVE` guruhda bo‘lishi mumkin;
archive qilingan guruhni restore qilishda ham shu qoida tekshiriladi. Eski course-nested group
endpointlari backward compatibility uchun saqlangan.

## 5. Avtomatik testlar

```bash
make test        # PostgreSQL: 566 passed
make lint
make schema      # OpenAPI validatsiyasi
```
Ishlayotgan PostgreSQL serveri bilan (parallel/race testlari ham ishlaydi):
```bash
DATABASE_URL=postgres://<user>:<password>@localhost:5432/<database> \
  DJANGO_SETTINGS_MODULE=config.settings.test pytest --create-db
```
