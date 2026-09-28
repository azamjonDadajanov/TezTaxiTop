"""Production settings: strict security, caching, real email delivery."""

from __future__ import annotations

import os

from .base import *  # noqa: F401,F403
from .base import env_bool, env_list

DEBUG = False

ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "example.uz,www.example.uz")

# --- Mandatory secret ------------------------------------------------------
SECRET_KEY = os.environ.get("SECRET_KEY", "")
if not SECRET_KEY or SECRET_KEY == "insecure-development-key-do-not-use-in-production":
    raise RuntimeError("SECRET_KEY environment variable must be set for production.")

# --- HTTPS / cookies -------------------------------------------------------
SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"

# --- Static / media --------------------------------------------------------
STATICFILES_STORAGE = "django.contrib.staticfiles.storage.StaticFilesStorage"

# --- Email -----------------------------------------------------------------
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = os.environ.get("EMAIL_HOST", "")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "no-reply@taxitop.uz")

# --- Celery: never run tasks inline ---------------------------------------
CELERY_TASK_ALWAYS_EAGER = False
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True

# --- API throttling is mandatory in production -----------------------------
REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"].update(
    {
        "anon": env_list("API_THROTTLE_RATE_ANON", "30/min")[0],
        "user": env_list("API_THROTTLE_RATE_USER", "120/min")[0],
        "burst": env_list("API_THROTTLE_RATE_BURST", "20/s")[0],
    }
)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{asctime} {levelname} {name} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {"handlers": ["console"], "level": env_list("LOG_LEVEL", "INFO")[0]},
    "loggers": {
        "django.db.backends": {"level": "WARNING", "handlers": ["console"], "propagate": False},
    },
}
