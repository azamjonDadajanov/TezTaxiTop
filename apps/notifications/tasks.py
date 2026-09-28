"""Celery tasks that deliver notifications to external channels.

The notification records are created by the domain services; these tasks are
the *only* place that knows something about Telegram. A task is idempotent: a
notification is only ever marked ``is_sent`` when it was not sent before.
"""

from __future__ import annotations

import logging

from celery import shared_task
from django.db import transaction

from apps.notifications import selectors as notification_selectors
from apps.notifications import services as notification_services
from apps.notifications.constants import DELIVERY_BATCH_SIZE, RETENTION_DAYS
from apps.notifications.models import Notification

logger = logging.getLogger(__name__)


@shared_task(name="apps.notifications.tasks.deliver_pending_notifications_task")
def deliver_pending_notifications_task(limit: int = DELIVERY_BATCH_SIZE) -> dict:
    """Push unsent notifications to Telegram (best effort).

    Failures are recorded (``attempts`` + ``last_error``) and retried on the
    next scheduler run until ``MAX_DELIVERY_ATTEMPTS`` is reached, after which
    the row is parked for support instead of being retried forever.
    """
    from apps.core.telegram import get_telegram_gateway
    from apps.notifications.constants import MAX_DELIVERY_ATTEMPTS

    gateway = get_telegram_gateway()
    pending = notification_selectors.get_pending_delivery(limit=limit)
    sent = 0
    failed = 0
    dropped = 0

    for notification in pending:
        chat_id = notification.user.telegram_chat_id
        if chat_id is None:
            continue
        try:
            gateway.send_message(
                chat_id=chat_id,
                text=f"{notification.title}\n\n{notification.message}".strip(),
            )
        except Exception as exc:  # noqa: BLE001 - delivery must never kill the run
            failed += 1
            notification.record_failed_attempt(str(exc))
            if notification.attempts >= MAX_DELIVERY_ATTEMPTS:
                dropped += 1
                logger.error(
                    "Bildirishnoma #%s berilmay qoldi (%s urinish): %s",
                    notification.pk,
                    notification.attempts,
                    exc,
                )
            else:
                logger.warning("Bildirishnoma yuborilmadi (#%s): %s", notification.pk, exc)
            continue
        notification_services.mark_as_sent(notification)
        sent += 1

    logger.info(
        "Bildirishnomalar yuborildi: %s, muvaffaqiyatsiz: %s, tashlab ketildi: %s",
        sent,
        failed,
        dropped,
    )
    return {
        "sent": sent,
        "failed": failed,
        "dropped": dropped,
        "processed": len(pending),
    }


@shared_task(name="apps.notifications.tasks.send_notification_task")
def send_notification_task(notification_id: int) -> dict:
    """Deliver one notification immediately (used for time-critical events)."""
    from apps.core.telegram import get_telegram_gateway

    notification = notification_selectors.get_notification_by_id(notification_id)
    if notification is None:
        return {"sent": False, "reason": "not_found"}
    if notification.is_sent:
        return {"sent": True, "reason": "already_sent"}
    if notification.user.telegram_chat_id is None:
        return {"sent": False, "reason": "no_telegram"}

    try:
        get_telegram_gateway().send_message(
            chat_id=notification.user.telegram_chat_id,
            text=f"{notification.title}\n\n{notification.message}".strip(),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Bildirishnoma yuborilmadi (#%s): %s", notification.pk, exc)
        notification.record_failed_attempt(str(exc))
        return {"sent": False, "reason": str(exc)}

    notification_services.mark_as_sent(notification)
    return {"sent": True}


@shared_task(name="apps.notifications.tasks.cleanup_old_notifications_task")
def cleanup_old_notifications_task(days: int = RETENTION_DAYS) -> dict:
    """Delete old notifications the user has already seen (or already got).

    Notifications that are neither read nor sent are *kept*: they still have to
    reach the user and deleting them would silently drop a message.
    """
    from datetime import timedelta

    from django.db.models import Q
    from django.utils import timezone

    threshold = timezone.now() - timedelta(days=days)
    deleted, _ = Notification.objects.filter(created_at__lt=threshold).filter(
        Q(is_read=True) | Q(is_sent=True)
    ).delete()
    logger.info("Eski bildirishnomalar tozalandi: %s", deleted)
    return {"deleted": deleted}


@shared_task(name="apps.notifications.tasks.mark_all_read_for_user_task")
def mark_all_read_for_user_task(user_id: int) -> dict:
    """Convenience task used by the bot's /start command."""
    from apps.users.models import User

    with transaction.atomic():
        user = User.objects.filter(pk=user_id).first()
        if user is None:
            return {"updated": 0}
        return {"updated": notification_services.mark_all_as_read(user)}
