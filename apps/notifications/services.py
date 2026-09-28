"""Write/business layer for the notifications app.

The whole module follows one rule: **create a record, deliver later**.

``create_notification`` (and its helpers) never touch Telegram. A Celery task
(:mod:`apps.notifications.tasks`) picks up rows where ``is_sent = False`` and
hands them to a channel gateway. As a result the domain services (orders, chat,
payments, ...) stay completely Telegram agnostic.
"""

from __future__ import annotations

import logging
from typing import Iterable

from django.db import transaction
from django.utils import timezone

from apps.notifications.models import Notification, NotificationType
from apps.notifications.selectors import get_notification_by_id, get_unread_notifications
from apps.users.models import User

logger = logging.getLogger(__name__)

#: Uzbek text used when a cancellation reason was not provided.
REASON_NOT_GIVEN = "ko'rsatilmagan"

#: Uzbek text used when a payment failed without a provider reason.
UNKNOWN_REASON = "noma'lum sabab"


@transaction.atomic
def create_notification(
    *,
    user: User,
    notification_type: str = NotificationType.SYSTEM,
    title: str = "",
    message: str = "",
) -> Notification:
    """Create one notification record. Delivery happens later."""
    if notification_type not in NotificationType.values:
        notification_type = NotificationType.SYSTEM
    return Notification.objects.create(
        user=user,
        type=notification_type,
        title=title[:200],
        message=message[:1000],
    )


def create_notifications(
    *,
    users: Iterable[User],
    notification_type: str = NotificationType.SYSTEM,
    title: str = "",
    message: str = "",
) -> list[Notification]:
    """Bulk creation used when several users must be informed at once."""
    notifications = [
        Notification(
            user=user,
            type=notification_type if notification_type in NotificationType.values else NotificationType.SYSTEM,
            title=title[:200],
            message=message[:1000],
        )
        for user in users
        if user is not None
    ]
    if not notifications:
        return []
    return Notification.objects.bulk_create(notifications)


@transaction.atomic
def mark_as_read(notification: Notification) -> Notification:
    if not notification.is_read:
        notification.is_read = True
        notification.read_at = timezone.now()
        notification.save(update_fields=["is_read", "read_at", "updated_at"])
    return notification


@transaction.atomic
def mark_all_as_read(user: User) -> int:
    """Mark every unread notification of a user as read. Idempotent."""
    return get_unread_notifications(user).update(
        is_read=True, read_at=timezone.now(), updated_at=timezone.now()
    )


@transaction.atomic
def mark_as_sent(notification: Notification) -> Notification:
    """Called by the delivery task once the message really left the system."""
    if notification.is_sent:
        return notification
    notification.is_sent = True
    notification.sent_at = timezone.now()
    notification.save(update_fields=["is_sent", "sent_at", "updated_at"])
    return notification


def get_required_notification(notification_id: int) -> Notification:
    from apps.core.exceptions import ResourceNotFound

    notification = get_notification_by_id(notification_id)
    if notification is None:
        raise ResourceNotFound("Bildirishnoma topilmadi.")
    return notification


# ---------------------------------------------------------------------------
# Domain specific helpers
# ---------------------------------------------------------------------------
def create_new_order_notification_for_driver(order) -> Notification | None:
    driver_user = order.trip.driver.user
    return create_notification(
        user=driver_user,
        notification_type=NotificationType.NEW_ORDER,
        title="Yangi buyurtma",
        message=(
            f"{order.passenger.display_name} sizning '{order.trip.route_label()}' yo'loviga "
            f"{order.seats_booked} ta o'rin band qilmoqchi."
        ),
    )


def create_order_notification(order, *, reason: str) -> list[Notification]:
    """Create the notification pair for any order state change.

    ``reason`` values used by :mod:`apps.orders.services`:
    ``order_accepted``, ``order_rejected``, ``order_cancelled_by_passenger``,
    ``order_cancelled_by_driver``, ``order_driver_arrived``, ``order_in_progress``.
    """
    passenger_notification: Notification | None = None
    driver_notification: Notification | None = None

    if reason == "order_accepted":
        passenger_notification = create_notification(
            user=order.passenger,
            notification_type=NotificationType.ORDER_ACCEPTED,
            title="Buyurtmangiz qabul qilindi",
            message=(
                f"Haydovchi buyurtmangizni qabul qildi. Marshrut: {order.trip.route_label()}, "
                f"chuqish: {order.trip.departure_time:%Y-%m-%d %H:%M}."
            ),
        )
    elif reason == "order_rejected":
        passenger_notification = create_notification(
            user=order.passenger,
            notification_type=NotificationType.ORDER_REJECTED,
            title="Buyurtma rad etildi",
            message=(
                f"Haydovchi buyurtmangizni rad etdi. Sabab: "
                f"{order.cancellation_reason or REASON_NOT_GIVEN}"
            ),
        )
    elif reason == "order_cancelled_by_passenger":
        driver_notification = create_notification(
            user=order.trip.driver.user,
            notification_type=NotificationType.TRIP_CANCELLED,
            title="Buyurtma bekor qilindi",
            message=(
                f"{order.passenger.display_name} buyurtmani bekor qildi. Sabab: "
                f"{order.cancellation_reason or REASON_NOT_GIVEN}"
            ),
        )
    elif reason == "order_cancelled_by_driver":
        passenger_notification = create_notification(
            user=order.passenger,
            notification_type=NotificationType.TRIP_CANCELLED,
            title="Yo'lov bekor qilindi",
            message=(
                f"Haydovchi yo'lovni bekor qildi. Sabab: "
                f"{order.cancellation_reason or REASON_NOT_GIVEN}"
            ),
        )
    elif reason == "order_driver_arrived":
        passenger_notification = create_notification(
            user=order.passenger,
            notification_type=NotificationType.SYSTEM,
            title="Haydovchi yetib keldi",
            message="Haydovchi sizni kutmoqda. Iltimos, tayyor bo'ling.",
        )
    elif reason == "order_in_progress":
        passenger_notification = create_notification(
            user=order.passenger,
            notification_type=NotificationType.SYSTEM,
            title="Yo'lga chiqdik",
            message=f"{order.trip.route_label()} marshruti bo'yicha sayohat boshlandi.",
        )

    created = [item for item in (passenger_notification, driver_notification) if item is not None]
    return created


def create_trip_cancelled_notification(trip) -> list[Notification]:
    """Inform every passenger holding an order on a cancelled trip."""
    from apps.notifications.models import Notification as NotificationModel

    order_passengers = trip.orders.exclude(
        status__in=(
            "rejected",
            "cancelled_by_passenger",
            "cancelled_by_driver",
            "completed",
        )
    ).select_related("passenger")
    return create_notifications(
        users=[order.passenger for order in order_passengers],
        notification_type=NotificationType.TRIP_CANCELLED,
        title="Yo'lov bekor qilindi",
        message=(
            f"{trip.route_label()} yo'lovi bekor qilindi. Iltimos, boshqa yo'lov tanlang."
        ),
    )


def create_payment_notification(payment, *, success: bool) -> Notification:
    if success:
        return create_notification(
            user=payment.user,
            notification_type=NotificationType.PAYMENT_SUCCESS,
            title="To'lov muvaffaqiyatli",
            message=f"{payment.amount} so'm to'lovingiz tasdiqlandi.",
        )
    return create_notification(
        user=payment.user,
        notification_type=NotificationType.PAYMENT_FAILED,
        title="To'lov muvaffaqiyatsiz",
        message=(
            f"To'lovni amalga oshirib bo'lmadi. Sabab: {payment.failure_reason or UNKNOWN_REASON}"
        ),
    )


def create_new_message_notification(message, *, recipient: User) -> Notification:
    return create_notification(
        user=recipient,
        notification_type=NotificationType.NEW_MESSAGE,
        title="Yangi xabar",
        message=f"Buyurtma #{message.thread.order_id} bo'yicha yangi xaboringiz bor.",
    )


def create_support_ticket_notification(ticket) -> Notification:
    return create_notification(
        user=ticket.user,
        notification_type=NotificationType.SYSTEM,
        title="Murojaatga javob berildi",
        message=(
            f"'{ticket.subject}' murojaatingizga administrator javob berdi. "
            "Xabarlarni ko'rish uchun qo'llab-quvvatlash bo'limiga o'ting."
        ),
    )


__all__ = [
    "Notification",
    "create_new_message_notification",
    "create_new_order_notification_for_driver",
    "create_notification",
    "create_notifications",
    "create_order_notification",
    "create_payment_notification",
    "create_support_ticket_notification",
    "create_trip_cancelled_notification",
    "get_required_notification",
    "mark_all_as_read",
    "mark_as_read",
    "mark_as_sent",
]
