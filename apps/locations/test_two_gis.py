"""Tests for the 2GIS Places client and the route-endpoint snapshot layer.

The payload fixtures below are the important part: they pin the two parts of
the 2GIS contract that are easy to get wrong and that fail *silently* rather
than loudly - the ``point`` object shape and the ``adm_div[].type`` vocabulary.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.core.exceptions import (
    BusinessValidationError,
    GeoProviderNotConfigured,
    GeoProviderUnavailable,
    PlaceNotResolved,
)
from apps.core.testing import TaxiTestData
from apps.locations import services as location_services
from apps.locations import two_gis

# A Tashkent address as 2GIS would return it. Note that ``point`` is an OBJECT
# with named keys, and ``adm_div[].type`` uses the short vocabulary
# ("region"/"city"/"district"), not the "adm_div.*" query-filter spelling.
TASHKENT_ITEM = {
    "id": "141265769336625_abc",
    "name": "Amir Temur ko'chasi, 12",
    "full_address_name": "Toshkent, Amir Temur ko'chasi, 12",
    "address": {
        "address_name": "Amir Temur ko'chasi, 12",
        "building": "12",
        "components": [{"type": "street", "name": "Amir Temur ko'chasi"}],
    },
    "point": {"lat": 41.311081, "lon": 69.240562},
    "adm_div": [
        {"name": "Toshkent shahri", "id": "1", "type": "region", "is_default": True},
        {"name": "Toshkent shahri", "id": "2", "type": "city", "is_default": True},
        {"name": "Yunusobod tumani", "id": "3", "type": "district"},
        {"name": "Bodomzor", "id": "4", "type": "district_area"},
        {"name": "Bodomzor MFY", "id": "5", "type": "living_area"},
    ],
    "type": "building",
}

# A settlement with no district at all - the levels must degrade independently
# rather than shifting up by one.
SETTLEMENT_ITEM = {
    "id": "999",
    "name": "Zangiota",
    "full_address_name": "",
    "address": {"address_name": ""},
    "point": {"lat": 41.309722, "lon": 69.231111},
    "adm_div": [
        {"name": "Toshkent viloyati", "id": "1", "type": "region"},
        {"name": "Zangiota", "id": "8", "type": "settlement"},
    ],
    "type": "adm_div",
}


def _payload(*items) -> dict:
    return {"meta": {"code": 200}, "result": {"items": list(items), "total": len(items)}}


class _FakeResponse:
    def __init__(self, payload=None, status_code: int = 200, text: str = ""):
        self._payload = payload
        self.status_code = status_code
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


@override_settings(TWOGIS_API_KEY="test-key", TWOGIS_REGION_ID=0, TWOGIS_LOCALE="ru_UZ")
class TwoGisParsingTests(TestCase):
    """The response contract, without any network access."""

    def test_point_is_read_by_key_name_not_by_position(self) -> None:
        place = two_gis._parse_item(TASHKENT_ITEM)
        self.assertEqual(place.latitude, Decimal("41.311081"))
        self.assertEqual(place.longitude, Decimal("69.240562"))

    def test_hierarchy_levels(self) -> None:
        place = two_gis._parse_item(TASHKENT_ITEM)
        self.assertEqual(place.region_name, "Toshkent shahri")
        self.assertEqual(place.city_name, "Toshkent shahri")
        self.assertEqual(place.district_name, "Yunusobod tumani")
        self.assertEqual(place.district_area_name, "Bodomzor")
        self.assertEqual(place.living_area_name, "Bodomzor MFY")

    def test_missing_levels_do_not_shift(self) -> None:
        place = two_gis._parse_item(SETTLEMENT_ITEM)
        self.assertEqual(place.region_name, "Toshkent viloyati")
        self.assertEqual(place.city_name, "Zangiota")
        self.assertEqual(place.district_name, "")

    def test_item_without_point_is_skipped(self) -> None:
        self.assertIsNone(two_gis._parse_item({"id": "1", "name": "no point"}))

    def test_long_admin_type_prefix_is_tolerated(self) -> None:
        """2GIS may switch to the "adm_div.*" spelling; we must not break."""
        item = {
            "point": {"lat": 41.0, "lon": 69.0},
            "adm_div": [
                {"name": "Samarqand viloyati", "type": "adm_div.region"},
                {"name": "Samarqand", "type": "adm_div.city"},
            ],
        }
        place = two_gis._parse_item(item)
        self.assertEqual(place.region_name, "Samarqand viloyati")
        self.assertEqual(place.city_name, "Samarqand")

    def test_display_name_prefers_full_address(self) -> None:
        place = two_gis._parse_item(TASHKENT_ITEM)
        self.assertEqual(place.display_name, "Toshkent, Amir Temur ko'chasi, 12")


@override_settings(TWOGIS_API_KEY="test-key", TWOGIS_REGION_ID=0, TWOGIS_LOCALE="ru_UZ")
class TwoGisRequestTests(TestCase):
    """What we actually send to 2GIS."""

    def setUp(self) -> None:
        cache.clear()
        self.addCleanup(cache.clear)

    def test_reverse_geocode_sends_lon_and_lat_in_the_right_slots(self) -> None:
        """The classic bug: 2GIS takes separate ``lon``/``lat`` numbers."""
        with patch("apps.locations.two_gis.requests.get") as get:
            get.return_value = _FakeResponse(_payload(TASHKENT_ITEM))
            place = two_gis.reverse_geocode("41.311081", "69.240562")

        params = get.call_args.kwargs["params"]
        self.assertEqual(params["lon"], "69.240562")
        self.assertEqual(params["lat"], "41.311081")
        self.assertEqual(params["radius"], 300)
        self.assertEqual(params["type"], "adm_div")
        self.assertNotIn("region_id", params)
        self.assertEqual(place.city_name, "Toshkent shahri")

    def test_reverse_geocode_clamps_radius_to_the_documented_cap(self) -> None:
        with patch("apps.locations.two_gis.requests.get") as get:
            get.return_value = _FakeResponse(_payload(TASHKENT_ITEM))
            two_gis.reverse_geocode("41.0", "69.0", radius_m=99999)
        self.assertEqual(get.call_args.kwargs["params"]["radius"], 2000)

    def test_reverse_geocode_raises_when_nothing_is_found(self) -> None:
        with patch("apps.locations.two_gis.requests.get") as get:
            get.return_value = _FakeResponse(_payload())
            with self.assertRaises(PlaceNotResolved):
                two_gis.reverse_geocode("41.0", "69.0")

    def test_reverse_geocode_rejects_out_of_range_coordinates(self) -> None:
        with self.assertRaises(PlaceNotResolved):
            two_gis.reverse_geocode("95.0", "69.0")
        with self.assertRaises(PlaceNotResolved):
            two_gis.reverse_geocode("41.0", "200.0")

    def test_search_without_region_id_or_position_fails_loudly(self) -> None:
        with self.assertRaises(GeoProviderNotConfigured):
            two_gis.search_places("Toshkent")

    def test_search_with_position_needs_no_region_id(self) -> None:
        with patch("apps.locations.two_gis.requests.get") as get:
            get.return_value = _FakeResponse(_payload(TASHKENT_ITEM))
            places = two_gis.search_places("Amir Temur", near=(Decimal("69.24"), Decimal("41.31")))

        params = get.call_args.kwargs["params"]
        self.assertEqual(params["lon"], "69.240000")
        self.assertEqual(params["lat"], "41.310000")
        self.assertNotIn("region_id", params)
        self.assertEqual(len(places), 1)

    @override_settings(TWOGIS_REGION_ID=42)
    def test_region_id_is_sent_for_text_only_search(self) -> None:
        with patch("apps.locations.two_gis.requests.get") as get:
            get.return_value = _FakeResponse(_payload(TASHKENT_ITEM))
            two_gis.search_places("Toshkent")
        self.assertEqual(get.call_args.kwargs["params"]["region_id"], 42)

    @override_settings(TWOGIS_API_KEY="")
    def test_missing_api_key_is_reported(self) -> None:
        with self.assertRaises(GeoProviderNotConfigured):
            two_gis.reverse_geocode("41.0", "69.0")

    def test_transport_error_becomes_provider_unavailable(self) -> None:
        import requests

        with patch("apps.locations.two_gis.requests.get", side_effect=requests.Timeout("boom")):
            with self.assertRaises(GeoProviderUnavailable):
                two_gis.reverse_geocode("41.0", "69.0")

    def test_http_error_becomes_provider_unavailable(self) -> None:
        with patch("apps.locations.two_gis.requests.get") as get:
            get.return_value = _FakeResponse(status_code=500, text="oops")
            with self.assertRaises(GeoProviderUnavailable):
                two_gis.reverse_geocode("41.0", "69.0")

    def test_results_are_cached(self) -> None:
        with patch("apps.locations.two_gis.requests.get") as get:
            get.return_value = _FakeResponse(_payload(TASHKENT_ITEM))
            two_gis.reverse_geocode("41.311081", "69.240562")
            two_gis.reverse_geocode("41.311081", "69.240562")
        self.assertEqual(get.call_count, 1)

    def test_search_nearby_always_sends_a_radius(self) -> None:
        """2GIS answers 404 to `search_nearby` without a radius, even for a
        district that plainly exists a few km away."""
        with patch("apps.locations.two_gis.requests.get") as get:
            get.return_value = _FakeResponse(_payload(TASHKENT_ITEM))
            two_gis.search_places("Yunusobod", near=(Decimal("69.24"), Decimal("41.31")))
        params = get.call_args.kwargs["params"]
        self.assertEqual(params["search_nearby"], "true")
        self.assertTrue(params.get("radius"), "search_nearby without radius returns 404")

    def test_meta_404_is_an_empty_result_not_an_outage(self) -> None:
        """A miss is HTTP 200 with meta.code=404; reporting it as 502 made an
        ordinary 'nothing found' look like a broken integration."""
        not_found = {
            "meta": {"code": 404, "error": {"message": "Results not found", "type": "itemNotFound"}},
            "result": {"items": []},
        }
        with patch("apps.locations.two_gis.requests.get") as get:
            get.return_value = _FakeResponse(not_found)
            self.assertEqual(two_gis.search_places("Nowhere", near=(Decimal("69.24"), Decimal("41.31"))), [])

    def test_reverse_geocode_reports_a_404_meta_as_unresolved(self) -> None:
        not_found = {
            "meta": {"code": 404, "error": {"message": "Results not found", "type": "itemNotFound"}},
            "result": {"items": []},
        }
        with patch("apps.locations.two_gis.requests.get") as get:
            get.return_value = _FakeResponse(not_found)
            with self.assertRaises(PlaceNotResolved):
                two_gis.reverse_geocode("41.0", "69.0")

    def test_meta_5xx_is_still_an_outage(self) -> None:
        with patch("apps.locations.two_gis.requests.get") as get:
            get.return_value = _FakeResponse({"meta": {"code": 500, "error": {"message": "boom"}}})
            with self.assertRaises(GeoProviderUnavailable):
                two_gis.reverse_geocode("41.0", "69.0")

    def test_empty_payload_is_not_mutated_by_a_caller(self) -> None:
        """The 404 shortcut returns a shared module-level dict that then lands in
        the cache, so it must stay pristine."""
        not_found = {
            "meta": {"code": 404, "error": {"message": "Results not found", "type": "itemNotFound"}},
            "result": {"items": [TASHKENT_ITEM]},
        }
        with patch("apps.locations.two_gis.requests.get") as get:
            get.return_value = _FakeResponse(not_found)
            two_gis.search_places("Amir Temur", near=(Decimal("69.24"), Decimal("41.31")))

        from django.core.cache import cache as django_cache

        key = f"{two_gis._CACHE_PREFIX}:{two_gis._forward_cache_key('Amir Temur', (Decimal('69.24'), Decimal('41.31')), 10)}"
        stored = django_cache.get(key)
        if stored is not None:  # a cache backend may decline to store
            self.assertEqual(stored["result"]["items"], [])


@override_settings(TWOGIS_API_KEY="test-key", TWOGIS_REGION_ID=42)
class PointSnapshotTests(TestCase):
    """``build_point_snapshot`` - the bridge between 2GIS and the trip row."""

    def setUp(self) -> None:
        cache.clear()
        self.addCleanup(cache.clear)
        self.region = location_services.get_or_create_region(name="Toshkent viloyati")
        self.district = location_services.get_or_create_district(region=self.region, name="Zangiota tumani")
        self.location = location_services.get_or_create_location(
            district=self.district, name="Qorasuv", latitude="41.311081", longitude="69.240562"
        )

    def test_catalogue_location_never_calls_2gis(self) -> None:
        with patch("apps.locations.two_gis.requests.get") as get:
            snapshot = location_services.build_point_snapshot("from", location=self.location)
        get.assert_not_called()
        self.assertEqual(snapshot["from_latitude"], self.location.latitude)
        self.assertEqual(snapshot["from_region_name"], "Toshkent viloyati")
        self.assertEqual(snapshot["from_place_name"], "Qorasuv")

    def test_coordinates_are_reverse_geocoded(self) -> None:
        with patch("apps.locations.two_gis.requests.get") as get:
            get.return_value = _FakeResponse(_payload(TASHKENT_ITEM))
            snapshot = location_services.build_point_snapshot(
                "to", latitude="41.311081", longitude="69.240562"
            )
        self.assertEqual(snapshot["to_address"], "Toshkent, Amir Temur ko'chasi, 12")
        self.assertEqual(snapshot["to_city_name"], "Toshkent shahri")
        self.assertEqual(snapshot["to_district_name"], "Yunusobod tumani")
        self.assertEqual(snapshot["to_latitude"], Decimal("41.311081"))

    def test_outage_keeps_the_coordinates(self) -> None:
        """A dead provider must not make the ride unbookable."""
        with patch("apps.locations.two_gis.requests.get", side_effect=OSError("network down")):
            snapshot = location_services.build_point_snapshot(
                "from", latitude="41.311081", longitude="69.240562"
            )
        self.assertEqual(snapshot["from_latitude"], Decimal("41.311081"))
        self.assertEqual(snapshot["from_longitude"], Decimal("69.240562"))
        # The text half is simply absent, so the trip row keeps an empty address
        # rather than a half-written one.
        self.assertNotIn("from_address", snapshot)

    def test_client_supplied_text_skips_the_network(self) -> None:
        with patch("apps.locations.two_gis.requests.get") as get:
            snapshot = location_services.build_point_snapshot(
                "from",
                latitude="41.311081",
                longitude="69.240562",
                address="Qo'lda kiritilgan manzil",
            )
        get.assert_not_called()
        self.assertEqual(snapshot["from_address"], "Qo'lda kiritilgan manzil")

    def test_half_a_coordinate_pair_is_rejected(self) -> None:
        with self.assertRaises(BusinessValidationError):
            location_services.build_point_snapshot("from", latitude="41.311081")

    def test_no_endpoint_at_all_is_rejected(self) -> None:
        with self.assertRaises(BusinessValidationError):
            location_services.build_point_snapshot("from")

    def test_text_without_coordinates_is_rejected(self) -> None:
        """An address string cannot be mapped, geocoded or route-compared."""
        with self.assertRaises(BusinessValidationError):
            location_services.build_point_snapshot("from", address="Amir Temur ko'chasi, 12")

    def test_only_resolved_columns_are_returned(self) -> None:
        """Sparse output is what keeps partial updates from blanking fields."""
        with patch("apps.locations.two_gis.requests.get") as get:
            get.return_value = _FakeResponse(_payload(TASHKENT_ITEM))
            snapshot = location_services.build_point_snapshot(
                "to", latitude="41.311081", longitude="69.240562", address="Faqat shu matn"
            )
        self.assertEqual(
            set(snapshot), {"to_latitude", "to_longitude", "to_address"}, snapshot
        )
        get.assert_not_called()

    def test_prefixed_column_names_are_produced(self) -> None:
        snapshot = location_services.build_point_snapshot("to", location=self.location)
        self.assertTrue(all(key.startswith("to_") for key in snapshot), snapshot)
        self.assertEqual(snapshot["to_latitude"], self.location.latitude)
        self.assertEqual(snapshot["to_place_name"], "Qorasuv")


@override_settings(TWOGIS_API_KEY="test-key", TWOGIS_REGION_ID=42)
class GeoEndpointTests(TestCase):
    """``/locations/geo/`` is the contract the React map depends on."""

    def setUp(self) -> None:
        cache.clear()
        self.addCleanup(cache.clear)
        self.client = APIClient()
        self.user = TaxiTestData().create_passenger()

    def test_endpoints_require_authentication(self) -> None:
        self.assertEqual(self.client.get("/api/v1/locations/geo/?q=Toshkent").status_code, 401)
        self.assertEqual(self.client.get("/api/v1/locations/geo/reverse/?lat=41&lon=69").status_code, 401)

    def test_search_returns_named_coordinate_fields(self) -> None:
        self.client.force_authenticate(self.user)
        with patch("apps.locations.two_gis.requests.get") as get:
            get.return_value = _FakeResponse(_payload(TASHKENT_ITEM))
            response = self.client.get("/api/v1/locations/geo/", {"q": "Amir Temur"})
        self.assertEqual(response.status_code, 200)
        first = response.json()[0]
        # The frontend reads these keys; latitude/longitude rather than lat/lon
        # so the payload matches the snapshot fields it has to send back. They
        # are JSON *numbers* (coerce_to_string=False) because the map library
        # needs to plot them without parsing.
        self.assertAlmostEqual(first["latitude"], 41.311081, places=6)
        self.assertAlmostEqual(first["longitude"], 69.240562, places=6)
        self.assertEqual(first["address"], "Amir Temur ko'chasi, 12")
        self.assertEqual(first["display_name"], "Toshkent, Amir Temur ko'chasi, 12")
        self.assertEqual(first["city_name"], "Toshkent shahri")
        self.assertEqual(first["district_name"], "Yunusobod tumani")

    def test_search_requires_a_query(self) -> None:
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.get("/api/v1/locations/geo/").status_code, 400)

    def test_search_rejects_half_a_coordinate_pair(self) -> None:
        self.client.force_authenticate(self.user)
        response = self.client.get("/api/v1/locations/geo/", {"q": "Amir Temur", "lat": "41.3"})
        self.assertEqual(response.status_code, 400)

    def test_search_rejects_impossible_coordinates(self) -> None:
        self.client.force_authenticate(self.user)
        response = self.client.get(
            "/api/v1/locations/geo/", {"q": "Amir Temur", "lat": "130", "lon": "69"}
        )
        self.assertEqual(response.status_code, 400)

    def test_search_rejects_a_non_numeric_coordinate(self) -> None:
        self.client.force_authenticate(self.user)
        response = self.client.get(
            "/api/v1/locations/geo/", {"q": "Amir Temur", "lat": "shimol", "lon": "69"}
        )
        self.assertEqual(response.status_code, 400)

    def test_reverse_returns_a_single_object(self) -> None:
        self.client.force_authenticate(self.user)
        with patch("apps.locations.two_gis.requests.get") as get:
            get.return_value = _FakeResponse(_payload(TASHKENT_ITEM))
            response = self.client.get(
                "/api/v1/locations/geo/reverse/", {"lat": "41.311081", "lon": "69.240562"}
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["display_name"], "Toshkent, Amir Temur ko'chasi, 12")

    def test_reverse_requires_both_coordinates(self) -> None:
        self.client.force_authenticate(self.user)
        self.assertEqual(
            self.client.get("/api/v1/locations/geo/reverse/", {"lat": "41.3"}).status_code, 400
        )
