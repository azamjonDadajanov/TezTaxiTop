"""Read/query layer for the orders app."""

from __future__ import annotations

from typing import Sequence

from django.db.models import Q, QuerySet

from apps.orders.models import Order, OrderPassenger, OrderStatus

#: Fields the Django admin can search by.
ORDER_SEARCH_FIELDS: Sequence[str] = (
    "id",
    "passenger__first_name",
    "passenger__last_name",
    "passenger__username",
    "passenger__phone_number",
    "passenger__telegram_id",
    "trip__driver__user__first_name",
    "trip__driver__user__last_name",
    "trip__driver__user__phone_number",
    "trip__vehicle__plate_number",
    "trip__from_location__name",
    "trip__to_location__name",
)

#: Fields the Django admin can order by.
ORDER_ORDERING_FIELDS: Sequence[str] = (
    "id",
    "status",
    "total_amount",
    "seats_booked",
    "created_at",
    "accepted_at",
    "completed_at",
)


def get_order_queryset() -> QuerySet[Order]:
    """Optimised base queryset: trip, driver, user and both locations."""
    return Order.objects.select_related(
        "passenger",
        "trip__driver__user",
        "trip__vehicle",
        "trip__from_location",
        "trip__to_location",
    ).prefetch_related("passengers")


def get_orders() -> QuerySet[Order]:
    return get_order_queryset()


def get_order_by_id(order_id: int) -> Order | None:
    return get_order_queryset().filter(pk=order_id).first()


def get_orders_by_passenger(passenger) -> QuerySet[Order]:
    return get_order_queryset().filter(passenger=passenger)


def get_orders_by_driver(driver_profile) -> QuerySet[Order]:
    return get_order_queryset().filter(trip__driver=driver_profile)


def get_orders_by_trip(trip) -> QuerySet[Order]:
    return get_order_queryset().filter(trip=trip)


def get_pending_orders() -> QuerySet[Order]:
    return get_order_queryset().filter(status=OrderStatus.PENDING)


def get_active_orders() -> QuerySet[Order]:
    return get_order_queryset().active()


def get_completed_orders() -> QuerySet[Order]:
    return get_order_queryset().filter(status=OrderStatus.COMPLETED)


def get_reviewable_orders(user) -> QuerySet[Order]:
    """Completed orders the user participated in and has not reviewed yet."""
    from apps.reviews.models import Review

    driver_profile = getattr(user, "driver_profile", None)
    condition = Q(trip__driver__user=user)
    if driver_profile is not None:
        condition |= Q(trip__driver=driver_profile)
    return (
        get_order_queryset()
        .filter(status=OrderStatus.COMPLETED)
        .filter(condition)
        .exclude(reviews__reviewer=user)
        .distinct()
    )


def search_orders(queryset: QuerySet[Order], search_term: str | None) -> QuerySet[Order]:
    if not search_term:
        return queryset
    term = search_term.strip()
    return queryset.filter(
        Q(passenger__first_name__icontains=term)
        | Q(passenger__last_name__icontains=term)
        | Q(passenger__username__icontains=term)
        | Q(passenger__phone_number__icontains=term)
        | Q(passenger__telegram_id__icontains=term.replace("+", ""))
        | Q(trip__driver__user__first_name__icontains=term)
        | Q(trip__driver__user__last_name__icontains=term)
        | Q(trip__driver__user__phone_number__icontains=term)
        | Q(trip__vehicle__plate_number__icontains=term)
        | Q(trip__from_location__name__icontains=term)
        | Q(trip__to_location__name__icontains=term)
    )


def get_order_passengers(order: Order) -> QuerySet[OrderPassenger]:
    return OrderPassenger.objects.filter(order=order)


def get_participant_user_ids(order: Order) -> tuple[int, int]:
    """``(passenger_id, driver_user_id)`` - used by chat and notifications."""
    return order.passenger_id, order.driver_user_id
