"""Rate limiting strategies.

DRF throttle scopes are configured in ``REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]``
and backed by the Redis cache, so counters are shared between all web workers.

* ``anon``   - IP based, protects unauthenticated endpoints (registration, ...)
* ``user``   - authenticated user based, fair per-account quota
* ``burst``  - short term protection against request floods
"""

from __future__ import annotations

from rest_framework.throttling import AnonRateThrottle, UserRateThrottle


class AnonScopedRateThrottle(AnonRateThrottle):
    """IP based throttle applied to anonymous requests."""

    scope = "anon"


class UserScopedRateThrottle(UserRateThrottle):
    """User id based throttle applied to authenticated requests."""

    scope = "user"


class BurstScopedRateThrottle(UserRateThrottle):
    """Very short window throttle that stops request floods."""

    scope = "burst"
