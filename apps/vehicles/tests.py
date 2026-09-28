"""Tests for the vehicles app."""

from __future__ import annotations

from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.core.exceptions import BusinessValidationError
from apps.users import services as user_services
from apps.users.constants import UserRole
from apps.users.models import User
from apps.vehicles import selectors as vehicle_selectors
from apps.vehicles import services as vehicle_services
from apps.vehicles.models import Vehicle, normalize_plate_number


class PlateNumberNormalisationTests(TestCase):
    def test_normalisation_is_canonical(self) -> None:
        self.assertEqual(normalize_plate_number("01b777aa"), "01B 777AA")
        self.assertEqual(normalize_plate_number(" 01 b 777 aa "), "01B 777AA")

    def test_short_plates(self) -> None:
        self.assertEqual(normalize_plate_number("abc"), "ABC")


class VehicleCreationTests(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(username="ali", telegram_id=1, role=UserRole.DRIVER)
        self.driver = user_services.create_driver_profile(self.user)

    def test_create_vehicle(self) -> None:
        vehicle = vehicle_services.create_vehicle(
            driver=self.driver,
            brand="Lancia",
            model="Doblo",
            color="Oq",
            plate_number="01b777aa",
            year=2018,
            seats_count=5,
        )
        self.assertEqual(vehicle.plate_number, "01B 777AA")
        self.assertFalse(vehicle.is_verified)
        self.assertTrue(vehicle.is_active)
        self.assertEqual(vehicle.seats_for_passengers, 4)

    def test_driver_can_own_multiple_vehicles(self) -> None:
        for plate in ("01A 111AA", "01A 222BB"):
            vehicle_services.create_vehicle(
                driver=self.driver,
                brand="Hyundai",
                model="Accent",
                color="Kumush",
                plate_number=plate,
                year=2020,
            )
        self.assertEqual(vehicle_selectors.get_vehicles_by_driver(self.driver).count(), 2)

    def test_plate_number_is_unique(self) -> None:
        vehicle_services.create_vehicle(
            driver=self.driver, brand="A", model="B", color="Oq", plate_number="01A 111AA", year=2015
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Vehicle.objects.create(
                    driver=self.driver,
                    brand="A",
                    model="B",
                    color="Qora",
                    plate_number="01A 111AA",
                    year=2016,
                    seats_count=4,
                )

    def test_invalid_year_is_rejected(self) -> None:
        with self.assertRaises(BusinessValidationError):
            vehicle_services.create_vehicle(
                driver=self.driver, brand="A", model="B", color="Oq", plate_number="01A 222BB", year=1900
            )

    def test_zero_seats_is_rejected_by_database(self) -> None:
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Vehicle.objects.create(
                    driver=self.driver,
                    brand="A",
                    model="B",
                    color="Oq",
                    plate_number="01A 333CC",
                    year=2020,
                    seats_count=0,
                )

    def test_blank_plate_is_rejected(self) -> None:
        with self.assertRaises(BusinessValidationError):
            vehicle_services.create_vehicle(
                driver=self.driver, brand="A", model="B", color="Oq", plate_number="   ", year=2020
            )


class VehicleStateTests(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(username="ali", telegram_id=1, role=UserRole.DRIVER)
        self.driver = user_services.create_driver_profile(self.user)
        self.vehicle = vehicle_services.create_vehicle(
            driver=self.driver, brand="Lancia", model="Doblo", color="Oq", plate_number="01A 111AA", year=2018
        )

    def test_verify_vehicle(self) -> None:
        vehicle_services.verify_vehicle(self.vehicle)
        self.vehicle.refresh_from_db()
        self.assertTrue(self.vehicle.is_verified)
        self.assertTrue(self.vehicle.is_usable_for_trip)
        self.assertIsNotNone(self.vehicle.verified_at)

    def test_unverify_vehicle(self) -> None:
        vehicle_services.verify_vehicle(self.vehicle)
        vehicle_services.verify_vehicle(self.vehicle, verified=False)
        self.vehicle.refresh_from_db()
        self.assertFalse(self.vehicle.is_verified)
        self.assertIsNone(self.vehicle.verified_at)

    def test_deactivate_vehicle(self) -> None:
        vehicle_services.verify_vehicle(self.vehicle)
        vehicle_services.set_vehicle_active(self.vehicle, is_active=False)
        self.vehicle.refresh_from_db()
        self.assertFalse(self.vehicle.is_usable_for_trip)
        self.assertFalse(vehicle_selectors.get_usable_vehicles().exists())

    def test_update_vehicle_rejects_unknown_fields(self) -> None:
        with self.assertRaises(BusinessValidationError):
            vehicle_services.update_vehicle(self.vehicle, is_verified=True)

    def test_update_vehicle(self) -> None:
        vehicle_services.update_vehicle(self.vehicle, brand="Chevrolet", year=2021)
        self.vehicle.refresh_from_db()
        self.assertEqual(self.vehicle.brand, "Chevrolet")
        self.assertEqual(self.vehicle.year, 2021)

    def test_selectors(self) -> None:
        vehicle_services.verify_vehicle(self.vehicle)
        self.assertTrue(vehicle_selectors.has_usable_vehicle(self.driver))
        self.assertEqual(vehicle_selectors.get_vehicle_by_plate_number("01a 111aa").pk, self.vehicle.pk)
        self.assertIsNotNone(vehicle_selectors.get_vehicle_by_plate_number("01A111AA"))
