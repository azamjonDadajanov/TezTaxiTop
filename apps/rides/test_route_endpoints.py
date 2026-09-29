"""Tests for map-picked route endpoints on trips and passenger requests.

A driver or passenger may now pick a point on the map instead of choosing a
curated :class:`~apps.locations.models.Location`. That makes the two route
endpoints independent rows of plain coordinates, so these tests cover the
consequences: geocoding on create, safe partial updates, and the guards that
stop an unusable or self-contradictory route from being stored.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.core.exceptions import BusinessValidationError
from apps.core.testing import TaxiTestData
from apps.rides import services as ride_services

from apps.locations.test_two_gis import TASHKENT_ITEM, _FakeResponse, _payload

TASHKENT = {"latitude": "41.311081", "longitude": "69.240562"}
SAMARKAND = {"latitude": "39.650000", "longitude": "66.960000"}


@override_settings(TWOGIS_API_KEY="test-key", TWOGIS_REGION_ID=42)
class MapEndpointTripTests(TestCase):
    def setUp(self) -> None:
        cache.clear()
        self.addCleanup(cache.clear)
        self.data = TaxiTestData()
        self.driver = self.data.create_driver()
        self.departure = timezone.now() + timedelta(hours=2)

    def create_trip(self, **kwargs):
        params = {
            "driver_profile": self.driver.profile,
            "vehicle": self.driver.vehicle,
            "departure_time": self.departure,
            "total_seats": 3,
            "price_per_seat": Decimal("20000.00"),
            "origin": dict(TASHKENT),
            "destination": dict(SAMARKAND),
        }
        params.update(kwargs)
        return ride_services.create_trip(**params)

    def test_map_points_are_stored_without_any_catalogue_location(self) -> None:
        with patch("apps.locations.two_gis.requests.get", return_value=_FakeResponse(_payload(TASHKENT_ITEM))):
            trip = self.create_trip()

        self.assertIsNone(trip.from_location_id)
        self.assertIsNone(trip.to_location_id)
        self.assertEqual(trip.from_latitude, Decimal("41.311081"))
        self.assertEqual(trip.to_latitude, Decimal("39.650000"))
        self.assertEqual(trip.from_city_name, "Toshkent shahri")
        self.assertEqual(trip.from_district_name, "Yunusobod tumani")
        self.assertEqual(trip.origin_display, "Toshkent, Amir Temur ko'chasi, 12")

    def test_missing_endpoint_is_rejected(self) -> None:
        with self.assertRaises(BusinessValidationError):
            self.create_trip(origin=None)

    def test_address_without_coordinates_is_rejected(self) -> None:
        """Free text alone cannot be mapped, geocoded or route-compared."""
        with self.assertRaises(BusinessValidationError):
            self.create_trip(origin={"address": "Amir Temur ko'chasi, 12"})

    def test_identical_endpoints_are_rejected_without_catalogue_locations(self) -> None:
        """The old check only compared catalogue FKs, so map trips slipped through."""
        with patch("apps.locations.two_gis.requests.get", return_value=_FakeResponse(_payload(TASHKENT_ITEM))):
            with self.assertRaises(BusinessValidationError):
                self.create_trip(destination=dict(TASHKENT))

    def test_outage_still_publishes_the_trip(self) -> None:
        with patch("apps.locations.two_gis.requests.get", side_effect=OSError("network down")):
            trip = self.create_trip()

        self.assertEqual(trip.status, "active")
        self.assertEqual(trip.from_latitude, Decimal("41.311081"))
        self.assertEqual(trip.from_address, "")

    def test_partial_origin_update_keeps_the_stored_address(self) -> None:
        """Regression: a PATCH that only moves the pin must not blank the address."""
        with patch("apps.locations.two_gis.requests.get", return_value=_FakeResponse(_payload(TASHKENT_ITEM))):
            trip = self.create_trip()
            self.assertEqual(trip.from_address, "Toshkent, Amir Temur ko'chasi, 12")

            moved = ride_services.update_trip(trip, origin={"latitude": "41.400000", "longitude": "69.300000"})
            moved.refresh_from_db()

        self.assertEqual(moved.from_latitude, Decimal("41.400000"))
        self.assertEqual(moved.from_address, "Toshkent, Amir Temur ko'chasi, 12")
        self.assertEqual(moved.from_city_name, "Toshkent shahri")

    def test_moving_the_onto_the_destination_is_rejected(self) -> None:
        with patch("apps.locations.two_gis.requests.get", return_value=_FakeResponse(_payload(TASHKENT_ITEM))):
            trip = self.create_trip()
            with self.assertRaises(BusinessValidationError):
                ride_services.update_trip(trip, origin=dict(SAMARKAND))


@override_settings(TWOGIS_API_KEY="test-key", TWOGIS_REGION_ID=42)
class MapEndpointRequestTests(TestCase):
    """The passenger side must resolve endpoints exactly like the driver side."""

    def setUp(self) -> None:
        cache.clear()
        self.addCleanup(cache.clear)
        self.data = TaxiTestData()
        self.passenger = self.data.create_passenger()

    def create_request(self, **kwargs):
        params = {
            "passenger": self.passenger,
            "origin": dict(TASHKENT),
            "destination": dict(SAMARKAND),
            "departure_from": timezone.now() + timedelta(hours=1),
            "departure_until": timezone.now() + timedelta(hours=3),
            "passenger_count": 1,
        }
        params.update(kwargs)
        return ride_services.create_passenger_request(**params)

    def test_map_points_are_stored_without_any_catalogue_location(self) -> None:
        with patch("apps.locations.two_gis.requests.get", return_value=_FakeResponse(_payload(TASHKENT_ITEM))):
            request = self.create_request()

        self.assertIsNone(request.from_location_id)
        self.assertEqual(request.from_city_name, "Toshkent shahri")
        self.assertIn("Amir Temur", request.destination_display)

    def test_identical_endpoints_are_rejected(self) -> None:
        with patch("apps.locations.two_gis.requests.get", return_value=_FakeResponse(_payload(TASHKENT_ITEM))):
            with self.assertRaises(BusinessValidationError):
                self.create_request(destination=dict(TASHKENT))
