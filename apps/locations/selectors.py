"""Read/query layer for the locations app."""

from __future__ import annotations

from django.db.models import Q, QuerySet

from apps.locations.models import District, Location, Region

#: Fields the Django admin can search by.
LOCATION_SEARCH_FIELDS = ("id", "name", "address", "district__name", "district__region__name")
REGION_SEARCH_FIELDS = ("id", "name", "code")
DISTRICT_SEARCH_FIELDS = ("id", "name", "region__name")


def get_regions() -> QuerySet[Region]:
    return Region.objects.all()


def get_active_regions() -> QuerySet[Region]:
    return Region.objects.filter(is_active=True)


def get_region_by_id(region_id: int) -> Region | None:
    return Region.objects.filter(pk=region_id).first()


def get_districts() -> QuerySet[District]:
    return District.objects.select_related("region")


def get_active_districts() -> QuerySet[District]:
    return get_districts().filter(is_active=True, region__is_active=True)


def get_districts_by_region(region_id: int) -> QuerySet[District]:
    return get_districts().filter(region_id=region_id, is_active=True)


def get_district_by_id(district_id: int) -> District | None:
    return get_districts().filter(pk=district_id).first()


def get_locations() -> QuerySet[Location]:
    return Location.objects.select_related("district__region")


def get_active_locations() -> QuerySet[Location]:
    """Locations selectable by passengers and drivers."""
    return get_locations().filter(
        is_active=True, district__is_active=True, district__region__is_active=True
    )


def get_locations_by_district(district_id: int) -> QuerySet[Location]:
    return get_active_locations().filter(district_id=district_id)


def get_location_by_id(location_id: int) -> Location | None:
    return get_locations().filter(pk=location_id).first()


def get_locations_in_use() -> QuerySet[Location]:
    """Locations referenced by at least one trip (protected from deletion)."""
    return get_locations().filter(
        Q(trips_as_origin__isnull=False) | Q(trips_as_destination__isnull=False)
    ).distinct()


def search_locations(queryset: QuerySet[Location], search_term: str | None) -> QuerySet[Location]:
    """Free text search across the whole location path (used by the bot)."""
    if not search_term:
        return queryset
    term = search_term.strip()
    return queryset.filter(
        Q(name__icontains=term)
        | Q(address__icontains=term)
        | Q(district__name__icontains=term)
        | Q(district__region__name__icontains=term)
    )


def get_regions_search(queryset: QuerySet[Region], search_term: str | None) -> QuerySet[Region]:
    if not search_term:
        return queryset
    return queryset.filter(Q(name__icontains=search_term.strip()) | Q(code__icontains=search_term.strip()))


def get_districts_search(queryset: QuerySet[District], search_term: str | None) -> QuerySet[District]:
    if not search_term:
        return queryset
    term = search_term.strip()
    return queryset.filter(Q(name__icontains=term) | Q(region__name__icontains=term))
