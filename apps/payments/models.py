"""Payment model and provider enumerations."""

from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel

MONEY_MAX_DIGITS = 12
MONEY_DECIMAL_PLACES = 2
NON_NEGATIVE = Decimal("0.00")


class PaymentType(models.TextChoices):
    SUBSCRIPTION = "subscription", "Obuna to'lovi"
    ORDER = "order", "Buyurtma to'lovi"
    OTHER = "other", "Boshqa"


class PaymentProvider(models.TextChoices):
    CLICK = "click", "Click"
    PAYME = "payme", "Payme"
    UZUM = "uzum", "Uzum"
    CASH = "cash", "Naqd pul"
    OTHER = "other", "Boshqa"


class PaymentStatus(models.TextChoices):
    PENDING = "pending", "Kutilmoqda"
    SUCCESS = "success", "Muvaffaqiyatli"
    FAILED = "failed", "Muvaffaqiyatsiz"
    REFUNDED = "refunded", "Qaytarildi"
    CANCELLED = "cancelled", "Bekor qilindi"


#: Statuses that are final - a final payment is never processed twice.
FINAL_PAYMENT_STATUSES: frozenset[str] = frozenset(
    {PaymentStatus.SUCCESS, PaymentStatus.REFUNDED, PaymentStatus.CANCELLED}
)


class Payment(TimeStampedModel):
    """A money movement recorded for a user.

    Design decisions
    ----------------
    * ``amount`` is ``DecimalField(12, 2)`` - never a float.
    * ``external_transaction_id`` is unique **per provider** via a partial
      unique constraint, so the same provider cannot report the same
      transaction twice. This is what makes webhook handling idempotent.
    * ``metadata`` (JSONField) stores the raw provider response for auditing.
    * ``status`` is only ever changed by
      :mod:`apps.payments.services` after a **server side** verification. A
      client can never post ``status=success``.
    * ``on_delete=PROTECT`` on the user: payments are financial history and are
      never cascade deleted.
    """

    user = models.ForeignKey(
        "users.User",
        on_delete=models.PROTECT,
        related_name="payments",
        verbose_name="Foydalanuvchi",
    )
    payment_type = models.CharField(
        verbose_name="To'lov turi",
        max_length=20,
        choices=PaymentType.choices,
        default=PaymentType.SUBSCRIPTION,
        db_index=True,
    )
    amount = models.DecimalField(
        verbose_name="Summa",
        max_digits=MONEY_MAX_DIGITS,
        decimal_places=MONEY_DECIMAL_PLACES,
        help_text="So'mda. Manfiy bo'lishi mumkin emas.",
    )
    provider = models.CharField(
        verbose_name="Provayder",
        max_length=20,
        choices=PaymentProvider.choices,
        default=PaymentProvider.CLICK,
        db_index=True,
    )
    external_transaction_id = models.CharField(
        verbose_name="Tashqi tranzaksiya ID",
        max_length=120,
        null=True,
        blank=True,
        help_text="Provayder tomonidan berilgan ID. Bo'sh bo'lsa, hali to'lov yuborilmagan.",
    )
    status = models.CharField(
        verbose_name="Holat",
        max_length=20,
        choices=PaymentStatus.choices,
        default=PaymentStatus.PENDING,
        db_index=True,
    )
    paid_at = models.DateTimeField(
        verbose_name="To'langan vaqti",
        null=True,
        blank=True,
        help_text="Faqat server tomonidan tasdiqlangan to'lovda to'ldiriladi.",
    )
    metadata = models.JSONField(
        verbose_name="Qo'shimcha ma'lumot",
        default=dict,
        blank=True,
        help_text="Provayder javobi (transaction id, status, summa va h.k.).",
    )
    failure_reason = models.CharField(
        verbose_name="Xatolik sababi",
        max_length=255,
        blank=True,
        default="",
    )
    refunded_at = models.DateTimeField(verbose_name="Qaytarilgan vaqti", null=True, blank=True)

    class Meta:
        verbose_name = "To'lov"
        verbose_name_plural = "To'lovlar"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("user", "-created_at"), name="payment_user_created_idx"),
            models.Index(fields=("provider", "status"), name="payment_provider_status_idx"),
            models.Index(fields=("payment_type", "status"), name="payment_type_status_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gte=NON_NEGATIVE), name="payment_amount_non_negative"
            ),
            models.UniqueConstraint(
                fields=("provider", "external_transaction_id"),
                condition=models.Q(external_transaction_id__isnull=False),
                name="uniq_payment_transaction_per_provider",
            ),
        ]

    def __str__(self) -> str:
        return f"#{self.pk} {self.user.display_name} - {self.amount} so'm ({self.get_status_display()})"

    def clean(self) -> None:
        super().clean()
        if self.amount is not None and self.amount < NON_NEGATIVE:
            raise ValidationError({"amount": _("Summa manfiy bo'lishi mumkin emas.")})

    # -- helpers (small, non-business) ---------------------------------------
    @property
    def is_final(self) -> bool:
        return self.status in FINAL_PAYMENT_STATUSES

    @property
    def is_successful(self) -> bool:
        return self.status == PaymentStatus.SUCCESS

    def can_be_processed(self) -> bool:
        """Only a still-pending payment may transition to a final state."""
        return self.status == PaymentStatus.PENDING
