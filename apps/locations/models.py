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
        Delegates to :func:`apps.rides.services.haversine_km` so a catalogue
        route and a map pick are measured with one formula.
        """
        from apps.rides.services import haversine_km

        return float(
            haversine_km(
                (self.latitude, self.longitude),
                (other.latitude, other.longitude),
            )
        )

    @staticmethod
    def same_place(first: "Location", second: "Location") -> bool:
        """Two pickup points are the same when the district matches."""
        return first.pk == second.pk or first.district_id == second.district_id


# ---------------------------------------------------------------------------
# Geocoded route snapshots
# ---------------------------------------------------------------------------
#: ``(district, district_area, living_area)`` string names are all capped at
#: this length by 2GIS; the address gets the longer budget because it is the
#: value rendered verbatim in the UI.
_SNAPSHOT_NAME_MAX_LENGTH = 120
_SNAPSHOT_ADDRESS_MAX_LENGTH = 255
_SNAPSHOT_PLACE_NAME_MAX_LENGTH = 180


def _point_snapshot_fields(prefix: str) -> dict[str, models.Field]:
    """Build the seven snapshot columns for a route endpoint.

    The factory is called once per abstract model so that each model owns its
    own field *instances* - Django assigns ``Field.name`` / ``Field.model`` when
    a field is contributed, so the same instance must never be shared between
    two models.
    """
    return {
        f"{prefix}_latitude": models.DecimalField(
            verbose_name="Kenglik (lat)",
            max_digits=COORDINATE_MAX_DIGITS,
            decimal_places=COORDINATE_DECIMAL_PLACES,
            null=True,
            blank=True,
            validators=[validate_latitude],
            help_text="2GIS yoki qurilmadan olingan kenglik. Bo'sh bo'lishi mumkin.",
        ),
        f"{prefix}_longitude": models.DecimalField(
            verbose_name="Uzunlik (lng)",
            max_digits=COORDINATE_MAX_DIGITS,
            decimal_places=COORDINATE_DECIMAL_PLACES,
            null=True,
            blank=True,
            validators=[validate_longitude],
            help_text="2GIS yoki qurilmadan olingan uzunlik. Bo'sh bo'lishi mumkin.",
        ),
        f"{prefix}_address": models.CharField(
            verbose_name="Aniq manzil",
            max_length=_SNAPSHOT_ADDRESS_MAX_LENGTH,
            blank=True,
            default="",
            help_text="2GIS qaytargan to'liq manzil. Masalan: Toshkent, Amir Temur ko'chasi, 12.",
        ),
        f"{prefix}_place_name": models.CharField(
            verbose_name="Nomi",
            max_length=_SNAPSHOT_PLACE_NAME_MAX_LENGTH,
            blank=True,
            default="",
            help_text="2GIS obyekti nomi yoki kvartal nomi.",
        ),
        f"{prefix}_region_name": models.CharField(
            verbose_name="Viloyat / shahar",
            max_length=_SNAPSHOT_NAME_MAX_LENGTH,
            blank=True,
            default="",
        ),
        f"{prefix}_city_name": models.CharField(
            verbose_name="Shahar",
            max_length=_SNAPSHOT_NAME_MAX_LENGTH,
            blank=True,
            default="",
        ),
        f"{prefix}_district_name": models.CharField(
            verbose_name="Tuman",
            max_length=_SNAPSHOT_NAME_MAX_LENGTH,
            blank=True,
            default="",
        ),
    }


def point_pair_constraints(prefix: str, *, name_prefix: str) -> list[models.CheckConstraint]:
    """Both coordinates present-or-absent together, for one route endpoint.

    Public because ``apps.rides`` attaches the same pair to ``DriverTrip`` and
    ``PassengerRequest``; the name mirrors Django's constraint prefixes.
    ``name_prefix`` keeps the generated names unique *per model*, which Django
    enforces (PostgreSQL would allow the same name in two tables, Django does
    not).
    """
    return [
        models.CheckConstraint(
            condition=(
                models.Q(**{f"{prefix}_latitude__isnull": True})
                & models.Q(**{f"{prefix}_longitude__isnull": True})
            )
            | (
                models.Q(**{f"{prefix}_latitude__isnull": False})
                & models.Q(**{f"{prefix}_longitude__isnull": False})
            ),
            name=f"{name_prefix}_{prefix}_coordinates_are_both_set",
        ),
        models.CheckConstraint(
            condition=models.Q(**{f"{prefix}_latitude__isnull": True})
            | (
                models.Q(**{f"{prefix}_latitude__gte": -90})
                & models.Q(**{f"{prefix}_latitude__lte": 90})
            ),
            name=f"{name_prefix}_{prefix}_latitude_range",
        ),
        models.CheckConstraint(
            condition=models.Q(**{f"{prefix}_longitude__isnull": True})
            | (
                models.Q(**{f"{prefix}_longitude__gte": -180})
                & models.Q(**{f"{prefix}_longitude__lte": 180})
            ),
            name=f"{name_prefix}_{prefix}_longitude_range",
        ),
    ]


class OriginPointSnapshot(models.Model):
    """``from_*`` half of a geocoded route endpoint.

    A trip/request resolves *one* of two ways:

    * a curated catalogue :class:`Location` (``from_location``), or
    * a raw point picked on the map / read from GPS (``from_latitude`` ...).

    The FK is therefore optional. The snapshot columns are a **denormalised
    copy** taken at creation time: renaming a district in the admin or a
    2GIS catalogue change must never rewrite the history of a booked ride, and
    passengers and drivers must see byte-identical text for the same ride.
    """

    locals().update(_point_snapshot_fields("from"))

    class Meta:
        abstract = True


class DestinationPointSnapshot(models.Model):
    """``to_*`` half of a geocoded route endpoint. See :class:`OriginPointSnapshot`."""

    locals().update(_point_snapshot_fields("to"))

    class Meta:
        abstract = True


__all__ = [
    "COORDINATE_DECIMAL_PLACES",
    "COORDINATE_MAX_DIGITS",
    "DestinationPointSnapshot",
    "District",
    "Location",
    "OriginPointSnapshot",
    "Region",
    "normalize_name",
]
