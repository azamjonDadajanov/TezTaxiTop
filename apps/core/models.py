"""Abstract base models shared by every domain application."""

from __future__ import annotations

from decimal import Decimal

from django.db import models

#: Standard money precision used across the whole platform.
MONEY_MAX_DIGITS = 12
MONEY_DECIMAL_PLACES = 2
ZERO = Decimal("0.00")


class TimeStampedModel(models.Model):
    """Adds timezone aware ``created_at`` / ``updated_at`` timestamps.

    ``auto_now_add`` / ``auto_now`` always store aware datetimes because the
    project runs with ``USE_TZ = True``. ``created_at`` is indexed by default
    because almost every list view in the admin and API is ordered by it.
    """

    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        verbose_name="Yaratilgan vaqti",
        help_text="Yozma yaratilgan payt (UTC, vaqt zonasi bilan).",
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Yangilangan vaqti",
        help_text="Yozma oxirgi marta yangilangan payt (UTC, vaqt zonasi bilan).",
    )

    class Meta:
        abstract = True
