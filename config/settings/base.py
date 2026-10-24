    """Umumiy sozlamalar. Muhitga xos qiymatlar `dev.py` / `prod.py` / `test.py` da."""

    from datetime import timedelta
    from pathlib import Path

    import environ

    BASE_DIR = Path(__file__).resolve().parent.parent.parent

    env = environ.Env()
    _env_file = BASE_DIR / ".env"
    if _env_file.exists():
        environ.Env.read_env(str(_env_file))

    # --------------------------------------------------------------------------
    # Core
    # --------------------------------------------------------------------------
    SECRET_KEY = env("SECRET_KEY")
    DEBUG = env.bool("DEBUG", default=False)
    ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[])

    INSTALLED_APPS = [
        "django.contrib.admin",
        "django.contrib.auth",
        "django.contrib.contenttypes",
        "django.contrib.sessions",
        "django.contrib.messages",
        "django.contrib.staticfiles",
        # third-party
        "rest_framework",
        "rest_framework_simplejwt.token_blacklist",
        "django_filters",
        "corsheaders",
        "drf_spectacular",
        # local
        "apps.users",
        "apps.academics",
        "apps.questions",
        "apps.exams",
        "apps.assignments",
        "apps.attempts",
        "apps.reports",
    ]

    MIDDLEWARE = [
        "django.middleware.security.SecurityMiddleware",
        "whitenoise.middleware.WhiteNoiseMiddleware",
        "corsheaders.middleware.CorsMiddleware",
        "django.contrib.sessions.middleware.SessionMiddleware",
        "django.middleware.common.CommonMiddleware",
        "django.middleware.csrf.CsrfViewMiddleware",
        "django.contrib.auth.middleware.AuthenticationMiddleware",
        "django.contrib.messages.middleware.MessageMiddleware",
        "django.middleware.clickjacking.XFrameOptionsMiddleware",
    ]

    ROOT_URLCONF = "config.urls"
    WSGI_APPLICATION = "config.wsgi.application"
    ASGI_APPLICATION = "config.asgi.application"

    TEMPLATES = [
        {
            "BACKEND": "django.template.backends.django.DjangoTemplates",
            "DIRS": [],
            "APP_DIRS": True,
            "OPTIONS": {
                "context_processors": [
                    "django.template.context_processors.request",
                    "django.contrib.auth.context_processors.auth",
                    "django.contrib.messages.context_processors.messages",
                ],
            },
        },
    ]

    # --------------------------------------------------------------------------
    # Database / cache
    # --------------------------------------------------------------------------
    # `DATABASES` — dev.py / prod.py / test.py da.

    DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

    # V1 da Redis yo‘q: throttling uchun umumiy (worker lar o‘rtasida) cache kerak,
    # shuning uchun DatabaseCache (`python manage.py createcachetable`).
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.db.DatabaseCache",
            "LOCATION": "django_cache",
        }
    }

    # --------------------------------------------------------------------------
    # Auth
    # --------------------------------------------------------------------------
    AUTH_USER_MODEL = "users.User"

    PASSWORD_HASHERS = [
        "django.contrib.auth.hashers.Argon2PasswordHasher",
        "django.contrib.auth.hashers.PBKDF2PasswordHasher",
        "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    ]

    AUTH_PASSWORD_VALIDATORS = [
        {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
        {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
        {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
        {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
    ]

    # --------------------------------------------------------------------------
    # Internationalization
    # --------------------------------------------------------------------------
    LANGUAGE_CODE = "uz"
    TIME_ZONE = "Asia/Tashkent"
    USE_I18N = True
    USE_TZ = True

    # --------------------------------------------------------------------------
    # Static
    # --------------------------------------------------------------------------
    STATIC_URL = "static/"
    STATIC_ROOT = BASE_DIR / "staticfiles"
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
    }

    # --------------------------------------------------------------------------
    # DRF
    # --------------------------------------------------------------------------
    REST_FRAMEWORK = {
        "DEFAULT_AUTHENTICATION_CLASSES": [
            "rest_framework_simplejwt.authentication.JWTAuthentication",
        ],
        "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
        "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
        "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
        "DEFAULT_PAGINATION_CLASS": "common.pagination.StandardPagination",
        "DEFAULT_FILTER_BACKENDS": [
            "django_filters.rest_framework.DjangoFilterBackend",
            "rest_framework.filters.SearchFilter",
            "rest_framework.filters.OrderingFilter",
        ],
        "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
        "EXCEPTION_HANDLER": "common.exceptions.api_exception_handler",
        # Ball/foizlar JSON da son sifatida ("7.00" emas, 7.0).
        "COERCE_DECIMAL_TO_STRING": False,
        "DEFAULT_THROTTLE_CLASSES": [
            "rest_framework.throttling.AnonRateThrottle",
            "rest_framework.throttling.UserRateThrottle",
        ],
        "DEFAULT_THROTTLE_RATES": {
            "anon": "60/min",
            "user": "600/min",
            "login": "5/min",  # (IP + email) bo‘yicha
            "login_ip": "120/min",  # faqat IP bo‘yicha
        },
        # Nginx/Load balancer orqasida: 1. To‘g‘ridan-to‘g‘ri: 0.
        "NUM_PROXIES": env.int("NUM_PROXIES", default=0),
    }

    SIMPLE_JWT = {
        "ACCESS_TOKEN_LIFETIME": timedelta(minutes=env.int("JWT_ACCESS_MINUTES", default=30)),
        "REFRESH_TOKEN_LIFETIME": timedelta(days=env.int("JWT_REFRESH_DAYS", default=7)),
        "ROTATE_REFRESH_TOKENS": True,
        "BLACKLIST_AFTER_ROTATION": True,
        "UPDATE_LAST_LOGIN": True,
        "AUTH_HEADER_TYPES": ("Bearer",),
    }

    SPECTACULAR_SETTINGS = {
        "TITLE": "ExamTaker API",
        "DESCRIPTION": "IT Academy uchun onlayn imtihon platformasi — backend API.",
        "VERSION": "1.0.0",
        "SERVE_INCLUDE_SCHEMA": False,
        "COMPONENT_SPLIT_REQUEST": True,
        "SERVE_PERMISSIONS": ["rest_framework.permissions.AllowAny"],
        "ENUM_NAME_OVERRIDES": {
            "UserRoleEnum": "apps.users.choices.UserRole",
            "CreatableUserRoleEnum": "apps.users.choices.CreatableUserRole",
            "UserStatusEnum": "apps.users.choices.UserStatus",
            # Course/Module/Question statuslari bir xil to‘plam (ACTIVE/ARCHIVED).
            "ActiveArchivedStatusEnum": "apps.academics.choices.CourseStatus",
            "CourseTeacherTypeEnum": "apps.academics.choices.CourseTeacherType",
            "EnrollmentStatusEnum": "apps.academics.choices.EnrollmentStatus",
            "QuestionTypeEnum": "apps.questions.choices.QuestionType",
            "ExamStatusEnum": "apps.exams.choices.ExamStatus",
            "ExamWritableStatusEnum": "apps.exams.choices.ExamWritableStatus",
            "AssignmentStatusEnum": "apps.assignments.choices.EffectiveStatus",
            "StoredAssignmentStatusEnum": "apps.assignments.choices.AssignmentStatus",
            "AudienceTypeEnum": "apps.assignments.choices.AudienceType",
            "AttemptStatusEnum": "apps.attempts.choices.AttemptStatus",
        },
    }

    # Attempt `deadline_at` dan keyin ham shuncha soniya kechikkan so‘rov (tarmoq) qabul qilinadi.
    ATTEMPT_GRACE_SECONDS = env.int("ATTEMPT_GRACE_SECONDS", default=10)

    # API hujjatlari (/api/schema, /api/docs). Prod da sukut bo‘yicha o‘chiq.
    ENABLE_API_DOCS = env.bool("ENABLE_API_DOCS", default=DEBUG)

    # --------------------------------------------------------------------------
    # CORS
    # --------------------------------------------------------------------------
    CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[])
    CORS_ALLOW_CREDENTIALS = False


    def database_from_env(default: str | None = None) -> dict:
        """SQLite sukut bo‘yicha; DATABASE_URL berilsa, o‘sha bazaga ulanadi."""
        if default is None and not env("DATABASE_URL", default=None):
            config = {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}
        else:
            config = env.db("DATABASE_URL", default=default)
        is_sqlite = config["ENGINE"] == "django.db.backends.sqlite3"
        config["CONN_MAX_AGE"] = env.int("DB_CONN_MAX_AGE", default=0 if is_sqlite else 60)
        if is_sqlite:
            config["OPTIONS"] = {**config.get("OPTIONS", {}), "timeout": 20}
        return config


    # --------------------------------------------------------------------------
    # Logging
    # --------------------------------------------------------------------------
    LOGGING = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"},
        },
        "handlers": {
            "console": {"class": "logging.StreamHandler", "formatter": "standard"},
        },
        "root": {"handlers": ["console"], "level": env("LOG_LEVEL", default="INFO")},
    }
