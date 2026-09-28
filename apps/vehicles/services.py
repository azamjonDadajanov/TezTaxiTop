"""Write/business layer for the vehicles app.

Deletion policy: a vehicle is never destroyed while it is referenced by a trip.
Instead it is deactivated (``is_active = False``) so historical trips keep a
readable car description.
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from apps.core.exceptions import BusinessValidationError, ResourceNotFound
from apps.users.models import DriverProfile
from apps.vehicles.models import Vehicle, normalize_plate_number
from apps.vehicles.selectors import (
    get_vehicle_by_id,
    get_vehicles_by_driver,
    has_usable_vehicle,
)

logger = logging.getLogger(__name__)


@transaction.atomic
def create_vehicle(
    *,
    driver: DriverProfile,
    brand: str,
    model: str,
    color: str,
    plate_number: str,
    year: int,
    seats_count: int = 4,
    notes: str = "",
) -> Vehicle:
    """Register a new car for ``driver``."""
    plate = normalize_plate_number(plate_number)
    vehicle = Vehicle(
        driver=driver,
        brand=brand.strip(),
        model=model.strip(),
        color=color.strip(),
        plate_number=plate,
        year=year,
        seats_count=seats_count,
        notes=notes.strip(),
    )
    try:
        vehicle.full_clean()
    except Exception as exc:  # noqa: BLE001 - re-raised as a business error
        raise BusinessValidationError(str(exc)) from exc
    vehicle.save()
    logger.info("Yangi avtomobil qo'shildi: %s (haydovchi=%s)", vehicle.plate_number, driver.pk)
    return vehicle


@transaction.atomic
def update_vehicle(vehicle: Vehicle, **changes) -> Vehicle:
    """Update editable vehicle fields.

    Allowed keys: ``brand``, ``model``, ``color``, ``plate_number``, ``year``,
    ``seats_count``, ``notes``, ``photo``. Verification flags are admin-only.
    """
    allowed_fields = {
        "brand",
        "model",
        "color",
        "plate_number",
        "year",
        "seats_count",
        "notes",
        "photo",
    }
    unknown = set(changes) - allowed_fields
    if unknown:
        raise BusinessValidationError(f"Ruxsat berilmagan maydonlar: {sorted(unknown)}")

    for field, value in changes.items():
        setattr(vehicle, field, value)
    if "plate_number" in changes:
        vehicle.plate_number = normalize_plate_number(vehicle.plate_number)
    try:
        vehicle.full_clean()
    except Exception as exc:  # noqa: BLE001
        raise BusinessValidationError(str(exc)) from exc
    vehicle.save()
    return vehicle


@transaction.atomic
def set_vehicle_active(vehicle: Vehicle, *, is_active: bool) -> Vehicle:
    """Activate or deactivate a vehicle (soft delete)."""
    vehicle.is_active = is_active
    vehicle.save(update_fields=["is_active", "updated_at"])
    return vehicle


@transaction.atomic
def verify_vehicle(vehicle: Vehicle, *, verified: bool = True) -> Vehicle:
    """Admin only: grant or revoke vehicle verification."""
    vehicle.is_verified = verified
    vehicle.verified_at = timezone.now() if verified else None
    vehicle.save(update_fields=["is_verified", "verified_at", "updated_at"])
    return vehicle


def delete_vehicle(vehicle: Vehicle) -> None:
    """Deactivate instead of deleting when the car has trip history."""
    if vehicle.trips.exists():
        set_vehicle_active(vehicle, is_active=False)
        return
    vehicle.delete()


def get_required_vehicle(vehicle_id: int) -> Vehicle:
    vehicle = get_vehicle_by_id(vehicle_id)
    if vehicle is None:
        raise ResourceNotFound("Avtomobil topilmadi.")
    return vehicle


def get_driver_vehicles(driver: DriverProfile) -> list[Vehicle]:
    return list(get_vehicles_by_driver(driver))


def assert_driver_has_usable_vehicle(driver: DriverProfile) -> Vehicle:
    """Return a usable car or raise - used by the trip creation service."""
    vehicle = get_vehicles_by_driver(driver).filter(is_active=True, is_verified=True).first()
    if vehicle is None:
        from apps.core.exceptions import VehicleNotVerified

        raise VehicleNotVerified()
    return vehicle


def driver_has_usable_vehicle(driver: DriverProfile) -> bool:
    return has_usable_vehicle(driver)


def vehicle_seats_for_passengers(vehicle: Vehicle) -> int:
    return vehicle.seats_for_passengers


def assert_plate_is_unique(plate_number: str, *, exclude_pk: int | None = None) -> None:
    """Explicit uniqueness check that produces a readable business error."""
    plate = normalize_plate_number(plate_number)
    queryset = Vehicle.objects.filter(plate_number=plate)
    if exclude_pk:
        queryset = queryset.exclude(pk=exclude_pk)
    if queryset.exists():
        raise BusinessValidationError(f"'{plate}' davlat raqamli avtomobil allaqachon ro'yxatda.")


__all__ = [
    "assert_driver_has_usable_vehicle",
    "assert_plate_is_unique",
    "create_vehicle",
    "delete_vehicle",
    "driver_has_usable_vehicle",
    "get_driver_vehicles",
    "get_required_vehicle",
    "set_vehicle_active",
    "update_vehicle",
    "vehicle_seats_for_passengers",
    "verify_vehicle",
]
