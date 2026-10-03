"""Pair compatibility rules of the deterministic matcher.

Two records (a driver trip and a passenger request) are compared on three
axes, and every rule here is measured with **coordinates and clocks**, never
with place names:

``route_compatibility``
    pickup and drop-off must sit close to the corresponding points of the
    other route, and both routes must point the same way. The distances come
    from the shared great-circle formula (:func:`apps.rides.services.haversine_km`)
    so a number quoted here means the same thing as on the maps.

``time_difference_minutes``
    the trip departure against the requested departure window - both ends of
    the window count, and a departure inside the window is a difference of
    zero.

Seats are not a "compatibility" rule but a plain capacity check that lives
next to the other hard filters in :mod:`apps.matching.services`.

Every function is pure: same inputs → same output, no database writes, no
clock reads. That is what keeps the ranking reproducible.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from math import cos, radians

from django.core.exceptions import ObjectDoesNotExist

from apps.core import conf
from apps.rides.services import haversine_km

#: A pair of ``(latitude, longitude)`` values in any numeric type.
Point = tuple[Decimal | float, Decimal | float]

#: Kilometres are displayed with two decimals, like the rest of the platform.
KM_QUANT = Decimal("0.01")
ZERO_KM = Decimal("0.00")


def round_km(value: Decimal) -> Decimal:
    """Quantise a distance to the two decimals the UI shows."""
    return Decimal(value).quantize(KM_QUANT, rounding=ROUND_HALF_UP)


def endpoint_point(obj, prefix: str) -> Point | None:
    """Resolve one route endpoint of a trip/request to a coordinate pair.

    The curated catalogue row wins when it is linked - the same precedence the
    display layer uses (see ``RouteEndpointMixin._endpoint_display``), so a
    record can never *show* one place and be *measured* against another. A
    map-picked point has no catalogue row at all and resolves from its
    denormalised snapshot columns instead. Returns ``None`` when neither half
    exists: the caller must treat that as "cannot be compared", never as
    "compatible".
    """
    if getattr(obj, f"{prefix}_location_id", None) is not None:
        try:
            location = getattr(obj, f"{prefix}_location")
        except ObjectDoesNotExist:  # pragma: no cover - a deleted row is protected
            location = None
        if location is not None and location.latitude is not None and location.longitude is not None:
            return (location.latitude, location.longitude)

    latitude = getattr(obj, f"{prefix}_latitude", None)
    longitude = getattr(obj, f"{prefix}_longitude", None)
    if latitude is not None and longitude is not None:
        return (latitude, longitude)
    return None


def route_points(obj) -> tuple[Point | None, Point | None]:
    """``(pickup, dropoff)`` of one trip or request."""
    return endpoint_point(obj, "from"), endpoint_point(obj, "to")


def _direction_vector(origin: Point, destination: Point) -> tuple[float, float]:
    """Local east/north components of ``origin → destination``, in radians.

    A flat (equirectangular) approximation is enough here: only the *sign* of
    the angle between two routes matters, and over the few dozen kilometres a
    match spans the distortion is far below the decision threshold.
    """
    mean_latitude = radians((float(origin[0]) + float(destination[0])) / 2)
    east = radians(float(destination[1]) - float(origin[1])) * cos(mean_latitude)
    north = radians(float(destination[0]) - float(origin[0]))
    return east, north


def same_direction(route_a: tuple[Point, Point], route_b: tuple[Point, Point]) -> bool:
    """Do both routes travel the same way? ``True`` when they cannot disagree.

    A passenger travelling the other way is never a match, and the dot product
    of the two direction vectors answers that without any string comparison.
    A degenerate (zero length) route gives no evidence of the opposite
    direction, so it is treated as compatible - the distance rules still apply.
    """
    east_a, north_a = _direction_vector(*route_a)
    east_b, north_b = _direction_vector(*route_b)
    if (east_a * east_a + north_a * north_a) == 0 or (east_b * east_b + north_b * north_b) == 0:
        return True
    return east_a * east_b + north_a * north_b > 0


def detour_km(trip_route: tuple[Point, Point], passenger_route: tuple[Point, Point]) -> Decimal:
    """Extra kilometres the driver drives to serve the passenger.

    ``driver origin → passenger pickup → passenger dropoff → driver destination``
    minus the direct ``driver origin → driver destination``, i.e. exactly the
    deviation the detour adds. Never negative - the triangle inequality keeps
    it at or above zero.
    """
    trip_origin, trip_destination = trip_route
    pickup, dropoff = passenger_route
    served = (
        haversine_km(trip_origin, pickup)
        + haversine_km(pickup, dropoff)
        + haversine_km(dropoff, trip_destination)
    )
    direct = haversine_km(trip_origin, trip_destination)
    return max(ZERO_KM, served - direct)


@dataclass(frozen=True)
class RouteCompatibility:
    """The measured relationship between two routes.

    ``reason`` is machine readable (``""`` when compatible) so the API can
    explain a rejection without the UI re-deriving the rule, and the numeric
    fields stay ``None`` when the points are unknown rather than being faked
    with zeros.
    """

    compatible: bool
    reason: str
    pickup_km: Decimal | None
    dropoff_km: Decimal | None
    distance_difference_km: Decimal | None
    detour_km: Decimal | None
    same_direction: bool


def route_compatibility(trip, request) -> RouteCompatibility:
    """Compare a driver trip with a passenger request on the map.

    Hard rules:

    * all four points known (otherwise the pair cannot be judged),
    * both routes point the same way,
    * ``max(pickup offset, dropoff offset) <= MATCHING_MAX_ROUTE_DISTANCE_KM``.
    """
    trip_route = route_points(trip)
    request_route = route_points(request)
    if any(point is None for point in (*trip_route, *request_route)):
        return RouteCompatibility(
            compatible=False,
            reason="missing_coordinates",
            pickup_km=None,
            dropoff_km=None,
            distance_difference_km=None,
            detour_km=None,
            same_direction=False,
        )

    pickup = haversine_km(trip_route[0], request_route[0])  # type: ignore[arg-type]
    dropoff = haversine_km(trip_route[1], request_route[1])  # type: ignore[arg-type]
    distance_difference = max(pickup, dropoff)
    detour = detour_km(trip_route, request_route)  # type: ignore[arg-type]
    direction_ok = same_direction(trip_route, request_route)  # type: ignore[arg-type]

    if not direction_ok:
        return RouteCompatibility(
            compatible=False,
            reason="opposite_direction",
            pickup_km=round_km(pickup),
            dropoff_km=round_km(dropoff),
            distance_difference_km=round_km(distance_difference),
            detour_km=round_km(detour),
            same_direction=False,
        )
    if distance_difference > Decimal(str(conf.MATCHING_MAX_ROUTE_DISTANCE_KM)):
        return RouteCompatibility(
            compatible=False,
            reason="route_too_far",
            pickup_km=round_km(pickup),
            dropoff_km=round_km(dropoff),
            distance_difference_km=round_km(distance_difference),
            detour_km=round_km(detour),
            same_direction=True,
        )
    return RouteCompatibility(
        compatible=True,
        reason="",
        pickup_km=round_km(pickup),
        dropoff_km=round_km(dropoff),
        distance_difference_km=round_km(distance_difference),
        detour_km=round_km(detour),
        same_direction=True,
    )


def time_difference_minutes(departure_time, request) -> int:
    """Minutes between a trip departure and the requested departure window.

    Zero when the departure already sits inside ``[departure_from,
    departure_until]``; otherwise the distance to the nearer end of the
    window. Both ends are considered, so a request with a pickup *and* a
    drop-off deadline is matched against whichever it is closest to.
    """
    if departure_time is None or request.departure_from is None or request.departure_until is None:
        return 0
    if departure_time < request.departure_from:
        return int((request.departure_from - departure_time).total_seconds() // 60)
    if departure_time > request.departure_until:
        return int((departure_time - request.departure_until).total_seconds() // 60)
    return 0


def time_is_compatible(departure_time, request) -> bool:
    """``True`` when the departure is within the configured tolerance."""
    return time_difference_minutes(departure_time, request) <= conf.MATCHING_TIME_TOLERANCE_MINUTES


__all__ = [
    "Point",
    "RouteCompatibility",
    "detour_km",
    "endpoint_point",
    "route_compatibility",
    "route_points",
    "round_km",
    "same_direction",
    "time_difference_minutes",
    "time_is_compatible",
]
