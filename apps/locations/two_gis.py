"""2GIS Places API client used to geocode trip origin / destination.

Verified API contract
---------------------
Everything in this module is derived from the official *Catalog of objects
(3.0)* reference: https://docs.2gis.com/en/api/search/places/reference/3.0/items

Two details are easy to get wrong and both are handled explicitly below.

1. ``items[].point`` is an **object** ``{"lat": ..., "lon": ...}``.
   The "``lon, lat``" wording in the docs applies to the *query* string
   parameters (``point=``, ``location=``, ``sort_point=``), which are the only
   places where the order matters. The response object is read by key name, so
   no ordering assumption is made. (The sample response in the docs shows
   ``{"lat": 82.9, "lon": 55.0}`` for Novosibirsk, whose real coordinates are
   lon 82.9 / lat 55.0 - the sample *values* are mislabelled, the *keys* are
   correct. Reading by key name sidesteps that entirely.)

2. ``items[].adm_div[].type`` uses **short** names: ``region``, ``city``,
   ``district``, ``district_area``, ``living_area``, ``settlement``, ...
   The longer ``adm_div.city`` spelling is only the vocabulary of the ``type=``
   *query filter*. :func:`_normalize_admin_type` accepts both so a change on
   2GIS's side cannot silently empty out our hierarchy.

Reverse geocoding uses the very same ``/3.0/items`` endpoint with ``lon``/``lat``
instead of ``q``; there is no separate geocode path to keep in sync.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import requests
from django.conf import settings
from django.core.cache import cache

from apps.core.exceptions import (
    GeoProviderNotConfigured,
    GeoProviderUnavailable,
    PlaceNotResolved,
)

logger = logging.getLogger(__name__)

#: Fields we need. ``items.point`` / ``items.adm_div`` / ``items.address`` /
#: ``items.full_address_name`` are exactly the "geometry and address" group.
GEOCODE_FIELDS = "items.point,items.adm_div,items.address,items.full_address_name"

#: Cache keys. Reverse results are very stable per coordinate, forward results
#: depend on the query text.
_CACHE_TTL = 60 * 60 * 24
_CACHE_PREFIX = "twogis"

#: Returned in place of a 404 response so the caller sees an ordinary empty
#: result. Frozen: it is stored in the cache and must never be mutated.
_EMPTY_PAYLOAD = {"meta": {"code": 200}, "result": {"items": [], "total": 0}}

#: Radius for a "near me" forward search, in metres. 2GIS requires a radius
#: alongside ``search_nearby``; without it the query is rejected with a 404
#: even when an obvious match exists a couple of kilometres away.
_NEAR_RADIUS_M = 5000

#: Administrative types we keep, longest-name-fallback order per level.
_REGION_TYPES = ("region",)
_CITY_TYPES = ("city", "settlement", "place", "amana", "division")
_DISTRICT_TYPES = ("district", "division")


@dataclass(frozen=True, slots=True)
class ResolvedPlace:
    """A single 2GIS result, flattened into what a trip actually needs."""

    place_id: str
    name: str
    full_address: str
    address: str
    latitude: Decimal
    longitude: Decimal
    region_name: str = ""
    city_name: str = ""
    district_name: str = ""
    district_area_name: str = ""
    living_area_name: str = ""
    admin_types: tuple[str, ...] = field(default=())

    @property
    def display_name(self) -> str:
        """Best single-line label for UI: the address, else the POI name."""
        return self.full_address or self.address or self.name

    @property
    def short_name(self) -> str:
        return self.name or self.full_address or self.address


def search_places(
    query: str,
    *,
    near: tuple[Decimal | float, Decimal | float] | None = None,
    limit: int = 10,
) -> list[ResolvedPlace]:
    """Forward geocoding: free text -> candidate places.

    ``near`` is a ``(longitude, latitude)`` pair used to bias results towards the
    user. Passing it also satisfies the endpoint's requirement for a geographic
    restriction, which is what makes the call work without a configured
    ``TWOGIS_REGION_ID``.
    """
    query = (query or "").strip()
    if not query:
        return []

    params: dict[str, Any] = {
        "q": query,
        "type": "adm_div,building,street,crossroad,attraction",
        "fields": GEOCODE_FIELDS,
        "page_size": _clamp(limit, 1, settings.TWOGIS_MAX_PAGE_SIZE),
    }
    if near is not None:
        longitude, latitude = near
        params["lon"] = f"{float(longitude):.6f}"
        params["lat"] = f"{float(latitude):.6f}"
        params["search_nearby"] = "true"
        # 2GIS rejects `search_nearby` without a radius: the response is a 404
        # "Results not found" even for a district that plainly exists, which
        # reads as a provider outage rather than an empty result.
        params["radius"] = str(_NEAR_RADIUS_M)
    elif not settings.TWOGIS_REGION_ID:
        # The endpoint rejects a text-only query with no geographic
        # restriction and no region_id. Fail loudly with an actionable message
        # instead of letting 2GIS return a confusing 4xx.
        raise GeoProviderNotConfigured(
            "Matn bo'yicha qidiruv uchun TWOGIS_REGION_ID sozlanmagan. "
            "Sozlamalarni to'ldiring yoki foydalanuvchi joylashuvini yuboring."
        )

    payload = _request(params, cache_key=_forward_cache_key(query, near, limit))
    return _parse_items(payload)


def reverse_geocode(
    latitude: Decimal | float,
    longitude: Decimal | float,
    *,
    radius_m: int | None = None,
) -> ResolvedPlace:
    """Coordinates -> the enclosing address and administrative hierarchy.

    Raises :class:`PlaceNotResolved` when 2GIS has nothing within the radius.
    """
    lat = float(latitude)
    lon = float(longitude)
    radius = radius_m or settings.TWOGIS_REVERSE_RADIUS_M
    if not (-90 <= lat <= 90):
        raise PlaceNotResolved("Kenglik -90 va 90 orasida bo'lishi kerak.")
    if not (-180 <= lon <= 180):
        raise PlaceNotResolved("Uzunlik -180 va 180 orasida bo'lishi kerak.")

    params: dict[str, Any] = {
        "lon": f"{lon:.6f}",
        "lat": f"{lat:.6f}",
        "radius": _clamp(radius, 0, 2000),
        "type": "adm_div",
        "fields": GEOCODE_FIELDS,
        "page_size": 1,
    }
    payload = _request(params, cache_key=_reverse_cache_key(lat, lon, radius))

    places = _parse_items(payload)
    if not places:
        raise PlaceNotResolved(
            "Bu nuqtani manzilga aniqlab bo'lmadi. Manzilni qo'lda kiriting."
        )

    place = places[0]
    # A bare administrative division carries no street address. Fill the
    # address from the hierarchy so the UI always has something to show.
    if not place.full_address:
        place = _with_hierarchy_address(place)
    return place


def _with_hierarchy_address(place: ResolvedPlace) -> ResolvedPlace:
    parts = [
        place.region_name,
        place.city_name,
        place.district_name,
        place.district_area_name,
        place.living_area_name,
        place.name,
    ]
    label = ", ".join(dict.fromkeys(part for part in parts if part))
    return ResolvedPlace(
        place_id=place.place_id,
        name=place.name,
        full_address=label,
        address=place.address,
        latitude=place.latitude,
        longitude=place.longitude,
        region_name=place.region_name,
        city_name=place.city_name,
        district_name=place.district_name,
        district_area_name=place.district_area_name,
        living_area_name=place.living_area_name,
        admin_types=place.admin_types,
    )


# ---------------------------------------------------------------------------
# HTTP / cache
# ---------------------------------------------------------------------------
def _request(params: dict[str, Any], *, cache_key: str) -> dict[str, Any]:
    api_key = settings.TWOGIS_API_KEY
    if not api_key:
        raise GeoProviderNotConfigured()

    full_key = f"{_CACHE_PREFIX}:{cache_key}"
    cached = cache.get(full_key)
    if cached is not None:
        return cached

    query = {**params, "key": api_key, "locale": settings.TWOGIS_LOCALE}
    if not params.get("lon"):
        query["region_id"] = settings.TWOGIS_REGION_ID

    try:
        response = requests.get(
            settings.TWOGIS_BASE_URL,
            params=query,
            timeout=settings.TWOGIS_TIMEOUT,
            headers={"Accept": "application/json"},
        )
    except OSError as exc:
        # ``requests.RequestException`` (ConnectionError, Timeout, ...) and
        # ``json``/socket level failures all derive from OSError, so one catch
        # covers every transport problem the provider can throw at us.
        logger.warning("2GIS so'rovi bajarilmadi: %s", exc)
        raise GeoProviderUnavailable() from exc

    if response.status_code == 429:
        logger.warning("2GIS rate limit: %s", response.status_code)
        raise GeoProviderUnavailable("Xarita xizmati vaqtincha band. Birozdan keyin qayta urinib ko'ring.")
    if response.status_code >= 400:
        logger.warning("2GIS xato javobi: %s %s", response.status_code, response.text[:200])
        raise GeoProviderUnavailable()

    try:
        payload = response.json()
    except ValueError as exc:
        raise GeoProviderUnavailable() from exc

    if not isinstance(payload, dict):
        raise GeoProviderUnavailable()
    meta = payload.get("meta") or {}
    meta_code = meta.get("code")
    if isinstance(meta_code, int) and meta_code >= 400:
        # ``meta.code`` carries the real status; the HTTP status is always 200
        # for these responses. 404/itemNotFound means "nothing matched", which
        # is a legitimate empty answer rather than an outage - reporting it as a
        # 502 made an ordinary miss look like a broken integration.
        if meta_code == 404:
            logger.info("2GIS meta.code=404 (%s): natija topilmadi", (meta.get("error") or {}).get("type"))
            return _EMPTY_PAYLOAD
        logger.warning("2GIS meta.code=%s: %s", meta_code, meta.get("error"))
        raise GeoProviderUnavailable()

    cache.set(full_key, payload, _CACHE_TTL)
    return payload


def _forward_cache_key(query: str, near, limit: int) -> str:
    near_part = "-".join(f"{float(value):.4f}" for value in near) if near else "none"
    return f"fwd:{_slug(query)}:{near_part}:{limit}"


def _reverse_cache_key(lat: float, lon: float, radius: int) -> str:
    # 6 decimal places is ~11 cm, so rounding at 5 (~1 m) collapses the noise
    # that would otherwise make a stationary device miss the cache.
    return f"rev:{lat:.5f}:{lon:.5f}:{radius}"


def _slug(value: str) -> str:
    return "".join(char if char.isalnum() else "_" for char in value.lower())[:60]


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(int(value), high))


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
def _parse_items(payload: dict[str, Any]) -> list[ResolvedPlace]:
    result = payload.get("result")
    items = result.get("items") if isinstance(result, dict) else None
    if not isinstance(items, list):
        return []

    places: list[ResolvedPlace] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        place = _parse_item(item)
        if place is not None:
            places.append(place)
    return places


def _parse_item(item: dict[str, Any]) -> ResolvedPlace | None:
    point = item.get("point")
    if not isinstance(point, dict):
        return None

    # Read by key name - see the module docstring. No lat/lon ordering guess.
    lat = point.get("lat")
    lon = point.get("lon")
    if lat is None or lon is None:
        return None

    address = item.get("address") or {}
    hierarchy = _parse_admin_div(item.get("adm_div"))

    return ResolvedPlace(
        place_id=str(item.get("id") or ""),
        name=_text(item.get("name")),
        full_address=_text(item.get("full_address_name")),
        address=_text(address.get("address_name") if isinstance(address, dict) else ""),
        latitude=Decimal(str(lat)),
        longitude=Decimal(str(lon)),
        region_name=hierarchy.get("region", ""),
        city_name=hierarchy.get("city", ""),
        district_name=hierarchy.get("district", ""),
        district_area_name=hierarchy.get("district_area", ""),
        living_area_name=hierarchy.get("living_area", ""),
        admin_types=hierarchy["_types"],
    )


def _parse_admin_div(raw: Any) -> dict[str, Any]:
    """Flatten ``adm_div`` into ``region`` / ``city`` / ``district`` / ... .

    2GIS returns the chain from the largest unit down to the neighbourhood, but
    levels may be missing (a settlement can have no district, a city centre can
    have no district area), so each level falls back independently.
    """
    found: dict[str, str] = {}
    types: list[str] = []
    if not isinstance(raw, list):
        raw = [raw] if isinstance(raw, dict) else []

    for entry in raw:
        if not isinstance(entry, dict):
            continue
        admin_type = _normalize_admin_type(entry.get("type"))
        name = _text(entry.get("name"))
        if admin_type:
            types.append(admin_type)
        if not admin_type or not name:
            continue
        if _is_district_area(admin_type):
            found.setdefault("district_area", name)
        elif _is_city(admin_type):
            found.setdefault("city", name)
        elif _is_district(admin_type):
            found.setdefault("district", name)
        elif _is_region(admin_type):
            found.setdefault("region", name)
        elif admin_type == "living_area":
            found.setdefault("living_area", name)
        else:
            # Unknown/extra level - keep it as a district if nothing better
            # exists, otherwise it is dropped on purpose.
            found.setdefault("district", name)

    # `settlement` is a city-level unit in the 2GIS vocabulary but the raw name
    # may also appear as its own type; normalise the level keys.
    if "city" not in found and "settlement" in found:
        found["city"] = found["settlement"]

    found["_types"] = tuple(dict.fromkeys(types))
    return found


def _normalize_admin_type(raw: Any) -> str:
    """Accept both ``city`` and ``adm_div.city`` and return the short form."""
    return str(raw or "").strip().removeprefix("adm_div.").strip()


def _is_region(admin_type: str) -> bool:
    return admin_type in _REGION_TYPES


def _is_city(admin_type: str) -> bool:
    return admin_type in _CITY_TYPES


def _is_district(admin_type: str) -> bool:
    return admin_type in _DISTRICT_TYPES


def _is_district_area(admin_type: str) -> bool:
    # `division` is documented as "a district" and `district_area` as "a
    # district of the region"; only the latter is the finer level here.
    return admin_type == "district_area"


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())
