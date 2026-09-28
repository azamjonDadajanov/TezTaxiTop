"""Subscription plan and driver subscription models.

Design decisions
----------------
* ``DriverSubscription`` is a **history table**, not a profile. It is therefore
  a plain ``ForeignKey`` to the driver, never a ``OneToOneField``: a driver must
  be able to own many subscriptions over time.
* ``price_at_purchase`` snapshots the plan price. If an administrator raises
  ``SubscriptionPlan.price`` tomorrow, every historical subscription must still
  show what the driver actually paid - exactly the same snapshot principle as
  ``Order.price_per_seat``.
* A **partial unique constraint** guarantees at most one ``ACTIVE``
  subscription per driver at the database level, while allowing any number of
  ``EXPIRED`` / ``CANCELLED`` / ``PENDING`` rows.
* ``plan`` uses ``on_delete=PROTECT``: deleting a plan must never destroy
  financial history.
* ``status`` is a *cache* of reality, not the source of truth. The authoritative
  test is :func:`apps.subscriptions.services.has_active_subscription`, which
  checks both the status **and** ``expires_at > now()`` (and also repairs the
  cached status when it is stale).
"""

from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel

MONEY_MAX_DIGITS = 12
MONEY_DECIMAL_PLACES = 2
NON_NEGATIVE = Decimal("0.00")


class DriverSubscriptionStatus(models.TextChoices):
    PENDING = "pending", "Kutilmoqda (to'lov kutilmoqda)"
    ACTIVE = "active", "Faol"
    EXPIRED = "expired", "Muddati tugagan"
    CANCELLED = "cancelled", "Bekor qilingan"


class SubscriptionPlan(TimeStampedModel):
    """A purchasable package, e.g. 1 / 3 / 6 / 12 months.

    ``duration_days`` keeps the duration configurable instead of hardcoding
    "one month" in code: a "10 day" trial plan works without any change.
    """

    name = models.CharField(verbose_name="Nomi", max_length=120, unique=True, help_text="Masalan: 1 oy, 3 oy, 6 oy.")
    duration_days = models.PositiveIntegerField(
        verbose_name="Muddat (kun)",
        help_text="Necha kunga mo'ljallangan. 30 kun = 1 oy, 365 kun = 1 yil.",
    )
    price = models.DecimalField(
        verbose_name="Narx",
        max_digits=MONEY_MAX_DIGITS,
        decimal_places=MONEY_DECIMAL_PLACES,
        help_text="So'mda. O'zgarishi mumkin - eski obunalar `price_at_purchase` saqlaydi.",
    )
    description = models.TextField(verbose_name="Tavsif", max_length=1000, blank=True, default="")
    is_active = models.BooleanField(verbose_name="Faol", default=True, db_index=True, help_text="Yangi xaridlarga taklif etiladi.")
    sort_order = models.PositiveSmallIntegerField(
        verbose_name="Tartib", default=0, db_index=True, help_text="Admin va bot ro'yxatidagi tartib."
    )

    class Meta:
        verbose_name = "Obuna rejası"
        verbose_name_plural = "Obuna rejalari"
        ordering = ("sort_order", "duration_days")
        indexes = [models.Index(fields=("is_active", "sort_order"), name="plan_active_order_idx")]
        constraints = [
            models.CheckConstraint(condition=models.Q(duration_days__gt=0), name="plan_duration_positive"),
            models.CheckConstraint(condition=models.Q(price__gte=NON_NEGATIVE), name="plan_price_non_negative"),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.duration_days} kun) - {self.price} so'm"

    def clean(self) -> None:
        super().clean()
        if self.duration_days is not None and self.duration_days <= 0:
            raise ValidationError({"duration_days": _("Muddat 0 dan katta bo'lishi kerak.")})
        if self.price is not None and self.price < NON_NEGATIVE:
            raise ValidationError({"price": _("Narx manfiy bo'lishi mumkin emas.")})

    @property
    def price_as_int(self) -> int:
        """Sum in whole so'm, used for inline keyboard labels."""
        return int(self.price.quantize(Decimal("1")))


class DriverSubscriptionQuerySet(models.QuerySet):
    def active(self) -> "DriverSubscriptionQuerySet":
        return self.filter(status=DriverSubscriptionStatus.ACTIVE)

    def currently_valid(self, moment=None) -> "DriverSubscriptionQuerySet":
        from django.utils import timezone

        moment = moment or timezone.now()
        return self.active().filter(starts_at__lte=moment, expires_at__gt=moment)

    def for_driver(self, driver) -> "DriverSubscriptionQuerySet":
        return self.filter(driver=driver)


class DriverSubscription(TimeStampedModel):
    """One purchased subscription period of a driver."""

    driver = models.ForeignKey(
        "users.DriverProfile",
        on_delete=models.PROTECT,
        related_name="subscriptions",
        verbose_name="Haydovchi",
        help_text="Bir haydovchining obuna tarixi shu maydonda saqlanadi.",
    )
    plan = models.ForeignKey(
        SubscriptionPlan,
        on_delete=models.PROTECT,
        related_name="subscriptions",
        verbose_name="Reja",
        help_text="Reja o'chirilmaydi - tarixiy obunalar butunligini saqlash uchun.",
    )
    starts_at = models.DateTimeField(
        verbose_name="Boshlanish vaqti",
        help_text="Faollik boshlanadigan payt (timezone-aware).",
    )
    expires_at = models.DateTimeField(
        verbose_name="Tugash vaqti",
        help_text="Faollik tugaydigan payt (timezone-aware).",
    )
    status = models.CharField(
        verbose_name="Holat",
        max_length=20,
        choices=DriverSubscriptionStatus.choices,
        default=DriverSubscriptionStatus.PENDING,
        db_index=True,
    )
    price_at_purchase = models.DecimalField(
        verbose_name="Xarid qilingan narx",
        max_digits=MONEY_MAX_DIGITS,
        decimal_places=MONEY_DECIMAL_PLACES,
        help_text="Reja narxi o'zgarsa ham, o'sha paytdagi to'lov saqlanib qoladi.",
    )
    auto_renew = models.BooleanField(
        verbose_name="Avtomatik yangilanish",
        default=False,
        help_text="To'lov muvaffaqiyatli bo'lsa muddat avtomatik uzaytiriladi.",
    )
    payment = models.ForeignKey(
        "payments.Payment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="subscriptions",
        verbose_name="To'lov",
        help_text="Obunani faollashtirgan to'lov (ixtiyoriy).",
    )
    activated_at = models.DateTimeField(verbose_name="Faollashtirilgan vaqti", null=True, blank=True)
    cancelled_at = models.DateTimeField(verbose_name="Bekor qilingan vaqti", null=True, blank=True)

    objects = DriverSubscriptionQuerySet.as_manager()

    class Meta:
        verbose_name = "Haydovchi obunasi"
        verbose_name_plural = "Haydovchi obunalari"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("driver", "status"), name="subscription_driver_status_idx"),
            models.Index(fields=("status", "expires_at"), name="subscription_status_expiry_idx"),
            models.Index(fields=("expires_at",), name="subscription_expiry_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(expires_at__gt=models.F("starts_at")),
                name="subscription_dates_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(price_at_purchase__gte=NON_NEGATIVE),
                name="subscription_price_non_negative",
            ),
            # At most one ACTIVE subscription per driver, at database level.
            models.UniqueConstraint(
                fields=("driver",),
                condition=models.Q(status="active"),
                name="uniq_active_subscription_per_driver",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.driver} - {self.plan.name} ({self.get_status_display()})"

    def clean(self) -> None:
        super().clean()
        if self.starts_at and self.expires_at and self.expires_at <= self.starts_at:
            raise ValidationError({"expires_at": _("Tugash vaqti boshlanish vaqtidan katta bo'lishi kerak.")})

    # -- helpers (small, non-business) ---------------------------------------
    def is_active_now(self) -> bool:
        """Both the cached status and the real validity window are checked."""
        from django.utils import timezone

        if self.status != DriverSubscriptionStatus.ACTIVE:
            return False
        now = timezone.now()
        return self.starts_at <= now < self.expires_at

    def days_remaining(self) -> int:
        """Whole days left, never negative."""
        from django.utils import timezone

        remaining = (self.expires_at - timezone.now()).total_seconds()
        if remaining <= 0:
            return 0
        return int(remaining // 86400)

    def snapshot_plan(self) -> None:
        """Copy the current plan price into ``price_at_purchase``."""
        if self.plan_id:
            self.price_at_purchase = self.plan.price
