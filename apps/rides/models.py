"""Driver trip and passenger request models.

Design decisions
----------------
``DriverTrip``
    * ``price_per_seat`` is a ``DecimalField(12, 2)`` - never a float.
    * ``available_seats`` is denormalised on purpose: the matching engine and the
      driver UI need to filter on "trips that still have free seats" on every
      request, and a join+aggregate on the orders table would be far slower.
      The value is only ever mutated inside ``transaction.atomic()`` blocks with
      ``select_for_update()`` (see :mod:`apps.rides.services`).
    * ``available_seats`` is snapshot business data, therefore the database
      enforces ``0 <= available_seats <= total_seats``.
    * A trip snapshots nothing from the vehicle except the constraint
      ``total_seats <= vehicle.seats_count - 1``; the vehicle may be changed or
      deactivated later without rewriting history.
    * ``related_name`` values are unique across the whole project so that admin
      autocomplete and reverse relations stay unambiguous:
      ``DriverTrip.trips`` on ``DriverProfile``, ``DriverTrip.orders``,
      ``DriverTrip.trips_as_origin`` / ``trips_as_destination`` on ``Location``,
      ``DriverTrip.passenger_requests`` on ``Location``.

``PassengerRequest``
    * ``departure_from`` / ``departure_until`` form a half open interval
      ``[from, until)`` and are checked by a database constraint.
    * ``max_price_per_seat`` is nullable: "no price limit" is a valid business
      statement.
"""

from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel
from apps.rides.constants import (
    MAX_SEATS_PER_TRIP,
    MONEY_DECIMAL_PLACES,
    MONEY_MAX_DIGITS,
)

#: Prices are non negative; the check constraint uses the same constant.
NON_NEGATIVE = Decimal("0.00")


class DriverTripStatus(models.TextChoices):
    DRAFT = "draft", "Qoralama"
    ACTIVE = "active", "Faol"
    FULL = "full", "To'liq"
    IN_PROGRESS = "in_progress", "Yo'lga chiqdi"
    COMPLETED = "completed", "Yakunlandi"
    CANCELLED = "cancelled", "Bekor qilindi"
    EXPIRED = "expired", "Muddati tugadi"


class PassengerRequestStatus(models.TextChoices):
    ACTIVE = "active", "Faol"
    MATCHED = "matched", "Moslashdi"
    COMPLETED = "completed", "Yakunlandi"
    CANCELLED = "cancelled", "Bekor qilindi"
    EXPIRED = "expired", "Muddati tugadi"


class DriverTripQuerySet(models.QuerySet):
    """Status aware queryset used by selectors and the matching engine."""

    def bookable(self) -> "DriverTripQuerySet":
        """Trips that can still receive orders and new matches."""
        return self.filter(status=DriverTripStatus.ACTIVE, available_seats__gt=0)

    def with_seats(self, seats: int) -> "DriverTripQuerySet":
        return self.filter(available_seats__gte=seats)

    def upcoming(self) -> "DriverTripQuerySet":
        return self.filter(
            status__in=(
                DriverTripStatus.ACTIVE,
                DriverTripStatus.FULL,
                DriverTripStatus.IN_PROGRESS,
            )
        )


class DriverTrip(TimeStampedModel):
    """A published ride: one driver, one vehicle, one route, N seats."""

    driver = models.ForeignKey(
        "users.DriverProfile",
        on_delete=models.PROTECT,
        related_name="trips",
        verbose_name="Haydovchi",
        help_text="Yo'lovni e'lon qilgan haydovchi.",
    )
    vehicle = models.ForeignKey(
        "vehicles.Vehicle",
        on_delete=models.PROTECT,
        related_name="trips",
        verbose_name="Avtomobil",
        help_text="Avtomobil haydovchining profili va tanlangan mashinasiga tegishli bo'lishi shart.",
    )
    from_location = models.ForeignKey(
        "locations.Location",
        on_delete=models.PROTECT,
        related_name="trips_as_origin",
        verbose_name="Qayerdan",
    )
    to_location = models.ForeignKey(
        "locations.Location",
        on_delete=models.PROTECT,
        related_name="trips_as_destination",
        verbose_name="Qayerga",
    )
    departure_time = models.DateTimeField(
        verbose_name="Chuqish vaqti",
        db_index=True,
        help_text="Vaqt zonasi bilan (UTC) saqlanadigan chuqish vaqti.",
    )
    total_seats = models.PositiveSmallIntegerField(
        verbose_name="Jami o'rinlar",
        help_text="Yo'lovchilar uchun taklif etilgan umumiy o'rin soni.",
    )
    available_seats = models.PositiveSmallIntegerField(
        verbose_name="Bo'sh o'rinlar",
        help_text="Hozirda band qilinmagan o'rinlar. 0 bo'lsa status avtomatik `full` ga o'tadi.",
    )
    price_per_seat = models.DecimalField(
        verbose_name="Bir o'rin narxi",
        max_digits=MONEY_MAX_DIGITS,
        decimal_places=MONEY_DECIMAL_PLACES,
        help_text="So'mda. Buyurtmada narx nusxalanadi (snapshot).",
    )
    comment = models.CharField(
        verbose_name="Izoh",
        max_length=500,
        blank=True,
        default="",
        help_text="Yo'lovchi uchun qo'shimcha ma'lumot.",
    )
    status = models.CharField(
        verbose_name="Holat",
        max_length=20,
        choices=DriverTripStatus.choices,
        default=DriverTripStatus.DRAFT,
        db_index=True,
    )

    objects = DriverTripQuerySet.as_manager()

    class Meta:
        verbose_name = "Haydovchi yo'lovi"
        verbose_name_plural = "Haydovchi yo'lovlari"
        ordering = ("departure_time", "-created_at")
        indexes = [
            models.Index(fields=("driver", "status"), name="trip_driver_status_idx"),
            models.Index(fields=("status", "departure_time"), name="trip_status_departure_idx"),
            models.Index(fields=("from_location", "to_location"), name="trip_route_idx"),
            models.Index(fields=("driver", "-created_at"), name="trip_driver_created_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(total_seats__gt=0) & models.Q(total_seats__lte=MAX_SEATS_PER_TRIP),
                name="trip_total_seats_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(available_seats__gte=0),
                name="trip_available_seats_not_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(available_seats__lte=models.F("total_seats")),
                name="trip_available_seats_lte_total",
            ),
            models.CheckConstraint(
                condition=models.Q(price_per_seat__gte=NON_NEGATIVE),
                name="trip_price_non_negative",
            ),
            # A pickup point and a dropoff point can never be the same row.
            # The comparison uses the raw ``*_id`` columns on purpose: a check
            # constraint may not span a JOIN.
            models.CheckConstraint(
                condition=~models.Q(from_location_id=models.F("to_location_id")),
                name="trip_locations_must_differ",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.from_location.name} -> {self.to_location.name} ({self.departure_time:%Y-%m-%d %H:%M})"

    def clean(self) -> None:
        super().clean()
        if self.from_location_id and self.from_location_id == self.to_location_id:
            raise ValidationError({"to_location": _("Qayerdan va qayerga bir xil bo'lishi mumkin emas.")})
        if self.driver_id and self.vehicle_id and self.vehicle.driver_id != self.driver_id:
            raise ValidationError({"vehicle": _("Avtomobil tanlangan haydovchining emas.")})
        if self.vehicle_id and self.total_seats and self.total_seats > self.vehicle.seats_for_passengers:
            raise ValidationError(
                {
                    "total_seats": _(
                        "Avtomobilda %(available)d ta o'rin bor."
                    ) % {"available": self.vehicle.seats_for_passengers}
                }
            )

    # -- helpers (small, non-business) ---------------------------------------
    @property
    def booked_seats(self) -> int:
        return max(0, self.total_seats - self.available_seats)

    @property
    def has_available_seats(self) -> bool:
        return self.available_seats > 0

    @property
    def is_active(self) -> bool:
        return self.status == DriverTripStatus.ACTIVE

    @property
    def is_terminal(self) -> bool:
        return self.status in (
            DriverTripStatus.COMPLETED,
            DriverTripStatus.CANCELLED,
            DriverTripStatus.EXPIRED,
        )

    @property
    def accepts_new_orders(self) -> bool:
        """Only an ``active`` trip with free seats can receive a new order."""
        return self.status == DriverTripStatus.ACTIVE and self.available_seats > 0

    def route_label(self) -> str:
        return f"{self.from_location.name} -> {self.to_location.name}"


class PassengerRequest(TimeStampedModel):
    """A passenger's "I need a ride from A to B" broadcast."""

    passenger = models.ForeignKey(
        "users.User",
        on_delete=models.PROTECT,
        related_name="passenger_requests",
        verbose_name="Yo'lovchi",
    )
    from_location = models.ForeignKey(
        "locations.Location",
        on_delete=models.PROTECT,
        related_name="passenger_requests_as_origin",
        verbose_name="Qayerdan",
    )
    to_location = models.ForeignKey(
        "locations.Location",
        on_delete=models.PROTECT,
        related_name="passenger_requests_as_destination",
        verbose_name="Qayerga",
    )
    passenger_count = models.PositiveSmallIntegerField(
        verbose_name="Yo'lovchilar soni",
        default=1,
        help_text="Kerakli o'rinlar soni (1 dan katta).",
    )
    max_price_per_seat = models.DecimalField(
        verbose_name="Maksimal narx (bir o'rinka)",
        max_digits=MONEY_MAX_DIGITS,
        decimal_places=MONEY_DECIMAL_PLACES,
        null=True,
        blank=True,
        help_text="Bo'sh bo'lsa - narx cheklovi yo'q.",
    )
    departure_from = models.DateTimeField(
        verbose_name="Chuqish (dan)",
        db_index=True,
        help_text="Engerta gapida chuqish vaqti.",
    )
    departure_until = models.DateTimeField(
        verbose_name="Chuqish (gacha)",
        db_index=True,
        help_text="Eng kechiktirilgan chuqish vaqti.",
    )
    comment = models.CharField(verbose_name="Izoh", max_length=500, blank=True, default="")
    status = models.CharField(
        verbose_name="Holat",
        max_length=20,
        choices=PassengerRequestStatus.choices,
        default=PassengerRequestStatus.ACTIVE,
        db_index=True,
    )

    class Meta:
        verbose_name = "Yo'lovchi so'rovi"
        verbose_name_plural = "Yo'lovchi so'rovlari"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("status", "-created_at"), name="req_status_created_idx"),
            models.Index(fields=("passenger", "status"), name="req_passenger_status_idx"),
            models.Index(fields=("from_location", "to_location"), name="req_route_idx"),
            models.Index(fields=("departure_from", "departure_until"), name="req_departure_window_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(passenger_count__gt=0),
                name="passenger_request_count_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(departure_until__gt=models.F("departure_from")),
                name="passenger_request_departure_window",
            ),
            models.CheckConstraint(
                condition=models.Q(from_location__isnull=False)
                & ~models.Q(from_location_id=models.F("to_location_id")),
                name="passenger_request_locations_must_differ",
            ),
            models.CheckConstraint(
                condition=models.Q(max_price_per_seat__isnull=True)
                | models.Q(max_price_per_seat__gte=NON_NEGATIVE),
                name="passenger_request_max_price_non_negative",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.passenger.display_name}: {self.from_location.name} -> {self.to_location.name}"

    def clean(self) -> None:
        super().clean()
        if self.from_location_id and self.from_location_id == self.to_location_id:
            raise ValidationError({"to_location": _("Qayerdan va qayerga bir xil bo'lishi mumkin emas.")})
        if (
            self.departure_from
            and self.departure_until
            and self.departure_until <= self.departure_from
        ):
            raise ValidationError({"departure_until": _("Chuqish oxirgi vaqti boshlangan vaqtdan katta bo'lishi kerak.")})

    # -- helpers (small, non-business) ---------------------------------------
    @property
    def is_active(self) -> bool:
        return self.status == PassengerRequestStatus.ACTIVE

    @property
    def is_matchable(self) -> bool:
        return self.status == PassengerRequestStatus.ACTIVE
