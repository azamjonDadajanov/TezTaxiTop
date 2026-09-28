"""Location lookup adapters used by Telegram handlers."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from asgiref.sync import sync_to_async
from django.core.exceptions import ValidationError

from apps.core.exceptions import BusinessValidationError, ResourceNotFound
from apps.core.validators import validate_latitude, validate_longitude


def _get_nearest_location(latitude: float, longitude: float):
    from apps.locations.models import Location
    from apps.locations.selectors import get_active_locations

    try:
        latitude_value = Decimal(str(latitude))
        longitude_value = Decimal(str(longitude))
        validate_latitude(latitude_value)
        validate_longitude(longitude_value)
    except (InvalidOperation, ValidationError) as exc:
        raise BusinessValidationError("Koordinatalar noto'g'ri.") from exc

    locations = list(get_active_locations())
    if not locations:
        raise ResourceNotFound("Faol manzillar katalogi bo'sh.")

    point = Location(latitude=latitude_value, longitude=longitude_value)
    return min(locations, key=lambda location: location.distance_km_to(point))


async def get_nearest_location_from_coordinates(latitude: float, longitude: float):
    """Resolve coordinates to the nearest active catalog location."""
    return await sync_to_async(_get_nearest_location)(latitude, longitude)