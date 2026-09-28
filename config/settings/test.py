"""Test settings: fast, deterministic, isolated from external services.

The reference database is **PostgreSQL** (that is what production uses, and the
partial unique indexes / check constraints of this project must be verified
there). ``DATABASE_URL`` may still be set to run the suite against another
backend - handy on a laptop without a PostgreSQL server.
"""

from __future__ import annotations

import os

import dj_database_url

from .base import *  # noqa: F401,F403
from .base import REST_FRAMEWORK

DEBUG = False
ALLOWED_HOSTS = ["*"]

# Hashing passwords is a hot path in tests - use the cheapest hasher.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

if os.environ.get("DATABASE_URL"):
    DATABASES = {"default": dj_database_url.parse(os.environ["DATABASE_URL"], conn_max_age=0)}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("POSTGRES_TEST_DB", "test_taxitop"),
            "USER": os.environ.get("POSTGRES_USER", "taxitop"),
            "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
            "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
            "PORT": os.environ.get("POSTGRES_PORT", "5432"),
            "TEST": {"NAME": os.environ.get("POSTGRES_TEST_DB", "test_taxitop")},
        }
    }

# An in-memory cache keeps throttle counters out of Redis during tests.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "taxitop-tests",
    }
}

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# Tests must never be throttled by the production rate limits.
REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["anon"] = "1000/min"
REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["user"] = "1000/min"
REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["burst"] = "1000/s"
