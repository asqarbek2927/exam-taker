# ExamTaker production deploy (PostgreSQL + Docker + Nginx + HTTPS)

Bu konfiguratsiya bitta production server uchun tayyorlangan. Tashqariga faqat Nginxning
`80/443` portlari ochiladi; Django/Gunicorn va PostgreSQL Docker private networkda qoladi.

## 1. Server va DNS

Serverda Docker Engine va Docker Compose plugin o‘rnatilgan bo‘lishi kerak. Tavsiya etilgan
minimum: 2 CPU, 4 GB RAM va yetarli SSD disk.

DNS boshqaruvida backend domeni uchun server public IP manziliga `A` record yarating:

```text
api.example.com -> SERVER_PUBLIC_IP
```

DNS tarqalganini tekshirgach deployni boshlang. Firewall/Security Group:

- `22/tcp` — faqat administrator IP manzilidan;
- `80/tcp` — internetdan (Let’s Encrypt va HTTPS redirect uchun);
- `443/tcp` — internetdan;
- `5432` va `8000` — internetga ochilmaydi.

## 2. Environment tayyorlash

```bash
git clone <repository-url> examtaker
cd examtaker
cp .env.production.example .env.production
chmod 600 .env.production
nano .env.production
```

Majburiy qiymatlar:

- `DOMAIN` — backend domeni, masalan `api.example.com`;
- `LETSENCRYPT_EMAIL` — sertifikat ogohlantirishlari keladigan email;
- `SECRET_KEY` — kamida 50 belgili tasodifiy qiymat;
- `POSTGRES_PASSWORD` va shu parol qatnashgan `DATABASE_URL`;
- `ALLOWED_HOSTS` — backend domeni;
- `CORS_ALLOWED_ORIGINS` — frontendning to‘liq HTTPS origini;
- `CSRF_TRUSTED_ORIGINS` — backendning to‘liq HTTPS origini.

Secret yaratish misoli:

```bash
openssl rand -base64 48
```

PostgreSQL parolida URL uchun maxsus belgilar ishlatilsa, `DATABASE_URL` ichida percent-encode
qiling. Eng sodda variant — uzun harf/raqamli parol ishlatish.

## 3. Birinchi deploy

```bash
sh docker/deploy-production.sh
```

Script quyidagilarni avtomatik bajaradi:

1. Compose va environment konfiguratsiyasini tekshiradi.
2. PostgreSQL, Django/Gunicorn va background servislarni ishga tushiradi.
3. Migratsiyalarni va shared cache jadvalini yaratadi.
4. Let’s Encrypt TLS sertifikatini oladi.
5. HTTPS Nginx va avtomatik sertifikat renewal servislarini ishga tushiradi.
6. Django `check --deploy` tekshiruvini bajaradi.

Birinchi Super Admin:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml \
  exec web python manage.py createsuperuser
```

Tekshirish:

```bash
curl -i https://api.example.com/health/live
curl -i https://api.example.com/health/ready
docker compose --env-file .env.production -f docker-compose.prod.yml ps
docker compose --env-file .env.production -f docker-compose.prod.yml logs --tail=200 web nginx
```

Ikkala health endpoint ham `200` va `{"status":"ok"}` qaytarishi kerak.

## 4. Servislar

- `db` — persistent PostgreSQL;
- `web` — Gunicorn orqali Django API;
- `nginx` — HTTPS termination, reverse proxy va media serving;
- `certbot` — Let’s Encrypt sertifikatini har 12 soatda tekshiradi;
- `finalizer` — muddati o‘tgan attemptlarni har daqiqada yakunlaydi;
- `maintenance` — eskirgan JWT blacklist tokenlarini har kuni tozalaydi;
- `backup` — PostgreSQL dumpni har kuni `./backups` ichiga yozadi;
- `media-backup` — yuklangan media fayllarini har kuni `./backups` ichiga arxivlaydi.

`postgres_data`, `media_data` va TLS certificate volumelarini server snapshot siyosatiga kiriting.
`./backups` katalogini boshqa server yoki object storage’ga muntazam nusxalash shart.

## 5. Yangilash

Deploydan oldin qo‘lda backup olish:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml exec -T db \
  sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' | gzip \
  > "backups/manual_$(date -u +%Y%m%dT%H%M%SZ).sql.gz"
```

Keyin:

```bash
git pull --ff-only
sh docker/deploy-production.sh
docker compose --env-file .env.production -f docker-compose.prod.yml logs --tail=200 web
```

## 6. Restore

Restore mavjud bazani o‘zgartiradi. To‘g‘ri backup tanlanganini tekshirib, maintenance oynasida:

```bash
gunzip -c backups/SELECTED_BACKUP.sql.gz | \
  docker compose --env-file .env.production -f docker-compose.prod.yml exec -T db \
  sh -c 'psql -U "$POSTGRES_USER" "$POSTGRES_DB"'
```

Katta yoki muhim production bazasida restore’dan oldin alohida yangi database’da sinov restore
bajaring.

## 7. Production checklist

- `.env.production` Gitga qo‘shilmagan va permissioni `600`;
- `ENABLE_API_DOCS=false`;
- barcha frontend URLlar `https://`;
- `SECURE_SSL_REDIRECT`, secure cookies va HSTS yoqilgan;
- `5432/8000` tashqariga yopiq;
- backup serverdan tashqariga ham nusxalanadi va restore sinovi o‘tkazilgan;
- server disk/RAM, container restartlari, `/health/ready` va certificate expiry monitoringga ulangan;
- deploydan keyin login, assignment, attempt autosave/submit va media upload smoke-test qilingan.
