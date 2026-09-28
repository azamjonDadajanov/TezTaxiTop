"""Write/business layer for the chat app.

Rules:
* only the driver and the passengers of the thread's order may send/read;
* a thread is created on demand for an order in a state where chatting makes
  sense (``pending``, ``accepted``, ``driver_arrived``, ``in_progress``);
* the thread can be closed only by the system (completed / cancelled orders);
* sending a message refreshes ``last_message_at`` and the preview so the chat
  list never shows stale information;
* system messages (order accepted, driver arrived, ...) are written by the
  order service, not by clients, and therefore carry a ``system`` type.
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from apps.chat.models import ChatMessage, ChatThread, MessageType
from apps.chat.selectors import get_message_queryset, get_thread_by_order
from apps.core.exceptions import (
    ChatClosed,
    EmptyMessage,
    ResourceNotFound,
    UnauthorizedChatAccess,
)
from apps.orders.constants import CHAT_ALLOWED_ORDER_STATUSES
from apps.users.models import User

logger = logging.getLogger(__name__)

MAX_MESSAGE_LENGTH = 2000
PREVIEW_LENGTH = 120


def _assert_user_is_participant(thread: ChatThread, user: User) -> None:
    order = thread.order
    if not order.is_participant(user):
        raise UnauthorizedChatAccess("Bu suhbatga faqat ishtirokchilar kirishi mumkin.")
    if user.is_blocked:
        raise UnauthorizedChatAccess("Bloklangan foydalanuvchi xabar yubora olmaydi.")


def _assert_thread_open(thread: ChatThread) -> None:
    if thread.is_closed:
        raise ChatClosed("Suhbat yopilgan, yangi xabar yuborib bo'lmaydi.")


def _assert_order_chat_allowed(thread: ChatThread) -> None:
    if thread.order.status not in CHAT_ALLOWED_ORDER_STATUSES:
        raise ChatClosed(
            f"Bu buyurtma holatida suhbat yopiq ({thread.order.get_status_display()})."
        )


@transaction.atomic
def get_or_create_thread(order) -> ChatThread:
    """Return the thread of an order, creating it on first use."""
    thread = get_thread_by_order(order)
    if thread is not None:
        return thread
    if order.status not in CHAT_ALLOWED_ORDER_STATUSES:
        raise ChatClosed(
            f"Bu buyurtma holatida suhbat yopiq ({order.get_status_display()})."
        )
    thread = ChatThread.objects.create(order=order)
    logger.info("Buyurtma #%s uchun suhbat yaratildi", order.pk)
    return thread


@transaction.atomic
def ensure_thread_for_order(order) -> ChatThread | None:
    """Idempotent helper used by the order service; never raises."""
    thread = get_thread_by_order(order)
    if thread is not None:
        return thread
    if order.status not in CHAT_ALLOWED_ORDER_STATUSES:
        return None
    return ChatThread.objects.create(order=order)


@transaction.atomic
def send_message(*, thread: ChatThread, sender: User, text: str, message_type: str = MessageType.TEXT) -> ChatMessage:
    """Send a text (or location) message inside a thread."""
    _assert_user_is_participant(thread, sender)
    _assert_thread_open(thread)
    _assert_order_chat_allowed(thread)

    clean_text = (text or "").strip()
    if not clean_text and message_type == MessageType.TEXT:
        raise EmptyMessage("Xabar matni bo'sh bo'lishi mumkin emas.")
    if len(clean_text) > MAX_MESSAGE_LENGTH:
        clean_text = clean_text[:MAX_MESSAGE_LENGTH]

    message = ChatMessage.objects.create(
        thread=thread,
        sender=sender,
        type=message_type,
        text=clean_text,
    )
    thread.last_message_at = message.created_at
    thread.last_message_preview = clean_text[:PREVIEW_LENGTH]
    thread.save(update_fields=["last_message_at", "last_message_preview", "updated_at"])
    return message


@transaction.atomic
def create_system_message(thread: ChatThread, text: str) -> ChatMessage:
    """Write a system message into the thread (driver identity is used as author)."""
    system_user = thread.order.trip.driver.user
    message = ChatMessage.objects.create(
        thread=thread,
        sender=system_user,
        type=MessageType.SYSTEM,
        text=text.strip()[:MAX_MESSAGE_LENGTH],
    )
    thread.last_message_at = message.created_at
    thread.last_message_preview = message.text[:PREVIEW_LENGTH]
    thread.save(update_fields=["last_message_at", "last_message_preview", "updated_at"])
    return message


@transaction.atomic
def mark_messages_read(thread: ChatThread, reader: User) -> int:
    """Mark the whole thread as read for ``reader``. Idempotent.

    ``ChatMessage.is_read`` is a *thread level* flag: a thread has exactly two
    participants, so "the other side has seen the conversation" is unambiguous.
    Marking the reader's own messages as read too is harmless (unread counters
    always exclude the reader) and is required to clear system messages, which
    are authored by the driver and would otherwise stay unread forever.
    """
    _assert_user_is_participant(thread, reader)
    now = timezone.now()
    return get_message_queryset().filter(thread=thread, is_read=False).update(
        is_read=True, read_at=now, updated_at=now
    )


@transaction.atomic
def close_thread(thread: ChatThread) -> ChatThread:
    """Close a thread (system use only, e.g. completed or cancelled order)."""
    if thread.is_closed:
        return thread
    thread.is_closed = True
    thread.save(update_fields=["is_closed", "updated_at"])
    return thread


def get_required_thread(thread_id: int) -> ChatThread:
    from apps.chat.selectors import get_thread_by_id

    thread = get_thread_by_id(thread_id)
    if thread is None:
        raise ResourceNotFound("Suhbat topilmadi.")
    return thread


__all__ = [
    "close_thread",
    "create_system_message",
    "ensure_thread_for_order",
    "get_or_create_thread",
    "get_required_thread",
    "mark_messages_read",
    "send_message",
]
