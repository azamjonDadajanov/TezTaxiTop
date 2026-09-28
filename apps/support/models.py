"""Support ticket models.

* A ticket is a conversation between the requesting user and the support team,
  therefore one ``SupportTicket`` row plus many ``SupportMessage`` rows.
* ``order`` is optional: users can write about anything (payment, verification,
  a technical problem), but linking an order lets support see the context.
* ``status`` is a small, explicit state machine: ``open`` -> ``in_progress`` ->
  ``closed`` (or ``closed`` directly). Only staff may change it.
"""

from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel


class TicketStatus(models.TextChoices):
    OPEN = "open", "Ochiq"
    IN_PROGRESS = "in_progress", "Ko'rib chiqilmoqda"
    CLOSED = "closed", "Yopilgan"


class TicketPriority(models.TextChoices):
    LOW = "low", "Past"
    NORMAL = "normal", "O'rtacha"
    HIGH = "high", "Yuqori"
    URGENT = "urgent", "Shoshilinch"


class SupportTicket(TimeStampedModel):
    """A support request opened by a user."""

    user = models.ForeignKey(
        "users.User",
        on_delete=models.PROTECT,
        related_name="support_tickets",
        verbose_name="Foydalanuvchi",
    )
    order = models.ForeignKey(
        "orders.Order",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="support_tickets",
        verbose_name="Buyurtma",
        help_text="Ixtiyoriy: buyurtma bilan bog'liq murojaat bo'lsa.",
    )
    subject = models.CharField(verbose_name="Mavzu", max_length=200)
    category = models.CharField(
        verbose_name="Kategoriya",
        max_length=30,
        choices=[
            ("payment", "To'lov"),
            ("subscription", "Obuna"),
            ("ride", "Yo'lov"),
            ("verification", "Tasdiqlash"),
            ("account", "Akkaunt"),
            ("technical", "Texnik"),
            ("other", "Boshqa"),
        ],
        default="other",
        db_index=True,
    )
    priority = models.CharField(
        verbose_name="Ustuvorlik",
        max_length=10,
        choices=TicketPriority.choices,
        default=TicketPriority.NORMAL,
        db_index=True,
    )
    status = models.CharField(
        verbose_name="Holati",
        max_length=15,
        choices=TicketStatus.choices,
        default=TicketStatus.OPEN,
        db_index=True,
    )
    is_anonymous = models.BooleanField(
        verbose_name="Anonim murojaat",
        default=False,
        help_text="Telegram orqali yuborilgan va foydalanuvchining ismi ko'rsatilmasin.",
    )
    last_message_at = models.DateTimeField(verbose_name="Oxirgi xabar vaqti", null=True, blank=True)
    closed_at = models.DateTimeField(verbose_name="Yopilgan vaqti", null=True, blank=True)

    class Meta:
        verbose_name = "Qo'llab-quvvatlash murojaati"
        verbose_name_plural = "Qo'llab-quvvatlash murojaatlari"
        ordering = ("-last_message_at", "-created_at")
        indexes = [
            models.Index(fields=("status", "-created_at"), name="support_status_created_idx"),
            models.Index(fields=("category", "status"), name="support_cat_status_idx"),
            models.Index(fields=("priority", "status"), name="support_prio_status_idx"),
            models.Index(fields=("user", "-created_at"), name="support_user_created_idx"),
        ]

    def __str__(self) -> str:
        return f"#{self.pk} {self.subject} ({self.get_status_display()})"

    @property
    def is_closed(self) -> bool:
        return self.status == TicketStatus.CLOSED

    @property
    def is_open(self) -> bool:
        return self.status in {TicketStatus.OPEN, TicketStatus.IN_PROGRESS}


class SupportMessage(TimeStampedModel):
    """One message inside a support ticket (from the user or from support)."""

    ticket = models.ForeignKey(
        SupportTicket,
        on_delete=models.CASCADE,
        related_name="messages",
        verbose_name="Murojaat",
    )
    sender = models.ForeignKey(
        "users.User",
        on_delete=models.PROTECT,
        related_name="support_messages",
        verbose_name="Yuboruvchi",
    )
    body = models.TextField(verbose_name="Matn", max_length=4000)
    is_from_support = models.BooleanField(verbose_name="Qo'llab-quvvatlashdan", default=False)
    attachment_url = models.URLField(verbose_name="Fayl havolasi", blank=True, default="")

    class Meta:
        verbose_name = "Murojaat xabari"
        verbose_name_plural = "Murojaat xabarlari"
        ordering = ("created_at", "id")
        indexes = [
            models.Index(fields=("ticket", "id"), name="supportmsg_ticket_id_idx"),
        ]

    def __str__(self) -> str:
        return f"[{self.ticket_id}] {self.sender_id}: {self.body[:40]}"
