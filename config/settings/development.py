"""Development settings: verbose, local tooling, no hardening required."""

from __future__ import annotations

from .base import *  # noqa: F401,F403
from .base import BASE_DIR, env_bool

DEBUG = env_bool("DEBUG", True)

ALLOWED_HOSTS = ["*"] if DEBUG else ["localhost", "127.0.0.1"]

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Console e-mail is used in development instead of a real SMTP server.
DEFAULT_FROM_EMAIL = "no-reply@taxitop.uz"

# Local SQLite fallback keeps `manage.py` usable before PostgreSQL is running.
# Set DATABASE_URL to point at PostgreSQL for anything resembling production.
if not __import__("os").environ.get("DATABASE_URL") and env_bool("DEV_SQLITE", False):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "taxitop-dev",
    }
}

CELERY_TASK_ALWAYS_EAGER = env_bool("CELERY_TASK_ALWAYS_EAGER", True)
CELERY_TASK_EAGER_PROPAGATES = True

# Never enforce HTTPS in local development.
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_SSL_REDIRECT = False
