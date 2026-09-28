"""Write/business layer for the locations app.

The catalogue is admin managed, but the bot needs to resolve free text
("Toshkent, Chirchiq") into a :class:`~apps.locations.models.Location`, therefore
idempotent ``get_or_create`` helpers live here.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Iterable

from django.db import transaction

from apps.core.exceptions import BusinessValidationError, ResourceNotFound
from apps.locations.models import District, Location, Region, normalize_name
from apps.locations.selectors import (
    get_active_locations,
    get_district_by_id,
    get_districts,
    get_location_by_id,
    get_regions,
    get_region_by_id,
    search_locations,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Region
# ---------------------------------------------------------------------------
@transaction.atomic
def create_region(*, name: str, code: str = "", is_active: bool = True) -> Region:
    region = Region(name=name, code=code.strip(), is_active=is_active)
    region.full_clean()
    region.save()
    return region


@transaction.atomic
def update_region(region: Region, **changes) -> Region:
    allowed = {"name", "code", "is_active"}
    if set(changes) - allowed:
        raise BusinessValidationError("Faqat nom, kod va faollikka o'zgartirish mumkin.")
    for field, value in changes.items():
        setattr(region, field, value)
    region.full_clean()
    region.save()
    return region


@transaction.atomic
def get_or_create_region(*, name: str, code: str = "") -> Region:
    """Idempotent region creation used by seeding and the bot."""
    region, created = Region.objects.get_or_create(
        name=normalize_name(name), defaults={"code": code.strip()}
    )
    if created:
        logger.info("Yangi viloyat yaratildi: %s", region.name)
    return region


# ---------------------------------------------------------------------------
# District
# ---------------------------------------------------------------------------
@transaction.atomic
def create_district(*, region: Region, name: str, is_active: bool = True) -> District:
    district = District(region=region, name=name, is_active=is_active)
    district.full_clean()
    district.save()
    return district


@transaction.atomic
def update_district(district: District, **changes) -> District:
    allowed = {"name", "is_active", "region"}
    if set(changes) - allowed:
        raise BusinessValidationError("Faqat nom, viloyat va faollikka o'zgartirish mumkin.")
    for field, value in changes.items():
        setattr(district, field, value)
    district.full_clean()
    district.save()
    return district


@transaction.atomic
def get_or_create_district(*, region: Region, name: str) -> District:
    district, created = District.objects.get_or_create(region=region, name=normalize_name(name))
    if created:
        logger.info("Yangi tuman yaratildi: %s", district)
    return district


# ---------------------------------------------------------------------------
# Location
# ---------------------------------------------------------------------------
@transaction.atomic
def create_location(
    *,
    district: District,
    name: str,
    latitude: Decimal | float | str,
    longitude: Decimal | float | str,
    address: str = "",
    is_active: bool = True,
) -> Location:
    """Create a location. Coordinates are stored as ``Decimal``."""
    location = Location(
        district=district,
        name=name,
        latitude=_to_decimal(latitude),
        longitude=_to_decimal(longitude),
        address=address,
        is_active=is_active,
    )
    try:
        location.full_clean()
    except Exception as exc:  # noqa: BLE001
        raise BusinessValidationError(str(exc)) from exc
    location.save()
    return location


@transaction.atomic
def update_location(location: Location, **changes) -> Location:
    allowed = {
        "district",
        "name",
        "latitude",
        "longitude",
        "address",
        "is_active",
    }
    if set(changes) - allowed:
        raise BusinessValidationError("Ruxsat berilmagan maydonlar.")
    for field, value in changes.items():
        if field in {"latitude", "longitude"}:
            value = _to_decimal(value)
        setattr(location, field, value)
    try:
        location.full_clean()
    except Exception as exc:  # noqa: BLE001
        raise BusinessValidationError(str(exc)) from exc
    location.save()
    return location


@transaction.atomic
def get_or_create_location(
    *,
    district: District,
    name: str,
    latitude: Decimal | float | str,
    longitude: Decimal | float | str,
    address: str = "",
) -> Location:
    location, created = Location.objects.get_or_create(
        district=district,
        name=normalize_name(name),
        defaults={
            "latitude": _to_decimal(latitude),
            "longitude": _to_decimal(longitude),
            "address": address,
        },
    )
    if created:
        logger.info("Yangi manzil yaratildi: %s", location)
    return location


def _to_decimal(value: Decimal | float | str) -> Decimal:
    """Coerce coordinates to ``Decimal`` without ever using binary floats."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


@transaction.atomic
def set_location_active(location: Location, *, is_active: bool) -> Location:
    location.is_active = is_active
    location.save(update_fields=["is_active", "updated_at"])
    return location


def get_required_location(location_id: int) -> Location:
    location = get_location_by_id(location_id)
    if location is None:
        raise ResourceNotFound("Manzil topilmadi.")
    return location


def get_required_region(region_id: int) -> Region:
    region = get_region_by_id(region_id)
    if region is None:
        raise ResourceNotFound("Viloyat topilmadi.")
    return region


def get_required_district(district_id: int) -> District:
    district = get_district_by_id(district_id)
    if district is None:
        raise ResourceNotFound("Tuman topilmadi.")
    return district


def resolve_location_by_text(search_term: str) -> Location | None:
    """Best-effort free text resolution used by the Telegram bot."""
    candidates: Iterable[Location] = search_locations(get_active_locations(), search_term)
    return next(iter(candidates), None)


def list_active_regions() -> list[Region]:
    return list(get_regions().filter(is_active=True))


def list_active_districts(region_id: int | None = None) -> list[District]:
    queryset = get_districts().filter(is_active=True, region__is_active=True)
    if region_id is not None:
        queryset = queryset.filter(region_id=region_id)
    return list(queryset)
