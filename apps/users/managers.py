"""Custom managers for the user model."""

from __future__ import annotations

from typing import Any

from django.contrib.auth.base_user import BaseUserManager
from django.db.models import Q, QuerySet


class UserQuerySet(QuerySet):
    """Reusable querysets that keep the "what is visible" rules in one place."""

    def active(self) -> "UserQuerySet":
        """Active, non-blocked accounts."""
        return self.filter(is_active=True, is_blocked=False)

    def drivers(self) -> "UserQuerySet":
        """Accounts that may act as a driver."""
        return self.filter(role__in=("driver", "both"))

    def passengers(self) -> "UserQuerySet":
        """Accounts that may act as a passenger."""
        return self.filter(role__in=("passenger", "both"))

    def search(self, term: str) -> "UserQuerySet":
        """Search across name, username, phone and Telegram id."""
        if not term:
            return self
        return self.filter(
            Q(first_name__icontains=term)
            | Q(last_name__icontains=term)
            | Q(username__icontains=term)
            | Q(phone_number__icontains=term)
            | Q(telegram_id__icontains=term.replace("+", ""))
        )


class UserManager(BaseUserManager):
    """Manager that understands Telegram accounts.

    ``username`` stays the Django login field (Telegram usernames are unique but
    optional), while ``telegram_id`` is the real platform identity.
    """

    use_in_migrations = True

    def get_queryset(self) -> QuerySet:
        return UserQuerySet(self.model, using=self._db)

    def _create_user(self, username: str, email: str | None, password: str | None, **extra: Any):
        if not username:
            raise ValueError("Username talab qilinadi.")
        user = self.model(
            username=username,
            email=self.normalize_email(email) if email else "",
            **extra,
        )
        if password:
            user.set_password(password)
        else:
            # Telegram users authenticate through their Telegram id, not a password.
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_user(self, username: str, email: str | None = None, password: str | None = None, **extra: Any):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(username, email, password, **extra)

    def create_superuser(self, username: str, email: str | None = None, password: str | None = None, **extra: Any):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("is_active", True)
        if extra.get("is_staff") is not True:
            raise ValueError("Superuserga is_staff=True berish shart.")
        if extra.get("is_superuser") is not True:
            raise ValueError("Superuserga is_superuser=True berish shart.")
        return self._create_user(username, email, password, **extra)

    def get_by_telegram_id(self, telegram_id: int):
        """Return the account owning ``telegram_id`` or ``None``."""
        return self.filter(telegram_id=telegram_id).first()

    def get_queryable(self) -> UserQuerySet:
        return self.get_queryset()
