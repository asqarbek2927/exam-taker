# ExamTaker: frontend handoff va AWS HTTP deploy

Yangilangan sana: 2026-10-29

Bu hujjat frontend integratsiyasi uchun backendning real holatini ko‘rsatadi. Original
`backend-api-tz.md` maqsad kontrakti bo‘lib qoladi, lekin hozirgi backendning URL va JSON
shakllari ayrim joylarda undan farq qiladi. Frontend integratsiyasida ishlayotgan serverdagi
`/api/docs` va `/api/schema` asosiy texnik manba sifatida ishlatilishi kerak.

## 1. Hozirgi API konvensiyasi

- Base URL: `http://<server>/api/v1`.
- Auth: `Authorization: Bearer <access_token>`.
- JSON maydonlari asosan `snake_case`. TZ dagi hamma `camelCase` maydonlar hali global
  konvertatsiya qilinmagan.
- List javobi: `{"data": [...], "pagination": {...}}`. TZ dagi
  `{items,page,pageSize,total,hasNext}` hali aynan qo‘llanmagan.
- Validation xatosi: `422` va `{"status_code":422,"message":"Validation failed","errors":{...}}`.
- Boshqa xatolar: `{"status_code":...,"error":"...","message":"..."}`. TZ dagi barcha
  stable error `code`, `details` va `requestId` hali yo‘q.
- Sana-vaqtlar ISO 8601 ko‘rinishida, lekin response doimo UTC `Z` bo‘lishi kafolatlanmagan.
- API trailing slashsiz ishlaydi: `/api/v1/auth/login`, `/api/v1/courses`.

## 2. TZ bo‘yicha holat

Belgilar:

- ✅ — asosiy backend logikasi va endpoint ishlaydi.
- 🟡 — asosiy logika bor, lekin TZ path/DTO yoki ayrim operatsiyalar to‘liq mos emas.
- ❌ — TZ dagi alohida operatsiya hozir yo‘q.

| TZ bo‘limi | Holat | Frontend uchun izoh |
| --- | --- | --- |
| Auth va profile, #1–9 | ✅ (product-trimmed) | Login, rotate refresh, logout, me, profile, photo va password ishlaydi. Product qarori bilan preferences, `/users` va `/auth/change-password` olib tashlangan. |
| Admin accounts, #10–19 | ✅ | `/admin/accounts` kontrakti, one-time temporary credentials, versioned update/status, soft delete, course assignments va paged activity audit ishlaydi. `SUPPORT_TEACHER` canonical role. |
| Courses/modules/enrollments, #20–33 | ✅ | Scoped course CRUD, status, teachers, idempotent enrollment, module status/order va `/students/me/courses` ishlaydi. |
| Groups, #34–41 | ✅ | Global scoped directory, versioned update/status, eligible students va transactional membership endpointlari ishlaydi. |
| Question bank, #42–48 | ✅ / 🟡 | Savol CRUD, turlar validatsiyasi, ownership, archive/restore, version va snapshot safety ishlaydi. Path `/questions`; summary `/questions/summary`. TZ dagi `PUT status`, `DELETED` tombstone va course-specific summary aynan mos emas. |
| Reusable exam templates, #49–55 | ✅ / 🟡 | `/exams` orqali CRUD, ownership, version, archive, duplicate, summary va edit-lock ishlaydi. TZ nomi `/exam-templates`; usage va explicit status/restore endpointlari to‘liq yo‘q. |
| Assignments, #56–64 | ✅ / 🟡 | `/exam-assignments` orqali immutable snapshot, audience, version, transitions, unused delete, review-policy va release-answer-review ishlaydi. TZ `/assignments` pathidan farq qiladi; resolved audience uchun alohida GET yo‘q. |
| Student attempts/integrity, #65–73 | ✅ / 🟡 | Start, fixed snapshot/order, resume detail, revisionli autosave, deadline, idempotent integrity events, focus limit va submit ishlaydi. Start `/exam-assignments/{id}/start`; dedicated `/students/me/exams`, `/students/me/attempts`, `/delivery`, `/status`, `/results/{id}` pathlari aynan ajratilmagan. |
| Results/manual grading, #74–78 | 🟡 | Scoped `/results`, `/results/summary`, `/grading/pending` va per-answer `/answers/{id}/grade` ishlaydi. TZ dagi staff attempt detail va bitta atomic batch `POST /results/attempts/{id}/grade` yo‘q; student result pathi ham umumiy scoped resultdan olinadi. |
| Dashboards, #79–81 | 🟡 | `/admin/dashboard`, `/student/dashboard`, `/teacher/dashboard` ishlaydi va real DB aggregate ishlatadi. TZ misolidagi barcha chart/activity/card maydonlari aynan bir xil emas. |
| Optional notifications N1–N3 | ✅ / 🟡 | `/notifications`, `/{id}/mark-read`, `/mark-all-read` ishlaydi. TZ path nomlari va `read-all` response shakli biroz farq qiladi. |

### To‘liq ishlaydigan asosiy biznes logika

- Role va resource scope serverda tekshiriladi; browser yuborgan role/IDga ishonilmaydi.
- Question/exam/assignment ownership va course scope tekshiriladi.
- Assignment va attempt snapshotlari tarixiy savol/javoblarni saqlaydi.
- Parallel attempt start uchun PostgreSQL row lock va DB constraint mavjud.
- Autosave revision, deadline, submit, objective grading va manual grading ishlaydi.
- Assignment state machine, attemptdan keyingi edit-lock va answer-review release guard ishlaydi.
- Student DTOlarda correct answer va ichki grading ma’lumoti yashiriladi.
- Refresh rotation/blacklist, inactive account denial va login rate limit ishlaydi.
- Audit log assignment transition, review release, grading va integrity eventlar uchun yoziladi.

### Frontend original TZga aynan ulanmasidan oldin qolgan P0 ishlar

1. Butun API uchun `camelCase` request/response yoki frontend generated clientda aniq adapter.
2. TZ pagination envelope va stable error code/requestId formati.
3. Dedicated `/students/me/*` va `/results/attempts/*` path/DTOlari.
4. Atomic batch manual grading endpointi (#76).
5. Universal `Idempotency-Key` create/start/submit/grade/reset/release operatsiyalari uchun.
6. Course/group kabi qolgan editable DTOlarda optimistic `version`/`If-Match`.
7. Self-profile telefonini aynan `+998` + 9 raqamga normalize qilish.
8. Barcha UTC timestamp response’larini `Z` bilan standartlashtirish.

Shu sababli backend biznes logikasi katta qismi tayyor, ammo original 81-operation TZ bilan
**drop-in contract compatibility hali 100% emas**. Frontendchi hozir integratsiyani joriy Swagger
bo‘yicha boshlashi mumkin; original TZ pathlarini hard-code qilmasligi kerak.

## 3. Frontend uchun real asosiy pathlar

| Qism | Hozirgi path |
| --- | --- |
| Auth | `/auth/login`, `/auth/refresh`, `/auth/logout`, `/auth/me` |
| Profile | `/profile`, `/profile/photo`, `/profile/change-password` |
| Accounts | `/admin/accounts`, `/teachers`, `/students` |
| Academics | `/courses`, `/groups`, `/courses/{id}/teachers`, `/students`, `/modules`, `/groups` nested pathlari |
| Questions | `/questions`, `/questions/summary` |
| Exam library | `/exams`, `/exams/summary`, `/exams/{id}/duplicate` |
| Assignments | `/exam-assignments`, `/{id}/transitions`, `/{id}/review-policy`, `/{id}/release-answer-review` |
| Attempt | `/exam-assignments/{id}/start`, `/attempts/{id}`, `/attempts/{id}/answers/{question_id}`, `/events`, `/submit` |
| Grading/results | `/grading/pending`, `/answers/{id}/grade`, `/results`, `/results/summary` |
| Dashboard | `/admin/dashboard`, `/teacher/dashboard`, `/student/dashboard` |
| Notifications | `/notifications`, `/notifications/{id}/mark-read`, `/notifications/mark-all-read` |

To‘liq method, query va schema ro‘yxati Swagger’da ko‘riladi:

- `http://<server>/api/docs`
- `http://<server>/api/schema`

## 4. AWS EC2 ga hozircha HTTP deploy

### Muhim ogohlantirish

HTTP’da login paroli, access token va refresh token tarmoqda shifrlanmaydi. Bu konfiguratsiya faqat
vaqtinchalik test/integratsiya serveri uchun. Real foydalanuvchilar va real imtihon ma’lumotlari uchun
HTTPS majburiy. Kamida EC2 Security Groupda `22` portni faqat o‘z IP manzilingizga oching; `5432` va
`8000` portlarini internetga ochmang. Tashqariga faqat `80` ochiladi.

### Server talablari

- Ubuntu EC2 (kamida 2 GB RAM tavsiya qilinadi).
- Elastic IP tavsiya qilinadi; oddiy public IP restartdan keyin o‘zgarishi mumkin.
- Docker Engine va Docker Compose plugin.
- Security Group inbound: `22` — faqat admin IP; `80` — kerakli clientlar yoki `0.0.0.0/0`.

### Ishga tushirish

```bash
git clone <repository-url> examtaker
cd examtaker
cp .env.aws.example .env.aws
nano .env.aws
```

`.env.aws` ichida kamida quyidagilarni almashtiring:

- `SECRET_KEY`
- `ALLOWED_HOSTS` — EC2 public/Elastic IP yoki domain, schemesiz
- `POSTGRES_PASSWORD`
- `DATABASE_URL` ichidagi shu password
- `CORS_ALLOWED_ORIGINS` — frontendning to‘liq origin manzili
- `CSRF_TRUSTED_ORIGINS` — `http://` bilan backend origin

So‘ng:

```bash
docker compose --env-file .env.aws -f docker-compose.aws.yml config --quiet
docker compose --env-file .env.aws -f docker-compose.aws.yml up -d --build
docker compose --env-file .env.aws -f docker-compose.aws.yml ps
docker compose --env-file .env.aws -f docker-compose.aws.yml logs -f web nginx
```

Redeployda mavjud `postgres_data` volume ishlatilsa, `POSTGRES_PASSWORD`ni o‘zboshimchalik bilan
almashtirmang: Postgres image mavjud DB user parolini environmentdan qayta o‘rnatmaydi.
`POSTGRES_PASSWORD` va `DATABASE_URL` ichidagi password doim bir xil bo‘lishi shart.

Birinchi Super Admin:

```bash
docker compose --env-file .env.aws -f docker-compose.aws.yml exec web python manage.py createsuperuser
```

Tekshirish:

```bash
curl http://YOUR_EC2_PUBLIC_IP/api/docs
curl -i http://YOUR_EC2_PUBLIC_IP/api/v1/auth/me
```

Ikkinchi so‘rovning `401` qaytarishi server ishlayotganini bildiradi.

### Ushbu AWS compose nimalarni hal qiladi

- Nginx port `80`da Gunicorn/Django’ga reverse proxy qiladi.
- PostgreSQL private Docker networkda qoladi va tashqi portga publish qilinmaydi.
- Migration container startida avtomatik bajariladi.
- `media-init` redeployda avatar volume ownership va read/write permissionlarini tiklaydi.
- Avatarlar `media_data` volume’da saqlanadi va Nginx `/media/` orqali beradi.
- PostgreSQL ma’lumoti `postgres_data` volume’da saqlanadi.
- Web/finalizer/nginx/db restartdan keyin avtomatik qayta turadi.
- `finalizer` muddati o‘tgan attemptlarni har daqiqada server tomonda yakunlaydi.

### Yangilash

```bash
docker compose --env-file .env.aws -f docker-compose.aws.yml exec -T db \
  sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' > examtaker-before-deploy.sql
git pull
docker compose --env-file .env.aws -f docker-compose.aws.yml config --quiet
docker compose --env-file .env.aws -f docker-compose.aws.yml up -d --build
docker compose --env-file .env.aws -f docker-compose.aws.yml ps
docker compose --env-file .env.aws -f docker-compose.aws.yml logs --tail=100 web
docker compose --env-file .env.aws -f docker-compose.aws.yml exec web \
  python manage.py showmigrations --plan
```

### Backup

```bash
docker compose --env-file .env.aws -f docker-compose.aws.yml exec -T db \
  sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' > examtaker-backup.sql
```

`postgres_data` va `media_data` volumelarini ham AWS snapshot/backup siyosatiga kiriting.

## 5. Keyin HTTPS yoqilganda

Domain va TLS sertifikat o‘rnatilgach:

1. Nginx yoki AWS Application Load Balancer TLSni terminate qiladi va
   `X-Forwarded-Proto: https` yuboradi.
2. `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS` domain/HTTPSga almashtiriladi.
3. `SECURE_SSL_REDIRECT=true`, `SESSION_COOKIE_SECURE=true`, `CSRF_COOKIE_SECURE=true` qilinadi.
4. Hammasi HTTPSda ishlashi tekshirilgandan keyin `SECURE_HSTS_SECONDS` avval kichik qiymat bilan,
   keyin uzoq muddatga oshiriladi. HSTSni HTTP test bosqichida yoqmang.
5. Frontend tokenni URL/query/local loglarga chiqarmasligi va productionda browser storage siyosati
   alohida security reviewdan o‘tishi kerak.
