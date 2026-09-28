"""Base Django settings shared by every environment.

All environment specific values are read from environment variables (optionally
loaded from a ``.env`` file placed at the repository root). No secret is ever
hardcoded inside the source tree.
"""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Load `.env` once, before any setting is read.
load_dotenv(BASE_DIR / ".env")


def env_bool(name: str, default: bool = False) -> bool:
    """Read a boolean flag from the environment.

    Accepted truthy values: ``1, true, yes, on``.
    """
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    """Read a comma separated list from the environment."""
    raw = os.environ.get(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


# ---------------------------------------------------------------------------
# Core security
# ---------------------------------------------------------------------------
SECRET_KEY = os.environ.get("SECRET_KEY", "insecure-development-key-do-not-use-in-production")
DEBUG = env_bool("DEBUG", False)
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "localhost,127.0.0.1")
CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS")

# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "rest_framework.authtoken",
    "corsheaders",
    "django_filters",
    "drf_spectacular",
]

LOCAL_APPS = [
    "apps.core",
    "apps.users",
    "apps.vehicles",
    "apps.locations",
    "apps.rides",
    "apps.orders",
    "apps.subscriptions",
    "apps.payments",
    "apps.reviews",
    "apps.chat",
    "apps.notifications",
    "apps.support",
    "apps.matching",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
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

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
if os.environ.get("DATABASE_URL"):
    DATABASES = {
        "default": dj_database_url.parse(
            os.environ["DATABASE_URL"],
            conn_max_age=int(os.environ.get("DATABASE_CONN_MAX_AGE", "60")),
            conn_health_checks=True,
        )
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("POSTGRES_DB", "taxitop"),
            "USER": os.environ.get("POSTGRES_USER", "taxitop"),
            "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
            "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
            "PORT": os.environ.get("POSTGRES_PORT", "5432"),
            "CONN_MAX_AGE": int(os.environ.get("DATABASE_CONN_MAX_AGE", "60")),
            "CONN_HEALTH_CHECKS": True,
        }
    }

if DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3":
    database_name = DATABASES["default"]["NAME"]
    if database_name and database_name != ":memory:" and not str(database_name).startswith("file:"):
        database_path = Path(database_name)
        if not database_path.is_absolute():
            DATABASES["default"]["NAME"] = BASE_DIR / database_path

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "users.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ---------------------------------------------------------------------------
# Cache / Celery
# ---------------------------------------------------------------------------
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
        "KEY_PREFIX": os.environ.get("CACHE_KEY_PREFIX", "taxitop"),
    }
}

CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", REDIS_URL)
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", REDIS_URL)
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TIMEZONE = "Asia/Tashkent"
CELERY_ENABLE_UTC = True
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_ALWAYS_EAGER = env_bool("CELERY_TASK_ALWAYS_EAGER", False)
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True

# ---------------------------------------------------------------------------
# Internationalization - the Django Admin is operated in Uzbek.
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "uz"
TIME_ZONE = os.environ.get("TIME_ZONE", "Asia/Tashkent")
USE_I18N = True
USE_TZ = True  # timezone aware datetimes everywhere

LANGUAGES = [
    ("uz", "Uzbek"),
    ("ru", "Russian"),
    ("en", "English"),
]

# ---------------------------------------------------------------------------
# Static & media files
# ---------------------------------------------------------------------------
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# ---------------------------------------------------------------------------
# Django REST Framework
# ---------------------------------------------------------------------------
API_PAGE_SIZE = int(os.environ.get("API_PAGE_SIZE", "20"))
API_MAX_PAGE_SIZE = int(os.environ.get("API_MAX_PAGE_SIZE", "100"))

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.TokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.OrderingFilter",
        "rest_framework.filters.SearchFilter",
    ],
    "DEFAULT_PAGINATION_CLASS": "apps.core.pagination.StandardPagination",
    "PAGE_SIZE": API_PAGE_SIZE,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "apps.core.exception_handler.business_exception_handler",
    "DEFAULT_THROTTLE_RATES": {
        "anon": os.environ.get("API_THROTTLE_RATE_ANON", "30/min"),
        "user": os.environ.get("API_THROTTLE_RATE_USER", "120/min"),
        "burst": os.environ.get("API_THROTTLE_RATE_BURST", "20/s"),
    },
    "DEFAULT_THROTTLE_CLASSES": [
        "apps.core.throttling.BurstScopedRateThrottle",
        "apps.core.throttling.AnonScopedRateThrottle",
        "apps.core.throttling.UserScopedRateThrottle",
    ],
    "DATETIME_FORMAT": "%Y-%m-%dT%H:%M:%S%z",
}

# ---------------------------------------------------------------------------
# drf-spectacular
# ---------------------------------------------------------------------------
SPECTACULAR_SETTINGS = {
    "TITLE": "TezTaxiTop API",
    "DESCRIPTION": (
        "Telegram based taxi marketplace API. Passengers search for rides, "
        "drivers publish trips, orders are matched, booked and completed."
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "SCHEMA_PATH_PREFIX": "/api/v1",
    "SORT_OPERATIONS": True,
    "TAGS": [
        {"name": "auth", "description": "Telegram registration and current user."},
        {"name": "users", "description": "User and driver profile management."},
        {"name": "vehicles", "description": "Driver vehicles."},
        {"name": "locations", "description": "Region / district / location catalogue."},
        {"name": "rides", "description": "Driver trips and passenger requests."},
        {"name": "orders", "description": "Seat booking and order lifecycle."},
        {"name": "subscriptions", "description": "Driver subscription plans and history."},
        {"name": "payments", "description": "Payment records and verification."},
        {"name": "reviews", "description": "Post-order ratings."},
        {"name": "chat", "description": "Order scoped messaging."},
        {"name": "notifications", "description": "In-app notification centre."},
        {"name": "support", "description": "Support tickets."},
        {"name": "matching", "description": "Deterministic trip matching."},
    ],
    "SWAGGER_UI_SETTINGS": {"persistAuthorization": True, "displayRequestDuration": True},
}

# ---------------------------------------------------------------------------
# Telegram integration (the bot itself lives in the `bot` package)
# ---------------------------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_BOT_USERNAME = os.environ.get("TELEGRAM_BOT_USERNAME", "")
TELEGRAM_WEBHOOK_URL = os.environ.get("TELEGRAM_WEBHOOK_URL", "")
TELEGRAM_WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")

# ---------------------------------------------------------------------------
# Payment providers
# ---------------------------------------------------------------------------
PAYMENT_PROVIDERS = {
    "CLICK": {
        "MERCHANT_ID": os.environ.get("PAYMENT_CLICK_MERCHANT_ID", ""),
        "SECRET_KEY": os.environ.get("PAYMENT_CLICK_SECRET_KEY", ""),
        "SERVICE_TOKEN": os.environ.get("PAYMENT_CLICK_SERVICE_TOKEN", ""),
    },
    "PAYME": {
        "MERCHANT_ID": os.environ.get("PAYMENT_PAYME_MERCHANT_ID", ""),
        "SECRET_KEY": os.environ.get("PAYMENT_PAYME_SECRET_KEY", ""),
    },
    "UZUM": {
        "MERCHANT_KEY": os.environ.get("PAYMENT_UZUM_MERCHANT_KEY", ""),
        "SECRET_KEY": os.environ.get("PAYMENT_UZUM_SECRET_KEY", ""),
    },
}

# ---------------------------------------------------------------------------
# Business rules consumed through `apps.core.conf`
# ---------------------------------------------------------------------------
TRIP_REQUIRES_ACTIVE_SUBSCRIPTION = env_bool("TRIP_REQUIRES_ACTIVE_SUBSCRIPTION", True)
TRIP_REQUIRES_VERIFIED_DRIVER = env_bool("TRIP_REQUIRES_VERIFIED_DRIVER", True)
TRIP_REQUIRES_VERIFIED_VEHICLE = env_bool("TRIP_REQUIRES_VERIFIED_VEHICLE", True)
SUBSCRIPTION_EXPIRING_WARNING_DAYS = int(os.environ.get("SUBSCRIPTION_EXPIRING_WARNING_DAYS", "3"))
PASSENGER_REQUEST_EXPIRY_HOURS = int(os.environ.get("PASSENGER_REQUEST_EXPIRY_HOURS", "6"))
TRIP_DEPARTURE_GRACE_MINUTES = int(os.environ.get("TRIP_DEPARTURE_GRACE_MINUTES", "60"))
MATCHING_TIME_WINDOW_HOURS = int(os.environ.get("MATCHING_TIME_WINDOW_HOURS", "6"))
MATCHING_MAX_RESULTS = int(os.environ.get("MATCHING_MAX_RESULTS", "20"))

# Periodic maintenance. Every task is idempotent, so a missed or duplicated
# run never corrupts data.
CELERY_BEAT_SCHEDULE = {
    # --- housekeeping (hourly) ---------------------------------------------
    "expire-subscriptions": {
        "task": "apps.subscriptions.tasks.expire_subscriptions_task",
        "schedule": timedelta(hours=1),
    },
    "expire-passenger-requests": {
        "task": "apps.rides.tasks.expire_passenger_requests_task",
        "schedule": timedelta(hours=1),
    },
    "expire-trips": {
        "task": "apps.rides.tasks.expire_trips_task",
        "schedule": timedelta(hours=1),
    },
    # --- notifications -----------------------------------------------------
    "dispatch-notifications": {
        "task": "apps.notifications.tasks.deliver_pending_notifications_task",
        "schedule": timedelta(minutes=1),
    },
    "notify-expiring-subscriptions": {
        "task": "apps.subscriptions.tasks.notify_expiring_subscriptions_task",
        "schedule": timedelta(hours=24),
    },
    "cleanup-old-notifications": {
        "task": "apps.notifications.tasks.cleanup_old_notifications_task",
        "schedule": timedelta(hours=24),
    },
    # --- matching ----------------------------------------------------------
    "refresh-matches": {
        "task": "apps.matching.tasks.refresh_all_matches_task",
        "schedule": timedelta(minutes=15),
    },
}

# ---------------------------------------------------------------------------
# Security (hardened in production settings)
# ---------------------------------------------------------------------------
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = False
X_FRAME_OPTIONS = "DENY"
SECURE_REFERRER_POLICY = "same-origin"
MESSAGE_STORAGE = "django.contrib.messages.storage.session.SessionStorage"
