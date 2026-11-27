#!/usr/bin/env bash
# exam-taker.uz production deploy (systemd + gunicorn + lokal PostgreSQL, Docker'siz).
#
# Ishlatish (serverda):
#   cd ~/exam_taker/exam-taker && bash scripts/deploy_server.sh        # tasdiq so'raydi
#   bash scripts/deploy_server.sh -y                                    # tasdiqsiz
#
# Nima qiladi:
#   1) kodda qo'lda o'zgartirilgan fayl yo'qligini tekshiradi
#   2) yangi commitlarni ko'rsatadi va tasdiq so'raydi
#   3) bazaning backup'ini oladi (pg_dump)
#   4) git pull (faqat fast-forward)
#   5) requirements o'zgargan bo'lsa — pip install
#   6) Django check, migratsiya rejasi, migrate, createcachetable, collectstatic
#   7) gunicorn'ni qayta ishga tushiradi va /health/ready ni tekshiradi
# Xato bo'lsa kod avvalgi commitga qaytariladi va gunicorn qayta ishga tushiriladi.
# Migratsiyalar avtomatik QAYTARILMAYDI — kerak bo'lsa backup'dan tiklang (skript yo'lini aytadi).

set -Eeuo pipefail

APP_DIR="${APP_DIR:-$HOME/exam_taker/exam-taker}"
ENV_FILE="${ENV_FILE:-$HOME/exam.env}"
BACKUP_DIR="${BACKUP_DIR:-$HOME/backups}"
SERVICE="${SERVICE:-gunicorn}"
HEALTH_URL="${HEALTH_URL:-https://exam-taker.uz/health/ready}"
BRANCH="${BRANCH:-main}"
ASSUME_YES=0
[[ "${1:-}" == "-y" || "${1:-}" == "--yes" ]] && ASSUME_YES=1

step() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
ok() { printf '\033[1;32m✔ %s\033[0m\n' "$*"; }
fail() { printf '\033[1;31m✘ %s\033[0m\n' "$*" >&2; }

cd "$APP_DIR"
PYTHON="$APP_DIR/venv/bin/python"
PIP="$APP_DIR/venv/bin/pip"
[[ -x "$PYTHON" ]] || { fail "venv topilmadi: $PYTHON"; exit 1; }
[[ -f "$ENV_FILE" ]] || { fail "env fayl topilmadi: $ENV_FILE"; exit 1; }

# gunicorn bilan bir xil muhit (manage.py sukut bo'yicha DEV sozlamalarini oladi!)
set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a
export DJANGO_SETTINGS_MODULE=config.settings.prod
manage() { "$PYTHON" manage.py "$@"; }

step "1/7 Kod holati"
if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
    fail "Serverda qo'lda o'zgartirilgan fayllar bor — deploy to'xtatildi:"
    git status --short --untracked-files=no
    exit 1
fi
PREV="$(git rev-parse HEAD)"
git fetch --quiet origin "$BRANCH"
NEXT="$(git rev-parse "origin/$BRANCH")"
if [[ "$PREV" == "$NEXT" ]]; then
    ok "Yangi commit yo'q — server allaqachon $(git log --oneline -1 HEAD)"
    exit 0
fi
if ! git merge-base --is-ancestor "$PREV" "$NEXT"; then
    fail "origin/$BRANCH hozirgi commitdan davom etmaydi (fast-forward emas). Qo'lda tekshiring."
    exit 1
fi
echo "Hozir:  $(git log --oneline -1 "$PREV")"
echo "Yangi commitlar:"
git log --oneline "$PREV..$NEXT"
CHANGED="$(git diff --name-only "$PREV" "$NEXT")"
NEW_MIGRATIONS="$(grep -E '/migrations/[0-9]{4}_.*\.py$' <<<"$CHANGED" || true)"
if [[ -n "$NEW_MIGRATIONS" ]]; then
    echo -e "\n\033[1;33m⚠ Yangi migratsiyalar bor:\033[0m"
    echo "$NEW_MIGRATIONS"
fi
if [[ "$ASSUME_YES" != 1 ]]; then
    read -r -p $'\nDeploy qilinsinmi? [y/N] ' answer
    [[ "$answer" =~ ^[Yy]$ ]] || { echo "Bekor qilindi."; exit 0; }
fi

step "2/7 Baza backup'i"
mkdir -p "$BACKUP_DIR"
BACKUP_FILE="$BACKUP_DIR/pre_deploy_$(date -u +%Y%m%dT%H%M%SZ)_${PREV:0:7}.dump"
pg_dump -Fc -d "$DATABASE_URL" -f "$BACKUP_FILE"
[[ -s "$BACKUP_FILE" ]] || { fail "Backup bo'sh: $BACKUP_FILE"; exit 1; }
TABLES="$(pg_restore -l "$BACKUP_FILE" | grep -c 'TABLE DATA' || true)"
ok "Backup: $BACKUP_FILE ($(du -h "$BACKUP_FILE" | cut -f1), $TABLES ta jadval)"

MIGRATED=0
rollback() {
    local code=$?
    fail "Deploy xato bilan to'xtadi (kod $code). Kod $PREV ga qaytarilmoqda..."
    git reset --hard --quiet "$PREV" || true
    sudo systemctl restart "$SERVICE" || true
    if [[ "$MIGRATED" == 1 ]]; then
        fail "Diqqat: migratsiyalar qo'llangan edi va avtomatik qaytarilmaydi."
        fail "Kerak bo'lsa bazani tiklang: pg_restore --clean --if-exists --no-owner -d \"\$DATABASE_URL\" $BACKUP_FILE"
    fi
    fail "Hozirgi holat: $(git log --oneline -1)"
    exit "$code"
}
trap rollback ERR

step "3/7 Kodni yangilash"
git merge --ff-only --quiet "$NEXT"
ok "$(git log --oneline -1)"

step "4/7 Kutubxonalar"
if grep -qE '^requirements(-dev)?\.txt$' <<<"$CHANGED"; then
    "$PIP" install --quiet -r requirements.txt
    ok "requirements.txt o'rnatildi"
else
    ok "requirements.txt o'zgarmagan — o'tkazib yuborildi"
fi

step "5/7 Tekshiruv va migratsiya"
manage check
manage migrate --plan
MIGRATED=1
manage migrate --noinput
manage createcachetable
manage collectstatic --noinput --verbosity 0
ok "Migratsiya va statik fayllar tayyor"

step "6/7 Gunicorn'ni qayta ishga tushirish"
sudo systemctl restart "$SERVICE"

step "7/7 Sog'liq tekshiruvi"
for attempt in $(seq 1 15); do
    if curl -fsS --max-time 5 "$HEALTH_URL" 2>/dev/null | grep -q '"ok"'; then
        trap - ERR
        ok "$HEALTH_URL — ok (urinish $attempt)"
        echo
        ok "Deploy tugadi: $(git log --oneline -1)"
        echo "Backup: $BACKUP_FILE"
        exit 0
    fi
    sleep 2
done
fail "$HEALTH_URL 30 soniyada javob bermadi"
sudo journalctl -u "$SERVICE" -n 30 --no-pager || true
false  # -> rollback
