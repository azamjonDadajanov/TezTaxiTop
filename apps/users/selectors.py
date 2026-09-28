"""Read/query layer for the users app.

Selectors contain *only* ``filter``/``exclude``/``annotate`` chains. They never
create, update or delete anything, which keeps read rules reusable from the
API, the admin search fields and the Telegram bot.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Sequence

from django.db.models import Count, Q, QuerySet

from apps.users.constants import UserRole
from apps.users.models import DriverProfile, User

#: Fields that the Django admin may search by (name, phone, Telegram id, ...).
USER_SEARCH_FIELDS: Sequence[str] = (
    "id",
    "username",
    "first_name",
    "last_name",
    "phone_number",
    "telegram_id",
)

#: Fields that the Django admin may order by.
USER_ORDERING_FIELDS: Sequence[str] = (
    "id",
    "username",
    "first_name",
    "last_name",
    "phone_number",
    "telegram_id",
    "role",
    "is_active",
    "is_blocked",
    "created_at",
    "last_seen_at",
)


def get_user_queryset() -> QuerySet[User]:
    """Base queryset with the relations the UI needs."""
    return User.objects.select_related("driver_profile").all()


def get_active_users() -> QuerySet[User]:
    return get_user_queryset().active()


def get_user_by_id(user_id: int) -> User | None:
    return get_user_queryset().filter(pk=user_id).first()


def get_user_by_telegram_id(telegram_id: int) -> User | None:
    return get_user_queryset().filter(telegram_id=telegram_id).first()


def get_user_by_phone(phone_number: str) -> User | None:
    return get_user_queryset().filter(phone_number=phone_number).first()


def get_user_by_username(username: str) -> User | None:
    return get_user_queryset().filter(username=username).first()


def users_search(queryset: QuerySet[User], search_term: str | None) -> QuerySet[User]:
    """Free text search used by ``SearchFilter`` and the admin."""
    if not search_term:
        return queryset
    term = search_term.strip()
    return queryset.filter(
        Q(username__icontains=term)
        | Q(first_name__icontains=term)
        | Q(last_name__icontains=term)
        | Q(phone_number__icontains=term)
        | Q(telegram_id__icontains=term.replace("+", ""))
    )


def get_driver_profiles() -> QuerySet[DriverProfile]:
    return DriverProfile.objects.select_related("user")


def _count_vehicles() -> Count:
    """Vehicles count annotation (avoids an N+1 query in list endpoints)."""
    return Count("vehicles", distinct=True)


def get_driver_profile_queryset() -> QuerySet[DriverProfile]:
    return (
        DriverProfile.objects.select_related("user")
        .annotate(vehicles_count=_count_vehicles())
    )


def get_driver_profile_by_user(user: User) -> DriverProfile | None:
    return DriverProfile.objects.filter(user=user).first()


def get_verified_driver_profiles() -> QuerySet[DriverProfile]:
    return get_driver_profile_queryset().filter(is_verified=True, user__is_blocked=False)


def get_driver_profiles_ordered_by_rating() -> QuerySet[DriverProfile]:
    return get_verified_driver_profiles().order_by("-rating", "user_id")


def get_top_rated_drivers(limit: int = 10) -> list[DriverProfile]:
    return list(get_driver_profiles_ordered_by_rating()[:limit])


def get_drivers_search(queryset: QuerySet[DriverProfile], search_term: str | None) -> QuerySet[DriverProfile]:
    if not search_term:
        return queryset
    term = search_term.strip()
    return queryset.filter(
        Q(user__first_name__icontains=term)
        | Q(user__last_name__icontains=term)
        | Q(user__username__icontains=term)
        | Q(user__phone_number__icontains=term)
        | Q(user__telegram_id__icontains=term.replace("+", ""))
    )


def get_users_with_role(role: str) -> QuerySet[User]:
    return get_user_queryset().filter(role=role)


def get_blocked_users() -> QuerySet[User]:
    return get_user_queryset().filter(is_blocked=True)


def get_minimum_rating(rating: Decimal) -> QuerySet[DriverProfile]:
    return get_driver_profile_queryset().filter(rating__gte=rating)


def has_role(user: User, *roles: str) -> bool:
    return user.role in roles or user.role == UserRole.BOTH
