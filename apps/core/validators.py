"""Shared field validators.

They are used both by Django ``CheckConstraint``-adjacent model validation and
by DRF serializers, so the same rule is enforced no matter which entry point a
client uses (Telegram bot, REST API, Django Admin).
"""

from __future__ import annotations

import re
from datetime import date

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

#: Accepts `+998901234567`, `998901234567` and local `901234567` formats.
PHONE_NUMBER_REGEX = re.compile(r"^\+?[0-9]{9,15}$")

#: Uzbekistan country code, used to normalise local phone numbers.
UZBEKISTON_COUNTRY_CODE = "+998"


def validate_phone_number(value: str) -> None:
    """Ensure the value looks like an international phone number."""
    if not value:
        return
    if not PHONE_NUMBER_REGEX.match(value):
        raise ValidationError(
            _("Telefon raqami noto'g'ri. Misol: +998901234567"),
            code="invalid_phone",
        )


def normalize_phone_number(value: str | None) -> str:
    """Normalise a phone number to the ``+998XXXXXXXXX`` form.

    Empty / ``None`` input is returned unchanged so the field can stay blank.
    """
    if not value:
        return ""
    digits = re.sub(r"\D", "", value)
    if not digits:
        return ""
    if digits.startswith("998") and len(digits) == 12:
        return f"{UZBEKISTON_COUNTRY_CODE}{digits[3:]}"
    if len(digits) == 9:
        return f"{UZBEKISTON_COUNTRY_CODE}{digits}"
    return value


def validate_vehicle_year(value: int) -> None:
    """A vehicle year must be plausible (1990 .. next year)."""
    current_year = date.today().year
    if value < 1990 or value > current_year + 1:
        raise ValidationError(
            _("Avtomobil yili 1990 va %(next_year)d orasida bo'lishi kerak.") % {"next_year": current_year + 1},
            code="invalid_vehicle_year",
        )


def validate_latitude(value) -> None:
    """Latitude must be within [-90, 90]."""
    if value is None:
        return
    if not (-90 <= float(value) <= 90):
        raise ValidationError(_("Kenglik -90 va 90 orasida bo'lishi kerak."), code="invalid_latitude")


def validate_longitude(value) -> None:
    """Longitude must be within [-180, 180]."""
    if value is None:
        return
    if not (-180 <= float(value) <= 180):
        raise ValidationError(
            _("Uzunlik -180 va 180 orasida bo'lishi kerak."), code="invalid_longitude"
        )


def validate_non_blank(value: str) -> None:
    """Reject strings that are empty or whitespace only."""
    if value is None or not str(value).strip():
        raise ValidationError(_("Qiymat bo'sh bo'lishi mumkin emas."), code="blank")
