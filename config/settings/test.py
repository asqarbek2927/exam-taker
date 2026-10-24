import os

# `base` import qilinishidan oldin (u SECRET_KEY ni o‘qiydi).
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production-use-0123456789abcdef")

from .base import *  # noqa: F403
from .base import REST_FRAMEWORK, database_from_env

DEBUG = False
ALLOWED_HOSTS = ["testserver", "localhost"]
ENABLE_API_DOCS = True

# CI da `DATABASE_URL` (PostgreSQL) beriladi, aks holda in-memory SQLite.
DATABASES = {"default": database_from_env(default="sqlite:///:memory:")}

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

# Testlar tez ishlashi uchun.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

# Throttling testlarni "flaky" qilmasligi uchun yuqori limitlar (login limiti
# alohida testda monkeypatch qilinadi).
REST_FRAMEWORK = {
    **REST_FRAMEWORK,
    "DEFAULT_THROTTLE_RATES": {
        "anon": "10000/min",
        "user": "10000/min",
        "login": "10000/min",
        "login_ip": "10000/min",
    },
}

# Statik fayllarni WhiteNoise emas, Django o‘zi beradi (STATIC_ROOT shart emas).
MIDDLEWARE = [m for m in MIDDLEWARE if "whitenoise" not in m]  # noqa: F405
