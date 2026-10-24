#!/bin/sh
# Konteyner ishga tushishida migratsiyalarni qo‘llaydi, so‘ng berilgan buyruqni bajaradi.
# Bir nechta replica ishlatilsa, migratsiyani alohida job qilib, RUN_MIGRATIONS=0 qo‘ying.
set -e

if [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
    python manage.py migrate --noinput
    python manage.py createcachetable
fi

exec "$@"
