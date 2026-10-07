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


def _schedule_delivery(notification_id: int) -> None:
    try:
        from apps.notifications.tasks import send_notification_task

        transaction.on_commit(lambda: send_notification_task.delay(notification_id))
    except Exception as e:
        logging.exception("Failed to schedule notification delivery for %s; Error: %s", notification_id, str(e))


@transaction.atomic
def create_notification(
    *,
    user: User,
    notification_type: str = NotificationType.SYSTEM,
    title: str = "",
    message: str = "",
) -> Notification:
    """Create one notification record and schedule immediate delivery."""
    if notification_type not in NotificationType.values:
        notification_type = NotificationType.SYSTEM
    notification = Notification.objects.create(
        user=user,
        type=notification_type,
        title=title[:200],
        message=message[:1000],
    )
    _schedule_delivery(notification.pk)
    return notification


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
    created = Notification.objects.bulk_create(notifications)
    for notif in created:
        _schedule_delivery(notif.pk)
    return created


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
    route = order.trip.route_label() if hasattr(order.trip, "route_label") else f"#{order.trip_id}"
    return create_notification(
        user=driver_user,
        notification_type=NotificationType.NEW_ORDER,
        title="Yangi buyurtma keldi",
        message=(
            f"{order.passenger.display_name} sizning '{route}' yo'nalishingizga "
            f"{order.seats_booked} ta o'rin band qilmoqchi."
        ),
    )


def create_order_notification(order, *, reason: str) -> list[Notification]:
    """Create notification records for order state transitions."""
    passenger_notification: Notification | None = None
    driver_notification: Notification | None = None
    route = order.trip.route_label() if hasattr(order.trip, "route_label") else f"#{order.trip_id}"

    if reason == "order_accepted":
        passenger_notification = create_notification(
            user=order.passenger,
            notification_type=NotificationType.ORDER_ACCEPTED,
            title="Buyurtmangiz qabul qilindi",
            message=(
                f"Haydovchi buyurtmangizni qabul qildi. Marshrut: {route}, "
                f"jo'nash: {order.trip.departure_time:%Y-%m-%d %H:%M}."
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
        driver_name = (
            order.trip.driver.user.display_name
            if hasattr(order.trip.driver, "user")
            else "Haydovchi"
        )
        passenger_notification = create_notification(
            user=order.passenger,
            notification_type=NotificationType.ORDER_DRIVER_ARRIVED,
            title="Haydovchi yetib keldi",
            message=f"Haydovchi {driver_name} olib ketish manziliga yetib keldi va sizni kutmoqda.",
        )
    elif reason == "order_in_progress":
        passenger_notification = create_notification(
            user=order.passenger,
            notification_type=NotificationType.ORDER_IN_PROGRESS,
            title="Safar boshlandi",
            message=f"{route} marshruti bo'yicha sayohat boshlandi. Oq yo'l!",
        )
    elif reason == "order_completed":
        passenger_notification = create_notification(
            user=order.passenger,
            notification_type=NotificationType.ORDER_COMPLETED,
            title="Safar yakunlandi",
            message=f"{route} safari muvaffaqiyatli yakunlandi. Xizmatimizdan foydalanganingiz uchun rahmat!",
        )
        driver_notification = create_notification(
            user=order.trip.driver.user,
            notification_type=NotificationType.ORDER_COMPLETED,
            title="Safar yakunlandi",
            message=f"{route} bo'yicha {order.passenger.display_name} bilan safar yakunlandi.",
        )
    elif reason == "order_no_show":
        passenger_notification = create_notification(
            user=order.passenger,
            notification_type=NotificationType.TRIP_CANCELLED,
            title="Yo'lovchi kelmadi",
            message="Siz belgilangan vaqtda kelmadingiz deb belgilandi va buyurtma bekor qilindi.",
        )

    created = [item for item in (passenger_notification, driver_notification) if item is not None]
    return created


def create_trip_cancelled_notification(trip) -> list[Notification]:
    """Inform every passenger holding an order on a cancelled trip."""
    order_passengers = trip.orders.exclude(
        status__in=(
            "rejected",
            "cancelled_by_passenger",
            "cancelled_by_driver",
            "completed",
        )
    ).select_related("passenger")
    route = trip.route_label() if hasattr(trip, "route_label") else f"#{trip.pk}"
    return create_notifications(
        users=[order.passenger for order in order_passengers],
        notification_type=NotificationType.TRIP_CANCELLED,
        title="Yo'lov bekor qilindi",
        message=(
            f"{route} yo'lovi haydovchi tomonidan bekor qilindi. Iltimos, boshqa mos safarni tanlang."
        ),
    )


def create_passenger_request_cancelled_notification(request) -> list[Notification]:
    """Inform active trip drivers if a booked request was cancelled."""
    route = request.route_label() if hasattr(request, "route_label") else f"#{request.pk}"
    return create_notifications(
        users=[request.passenger],
        notification_type=NotificationType.TRIP_CANCELLED,
        title="So'rov bekor qilindi",
        message=f"{route} bo'yicha so'rovingiz bekor qilindi.",
    )


def create_payment_notification(payment, *, success: bool) -> Notification:
    if success:
        return create_notification(
            user=payment.user,
            notification_type=NotificationType.PAYMENT_SUCCESS,
            title="To'lov muvaffaqiyatli",
            message=f"{payment.amount} so'm to'lovingiz muvaffaqiyatli tasdiqlandi.",
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
    sender_name = message.sender.display_name if hasattr(message, "sender") else "Suhbatdosh"
    return create_notification(
        user=recipient,
        notification_type=NotificationType.NEW_MESSAGE,
        title=f"Yangi xabar ({sender_name})",
        message=f"Buyurtma #{message.thread.order_id} bo'yicha: {message.text[:120]}",
    )


def create_review_notification(review) -> Notification:
    return create_notification(
        user=review.reviewed_user,
        notification_type=NotificationType.NEW_REVIEW,
        title=f"Yangi baho: {'⭐' * review.rating} ({review.rating}/5)",
        message=(
            f"{review.reviewer.display_name} sizga {review.rating} ballik baho qoldirdi.\n"
            f"Izoh: {review.comment or 'Izohsiz'}"
        ),
    )


def create_subscription_activated_notification(subscription) -> Notification:
    return create_notification(
        user=subscription.driver.user,
        notification_type=NotificationType.SUBSCRIPTION_ACTIVATED,
        title="Obuna faollashtirildi",
        message=(
            f"'{subscription.plan.name}' obunangiz muvaffaqiyatli faollashtirildi! "
            f"Muddati: {subscription.expires_at:%Y-%m-%d %H:%M} gacha."
        ),
    )


def create_subscription_expiring_notification(subscription, days: int) -> Notification:
    return create_notification(
        user=subscription.driver.user,
        notification_type=NotificationType.SUBSCRIPTION_EXPIRING,
        title=f"Obuna {days} kundan keyin tugaydi",
        message=(
            f"'{subscription.plan.name}' obunangiz {subscription.expires_at:%Y-%m-%d %H:%M} "
            "vaqtida tugaydi. Xizmatlardan uzluksiz foydalanish uchun yangi obuna xarid qiling."
        ),
    )


def create_subscription_expired_notification(subscription) -> Notification:
    return create_notification(
        user=subscription.driver.user,
        notification_type=NotificationType.SUBSCRIPTION_EXPIRED,
        title="Obuna muddati tugadi",
        message=(
            f"'{subscription.plan.name}' obunangiz muddati tugadi. "
            "Yangi yo'lovlar yaratish uchun obunani yangilang."
        ),
    )


def create_driver_verified_notification(driver_profile) -> Notification:
    return create_notification(
        user=driver_profile.user,
        notification_type=NotificationType.DRIVER_VERIFIED,
        title="Haydovchi profilingiz tasdiqlandi",
        message="Tabriklaymiz! Sizning haydovchi profilingiz administrator tomonidan muvaffaqiyatli tasdiqlandi.",
    )


def create_driver_rejected_notification(driver_profile, reason: str = "") -> Notification:
    return create_notification(
        user=driver_profile.user,
        notification_type=NotificationType.DRIVER_REJECTED,
        title="Haydovchi arizangiz rad etildi",
        message=f"Haydovchi arizangiz rad etildi. Sabab: {reason or REASON_NOT_GIVEN}",
    )


def create_vehicle_verified_notification(vehicle) -> Notification:
    return create_notification(
        user=vehicle.driver.user,
        notification_type=NotificationType.VEHICLE_VERIFIED,
        title="Avtomobilingiz tasdiqlandi",
        message=f"{vehicle.brand} {vehicle.model} ({vehicle.plate_number}) avtomobilingiz muvaffaqiyatli tasdiqlandi.",
    )


def create_vehicle_rejected_notification(vehicle, reason: str = "") -> Notification:
    return create_notification(
        user=vehicle.driver.user,
        notification_type=NotificationType.VEHICLE_REJECTED,
        title="Avtomobil rad etildi",
        message=f"{vehicle.brand} {vehicle.model} ({vehicle.plate_number}) avtomobili rad etildi. Sabab: {reason or REASON_NOT_GIVEN}",
    )


def create_match_found_notification(*, user: User, match_count: int = 1, route_label: str = "") -> Notification:
    return create_notification(
        user=user,
        notification_type=NotificationType.MATCH_FOUND,
        title="Yangi mos safar topildi",
        message=(
            f"Sizning '{route_label}' yo'nalishingiz bo'yicha {match_count} ta yangi mos safar topildi!"
            if route_label
            else f"Siz uchun {match_count} ta yangi mos safar topildi!"
        ),
    )


def create_passenger_request_expired_notification(request) -> Notification:
    route = request.route_label() if hasattr(request, "route_label") else f"#{request.pk}"
    return create_notification(
        user=request.passenger,
        notification_type=NotificationType.SYSTEM,
        title="So'rov muddati tugadi",
        message=f"'{route}' bo'yicha so'rovingizning jo'nash vaqti o'tganligi sababli yopildi.",
    )


def create_trip_expired_notification(trip) -> Notification:
    route = trip.route_label() if hasattr(trip, "route_label") else f"#{trip.pk}"
    return create_notification(
        user=trip.driver.user,
        notification_type=NotificationType.SYSTEM,
        title="Yo'lov muddati tugadi",
        message=f"'{route}' yo'lovingizning jo'nash vaqti o'tganligi sababli yopildi.",
    )


def create_support_ticket_notification(ticket) -> Notification:
    return create_notification(
        user=ticket.user,
        notification_type=NotificationType.SUPPORT_REPLY,
        title="Murojaatga javob berildi",
        message=(
            f"'{ticket.subject}' murojaatingizga administrator javob berdi. "
            "Xabarlarni ko'rish uchun qo'llab-quvvatlash bo'limiga o'ting."
        ),
    )


__all__ = [
    "Notification",
    "create_driver_rejected_notification",
    "create_driver_verified_notification",
    "create_match_found_notification",
    "create_new_message_notification",
    "create_new_order_notification_for_driver",
    "create_notification",
    "create_notifications",
    "create_order_notification",
    "create_passenger_request_cancelled_notification",
    "create_passenger_request_expired_notification",
    "create_payment_notification",
    "create_review_notification",
    "create_subscription_activated_notification",
    "create_subscription_expired_notification",
    "create_subscription_expiring_notification",
    "create_support_ticket_notification",
    "create_trip_cancelled_notification",
    "create_trip_expired_notification",
    "create_vehicle_rejected_notification",
    "create_vehicle_verified_notification",
    "get_required_notification",
    "mark_all_as_read",
    "mark_as_read",
    "mark_as_sent",
]
