"""Read/query layer for the notifications app."""

from __future__ import annotations

from django.db.models import Count, QuerySet
from django.utils import timezone

from apps.notifications.models import Notification, NotificationType


def get_notification_queryset() -> QuerySet[Notification]:
    return Notification.objects.select_related("user")


def get_notifications_for_user(user) -> QuerySet[Notification]:
    return get_notification_queryset().filter(user=user)


def get_unread_notifications(user) -> QuerySet[Notification]:
    return get_notifications_for_user(user).filter(is_read=False)


def get_unread_count(user) -> int:
    return get_unread_notifications(user).count()


def get_notification_by_id(notification_id: int) -> Notification | None:
    return get_notification_queryset().filter(pk=notification_id).first()


def get_pending_delivery(limit: int = 100) -> QuerySet[Notification]:
    """Notifications that still have to be pushed to an external channel."""
    return (
        get_notification_queryset()
        .filter(is_sent=False, user__is_blocked=False, user__telegram_id__isnull=False)
        .order_by("created_at")[:limit]
    )


def get_recent_notifications(user, limit: int = 20) -> QuerySet[Notification]:
    return get_notifications_for_user(user).order_by("-created_at")[:limit]


def get_notifications_by_type(notification_type: str) -> QuerySet[Notification]:
    return get_notification_queryset().filter(type=notification_type)


def get_unread_counts_for_users(user_ids) -> dict[int, int]:
    rows = (
        get_notification_queryset()
        .filter(user_id__in=user_ids, is_read=False)
        .values("user_id")
        .annotate(total=Count("id"))
    )
    return {row["user_id"]: row["total"] for row in rows}


def get_notifications_since(moment) -> QuerySet[Notification]:
    return get_notification_queryset().filter(created_at__gte=moment or timezone.now())


def get_system_notifications() -> QuerySet[Notification]:
    return get_notifications_by_type(NotificationType.SYSTEM)
