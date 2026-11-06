from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403
from .base import database_from_env, env

DATABASES = {"default": database_from_env()}

if DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3" and not env.bool(
    "ALLOW_SQLITE_IN_PRODUCTION", default=False
):
    raise ImproperlyConfigured("Production uchun PostgreSQL DATABASE_URL majburiy.")
if not ALLOWED_HOSTS:  # noqa: F405
    raise ImproperlyConfigured("Production uchun ALLOWED_HOSTS majburiy.")

DEBUG = False

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
SECURE_REDIRECT_EXEMPT = [r"^health/"]
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=0)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", default=False)
SECURE_HSTS_PRELOAD = env.bool("SECURE_HSTS_PRELOAD", default=False)
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
SESSION_COOKIE_SECURE = env.bool("SESSION_COOKIE_SECURE", default=SECURE_SSL_REDIRECT)
CSRF_COOKIE_SECURE = env.bool("CSRF_COOKIE_SECURE", default=SECURE_SSL_REDIRECT)
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])
