"""Notification model."""

from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel


class NotificationType(models.TextChoices):
    NEW_ORDER = "new_order", "Yangi buyurtma"
    ORDER_ACCEPTED = "order_accepted", "Buyurtma qabul qilindi"
    ORDER_REJECTED = "order_rejected", "Buyurtma rad etildi"
    ORDER_DRIVER_ARRIVED = "order_driver_arrived", "Haydovchi yetib keldi"
    ORDER_IN_PROGRESS = "order_in_progress", "Safar boshlandi"
    ORDER_COMPLETED = "order_completed", "Safar yakunlandi"
    TRIP_CANCELLED = "trip_cancelled", "Yo'lov bekor qilindi"
    SUBSCRIPTION_ACTIVATED = "subscription_activated", "Obuna faollashtirildi"
    SUBSCRIPTION_EXPIRING = "subscription_expiring", "Obuna tugashiga yaqin"
    SUBSCRIPTION_EXPIRED = "subscription_expired", "Obuna muddati tugadi"
    PAYMENT_SUCCESS = "payment_success", "To'lov muvaffaqiyatli"
    PAYMENT_FAILED = "payment_failed", "To'lov muvaffaqiyatsiz"
    NEW_MESSAGE = "new_message", "Yangi xabar"
    NEW_REVIEW = "new_review", "Yangi baho"
    MATCH_FOUND = "match_found", "Mos safar topildi"
    DRIVER_VERIFIED = "driver_verified", "Haydovchi tasdiqlandi"
    DRIVER_REJECTED = "driver_rejected", "Haydovchi rad etildi"
    VEHICLE_VERIFIED = "vehicle_verified", "Avtomobil tasdiqlandi"
    VEHICLE_REJECTED = "vehicle_rejected", "Avtomobil rad etildi"
    SUPPORT_REPLY = "support_reply", "Murojaatga javob"
    SYSTEM = "system", "Tizim xabari"


class Notification(TimeStampedModel):
    """One in-app notification for one user.

    ``sent_at`` is set by the delivery task (Telegram / push / e-mail). It is
    intentionally part of the model rather than a Telegram specific field, so
    the same row can later be delivered through another channel as well.
    """

    user = models.ForeignKey(
        "users.User",
        on_delete=models.CASCADE,
        related_name="notifications",
        verbose_name="Foydalanuvchi",
        help_text="Bildirishnoma egasi. Foydalanuvchi o'chirilsa bildirishnomalari ham o'chadi.",
    )
    type = models.CharField(
        verbose_name="Turi",
        max_length=30,
        choices=NotificationType.choices,
        default=NotificationType.SYSTEM,
        db_index=True,
    )
    title = models.CharField(verbose_name="Sarlavha", max_length=200)
    message = models.TextField(verbose_name="Matn", max_length=1000, blank=True, default="")
    is_read = models.BooleanField(verbose_name="O'qildi", default=False, db_index=True)
    read_at = models.DateTimeField(
        verbose_name="O'qilgan vaqti",
        null=True,
        blank=True,
        help_text="Foydalanuvchi bildirishnomani birinchi marta ochgan vaqt.",
    )
    sent_at = models.DateTimeField(
        verbose_name="Yuborilgan vaqti",
        null=True,
        blank=True,
        help_text="Telegram (yoki boshqa kanal) orqali yuborilgan vaqt. Bo'sh bo'lsa yuborilmagan.",
    )
    is_sent = models.BooleanField(
        verbose_name="Yuborilgan",
        default=False,
        db_index=True,
        help_text="Yetkazib berish tizimi ushlu qilib yuborgan deb belgilagan.",
    )
    attempts = models.PositiveSmallIntegerField(
        verbose_name="Urinishlar soni",
        default=0,
        help_text="Telegram ga yuborish urinishlari. Maksimal urinishlar soni "
        "oshgandan keyin bildirishnoma 'berilgan' deb hisoblanadi va qayta "
        "yuborilmaydi.",
    )
    last_error = models.CharField(
        verbose_name="Oxirgi xato",
        max_length=255,
        blank=True,
        default="",
        help_text="Yetkazib berishdagi oxirgi xato matni (diagnostika uchun).",
    )

    class Meta:
        verbose_name = "Bildirishnoma"
        verbose_name_plural = "Bildirishnomalar"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("user", "is_read", "-created_at"), name="notif_user_read_idx"),
            models.Index(fields=("is_sent", "-created_at"), name="notif_sent_idx"),
            models.Index(fields=("type", "-created_at"), name="notif_type_created_idx"),
            models.Index(fields=("is_sent", "attempts"), name="notif_sent_attempts_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.user.display_name}: {self.title}"

    # -- helpers (small, non-business) ---------------------------------------
    def mark_read(self) -> None:
        from django.utils import timezone

        self.is_read = True
        self.read_at = timezone.now()
        self.save(update_fields=["is_read", "read_at", "updated_at"])

    def mark_sent(self) -> None:
        from django.utils import timezone

        self.is_sent = True
        self.sent_at = timezone.now()
        self.save(update_fields=["is_sent", "sent_at", "updated_at"])

    def record_failed_attempt(self, error: str) -> None:
        """Store a delivery failure and give up after ``MAX_DELIVERY_ATTEMPTS``.

        ``is_sent`` is set to ``True`` once the retry budget is exhausted: the
        row stays in the database for support/audit, but the scheduler stops
        picking it up (it is indexed on ``is_sent`` + ``attempts``).
        """
        from django.utils import timezone

        from apps.notifications.constants import MAX_DELIVERY_ATTEMPTS

        self.attempts = (self.attempts or 0) + 1
        self.last_error = (error or "")[:255]
        if self.attempts >= MAX_DELIVERY_ATTEMPTS:
            self.is_sent = True
            self.sent_at = timezone.now()
        self.save(update_fields=["attempts", "last_error", "is_sent", "sent_at", "updated_at"])
