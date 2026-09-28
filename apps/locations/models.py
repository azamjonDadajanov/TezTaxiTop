"""Region / District / Location catalogue.

Design decisions
----------------
* The hierarchy ``Region -> District -> Location`` mirrors the Uzbek
  administrative division, which is what drivers and passengers actually say
  ("Toshkent viloyati, Zangiota tumani, Qorasuv MFY").
* Coordinates are ``DecimalField(max_digits=9, decimal_places=6)`` - that is
  ~11 cm of precision, more than enough, and it keeps the value exact for
  matching maths. PostGIS/GeoDjango is deliberately **not** required for this
  first implementation; a ``lat``/``lng`` pair is enough for the deterministic
  matcher and leaves room to add a ``PointField`` later.
* Names are unique per parent (case-insensitively normalised at write time) so
  that the bot's free-text lookup can use ``get_or_create`` safely.
* ``on_delete=PROTECT`` everywhere: a district with locations must never be
  deleted while trips reference it.
"""

from __future__ import annotations

from django.db import models
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel
from apps.core.validators import validate_latitude, validate_longitude

#: Decimal precision for geographic coordinates.
COORDINATE_MAX_DIGITS = 9
COORDINATE_DECIMAL_PLACES = 6


def normalize_name(value: str) -> str:
    """Trim and collapse whitespace so ``" Toshkent  viloyati "`` == ``"Toshkent viloyati"``."""
    return " ".join(str(value or "").split())


class Region(TimeStampedModel):
    """Top level administrative unit (viloyat / shahar)."""

    name = models.CharField(
        verbose_name="Nomi",
        max_length=120,
        unique=True,
        help_text="Masalan: Toshkent viloyati, Toshkent shahri, Samarqand viloyati.",
    )
    code = models.CharField(
        verbose_name="Kodi",
        max_length=20,
        blank=True,
        default="",
        help_text="Ixtiyoriy tashqi kod (ixtiyoriy).",
    )
    is_active = models.BooleanField(
        verbose_name="Faol",
        default=True,
        db_index=True,
        help_text="Faol bo'lmagan viloyat yangi manzil tanlashda ko'rinmaydi.",
    )

    class Meta:
        verbose_name = "Viloyat / Shahar"
        verbose_name_plural = "Viloyat / Shaharlar"
        ordering = ("name",)
        constraints = [
            # Case insensitive uniqueness: "Toshkent" and "toshkent" are the same
            # region, therefore the comparison happens on the lowered column.
            models.UniqueConstraint(
                Lower("name"),
                name="uniq_region_name_ci",
                violation_error_message="Bunday nomli viloyat allaqachon mavjud.",
            ),
        ]

    def __str__(self) -> str:
        return self.name

    def clean(self) -> None:
        super().clean()
        self.name = normalize_name(self.name)

    def save(self, *args, **kwargs) -> None:
        self.name = normalize_name(self.name)
        super().save(*args, **kwargs)


class District(TimeStampedModel):
    """Second level administrative unit (tuman / shaharcha)."""

    region = models.ForeignKey(
        Region,
        on_delete=models.PROTECT,
        related_name="districts",
        verbose_name="Viloyat / Shahar",
    )
    name = models.CharField(
        verbose_name="Nomi",
        max_length=120,
        help_text="Masalan: Zangiota tumani, Sergeli tumani.",
    )
    is_active = models.BooleanField(verbose_name="Faol", default=True, db_index=True)

    class Meta:
        verbose_name = "Tuman"
        verbose_name_plural = "Tumanlar"
        # Model level ``ordering`` may not span a JOIN, so districts are ordered
        # by name here; the admin adds the region column explicitly.
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(
                fields=("region", "name"),
                name="uniq_district_name_per_region",
                violation_error_message="Bu viloyatda bunday nomli tuman mavjud.",
            ),
        ]
        indexes = [models.Index(fields=("region", "is_active"), name="district_region_active_idx")]

    def __str__(self) -> str:
        return f"{self.name} ({self.region.name})"

    def clean(self) -> None:
        super().clean()
        self.name = normalize_name(self.name)

    def save(self, *args, **kwargs) -> None:
        self.name = normalize_name(self.name)
        super().save(*args, **kwargs)

    @property
    def full_name(self) -> str:
        return f"{self.region.name}, {self.name}"


class Location(TimeStampedModel):
    """A concrete pickup/dropoff point: city, town or village plus coordinates."""

    district = models.ForeignKey(
        District,
        on_delete=models.PROTECT,
        related_name="locations",
        verbose_name="Tuman",
    )
    name = models.CharField(
        verbose_name="Nomi",
        max_length=180,
        help_text="Shahar, tuman markazi yoki MFY nomi. Masalan: Toshkent shahri, Chirchiq.",
    )
    latitude = models.DecimalField(
        verbose_name="Kenglik (lat)",
        max_digits=COORDINATE_MAX_DIGITS,
        decimal_places=COORDINATE_DECIMAL_PLACES,
        validators=[validate_latitude],
        help_text="-90 .. 90 orasida.",
    )
    longitude = models.DecimalField(
        verbose_name="Uzunlik (lng)",
        max_digits=COORDINATE_MAX_DIGITS,
        decimal_places=COORDINATE_DECIMAL_PLACES,
        validators=[validate_longitude],
        help_text="-180 .. 180 orasida.",
    )
    address = models.CharField(
        verbose_name="Aniq manzil",
        max_length=255,
        blank=True,
        default="",
        help_text="Ko'cha, uy, mo'ljal. Ixtiyoriy.",
    )
    is_active = models.BooleanField(verbose_name="Faol", default=True, db_index=True)

    class Meta:
        verbose_name = "Manzil"
        verbose_name_plural = "Manzillar"
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(
                fields=("district", "name"),
                name="uniq_location_name_per_district",
                violation_error_message="Bu tumanda bunday nomli manzil mavjud.",
            ),
            models.CheckConstraint(
                condition=models.Q(latitude__gte=-90) & models.Q(latitude__lte=90),
                name="location_latitude_range",
            ),
            models.CheckConstraint(
                condition=models.Q(longitude__gte=-180) & models.Q(longitude__lte=180),
                name="location_longitude_range",
            ),
        ]
        indexes = [
            models.Index(fields=("district", "is_active"), name="location_district_active_idx"),
            models.Index(fields=("name",), name="location_name_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.name} - {self.district.full_name}"

    def clean(self) -> None:
        super().clean()
        self.name = normalize_name(self.name)
        self.address = str(self.address or "").strip()

    def save(self, *args, **kwargs) -> None:
        self.name = normalize_name(self.name)
        self.address = str(self.address or "").strip()
        super().save(*args, **kwargs)

    # -- helpers (small, non-business) ---------------------------------------
    @property
    def region(self) -> Region:
        return self.district.region

    @property
    def full_name(self) -> str:
        parts = [self.name, self.district.name, self.district.region.name]
        if self.address:
            parts.insert(1, self.address)
        return ", ".join(parts)

    def distance_km_to(self, other: "Location") -> float:
        """Great-circle distance in kilometres (Haversine).

        Used only for informative display and for the "nearby locations"
        ordering; the matching score itself is deterministic and rule based.
        """
        from math import asin, cos, radians, sin, sqrt

        latitude_1, longitude_1 = radians(float(self.latitude)), radians(float(self.longitude))
        latitude_2, longitude_2 = radians(float(other.latitude)), radians(float(other.longitude))
        delta_latitude = latitude_2 - latitude_1
        delta_longitude = longitude_2 - longitude_1
        haversine = (
            sin(delta_latitude / 2) ** 2
            + cos(latitude_1) * cos(latitude_2) * sin(delta_longitude / 2) ** 2
        )
        return 2 * 6371.0 * asin(sqrt(haversine))

    @staticmethod
    def same_place(first: "Location", second: "Location") -> bool:
        """Two pickup points are the same when the district matches."""
        return first.pk == second.pk or first.district_id == second.district_id
