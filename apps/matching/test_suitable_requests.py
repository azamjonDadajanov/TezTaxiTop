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

#: The inclusive ``MATCHING_MAX_ROUTE_DISTANCE_KM`` boundary, measured with the
#: same great-circle helper the matcher uses: each of the two points below sits
#: exactly 25.00 km north of the corresponding endpoint of the driver's route,
#: so the assertions can be written in kilometres rather than in degrees.
LIMIT_PICKUP = Decimal("41.535911")
LIMIT_DROPOFF = Decimal("41.635911")

#: 26.00 km north of the same two endpoints - just outside the limit.
OVER_LIMIT_PICKUP = Decimal("41.544905")
OVER_LIMIT_DROPOFF = Decimal("41.644905")

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
        trip=None,
    ):
        """A passenger whose window brackets the given trip's departure by default.

        ``trip`` defaults to the one the fixture opened with, so a second trip in
        a multi-trip scenario gets its own passengers instead of borrowing the
        first one's clock.
        """
        self._requests += 1
        reference = trip or self.trip
        start = (
            departure_from
            if departure_from is not None
            else reference.departure_time - timedelta(minutes=30)
        )
        end = (
            departure_until
            if departure_until is not None
            else reference.departure_time + timedelta(minutes=90)
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

    def test_exactly_twenty_five_kilometres_is_still_a_match(self) -> None:
        """The limit is inclusive, so 25.00 km in both directions is accepted."""
        passenger_request = self.create_request(pickup=LIMIT_PICKUP, dropoff=LIMIT_DROPOFF)
        measured = compatibility.route_compatibility(self.trip, passenger_request)
        self.assertEqual(measured.pickup_km, Decimal("25.00"))
        self.assertEqual(measured.dropoff_km, Decimal("25.00"))
        self.assertEqual(measured.distance_difference_km, Decimal("25.00"))
        self.assertTrue(measured.same_direction)
        self.assertTrue(measured.compatible)
        self.assertEqual(matching_services.exclusion_reason(self.trip, passenger_request), "")
        self.assertEqual(
            [candidate.pk for candidate in matching_services.get_candidate_requests(self.trip)],
            [passenger_request.pk],
        )

    def test_twenty_six_kilometres_is_rejected(self) -> None:
        passenger_request = self.create_request(
            pickup=OVER_LIMIT_PICKUP, dropoff=OVER_LIMIT_DROPOFF
        )
        measured = compatibility.route_compatibility(self.trip, passenger_request)
        self.assertEqual(measured.distance_difference_km, Decimal("26.00"))
        self.assertTrue(measured.same_direction)
        self.assertEqual(matching_services.exclusion_reason(self.trip, passenger_request), "route_too_far")

    def test_a_pickup_over_the_limit_rejects_the_pair_on_its_own(self) -> None:
        """26 km at the pickup, exactly 25 km at the drop-off - the worst endpoint decides."""
        passenger_request = self.create_request(pickup=OVER_LIMIT_PICKUP, dropoff=LIMIT_DROPOFF)
        measured = compatibility.route_compatibility(self.trip, passenger_request)
        self.assertEqual(measured.pickup_km, Decimal("26.00"))
        self.assertEqual(measured.dropoff_km, Decimal("25.00"))
        self.assertEqual(matching_services.exclusion_reason(self.trip, passenger_request), "route_too_far")

    def test_a_dropoff_over_the_limit_rejects_the_pair_on_its_own(self) -> None:
        """One kilometre at the pickup, 26 km at the drop-off - still rejected."""
        passenger_request = self.create_request(pickup=ON_ROUTE_PICKUP, dropoff=OVER_LIMIT_DROPOFF)
        measured = compatibility.route_compatibility(self.trip, passenger_request)
        self.assertEqual(measured.dropoff_km, Decimal("26.00"))
        self.assertTrue(measured.same_direction)
        self.assertEqual(matching_services.exclusion_reason(self.trip, passenger_request), "route_too_far")

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

    def test_the_matching_basis_says_which_rule_decided(self) -> None:
        """A coordinate-free pair may be shown, but never as a measured match."""
        measured_pair = self.create_request()
        self.assertEqual(
            matching_services.route_match_basis(self.trip, measured_pair),
            matching_services.ROUTE_BASIS_COORDINATES,
        )

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
            **{**vars(legacy), "to_city_name": "Buxoro viloyati"}
        )
        self.assertEqual(
            matching_services.route_match_basis(legacy, same_route),
            matching_services.ROUTE_BASIS_ROUTE_IDENTITY,
        )
        self.assertEqual(
            matching_services.route_match_basis(legacy, other_route),
            matching_services.ROUTE_BASIS_INCOMPARABLE,
        )


class TimeRuleTests(SuitableRequestsTestBase):
    """The departure must sit within the configured tolerance of the window.

    A passenger departure is a **window** (``departure_from`` /
    ``departure_until``), not an instant, and that is the stored business rule -
    :mod:`apps.matching.compatibility` measures the trip departure against the
    nearer end of the window. So 0 minutes means "inside the window", and the
    60-minute tolerance is the distance to the window's edge. These tests pin
    that semantics down instead of silently reinterpreting the data model.
    """

    def test_the_tolerance_is_the_configured_hour(self) -> None:
        self.assertEqual(conf.MATCHING_TIME_TOLERANCE_MINUTES, 60)

    def departure_before_window(self, minutes: int):
        """A request whose whole window closed ``minutes`` before the departure."""
        return self.create_request(
            departure_from=self.trip.departure_time - timedelta(hours=6),
            departure_until=self.trip.departure_time - timedelta(minutes=minutes),
        )

    def test_departure_inside_the_window_is_a_match(self) -> None:
        passenger_request = self.create_request()
        self.assertEqual(compatibility.time_difference_minutes(self.trip.departure_time, passenger_request), 0)
        self.assertEqual(matching_services.exclusion_reason(self.trip, passenger_request), "")

    def test_zero_minutes_outside_the_window_is_accepted(self) -> None:
        passenger_request = self.departure_before_window(0)
        self.assertEqual(compatibility.time_difference_minutes(self.trip.departure_time, passenger_request), 0)
        self.assertEqual(matching_services.exclusion_reason(self.trip, passenger_request), "")

    def test_thirty_minutes_outside_the_window_is_accepted(self) -> None:
        passenger_request = self.departure_before_window(30)
        self.assertEqual(compatibility.time_difference_minutes(self.trip.departure_time, passenger_request), 30)
        self.assertEqual(matching_services.exclusion_reason(self.trip, passenger_request), "")

    def test_forty_five_minutes_outside_the_window_is_accepted(self) -> None:
        passenger_request = self.departure_before_window(45)
        self.assertEqual(compatibility.time_difference_minutes(self.trip.departure_time, passenger_request), 45)
        self.assertEqual(matching_services.exclusion_reason(self.trip, passenger_request), "")

    def test_sixty_minutes_outside_the_window_is_accepted(self) -> None:
        """The tolerance is inclusive, so exactly one hour still matches."""
        passenger_request = self.departure_before_window(60)
        self.assertEqual(compatibility.time_difference_minutes(self.trip.departure_time, passenger_request), 60)
        self.assertTrue(compatibility.time_is_compatible(self.trip.departure_time, passenger_request))
        self.assertEqual(matching_services.exclusion_reason(self.trip, passenger_request), "")
        self.assertEqual(
            [candidate.pk for candidate in matching_services.get_candidate_requests(self.trip)],
            [passenger_request.pk],
        )

    def test_sixty_one_minutes_outside_the_window_is_rejected(self) -> None:
        passenger_request = self.departure_before_window(61)
        self.assertEqual(compatibility.time_difference_minutes(self.trip.departure_time, passenger_request), 61)
        self.assertFalse(compatibility.time_is_compatible(self.trip.departure_time, passenger_request))
        self.assertEqual(matching_services.exclusion_reason(self.trip, passenger_request), "outside_departure_window")

    def test_ninety_minutes_outside_the_window_is_rejected(self) -> None:
        passenger_request = self.departure_before_window(90)
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

    def test_the_nearer_end_of_the_window_decides(self) -> None:
        """Both ends are considered, so a window that closes late still matches."""
        passenger_request = self.create_request(
            departure_from=self.trip.departure_time - timedelta(minutes=10),
            departure_until=self.trip.departure_time + timedelta(minutes=10),
        )
        self.assertEqual(compatibility.time_difference_minutes(self.trip.departure_time, passenger_request), 0)
        self.assertEqual(matching_services.exclusion_reason(self.trip, passenger_request), "")


class SeatRuleTests(SuitableRequestsTestBase):
    """The party must fit into the seats that are still free."""

    def test_party_bigger_than_the_free_seats_is_rejected(self) -> None:
        passenger_request = self.create_request(passengers=4)
        self.assertEqual(self.trip.available_seats, 3)
        self.assertEqual(matching_services.exclusion_reason(self.trip, passenger_request), "not_enough_seats")

    def test_party_that_fits_the_free_seats_is_kept(self) -> None:
        passenger_request = self.create_request(passengers=3)
        self.assertEqual(matching_services.exclusion_reason(self.trip, passenger_request), "")

    def test_party_equal_to_the_free_seats_is_kept(self) -> None:
        """Exact fit: ``available_seats >= passenger_count`` holds."""
        passenger_request = self.create_request(passengers=self.trip.available_seats)
        self.assertGreaterEqual(self.trip.available_seats, passenger_request.passenger_count)
        self.assertEqual(matching_services.exclusion_reason(self.trip, passenger_request), "")
        self.assertEqual(
            [candidate.pk for candidate in matching_services.get_candidate_requests(self.trip)],
            [passenger_request.pk],
        )

    def test_four_seats_fit_a_party_of_two(self) -> None:
        roomy_driver = self.data.create_driver(vehicle_seats=5)
        roomy = self.data.create_trip(
            roomy_driver,
            from_location=self.location("Keng chiqish", TRIP_PICKUP),
            to_location=self.location("Keng tushish", TRIP_DROPOFF),
            seats=4,
        )
        passenger_request = self.create_request(passengers=2, trip=roomy)
        self.assertEqual(roomy.available_seats, 4)
        self.assertGreaterEqual(roomy.available_seats, passenger_request.passenger_count)
        self.assertEqual(matching_services.exclusion_reason(roomy, passenger_request), "")
        self.assertEqual(
            [candidate.pk for candidate in matching_services.get_candidate_requests(roomy)],
            [passenger_request.pk],
        )

    def test_two_seats_never_fit_a_party_of_three(self) -> None:
        narrow = self.create_trip(
            pickup=Decimal("41.313081"),
            dropoff=Decimal("41.413081"),
            seats=2,
        )
        passenger_request = self.create_request(passengers=3, trip=narrow)
        self.assertEqual(narrow.available_seats, 2)
        self.assertEqual(matching_services.exclusion_reason(narrow, passenger_request), "not_enough_seats")
        self.assertEqual(matching_services.get_candidate_requests(narrow), [])


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


class MultipleTripTests(SuitableRequestsTestBase):
    """One driver, several trips: every trip that has a match comes back.

    The scenario is the one the requirement spells out - ``Trip A -> 2 matches,
    Trip B -> 0 matches, Trip C -> 3 matches`` - and the answer must group them
    per trip instead of silently answering for whichever trip happens to be
    first in the list.
    """

    def setUp(self) -> None:
        super().setUp()
        # Trip A is the fixture's own trip (departs in 2 hours). Trips B and C
        # sit on their own stretches of the same meridian, hours apart, so no
        # passenger of one trip can ever serve another.
        self.trip_b = self.create_trip(
            pickup=Decimal("41.331081"),
            dropoff=Decimal("41.431081"),
            departure_in=timedelta(hours=6),
        )
        self.trip_c = self.create_trip(
            pickup=Decimal("41.351081"),
            dropoff=Decimal("41.451081"),
            departure_in=timedelta(hours=10),
        )
        self.a1 = self.create_request(name="A1")
        self.a2 = self.create_request(name="A2", pickup=OFFSET_PICKUP, dropoff=OFFSET_DROPOFF)
        self.c1 = self.create_request(name="C1", trip=self.trip_c)
        self.c2 = self.create_request(name="C2", trip=self.trip_c, pickup=OFFSET_PICKUP, dropoff=OFFSET_DROPOFF)
        self.c3 = self.create_request(name="C3", trip=self.trip_c, passengers=2)

    def groups(self):
        return {
            group.trip.pk: group
            for group in matching_services.get_suitable_requests_by_trip(self.driver.profile)
        }

    def test_every_trip_with_a_match_is_present(self) -> None:
        grouped = self.groups()
        self.assertEqual(sorted(grouped), sorted([self.trip.pk, self.trip_c.pk]))

    def test_a_trip_without_a_match_is_left_out(self) -> None:
        self.assertNotIn(self.trip_b.pk, self.groups())

    def test_each_group_carries_only_its_own_passengers(self) -> None:
        grouped = self.groups()
        self.assertEqual(
            sorted(match.request_id for match in grouped[self.trip.pk].results),
            sorted([self.a1.pk, self.a2.pk]),
        )
        self.assertEqual(
            sorted(match.request_id for match in grouped[self.trip_c.pk].results),
            sorted([self.c1.pk, self.c2.pk, self.c3.pk]),
        )

    def test_the_groups_keep_the_backend_ranking(self) -> None:
        for group in self.groups().values():
            self.assertEqual([match.rank for match in group.results], list(range(1, len(group.results) + 1)))
            for match in group.results:
                self.assertEqual(match.trip_id, group.trip.pk)

    def test_the_group_order_is_stable_across_two_reads(self) -> None:
        first = [group.trip.pk for group in matching_services.get_suitable_requests_by_trip(self.driver.profile)]
        second = [group.trip.pk for group in matching_services.get_suitable_requests_by_trip(self.driver.profile)]
        self.assertEqual(first, second)

    def test_another_driver_sees_only_their_own_trips(self) -> None:
        stranger = self.data.create_driver()
        self.assertEqual(matching_services.get_suitable_requests_by_trip(stranger.profile), [])


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

    def test_the_row_says_which_rule_judged_the_route(self) -> None:
        self.create_request(pickup=OFFSET_PICKUP, dropoff=OFFSET_DROPOFF)
        [row] = self.feed().json()["results"]
        self.assertEqual(row["route_match_basis"], matching_services.ROUTE_BASIS_COORDINATES)


class DriverSuitableRequestsApiTests(SuitableRequestsTestBase):
    """``GET /api/v1/matching/trips/suitable-requests/`` - the whole screen.

    One call, no ``trip_id`` in the path, nothing chosen by the client: this is
    the endpoint that lets the "suitable passengers" screen open on an already
    filled answer.
    """

    def setUp(self) -> None:
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(self.driver.user)

    def screen(self):
        return self.client.get("/api/v1/matching/trips/suitable-requests/")

    def test_a_driver_without_a_match_gets_an_empty_but_valid_answer(self) -> None:
        response = self.screen()
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["trips"], [])
        self.assertEqual(Decimal(payload["max_score"]), matching_services.MAX_SCORE)

    def test_the_screen_is_already_filled_without_any_selection(self) -> None:
        passenger_request = self.create_request()
        payload = self.screen().json()
        [group] = payload["trips"]

        self.assertEqual(group["trip_id"], self.trip.pk)
        self.assertEqual(group["available_seats"], self.trip.available_seats)
        self.assertEqual(group["total_seats"], self.trip.total_seats)
        self.assertTrue(group["route"])
        self.assertTrue(group["departure_time"])
        self.assertEqual([row["request_id"] for row in group["results"]], [passenger_request.pk])

    def test_every_group_carries_the_measurements_the_screen_shows(self) -> None:
        self.create_request(pickup=OFFSET_PICKUP, dropoff=OFFSET_DROPOFF)
        [group] = self.screen().json()["trips"]
        [row] = group["results"]

        for field in (
            "pickup_offset_km",
            "dropoff_offset_km",
            "distance_difference_km",
            "route_deviation_km",
            "time_difference_minutes",
            "route_compatible",
            "route_status",
            "route_match_basis",
            "required_seats",
            "available_seats",
            "pickup_location",
            "dropoff_location",
            "departure_from",
            "departure_until",
            "passenger_name",
            "score",
            "rank",
        ):
            self.assertIn(field, row)
        self.assertIsNotNone(row["pickup_offset_km"])
        self.assertIsNotNone(row["dropoff_offset_km"])
        self.assertLessEqual(row["distance_difference_km"], conf.MATCHING_MAX_ROUTE_DISTANCE_KM)

    def test_several_trips_are_grouped_and_the_empty_one_is_dropped(self) -> None:
        trip_b = self.create_trip(
            pickup=Decimal("41.331081"), dropoff=Decimal("41.431081"), departure_in=timedelta(hours=6)
        )
        trip_c = self.create_trip(
            pickup=Decimal("41.351081"), dropoff=Decimal("41.451081"), departure_in=timedelta(hours=10)
        )
        first = self.create_request(name="A1")
        self.create_request(name="A2", pickup=OFFSET_PICKUP, dropoff=OFFSET_DROPOFF)
        c1 = self.create_request(name="C1", trip=trip_c)
        c2 = self.create_request(name="C2", trip=trip_c, pickup=OFFSET_PICKUP, dropoff=OFFSET_DROPOFF)
        c3 = self.create_request(name="C3", trip=trip_c, passengers=2)

        payload = self.screen().json()
        groups = {group["trip_id"]: group for group in payload["trips"]}

        self.assertNotIn(trip_b.pk, groups)
        self.assertEqual(
            [row["request_id"] for row in groups[self.trip.pk]["results"]],
            [first.pk, groups[self.trip.pk]["results"][1]["request_id"]],
        )
        self.assertEqual(
            [row["request_id"] for row in groups[trip_c.pk]["results"]], [c1.pk, c2.pk, c3.pk]
        )

    def test_the_backend_ranking_is_the_order_the_api_returns(self) -> None:
        first = self.create_request(name="Birinchi")
        second = self.create_request(name="Ikkinchi", pickup=OFFSET_PICKUP, dropoff=OFFSET_DROPOFF)

        [group] = self.screen().json()["trips"]
        self.assertEqual([row["request_id"] for row in group["results"]], [first.pk, second.pk])
        self.assertEqual([row["rank"] for row in group["results"]], [1, 2])

    def test_passengers_that_do_not_fit_never_reach_the_screen(self) -> None:
        self.create_request(pickup=FAR_PICKUP, dropoff=FAR_DROPOFF, name="Uzoq")
        self.create_request(pickup=REVERSE_PICKUP, dropoff=REVERSE_DROPOFF, name="Teskari")
        self.create_request(passengers=4, name="To'la")
        self.create_request(
            departure_from=self.trip.departure_time - timedelta(hours=6),
            departure_until=self.trip.departure_time - timedelta(minutes=61),
            name="Kech",
        )
        self.assertEqual(self.screen().json()["trips"], [])

    def test_reading_the_screen_writes_nothing(self) -> None:
        self.create_request()
        rows_before = TripMatch.objects.count()
        self.assertEqual(self.screen().status_code, 200)
        self.assertEqual(TripMatch.objects.count(), rows_before)

    def test_another_driver_sees_only_their_own_empty_answer(self) -> None:
        self.create_request()
        self.client.force_authenticate(self.data.create_driver().user)
        self.assertEqual(self.screen().json()["trips"], [])

    def test_a_user_without_a_driver_profile_is_refused(self) -> None:
        self.client.force_authenticate(self.data.create_passenger())
        self.assertEqual(self.screen().status_code, 403)

    def test_anonymous_cannot_read_the_screen(self) -> None:
        self.client.force_authenticate(None)
        self.assertEqual(self.screen().status_code, 401)
