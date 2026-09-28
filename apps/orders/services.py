"""Write/business layer for the orders app.

This is the most safety critical module in the project. Its contract:

* **No business rule lives in ``Model.save()``.** Every state change goes
  through a function in this module.
* Every state change runs inside ``transaction.atomic()`` and locks the rows in
  a fixed order: first the *trip* row (``select_for_update``), then the *order*
  row. A consistent lock order is what prevents deadlocks between the
  "driver accepts" and "passenger cancels" flows.
* The price is snapshotted at creation, so later trip price changes never alter
  historical orders.
* Invalid transitions raise :class:`~apps.core.exceptions.InvalidOrderTransition`
  instead of silently writing a wrong status.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from django.db import connection, transaction
from django.utils import timezone

from apps.core.exceptions import (
    BusinessValidationError,
    DriverCannotBookOwnTrip,
    InvalidOrderState,
    InvalidOrderTransition,
    NotADriver,
    OrderNotFound,
    ResourceNotFound,
    TripNotActive,
    UnauthorizedOrderAccess,
    UserIsBlocked,
)
from apps.core.validators import normalize_phone_number
from apps.orders.constants import ALLOWED_TRANSITIONS, MAX_SEATS_PER_ORDER
from apps.orders.models import Order, OrderPassenger, OrderStatus
from apps.orders.selectors import get_order_by_id, get_orders_by_trip
from apps.rides.models import DriverTrip, DriverTripStatus
from apps.rides.services import release_seats, reserve_seats
from apps.users.models import User

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Locking helpers
# ---------------------------------------------------------------------------
def _lock_trip(trip_id: int) -> DriverTrip:
    queryset = DriverTrip.objects.all()
    if connection.features.has_select_for_update:
        queryset = DriverTrip.objects.select_for_update()
    return queryset.select_related("driver__user", "vehicle").get(pk=trip_id)


def _lock_order(order_id: int) -> Order:
    queryset = Order.objects.all()
    if connection.features.has_select_for_update:
        queryset = Order.objects.select_for_update()
    return queryset.select_related("trip__driver__user", "passenger").get(pk=order_id)


def _lock_trip_and_order(order: Order) -> tuple[DriverTrip, Order]:
    """Lock the trip row first, then the order row.

    This is the single place that implements the documented lock order, so no
    flow can accidentally take the two locks in the opposite order.
    """
    locked_trip = _lock_trip(order.trip_id)
    locked_order = _lock_order(order.pk)
    return locked_trip, locked_order


def _assert_transition(order: Order, target_status: str) -> None:
    allowed = ALLOWED_TRANSITIONS.get(order.status, frozenset())
    if target_status not in allowed:
        raise InvalidOrderTransition(
            f"'{order.get_status_display()}' holatidan '{OrderStatus(target_status).label}' holatiga "
            "o'tish mumkin emas.",
            details={"from": order.status, "to": target_status, "allowed": sorted(allowed)},
        )


# ---------------------------------------------------------------------------
# Creation
# ---------------------------------------------------------------------------
@transaction.atomic
def create_order(
    *,
    passenger: User,
    trip: DriverTrip,
    seats_booked: int,
    passenger_note: str = "",
    companion: dict | None = None,
) -> Order:
    """Create a ``PENDING`` order.

    Seats are **not** reserved here on purpose: a passenger may create several
    requests and the driver chooses which one to accept. A seat becomes
    guaranteed only in :func:`accept_order`, which is fully transaction safe.
    The only validation performed at creation time is that the request is
    *plausible* (enough free seats right now, not a trip the driver already
    closed).
    """
    if passenger.is_blocked:
        raise UserIsBlocked()

    driver_profile = getattr(passenger, "driver_profile", None)
    if driver_profile is not None and driver_profile.pk == trip.driver_id:
        raise DriverCannotBookOwnTrip()

    if seats_booked is None or seats_booked <= 0:
        raise BusinessValidationError("Kamida 1 ta o'rin band qilish kerak.")
    if seats_booked > MAX_SEATS_PER_ORDER:
        raise BusinessValidationError(f"Bir buyurtmada ko'pi bilan {MAX_SEATS_PER_ORDER} ta o'rin.")
    if trip.status not in (DriverTripStatus.ACTIVE, DriverTripStatus.FULL):
        raise TripNotActive()
    if seats_booked > trip.available_seats:
        from apps.core.exceptions import InsufficientSeats

        raise InsufficientSeats(
            details={"available_seats": trip.available_seats, "requested_seats": seats_booked}
        )

    # Snapshot the price. The order never reads the trip price again.
    price_per_seat = Decimal(trip.price_per_seat)
    total_amount = (price_per_seat * Decimal(seats_booked)).quantize(Decimal("0.01"))

    order = Order(
        trip=trip,
        passenger=passenger,
        seats_booked=seats_booked,
        price_per_seat=price_per_seat,
        total_amount=total_amount,
        status=OrderStatus.PENDING,
        passenger_note=passenger_note.strip(),
    )
    order.full_clean()
    order.save()

    if companion:
        add_order_passenger(order, **companion)

    _notify_driver(order)
    _sync_chat(order, "Buyurtma yaratildi. Haydovchi bilan suhbatlashishingiz mumkin.")

    logger.info("Buyurtma yaratildi: #%s (trip=%s, o'rin=%s)", order.pk, trip.pk, seats_booked)
    return order


@transaction.atomic
def add_order_passenger(
    order: Order,
    *,
    first_name: str,
    last_name: str = "",
    phone_number: str = "",
) -> OrderPassenger:
    """Attach an optional companion traveller to an order."""
    if order.is_terminal:
        raise InvalidOrderState("Yakunlangan buyurtmaga yo'lovchi qo'shib bo'lmaydi.")
    return OrderPassenger.objects.create(
        order=order,
        first_name=first_name.strip(),
        last_name=last_name.strip(),
        phone_number=normalize_phone_number(phone_number),
    )


# ---------------------------------------------------------------------------
# State transitions
# ---------------------------------------------------------------------------
@transaction.atomic
def accept_order(order: Order) -> Order:
    """Driver accepts the order and the seats are reserved atomically.

    Lock order: trip -> order. If two drivers of the same trip accept two
    competing orders for the last seat, the second transaction blocks on the
    trip row, re-reads ``available_seats`` after the first committed, and fails
    with :class:`~apps.core.exceptions.InsufficientSeats` instead of
    overbooking.
    """
    locked_trip, locked_order = _lock_trip_and_order(order)

    _assert_transition(locked_order, OrderStatus.ACCEPTED)

    if locked_order.passenger_id == locked_trip.driver.user_id:
        raise DriverCannotBookOwnTrip()

    # Seats were not reserved at creation time - reserve them now, atomically.
    reserve_seats(locked_trip, locked_order.seats_booked)

    locked_order.status = OrderStatus.ACCEPTED
    locked_order.accepted_at = timezone.now()
    locked_order.save(update_fields=["status", "accepted_at", "updated_at"])

    _notify_parties(locked_order, "order_accepted")
    _sync_chat(locked_order, "Buyurtma qabul qilindi. Haydovchi tez orada yoniga keladi.")
    return locked_order


@transaction.atomic
def reject_order(order: Order, *, reason: str = "") -> Order:
    """Driver rejects the order. No seats were held, so nothing to release."""
    locked_order = _lock_order(order.pk)
    _assert_transition(locked_order, OrderStatus.REJECTED)

    locked_order.status = OrderStatus.REJECTED
    if reason:
        locked_order.cancellation_reason = reason.strip()
    locked_order.save(update_fields=["status", "cancellation_reason", "updated_at"])

    _notify_parties(locked_order, "order_rejected")
    return locked_order


@transaction.atomic
def cancel_order_by_passenger(order: Order, *, reason: str = "") -> Order:
    """Passenger cancels. Seats are released if they were being held."""
    locked_trip, locked_order = _lock_trip_and_order(order)
    _assert_transition(locked_order, OrderStatus.CANCELLED_BY_PASSENGER)

    if locked_order.holds_seats:
        release_seats(locked_trip, locked_order.seats_booked)

    locked_order.status = OrderStatus.CANCELLED_BY_PASSENGER
    locked_order.cancelled_at = timezone.now()
    if reason:
        locked_order.cancellation_reason = reason.strip()
    locked_order.save(
        update_fields=["status", "cancelled_at", "cancellation_reason", "updated_at"]
    )

    _notify_parties(locked_order, "order_cancelled_by_passenger")
    _close_chat(locked_order, "Buyurtma yo'lovchi tomonidan bekor qilindi.")
    return locked_order


@transaction.atomic
def cancel_order_by_driver(order: Order, *, reason: str = "") -> Order:
    """Driver cancels. Seats are released if they were being held."""
    locked_trip, locked_order = _lock_trip_and_order(order)
    _assert_transition(locked_order, OrderStatus.CANCELLED_BY_DRIVER)

    if locked_order.holds_seats:
        release_seats(locked_trip, locked_order.seats_booked)

    locked_order.status = OrderStatus.CANCELLED_BY_DRIVER
    locked_order.cancelled_at = timezone.now()
    if reason:
        locked_order.cancellation_reason = reason.strip()
    locked_order.save(
        update_fields=["status", "cancelled_at", "cancellation_reason", "updated_at"]
    )

    _notify_parties(locked_order, "order_cancelled_by_driver")
    _close_chat(locked_order, "Buyurtma haydovchi tomonidan bekor qilindi.")
    return locked_order


@transaction.atomic
def mark_driver_arrived(order: Order) -> Order:
    locked_order = _lock_order(order.pk)
    _assert_transition(locked_order, OrderStatus.DRIVER_ARRIVED)
    locked_order.status = OrderStatus.DRIVER_ARRIVED
    locked_order.save(update_fields=["status", "updated_at"])
    _notify_parties(locked_order, "order_driver_arrived")
    return locked_order


@transaction.atomic
def start_order(order: Order) -> Order:
    """The ride has started. Seats stay held."""
    locked_order = _lock_order(order.pk)
    _assert_transition(locked_order, OrderStatus.IN_PROGRESS)
    locked_order.status = OrderStatus.IN_PROGRESS
    locked_order.save(update_fields=["status", "updated_at"])
    _notify_parties(locked_order, "order_in_progress")
    return locked_order


@transaction.atomic
def complete_order(order: Order) -> Order:
    """Complete the ride and release the seats from the pool.

    The seats are released (not reserved) because the trip has already consumed
    them; keeping the counter consistent matters more than the exact value once
    the trip is over. A completed order can never be cancelled afterwards.
    """
    locked_trip, locked_order = _lock_trip_and_order(order)
    _assert_transition(locked_order, OrderStatus.COMPLETED)

    if locked_order.holds_seats and locked_trip.status != DriverTripStatus.COMPLETED:
        release_seats(locked_trip, locked_order.seats_booked)

    locked_order.status = OrderStatus.COMPLETED
    locked_order.completed_at = timezone.now()
    locked_order.save(update_fields=["status", "completed_at", "updated_at"])
    _close_chat(locked_order, "Sayohat yakunlandi. Yo'lganiz yaxshi bo'lsin!")
    return locked_order


@transaction.atomic
def mark_no_show(order: Order, *, reason: str = "") -> Order:
    """Passenger did not show up: the seats go back to the pool."""
    locked_trip, locked_order = _lock_trip_and_order(order)
    _assert_transition(locked_order, OrderStatus.NO_SHOW)

    release_seats(locked_trip, locked_order.seats_booked)

    locked_order.status = OrderStatus.NO_SHOW
    locked_order.cancelled_at = timezone.now()
    if reason:
        locked_order.cancellation_reason = reason.strip()
    locked_order.save(
        update_fields=["status", "cancelled_at", "cancellation_reason", "updated_at"]
    )
    _close_chat(locked_order, "Yo'lovchi kelmadi.")
    return locked_order


# ---------------------------------------------------------------------------
# Lookups & authorisation
# ---------------------------------------------------------------------------
def get_required_order(order_id: int) -> Order:
    order = get_order_by_id(order_id)
    if order is None:
        raise OrderNotFound()
    return order


def assert_order_participant(order: Order, user: User) -> Order:
    """Raise unless ``user`` is the passenger or the driver of this order."""
    if not order.is_participant(user):
        raise UnauthorizedOrderAccess()
    return order


def get_driver_user_for_order(order: Order) -> User:
    driver_profile = getattr(order.trip.driver, "user", None)
    if driver_profile is None:  # pragma: no cover - defensive
        raise NotADriver()
    return driver_profile


def get_trip_orders(trip: DriverTrip) -> list[Order]:
    return list(get_orders_by_trip(trip))


def _notify_driver(order: Order) -> None:
    """Inform the driver about a brand new pending order."""
    from apps.notifications.services import create_new_order_notification_for_driver

    try:
        create_new_order_notification_for_driver(order)
    except Exception:  # pragma: no cover - notification must never break the flow
        logger.exception("Haydovchiga bildirishnoma yaratilmadi: order=%s", order.pk)


def _sync_chat(order: Order, text: str) -> None:
    """Open the thread for a non terminal order and write a system message."""
    from apps.chat import services as chat_services

    try:
        thread = chat_services.ensure_thread_for_order(order)
        if thread is not None:
            chat_services.create_system_message(thread, text)
    except Exception:  # pragma: no cover - chat must never break the flow
        logger.exception("Suhbat yangilanmadi: order=%s", order.pk)


def _close_chat(order: Order, text: str) -> None:
    """Write a final system message and close the thread.

    A terminal order cannot open a *new* thread, so an existing thread is
    looked up directly; when there is none there is simply nothing to close.
    """
    from apps.chat import services as chat_services
    from apps.chat.selectors import get_thread_by_order

    try:
        thread = get_thread_by_order(order)
        if thread is not None:
            chat_services.create_system_message(thread, text)
            chat_services.close_thread(thread)
    except Exception:  # pragma: no cover - chat must never break the flow
        logger.exception("Suhbat yopilmadi: order=%s", order.pk)


def _notify_parties(order: Order, reason: str) -> None:
    """Create notification records for both sides of the order.

    Notifications are *records* only. Delivering them to Telegram is the job of
    ``apps.notifications.services`` + a Celery task, which keeps this module free
    of any Telegram dependency.
    """
    from apps.notifications.services import create_order_notification

    try:
        create_order_notification(order, reason=reason)
    except Exception:  # pragma: no cover - notification must never break the flow
        logger.exception("Buyurtma bildirishnoma yaratilmadi: order=%s", order.pk)


__all__ = [
    "accept_order",
    "add_order_passenger",
    "cancel_order_by_driver",
    "cancel_order_by_passenger",
    "complete_order",
    "create_order",
    "get_required_order",
    "get_trip_orders",
    "mark_driver_arrived",
    "mark_no_show",
    "reject_order",
    "start_order",
    "assert_order_participant",
]
