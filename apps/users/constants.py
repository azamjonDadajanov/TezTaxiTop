"""User model domain constants."""

from __future__ import annotations

from django.db import models


class UserRole(models.TextChoices):
    """A single account may act as a passenger, a driver, or both.

    ``TextChoices`` values are the *stored* values, not the human readable
    labels, so switching a label never invalidates existing rows.
    """

    PASSENGER = "passenger", "Yo'lovchi"
    DRIVER = "driver", "Haydovchi"
    BOTH = "both", "Yo'lovchi va haydovchi"


#: Roles that are allowed to own a :class:`~apps.users.models.DriverProfile`.
DRIVER_ROLES: frozenset[str] = frozenset({UserRole.DRIVER, UserRole.BOTH})

#: Roles that are allowed to act as a passenger.
PASSENGER_ROLES: frozenset[str] = frozenset({UserRole.PASSENGER, UserRole.BOTH})
