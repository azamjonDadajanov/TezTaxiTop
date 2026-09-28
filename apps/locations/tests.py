"""Tests for the locations app."""

from __future__ import annotations

from decimal import Decimal

from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.core.exceptions import BusinessValidationError
from apps.locations import services as location_services
from apps.locations.models import District, Location, Region


class LocationCatalogueTests(TestCase):
    def setUp(self) -> None:
        self.region = location_services.get_or_create_region(name="Toshkent viloyati")
        self.district = location_services.get_or_create_district(
            region=self.region, name="Zangiota tumani"
        )
        self.location = location_services.get_or_create_location(
            district=self.district,
            name="Qorasuv",
            latitude="41.311081",
            longitude="69.240562",
        )

    def test_hierarchy(self) -> None:
        self.assertEqual(self.location.district.region, self.region)
        self.assertEqual(self.location.full_name, "Qorasuv, Zangiota tumani, Toshkent viloyati")

    def test_region_creation_is_idempotent(self) -> None:
        again = location_services.get_or_create_region(name="Toshkent viloyati")
        self.assertEqual(again.pk, self.region.pk)
        self.assertEqual(Region.objects.count(), 1)

    def test_district_unique_per_region(self) -> None:
        from django.db.utils import IntegrityError as DjangoIntegrityError

        with self.assertRaises(DjangoIntegrityError):
            with transaction.atomic():
                District.objects.create(region=self.region, name="Zangiota tumani")

    def test_same_district_name_in_another_region_is_allowed(self) -> None:
        other_region = location_services.get_or_create_region(name="Samarqand viloyati")
        district = location_services.get_or_create_district(region=other_region, name="Zangiota tumani")
        self.assertNotEqual(district.pk, self.district.pk)

    def test_location_unique_per_district(self) -> None:
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Location.objects.create(
                    district=self.district,
                    name="Qorasuv",
                    latitude=Decimal("41.0"),
                    longitude=Decimal("69.0"),
                )

    def test_latitude_range_is_enforced_by_database(self) -> None:
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Location.objects.create(
                    district=self.district,
                    name="Noto'g'ri kenglik",
                    latitude=Decimal("100.5"),
                    longitude=Decimal("69.0"),
                )

    def test_longitude_range_is_enforced_by_database(self) -> None:
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Location.objects.create(
                    district=self.district,
                    name="Noto'g'ri uzunlik",
                    latitude=Decimal("41.0"),
                    longitude=Decimal("-200.0"),
                )

    def test_invalid_coordinates_are_rejected_by_service(self) -> None:
        with self.assertRaises(BusinessValidationError):
            location_services.create_location(
                district=self.district, name="X", latitude=Decimal("91.0"), longitude=Decimal("0.0")
            )

    def test_coordinates_are_stored_as_decimal(self) -> None:
        self.assertIsInstance(self.location.latitude, Decimal)
        self.assertEqual(str(self.location.latitude), "41.311081")

    def test_name_is_normalized(self) -> None:
        location = location_services.get_or_create_location(
            district=self.district, name="  Chirchiq  shahri ", latitude="41.51", longitude="69.21"
        )
        self.assertEqual(location.name, "Chirchiq shahri")

    def test_free_text_resolution(self) -> None:
        found = location_services.resolve_location_by_text("Qorasuv")
        self.assertIsNotNone(found)
        self.assertEqual(found.pk, self.location.pk)

    def test_distance_calculation(self) -> None:
        second = location_services.get_or_create_location(
            district=self.district, name="Yuqorichoq", latitude="41.411081", longitude="69.240562"
        )
        distance = self.location.distance_km_to(second)
        self.assertGreater(distance, 10.0)
        self.assertLess(distance, 12.5)

    def test_update_location_rejects_unknown_field(self) -> None:
        with self.assertRaises(BusinessValidationError):
            location_services.update_location(self.location, region=self.region)

    def test_soft_delete_locations(self) -> None:
        location_services.set_location_active(self.location, is_active=False)
        self.assertFalse(location_services.resolve_location_by_text("Qorasuv"))
