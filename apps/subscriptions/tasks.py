"""Celery tasks for the subscriptions app.

Every task is **idempotent**: running it twice in a row must not change any
additional row, and running it when there is nothing to do must succeed
silently.
"""

from __future__ import annotations

import logging

from celery import shared_task
from django.utils import timezone

from apps.core import conf
from apps.subscriptions import selectors as subscription_selectors
from apps.subscriptions import services as subscription_services

logger = logging.getLogger(__name__)


@shared_task(name="apps.subscriptions.tasks.expire_subscriptions_task")
def expire_subscriptions_task() -> dict:
    """Hourly: mark every subscription whose end date has passed as expired."""
    expired = subscription_services.expire_due_subscriptions()
    logger.info("Muddati tugagan obunalar soni: %s", expired)
    return {"expired": expired}


@shared_task(name="apps.subscriptions.tasks.notify_expiring_subscriptions_task")
def notify_expiring_subscriptions_task() -> dict:
    """Daily: warn drivers whose subscription expires soon.

    Idempotent per day: a driver is notified at most once per subscription per
    day because the notification is stored in the database and the dispatcher
    skips records that already carry today's title.
    """
    from apps.notifications.models import NotificationType
    from apps.notifications.services import create_notification

    days = conf.SUBSCRIPTION_EXPIRING_WARNING_DAYS
    subscriptions = subscription_selectors.get_expiring_subscriptions(days)
    notified = 0

    for subscription in subscriptions:
        title = f"Obuna {days} kundan keyin tugaydi"
        already_notified = subscription.driver.user.notifications.filter(
            type=NotificationType.SUBSCRIPTION_EXPIRING, title=title
        ).exists()
        if already_notified:
            continue
        create_notification(
            user=subscription.driver.user,
            notification_type=NotificationType.SUBSCRIPTION_EXPIRING,
            title=title,
            message=(
                f"'{subscription.plan.name}' obunangiz {subscription.expires_at:%Y-%m-%d %H:%M} "
                "vaqti bilan tugaydi. Davom ettirish uchun yangi obuna xarid qiling."
            ),
        )
        notified += 1

    logger.info("Obuna ogohlantirishlari yuborildi: %s", notified)
    return {"notified": notified}


@shared_task(name="apps.subscriptions.tasks.send_expired_subscription_notification_task")
def send_expired_subscription_notification_task(subscription_id: int) -> dict:
    """Notify one driver that their subscription has just expired."""
    from apps.notifications.models import NotificationType
    from apps.notifications.services import create_notification

    subscription = subscription_services.get_subscription_or_raise(subscription_id)
    if subscription.status != "expired" and subscription.expires_at > timezone.now():
        return {"skipped": True}

    create_notification(
        user=subscription.driver.user,
        notification_type=NotificationType.SUBSCRIPTION_EXPIRED,
        title="Obuna muddati tugadi",
        message=(
            f"'{subscription.plan.name}' obunangiz {subscription.expires_at:%Y-%m-%d %H:%M} "
            "vaqti bilan tugadi. Yangi yo'lov yaratish uchun obunani yangilang."
        ),
    )
    return {"notified": True}
