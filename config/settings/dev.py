from config.settings.base import *
from config.settings.base import database_from_env

DATABASES = {"default": database_from_env()}

DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "172.20.10.2"]
ENABLE_API_DOCS = True

# Dev da `createcachetable` talab qilmaslik uchun.
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

CORS_ALLOW_ALL_ORIGINS = True

# Statik fayllarni WhiteNoise emas, Django o‘zi beradi (STATIC_ROOT shart emas).
MIDDLEWARE = [m for m in MIDDLEWARE if "whitenoise" not in m]  # noqa: F405
