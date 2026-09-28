"""Settings package entry point.

Every environment module (``development``, ``test``, ``production``) imports
from :mod:`config.settings.base` and only overrides what is genuinely
environment specific. Keeping this logic here means the project always starts
with a deterministic default instead of an ``ImproperlyConfigured`` error.
"""

from __future__ import annotations

import os

BASE_ENVIRONMENT = "development"
TEST_ENVIRONMENT = "test"
PRODUCTION_ENVIRONMENT = "production"

_VALID_ENVIRONMENTS = {
    BASE_ENVIRONMENT,
    TEST_ENVIRONMENT,
    PRODUCTION_ENVIRONMENT,
}


def get_settings_module() -> str:
    """Return the settings module requested by the environment.

    An unknown value falls back to development so that a typo can never leave
    the project in a silently misconfigured state.
    """
    requested = os.environ.get("DJANGO_SETTINGS_MODULE", "")
    environment = requested.rsplit(".", 1)[-1] if requested else BASE_ENVIRONMENT
    if environment not in _VALID_ENVIRONMENTS:
        environment = BASE_ENVIRONMENT
    return f"config.settings.{environment}"


__all__ = [
    "BASE_ENVIRONMENT",
    "TEST_ENVIRONMENT",
    "PRODUCTION_ENVIRONMENT",
    "get_settings_module",
]
