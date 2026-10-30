# ExamTaker — Backend (Django + DRF)

IT Academy uchun onlayn imtihon platformasi backendi. Bu repozitoriya **TZ (DRF versiyasi)** ning
1–10 bosqichlarini (to‘liq imtihon aylanishi: yaratish → e’lon → topshirish → baholash → natija → dashboard) o‘z ichiga oladi:

| Phase | Qism | Holat |
|---|---|---|
| 0 | Setup: settings split, custom User, DRF, SimpleJWT, pagination, xatolik formati, CI, Docker | ✅ |
| 1 | **Auth** + Users + rollar/permission | ✅ |
| 2 | **Academics**: Course, CourseTeacher, Enrollment, **Module**, **StudyGroup + GroupStudent** | ✅ |
| 3 | **Question Bank**: Question + QuestionOption (4 tur), ownership, filterlar | ✅ |
| 4 | **Exam Library**: Exam, ExamModule, ExamQuestion, duplicate, edit-lock | ✅ |
| 5 | **ExamAssignment**: audience, vaqt, duration, attempt limiti, hisoblanadigan status, publish/pause/resume/complete/cancel/restore | ✅ |
| 6 | **Attempt**: boshlash (`start`), autosave, taymer, student DTO (to‘g‘ri javobsiz) | ✅ |
| 7 | **Submit + auto grading**: partial credit, muddati o‘tgan attemptni yopish (lazy + cron command) | ✅ |
| 8 | **Manual grading**: `/grading/pending`, `PATCH /answers/{id}/grade` | ✅ |
| 9 | **Results**: `/results` (filterlar, `latest_only`, `is_latest`) | ✅ |
| 10 | **Dashboard**: admin / teacher / student | ✅ |
| 11 | Production improvements (ExamSnapshot, AuditLog, cache, Celery/Redis) | ⏳ ixtiyoriy |

## Stack

Python 3.12 · Django 5.2 · DRF 3.16 · SimpleJWT (+ blacklist) · django-filter · drf-spectacular ·
drf-nested-routers · SQLite (sukut bo‘yicha, PostgreSQL ixtiyoriy) · Argon2 · gunicorn + WhiteNoise · pytest + factory_boy · ruff.
V1 da Celery / Redis / WebSocket **yo‘q**.

> **Sinab ko‘rish:** `python manage.py seed_demo` demo ma’lumot yaratadi; qadamma-qadam ssenariylar — [`docs/TESTING_UZ.md`](docs/TESTING_UZ.md); Postman uchun — `docs/openapi.yml`.

## Tez boshlash (lokal)

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
# .env dagi SECRET_KEY ni almashtiring
python manage.py migrate
python manage.py createsuperuser   # email, full_name, parol -> role=SUPER_ADMIN
python manage.py runserver
```

* API: `http://localhost:8000/api/v1/`
* Swagger UI: `http://localhost:8000/api/docs` (dev da yoqilgan)
* Django admin: `http://localhost:8000/admin/` (faqat Super Admin)

Hammasini Docker da ishga tushirish: `docker compose up --build` (lokal, http uchun
`SECURE_SSL_REDIRECT=false` compose da qo‘yilgan). Docker compose hozir SQLite'ni `sqlite_data`
volume'da saqlaydi. Lokal server PostgreSQL bilan ishlashi uchun `.env`da masalan
`DATABASE_URL=postgres://<user>:<password>@localhost:5432/<database>` yozing va
`python manage.py migrate` buyrug‘ini bajaring.

## Struktura

```text
config/            settings (base/dev/prod/test), urls
common/            UUIDModel, pagination, exception handler, role permissions, login throttling
apps/users/        User, auth endpointlar, users/teachers/students
apps/academics/    Course, CourseTeacher, Enrollment, Module, StudyGroup, GroupStudent
apps/questions/    Question, QuestionOption (+ turlar bo‘yicha validatsiya)
apps/exams/        Exam, ExamModule, ExamQuestion
apps/assignments/  ExamAssignment (+ audience), status hisoblash, eligibility
apps/attempts/     ExamAttempt, StudentAnswer, auto/manual grading, finalize_expired_attempts command
apps/reports/      Results, Dashboard (modelsiz, faqat selectors), seed_demo command
```

Har app ichida: `models` · `serializers` · `views` (yupqa) · `services` (yozish, `transaction.atomic`) ·
`selectors` (o‘qish) · `filters` · `urls` · `tests`.

## API (qisqacha)

Base: `/api/v1`. Barcha ro‘yxatlar: `?page=1&limit=20`, javob `{"data": [...], "pagination": {...}}`.

| Endpoint | Kim |
|---|---|
| `POST /auth/login` · `POST /auth/refresh` · `POST /auth/logout` · `GET /auth/me` | hamma |
| `GET/POST /users`, `GET/PATCH /users/{id}` | Super Admin |
| `POST /users/{id}/activate` · `deactivate` · `set-password` | Super Admin |
| `GET /teachers`, `GET /students` (+`/{id}`) | Super Admin |
| `GET /courses`, `GET /courses/{id}` | rolga qarab scoped (admin: hammasi, teacher: biriktirilgan, student: yozilgan) |
| `POST /courses`, `PATCH /courses/{id}`, `POST /courses/{id}/archive` | Super Admin |
| `GET /courses/{id}/teachers` | Super Admin, kursga biriktirilgan teacher |
| `POST/PATCH/DELETE /courses/{id}/teachers[/{id}]` | Super Admin |
| `GET /courses/{id}/students` | Super Admin, kursga biriktirilgan teacher |
| `POST/PATCH/DELETE /courses/{id}/students[/{id}]` | Super Admin |
| `GET /courses/{id}/modules[/{id}]` | Super Admin, kursga biriktirilgan teacher, kursga yozilgan student |
| `POST/PATCH/DELETE /courses/{id}/modules[/{id}]` | Super Admin, kursga biriktirilgan teacher |
| `GET /courses/{id}/groups[/{id}]`, `GET .../groups/{id}/students` | Super Admin, kursga biriktirilgan teacher |
| `POST/PATCH/DELETE /courses/{id}/groups[/{id}]` | Super Admin |
| `POST /courses/{id}/groups/{id}/students`, `DELETE .../students/{student_id}` | Super Admin |
| `GET/POST /questions`, `GET/PATCH/DELETE /questions/{id}`, `POST /questions/{id}/archive` | Super Admin, Teacher (o‘zgartirish — faqat muallif / Super Admin) |
| `GET/POST /exams`, `GET/PATCH/DELETE /exams/{id}`, `POST /exams/{id}/archive`, `POST /exams/{id}/duplicate` | Super Admin, Teacher (o‘zgartirish — faqat muallif / Super Admin; `duplicate` — hamma teacher) |
| `GET/POST /exam-assignments`, `GET/PATCH /exam-assignments/{id}` | Super Admin, Teacher (yozish — faqat e’lon muallifi / Super Admin); Student — faqat o‘qish, o‘ziga eligible larini |
| `POST /exam-assignments/{id}/publish\|pause\|resume\|complete\|cancel\|restore` | e’lon muallifi, Super Admin |
| `POST /exam-assignments/{id}/start` | Student (eligible bo‘lsa) |
| `GET /attempts`, `GET /attempts/{id}` | rolga qarab scoped (Student — o‘ziniki) |
| `PUT /attempts/{id}/answers/{exam_question_id}`, `POST /attempts/{id}/submit` | Student (attempt egasi) |
| `GET /grading/pending`, `PATCH /answers/{id}/grade` | Super Admin, kursga biriktirilgan teacher |
| `GET /results` | rolga qarab scoped (Student — o‘ziniki) |
| `GET /admin/dashboard`, `/teacher/dashboard`, `/student/dashboard` | mos ravishda Super Admin, Teacher, Student |

To‘liq sxema: `/api/docs` (Swagger) yoki `/api/schema` (OpenAPI).

### Auth oqimi

```bash
# login
curl -X POST localhost:8000/api/v1/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"boss@example.com","password":"..."}'
# -> {"user": {...}, "access_token": "...", "refresh_token": "..."}

# himoyalangan endpoint
curl localhost:8000/api/v1/auth/me -H 'Authorization: Bearer <access_token>'

# access tugaganda (refresh rotatsiya qilinadi, eskisi blacklist ga tushadi)
curl -X POST localhost:8000/api/v1/auth/refresh -H 'Content-Type: application/json' \
  -d '{"refresh_token":"<refresh_token>"}'

# logout (refresh tokenni bekor qiladi)
curl -X POST localhost:8000/api/v1/auth/logout -H 'Authorization: Bearer <access_token>' \
  -H 'Content-Type: application/json' -d '{"refresh_token":"<refresh_token>"}'
```

### Xatolik formati

```json
{"status_code": 400, "error": "Bad Request", "message": "..."}
```

Validation xatosi — **422**:

```json
{"status_code": 422, "message": "Validation failed", "errors": {"email": ["..."]}}
```

`401` autentifikatsiya yo‘q/yaroqsiz · `403` rol ruxsat bermaydi · `404` topilmadi **yoki sizga ko‘rinmaydi** ·
`409` to‘qnashuv (masalan, teacher allaqachon biriktirilgan) · `429` throttling.

## Qabul qilingan qarorlar

* **Rol token ichidan emas, DB dagi userdan o‘qiladi** — rol/holat o‘zgarsa eski token huquq bermaydi.
* `User.status` — yagona haqiqat manbai; `is_active` shundan hisoblanadi. Nofaol qilinganda (`deactivate`)
  yoki parol almashtirilganda userning barcha refresh tokenlari blacklist qilinadi.
* **Himoya 2 qatlamli:** `get_queryset()` scoping (ko‘rinmasa 404) + permission class (403).
* **Login throttling** (IP + email) bo‘yicha: bir NAT IP dan ko‘p student kirsa bir-birini bloklamaydi.
  Cache — `DatabaseCache` (prod, Redis yo‘q; `createcachetable` entrypoint da). Nginx orqasida `NUM_PROXIES=1`.
* Kurs `ARCHIVED` bo‘lsa unga teacher/student biriktirib bo‘lmaydi, tahrirlab bo‘lmaydi.
* Enrollment o‘chirilmaydi: `DELETE` → `REMOVED` (idempotent); qayta yozilsa mavjud yozuv `ACTIVE` ga qaytadi.
  `GET /courses/{id}/students` da `status` berilmasa `REMOVED` lar ko‘rsatilmaydi.
* SUPER_ADMIN API orqali yaratilmaydi — faqat `createsuperuser`.
* **Delete yoki archive:** `DELETE` modul/savol/imtihonga — ishlatilmagan bo‘lsa o‘chiradi (`204`),
  tarixi bo‘lsa `ARCHIVED` ga o‘tkazadi (`200 {"archived": true}`). DB da tarixiy FK lar `PROTECT`.
  Ro‘yxatlarda `status` berilmasa arxivlanganlar ko‘rsatilmaydi.
* **Modul** — kurs ichida shared: kursga biriktirilgan har qanday teacher tahrirlaydi. `?with_questions=true`
  har modul uchun 5 tagacha savol preview qaytaradi (studentga berilmaydi).
* **Guruh a’zoligi:** student guruhga faqat kursga `ACTIVE` yozilgan bo‘lsa qo‘shiladi; kursdan chiqarilsa
  (`REMOVED`) shu kursdagi guruhlardan ham chiqariladi.
* **Savol turlari:** SINGLE (aynan 1 to‘g‘ri, ≥2 option) · MULTIPLE (≥1 to‘g‘ri, ≥2 option) ·
  TRUE_FALSE (aynan 2 option, 1 to‘g‘ri) · OPEN_ENDED (optionsiz). `default_points` berilmasa 2/3/1/5.
  `type` o‘zgarsa `options` ham yuboriladi; `options` yuborilsa to‘liq almashtiriladi.
* **Ownership:** savolni faqat muallifi (yoki Super Admin) o‘zgartiradi. **Imtihon uchun ham xuddi shunday**
  (TZ da aniq yozilmagan — xavfsiz tomonga qaror qilindi); boshqa teacher imtihonni ko‘radi va `duplicate` qila oladi.
* **Exam:** `Exam.course == Module.course == Question.course`, savol modullari tanlangan modullar ichida,
  yangi qo‘shiladigan modul/savol `ACTIVE` bo‘lishi shart. `PATCH` da `module_ids`/`questions` to‘plamni
  almashtiradi, lekin mavjud `ExamQuestion` ID lari saqlanadi (attemptlar ularga bog‘lanadi).
  `READY` uchun kamida 1 ta savol kerak. Student DTO da `id` = `ExamQuestion.id`.
* **Edit-lock (hook):** `exams/selectors.py::exam_has_assignments()` hozircha `False` qaytaradi, chunki
  ExamAssignment 5-bosqichda qo‘shiladi. O‘shanda bitta funksiya almashtiriladi va e’lon qilingan imtihon
  kontenti hamda ishlatilgan savollar avtomatik `409` bilan bloklanadi (testlar hook ni tekshiradi).
* Ball va foizlar JSON da son sifatida qaytadi (`COERCE_DECIMAL_TO_STRING=False`).

### ExamAssignment (5-bosqich)
* **Status hisoblanadi, saqlanmaydi:** DB da `DRAFT/PUBLISHED/PAUSED/COMPLETED/CANCELLED`; API da `status` =
  `DRAFT/SCHEDULED/ACTIVE/PAUSED/COMPLETED/CANCELLED` (`PUBLISHED` + vaqtga qarab). Scheduler (Celery) kerak emas.
  `?status=ACTIVE` filtri ham shu hisob bo‘yicha ishlaydi. `stored_status` ham qaytadi.
* **Audience:** `ALL_COURSE_STUDENTS` / `GROUPS` / `SPECIFIC_STUDENTS`. Eligible = audience ∩ kursga `ACTIVE` yozilgan
  ∩ `ACTIVE` foydalanuvchi. Bitta joyda: `assignments/selectors.py::eligible_students`.
* `end_at: null` — deadline yo‘q, `max_attempts: null` — cheksiz (ikkala kalit ham aniq yuboriladi).
  Faqat `READY` va savolli imtihon e’lon qilinadi; `is_draft: true` — qoralama.
* **Attempt boshlangach** faqat `end_at` ni uzaytirish mumkin (qolgani `409`).
* **Edit-lock ishlaydi:** DRAFT bo‘lmagan assignment yoki attempt bor imtihon (va uning savollari) kontenti `409`;
  DRAFT assignment bloklamaydi. Assignmentda ishlatilgan guruhni o‘chirib bo‘lmaydi (`409`).
* Assignmentni o‘zgartirish/status amallari — e’lon muallifi yoki Super Admin (imtihon/savol qoidasi bilan bir xil).
* Student `COMPLETED` e’lonlarni ham ko‘radi (natijalar uchun); `DRAFT`/`CANCELLED` yashirin.

### Attempt (6–7-bosqich)
* `start`: assignment qatori `select_for_update` bilan qulflanadi; limit va "bitta faol attempt" qoidasi DB
  constraint (`uniq_active_attempt`) bilan ham himoyalangan. PostgreSQL da parallel start testlari bor.
* `deadline_at = min(started_at + duration, end_at)` — boshlanganda saqlanadi. Server vaqti yagona manba.
* **Student DTO** da `is_correct` yo‘q; savol `id` si = `ExamQuestion.id` (autosave shu ID bilan).
  Yakunlangan attemptda student faqat natijani ko‘radi (to‘g‘ri javoblarsiz) — TZ 19-bo‘lim 4-savol default.
* **Autosave** (`PUT .../answers/{exam_question_id}`): tanlovli savol — `option_ids` (bo‘sh ro‘yxat = tozalash),
  OPEN_ENDED — `text_answer`. `deadline + ATTEMPT_GRACE_SECONDS` (10 s) dan keyin `409` va attempt yopiladi.
* **Auto grading:** SINGLE/TRUE_FALSE — hammasi yoki hech narsa; MULTIPLE — partial:
  `ball = points × clamp((to‘g‘ri − noto‘g‘ri) / jami to‘g‘ri, 0, 1)`; OPEN_ENDED — matn bo‘lsa
  `PENDING_GRADING` (qo‘lda baholash 8-bosqichda), matn bo‘sh bo‘lsa 0 ball. `passed` yaxlitlashsiz,
  aniq taqqoslanadi (`score·100 ≥ passing·total`).
* **Muddati o‘tgan attemptlar** (brauzer yopilgan bo‘lsa ham) Celery siz yopiladi: (1) lazy — `start`,
  autosave, submit, `GET /attempts[/{id}]` va student assignmentlar ro‘yxatida; (2) cron —
  `python manage.py finalize_expired_attempts` (`docker-compose` da `finalizer` servisi har 60 s ishga tushiradi).
  Yopilgan attemptda `submitted_at = deadline_at`.

### Manual grading, Results, Dashboard (8–10-bosqich)
* **Qo‘lda baholash:** faqat `OPEN_ENDED` javob; `0 ≤ ball ≤ ExamQuestion.points` (aks holda `400`); faol (IN_PROGRESS)
  attemptni baholab bo‘lmaydi (`409`). Kursga biriktirilgan **har qanday** teacher baholay oladi (e’lon muallifi shart emas).
  Hamma baholanmagan javob baholangach attempt `GRADED` bo‘ladi; baholangan javobni qayta baholash natijani qayta hisoblaydi.
  `teacher_feedback` yuborilmasa avvalgisi saqlanadi. `/grading/pending` — eng eski topshirilgani birinchi.
* **Results:** faqat yakunlangan attemptlar (`SUBMITTED/PENDING_GRADING/GRADED`). `latest_only=true` — har
  (assignment, student) uchun eng katta `attempt_number`; `is_latest` har qatorda. `PENDING_GRADING` da natija `null`.
  `teacher_id` filtri — e’lonni chiqargan teacher; `date_from/date_to` — topshirilgan sana (Asia/Tashkent).
* **Dashboard ta’riflari** (statistika saqlanmaydi, har so‘rovda hisoblanadi):
  * `total_*` / `my_courses` — faqat faol (`ACTIVE`, arxivlanmagan) obyektlar; `total_students/teachers` — faqat faol userlar.
  * `active_assignments` / `completed_assignments` — **hisoblangan** status bo‘yicha (vaqtga qarab ham).
  * `average_score` — har (assignment, student) uchun **oxirgi baholangan** attempt foizlarining o‘rtachasi;
    `pass_rate` — shulardan o‘tganlar ulushi (%). Ma’lumot bo‘lmasa `null`.
  * Teacher: `my_questions/my_exams` — o‘zi yaratgani; `active_assignments` — o‘zi e’lon qilgani;
    `pending_grading` va `average_student_score` — **kurs bo‘yicha** (hamkasbining e’lonlari ham); `my_students` — takrorlanmaydi.
  * Student: `available_exams` — hozir ACTIVE va (urinish qolgan **yoki** davom ettiriladigan attempt bor);
    `completed_exams` — kamida 1 ta yakunlangan attemptli e’lonlar; `passed_exams` — oxirgi baholangan attempt o‘tgan e’lonlar.

## Test va sifat

```bash
make test        # pytest; .env dagi DATABASE_URL ishlatiladi
make lint        # ruff check + format --check
make schema      # OpenAPI sxemani validatsiya qilish (--fail-on-warn)

# Ishlayotgan PostgreSQL serveri bilan (CI dagidek):
DATABASE_URL=postgres://<user>:<password>@localhost:5432/<database> \
  DJANGO_SETTINGS_MODULE=config.settings.test pytest --create-db
```

535 ta test: auth, users, permission matritsasi, queryset scoping,
academics, savol validatsiyasi, imtihon CRUD, edit-lock, assignment (status/transition/audience/eligibility),
attempt (start/autosave/submit/grading/expiry/leakage), DB constraintlar, race condition, OpenAPI.

## Production eslatmalari

Frontendga topshirish holati va AWS EC2 HTTP deploy qadamlari:
[`docs/FRONTEND_AND_AWS_HANDOFF_UZ.md`](docs/FRONTEND_AND_AWS_HANDOFF_UZ.md).
Faqat hozir ishlaydigan endpointlarning frontend ro‘yxati:
[`docs/FRONTEND_READY_APIS_UZ.md`](docs/FRONTEND_READY_APIS_UZ.md).

AWS uchun alohida compose konfiguratsiyasi PostgreSQL, Nginx port 80 va persistent media bilan:

```bash
cp .env.aws.example .env.aws
docker compose --env-file .env.aws -f docker-compose.aws.yml up -d --build
```

* `DJANGO_SETTINGS_MODULE=config.settings.prod`, `SECRET_KEY`, `ALLOWED_HOSTS`,
  `CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS` ni env orqali bering (`.env` ga qarang).
  Ko‘p foydalanuvchi va parallel yozuvlar uchun PostgreSQL tanlang va `DATABASE_URL` ni sozlang.
* HTTPS nginx da tugatiladi; `X-Forwarded-Proto` uzating. `SECURE_HSTS_SECONDS` ni HTTPS ishlagach yoqing.
* Eskirgan blacklist yozuvlarini vaqti-vaqti bilan tozalang (cron):
  `python manage.py flushexpiredtokens`
* Bir nechta replica bo‘lsa migratsiyani alohida job qiling va konteynerda `RUN_MIGRATIONS=0` qo‘ying.
* `/api/docs` prod da sukut bo‘yicha o‘chiq (`ENABLE_API_DOCS=true` bilan yoqiladi).
