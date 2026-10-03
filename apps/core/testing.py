"""Test helpers shared by the app test-suites.

Creating a valid driver with a verified vehicle, an active subscription and an
active trip requires eight rows; doing that inline in every test would drown
the actual assertion. :class:`TaxiTestData` builds a ready-to-use scenario and
is the single place where the business preconditions live.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.locations import services as location_services
from apps.orders import services as order_services
from apps.rides import services as ride_services
from apps.subscriptions import services as subscription_services
from apps.users import services as user_services
from apps.users.constants import UserRole
from apps.users.models import DriverProfile
from apps.vehicles import services as vehicle_services

User = get_user_model()

PLATE = "01B 777AA"


@dataclass
class DriverBundle:
    user: object
    profile: DriverProfile
    vehicle: object
    subscription: object


class TaxiTestData:
    """Factory for the objects every end-to-end test needs."""

    def __init__(self) -> None:
        self._counter = 0

    def _next(self) -> int:
        self._counter += 1
        return self._counter

    # -- users ---------------------------------------------------------------
    def create_passenger(self, **kwargs) -> object:
        index = self._next()
        return User.objects.create_user(
            username=kwargs.pop("username", f"passenger{index}"),
            telegram_id=kwargs.pop("telegram_id", 100000 + index),
            first_name=kwargs.pop("first_name", "Yo'lovchi"),
            phone_number=kwargs.pop("phone_number", f"+99890100{index:04d}"),
            role=UserRole.PASSENGER,
            **kwargs,
        )

    def create_superuser(self, **kwargs) -> object:
        """Staff + superuser, for tests that exercise the Django admin."""
        index = self._next()
        return User.objects.create_superuser(
            username=kwargs.pop("username", f"admin{index}"),
            email=kwargs.pop("email", f"admin{index}@example.com"),
            password=kwargs.pop("password", "admin-pass-123"),
            **kwargs,
        )

    def create_driver(
        self,
        *,
        verified: bool = True,
        vehicle_verified: bool = True,
        with_subscription: bool = True,
        vehicle_seats: int = 4,
        **kwargs,
    ) -> DriverBundle:
        """``vehicle_seats`` is the *total* seat count, driver seat included, so a
        scenario that needs four sellable seats asks for ``vehicle_seats=5``."""
        index = self._next()
        user = User.objects.create_user(
            username=kwargs.pop("username", f"driver{index}"),
            telegram_id=kwargs.pop("telegram_id", 200000 + index),
            first_name=kwargs.pop("first_name", "Haydovchi"),
            phone_number=kwargs.pop("phone_number", f"+99890200{index:04d}"),
            role=UserRole.DRIVER,
            **kwargs,
        )
        profile = user_services.create_driver_profile(user)
        if verified:
            user_services.verify_driver_profile(profile, verified=True)

        vehicle = vehicle_services.create_vehicle(
            driver=profile,
            plate_number=f"{index:02d}B {index:03d}AA",
            brand="Lacetti",
            model="Chery",
            year=2020,
            color="white",
            seats_count=vehicle_seats,
        )
        if vehicle_verified:
            vehicle_services.verify_vehicle(vehicle, verified=True)

        subscription = None
        if with_subscription:
            plan = self.get_or_create_plan()
            subscription = subscription_services.create_subscription(driver=profile, plan=plan)
            subscription = subscription_services.activate_subscription(subscription)

        return DriverBundle(
            user=user, profile=profile, vehicle=vehicle, subscription=subscription
        )

    # -- catalogue -----------------------------------------------------------
    def get_or_create_region(self):
        return location_services.get_or_create_region(name="Toshkent shahri")

    def get_or_create_district(self, region=None):
        region = region or self.get_or_create_region()
        return location_services.get_or_create_district(region=region, name="Sergeli tumani")

    def get_or_create_location(self, name: str, district=None, latitude=None, longitude=None):
        district = district or self.get_or_create_district()
        if latitude is None or longitude is None:
            # Deterministic pseudo-coordinates derived from the name, so that two
            # *different* places never collapse onto a single point (the model
            # rejects a trip whose origin and destination share coordinates) and
            # the same name always maps to the same spot.
            seed = zlib.crc32(name.encode("utf-8"))
            latitude = Decimal("41.200000") + Decimal(seed % 5_000) / Decimal("10000")
            longitude = Decimal("69.200000") + Decimal((seed >> 8) % 5_000) / Decimal("10000")
        return location_services.get_or_create_location(
            district=district, name=name, latitude=latitude, longitude=longitude
        )

    # -- subscriptions -------------------------------------------------------
    def get_or_create_plan(self):
        from apps.subscriptions import selectors as subscription_selectors

        plan = subscription_selectors.get_plan_queryset().filter(name="Oylik").first()
        if plan is not None:
            return plan
        return subscription_services.create_plan(
            name="Oylik", duration_days=30, price=Decimal("50000.00")
        )

    # -- rides ---------------------------------------------------------------
    def create_trip(
        self,
        driver: DriverBundle,
        *,
        from_location=None,
        to_location=None,
        seats: int = 3,
        price: str = "20000.00",
        departure_in: timedelta = timedelta(hours=2),
        publish: bool = True,
    ):
        from_location = from_location or self.get_or_create_location("Qorasuv MFY")
        to_location = to_location or self.get_or_create_location("Sergeli MFY")
        return ride_services.create_trip(
            driver_profile=driver.profile,
            vehicle=driver.vehicle,
            from_location=from_location,
            to_location=to_location,
            departure_time=timezone.now() + departure_in,
            total_seats=seats,
            price_per_seat=Decimal(price),
            publish=publish,
        )

    def create_order(self, trip, passenger, *, seats: int = 1):
        return order_services.create_order(
            passenger=passenger, trip=trip, seats_booked=seats
        )
