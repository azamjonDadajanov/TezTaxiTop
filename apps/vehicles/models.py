"""Vehicle model.

Design decisions
----------------
* A vehicle is attached to a :class:`~apps.users.models.DriverProfile` (not to
  ``User``) so that "who is allowed to drive" and "what the car is" are the
  same decision, and a blocked/removed driver profile can never own a car.
* ``plate_number`` is unique platform wide - it is the natural business key used
  by admin verification and by the trip search.
* ``seats_count`` is the *total* number of seats including the driver seat, so
  the number of seats that can be sold is ``seats_count - 1``. The property
  :attr:`Vehicle.seats_for_passengers` is the single place that knows this.
* ``DriverProfile`` never stores vehicle columns: one driver, many vehicles.
"""

from __future__ import annotations

import re

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel
from apps.core.validators import validate_vehicle_year

#: Minimum realistic year for a taxi in Uzbekistan.
MIN_VEHICLE_YEAR = 1990

#: A car has between 1 and 20 physical seats.
MIN_SEATS = 1
MAX_SEATS = 20


#: Canonical Uzbek plate shapes (after removing spaces and upper-casing).
PLATE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # 01B 777AA - region digits, series letter, 3 digits, 2 letters (most common)
    (re.compile(r"^(\d{2}[A-Z])(\d{3}[A-Z]{2})$"), r"\1 \2"),
    # 01 777 AA - region digits, 3 digits, 2 letters
    (re.compile(r"^(\d{2})(\d{3}[A-Z]{2})$"), r"\1 \2"),
    # 01 777 AAA - region digits, 3 digits, 3 letters
    (re.compile(r"^(\d{2})(\d{3}[A-Z]{3})$"), r"\1 \2"),
)


def normalize_plate_number(value: str) -> str:
    """Normalise a plate to a canonical upper-case, space separated form.

    ``01 b 777 aa`` -> ``01B 777AA``. Normalising on write keeps the unique
    constraint meaningful (otherwise ``01B777AA`` and ``01b777aa`` would be two
    different cars).
    """
    if not value:
        return ""
    raw = value.strip().upper()
    compact = "".join(character for character in raw if character.isalnum())
    for pattern, replacement in PLATE_PATTERNS:
        if pattern.match(compact):
            return pattern.sub(replacement, compact)
    return compact


class Vehicle(TimeStampedModel):
    """A car registered to a driver."""

    driver = models.ForeignKey(
        "users.DriverProfile",
        on_delete=models.PROTECT,
        related_name="vehicles",
        verbose_name="Haydovchi",
        help_text="Avtomobil egasi. Profil o'chirilsa avtomobil ham o'chirilmaydi.",
    )
    brand = models.CharField(verbose_name="Brend", max_length=60, help_text="Lancia, Chevrolet, Hyundai ...")
    model = models.CharField(verbose_name="Model", max_length=60, help_text="Doblo, Nexia, Accent ...")
    color = models.CharField(verbose_name="Rang", max_length=40, help_text="Oq, qora, kumush ...")
    plate_number = models.CharField(
        verbose_name="Davlat raqami",
        max_length=15,
        unique=True,
        help_text="O'zbekiston davlat raqami, masalan: 01B 777AA.",
    )
    year = models.PositiveSmallIntegerField(
        verbose_name="Ishlab chiqarilgan yili",
        validators=[validate_vehicle_year, MinValueValidator(MIN_VEHICLE_YEAR)],
    )
    seats_count = models.PositiveSmallIntegerField(
        verbose_name="O'rindiq soni",
        default=4,
        validators=[MinValueValidator(MIN_SEATS), MaxValueValidator(MAX_SEATS)],
        help_text="Jami o'rindiq soni (haydovchi o'rni ham hisobga olinadi).",
    )
    is_active = models.BooleanField(
        verbose_name="Faol",
        default=True,
        db_index=True,
        help_text="Faol emas avtomobil bilan yo'lov yaratib bo'lmaydi.",
    )
    is_verified = models.BooleanField(
        verbose_name="Tasdiqlangan",
        default=False,
        db_index=True,
        help_text="Administrator tomonidan tasdiqlangan. Faqat tasdiqlangan mashina ishlatiladi.",
    )
    verified_at = models.DateTimeField(verbose_name="Tasdiqlangan vaqti", null=True, blank=True)
    photo = models.ImageField(
        verbose_name="Rasm",
        upload_to="vehicles/%Y/%m/",
        null=True,
        blank=True,
        help_text="Avtomobil rasmi (ixtiyoriy).",
    )
    notes = models.CharField(verbose_name="Izoh", max_length=255, blank=True, default="")

    class Meta:
        verbose_name = "Avtomobil"
        verbose_name_plural = "Avtomobillar"
        ordering = ("-created_at",)
        indexes = [
            # `plate_number` already has a unique index from `unique=True`.
            models.Index(fields=("driver", "is_active"), name="vehicle_driver_active_idx"),
            models.Index(fields=("driver", "is_verified"), name="vehicle_driver_verified_idx"),
            models.Index(fields=("is_active", "is_verified"), name="vehicle_status_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(seats_count__gte=MIN_SEATS) & models.Q(seats_count__lte=MAX_SEATS),
                name="vehicle_seats_count_range",
            ),
            models.CheckConstraint(
                condition=models.Q(year__gte=MIN_VEHICLE_YEAR),
                name="vehicle_year_minimum",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.brand} {self.model} ({self.plate_number})"

    def clean(self) -> None:
        super().clean()
        self.plate_number = normalize_plate_number(self.plate_number)
        if not self.plate_number:
            raise ValidationError({"plate_number": _("Davlat raqami majburiy.")})

    def save(self, *args, **kwargs) -> None:
        self.plate_number = normalize_plate_number(self.plate_number)
        super().save(*args, **kwargs)

    # -- helpers (small, non-business) ---------------------------------------
    @property
    def seats_for_passengers(self) -> int:
        """Seats that can actually be sold (total seats minus the driver)."""
        return max(0, self.seats_count - 1)

    @property
    def is_usable_for_trip(self) -> bool:
        """Whether the car may be attached to a published trip."""
        return self.is_active and self.is_verified

    @property
    def display_name(self) -> str:
        return f"{self.brand} {self.model} - {self.plate_number}"
