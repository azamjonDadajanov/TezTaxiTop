"""Async adapters between passenger bot handlers and Django services."""

from __future__ import annotations

import html
from datetime import date, datetime, time
from decimal import Decimal
from typing import Iterable

from asgiref.sync import sync_to_async
from django.utils import timezone

from apps.core.exceptions import ResourceNotFound
from apps.rides.constants import MATCHABLE_REQUEST_STATUSES
from bot.services.platform import _resolve_endpoint


def _create_passenger_request(
    *,
    user_id: int,
    origin,
    destination,
    departure_date: date,
    departure_time: time,
    passenger_count: int,
    max_price_per_seat: Decimal | int | None = None,
    comment: str = "",
):
    from apps.rides.services import create_passenger_request as create_request
    from apps.users.selectors import get_user_by_telegram_id

    passenger = get_user_by_telegram_id(user_id)
    if passenger is None:
        raise ResourceNotFound("Foydalanuvchi topilmadi.")

    endpoint_kwargs = _resolve_endpoint(
        origin, label="Jo'nash", point_key="origin", location_field="from_location"
    )
    endpoint_kwargs.update(
        _resolve_endpoint(
            destination, label="Borish", point_key="destination", location_field="to_location"
        )
    )

    departure_from = timezone.make_aware(datetime.combine(departure_date, departure_time))
    return create_request(
        passenger=passenger,
        passenger_count=passenger_count,
        max_price_per_seat=max_price_per_seat,
        departure_from=departure_from,
        comment=comment,
        **endpoint_kwargs,
    )


async def create_passenger_request(**request_data):
    """Create a passenger request from Telegram-facing values."""
    return await sync_to_async(_create_passenger_request)(**request_data)


def _get_passenger_requests(telegram_id: int, *, active_only: bool = False) -> list:
    from apps.rides.selectors import get_requests_by_passenger
    from apps.users.selectors import get_user_by_telegram_id

    passenger = get_user_by_telegram_id(telegram_id)
    if passenger is None:
        return []

    requests = get_requests_by_passenger(passenger)
    if active_only:
        requests = requests.filter(status__in=MATCHABLE_REQUEST_STATUSES)
    return list(requests)


async def get_my_requests(telegram_id: int) -> list:
    return await sync_to_async(_get_passenger_requests)(telegram_id)


async def get_active_requests(telegram_id: int) -> list:
    return await sync_to_async(_get_passenger_requests)(telegram_id, active_only=True)


def _get_passenger_orders(telegram_id: int) -> list:
    from apps.orders.selectors import get_orders_by_passenger
    from apps.users.selectors import get_user_by_telegram_id

    passenger = get_user_by_telegram_id(telegram_id)
    if passenger is None:
        return []
    return list(get_orders_by_passenger(passenger))


async def get_my_orders(telegram_id: int) -> list:
    return await sync_to_async(_get_passenger_orders)(telegram_id)


def _get_matching_trips(request_id: int) -> list:
    from apps.matching.services import get_ranked_matches
    from apps.rides.selectors import get_request_by_id

    passenger_request = get_request_by_id(request_id)
    if passenger_request is None:
        raise ResourceNotFound("Yo'lovchi so'rovi topilmadi.")
    return get_ranked_matches(passenger_request)


async def get_matching_trips(request_id: int) -> list:
    return await sync_to_async(_get_matching_trips)(request_id)


def format_matches_for_user(matches: Iterable) -> str:
    """Render ranked TripMatch objects as Telegram-safe HTML."""
    entries = []
    for match in matches:
        trip = match.trip
        driver = trip.driver.user
        driver_name = driver.display_name or driver.username
        departure = timezone.localtime(trip.departure_time).strftime("%d.%m.%Y %H:%M")
        entries.append(
            "\n".join(
                (
                    f"<b>{html.escape(trip.route_label())}</b>",
                    f"🕐 {departure} | 💺 {trip.available_seats}",
                    f"💰 {trip.price_per_seat:,.0f} so'm | "
                    f"⭐ {trip.driver.rating} | {html.escape(driver_name)}",
                )
            )
        )
    return "\n\n".join(entries)


def format_trip_for_user(trip) -> str:
    """Render a bookable driver trip as Telegram-safe HTML."""
    driver_user = trip.driver.user
    driver_name = driver_user.display_name or driver_user.username
    departure = timezone.localtime(trip.departure_time).strftime("%d.%m.%Y %H:%M")
    return "\n".join(
        (
            f"<b>{html.escape(trip.route_label())}</b>",
            f"🕐 {departure} | 💺 {trip.available_seats} ta bo'sh o'rin",
            f"💰 {trip.price_per_seat:,.0f} so'm/joy | "
            f"⭐ {trip.driver.rating} | {html.escape(driver_name)}",
        )
    )