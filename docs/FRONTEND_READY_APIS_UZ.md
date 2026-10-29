# ExamTaker — frontend uchun tayyor API'lar

Yangilangan sana: 2026-10-29

Ushbu faylda faqat hozirgi backendda mavjud, OpenAPI schema'ga kirgan va umumiy regressiya
testlaridan o‘tgan endpointlar berilgan. Jami: **113 ta method/path operatsiya**.

> Muhim: bu ro‘yxat backendning **amaldagi kontrakti**. Original TZ dagi ayrim path va DTO nomlari
> boshqacha. Frontend aynan shu fayl va serverdagi Swagger asosida integratsiya qilishi kerak.

## Umumiy qoidalar

- Base URL: `http://SERVER_IP/api/v1`
- Swagger: `http://SERVER_IP/api/docs`
- OpenAPI: `http://SERVER_IP/api/schema`
- JSON maydonlari: `snake_case`
- Auth header: `Authorization: Bearer <access_token>`
- List response: `{"data": [...], "pagination": {...}}`
- Validation xatosi: `422`
- Unauthorized: `401`; forbidden: `403`; not found/scope tashqarisi: `404`
- Conflict/business state: `400` yoki `409`; rate limit: `429`
- UUID path parametrlari string sifatida yuboriladi.
- Trailing slash ishlatilmaydi.

Rollar:

- `Public` — tokensiz.
- `Auth` — login qilgan har qanday user.
- `Admin` — `SUPER_ADMIN`.
- `Teacher` — course scope ichidagi `TEACHER`.
- `Student` — faqat o‘z scope'i.

## 1. Auth va profile — tayyor

| Method | Path | Role | Vazifa |
| --- | --- | --- | --- |
| POST | `/auth/login` | Public | Email yoki username bilan login |
| POST | `/auth/refresh` | Public + refresh token | Access/refresh rotation |
| POST | `/auth/logout` | Auth | Refresh tokenni blacklist qilish |
| GET | `/auth/me` | Auth | Account, permission flags va preferences |
| PATCH | `/auth/me` | Auth | Eski profile aliasi |
| POST | `/auth/change-password` | Auth | Eski password-change aliasi |
| GET | `/profile` | Auth | Joriy profil |
| PATCH | `/profile` | Auth | Phone; Admin uchun full name ham |
| POST | `/profile/photo` | Auth | Multipart avatar upload |
| DELETE | `/profile/photo` | Auth | Avatarni o‘chirish |
| POST | `/profile/change-password` | Auth | Parolni o‘zgartirish va refresh sessionlarni bekor qilish |
| PATCH | `/profile/preferences` | Auth | `language` va `theme` |

Login request:

```json
{"emailOrUsername":"teacher@example.com","password":"StrongPassword1"}
```

Login response asosiy maydonlari:

```json
{
  "user": {"id":"uuid","full_name":"...","email":"...","role":"TEACHER"},
  "access_token":"...",
  "refresh_token":"...",
  "must_change_password":false
}
```

Refresh/logout request:

```json
{"refresh_token":"..."}
```

Password request:

```json
{"current_password":"OldPassword1","new_password":"NewPassword2"}
```

Preferences request:

```json
{"language":"uz","theme":"system"}
```

Avatar request: `multipart/form-data`, field nomi `image`; JPEG/PNG/WEBP, maksimal 5 MB.

## 2. Admin account boshqaruvi — tayyor

Bu endpointlarning hammasi faqat `SUPER_ADMIN` uchun.

| Method | Path | Vazifa |
| --- | --- | --- |
| GET | `/users` | Accountlar ro‘yxati |
| POST | `/users` | Teacher yoki student yaratish |
| GET | `/users/{id}` | Account detail |
| PATCH | `/users/{id}` | Accountni tahrirlash |
| POST | `/users/{id}/activate` | Accountni faollashtirish |
| POST | `/users/{id}/deactivate` | Accountni nofaol qilish va tokenlarni bekor qilish |
| POST | `/users/{id}/set-password` | Admin tomonidan yangi parol o‘rnatish |
| GET | `/teachers` | Teacher directory |
| GET | `/teachers/{id}` | Teacher detail/statistika |
| GET | `/teachers/summary` | Teacher summary kartalari |
| GET | `/students` | Student directory |
| GET | `/students/{id}` | Student detail/statistika |
| GET | `/students/summary` | Student summary kartalari |

User create ikki usulni qo‘llaydi:

```json
{
  "full_name":"Ali Valiyev",
  "email":"ali@example.com",
  "role":"STUDENT",
  "generate_random_password":true
}
```

yoki `generate_random_password` o‘rniga kuchli `password` yuboriladi. Random parol response'da
faqat bir marta `generated_password` sifatida qaytadi va userga `must_change_password=true` qo‘yiladi.

## 3. Courses — tayyor

| Method | Path | Role | Vazifa |
| --- | --- | --- | --- |
| GET | `/courses` | Auth, scoped | Admin: hammasi; Teacher: assigned; Student: enrolled |
| POST | `/courses` | Admin | Course yaratish |
| GET | `/courses/{id}` | Auth, scoped | Course detail |
| PATCH | `/courses/{id}` | Admin | Course tahrirlash |
| POST | `/courses/{id}/archive` | Admin | Course archive |
| POST | `/courses/{id}/restore` | Admin | Course restore |
| GET | `/courses/summary` | Admin | Course catalog summary |

## 4. Course teacher va enrollment — tayyor

| Method | Path | Role | Vazifa |
| --- | --- | --- | --- |
| GET | `/courses/{course_pk}/teachers` | Admin/Teacher scoped | Course teacherlari |
| POST | `/courses/{course_pk}/teachers` | Admin | Teacher biriktirish |
| PATCH | `/courses/{course_pk}/teachers/{id}` | Admin | `MAIN`/`SUPPORT` turini o‘zgartirish |
| DELETE | `/courses/{course_pk}/teachers/{id}` | Admin | Teacher assignmentni olib tashlash |
| GET | `/courses/{course_pk}/students` | Admin/Teacher scoped | Course roster |
| POST | `/courses/{course_pk}/students` | Admin | Student enrollment |
| PATCH | `/courses/{course_pk}/students/{id}` | Admin | Enrollment statusini o‘zgartirish |
| DELETE | `/courses/{course_pk}/students/{id}` | Admin | Studentni course'dan chiqarish |

Enrollment `DELETE` tarixni hard-delete qilmaydi; membershipni `REMOVED` holatiga o‘tkazadi va
course ichidagi faol group membershipni ham olib tashlaydi.

## 5. Modules — tayyor

| Method | Path | Role | Vazifa |
| --- | --- | --- | --- |
| GET | `/courses/{course_pk}/modules` | Auth, scoped | Course modullari |
| POST | `/courses/{course_pk}/modules` | Admin/Teacher scoped | Module yaratish |
| GET | `/courses/{course_pk}/modules/{id}` | Auth, scoped | Module detail |
| PATCH | `/courses/{course_pk}/modules/{id}` | Admin/Teacher scoped | Module tahrirlash |
| DELETE | `/courses/{course_pk}/modules/{id}` | Admin/Teacher scoped | Ishlatilmagan bo‘lsa delete, aks holda archive |

## 6. Groups — tayyor

Admin directory:

| Method | Path | Vazifa |
| --- | --- | --- |
| GET | `/groups` | Barcha grouplar |
| POST | `/groups` | Group yaratish |
| GET | `/groups/{id}` | Group detail |
| PATCH | `/groups/{id}` | Group tahrirlash |
| POST | `/groups/{id}/archive` | Group archive |
| POST | `/groups/{id}/restore` | Group restore |
| GET | `/groups/summary` | Group summary |

Course nested API:

| Method | Path | Role | Vazifa |
| --- | --- | --- | --- |
| GET | `/courses/{course_pk}/groups` | Admin/Teacher scoped | Course grouplari |
| POST | `/courses/{course_pk}/groups` | Admin | Group yaratish |
| GET | `/courses/{course_pk}/groups/{id}` | Admin/Teacher scoped | Group detail |
| PATCH | `/courses/{course_pk}/groups/{id}` | Admin | Group tahrirlash |
| DELETE | `/courses/{course_pk}/groups/{id}` | Admin | Ruxsat etilgan groupni o‘chirish |
| POST | `/courses/{course_pk}/groups/{id}/archive` | Admin | Archive |
| POST | `/courses/{course_pk}/groups/{id}/restore` | Admin | Restore |
| GET | `/courses/{course_pk}/groups/{group_pk}/students` | Admin/Teacher scoped | Group studentlari |
| POST | `/courses/{course_pk}/groups/{group_pk}/students` | Admin | Student qo‘shish |
| DELETE | `/courses/{course_pk}/groups/{group_pk}/students/{student_id}` | Admin | Studentni groupdan chiqarish |

## 7. Question bank — tayyor

Admin va assigned course Teacher uchun.

| Method | Path | Vazifa |
| --- | --- | --- |
| GET | `/questions` | Scoped question list/filter/search |
| POST | `/questions` | Question yaratish |
| GET | `/questions/{id}` | Staff question detail va options |
| PATCH | `/questions/{id}` | Owner/Admin tahrirlashi |
| DELETE | `/questions/{id}` | Ishlatilmagan bo‘lsa delete, aks holda archive |
| POST | `/questions/{id}/archive` | Archive |
| POST | `/questions/{id}/restore` | Restore |
| GET | `/questions/summary` | Question bank summary |

Qo‘llanadigan question turlari: `SINGLE_CHOICE`, `MULTIPLE_CHOICE`, `TRUE_FALSE`, `OPEN_ENDED`.
Question detail staffga correct flaglarni beradi; student attempt DTO ularni bermaydi.

## 8. Exam library — tayyor

Admin va assigned course Teacher uchun.

| Method | Path | Vazifa |
| --- | --- | --- |
| GET | `/exams` | Scoped exam list/filter/search |
| POST | `/exams` | Exam template yaratish |
| GET | `/exams/{id}` | Exam detail |
| PATCH | `/exams/{id}` | Owner/Admin tahrirlashi |
| DELETE | `/exams/{id}` | Ishlatilmagan bo‘lsa delete, aks holda archive |
| POST | `/exams/{id}/archive` | Archive |
| POST | `/exams/{id}/duplicate` | Exam nusxasini yaratish |
| GET | `/exams/summary` | Exam library summary |

Published assignment yoki attempt bilan bog‘langan exam kontenti edit-lock bilan himoyalangan.

## 9. Exam assignments — tayyor

| Method | Path | Role | Vazifa |
| --- | --- | --- | --- |
| GET | `/exam-assignments` | Auth, scoped | Staff directory yoki student eligible assignments |
| POST | `/exam-assignments` | Admin/Teacher scoped | Assignment va immutable snapshot yaratish |
| GET | `/exam-assignments/{id}` | Auth, scoped | Role-safe detail |
| PATCH | `/exam-assignments/{id}` | Owner/Admin | Ruxsat etilgan fieldlarni tahrirlash |
| DELETE | `/exam-assignments/{id}` | Owner/Admin | Faqat zero-attempt assignmentni o‘chirish |
| GET | `/exam-assignments/summary` | Admin/Teacher | Directory summary |
| POST | `/exam-assignments/{id}/transitions` | Owner/Admin | Umumiy state transition endpointi |
| POST | `/exam-assignments/{id}/publish` | Owner/Admin | Publish |
| POST | `/exam-assignments/{id}/pause` | Owner/Admin | Pause |
| POST | `/exam-assignments/{id}/resume` | Owner/Admin | Resume |
| POST | `/exam-assignments/{id}/complete` | Owner/Admin | Complete |
| POST | `/exam-assignments/{id}/cancel` | Owner/Admin | Cancel |
| POST | `/exam-assignments/{id}/restore` | Owner/Admin | Draftga restore |
| POST | `/exam-assignments/{id}/archive` | Owner/Admin | Archive |
| POST | `/exam-assignments/{id}/unarchive` | Owner/Admin | Archive'dan chiqarish |
| GET | `/exam-assignments/{id}/review-policy` | Admin/Teacher scoped | Review release holati va blockerlar |
| POST | `/exam-assignments/{id}/release-answer-review` | Owner/Admin | Answer reviewni release qilish |
| POST | `/exam-assignments/{id}/start` | Student | Attempt boshlash yoki faol attemptni davom ettirish |

Yangi frontend statusni arbitrary PATCH qilmasin; `transitions` yoki aniq action endpointlaridan
foydalansin. Attempt boshlanganidan keyin fairness-sensitive fieldlar lock qilinadi.

## 10. Attempts va exam runner — tayyor

| Method | Path | Role | Vazifa |
| --- | --- | --- | --- |
| GET | `/attempts` | Auth, scoped | Student o‘ziniki; Teacher course scope; Admin hammasi |
| GET | `/attempts/{id}` | Auth, scoped | Student delivery/result yoki staff detail |
| PUT | `/attempts/{id}/answers/{exam_question_id}` | Student owner | Revisionli autosave |
| POST | `/attempts/{id}/events` | Student owner | Fullscreen/tab/integrity event |
| POST | `/attempts/{id}/submit` | Student owner | Attempt submit |

Student uchun savol ID — `ExamQuestion` snapshot/delivery ID. Autosave payload:

```json
{"option_ids":["uuid"],"revision":1}
```

yoki open-ended uchun:

```json
{"text_answer":"Javob matni","revision":1}
```

Integrity event payload asosiy maydonlari:

```json
{
  "event_id":"client-generated-unique-id",
  "type":"TAB_HIDDEN",
  "client_at":"2026-10-29T10:00:00Z",
  "details":{}
}
```

Deadline, focus violation counter, fixed question/option order va final status server tomonidan boshqariladi.

## 11. Manual grading va results — tayyor

| Method | Path | Role | Vazifa |
| --- | --- | --- | --- |
| GET | `/grading/pending` | Admin/Teacher scoped | Manual grading queue |
| PATCH | `/answers/{answer_id}/grade` | Admin/Teacher scoped | Bitta open-ended javobni baholash |
| GET | `/results` | Auth, scoped | Student o‘z natijasi; Teacher course; Admin hammasi |
| GET | `/results/summary` | Auth, scoped | Result va grading summary |

Grade qiymati `0 <= points_awarded <= question points`. Barcha open-ended javoblar baholangach
attempt avtomatik `GRADED` bo‘ladi va final score/pass qayta hisoblanadi.

Grade request:

```json
{"points_awarded":3,"teacher_feedback":"Yaxshi javob"}
```

## 12. Dashboards — tayyor

| Method | Path | Role |
| --- | --- | --- |
| GET | `/admin/dashboard` | Admin |
| GET | `/teacher/dashboard` | Teacher |
| GET | `/student/dashboard` | Student |

Dashboard qiymatlari DB recordlaridan hisoblanadi; frontend page ichida demo count hisoblamasligi kerak.

## 13. Notifications — tayyor

| Method | Path | Role | Vazifa |
| --- | --- | --- | --- |
| GET | `/notifications` | Auth owner | Paged notifications |
| GET | `/notifications/{id}` | Auth owner | Notification detail |
| GET | `/notifications/summary` | Auth | Unread/total summary |
| POST | `/notifications/{id}/mark-read` | Auth owner | Bittasini read qilish |
| POST | `/notifications/mark-all-read` | Auth | Hammasini read qilish |

## Frontend integratsiya tartibi

1. Auth/profile va token refresh interceptor.
2. Role bo‘yicha `/auth/me.permissions` asosida route/button guard.
3. Course, roster va group sahifalari.
4. Question bank va exam library.
5. Assignment state actions.
6. Student exam runner: start → attempt GET → autosave/events → submit.
7. Manual grading/results.
8. Dashboard va notifications.

Frontend original TZdagi mavjud bo‘lmagan pathni taxmin qilmasin. Request/response fieldlarining to‘liq
schema, enum va filterlari uchun har doim `/api/docs` yoki `/api/schema`dan foydalansin.

## Verifikatsiya

- OpenAPI validation: warninglarsiz o‘tgan.
- Migration drift: yo‘q.
- Ruff lint/format: toza.
- Testlar: **522 passed**, **3 skipped**. Uchta skip faqat lokal SQLite'da PostgreSQL row-lock
  concurrency testlari; CI PostgreSQL bilan ularni ishlatadi.
