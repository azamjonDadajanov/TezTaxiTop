"""Read/query layer for the vehicles app."""

from __future__ import annotations

from django.db.models import Q, QuerySet

from apps.vehicles.models import Vehicle

#: Fields the Django admin can search by.
VEHICLE_SEARCH_FIELDS = (
    "id",
    "plate_number",
    "brand",
    "model",
    "color",
    "driver__user__first_name",
    "driver__user__last_name",
    "driver__user__phone_number",
    "driver__user__telegram_id",
)

#: Fields the Django admin can order by.
VEHICLE_ORDERING_FIELDS = (
    "id",
    "brand",
    "model",
    "plate_number",
    "year",
    "seats_count",
    "is_active",
    "is_verified",
    "created_at",
)


def get_vehicle_queryset() -> QuerySet[Vehicle]:
    """Optimised base queryset: driver + user are always rendered."""
    return Vehicle.objects.select_related("driver__user")


def get_vehicles() -> QuerySet[Vehicle]:
    return get_vehicle_queryset()


def get_active_vehicles() -> QuerySet[Vehicle]:
    return get_vehicle_queryset().filter(is_active=True)


def get_usable_vehicles() -> QuerySet[Vehicle]:
    """Active **and** verified cars, i.e. attachable to a published trip."""
    return get_vehicle_queryset().filter(is_active=True, is_verified=True)


def get_verified_vehicles() -> QuerySet[Vehicle]:
    return get_vehicle_queryset().filter(is_verified=True)


def get_vehicles_by_driver(driver) -> QuerySet[Vehicle]:
    return get_vehicle_queryset().filter(driver=driver)


def get_usable_vehicles_by_driver(driver) -> QuerySet[Vehicle]:
    return get_vehicles_by_driver(driver).filter(is_active=True, is_verified=True)


def get_vehicle_by_id(vehicle_id: int) -> Vehicle | None:
    return get_vehicle_queryset().filter(pk=vehicle_id).first()


def get_vehicle_by_plate_number(plate_number: str) -> Vehicle | None:
    from apps.vehicles.models import normalize_plate_number

    return get_vehicle_queryset().filter(plate_number=normalize_plate_number(plate_number)).first()


def search_vehicles(queryset: QuerySet[Vehicle], search_term: str | None) -> QuerySet[Vehicle]:
    if not search_term:
        return queryset
    term = search_term.strip()
    return queryset.filter(
        Q(plate_number__icontains=term)
        | Q(brand__icontains=term)
        | Q(model__icontains=term)
        | Q(color__icontains=term)
        | Q(driver__user__first_name__icontains=term)
        | Q(driver__user__last_name__icontains=term)
        | Q(driver__user__phone_number__icontains=term)
        | Q(driver__user__telegram_id__icontains=term.replace("+", ""))
    )


def has_usable_vehicle(driver) -> bool:
    """Whether the driver owns at least one active verified vehicle."""
    return get_usable_vehicles_by_driver(driver).exists()
