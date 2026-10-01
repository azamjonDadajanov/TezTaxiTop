"""Tests for the driver map feed (``/rides/requests/nearby/``).

The map is the one screen where a driver sees *other* people's requests, so the
suite pins down the four things that could leak or mislead: who may read the
feed, which requests qualify as "nearby", how they are ordered, and what the
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
from apps.rides import services as ride_services
from apps.rides.models import PassengerRequestStatus

#: The driver stands here (Tashkent city centre).
DRIVER_POINT = {"latitude": Decimal("41.311081"), "longitude": Decimal("69.240562")}

#: ~1.1 km north of the driver.
NEAR_PICKUP = {"latitude": Decimal("41.321081"), "longitude": Decimal("69.240562")}
#: ~8.0 km north - still inside the default 25 km radius.
MID_PICKUP = {"latitude": Decimal("41.383081"), "longitude": Decimal("69.240562")}
#: ~40 km north - outside every radius the feed allows.
FAR_PICKUP = {"latitude": Decimal("41.671081"), "longitude": Decimal("69.240562")}

#: Dropoffs far enough from their pickup (the platform refuses a route under 5 km).
NEAR_DROPOFF = {"latitude": Decimal("41.471081"), "longitude": Decimal("69.240562")}
MID_DROPOFF = {"latitude": Decimal("41.553081"), "longitude": Decimal("69.240562")}
FAR_DROPOFF = {"latitude": Decimal("41.850000"), "longitude": Decimal("69.240562")}


class NearbyRequestsTestBase(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.data = TaxiTestData()
        self.driver = self.data.create_driver()
        self.client.force_authenticate(self.driver.user)
        self.passenger = self.data.create_passenger()

    def get_or_create_location(self, name: str, point: dict):
        return self.data.get_or_create_location(
            name,
            latitude=point["latitude"],
            longitude=point["longitude"],
        )

    def create_request(
        self,
        *,
        pickup: dict,
        dropoff: dict,
        passenger=None,
        origin_name: str = "Pickup",
        destination_name: str = "Dropoff",
        **kwargs,
    ):
        departure = timezone.now() + timedelta(hours=1)
        return ride_services.create_passenger_request(
            passenger=passenger or self.passenger,
            from_location=self.get_or_create_location(f"{origin_name} MFY", pickup),
            to_location=self.get_or_create_location(f"{destination_name} MFY", dropoff),
            passenger_count=kwargs.pop("passenger_count", 1),
            departure_from=departure,
            departure_until=departure + timedelta(hours=4),
            **kwargs,
        )

    def feed(self, **params):
        query = {"lat": DRIVER_POINT["latitude"], "lon": DRIVER_POINT["longitude"], **params}
        return self.client.get("/api/v1/rides/requests/nearby/", query)


class NearbyRequestsAccessTests(NearbyRequestsTestBase):
    def test_anonymous_access_is_rejected(self) -> None:
        self.client.force_authenticate(None)
        self.assertEqual(self.feed().status_code, 401)

    def test_a_plain_passenger_may_not_read_the_driver_map(self) -> None:
        self.client.force_authenticate(self.data.create_passenger())
        self.assertEqual(self.feed().status_code, 403)

    def test_a_driver_reads_the_feed(self) -> None:
        self.assertEqual(self.feed().status_code, 200)

    def test_coordinates_are_mandatory(self) -> None:
        response = self.client.get("/api/v1/rides/requests/nearby/")
        self.assertEqual(response.status_code, 400)

    def test_a_half_coordinate_pair_is_rejected(self) -> None:
        response = self.client.get(
            "/api/v1/rides/requests/nearby/", {"lat": DRIVER_POINT["latitude"]}
        )
        self.assertEqual(response.status_code, 400)

    def test_a_nonsense_coordinate_is_rejected(self) -> None:
        self.assertEqual(self.feed(lat="north").status_code, 400)

    def test_a_coordinate_out_of_range_is_rejected(self) -> None:
        self.assertEqual(self.feed(lat="120").status_code, 400)


class NearbyRequestsProximityTests(NearbyRequestsTestBase):
    def test_a_request_within_the_radius_is_listed_with_its_distance(self) -> None:
        created = self.create_request(pickup=NEAR_PICKUP, dropoff=NEAR_DROPOFF)

        body = self.feed().json()

        self.assertEqual(body["count"], 1)
        first = body["results"][0]
        self.assertEqual(first["id"], created.pk)
        self.assertAlmostEqual(first["distance_km"], 1.1, places=1)
        # The pickup-to-dropoff length is what the arrow spans on the map.
        self.assertAlmostEqual(first["trip_km"], 16.7, places=1)
        self.assertAlmostEqual(body["radius_km"], 25, places=0)

    def test_a_request_beyond_the_radius_is_not_listed(self) -> None:
        self.create_request(pickup=FAR_PICKUP, dropoff=FAR_DROPOFF)

        body = self.feed().json()

        self.assertEqual(body["count"], 0)
        self.assertEqual(body["results"], [])

    def test_a_request_beyond_a_client_radius_is_filtered_by_it(self) -> None:
        self.create_request(pickup=MID_PICKUP, dropoff=MID_DROPOFF)

        self.assertEqual(self.feed(radius_km="5").json()["count"], 0)
        self.assertEqual(self.feed(radius_km="12").json()["count"], 1)

    def test_the_radius_is_clamped_to_the_configured_ceiling(self) -> None:
        self.create_request(pickup=MID_PICKUP, dropoff=MID_DROPOFF)

        with patch.object(conf, "DRIVER_MAP_MAX_RADIUS_KM", 5):
            body = self.feed(radius_km="500").json()

        self.assertEqual(body["radius_km"], 5)
        self.assertEqual(body["count"], 0)

    def test_a_non_positive_radius_is_rejected(self) -> None:
        self.assertEqual(self.feed(radius_km="0").status_code, 400)

    def test_results_are_ordered_nearest_first(self) -> None:
        far = self.create_request(pickup=MID_PICKUP, dropoff=MID_DROPOFF, origin_name="Uzoq")
        near = self.create_request(pickup=NEAR_PICKUP, dropoff=NEAR_DROPOFF, origin_name="Yaqin")

        results = self.feed().json()["results"]

        self.assertEqual([item["id"] for item in results], [near.pk, far.pk])
        self.assertLess(results[0]["distance_km"], results[1]["distance_km"])

    def test_the_drivers_own_request_is_hidden_from_them(self) -> None:
        """A driver who is also a passenger must not bid on their own trip."""
        self.create_request(pickup=NEAR_PICKUP, dropoff=NEAR_DROPOFF, passenger=self.driver.user)
        self.create_request(pickup=MID_PICKUP, dropoff=MID_DROPOFF)

        results = self.feed().json()["results"]

        self.assertEqual(len(results), 1)
        self.assertNotEqual(results[0]["passenger"], self.driver.user.pk)

    def test_a_cancelled_request_disappears(self) -> None:
        created = self.create_request(pickup=NEAR_PICKUP, dropoff=NEAR_DROPOFF)
        created.status = PassengerRequestStatus.CANCELLED
        created.save(update_fields=["status"])

        self.assertEqual(self.feed().json()["count"], 0)

    def test_a_request_whose_departure_window_closed_disappears(self) -> None:
        departure = timezone.now() - timedelta(hours=3)
        ride_services.create_passenger_request(
            passenger=self.passenger,
            from_location=self.get_or_create_location("O'tgan MFY", NEAR_PICKUP),
            to_location=self.get_or_create_location("Keyin MFY", NEAR_DROPOFF),
            departure_from=departure,
            departure_until=departure + timedelta(hours=1),
        )

        self.assertEqual(self.feed().json()["count"], 0)

    def test_the_feed_reports_the_echoed_centre(self) -> None:
        body = self.feed().json()

        self.assertAlmostEqual(float(body["center"]["latitude"]), 41.311081, places=5)
        self.assertAlmostEqual(float(body["center"]["longitude"]), 69.240562, places=5)


class NearbyRequestsPayloadTests(NearbyRequestsTestBase):
    def setUp(self) -> None:
        super().setUp()
        self.created = self.create_request(pickup=NEAR_PICKUP, dropoff=NEAR_DROPOFF)
        self.payload = self.feed().json()["results"][0]

    def test_the_payload_carries_what_the_card_needs(self) -> None:
        self.assertEqual(self.payload["id"], self.created.pk)
        self.assertEqual(self.payload["passenger_name"], self.passenger.display_name)
        self.assertEqual(self.payload["passenger_username"], self.passenger.username)
        self.assertEqual(self.payload["status"], PassengerRequestStatus.ACTIVE)
        self.assertEqual(self.payload["comment"], "")
        self.assertEqual(
            self.payload["origin"]["display"], self.created.origin_display
        )
        self.assertAlmostEqual(
            self.payload["origin"]["latitude"], float(NEAR_PICKUP["latitude"]), places=5
        )
        self.assertAlmostEqual(
            self.payload["destination"]["latitude"], float(NEAR_DROPOFF["latitude"]), places=5
        )

    def test_a_passenger_phone_number_is_never_broadcast(self) -> None:
        body = self.feed().json()

        self.assertNotIn("passenger_phone", body["results"][0])
        self.assertNotIn(self.passenger.phone_number, str(body))