# exam-taker.uz — production server (haqiqiy sozlama)

> `docs/PRODUCTION_DEPLOY_UZ.md` va `docker-compose*.yml` Docker uchun yozilgan. Hozirgi
> production server **Docker'siz** ishlaydi — quyidagi hujjat aynan shu serverga tegishli.

## Tuzilishi

| Qism | Qayerda |
|---|---|
| Server | AWS EC2 (`ap-southeast-2`), Ubuntu 24.04, Elastic IP — domen shunga ulangan |
| Kod | `~/exam_taker/exam-taker` (`main` branch), Python venv: `venv/` |
| Ilova | systemd `gunicorn.service` → `127.0.0.1:8000`, `DJANGO_SETTINGS_MODULE=config.settings.prod` |
| Muhit | `~/exam.env` (`DATABASE_URL`, gunicorn `EnvironmentFile`) + loyihadagi `.env` (qolgan sozlamalar) |
| Baza | Lokal PostgreSQL 16 (`127.0.0.1:5432`) |
| Web | nginx (80/443) + Let's Encrypt; `/etc/nginx/conf.d/security.conf` da `server_tokens off` |
| Kirish | Faqat EC2 Instance Connect (Security Group: 22-port faqat `ec2-instance-connect` prefix list) |

## Deploy

```bash
cd ~/exam_taker/exam-taker
bash scripts/deploy_server.sh
```

Skript: qo'lda o'zgartirilgan fayl yo'qligini tekshiradi → yangi commitlar va yangi
migratsiyalarni ko'rsatib tasdiq so'raydi → bazani `~/backups/pre_deploy_<vaqt>_<commit>.dump`
ga saqlaydi → `git pull` (faqat fast-forward) → `requirements.txt` o'zgargan bo'lsa `pip install`
→ `check`, `migrate`, `createcachetable`, `collectstatic` → gunicorn restart → `/health/ready`.

- Tasdiqsiz: `bash scripts/deploy_server.sh -y`
- Xato bo'lsa kod avtomatik avvalgi commitga qaytadi va gunicorn qayta ishga tushadi.
- **Migratsiyalar avtomatik qaytarilmaydi.** Migratsiyadan keyin xato chiqsa, skript qaysi backup'dan
  tiklash kerakligini yozadi.
- Imtihon bo'lmagan vaqtda deploy qiling (gunicorn restart bir necha soniya uzilish beradi).

### Qo'lda `manage.py` buyruqlari

`manage.py` sukut bo'yicha **dev** sozlamalarini oladi. Prod bazasi bilan ishlash uchun avval:

```bash
cd ~/exam_taker/exam-taker
set -a; . ~/exam.env; set +a
export DJANGO_SETTINGS_MODULE=config.settings.prod
venv/bin/python manage.py <buyruq>
```

## Bazani backup'dan tiklash

Tiklash mavjud ma'lumotlarni almashtiradi — imtihon bo'lmagan vaqtda va avval yangi backup olib:

```bash
sudo systemctl stop gunicorn
set -a; . ~/exam.env; set +a
pg_dump -Fc -d "$DATABASE_URL" -f ~/backups/before_restore_$(date -u +%Y%m%dT%H%M%SZ).dump
pg_restore --clean --if-exists --no-owner -d "$DATABASE_URL" ~/backups/<TANLANGAN>.dump
sudo systemctl start gunicorn
curl -s https://exam-taker.uz/health/ready; echo
```

## Cron (`crontab -l`)

| Vaqt | Vazifa |
|---|---|
| har 6 soatda | `~/backup.sh` — baza backup'i `~/backups` ga |
| har daqiqa | `finalize_expired_attempts` — muddati o'tgan attemptlarni yopadi |
| har kuni 03:30 UTC | `flushexpiredtokens` — muddati o'tgan JWT tokenlarni bazadan tozalaydi |

`flushexpiredtokens` ni qo'shish (bir marta):

```bash
(crontab -l; echo '30 3 * * * cd /home/ubuntu/exam_taker/exam-taker && set -a && . /home/ubuntu/exam.env && set +a && DJANGO_SETTINGS_MODULE=config.settings.prod venv/bin/python manage.py flushexpiredtokens >> /home/ubuntu/backups/maintenance.log 2>&1') | crontab -
crontab -l
```

## Foydali buyruqlar

```bash
sudo systemctl status gunicorn --no-pager            # holat
journalctl -u gunicorn -n 100 --no-pager              # oxirgi loglar
journalctl -u gunicorn --since today | grep login_failed   # muvaffaqiyatsiz loginlar
df -h / && du -sh ~/backups                           # disk joyi
sudo nginx -t && sudo systemctl reload nginx          # nginx sozlamasini qayta yuklash
```

## Serverdan tashqaridagi backup

- EBS snapshot: AWS Console → EC2 → Volumes → Actions → Create snapshot.
- Tavsiya: EC2 → Lifecycle Manager → kunlik snapshot siyosati (oxirgi 7 ta).
