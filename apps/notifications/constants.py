"""Constants for the notifications app."""

from __future__ import annotations

from apps.notifications.models import NotificationType

#: How many times a single notification is pushed to Telegram before it is
#: considered delivered-for-audit and removed from the delivery queue.
MAX_DELIVERY_ATTEMPTS = 5

#: How many notifications one scheduler run may push (protects the Telegram
#: rate limit and keeps the task short).
DELIVERY_BATCH_SIZE = 100

#: Read/sent notifications older than this are removed by the cleanup task.
RETENTION_DAYS = 90

__all__ = [
    "DELIVERY_BATCH_SIZE",
    "MAX_DELIVERY_ATTEMPTS",
    "RETENTION_DAYS",
    "NotificationType",
]
