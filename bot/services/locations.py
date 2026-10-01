"""Route endpoint helpers used by Telegram handlers.

A Telegram ``location`` message carries raw coordinates and they are passed
through as-is. They used to be snapped to the nearest row of the curated
``Location`` catalogue first, which meant two genuinely different pins could
collapse onto one place - and on a catalogue holding a single entry, onto the
same place every time - so the route then failed the "origin must differ from
destination" guard even though the driver had picked two different spots. The
catalogue stays available for admin-managed places; the bot just stops pretending
a map pin is a catalogue row.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from asgiref.sync import sync_to_async
from django.core.exceptions import ValidationError

from apps.core.exceptions import BusinessValidationError
from apps.core.validators import validate_latitude, validate_longitude


def _normalize_coordinates(latitude, longitude) -> dict[str, Decimal]:
    """Validate one Telegram location and return it as a route endpoint payload."""
    try:
        latitude_value = Decimal(str(latitude))
        longitude_value = Decimal(str(longitude))
        validate_latitude(latitude_value)
        validate_longitude(longitude_value)
    except (InvalidOperation, TypeError, ValueError, ValidationError) as exc:
        raise BusinessValidationError("Koordinatalar noto'g'ri.") from exc
    return {"latitude": latitude_value, "longitude": longitude_value}


async def normalize_location(latitude, longitude) -> dict[str, Decimal]:
    """Turn a Telegram ``location`` into an ``origin`` / ``destination`` payload.

    Raises :class:`~apps.core.exceptions.BusinessValidationError` for coordinates
    outside the valid ranges, so a malformed pin never reaches the trip service.
    """
    return await sync_to_async(_normalize_coordinates)(latitude, longitude)


def describe_point(point: dict) -> str:
    """Short label for a stored endpoint, used in the confirmation prompts.

    Coerces through :class:`~decimal.Decimal` because the values travel through
    the FSM state, which is free to hand them back as strings.
    """
    return f"{_decimal(point['latitude']):.5f}, {_decimal(point['longitude']):.5f}"


def route_distance_km(first: dict, second: dict) -> float:
    """Great-circle distance between two route points, in kilometres."""
    from apps.rides.services import haversine_km

    return float(haversine_km(_point(first), _point(second)))


def route_error(first: dict, second: dict) -> str | None:
    """The reason this route may not be announced, or ``None`` when it may.

    Asks the very rule the service layer enforces, so the driver is told as soon
    as the second pin arrives instead of after departure, seats and price. The
    minimum distance matters here more than anywhere else: two pins a few hundred
    metres apart describe no ride at all.
    """
    from apps.rides.services import validate_route_points

    return validate_route_points(_point(first), _point(second))


def _point(value: dict) -> tuple[Decimal, Decimal]:
    return (_decimal(value["latitude"]), _decimal(value["longitude"]))


def _decimal(value) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))