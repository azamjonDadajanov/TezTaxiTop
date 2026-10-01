"""Async adapters for backend operations exposed by bot menu handlers."""

from __future__ import annotations

from asgiref.sync import sync_to_async

from apps.core.exceptions import ResourceNotFound, UnauthorizedOrderAccess


def _get_user(telegram_id: int):
    from apps.users.selectors import get_user_by_telegram_id

    user = get_user_by_telegram_id(telegram_id)
    if user is None:
        raise ResourceNotFound("Foydalanuvchi topilmadi.")
    return user


async def get_user(telegram_id: int):
    return await sync_to_async(_get_user)(telegram_id)


def _update_profile(telegram_id: int, **changes):
    from apps.users.services import update_user_profile

    return update_user_profile(_get_user(telegram_id), **changes)


async def update_profile(telegram_id: int, **changes):
    return await sync_to_async(_update_profile)(telegram_id, **changes)


def _register_driver(telegram_id: int):
    from apps.users.services import register_as_driver

    return register_as_driver(_get_user(telegram_id))


async def register_driver(telegram_id: int):
    return await sync_to_async(_register_driver)(telegram_id)


def _set_user_role(telegram_id: int, role: str):
    from apps.users.services import set_user_role

    return set_user_role(_get_user(telegram_id), role)


async def set_user_role(telegram_id: int, role: str):
    return await sync_to_async(_set_user_role)(telegram_id, role)


def _driver_vehicles(telegram_id: int):
    from apps.vehicles.services import get_driver_vehicles
    from apps.users.services import get_required_driver_profile

    return get_driver_vehicles(get_required_driver_profile(_get_user(telegram_id)))


async def get_driver_vehicles(telegram_id: int):
    return await sync_to_async(_driver_vehicles)(telegram_id)


def _create_vehicle(telegram_id: int, **vehicle_data):
    from apps.users.services import get_required_driver_profile
    from apps.vehicles.services import create_vehicle

    driver = get_required_driver_profile(_get_user(telegram_id))
    return create_vehicle(driver=driver, **vehicle_data)


async def create_vehicle(telegram_id: int, **vehicle_data):
    return await sync_to_async(_create_vehicle)(telegram_id, **vehicle_data)


def _resolve_endpoint(value, *, label: str, point_key: str, location_field: str) -> dict:
    """Accept either a route point payload or a catalogue ``Location`` id.

    The bot sends raw coordinates, but a caller holding a catalogue id keeps
    working: the two shapes map onto the two ways a route endpoint can be
    described in :func:`apps.rides.services.create_trip`.
    """
    from apps.locations.selectors import get_location_by_id

    if isinstance(value, dict):
        return {point_key: dict(value)}
    location = get_location_by_id(value)
    if location is None:
        raise ResourceNotFound(f"{label} manzili topilmadi.")
    return {location_field: location}


def _create_trip(telegram_id: int, vehicle_id: int, origin, destination, **trip_data):
    from apps.rides.services import assert_driver_can_create_trip, create_trip
    from apps.users.selectors import get_user_by_telegram_id
    from apps.vehicles.selectors import get_vehicle_by_id

    user = get_user_by_telegram_id(telegram_id)
    if user is None:
        raise ResourceNotFound("Foydalanuvchi topilmadi.")
    driver = assert_driver_can_create_trip(user)
    vehicle = get_vehicle_by_id(vehicle_id)
    if vehicle is None:
        raise ResourceNotFound("Avtomobil topilmadi.")

    endpoint_kwargs = _resolve_endpoint(
        origin, label="Jo'nash", point_key="origin", location_field="from_location"
    )
    endpoint_kwargs.update(
        _resolve_endpoint(
            destination, label="Borish", point_key="destination", location_field="to_location"
        )
    )
    return create_trip(
        driver_profile=driver,
        vehicle=vehicle,
        **endpoint_kwargs,
        **trip_data,
    )


async def create_trip(telegram_id: int, vehicle_id: int, origin, destination, **trip_data):
    return await sync_to_async(_create_trip)(
        telegram_id, vehicle_id, origin, destination, **trip_data
    )


def _driver_trips(telegram_id: int):
    from apps.rides.selectors import get_trips_by_driver
    from apps.users.services import get_required_driver_profile

    driver = get_required_driver_profile(_get_user(telegram_id))
    return list(get_trips_by_driver(driver))


async def get_driver_trips(telegram_id: int):
    return await sync_to_async(_driver_trips)(telegram_id)


def _transition_trip(telegram_id: int, trip_id: int, action: str):
    from apps.rides import services as ride_services
    from apps.rides.selectors import get_trip_by_id

    user = _get_user(telegram_id)
    trip = get_trip_by_id(trip_id)
    if trip is None:
        raise ResourceNotFound("Yo'lov topilmadi.")
    if trip.driver.user_id != user.pk:
        raise UnauthorizedOrderAccess()
    service = {"publish": ride_services.publish_trip, "cancel": ride_services.cancel_trip}[action]
    return service(trip)


async def transition_trip(telegram_id: int, trip_id: int, action: str):
    return await sync_to_async(_transition_trip)(telegram_id, trip_id, action)


def _driver_requests(telegram_id: int):
    from apps.rides.models import PassengerRequestStatus
    from apps.rides.selectors import build_route_filter, get_matchable_requests
    from apps.users.services import get_required_driver_profile

    driver = get_required_driver_profile(_get_user(telegram_id))
    trips = list(
        driver.trips.filter(status="active", available_seats__gt=0).values_list(
            "from_location_id",
            "to_location_id",
            "from_city_name",
            "to_city_name",
            "departure_time",
            "available_seats",
            "price_per_seat",
        )
    )
    if not trips:
        return []
    from django.db.models import Q

    route_filter = Q()
    for (
        origin_id,
        destination_id,
        origin_city,
        destination_city,
        departure_time,
        seats,
        price,
    ) in trips:
        compatible_budget = Q(max_price_per_seat__isnull=True) | Q(
            max_price_per_seat__gte=price
        )
        # Falls back to the geocoded city names when the trip was picked on the
        # map and therefore has no catalogue Location at all.
        this_route = build_route_filter(
            from_location_id=origin_id,
            to_location_id=destination_id,
            from_city_name=origin_city,
            to_city_name=destination_city,
        )
        if this_route is None:
            continue
        route_filter |= this_route & Q(
            departure_from__lte=departure_time,
            departure_until__gte=departure_time,
            passenger_count__lte=seats,
        ) & compatible_budget

    if not route_filter:
        return []

    requests = (
        get_matchable_requests()
        .filter(route_filter, status=PassengerRequestStatus.ACTIVE)
        .exclude(passenger__telegram_id=telegram_id)
    )
    return list(requests[:20])


async def get_driver_requests(telegram_id: int):
    return await sync_to_async(_driver_requests)(telegram_id)


def _user_orders(telegram_id: int):
    from apps.orders.selectors import get_orders_by_driver, get_orders_by_passenger
    from apps.users.services import get_required_driver_profile

    user = _get_user(telegram_id)
    orders = list(get_orders_by_passenger(user))
    driver = getattr(user, "driver_profile", None)
    if driver is not None:
        orders.extend(get_orders_by_driver(driver).exclude(passenger=user))
    return orders


async def get_user_orders(telegram_id: int):
    return await sync_to_async(_user_orders)(telegram_id)


def _transition_order(telegram_id: int, order_id: int, action: str):
    from apps.orders import services as order_services
    from apps.orders.selectors import get_order_by_id

    user = _get_user(telegram_id)
    order = get_order_by_id(order_id)
    if order is None:
        raise ResourceNotFound("Buyurtma topilmadi.")
    is_passenger = order.passenger_id == user.pk
    is_driver = order.trip.driver.user_id == user.pk
    if not (is_passenger or is_driver):
        raise UnauthorizedOrderAccess()
    actions = {
        "accept": (is_driver, order_services.accept_order),
        "reject": (is_driver, order_services.reject_order),
        "arrived": (is_driver, order_services.mark_driver_arrived),
        "start": (is_driver, order_services.start_order),
        "complete": (is_driver, order_services.complete_order),
    }
    if action == "cancel":
        if is_passenger:
            service = order_services.cancel_order_by_passenger
        elif is_driver:
            service = order_services.cancel_order_by_driver
        else:
            raise UnauthorizedOrderAccess()
        return service(order)
    permitted, service = actions[action]
    if not permitted:
        raise UnauthorizedOrderAccess()
    return service(order)


async def transition_order(telegram_id: int, order_id: int, action: str):
    return await sync_to_async(_transition_order)(telegram_id, order_id, action)


def _profile_notifications(telegram_id: int):
    from apps.notifications.selectors import get_recent_notifications

    return list(get_recent_notifications(_get_user(telegram_id), limit=10))


async def get_notifications(telegram_id: int):
    return await sync_to_async(_profile_notifications)(telegram_id)


def _mark_notifications_read(telegram_id: int) -> int:
    from apps.notifications.services import mark_all_as_read

    return mark_all_as_read(_get_user(telegram_id))


async def mark_notifications_read(telegram_id: int) -> int:
    return await sync_to_async(_mark_notifications_read)(telegram_id)


def _create_support_ticket(telegram_id: int, subject: str, body: str):
    from apps.support.services import add_message, create_ticket

    user = _get_user(telegram_id)
    ticket = create_ticket(user=user, subject=subject, category="other")
    add_message(ticket=ticket, sender=user, body=body)
    return ticket


async def create_support_ticket(telegram_id: int, subject: str, body: str):
    return await sync_to_async(_create_support_ticket)(telegram_id, subject, body)


def _support_tickets(telegram_id: int):
    from apps.support.selectors import get_tickets_for_user

    return list(get_tickets_for_user(_get_user(telegram_id))[:10])


async def get_support_tickets(telegram_id: int):
    return await sync_to_async(_support_tickets)(telegram_id)


def _subscription_info(telegram_id: int):
    from apps.subscriptions.selectors import get_active_plans, get_active_subscription
    from apps.users.services import get_required_driver_profile

    user = _get_user(telegram_id)
    driver = getattr(user, "driver_profile", None)
    subscription = get_active_subscription(driver) if driver else None
    return subscription, list(get_active_plans())


async def get_subscription_info(telegram_id: int):
    return await sync_to_async(_subscription_info)(telegram_id)


def _payments(telegram_id: int):
    from apps.payments.selectors import get_payments_by_user

    return list(get_payments_by_user(_get_user(telegram_id))[:10])


async def get_payments(telegram_id: int):
    return await sync_to_async(_payments)(telegram_id)


def _book_match(
    telegram_id: int,
    request_id: int,
    match_id: int,
    seats: int | None = None,
):
    from apps.matching.models import TripMatch
    from apps.orders.services import create_order

    user = _get_user(telegram_id)
    match = TripMatch.objects.select_related("request", "trip").filter(pk=match_id).first()
    if match is None:
        raise ResourceNotFound("Mos yo'lov topilmadi.")
    if match.request_id != request_id or match.request.passenger_id != user.pk:
        raise UnauthorizedOrderAccess()
    return create_order(
        passenger=user,
        trip=match.trip,
        seats_booked=seats if seats is not None else match.request.passenger_count,
    )


async def book_match(
    telegram_id: int,
    request_id: int,
    match_id: int,
    seats: int | None = None,
):
    return await sync_to_async(_book_match)(telegram_id, request_id, match_id, seats)


def _get_matching_for_user(telegram_id: int, request_id: int):
    from apps.rides.selectors import get_request_by_id
    from apps.matching.services import get_ranked_matches

    user = _get_user(telegram_id)
    passenger_request = get_request_by_id(request_id)
    if passenger_request is None:
        raise ResourceNotFound("Yo'lovchi so'rovi topilmadi.")
    if passenger_request.passenger_id != user.pk:
        raise UnauthorizedOrderAccess()
    return get_ranked_matches(passenger_request)


async def get_matching_for_user(telegram_id: int, request_id: int):
    return await sync_to_async(_get_matching_for_user)(telegram_id, request_id)


def _cancel_passenger_request(telegram_id: int, request_id: int):
    from apps.rides.selectors import get_request_by_id
    from apps.rides.services import cancel_passenger_request

    user = _get_user(telegram_id)
    passenger_request = get_request_by_id(request_id)
    if passenger_request is None:
        raise ResourceNotFound("Yo'lovchi so'rovi topilmadi.")
    if passenger_request.passenger_id != user.pk:
        raise UnauthorizedOrderAccess()
    return cancel_passenger_request(passenger_request)


async def cancel_passenger_request_for_user(telegram_id: int, request_id: int):
    return await sync_to_async(_cancel_passenger_request)(telegram_id, request_id)


def _create_subscription_invoice(telegram_id: int, plan_id: int):
    from django.db import transaction

    from apps.payments.services import build_subscription_payment_invoice
    from apps.subscriptions.services import create_subscription, get_required_plan
    from apps.users.services import get_required_driver_profile

    with transaction.atomic():
        user = _get_user(telegram_id)
        driver = get_required_driver_profile(user)
        plan = get_required_plan(plan_id)
        subscription = create_subscription(driver=driver, plan=plan)
        return build_subscription_payment_invoice(user=user, subscription=subscription)


async def create_subscription_invoice(telegram_id: int, plan_id: int):
    return await sync_to_async(_create_subscription_invoice)(telegram_id, plan_id)


def _profile_for_chat(telegram_id: int):
    from apps.users.selectors import get_user_by_telegram_id

    return get_user_by_telegram_id(telegram_id)


async def profile_for_chat(telegram_id: int):
    return await sync_to_async(_profile_for_chat)(telegram_id)
