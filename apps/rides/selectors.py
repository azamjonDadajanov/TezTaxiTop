"""Read/query layer for the rides app.

Selectors never write. They are shared by the REST API, the Django admin, the
Celery tasks and the deterministic matcher so that "which trips are visible"
is defined in exactly one place.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from math import cos, radians
from typing import Sequence

from django.db.models import Q, QuerySet
from django.utils import timezone

from apps.rides.constants import (
    BOOKABLE_TRIP_STATUSES,
    MATCHABLE_REQUEST_STATUSES,
)
from apps.rides.models import DriverTrip, DriverTripStatus, PassengerRequest, PassengerRequestStatus

#: Fields the Django admin may search by (driver name, phone, plate, route).
#: The ``from_*``/``to_*`` snapshot columns are searchable next to the
#: catalogue FKs, so a map-picked route is findable by its address text.
TRIP_SEARCH_FIELDS: Sequence[str] = (
    "id",
    "driver__user__first_name",
    "driver__user__last_name",
    "driver__user__username",
    "driver__user__phone_number",
    "driver__user__telegram_id",
    "vehicle__plate_number",
    "from_location__name",
    "to_location__name",
    "from_address",
    "to_address",
    "from_place_name",
    "to_place_name",
    "from_city_name",
    "to_city_name",
)

#: Fields the Django admin may order by.
TRIP_ORDERING_FIELDS: Sequence[str] = (
    "id",
    "departure_time",
    "price_per_seat",
    "available_seats",
    "status",
    "created_at",
)

REQUEST_SEARCH_FIELDS: Sequence[str] = (
    "id",
    "passenger__first_name",
    "passenger__last_name",
    "passenger__username",
    "passenger__phone_number",
    "passenger__telegram_id",
    "from_location__name",
    "to_location__name",
    "from_address",
    "to_address",
    "from_place_name",
    "to_place_name",
    "from_city_name",
    "to_city_name",
)

REQUEST_ORDERING_FIELDS: Sequence[str] = (
    "id",
    "departure_from",
    "departure_until",
    "passenger_count",
    "status",
    "created_at",
)


# ---------------------------------------------------------------------------
# Driver trip
# ---------------------------------------------------------------------------
def get_trip_queryset() -> QuerySet[DriverTrip]:
    """Optimised base queryset: driver, user, vehicle and both locations."""
    return DriverTrip.objects.select_related(
        "driver__user",
        "vehicle",
        "from_location__district__region",
        "to_location__district__region",
    )


def get_trips() -> QuerySet[DriverTrip]:
    return get_trip_queryset()


def get_trip_by_id(trip_id: int) -> DriverTrip | None:
    return get_trip_queryset().filter(pk=trip_id).first()


def get_trips_by_driver(driver) -> QuerySet[DriverTrip]:
    return get_trip_queryset().filter(driver=driver)


def get_active_trips() -> QuerySet[DriverTrip]:
    return get_trip_queryset().filter(status__in=BOOKABLE_TRIP_STATUSES)


def get_bookable_trips() -> QuerySet[DriverTrip]:
    """Trips that can still accept an order."""
    return get_trip_queryset().bookable()


def get_upcoming_trips() -> QuerySet[DriverTrip]:
    return get_trip_queryset().upcoming().filter(departure_time__gte=timezone.now())


def get_trips_for_vehicle(vehicle) -> QuerySet[DriverTrip]:
    return get_trip_queryset().filter(vehicle=vehicle)


def search_trips(queryset: QuerySet[DriverTrip], search_term: str | None) -> QuerySet[DriverTrip]:
    if not search_term:
        return queryset
    term = search_term.strip()
    return queryset.filter(
        Q(driver__user__first_name__icontains=term)
        | Q(driver__user__last_name__icontains=term)
        | Q(driver__user__username__icontains=term)
        | Q(driver__user__phone_number__icontains=term)
        | Q(driver__user__telegram_id__icontains=term.replace("+", ""))
        | Q(vehicle__plate_number__icontains=term)
        | Q(from_location__name__icontains=term)
        | Q(to_location__name__icontains=term)
        | Q(from_address__icontains=term)
        | Q(to_address__icontains=term)
        | Q(from_place_name__icontains=term)
        | Q(to_place_name__icontains=term)
        | Q(from_city_name__icontains=term)
        | Q(to_city_name__icontains=term)
    )


def get_trips_in_status(status: str) -> QuerySet[DriverTrip]:
    return get_trip_queryset().filter(status=status)


def get_expired_trips_candidates(grace_minutes: int) -> QuerySet[DriverTrip]:
    """Upcoming trips whose departure time has already passed."""
    deadline = timezone.now() - timedelta(minutes=grace_minutes)
    return (
        get_trip_queryset()
        .filter(
            status__in=(
                DriverTripStatus.DRAFT,
                DriverTripStatus.ACTIVE,
                DriverTripStatus.FULL,
            ),
            departure_time__lte=deadline,
        )
        .order_by("pk")
    )


def build_route_filter(
    *,
    from_location_id: int | None,
    to_location_id: int | None,
    from_city_name: str = "",
    to_city_name: str = "",
) -> Q | None:
    """The "same route" predicate shared by every matcher entry point.

    Returns a ``Q`` for models that were resolved through the curated
    catalogue, otherwise a ``Q`` on the geocoded snapshot city names. Returns
    ``None`` when the route cannot be compared at all - two blank cities are
    not evidence that two people want the same ride, so the caller must treat
    ``None`` as "matches nothing" rather than as "matches everything".
    """
    if from_location_id is not None and to_location_id is not None:
        return Q(from_location_id=from_location_id, to_location_id=to_location_id)
    if from_city_name and to_city_name:
        return Q(from_city_name=from_city_name, to_city_name=to_city_name)
    return None


def get_trip_candidates_for_matching(
    *,
    from_location_id: int | None,
    to_location_id: int | None,
    seats: int,
    not_before: datetime,
    from_city_name: str = "",
    to_city_name: str = "",
) -> QuerySet[DriverTrip]:
    """Pre-filtered candidate set handed to the deterministic scorer.

    Hard filters (things that make a trip *unusable* rather than *less good*):

    * the trip must be bookable (active + free seats),
    * it must depart after ``not_before`` minus the grace period,
    * it must have at least ``seats`` free seats.

    See :func:`build_route_filter` for why the route is matched on either the
    catalogue FKs or the snapshot city names.
    """
    from apps.core import conf

    route_filter = build_route_filter(
        from_location_id=from_location_id,
        to_location_id=to_location_id,
        from_city_name=from_city_name,
        to_city_name=to_city_name,
    )
    if route_filter is None:
        return get_trip_queryset().none()

    grace = timedelta(minutes=conf.TRIP_DEPARTURE_GRACE_MINUTES)
    return (
        get_trip_queryset()
        .bookable()
        .with_seats(seats)
        .filter(departure_time__gte=not_before - grace)
        .filter(route_filter)
    )


def get_trips_with_driver_subscriptions() -> QuerySet[DriverTrip]:
    """Trips whose driver currently has an ``ACTIVE`` subscription."""
    from apps.subscriptions.models import DriverSubscriptionStatus

    return get_trip_queryset().filter(
        driver__subscriptions__status=DriverSubscriptionStatus.ACTIVE,
        driver__subscriptions__expires_at__gt=timezone.now(),
    ).distinct()


# ---------------------------------------------------------------------------
# Passenger request
# ---------------------------------------------------------------------------
def get_request_queryset() -> QuerySet[PassengerRequest]:
    return PassengerRequest.objects.select_related(
        "passenger",
        "from_location__district__region",
        "to_location__district__region",
    ).prefetch_related("matches")


def get_requests() -> QuerySet[PassengerRequest]:
    return get_request_queryset()


def get_request_by_id(request_id: int) -> PassengerRequest | None:
    return get_request_queryset().filter(pk=request_id).first()


def get_requests_by_passenger(passenger) -> QuerySet[PassengerRequest]:
    return get_request_queryset().filter(passenger=passenger)


def get_active_requests() -> QuerySet[PassengerRequest]:
    return get_request_queryset().filter(status__in=MATCHABLE_REQUEST_STATUSES)


def get_matchable_requests() -> QuerySet[PassengerRequest]:
    return get_request_queryset().filter(status__in=MATCHABLE_REQUEST_STATUSES)


def search_requests(queryset: QuerySet[PassengerRequest], search_term: str | None) -> QuerySet[PassengerRequest]:
    if not search_term:
        return queryset
    term = search_term.strip()
    return queryset.filter(
        Q(passenger__first_name__icontains=term)
        | Q(passenger__last_name__icontains=term)
        | Q(passenger__username__icontains=term)
        | Q(passenger__phone_number__icontains=term)
        | Q(passenger__telegram_id__icontains=term.replace("+", ""))
        | Q(from_location__name__icontains=term)
        | Q(to_location__name__icontains=term)
        | Q(from_address__icontains=term)
        | Q(to_address__icontains=term)
        | Q(from_place_name__icontains=term)
        | Q(to_place_name__icontains=term)
        | Q(from_city_name__icontains=term)
        | Q(to_city_name__icontains=term)
    )


def get_expired_request_candidates(expiry_hours: int) -> QuerySet[PassengerRequest]:
    """Active requests older than ``expiry_hours``.

    A request is a *broadcast*, therefore its lifetime is decided purely by its
    age: once it is older than the configured window nobody is expected to act
    on it any more, and the matcher would still show it to drivers.
    """
    deadline = timezone.now() - timedelta(hours=expiry_hours)
    return (
        get_request_queryset()
        .filter(status=PassengerRequestStatus.ACTIVE, created_at__lte=deadline)
        .order_by("pk")
    )


# ---------------------------------------------------------------------------
# Passenger request - driver map ("passengers near me")
# ---------------------------------------------------------------------------
#: Kilometres per degree of latitude (mean value), the constant the Haversine
#: helper in :mod:`apps.rides.services` implies.
KM_PER_DEGREE_LATITUDE = 111.32

#: Floor for ``cos(latitude)``: a single degree of longitude collapses to zero
#: metres at the poles, and without the floor the longitude delta explodes.
_MIN_COS_LATITUDE = 0.01


def bounding_box(
    latitude, longitude, radius_km: float
) -> tuple[float, float, float, float]:
    """``(min_lat, max_lat, min_lon, max_lon)`` covering ``radius_km`` around a point.

    The circle is approximated by its bounding box so the expensive part of a
    proximity search stays a plain range filter - answerable by PostgreSQL and
    SQLite alike, with no geospatial extension installed. The exact circle test
    runs afterwards on the small result of that filter.
    """
    center_latitude = float(latitude)
    center_longitude = float(longitude)
    latitude_delta = float(radius_km) / KM_PER_DEGREE_LATITUDE
    # A meridian of longitude is only KM_PER_DEGREE_LATITUDE * cos(lat) long, so
    # the same kilometres span more degrees the closer the point sits to a pole.
    longitude_delta = min(
        float(radius_km)
        / (
            KM_PER_DEGREE_LATITUDE
            * max(abs(cos(radians(center_latitude))), _MIN_COS_LATITUDE)
        ),
        180.0,
    )
    return (
        max(-90.0, center_latitude - latitude_delta),
        min(90.0, center_latitude + latitude_delta),
        max(-180.0, center_longitude - longitude_delta),
        min(180.0, center_longitude + longitude_delta),
    )


def get_map_request_queryset() -> QuerySet[PassengerRequest]:
    """Lean queryset for the map feed.

    Skips the ``matches`` prefetch of :func:`get_request_queryset`: a map draws
    the pickup point, never the ranking, so that query would be wasted on every
    refresh.
    """
    return PassengerRequest.objects.select_related(
        "passenger",
        "from_location__district__region",
        "to_location__district__region",
    )


def get_nearby_requests(
    latitude,
    longitude,
    radius_km: float,
    *,
    exclude_passenger=None,
) -> list[tuple[PassengerRequest, float]]:
    """Active, still-departable requests whose pickup point is within ``radius_km``.

    Returns ``(request, distance_km)`` pairs, nearest first. The distance is the
    great-circle value from :func:`apps.rides.services.haversine_km`, so the
    number the driver reads on the map is the number the rest of the platform
    quotes for the same two points.

    The order is ``(distance, departure_from, pk)``; the last element makes it a
    total order, so two requests at the same distance always come back in the
    same sequence.
    """
    from apps.rides.services import haversine_km

    min_latitude, max_latitude, min_longitude, max_longitude = bounding_box(
        latitude, longitude, radius_km
    )
    candidates = get_map_request_queryset().filter(
        status=PassengerRequestStatus.ACTIVE,
        departure_until__gte=timezone.now(),
        from_latitude__isnull=False,
        from_longitude__isnull=False,
        from_latitude__gte=min_latitude,
        from_latitude__lte=max_latitude,
        from_longitude__gte=min_longitude,
        from_longitude__lte=max_longitude,
    )
    if exclude_passenger is not None:
        # A driver who is also a passenger must not see their own request on the
        # map as if it were somebody else's customer.
        candidates = candidates.exclude(passenger=exclude_passenger)

    origin = (float(latitude), float(longitude))
    measured = [
        (
            passenger_request,
            float(
                haversine_km(
                    origin,
                    (passenger_request.from_latitude, passenger_request.from_longitude),
                )
            ),
        )
        for passenger_request in candidates
    ]
    inside = [pair for pair in measured if pair[1] <= float(radius_km)]
    inside.sort(key=lambda pair: (pair[1], pair[0].departure_from, pair[0].pk))
    return inside


# ---------------------------------------------------------------------------
# Driver trip - passenger map ("taxis near me")
# ---------------------------------------------------------------------------
def get_map_trip_queryset() -> QuerySet[DriverTrip]:
    """Lean queryset for the passenger map feed.

    Mirrors :func:`get_map_request_queryset`: driver, user and vehicle come
    along because a taxi marker is drawn from all three, but nothing that only
    the trip *detail* view needs is joined.
    """
    return DriverTrip.objects.select_related(
        "driver__user",
        "vehicle",
        "from_location__district__region",
        "to_location__district__region",
    )


def get_nearby_trips(
    latitude,
    longitude,
    radius_km: float,
    *,
    exclude_driver=None,
) -> list[tuple[DriverTrip, float]]:
    """Bookable trips whose pickup point is within ``radius_km``, nearest first.

    The passenger-map counterpart of :func:`get_nearby_requests`, measured with
    the same :func:`apps.rides.services.haversine_km` so a distance quoted on
    either map means the same thing.

    Only trips a passenger can actually board are returned: ``active`` with a
    free seat and a departure that has not passed. A cancelled, expired or
    already-full trip has nothing to offer, so listing it would only make the
    marker a dead end.

    Ordered by ``(distance, departure_time, pk)`` - the trailing primary key
    makes it a total order, so equal distances always come back identically.
    """
    from apps.core import conf
    from apps.rides.services import haversine_km

    min_latitude, max_latitude, min_longitude, max_longitude = bounding_box(
        latitude, longitude, radius_km
    )
    candidates = (
        get_map_trip_queryset()
        .bookable()
        .filter(
            departure_time__gte=timezone.now() - timedelta(minutes=conf.TRIP_DEPARTURE_GRACE_MINUTES),
            from_latitude__isnull=False,
            from_longitude__isnull=False,
            from_latitude__gte=min_latitude,
            from_latitude__lte=max_latitude,
            from_longitude__gte=min_longitude,
            from_longitude__lte=max_longitude,
        )
    )
    if exclude_driver is not None:
        # A driver who is also a passenger must not be offered their own trip.
        candidates = candidates.exclude(driver=exclude_driver)

    origin = (float(latitude), float(longitude))
    measured = [
        (
            trip,
            float(haversine_km(origin, (trip.from_latitude, trip.from_longitude))),
        )
        for trip in candidates
    ]
    inside = [pair for pair in measured if pair[1] <= float(radius_km)]
    inside.sort(key=lambda pair: (pair[1], pair[0].departure_time, pair[0].pk))
    return inside
