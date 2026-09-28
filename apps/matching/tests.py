"""Tests for the deterministic matching engine.

The engine is the part of the product a user cannot audit from the UI, so the
suite pins down three things: the hard filters, the weight arithmetic, and the
determinism of the ranking (same input -> same order, every time).
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ImproperlyConfigured
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from apps.core.exceptions import ResourceNotFound
from apps.core.testing import TaxiTestData
from apps.matching import services as matching_services
from apps.matching.models import MatchReason, TripMatch
from apps.orders import services as order_services
from apps.reviews import services as review_services
from apps.rides import services as ride_services
from apps.users.services import verify_driver_profile


class MatchingTestBase(TestCase):
    def setUp(self) -> None:
        self.data = TaxiTestData()
        self.driver = self.data.create_driver()
        self.passenger = self.data.create_passenger()
        self.from_location = self.data.get_or_create_location("Qorasuv MFY")
        self.to_location = self.data.get_or_create_location("Sergeli MFY")
        self.request = self.create_request()

    def create_request(
        self,
        *,
        passenger=None,
        departure_in: timedelta = timedelta(hours=2),
        window: timedelta = timedelta(hours=4),
        budget: str | None = "30000.00",
    ):
        start = timezone.now() + departure_in
        return ride_services.create_passenger_request(
            passenger=passenger or self.passenger,
            from_location=self.from_location,
            to_location=self.to_location,
            passenger_count=1,
            max_price_per_seat=Decimal(budget) if budget else None,
            departure_from=start,
            departure_until=start + window,
        )

    def create_trip(self, *, driver=None, price="20000.00", departure_in=timedelta(hours=2), **kwargs):
        return self.data.create_trip(
            driver or self.driver,
            price=price,
            departure_in=departure_in,
            from_location=self.from_location,
            to_location=self.to_location,
            **kwargs,
        )


class WeightTests(TestCase):
    def test_weights_add_up_to_one_hundred(self) -> None:
        weights = [
            matching_services.WEIGHT_TIME,
            matching_services.WEIGHT_PRICE,
            matching_services.WEIGHT_RATING,
            matching_services.WEIGHT_SUBSCRIPTION,
            matching_services.WEIGHT_VEHICLE,
        ]
        self.assertEqual(sum(weights), Decimal("100"))
        self.assertEqual(matching_services.MAX_SCORE, Decimal("100"))

    def test_weights_are_the_agreed_ones(self) -> None:
        self.assertEqual(matching_services.WEIGHT_TIME, Decimal("30"))
        self.assertEqual(matching_services.WEIGHT_PRICE, Decimal("30"))
        self.assertEqual(matching_services.WEIGHT_RATING, Decimal("20"))
        self.assertEqual(matching_services.WEIGHT_SUBSCRIPTION, Decimal("10"))
        self.assertEqual(matching_services.WEIGHT_VEHICLE, Decimal("10"))


class ScoringTests(MatchingTestBase):
    def test_total_is_the_sum_of_the_components(self) -> None:
        trip = self.create_trip()
        score = matching_services.score_trip_for_request(trip, self.request)
        self.assertTrue(score.is_match)
        self.assertEqual(
            score.total,
            score.time_score
            + score.price_score
            + score.rating_score
            + score.subscription_score
            + score.vehicle_score,
        )
        self.assertLessEqual(score.total, matching_services.MAX_SCORE)
        self.assertGreaterEqual(score.total, Decimal("0"))

    def test_score_is_deterministic(self) -> None:
        trip = self.create_trip()
        first = matching_services.score_trip_for_request(trip, self.request)
        second = matching_services.score_trip_for_request(trip, self.request)
        self.assertEqual(first.total, second.total)
        self.assertEqual(first.as_components(), second.as_components())

    def test_closer_departure_scores_higher(self) -> None:
        # The window starts 2 hours from now, so both trips sit inside it.
        near = self.create_trip(departure_in=timedelta(hours=2, minutes=30))
        far = self.create_trip(departure_in=timedelta(hours=5))
        near_score = matching_services.score_trip_for_request(near, self.request)
        far_score = matching_services.score_trip_for_request(far, self.request)
        self.assertGreater(near_score.time_score, far_score.time_score)
        self.assertEqual(near_score.minutes_difference, 30)
        self.assertEqual(far_score.minutes_difference, 180)

    def test_cheaper_trip_scores_higher(self) -> None:
        cheap = self.create_trip(price="10000.00")
        pricey = self.create_trip(price="28000.00")
        self.assertGreater(
            matching_services.score_trip_for_request(cheap, self.request).price_score,
            matching_services.score_trip_for_request(pricey, self.request).price_score,
        )

    def test_higher_rating_scores_higher(self) -> None:
        good = self.data.create_driver()
        poor = self.data.create_driver()
        for rating, driver in ((5, good), (1, poor)):
            order = self.data.create_order(self.create_trip(driver=driver), self.data.create_passenger())
            order_services.accept_order(order)
            order_services.start_order(order)
            order = order_services.complete_order(order)
            review_services.create_review(
                order=order, reviewer=order.passenger, reviewed_user=driver.user, rating=rating
            )
        good_score = matching_services.score_trip_for_request(self.create_trip(driver=good), self.request)
        poor_score = matching_services.score_trip_for_request(self.create_trip(driver=poor), self.request)
        self.assertGreater(good_score.rating_score, poor_score.rating_score)
        self.assertEqual(good_score.rating_score, matching_services.WEIGHT_RATING)
        self.assertEqual(poor_score.rating_score, Decimal("0.00"))

    def test_roomier_vehicle_scores_higher(self) -> None:
        """Only the comfort term can vary: unverified cars cannot be published."""
        small = self.data.create_driver()
        Vehicle = small.vehicle.__class__
        Vehicle.objects.filter(pk=small.vehicle.pk).update(seats_count=3)
        small.vehicle.refresh_from_db()
        roomy = self.data.create_driver()

        small_score = matching_services.score_trip_for_request(
            self.create_trip(driver=small, seats=1), self.request
        )
        roomy_score = matching_services.score_trip_for_request(
            self.create_trip(driver=roomy), self.request
        )
        self.assertGreater(roomy_score.vehicle_score, small_score.vehicle_score)

    def test_explanation_is_populated_in_uzbek(self) -> None:
        score = matching_services.score_trip_for_request(self.create_trip(), self.request)
        self.assertTrue(score.reasons)
        for reason in score.reasons:
            self.assertIsInstance(reason, str)
            self.assertTrue(reason.strip())


class HardFilterTests(MatchingTestBase):
    def test_full_trip_is_excluded(self) -> None:
        trip = self.create_trip(seats=1)
        # A *different* passenger fills the only seat, so the reason is the
        # trip state and not "already ordered".
        order = self.data.create_order(trip, self.data.create_passenger())
        order_services.accept_order(order)
        trip.refresh_from_db()
        self.assertEqual(
            matching_services.exclusion_reason(trip, self.request), "trip_not_bookable"
        )
        self.assertEqual(matching_services.get_candidate_trips(self.request), [])

    def test_not_enough_seats_for_the_party_is_excluded(self) -> None:
        trip = self.create_trip(seats=2)
        order = self.data.create_order(trip, self.data.create_passenger(), seats=1)
        order_services.accept_order(order)
        trip.refresh_from_db()
        self.assertEqual(trip.available_seats, 1)
        group_request = self.create_request()
        PassengerRequest = group_request.__class__
        PassengerRequest.objects.filter(pk=group_request.pk).update(passenger_count=3)
        group_request.refresh_from_db()
        self.assertEqual(
            matching_services.exclusion_reason(trip, group_request), "not_enough_seats"
        )

    def test_cancelled_trip_is_excluded(self) -> None:
        trip = self.create_trip()
        trip = ride_services.cancel_trip(trip)
        self.assertEqual(
            matching_services.exclusion_reason(trip, self.request), "trip_not_bookable"
        )

    def test_trip_outside_the_window_is_excluded(self) -> None:
        trip = self.create_trip(departure_in=timedelta(hours=10))
        self.assertEqual(
            matching_services.exclusion_reason(trip, self.request), "outside_departure_window"
        )

    def test_trip_above_the_budget_is_excluded(self) -> None:
        trip = self.create_trip(price="90000.00")
        self.assertEqual(
            matching_services.exclusion_reason(trip, self.request), "above_budget"
        )

    def test_unverified_driver_is_excluded(self) -> None:
        driver = self.data.create_driver(verified=False)
        trip = self.create_trip(driver=driver)
        self.assertEqual(
            matching_services.exclusion_reason(trip, self.request), "driver_not_verified"
        )
        verify_driver_profile(driver.profile, verified=True)
        trip.refresh_from_db()
        self.assertEqual(matching_services.exclusion_reason(trip, self.request), "")

    def test_driver_without_subscription_is_excluded(self) -> None:
        from apps.subscriptions import services as subscription_services

        driver = self.data.create_driver()
        trip = self.create_trip(driver=driver)
        self.assertEqual(matching_services.exclusion_reason(trip, self.request), "")

        subscription_services.cancel_subscription(driver.subscription)
        trip.refresh_from_db()
        self.assertEqual(
            matching_services.exclusion_reason(trip, self.request), "no_active_subscription"
        )

    def test_driver_who_never_had_a_subscription_is_excluded(self) -> None:
        driver = self.data.create_driver(with_subscription=False)
        trip = self.create_trip(driver=driver)
        self.assertEqual(
            matching_services.exclusion_reason(trip, self.request), "no_active_subscription"
        )

    def test_passenger_cannot_match_their_own_trip(self) -> None:
        trip = self.data.create_trip(
            self.driver,
            from_location=self.from_location,
            to_location=self.to_location,
            departure_in=timedelta(hours=3),
        )
        own_request = self.create_request(passenger=self.driver.user)
        self.assertEqual(matching_services.exclusion_reason(trip, own_request), "own_trip")

    def test_passenger_who_already_ordered_is_excluded(self) -> None:
        trip = self.create_trip()
        order = self.data.create_order(trip, self.passenger)
        order_services.accept_order(order)
        trip.refresh_from_db()
        self.assertEqual(
            matching_services.exclusion_reason(trip, self.request), "already_ordered"
        )

    def test_different_route_is_not_a_candidate(self) -> None:
        self.create_trip()
        elsewhere = self.create_request()
        elsewhere.from_location = self.data.get_or_create_location("Buxoro MFY")
        elsewhere.to_location = self.data.get_or_create_location("Andijon MFY")
        elsewhere.save(update_fields=["from_location", "to_location"])
        self.assertEqual(matching_services.get_candidate_trips(elsewhere), [])
        self.assertEqual(len(matching_services.get_candidate_trips(self.request)), 1)

    def test_excluded_pair_scores_zero(self) -> None:
        trip = self.create_trip(price="90000.00")
        score = matching_services.score_trip_for_request(trip, self.request)
        self.assertFalse(score.is_match)
        self.assertEqual(score.total, Decimal("0.00"))


class RankingTests(MatchingTestBase):
    def test_ranking_is_sorted_by_total_score(self) -> None:
        self.create_trip(price="25000.00", departure_in=timedelta(hours=4))
        best = self.create_trip(price="12000.00", departure_in=timedelta(hours=2, minutes=30))
        ranked = matching_services.rank_trips_for_request(self.request)
        self.assertEqual(ranked[0][0].pk, best.pk)
        scores = [score.total for _, score in ranked]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_ranking_is_stable_for_equal_scores(self) -> None:
        first = self.create_trip()
        second = self.create_trip()
        first_order = matching_services.rank_trips_for_request(self.request)
        second_order = matching_services.rank_trips_for_request(self.request)
        self.assertEqual(
            [t.pk for t, _ in first_order], [t.pk for t, _ in second_order]
        )
        self.assertEqual(
            [t.pk for t, _ in first_order], sorted([first.pk, second.pk])
        )

    def test_price_can_outrank_departure(self) -> None:
        """In a tight window the 30 price points outweigh a small time gap."""
        narrow = self.create_request(window=timedelta(hours=1))
        expensive = self.create_trip(
            price="29000.00", departure_in=timedelta(hours=2, minutes=10)
        )
        cheap = self.create_trip(price="11000.00", departure_in=timedelta(hours=2, minutes=50))
        ranked = matching_services.rank_trips_for_request(narrow)
        self.assertEqual(len(ranked), 2)
        self.assertEqual(ranked[0][0].pk, cheap.pk)
        self.assertNotEqual(ranked[0][0].pk, expensive.pk)

    def test_equal_departure_is_broken_by_price_then_id(self) -> None:
        first = self.create_trip(price="10000.00")
        second = self.create_trip(price="10000.00")
        ranked = matching_services.rank_trips_for_request(self.request)
        self.assertEqual([t.pk for t, _ in ranked], [first.pk, second.pk])


class PersistedMatchTests(MatchingTestBase):
    def test_refresh_persists_components_and_ranks(self) -> None:
        self.create_trip()
        self.create_trip(price="15000.00")
        matches = matching_services.refresh_matches_for_request(self.request)
        self.assertEqual(len(matches), 2)
        self.assertEqual(TripMatch.objects.filter(request=self.request).count(), 2)
        self.assertEqual(sorted(m.rank for m in matches), [1, 2])
        for match in matches:
            self.assertEqual(
                match.score,
                match.time_score
                + match.price_score
                + match.rating_score
                + match.subscription_score
                + match.vehicle_score,
            )
            self.assertEqual(match.reason, MatchReason.NEW_MATCH)

    def test_refresh_is_idempotent(self) -> None:
        self.create_trip()
        first = matching_services.refresh_matches_for_request(self.request)
        snapshot = list(
            TripMatch.objects.filter(request=self.request).values_list(
                "pk", "score", "rank", "reason"
            )
        )
        second = matching_services.refresh_matches_for_request(self.request)
        self.assertEqual(
            sorted(m.pk for m in first), sorted(m.pk for m in second)
        )
        self.assertEqual(
            snapshot,
            list(
                TripMatch.objects.filter(request=self.request).values_list(
                    "pk", "score", "rank", "reason"
                )
            ),
        )
        self.assertEqual(TripMatch.objects.filter(request=self.request).count(), 1)

    def test_score_change_is_recorded_as_rescore(self) -> None:
        trip = self.create_trip(price="20000.00")
        matching_services.refresh_matches_for_request(self.request)
        trip.price_per_seat = Decimal("10000.00")
        trip.save(update_fields=["price_per_seat"])
        matching_services.refresh_matches_for_request(self.request)
        self.assertEqual(
            TripMatch.objects.get(request=self.request, trip=trip).reason,
            MatchReason.RESCORE,
        )

    def test_ineligible_matches_are_removed(self) -> None:
        trip = self.create_trip()
        self.assertEqual(len(matching_services.refresh_matches_for_request(self.request)), 1)
        ride_services.cancel_trip(trip)
        self.assertEqual(matching_services.refresh_matches_for_request(self.request), [])
        self.assertEqual(TripMatch.objects.filter(request=self.request).count(), 0)

    def test_trip_refresh_returns_only_that_trip(self) -> None:
        other_request = self.create_request()
        self.create_trip()
        trip = self.create_trip()
        matches = matching_services.refresh_matches_for_trip(trip)
        self.assertTrue(matches)
        self.assertEqual({m.trip_id for m in matches}, {trip.pk})
        self.assertIn(
            self.request.pk, {m.request_id for m in matches}
        )
        self.assertIn(other_request.pk, {m.request_id for m in matches})

    def test_trip_refresh_drops_requests_that_no_longer_apply(self) -> None:
        trip = self.create_trip()
        matching_services.refresh_matches_for_trip(trip)
        self.assertEqual(TripMatch.objects.filter(trip=trip).count(), 1)
        trip = ride_services.complete_trip(trip)
        self.assertEqual(matching_services.refresh_matches_for_trip(trip), [])
        self.assertEqual(TripMatch.objects.filter(trip=trip).count(), 0)

    def test_trip_refresh_ranks_requests_consistently(self) -> None:
        urgent = self.create_request(
            departure_in=timedelta(hours=2, minutes=30), window=timedelta(hours=1)
        )
        relaxed = self.create_request(departure_in=timedelta(hours=2), window=timedelta(hours=5))
        trip = self.create_trip(departure_in=timedelta(hours=3))
        matching_services.refresh_matches_for_trip(trip)
        matches = list(TripMatch.objects.filter(trip=trip).order_by("rank"))
        # The trip departs 30 minutes after the urgent window opens, so that
        # request wins; the two requests whose window opened an hour earlier
        # score the same and are ordered by request id.
        self.assertEqual([m.request_id for m in matches], [urgent.pk, self.request.pk, relaxed.pk])
        self.assertEqual([m.rank for m in matches], [1, 2, 3])

    def test_repeated_trip_refresh_is_stable(self) -> None:
        """Re-running the refresh must not delete or duplicate other matches.

        Regression test: the stale-match cleanup once compared trip ids with
        match primary keys, which silently dropped the match of a *different*
        request on the second run.
        """
        twin = self.create_request()
        trip = self.create_trip(departure_in=timedelta(hours=3))
        for _ in range(3):
            matching_services.refresh_matches_for_trip(trip)
            self.assertEqual(
                [(m.request_id, m.rank) for m in TripMatch.objects.filter(trip=trip).order_by("request_id")],
                [(self.request.pk, 1), (twin.pk, 2)],
            )
        self.assertEqual(TripMatch.objects.count(), 2)

    def test_refresh_all_returns_a_summary(self) -> None:
        second_request = self.create_request()
        self.create_trip(departure_in=timedelta(hours=3))
        summary = matching_services.refresh_all_active_matches()
        self.assertEqual(summary["requests"], 2)
        self.assertEqual(summary["matches"], 2)
        self.assertEqual(TripMatch.objects.filter(request=second_request).count(), 1)

    def test_get_ranked_matches_uses_the_persisted_rows(self) -> None:
        self.create_trip()
        matching_services.refresh_matches_for_request(self.request)
        matches = matching_services.get_ranked_matches(self.request)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].rank, 1)

    def test_get_ranked_matches_falls_back_to_a_live_ranking(self) -> None:
        self.create_trip()
        matches = matching_services.get_ranked_matches(self.request)
        self.assertEqual(len(matches), 1)
        self.assertEqual(TripMatch.objects.count(), 1)


class MatchModelTests(MatchingTestBase):
    def test_duplicate_pair_is_rejected_by_the_database(self) -> None:
        trip = self.create_trip()
        matching_services.refresh_matches_for_request(self.request)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                TripMatch.objects.create(
                    request=self.request, trip=trip, score=Decimal("50")
                )

    def test_score_out_of_range_is_rejected(self) -> None:
        trip = self.create_trip()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                TripMatch.objects.create(
                    request=self.request, trip=trip, score=Decimal("150")
                )

    def test_components_are_exposed(self) -> None:
        trip = self.create_trip()
        match = matching_services.refresh_matches_for_request(self.request)[0]
        self.assertEqual(
            set(match.components),
            {"time", "price", "rating", "subscription", "vehicle"},
        )
        self.assertIsInstance(match.top_reasons(), list)
        self.assertLessEqual(len(match.top_reasons()), 2)

    def test_get_required_request_raises_for_unknown_id(self) -> None:
        with self.assertRaises(ResourceNotFound):
            matching_services.get_required_request(999999)

    def test_top_reasons_are_uzbek_labels(self) -> None:
        trip = self.create_trip()
        match = matching_services.refresh_matches_for_request(self.request)[0]
        allowed = {
            "Chuqish vaqti yaqin",
            "Narx qulay",
            "Yuqori reyting",
            "Faol obuna",
            "Ishonchli avtomobil",
        }
        self.assertTrue(set(match.top_reasons()).issubset(allowed))


class MatchingTaskTests(MatchingTestBase):
    def test_periodic_refresh_task(self) -> None:
        from apps.matching import tasks as matching_tasks

        self.create_trip()
        result = matching_tasks.refresh_all_matches_task()
        self.assertEqual(result["matches"], 1)

    def test_single_request_task(self) -> None:
        from apps.matching import tasks as matching_tasks

        self.create_trip()
        result = matching_tasks.refresh_request_matches_task(self.request.pk)
        self.assertEqual(result["matches"], 1)

    def test_single_trip_task(self) -> None:
        from apps.matching import tasks as matching_tasks

        trip = self.create_trip()
        result = matching_tasks.refresh_trip_matches_task(trip.pk)
        self.assertEqual(result["matches"], 1)
