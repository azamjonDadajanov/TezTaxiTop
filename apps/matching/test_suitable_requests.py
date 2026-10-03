"""Tests for the automatic "suitable trips" screen (driver side).

The screen opens on one trip and must already answer "which passengers fit
it?" - no selection, no button, no manual search. This suite therefore pins
down the four hard rules behind that list (geographic route, direction,
departure window, free seats), the measurements the screen shows next to every
passenger, and the fact that *reading* the answer never writes a row of its
own.

Every point below sits on one meridian, so a latitude difference along the
test data *is* a distance - the assertions can be written in kilometres.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

from django.test import TestCase
from rest_framework.test import APIClient

from apps.core import conf
from apps.core.testing import TaxiTestData
from apps.matching import compatibility
from apps.matching import services as matching_services
from apps.matching.models import TripMatch
from apps.rides import services as ride_services

LNG = Decimal("69.240562")

#: The driver's own route: 11.1 km north.
TRIP_PICKUP = Decimal("41.311081")
TRIP_DROPOFF = Decimal("41.411081")

#: A passenger one kilometre off each endpoint - clearly the same street.
ON_ROUTE_PICKUP = Decimal("41.321081")
ON_ROUTE_DROPOFF = Decimal("41.421081")

#: ~5.5 km off both endpoints: inside the 25 km limit.
OFFSET_PICKUP = Decimal("41.361081")
OFFSET_DROPOFF = Decimal("41.461081")

#: ~30 km off both endpoints: outside the 25 km limit.
FAR_PICKUP = Decimal("41.581081")
FAR_DROPOFF = Decimal("41.681081")

#: Near at the pickup, far at the drop-off - the worst endpoint must decide.
SPLIT_DROPOFF = Decimal("41.741081")

#: The same street, walked the other way.
REVERSE_PICKUP = Decimal("41.421081")
REVERSE_DROPOFF = Decimal("41.321081")

BUDGET = Decimal("30000.00")


class SuitableRequestsTestBase(TestCase):
    def setUp(self) -> None:
        self.data = TaxiTestData()
        self.driver = self.data.create_driver()
        self.passenger = self.data.create_passenger()
        self._trips = 0
        self._requests = 0
        self.trip = self.create_trip()

    # -- fixtures -----------------------------------------------------------
    def location(self, name: str, latitude: Decimal):
        return self.data.get_or_create_location(name, latitude=latitude, longitude=LNG)

    def create_trip(self, *, pickup: Decimal = TRIP_PICKUP, dropoff: Decimal = TRIP_DROPOFF, **kwargs):
        self._trips += 1
        return self.data.create_trip(
            self.driver,
            from_location=self.location(f"Haydovchi chiqish {self._trips}", pickup),
            to_location=self.location(f"Haydovchi tushish {self._trips}", dropoff),
            **kwargs,
        )

    def create_request(
        self,
        *,
        pickup: Decimal = ON_ROUTE_PICKUP,
        dropoff: Decimal = ON_ROUTE_DROPOFF,
        departure_from=None,
        departure_until=None,
        passengers: int = 1,
        name: str = "Yo'lovchi",
    ):
        """A passenger whose window brackets the trip departure by default."""
        self._requests += 1
        start = (
            departure_from
            if departure_from is not None
            else self.trip.departure_time - timedelta(minutes=30)
        )
        end = (
            departure_until
            if departure_until is not None
            else self.trip.departure_time + timedelta(minutes=90)
        )
        return ride_services.create_passenger_request(
            passenger=self.data.create_passenger(),
            from_location=self.location(f"{name} chiqish {self._requests}", pickup),
            to_location=self.location(f"{name} tushish {self._requests}", dropoff),
            passenger_count=passengers,
            max_price_per_seat=BUDGET,
            departure_from=start,
            departure_until=end,
        )


class RouteRuleTests(SuitableRequestsTestBase):
    """The geographic half of the rule: same street, same direction."""

    def test_passenger_on_the_route_is_compatible(self) -> None:
        passenger_request = self.create_request()
        measured = compatibility.route_compatibility(self.trip, passenger_request)
        self.assertEqual(matching_services.route_exclusion_reason(self.trip, passenger_request), "")
        self.assertTrue(measured.compatible)
        self.assertLessEqual(measured.distance_difference_km, Decimal("25"))

    def test_passenger_five_and_a_half_kilometres_off_is_compatible(self) -> None:
        passenger_request = self.create_request(pickup=OFFSET_PICKUP, dropoff=OFFSET_DROPOFF)
        measured = compatibility.route_compatibility(self.trip, passenger_request)
        self.assertEqual(matching_services.route_exclusion_reason(self.trip, passenger_request), "")
        self.assertTrue(measured.compatible)
        self.assertGreater(measured.distance_difference_km, Decimal("1"))
        self.assertLessEqual(measured.distance_difference_km, Decimal("25"))

    def test_passenger_beyond_twenty_five_kilometres_is_rejected(self) -> None:
        passenger_request = self.create_request(pickup=FAR_PICKUP, dropoff=FAR_DROPOFF)
        measured = compatibility.route_compatibility(self.trip, passenger_request)
        self.assertGreater(measured.distance_difference_km, Decimal("25"))
        self.assertEqual(matching_services.route_exclusion_reason(self.trip, passenger_request), "route_too_far")
        self.assertEqual(matching_services.exclusion_reason(self.trip, passenger_request), "route_too_far")

    def test_the_worst_endpoint_decides_the_distance(self) -> None:
        passenger_request = self.create_request(pickup=OFFSET_PICKUP, dropoff=SPLIT_DROPOFF)
        measured = compatibility.route_compatibility(self.trip, passenger_request)
        self.assertLessEqual(measured.pickup_km, Decimal("25"))
        self.assertGreater(measured.dropoff_km, Decimal("25"))
        self.assertEqual(measured.distance_difference_km, measured.dropoff_km)
        self.assertEqual(matching_services.exclusion_reason(self.trip, passenger_request), "route_too_far")

    def test_a_passenger_travelling_the_other_way_is_rejected(self) -> None:
        passenger_request = self.create_request(pickup=REVERSE_PICKUP, dropoff=REVERSE_DROPOFF)
        measured = compatibility.route_compatibility(self.trip, passenger_request)
        self.assertFalse(measured.same_direction)
        self.assertLessEqual(measured.distance_difference_km, Decimal("25"))
        self.assertEqual(matching_services.exclusion_reason(self.trip, passenger_request), "opposite_direction")

    def test_detour_is_never_negative(self) -> None:
        passenger_request = self.create_request(pickup=OFFSET_PICKUP, dropoff=OFFSET_DROPOFF)
        measured = compatibility.route_compatibility(self.trip, passenger_request)
        self.assertGreaterEqual(measured.detour_km, Decimal("0"))

    def test_rows_without_coordinates_fall_back_to_the_catalogue_identity(self) -> None:
        """Legacy rows are judged by the pair they name, never by guesswork."""
        legacy = SimpleNamespace(
            from_location_id=None,
            to_location_id=None,
            from_latitude=None,
            from_longitude=None,
            to_latitude=None,
            to_longitude=None,
            from_city_name="Toshkent shahri",
            to_city_name="Sergeli tumani",
        )
        same_route = SimpleNamespace(**vars(legacy))
        other_route = SimpleNamespace(
            **{**vars(legacy), "from_city_name": "Toshkent shahri", "to_city_name": "Buxoro viloyati"}
        )

        measured = compatibility.route_compatibility(legacy, same_route)
        self.assertEqual(measured.reason, "missing_coordinates")
        self.assertFalse(measured.compatible)
        self.assertIsNone(measured.distance_difference_km)
        self.assertEqual(matching_services.route_exclusion_reason(legacy, same_route), "")
        self.assertEqual(matching_services.route_exclusion_reason(legacy, other_route), "route_not_comparable")


class TimeRuleTests(SuitableRequestsTestBase):
    """The departure must sit within the configured tolerance of the window."""

    def test_the_tolerance_is_the_configured_hour(self) -> None:
        self.assertEqual(conf.MATCHING_TIME_TOLERANCE_MINUTES, 60)

    def test_departure_inside_the_window_is_a_match(self) -> None:
        passenger_request = self.create_request()
        self.assertEqual(compatibility.time_difference_minutes(self.trip.departure_time, passenger_request), 0)
        self.assertEqual(matching_services.exclusion_reason(self.trip, passenger_request), "")

    def test_forty_five_minutes_outside_the_window_is_accepted(self) -> None:
        passenger_request = self.create_request(
            departure_from=self.trip.departure_time - timedelta(hours=5),
            departure_until=self.trip.departure_time - timedelta(minutes=45),
        )
        self.assertEqual(compatibility.time_difference_minutes(self.trip.departure_time, passenger_request), 45)
        self.assertEqual(matching_services.exclusion_reason(self.trip, passenger_request), "")

    def test_ninety_minutes_outside_the_window_is_rejected(self) -> None:
        passenger_request = self.create_request(
            departure_from=self.trip.departure_time - timedelta(hours=5),
            departure_until=self.trip.departure_time - timedelta(minutes=90),
        )
        self.assertEqual(compatibility.time_difference_minutes(self.trip.departure_time, passenger_request), 90)
        self.assertFalse(compatibility.time_is_compatible(self.trip.departure_time, passenger_request))
        self.assertEqual(matching_services.exclusion_reason(self.trip, passenger_request), "outside_departure_window")

    def test_a_departure_before_the_window_is_measured_to_its_start(self) -> None:
        passenger_request = self.create_request(
            departure_from=self.trip.departure_time + timedelta(hours=3),
            departure_until=self.trip.departure_time + timedelta(hours=5),
        )
        self.assertEqual(compatibility.time_difference_minutes(self.trip.departure_time, passenger_request), 180)
        self.assertEqual(matching_services.exclusion_reason(self.trip, passenger_request), "outside_departure_window")


class SeatRuleTests(SuitableRequestsTestBase):
    """The party must fit into the seats that are still free."""

    def test_party_bigger_than_the_free_seats_is_rejected(self) -> None:
        passenger_request = self.create_request(passengers=4)
        self.assertEqual(self.trip.available_seats, 3)
        self.assertEqual(matching_services.exclusion_reason(self.trip, passenger_request), "not_enough_seats")

    def test_party_that_fits_the_free_seats_is_kept(self) -> None:
        passenger_request = self.create_request(passengers=3)
        self.assertEqual(matching_services.exclusion_reason(self.trip, passenger_request), "")


class SuitablePassengersTests(SuitableRequestsTestBase):
    """What the screen shows the moment the driver opens it."""

    def test_only_passengers_that_fit_reach_the_screen(self) -> None:
        fitting = self.create_request(name="Mos")
        self.create_request(pickup=FAR_PICKUP, dropoff=FAR_DROPOFF, name="Uzoq")
        self.create_request(pickup=REVERSE_PICKUP, dropoff=REVERSE_DROPOFF, name="Teskari")
        self.create_request(
            departure_from=self.trip.departure_time - timedelta(hours=5),
            departure_until=self.trip.departure_time - timedelta(minutes=90),
            name="Kech",
        )
        self.create_request(passengers=4, name="To'la")

        candidates = matching_services.get_candidate_requests(self.trip)
        self.assertEqual([candidate.pk for candidate in candidates], [fitting.pk])

    def test_ranking_is_identical_between_two_reads(self) -> None:
        first_request = self.create_request(name="Birinchi")
        second_request = self.create_request(pickup=OFFSET_PICKUP, dropoff=OFFSET_DROPOFF, name="Ikkinchi")

        first = matching_services.get_ranked_matches_for_trip(self.trip)
        second = matching_services.get_ranked_matches_for_trip(self.trip)

        self.assertEqual([match.request_id for match in first], [first_request.pk, second_request.pk])
        self.assertEqual(
            [(match.request_id, str(match.score), match.rank) for match in first],
            [(match.request_id, str(match.score), match.rank) for match in second],
        )
        self.assertEqual([match.rank for match in first], [1, 2])

    def test_reading_the_ranking_writes_nothing(self) -> None:
        self.create_request()
        rows_before = TripMatch.objects.count()

        matches = matching_services.get_ranked_matches_for_trip(self.trip)

        self.assertEqual(len(matches), 1)
        self.assertIsNone(matches[0].pk)
        self.assertEqual(TripMatch.objects.count(), rows_before)

    def test_a_match_carries_both_halves_of_the_pair(self) -> None:
        passenger_request = self.create_request()
        [match] = matching_services.get_ranked_matches_for_trip(self.trip)

        self.assertEqual(match.trip_id, self.trip.pk)
        self.assertEqual(match.request_id, passenger_request.pk)
        self.assertGreaterEqual(match.rank, 1)
        self.assertGreater(match.score, Decimal("0"))
        self.assertGreaterEqual(match.minutes_difference, 0)


class TripRankingApiTests(SuitableRequestsTestBase):
    """``GET /api/v1/matching/trips/<trip_id>/requests/`` - the screen's feed."""

    def setUp(self) -> None:
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(self.driver.user)

    def feed(self, trip_id: int | None = None):
        return self.client.get(f"/api/v1/matching/trips/{trip_id or self.trip.pk}/requests/")

    def test_the_screen_arrives_already_filled(self) -> None:
        passenger_request = self.create_request()
        response = self.feed()
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        self.assertEqual(payload["trip_id"], self.trip.pk)
        [row] = payload["results"]
        self.assertEqual(row["request_id"], passenger_request.pk)
        self.assertEqual(row["trip_id"], self.trip.pk)
        self.assertEqual(row["required_seats"], passenger_request.passenger_count)
        self.assertEqual(row["available_seats"], self.trip.available_seats)
        self.assertEqual(row["time_difference_minutes"], 0)
        self.assertTrue(row["route_compatible"])
        self.assertEqual(row["route_status"], "")
        self.assertGreaterEqual(row["rank"], 1)
        self.assertGreaterEqual(row["score"], "0.00")

    def test_every_measurement_the_screen_shows_is_in_the_payload(self) -> None:
        self.create_request(pickup=OFFSET_PICKUP, dropoff=OFFSET_DROPOFF)
        response = self.feed()
        [row] = response.json()["results"]

        for field in (
            "distance_difference_km",
            "pickup_offset_km",
            "dropoff_offset_km",
            "route_deviation_km",
            "time_difference_minutes",
            "required_seats",
            "available_seats",
            "pickup_location",
            "dropoff_location",
            "departure_from",
            "departure_until",
            "passenger_name",
        ):
            self.assertIn(field, row)
        self.assertIsNotNone(row["distance_difference_km"])
        self.assertIsNotNone(row["route_deviation_km"])
        self.assertLessEqual(row["distance_difference_km"], 25)
        self.assertGreaterEqual(row["route_deviation_km"], 0)

    def test_passengers_that_do_not_fit_are_not_returned(self) -> None:
        self.create_request(pickup=FAR_PICKUP, dropoff=FAR_DROPOFF, name="Uzoq")
        self.create_request(passengers=4, name="To'la")
        response = self.feed()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"], [])

    def test_another_driver_cannot_read_the_ranking(self) -> None:
        self.create_request()
        self.client.force_authenticate(self.data.create_driver().user)
        self.assertEqual(self.feed().status_code, 403)

    def test_anonymous_cannot_read_the_ranking(self) -> None:
        self.client.force_authenticate(None)
        self.assertEqual(self.feed().status_code, 401)

    def test_unknown_trip_is_not_found(self) -> None:
        self.assertEqual(self.feed(trip_id=999999).status_code, 404)
