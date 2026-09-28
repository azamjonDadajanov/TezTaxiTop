"""Chat models: one thread per order, many messages per thread."""

from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel


class MessageType(models.TextChoices):
    TEXT = "text", "Matn"
    SYSTEM = "system", "Tizim"
    LOCATION = "location", "Manzil"


class ChatThread(TimeStampedModel):
    """Conversation between the driver of a trip and the passengers of an order.

    Created lazily the first time somebody opens the chat, so a thread always
    exists exactly when a conversation actually started.
    """

    order = models.OneToOneField(
        "orders.Order",
        on_delete=models.CASCADE,
        related_name="chat_thread",
        verbose_name="Buyurtma",
    )
    last_message_at = models.DateTimeField(
        verbose_name="Oxirgi xabar vaqti",
        null=True,
        blank=True,
        help_text="Ro'yxatni tez tartibga solish va 'yangi xabar' belgisini hisoblash uchun.",
    )
    last_message_preview = models.CharField(
        verbose_name="Oxirgi xabar ko'rinishi",
        max_length=120,
        blank=True,
        default="",
    )
    is_closed = models.BooleanField(
        verbose_name="Yopilgan",
        default=False,
        help_text="Yakunlangan yoki bekor qilingan buyurtma chatini yopish uchun ishlatiladi.",
    )

    class Meta:
        verbose_name = "Suhbat"
        verbose_name_plural = "Suhbatlar"
        ordering = ("-last_message_at", "-created_at")
        indexes = [
            models.Index(fields=("is_closed", "-last_message_at"), name="chat_closed_last_idx"),
        ]

    def __str__(self) -> str:
        return f"Chat #{self.order_id}"

    @property
    def is_open(self) -> bool:
        """Convenience flag: an open thread is not marked as closed."""
        return not self.is_closed

    @property
    def driver_user(self):
        return self.order.trip.driver.user

    @property
    def passenger_user(self):
        return self.order.passenger


class ChatMessage(TimeStampedModel):
    """One message inside a thread."""

    thread = models.ForeignKey(
        ChatThread,
        on_delete=models.CASCADE,
        related_name="messages",
        verbose_name="Suhbat",
    )
    sender = models.ForeignKey(
        "users.User",
        on_delete=models.PROTECT,
        related_name="chat_messages",
        verbose_name="Yuboruvchi",
    )
    type = models.CharField(
        verbose_name="Turi",
        max_length=10,
        choices=MessageType.choices,
        default=MessageType.TEXT,
    )
    text = models.TextField(verbose_name="Matn", max_length=2000, blank=True, default="")
    is_read = models.BooleanField(
        verbose_name="O'qilgan",
        default=False,
        help_text="Xabarni yuboruvchidan tashqari birinchi o'quvchi tomonidan o'qilgan.",
    )
    read_at = models.DateTimeField(verbose_name="O'qilgan vaqti", null=True, blank=True)

    class Meta:
        verbose_name = "Xabar"
        verbose_name_plural = "Xabarlar"
        ordering = ("created_at", "id")
        indexes = [
            # The polling query is "messages of this thread after id X".
            models.Index(fields=("thread", "id"), name="chatmsg_thread_id_idx"),
            models.Index(fields=("thread", "is_read"), name="chatmsg_thread_unread_idx"),
            models.Index(fields=("sender", "-created_at"), name="chatmsg_sender_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(text="") | models.Q(type=MessageType.LOCATION),
                name="chatmsg_text_required_unless_location",
            ),
        ]

    def __str__(self) -> str:
        return f"[{self.thread_id}] {self.sender_id}: {self.text[:40]}"
