"""Write/business layer for the users app.

Every state change of a user or a driver profile goes through this module so
that the Telegram bot and the REST API share exactly the same rules.

Transaction policy
------------------
* Simple single-row writes run inside ``transaction.atomic()`` to keep the
  "update row + dependent row" pairs (for example role change + profile
  creation) atomic.
* :func:`increment_driver_trip_statistics` uses ``F()`` expressions, which
  makes it safe under concurrency without an explicit row lock.
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import F
from django.db.models.functions import Greatest
from django.utils import timezone

from apps.core.exceptions import (
    BusinessValidationError,
    NotADriver,
    ResourceNotFound,
    UserIsBlocked,
)
from apps.core.validators import normalize_phone_number
from apps.users.constants import DRIVER_ROLES, UserRole
from apps.users.models import DriverProfile, User
from apps.users.selectors import get_user_by_telegram_id

logger = logging.getLogger(__name__)

#: Ratings a driver can hold, as Decimal (never float).
MIN_RATING = Decimal("1.00")
MAX_RATING = Decimal("5.00")
DEFAULT_RATING = Decimal("5.00")


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------
@transaction.atomic
def get_or_create_user_from_telegram(
    *,
    telegram_id: int,
    username: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    phone_number: str | None = None,
    language_code: str | None = None,
) -> tuple[User, bool]:
    """Return ``(user, created)`` for a Telegram identity.

    The very first contact of a Telegram user registers the account; later
    contacts refresh the mutable Telegram fields (name and username may change
    inside Telegram). ``telegram_id`` is the lookup key, never the username.
    """
    if not telegram_id:
        raise BusinessValidationError("Telegram ID majburiy.")

    user = get_user_by_telegram_id(telegram_id)
    if user is None:
        username = _unique_username(username or f"tg{telegram_id}")
        user = User(
            telegram_id=telegram_id,
            username=username,
            first_name=first_name or "",
            last_name=last_name or "",
            phone_number=normalize_phone_number(phone_number),
            role=UserRole.PASSENGER,
            last_seen_at=timezone.now(),
            language_code=language_code or "uz",
        )
        user.set_unusable_password()
        try:
            user.save(force_insert=True)
        except IntegrityError:
            # A concurrent /start from the same Telegram user.
            transaction.set_rollback(False)
            user = get_user_by_telegram_id(telegram_id)
            if user is None:  # pragma: no cover - defensive
                raise
            return user, False
        logger.info("Yangi Telegram foydalanuvchi ro'yxatdan o'tdi: %s", user.telegram_id)
        return user, True

    _sync_telegram_fields(
        user,
        username=username,
        first_name=first_name,
        last_name=last_name,
        language_code=language_code,
    )
    if phone_number and not user.phone_number:
        user.phone_number = normalize_phone_number(phone_number)
    user.last_seen_at = timezone.now()
    user.save(
        update_fields=[
            "username",
            "first_name",
            "last_name",
            "phone_number",
            "language_code",
            "last_seen_at",
            "updated_at",
        ]
    )
    return user, False


def _unique_username(preferred: str) -> str:
    """Return a free Django username derived from the Telegram username."""
    base = (preferred or "").strip().replace(" ", "_") or "user"
    candidate = base[:140]
    suffix = 1
    while User.objects.filter(username=candidate).exists():
        suffix += 1
        candidate = f"{base[: 140 - len(str(suffix)) - 1]}_{suffix}"
    return candidate


def _sync_telegram_fields(
    user: User,
    *,
    username: str | None,
    first_name: str | None,
    last_name: str | None,
    language_code: str | None,
) -> None:
    """Refresh Telegram owned fields, keeping manually edited phone intact."""
    changed = False
    if first_name and user.first_name != first_name:
        user.first_name = first_name
        changed = True
    if last_name is not None and user.last_name != last_name:
        user.last_name = last_name
        changed = True
    if username and user.username != username:
        new_username = _unique_username(username)
        if new_username != user.username:
            user.username = new_username
            changed = True
    if language_code and user.language_code != language_code:
        user.language_code = language_code
        changed = True
    if changed:
        user.save(update_fields=["first_name", "last_name", "username", "language_code", "updated_at"])


@transaction.atomic
def create_user(
    *,
    username: str,
    telegram_id: int | None = None,
    first_name: str = "",
    last_name: str = "",
    phone_number: str = "",
    role: str = UserRole.PASSENGER,
    password: str | None = None,
) -> User:
    """Create a user explicitly (admin panel, tests, staff accounts)."""
    user = User(
        username=username,
        telegram_id=telegram_id,
        first_name=first_name,
        last_name=last_name,
        phone_number=normalize_phone_number(phone_number),
        role=role,
    )
    if password:
        user.set_password(password)
    else:
        user.set_unusable_password()
    user.full_clean(exclude=["password"], validate_unique=False)
    user.save()
    return user


@transaction.atomic
def update_user_profile(
    user: User,
    *,
    first_name: str | None = None,
    last_name: str | None = None,
    phone_number: str | None = None,
    language_code: str | None = None,
) -> User:
    """Update mutable profile fields. ``role`` is intentionally not accepted."""
    if first_name is not None:
        user.first_name = first_name.strip()
    if last_name is not None:
        user.last_name = last_name.strip()
    if phone_number is not None:
        user.phone_number = normalize_phone_number(phone_number)
    if language_code is not None:
        user.language_code = language_code
    user.full_clean(exclude=["telegram_id", "role", "password"], validate_unique=False)
    user.save(
        update_fields=["first_name", "last_name", "phone_number", "language_code", "updated_at"]
    )
    return user


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
@transaction.atomic
def set_user_role(user: User, role: str) -> User:
    """Set the platform role, keeping ``DriverProfile`` consistent.

    * Switching to a passenger-only role deletes the driver profile **only**
      when it has no business history (no vehicles, no trips). Otherwise the
      role change is rejected so historical data stays intact.
    """
    if role not in UserRole.values:
        raise BusinessValidationError(f"Noma'lum rol: {role}")

    user.role = role
    user.save(update_fields=["role", "updated_at"])

    if role in DRIVER_ROLES:
        create_driver_profile(user)
    else:
        _detach_driver_profile_if_unused(user)
    return user


def _detach_driver_profile_if_unused(user: User) -> None:
    """Remove an empty driver profile when the user stops being a driver."""
    profile = getattr(user, "driver_profile", None)
    if profile is None:
        return
    if profile.vehicles.exists() or profile.trips.exists():
        raise BusinessValidationError(
            "Haydovchi profili mavjud tarixiy ma'lumotga ega, ro'lini o'zgartirib bo'lmaydi."
        )
    profile.delete()


# ---------------------------------------------------------------------------
# Moderation
# ---------------------------------------------------------------------------
@transaction.atomic
def block_user(user: User, *, is_active: bool = False) -> User:
    """Block a user without deleting any historical data (data retention)."""
    user.is_blocked = True
    user.is_active = is_active
    user.save(update_fields=["is_blocked", "is_active", "updated_at"])
    return user


@transaction.atomic
def unblock_user(user: User) -> User:
    user.is_blocked = False
    user.is_active = True
    user.save(update_fields=["is_blocked", "is_active", "updated_at"])
    return user


@transaction.atomic
def touch_last_seen(user: User, moment: datetime | None = None) -> User:
    """Record the last time the user was seen (used for driver statistics)."""
    user.last_seen_at = moment or timezone.now()
    user.save(update_fields=["last_seen_at", "updated_at"])
    return user


# ---------------------------------------------------------------------------
# Driver profile
# ---------------------------------------------------------------------------
@transaction.atomic
def create_driver_profile(user: User, *, bio: str = "") -> DriverProfile:
    """Create the driver profile and promote the role when needed."""
    if user.role not in DRIVER_ROLES:
        user.role = UserRole.DRIVER
        user.save(update_fields=["role", "updated_at"])

    profile, created = DriverProfile.objects.get_or_create(user=user, defaults={"bio": bio})
    return profile


@transaction.atomic
def update_driver_profile(profile: DriverProfile, *, bio: str | None = None) -> DriverProfile:
    if bio is not None:
        profile.bio = bio.strip()
    profile.full_clean(exclude=["user"], validate_unique=False)
    profile.save(update_fields=["bio", "updated_at"])
    return profile


@transaction.atomic
def verify_driver_profile(profile: DriverProfile, *, verified: bool = True) -> DriverProfile:
    """Admin only action: grant or revoke driver verification."""
    profile.is_verified = verified
    profile.verified_at = timezone.now() if verified else None
    profile.save(update_fields=["is_verified", "verified_at", "updated_at"])
    return profile


@transaction.atomic
def register_as_driver(user: User, *, bio: str = "") -> DriverProfile:
    """Turn a passenger account into a driver account (keeps history)."""
    if user.is_blocked:
        raise UserIsBlocked()
    profile = getattr(user, "driver_profile", None)
    if profile is not None:
        return profile
    return create_driver_profile(user, bio=bio)


def get_required_driver_profile(user: User) -> DriverProfile:
    """Return the driver profile or raise :class:`NotADriver`."""
    profile = getattr(user, "driver_profile", None)
    if profile is None:
        raise NotADriver()
    return profile


@transaction.atomic
def get_required_user(user_id: int) -> User:
    user = User.objects.filter(pk=user_id).first()
    if user is None:
        raise ResourceNotFound("Foydalanuvchi topilmadi.")
    return user


# ---------------------------------------------------------------------------
# Driver statistics
# ---------------------------------------------------------------------------
@transaction.atomic
def increment_driver_trip_statistics(profile: DriverProfile, *, cancelled: bool = False) -> DriverProfile:
    """Update trip counters atomically using ``F()`` expressions.

    ``F()`` expressions translate into ``SET x = x + 1`` in SQL, so concurrent
    calls cannot lose an increment (no read-modify-write race).
    """
    update_fields = ["total_trips", "updated_at"]
    profile.total_trips = F("total_trips") + 1
    if cancelled:
        profile.cancelled_trips = F("cancelled_trips") + 1
        update_fields.append("cancelled_trips")
    profile.save(update_fields=update_fields)
    profile.refresh_from_db(fields=["total_trips", "cancelled_trips", "updated_at"])
    return profile


@transaction.atomic
def increment_completed_trips(profile: DriverProfile) -> DriverProfile:
    """Increment the completed counter, never exceeding ``total_trips``.

    ``Greatest`` keeps the database invariant
    ``completed_trips <= total_trips`` true even when the trip counter has not
    been incremented yet, so a race between "trip created" and "trip completed"
    can never raise an IntegrityError.
    """
    DriverProfile.objects.filter(pk=profile.pk).update(
        completed_trips=F("completed_trips") + 1,
        total_trips=Greatest(F("total_trips"), F("completed_trips") + 1),
        updated_at=timezone.now(),
    )
    profile.refresh_from_db(fields=["completed_trips", "total_trips", "updated_at"])
    return profile


@transaction.atomic
def set_driver_rating(
    profile: DriverProfile,
    *,
    rating: Decimal,
    rating_count: int | None = None,
) -> DriverProfile:
    """Persist an externally computed rating (see ``apps.reviews.services``)."""
    if not MIN_RATING <= rating <= MAX_RATING:
        raise BusinessValidationError("Reyting 1.00 va 5.00 orasida bo'lishi kerak.")
    fields = ["rating", "updated_at"]
    profile.rating = rating
    if rating_count is not None:
        profile.rating_count = rating_count
        fields.append("rating_count")
    profile.save(update_fields=fields)
    return profile


def get_driver_rating_for_admin(profile: DriverProfile) -> Decimal:
    return profile.rating
