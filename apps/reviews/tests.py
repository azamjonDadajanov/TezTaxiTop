"""Tests for the reviews app.

Reviews are the reputation source of the marketplace, so the suite focuses on
the four invariants: only completed orders can be reviewed, only participants
may review each other, one review per direction, and the cached driver rating
is always a deterministic function of the review rows.
"""

from __future__ import annotations

from decimal import Decimal

from django.test import TestCase

from apps.core.exceptions import DuplicateReview, InvalidReview, ReviewNotAllowed
from apps.core.testing import TaxiTestData
from apps.orders import services as order_services
from apps.reviews import services as review_services
from apps.reviews.models import Review
from apps.users.constants import UserRole


class ReviewTestBase(TestCase):
    def setUp(self) -> None:
        self.data = TaxiTestData()
        self.driver = self.data.create_driver()
        self.passenger = self.data.create_passenger()
        self.trip = self.data.create_trip(self.driver)
        self.order = self.data.create_order(self.trip, self.passenger)
        order_services.accept_order(self.order)
        order_services.start_order(self.order)
        self.order = order_services.complete_order(self.order)


class ReviewCreationTests(ReviewTestBase):
    def test_passenger_reviews_the_driver(self) -> None:
        review = review_services.create_review(
            order=self.order,
            reviewer=self.passenger,
            reviewed_user=self.driver.user,
            rating=5,
            comment="Juda yaxshi haydovchi",
        )
        self.assertEqual(review.rating, 5)
        self.assertEqual(review.is_for_driver, True)
        self.assertEqual(review.order, self.order)

    def test_driver_reviews_the_passenger(self) -> None:
        review = review_services.create_review(
            order=self.order,
            reviewer=self.driver.user,
            reviewed_user=self.passenger,
            rating=4,
        )
        self.assertEqual(review.is_for_driver, False)

    def test_both_directions_are_allowed_at_the_same_time(self) -> None:
        review_services.create_review(
            order=self.order,
            reviewer=self.passenger,
            reviewed_user=self.driver.user,
            rating=5,
        )
        review_services.create_review(
            order=self.order,
            reviewer=self.driver.user,
            reviewed_user=self.passenger,
            rating=3,
        )
        self.assertEqual(Review.objects.filter(order=self.order).count(), 2)

    def test_duplicate_review_in_the_same_direction_is_rejected(self) -> None:
        review_services.create_review(
            order=self.order,
            reviewer=self.passenger,
            reviewed_user=self.driver.user,
            rating=5,
        )
        with self.assertRaises(DuplicateReview):
            review_services.create_review(
                order=self.order,
                reviewer=self.passenger,
                reviewed_user=self.driver.user,
                rating=1,
            )

    def test_cannot_review_yourself(self) -> None:
        with self.assertRaises(InvalidReview):
            review_services.create_review(
                order=self.order,
                reviewer=self.passenger,
                reviewed_user=self.passenger,
                rating=5,
            )

    def test_stranger_cannot_review(self) -> None:
        stranger = self.data.create_passenger()
        with self.assertRaises(ReviewNotAllowed):
            review_services.create_review(
                order=self.order,
                reviewer=stranger,
                reviewed_user=self.driver.user,
                rating=5,
            )

    def test_rating_bounds_are_enforced(self) -> None:
        for rating in (0, 6):
            with self.assertRaises(InvalidReview):
                review_services.create_review(
                    order=self.order,
                    reviewer=self.passenger,
                    reviewed_user=self.driver.user,
                    rating=rating,
                )

    def test_unfinished_order_cannot_be_reviewed(self) -> None:
        order = self.data.create_order(self.trip, self.passenger)
        with self.assertRaises(ReviewNotAllowed):
            review_services.create_review(
                order=order,
                reviewer=self.passenger,
                reviewed_user=self.driver.user,
                rating=5,
            )

    def test_cancelled_order_cannot_be_reviewed(self) -> None:
        order = self.data.create_order(self.trip, self.passenger)
        order_services.accept_order(order)
        order_services.cancel_order_by_passenger(order)
        with self.assertRaises(ReviewNotAllowed):
            review_services.create_review(
                order=order,
                reviewer=self.passenger,
                reviewed_user=self.driver.user,
                rating=5,
            )

    def test_review_can_be_edited_by_its_author(self) -> None:
        review = review_services.create_review(
            order=self.order,
            reviewer=self.passenger,
            reviewed_user=self.driver.user,
            rating=5,
        )
        updated = review_services.update_review(review, rating=3, comment="uzartdim")
        self.assertEqual(updated.rating, 3)
        self.driver.profile.refresh_from_db()
        self.assertEqual(self.driver.profile.rating, Decimal("3.00"))

    def test_review_can_be_deleted(self) -> None:
        review = review_services.create_review(
            order=self.order,
            reviewer=self.passenger,
            reviewed_user=self.driver.user,
            rating=2,
        )
        review_services.delete_review(review)
        self.assertEqual(Review.objects.count(), 0)
        self.driver.profile.refresh_from_db()
        self.assertEqual(self.driver.profile.rating, Decimal("5.00"))
        self.assertEqual(self.driver.profile.rating_count, 0)


class DriverRatingTests(ReviewTestBase):
    def test_rating_is_the_average_of_driver_reviews(self) -> None:
        for rating in (5, 4, 3):
            passenger = self.data.create_passenger()
            trip = self.data.create_trip(self.driver)
            order = self.data.create_order(trip, passenger)
            order_services.accept_order(order)
            order_services.start_order(order)
            order = order_services.complete_order(order)
            review_services.create_review(
                order=order,
                reviewer=passenger,
                reviewed_user=self.driver.user,
                rating=rating,
            )

        self.driver.profile.refresh_from_db()
        self.assertEqual(self.driver.profile.rating, Decimal("4.00"))
        self.assertEqual(self.driver.profile.rating_count, 3)

    def test_recalculation_is_deterministic(self) -> None:
        review = review_services.create_review(
            order=self.order,
            reviewer=self.passenger,
            reviewed_user=self.driver.user,
            rating=4,
        )
        review_services.update_review(review, rating=2)
        value = review_services.recalculate_driver_rating(self.driver.user)
        self.driver.profile.refresh_from_db()
        self.assertEqual(value, self.driver.profile.rating)
        self.assertEqual(value, Decimal("2.00"))

    def test_passenger_reviews_do_not_touch_the_driver_rating(self) -> None:
        review_services.create_review(
            order=self.order,
            reviewer=self.driver.user,
            reviewed_user=self.passenger,
            rating=1,
        )
        self.driver.profile.refresh_from_db()
        self.assertEqual(self.driver.profile.rating, Decimal("5.00"))
        self.assertEqual(self.driver.profile.rating_count, 0)

    def test_database_constraint_blocks_duplicate_rows(self) -> None:
        from django.db import IntegrityError, transaction

        review_services.create_review(
            order=self.order,
            reviewer=self.passenger,
            reviewed_user=self.driver.user,
            rating=5,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Review.objects.create(
                    order=self.order,
                    reviewer=self.passenger,
                    reviewed_user=self.driver.user,
                    rating=4,
                )

    def test_database_constraint_blocks_self_review(self) -> None:
        from django.db import IntegrityError, transaction

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Review.objects.create(
                    order=self.order,
                    reviewer=self.passenger,
                    reviewed_user=self.passenger,
                    rating=5,
                )

    def test_recalculation_ignores_blocked_users(self) -> None:
        """Blocking a user must not silently rewrite the reputation cache."""
        from apps.users.models import User

        review_services.create_review(
            order=self.order,
            reviewer=self.passenger,
            reviewed_user=self.driver.user,
            rating=1,
        )
        User.objects.filter(pk=self.passenger.pk).update(is_blocked=True)
        self.driver.profile.refresh_from_db()
        self.assertEqual(self.driver.profile.rating, Decimal("1.00"))


class ReviewRoleTests(ReviewTestBase):
    def test_only_drivers_accumulate_a_public_rating(self) -> None:
        review_services.create_review(
            order=self.order,
            reviewer=self.driver.user,
            reviewed_user=self.passenger,
            rating=5,
        )
        self.assertFalse(hasattr(self.passenger, "driver_profile"))
        self.assertEqual(self.passenger.role, UserRole.PASSENGER)
