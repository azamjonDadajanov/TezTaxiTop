"""Tests for the passenger map feed (``/rides/trips/nearby/``).

This is the mirror of the driver map: instead of other people's requests the
caller sees every taxi they could actually board. The suite therefore pins down
who may read the feed, which trips qualify, how they are ordered, and what the
payload must not contain.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core import conf
from apps.core.testing import TaxiTestData
from apps.rides.models import DriverTripStatus

#: The passenger stands here (Tashkent city centre).
PASSENGER_POINT = {"latitude": Decimal("41.311081"), "longitude": Decimal("69.240562")}

#: ~1.1 km north of the passenger.
NEAR_PICKUP = {"latitude": Decimal("41.321081"), "longitude": Decimal("69.240562")}
#: ~8.0 km north - still inside the default 25 km radius.
MID_PICKUP = {"latitude": Decimal("41.383081"), "longitude": Decimal("69.240562")}
#: ~40 km north - outside every radius the feed allows.
FAR_PICKUP = {"latitude": Decimal("41.671081"), "longitude": Decimal("69.240562")}

#: Dropoffs far enough from their pickup (the platform refuses a route under 5 km).
NEAR_DROPOFF = {"latitude": Decimal("41.471081"), "longitude": Decimal("69.240562")}
MID_DROPOFF = {"latitude": Decimal("41.553081"), "longitude": Decimal("69.240562")}
FAR_DROPOFF = {"latitude": Decimal("41.850000"), "longitude": Decimal("69.240562")}


class NearbyTripsTestBase(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.data = TaxiTestData()
        self.passenger = self.data.create_passenger()
        self.client.force_authenticate(self.passenger)

    def get_or_create_location(self, name: str, point: dict):
        return self.data.get_or_create_location(
            name,
            latitude=point["latitude"],
            longitude=point["longitude"],
        )

    def create_trip(
        self,
        *,
        pickup: dict,
        dropoff: dict,
        driver=None,
        origin_name: str = "Pickup",
        destination_name: str = "Dropoff",
        **kwargs,
    ):
        driver = driver or self.data.create_driver()
        return self.data.create_trip(
            driver,
            from_location=self.get_or_create_location(f"{origin_name} MFY", pickup),
            to_location=self.get_or_create_location(f"{destination_name} MFY", dropoff),
            **kwargs,
        )

    def feed(self, **params):
        query = {"lat": PASSENGER_POINT["latitude"], "lon": PASSENGER_POINT["longitude"], **params}
        return self.client.get("/api/v1/rides/trips/nearby/", query)


class NearbyTripsAccessTests(NearbyTripsTestBase):
    def test_anonymous_access_is_rejected(self) -> None:
        self.client.force_authenticate(None)
        self.assertEqual(self.feed().status_code, 401)

    def test_a_driver_may_also_read_the_passenger_map(self) -> None:
        """The caller only has to be able to act as a passenger to want a ride."""
        self.client.force_authenticate(self.data.create_driver().user)
        self.assertEqual(self.feed().status_code, 200)

    def test_coordinates_are_mandatory(self) -> None:
        self.assertEqual(self.client.get("/api/v1/rides/trips/nearby/").status_code, 400)

    def test_a_half_coordinate_pair_is_rejected(self) -> None:
        response = self.client.get(
            "/api/v1/rides/trips/nearby/", {"lat": PASSENGER_POINT["latitude"]}
        )
        self.assertEqual(response.status_code, 400)

    def test_a_nonsense_coordinate_is_rejected(self) -> None:
        self.assertEqual(self.feed(lat="north").status_code, 400)

    def test_a_latitude_out_of_range_is_rejected(self) -> None:
        self.assertEqual(self.feed(lat="120").status_code, 400)

    def test_a_longitude_out_of_range_is_rejected(self) -> None:
        self.assertEqual(self.feed(lon="200").status_code, 400)


class NearbyTripsProximityTests(NearbyTripsTestBase):
    def test_a_trip_within_the_radius_is_listed_with_its_distance(self) -> None:
        created = self.create_trip(pickup=NEAR_PICKUP, dropoff=NEAR_DROPOFF)

        body = self.feed().json()

        self.assertEqual(body["count"], 1)
        first = body["results"][0]
        self.assertEqual(first["id"], created.pk)
        self.assertAlmostEqual(first["distance_km"], 1.1, places=1)
        # The pickup-to-dropoff length is what the route line spans on the map.
        self.assertAlmostEqual(first["trip_km"], 16.7, places=1)
        self.assertAlmostEqual(body["radius_km"], 25, places=0)

    def test_a_trip_beyond_the_radius_is_not_listed(self) -> None:
        self.create_trip(pickup=FAR_PICKUP, dropoff=FAR_DROPOFF)

        body = self.feed().json()

        self.assertEqual(body["count"], 0)
        self.assertEqual(body["results"], [])

    def test_a_trip_beyond_a_client_radius_is_filtered_by_it(self) -> None:
        self.create_trip(pickup=MID_PICKUP, dropoff=MID_DROPOFF)

        self.assertEqual(self.feed(radius_km="5").json()["count"], 0)
        self.assertEqual(self.feed(radius_km="12").json()["count"], 1)

    def test_the_radius_is_clamped_to_the_configured_ceiling(self) -> None:
        self.create_trip(pickup=MID_PICKUP, dropoff=MID_DROPOFF)

        with patch.object(conf, "PASSENGER_MAP_MAX_RADIUS_KM", 5):
            body = self.feed(radius_km="500").json()

        self.assertEqual(body["radius_km"], 5)
        self.assertEqual(body["count"], 0)

    def test_a_non_positive_radius_is_rejected(self) -> None:
        self.assertEqual(self.feed(radius_km="0").status_code, 400)

    def test_results_are_ordered_nearest_first(self) -> None:
        far = self.create_trip(pickup=MID_PICKUP, dropoff=MID_DROPOFF, origin_name="Uzoq")
        near = self.create_trip(pickup=NEAR_PICKUP, dropoff=NEAR_DROPOFF, origin_name="Yaqin")

        results = self.feed().json()["results"]

        self.assertEqual([item["id"] for item in results], [near.pk, far.pk])
        self.assertLess(results[0]["distance_km"], results[1]["distance_km"])

    def test_the_caller_own_trip_is_hidden_when_they_are_also_a_driver(self) -> None:
        own = self.data.create_driver()
        self.client.force_authenticate(own.user)
        own_trip = self.create_trip(pickup=NEAR_PICKUP, dropoff=NEAR_DROPOFF, driver=own)
        other_trip = self.create_trip(pickup=MID_PICKUP, dropoff=MID_DROPOFF)

        results = self.feed().json()["results"]

        self.assertEqual([item["id"] for item in results], [other_trip.pk])
        self.assertNotIn(own_trip.pk, [item["id"] for item in results])

    def test_a_cancelled_trip_disappears(self) -> None:
        created = self.create_trip(pickup=NEAR_PICKUP, dropoff=NEAR_DROPOFF)
        created.status = DriverTripStatus.CANCELLED
        created.save(update_fields=["status"])

        self.assertEqual(self.feed().json()["count"], 0)

    def test_a_full_trip_is_not_offered(self) -> None:
        """Nothing to board, so nothing to show."""
        created = self.create_trip(pickup=NEAR_PICKUP, dropoff=NEAR_DROPOFF)
        created.available_seats = 0
        created.status = DriverTripStatus.FULL
        created.save(update_fields=["available_seats", "status"])

        self.assertEqual(self.feed().json()["count"], 0)

    def test_a_draft_trip_is_not_offered(self) -> None:
        created = self.create_trip(pickup=NEAR_PICKUP, dropoff=NEAR_DROPOFF, publish=False)

        self.assertEqual(self.feed().json()["count"], 0)
        self.assertEqual(created.status, DriverTripStatus.DRAFT)

    def test_a_trip_that_already_departed_disappears(self) -> None:
        self.create_trip(
            pickup=NEAR_PICKUP,
            dropoff=NEAR_DROPOFF,
            departure_in=timedelta(hours=-4),
        )

        self.assertEqual(self.feed().json()["count"], 0)

    def test_the_feed_reports_the_echoed_centre(self) -> None:
        body = self.feed().json()

        self.assertAlmostEqual(float(body["center"]["latitude"]), 41.311081, places=5)
        self.assertAlmostEqual(float(body["center"]["longitude"]), 69.240562, places=5)


class NearbyTripsPayloadTests(NearbyTripsTestBase):
    def setUp(self) -> None:
        super().setUp()
        self.driver = self.data.create_driver()
        self.created = self.create_trip(
            pickup=NEAR_PICKUP, dropoff=NEAR_DROPOFF, driver=self.driver
        )
        self.payload = self.feed().json()["results"][0]

    def test_the_payload_carries_what_the_card_needs(self) -> None:
        self.assertEqual(self.payload["id"], self.created.pk)
        self.assertEqual(self.payload["driver_name"], self.driver.user.display_name)
        self.assertEqual(self.payload["driver_username"], self.driver.user.username)
        self.assertEqual(self.payload["status"], DriverTripStatus.ACTIVE)
        self.assertEqual(self.payload["vehicle_brand"], self.driver.vehicle.brand)
        self.assertEqual(self.payload["vehicle_model"], self.driver.vehicle.model)
        self.assertEqual(self.payload["vehicle_plate_number"], self.driver.vehicle.plate_number)
        # The marker is drawn in the car's own colour, so it must be readable.
        self.assertEqual(self.payload["vehicle_color"], self.driver.vehicle.color)
        self.assertEqual(self.payload["vehicle_seats_count"], self.driver.vehicle.seats_count)
        self.assertEqual(
            self.payload["origin"]["display"], self.created.origin_display
        )
        self.assertAlmostEqual(
            self.payload["origin"]["latitude"], float(NEAR_PICKUP["latitude"]), places=5
        )
        self.assertAlmostEqual(
            self.payload["destination"]["latitude"], float(NEAR_DROPOFF["latitude"]), places=5
        )

    def test_a_driver_phone_number_is_never_broadcast(self) -> None:
        body = self.feed().json()

        self.assertNotIn("driver_phone", self.payload)
        self.assertNotIn("driver_telegram_id", self.payload)
        self.assertNotIn(self.driver.user.phone_number, str(body))