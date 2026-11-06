#!/bin/sh
set -eu

ENV_FILE="${ENV_FILE:-.env.production}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"

if [ ! -f "$ENV_FILE" ]; then
    echo "$ENV_FILE topilmadi. Avval: cp .env.production.example .env.production" >&2
    exit 1
fi

set -a
# shellcheck disable=SC1090
. "./$ENV_FILE"
set +a

: "${DOMAIN:?DOMAIN is required in $ENV_FILE}"
: "${LETSENCRYPT_EMAIL:?LETSENCRYPT_EMAIL is required in $ENV_FILE}"
: "${SECRET_KEY:?SECRET_KEY is required in $ENV_FILE}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required in $ENV_FILE}"

export APP_ENV_FILE="$ENV_FILE"

case "$DOMAIN $LETSENCRYPT_EMAIL $SECRET_KEY $POSTGRES_PASSWORD" in
    *CHANGE_ME*|*example.com*)
        echo "$ENV_FILE ichidagi placeholder qiymatlarni real qiymatlarga almashtiring." >&2
        exit 1
        ;;
esac

dc() {
    docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

mkdir -p backups
dc config --quiet
dc up -d --build db media-init web finalizer maintenance backup media-backup

if ! dc run --rm --no-deps --entrypoint /bin/sh certbot \
    -c "test -f '/etc/letsencrypt/live/$DOMAIN/fullchain.pem'"; then
    dc stop nginx >/dev/null 2>&1 || true
    dc --profile bootstrap up -d nginx-bootstrap
    dc --profile bootstrap run --rm certbot-bootstrap
    dc --profile bootstrap stop nginx-bootstrap
    dc --profile bootstrap rm -f nginx-bootstrap
fi

dc up -d nginx certbot
dc exec -T web python manage.py check --deploy
dc ps

echo "Deploy tayyor: https://$DOMAIN/health/ready"
