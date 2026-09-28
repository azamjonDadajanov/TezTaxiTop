"""Order and OrderPassenger models.

Design decisions
----------------
* ``price_per_seat`` and ``total_amount`` are **snapshots** taken at creation
  time. Changing ``DriverTrip.price_per_seat`` later must never change an old
  order, so the value is copied, never joined at render time.
* ``total_amount = seats_booked * price_per_seat`` is computed with
  :class:`~decimal.Decimal` in the service layer and additionally guarded by a
  database check constraint (``total_amount >= 0``).
* Seats are **not** reserved while the order is ``PENDING`` (a passenger may
  send many requests and the driver picks one). They are reserved the moment the
  driver accepts, inside a transaction that locks the trip row first.
* Every FK uses ``PROTECT`` for business data (trip, passenger, order) so that a
  mistake in the admin can never cascade-delete financial history.
* ``related_name`` values are unique project wide:
  ``Order.orders`` on ``DriverTrip``, ``Order.orders`` on ``User``,
  ``OrderPassenger.passengers`` on ``Order``.
"""

from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel
from apps.orders.constants import (
    CANCELLABLE_BY_DRIVER,
    CANCELLABLE_BY_PASSENGER,
    MONEY_DECIMAL_PLACES,
    MONEY_MAX_DIGITS,
    SEAT_HOLDING_STATUSES,
    TERMINAL_STATUSES,
)

NON_NEGATIVE = Decimal("0.00")


class OrderStatus(models.TextChoices):
    PENDING = "pending", "Kutilmoqda"
    ACCEPTED = "accepted", "Qabul qilindi"
    DRIVER_ARRIVED = "driver_arrived", "Haydovchi keldi"
    IN_PROGRESS = "in_progress", "Yo'lga chiqdi"
    COMPLETED = "completed", "Yakunlandi"
    REJECTED = "rejected", "Rad etildi"
    CANCELLED_BY_PASSENGER = "cancelled_by_passenger", "Yo'lovchi bekor qildi"
    CANCELLED_BY_DRIVER = "cancelled_by_driver", "Haydovchi bekor qildi"
    NO_SHOW = "no_show", "Yo'lovchi kelmadi"


class OrderQuerySet(models.QuerySet):
    def active(self) -> "OrderQuerySet":
        return self.exclude(status__in=TERMINAL_STATUSES)

    def holding_seats(self) -> "OrderQuerySet":
        return self.filter(status__in=SEAT_HOLDING_STATUSES)

    def pending(self) -> "OrderQuerySet":
        return self.filter(status=OrderStatus.PENDING)

    def for_passenger(self, passenger) -> "OrderQuerySet":
        return self.filter(passenger=passenger)

    def for_driver(self, driver_profile) -> "OrderQuerySet":
        return self.filter(trip__driver=driver_profile)


class Order(TimeStampedModel):
    """A booking of ``seats_booked`` seats on one trip by one passenger."""

    trip = models.ForeignKey(
        "rides.DriverTrip",
        on_delete=models.PROTECT,
        related_name="orders",
        verbose_name="Yo'lov",
        help_text="Buyurtma qaysi yo'lovga berilganini ko'rsatadi.",
    )
    passenger = models.ForeignKey(
        "users.User",
        on_delete=models.PROTECT,
        related_name="orders",
        verbose_name="Yo'lovchi",
    )
    seats_booked = models.PositiveSmallIntegerField(
        verbose_name="Band qilingan o'rinlar",
        help_text="1 dan ko'p bo'lishi kerak va yo'lovdagi bo'sh o'rinlardan oshmasligi kerak.",
    )
    price_per_seat = models.DecimalField(
        verbose_name="Bir o'rin narxi (nusxa)",
        max_digits=MONEY_MAX_DIGITS,
        decimal_places=MONEY_DECIMAL_PLACES,
        help_text="Buyurtma yaratilgan paytdagi narx. Yo'lov narxi o'zgarsa ham o'zgarmaydi.",
    )
    total_amount = models.DecimalField(
        verbose_name="Umumiy summa",
        max_digits=MONEY_MAX_DIGITS,
        decimal_places=MONEY_DECIMAL_PLACES,
        help_text="seats_booked * price_per_seat",
    )
    status = models.CharField(
        verbose_name="Holat",
        max_length=32,
        choices=OrderStatus.choices,
        default=OrderStatus.PENDING,
        db_index=True,
    )
    passenger_note = models.CharField(
        verbose_name="Yo'lovchi izohi",
        max_length=500,
        blank=True,
        default="",
        help_text="Buyurtma qilishda yozilgan izoh.",
    )
    cancellation_reason = models.CharField(
        verbose_name="Bekor qilish sababi",
        max_length=500,
        blank=True,
        default="",
    )
    accepted_at = models.DateTimeField(verbose_name="Qabul qilingan vaqti", null=True, blank=True)
    cancelled_at = models.DateTimeField(verbose_name="Bekor qilingan vaqti", null=True, blank=True)
    completed_at = models.DateTimeField(verbose_name="Yakunlangan vaqti", null=True, blank=True)

    objects = OrderQuerySet.as_manager()

    class Meta:
        verbose_name = "Buyurtma"
        verbose_name_plural = "Buyurtmalar"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("trip", "status"), name="order_trip_status_idx"),
            models.Index(fields=("passenger", "status"), name="order_passenger_status_idx"),
            models.Index(fields=("status", "-created_at"), name="order_status_created_idx"),
            models.Index(fields=("status", "created_at"), name="order_status_asc_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(seats_booked__gt=0), name="order_seats_booked_positive"
            ),
            models.CheckConstraint(
                condition=models.Q(price_per_seat__gte=NON_NEGATIVE), name="order_price_non_negative"
            ),
            models.CheckConstraint(
                condition=models.Q(total_amount__gte=NON_NEGATIVE), name="order_total_non_negative"
            ),
        ]

    def __str__(self) -> str:
        return f"Buyurtma #{self.pk} - {self.passenger.display_name} ({self.get_status_display()})"

    def clean(self) -> None:
        super().clean()
        if self.seats_booked is not None and self.seats_booked <= 0:
            raise ValidationError({"seats_booked": _("Kamida 1 ta o'rin kerak.")})

    # -- helpers (small, non-business) ---------------------------------------
    @property
    def holds_seats(self) -> bool:
        """Whether the booked seats are currently deducted from the trip."""
        return self.status in SEAT_HOLDING_STATUSES

    @property
    def is_terminal(self) -> bool:
        """True once the order can no longer change state."""
        return self.status in TERMINAL_STATUSES

    @property
    def can_cancel(self) -> bool:
        """Generic cancel check (passenger side)."""
        return self.status in CANCELLABLE_BY_PASSENGER

    @property
    def can_driver_cancel(self) -> bool:
        return self.status in CANCELLABLE_BY_DRIVER

    @property
    def is_reviewable(self) -> bool:
        """Only completed orders can be reviewed."""
        return self.status == OrderStatus.COMPLETED

    @property
    def driver_user_id(self) -> int:
        return self.trip.driver.user_id

    def is_participant(self, user) -> bool:
        """Object level authorisation used by chat, reviews and the API."""
        if user is None or not user.is_authenticated:
            return False
        if user.pk == self.passenger_id:
            return True
        driver_profile = getattr(user, "driver_profile", None)
        return driver_profile is not None and driver_profile.pk == self.trip.driver_id


class OrderPassenger(TimeStampedModel):
    """Optional companion travelling instead of the account owner."""

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="passengers",
        verbose_name="Buyurtma",
        help_text="Buyurtma o'chirilsa, birga sayohat qiluvchilar ham o'chadi (moliyaviy emas).",
    )
    first_name = models.CharField(verbose_name="Ism", max_length=150)
    last_name = models.CharField(verbose_name="Familiya", max_length=150, blank=True, default="")
    phone_number = models.CharField(
        verbose_name="Telefon",
        max_length=20,
        blank=True,
        default="",
        help_text="+998901234567",
    )

    class Meta:
        verbose_name = "Buyurtma yo'lovchisi"
        verbose_name_plural = "Buyurtma yo'lovchilari"
        ordering = ("id",)
        indexes = [models.Index(fields=("order",), name="orderpassenger_order_idx")]

    def __str__(self) -> str:
        return f"{self.first_name} {self.last_name}".strip() or f"Yo'lovchi #{self.pk}"

    @property
    def display_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()
