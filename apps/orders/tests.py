"""Tests for the orders app - the most safety critical module of the project.

The suite is organised around the guarantees the domain promises:

* the price is snapshotted and never follows the trip;
* a pending order does **not** hold seats, accepting one does;
* the state machine rejects every illegal transition;
* cancellation returns the seats exactly once;
* two drivers competing for the last seat can never overbook (concurrency).
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.db.models import Sum
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from apps.core.exceptions import (
    BusinessError,
    BusinessValidationError,    DriverCannotBookOwnTrip,
    InsufficientSeats,
    InvalidOrderTransition,
    TripNotActive,
    UnauthorizedOrderAccess,
    UserIsBlocked,
)
from apps.core.testing import TaxiTestData
from apps.orders import services as order_services
from apps.orders.models import Order, OrderStatus
from apps.rides.models import DriverTripStatus
from apps.users.constants import UserRole
from apps.users.models import User


class OrderTestBase(TestCase):
    def setUp(self) -> None:
        self.data = TaxiTestData()
        self.driver = self.data.create_driver()
        self.passenger = self.data.create_passenger()
        self.trip = self.data.create_trip(self.driver, seats=3)


class OrderCreationTests(OrderTestBase):
    def test_order_starts_pending_and_snapshots_the_price(self) -> None:
        order = self.data.create_order(self.trip, self.passenger, seats=2)

        self.assertEqual(order.status, OrderStatus.PENDING)
        self.assertEqual(order.seats_booked, 2)
        self.assertEqual(order.price_per_seat, Decimal("20000.00"))
        self.assertEqual(order.total_amount, Decimal("40000.00"))

    def test_price_change_does_not_touch_existing_orders(self) -> None:
        order = self.data.create_order(self.trip, self.passenger)

        self.trip.price_per_seat = Decimal("99000.00")
        self.trip.save(update_fields=["price_per_seat"])

        order.refresh_from_db()
        self.assertEqual(order.price_per_seat, Decimal("20000.00"))
        self.assertEqual(order.total_amount, Decimal("20000.00"))

    def test_pending_order_does_not_reserve_seats(self) -> None:
        self.data.create_order(self.trip, self.passenger, seats=2)
        self.trip.refresh_from_db()
        self.assertEqual(self.trip.available_seats, 3)
        self.assertEqual(self.trip.status, DriverTripStatus.ACTIVE)

    def test_cannot_book_own_trip(self) -> None:
        with self.assertRaises(DriverCannotBookOwnTrip):
            self.data.create_order(self.trip, self.driver.user)

    def test_cannot_book_inactive_trip(self) -> None:
        from apps.rides import services as ride_services

        self.trip = ride_services.cancel_trip(self.trip, reason="test")
        with self.assertRaises(TripNotActive):
            self.data.create_order(self.trip, self.passenger)

    def test_cannot_book_more_seats_than_available(self) -> None:
        with self.assertRaises(InsufficientSeats):
            self.data.create_order(self.trip, self.passenger, seats=4)

    def test_cannot_book_more_seats_than_the_per_order_limit(self) -> None:
        with self.assertRaises(BusinessValidationError):
            self.data.create_order(self.trip, self.passenger, seats=9)

    def test_blocked_user_cannot_order(self) -> None:
        User.objects.filter(pk=self.passenger.pk).update(is_blocked=True)
        self.passenger.refresh_from_db()
        with self.assertRaises(UserIsBlocked):
            self.data.create_order(self.trip, self.passenger)

    def test_companion_can_be_attached(self) -> None:
        order = self.data.create_order(self.trip, self.passenger)
        order_services.add_order_passenger(
            order, first_name="Ali", phone_number="+998901112233"
        )
        self.assertEqual(order.passengers.count(), 1)


class OrderAcceptanceTests(OrderTestBase):
    def test_accept_reserves_seats_and_fills_trip(self) -> None:
        order = self.data.create_order(self.trip, self.passenger, seats=3)
        accepted = order_services.accept_order(order)

        self.trip.refresh_from_db()
        self.assertEqual(accepted.status, OrderStatus.ACCEPTED)
        self.assertIsNotNone(accepted.accepted_at)
        self.assertEqual(self.trip.available_seats, 0)
        self.assertEqual(self.trip.status, DriverTripStatus.FULL)

    def test_accept_notifies_the_passenger(self) -> None:
        from apps.notifications.models import Notification, NotificationType

        order = self.data.create_order(self.trip, self.passenger)
        order_services.accept_order(order)

        notification = Notification.objects.filter(
            user=self.passenger, type=NotificationType.ORDER_ACCEPTED
        ).first()
        self.assertIsNotNone(notification)
        self.assertFalse(notification.is_read)

    def test_cannot_accept_twice(self) -> None:
        order = self.data.create_order(self.trip, self.passenger)
        order_services.accept_order(order)
        with self.assertRaises(InvalidOrderTransition):
            order_services.accept_order(order)

    def test_accepting_oversubscribed_trip_fails(self) -> None:
        order = self.data.create_order(self.trip, self.passenger, seats=2)
        self.trip.refresh_from_db()
        # Somebody else took the seats behind our back.
        DriverTrip = self.trip.__class__
        DriverTrip.objects.filter(pk=self.trip.pk).update(available_seats=1)

        with self.assertRaises(InsufficientSeats):
            order_services.accept_order(order)


class OrderCancellationTests(OrderTestBase):
    def test_passenger_cancel_releases_seats(self) -> None:
        order = self.data.create_order(self.trip, self.passenger, seats=2)
        order_services.accept_order(order)
        self.trip.refresh_from_db()
        self.assertEqual(self.trip.available_seats, 1)

        order_services.cancel_order_by_passenger(order, reason="reja o'zgardi")

        self.trip.refresh_from_db()
        self.assertEqual(self.trip.available_seats, 3)
        self.assertEqual(self.trip.status, DriverTripStatus.ACTIVE)
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.CANCELLED_BY_PASSENGER)

    def test_cancel_pending_order_keeps_seats_untouched(self) -> None:
        order = self.data.create_order(self.trip, self.passenger, seats=2)
        order_services.cancel_order_by_passenger(order)
        self.trip.refresh_from_db()
        self.assertEqual(self.trip.available_seats, 3)

    def test_driver_cancel_releases_seats(self) -> None:
        order = self.data.create_order(self.trip, self.passenger, seats=2)
        order_services.accept_order(order)
        order_services.cancel_order_by_driver(order, reason="mashina buzildi")

        self.trip.refresh_from_db()
        self.assertEqual(self.trip.available_seats, 3)

    def test_cannot_cancel_in_progress(self) -> None:
        order = self.data.create_order(self.trip, self.passenger)
        order_services.accept_order(order)
        order_services.start_order(order)
        with self.assertRaises(InvalidOrderTransition):
            order_services.cancel_order_by_passenger(order)

    def test_rejected_order_never_held_seats(self) -> None:
        order = self.data.create_order(self.trip, self.passenger, seats=2)
        order_services.reject_order(order, reason="boshqa yo'lov")
        self.trip.refresh_from_db()
        self.assertEqual(self.trip.available_seats, 3)
        order.refresh_from_db()
        self.assertEqual(order.cancellation_reason, "boshqa yo'lov")


class OrderLifecycleTests(OrderTestBase):
    def test_full_lifecycle(self) -> None:
        order = self.data.create_order(self.trip, self.passenger)
        order_services.accept_order(order)
        order_services.mark_driver_arrived(order)
        order_services.start_order(order)
        completed = order_services.complete_order(order)

        self.assertEqual(completed.status, OrderStatus.COMPLETED)
        self.assertIsNotNone(completed.completed_at)
        self.assertTrue(completed.is_reviewable)

    def test_completed_order_cannot_be_cancelled(self) -> None:
        order = self.data.create_order(self.trip, self.passenger)
        order_services.accept_order(order)
        order_services.start_order(order)
        order_services.complete_order(order)
        with self.assertRaises(InvalidOrderTransition):
            order_services.cancel_order_by_passenger(order)

    def test_no_show_returns_seats(self) -> None:
        order = self.data.create_order(self.trip, self.passenger, seats=2)
        order_services.accept_order(order)
        order_services.mark_no_show(order, reason="kellmadi")

        self.trip.refresh_from_db()
        self.assertEqual(self.trip.available_seats, 3)
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.NO_SHOW)


class OrderAuthorisationTests(OrderTestBase):
    def test_participants_pass(self) -> None:
        order = self.data.create_order(self.trip, self.passenger)
        self.assertTrue(order.is_participant(self.passenger))
        self.assertTrue(order.is_participant(self.driver.user))

    def test_stranger_is_denied(self) -> None:
        order = self.data.create_order(self.trip, self.passenger)
        stranger = self.data.create_passenger()
        self.assertFalse(order.is_participant(stranger))
        with self.assertRaises(UnauthorizedOrderAccess):
            order_services.assert_order_participant(order, stranger)

    def test_anonymous_is_not_a_participant(self) -> None:
        order = self.data.create_order(self.trip, self.passenger)
        self.assertFalse(order.is_participant(None))

    def test_blocked_passenger_keeps_history(self) -> None:
        order = self.data.create_order(self.trip, self.passenger)
        User.objects.filter(pk=self.passenger.pk).update(is_blocked=True)
        self.assertEqual(Order.objects.filter(passenger=self.passenger).count(), 1)
        self.assertIsNotNone(order.pk)


class SeatAccountingTests(OrderTestBase):
    def test_cancelled_order_cannot_release_seats_twice(self) -> None:
        order = self.data.create_order(self.trip, self.passenger, seats=3)
        order_services.accept_order(order)
        order_services.cancel_order_by_passenger(order)
        self.trip.refresh_from_db()
        self.assertEqual(self.trip.available_seats, 3)

        # The seat release is guarded by the state machine: a second
        # cancellation must not credit the trip with free seats.
        with self.assertRaises(InvalidOrderTransition):
            order_services.cancel_order_by_passenger(order)
        self.trip.refresh_from_db()
        self.assertEqual(self.trip.available_seats, 3)

    def test_trip_goes_back_to_active_when_seats_are_released(self) -> None:
        order = self.data.create_order(self.trip, self.passenger, seats=3)
        order_services.accept_order(order)
        order_services.cancel_order_by_passenger(order)
        self.trip.refresh_from_db()
        self.assertEqual(self.trip.status, DriverTripStatus.ACTIVE)
        self.assertEqual(self.trip.available_seats, 3)


class OrderConcurrencyTests(TransactionTestCase):
    """Real row locking, real threads, real database.

    ``TransactionTestCase`` is required: ``TestCase`` wraps each test in a
    transaction that the worker threads could never see.
    """

    reset_sequences = True

    def test_two_orders_cannot_take_the_same_last_seat(self) -> None:
        from concurrent.futures import ThreadPoolExecutor

        from django.db import OperationalError, connection

        data = TaxiTestData()
        driver = data.create_driver()
        first = data.create_passenger()
        second = data.create_passenger()
        trip = data.create_trip(driver, seats=1)

        order_one = data.create_order(trip, first, seats=1)
        order_two = data.create_order(trip, second, seats=1)

        def accept(order_id: int) -> str:
            from apps.orders.services import get_required_order

            order = get_required_order(order_id)
            try:
                order_services.accept_order(order)
            except BusinessError:
                return "rejected"
            except OperationalError:
                # SQLite serialises writers with a database-wide lock instead of
                # a row lock, so a thread can lose the race for the *write* and
                # never reach a decision. That is an artefact of the test
                # database, not of the production backend.
                return "busy"
            return "accepted"

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(accept, [order_one.pk, order_two.pk]))

        trip.refresh_from_db()
        accepted = Order.objects.filter(trip=trip, status=OrderStatus.ACCEPTED)
        decided = [status for status in results if status != "busy"]

        # The safety property holds on every backend: a seat is never sold twice.
        self.assertLessEqual(accepted.count(), 1, "Ikkalasi ham yagona o'rinni olib bo'lmaydi.")
        self.assertGreaterEqual(trip.available_seats, 0, "Joylar manfiy bo'lmasligi kerak.")
        if accepted.exists():
            self.assertEqual(
                trip.available_seats,
                trip.total_seats - accepted.aggregate(total=Sum("seats_booked"))["total"],
                "Qolgan joylar band qilingan joylarga teng bo'lishi kerak.",
            )
        if connection.features.has_select_for_update:
            # Only a backend with real row locks guarantees a single winner.
            self.assertEqual(sorted(decided), ["accepted", "rejected"])
            self.assertEqual(trip.available_seats, 0)


class OrderExpiryTests(OrderTestBase):
    def test_expired_trip_cannot_receive_orders(self) -> None:
        from apps.rides import services as ride_services

        DriverTrip = self.trip.__class__
        DriverTrip.objects.filter(pk=self.trip.pk).update(
            departure_time=timezone.now() - timedelta(hours=2)
        )
        ride_services.expire_trips()
        self.trip.refresh_from_db()
        self.assertEqual(self.trip.status, DriverTripStatus.EXPIRED)
        with self.assertRaises(TripNotActive):
            self.data.create_order(self.trip, self.passenger)
