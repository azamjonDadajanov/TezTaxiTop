"""Integration tests for booking API — both directions.

Covers Section 10 of the backend requirements:

* Passenger → Taxi booking: valid, duplicate, unknown trip, inactive trip,
  insufficient seats, blocked user, unauthenticated.
* Taxi → Passenger booking: valid, duplicate, unknown request, own request,
  non-driver, no active trip, incompatible route, incompatible time,
  insufficient capacity.
* Chat operations for both sides.
"""

from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.utils import timezone
from rest_framework import status

from apps.chat.services import get_or_create_conversation
from apps.core.testing import TaxiTestData
from apps.orders import services as order_services
from apps.orders.models import OrderStatus
from apps.rides import services as ride_services

User = get_user_model()


class BookingAPIBase(TestCase):
    """Shared fixtures for booking integration tests."""

    def setUp(self) -> None:
        self.data = TaxiTestData()
        self.driver_bundle = self.data.create_driver()
        self.driver_user = self.driver_bundle.user
        self.passenger = self.data.create_passenger()
        self.stranger = self.data.create_passenger()
        self.trip = self.data.create_trip(self.driver_bundle, seats=3)

    def _client_for(self, user: User) -> Client:
        client = Client()
        client.force_login(user)
        return client

    def _make_request(
        self,
        passenger: User,
        *,
        reverse_route: bool = False,
        passenger_count: int = 2,
        window_start: timedelta | None = None,
        window_end: timedelta | None = None,
    ):
        """A passenger request, optionally against the trip's reversed route."""
        origin, destination = self.trip.from_location, self.trip.to_location
        if reverse_route:
            origin, destination = destination, origin
        return ride_services.create_passenger_request(
            passenger=passenger,
            from_location=origin,
            to_location=destination,
            departure_from=timezone.now() + (window_start or timedelta(hours=1)),
            departure_until=timezone.now() + (window_end or timedelta(hours=3)),
            passenger_count=passenger_count,
        )


class PassengerBookingTests(BookingAPIBase):
    """Passenger → Taxi booking scenarios."""

    def test_valid_booking_succeeds(self) -> None:
        response = self._client_for(self.passenger).post(
            "/api/v1/orders/orders/",
            {"trip": self.trip.pk, "seats_booked": 1},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["status"], OrderStatus.PENDING)

    def test_duplicate_booking_rejected(self) -> None:
        order_services.create_order(passenger=self.passenger, trip=self.trip, seats_booked=1)
        response = self._client_for(self.passenger).post(
            "/api/v1/orders/orders/",
            {"trip": self.trip.pk, "seats_booked": 1},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data["error"]["code"], "duplicate_booking")

    def test_invalid_trip_rejected(self) -> None:
        response = self._client_for(self.passenger).post(
            "/api/v1/orders/orders/",
            {"trip": 99999, "seats_booked": 1},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_insufficient_seats_rejected(self) -> None:
        # The trip has 3 free seats; 4 is inside the per-order cap of 8, so the
        # business rule (not the serializer) is what rejects it.
        response = self._client_for(self.passenger).post(
            "/api/v1/orders/orders/",
            {"trip": self.trip.pk, "seats_booked": 4},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data["error"]["code"], "insufficient_seats")

    def test_seats_above_the_per_order_cap_rejected_by_the_serializer(self) -> None:
        response = self._client_for(self.passenger).post(
            "/api/v1/orders/orders/",
            {"trip": self.trip.pk, "seats_booked": 10},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cancelled_trip_rejected(self) -> None:
        ride_services.cancel_trip(self.trip, reason="test")
        response = self._client_for(self.passenger).post(
            "/api/v1/orders/orders/",
            {"trip": self.trip.pk, "seats_booked": 1},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data["error"]["code"], "trip_not_active")

    def test_blocked_user_cannot_book(self) -> None:
        User.objects.filter(pk=self.passenger.pk).update(is_blocked=True)
        self.passenger.refresh_from_db()
        response = self._client_for(self.passenger).post(
            "/api/v1/orders/orders/",
            {"trip": self.trip.pk, "seats_booked": 1},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data["error"]["code"], "user_is_blocked")

    def test_unauthenticated_cannot_book(self) -> None:
        client = Client()
        response = client.post(
            "/api/v1/orders/orders/",
            {"trip": self.trip.pk, "seats_booked": 1},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class DriverBookingTests(BookingAPIBase):
    """Taxi → Passenger booking scenarios."""

    def _book(self, driver: User, request, trip_pk: int | None = None):
        payload: dict = {"request_id": request.pk}
        if trip_pk is not None:
            payload["trip"] = trip_pk
        return self._client_for(driver).post(
            "/api/v1/orders/orders/",
            payload,
            format="json",
        )

    def test_driver_valid_booking_succeeds(self) -> None:
        request = self._make_request(self.passenger)
        response = self._book(self.driver_user, request)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["status"], OrderStatus.ACCEPTED)

    def test_driver_duplicate_booking_rejected(self) -> None:
        # One seat keeps a candidate trip available, so the duplicate guard is
        # what rejects the second attempt rather than the seat filter.
        request = self._make_request(self.passenger, passenger_count=1)
        order_services.book_passenger_request(
            driver_user=self.driver_user,
            passenger_request=request,
        )
        response = self._book(self.driver_user, request)
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data["error"]["code"], "duplicate_booking")

    def test_driver_invalid_request_rejected(self) -> None:
        response = self._client_for(self.driver_user).post(
            "/api/v1/orders/orders/",
            {"request_id": 99999},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_driver_cannot_book_own_request(self) -> None:
        request = self._make_request(self.driver_user)
        response = self._book(self.driver_user, request)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_non_driver_cannot_book(self) -> None:
        request = self._make_request(self.passenger)
        response = self._book(self.stranger, request)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data["error"]["code"], "not_a_driver")

    def test_driver_no_active_trips_auto_creates_trip(self) -> None:
        ride_services.cancel_trip(self.trip, reason="test")
        request = self._make_request(self.passenger)
        response = self._book(self.driver_user, request)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["status"], OrderStatus.ACCEPTED)

    def test_driver_no_vehicle_rejected(self) -> None:
        driver2 = self.data.create_driver()
        driver2.profile.vehicles.all().delete()
        request = self._make_request(self.passenger)
        response = self._book(driver2.user, request)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"]["code"], "validation_error")

    def test_incompatible_route_rejected(self) -> None:
        """A request travelling the opposite way is never a match."""
        request = self._make_request(self.passenger, reverse_route=True)
        response = self._book(self.driver_user, request, trip_pk=self.trip.pk)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"]["code"], "incompatible_route")

    def test_incompatible_time_rejected(self) -> None:
        """A request whose window sits far from the departure is refused."""
        request = self._make_request(
            self.passenger,
            window_start=timedelta(hours=20),
            window_end=timedelta(hours=24),
        )
        response = self._book(self.driver_user, request, trip_pk=self.trip.pk)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"]["code"], "incompatible_time")

    def test_insufficient_capacity_rejected(self) -> None:
        """More passengers than free seats cannot be served."""
        request = self._make_request(self.passenger, passenger_count=2)
        # A PENDING order holds no seat; only accepting one consumes capacity.
        order_services.accept_order(
            order_services.create_order(
                passenger=self.stranger, trip=self.trip, seats_booked=2
            )
        )
        response = self._book(self.driver_user, request, trip_pk=self.trip.pk)
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data["error"]["code"], "insufficient_seats")

    def test_driver_cannot_use_another_drivers_trip(self) -> None:
        other = self.data.create_driver()
        other_trip = self.data.create_trip(other, seats=3)
        request = self._make_request(self.passenger)
        response = self._book(self.driver_user, request, trip_pk=other_trip.pk)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data["error"]["code"], "unauthorized_order_access")

    def test_cancelled_request_rejected(self) -> None:
        request = self._make_request(self.passenger)
        ride_services.cancel_passenger_request(request)
        response = self._book(self.driver_user, request)
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data["error"]["code"], "passenger_request_not_active")

    def test_expired_request_rejected(self) -> None:
        request = self._make_request(
            self.passenger, window_start=timedelta(hours=-5), window_end=timedelta(hours=-3)
        )
        response = self._book(self.driver_user, request)
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data["error"]["code"], "passenger_request_not_active")


class ChatIntegrationTests(BookingAPIBase):
    """Chat must work for both sides after booking."""

    def setUp(self) -> None:
        super().setUp()
        self.order = order_services.create_order(
            passenger=self.passenger, trip=self.trip, seats_booked=1
        )

    def test_passenger_can_open_chat(self) -> None:
        client = self._client_for(self.passenger)
        response = client.post(
            "/api/v1/chat/chats/open/",
            {"order_id": self.order.pk},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["order_id"], self.order.pk)

    def test_driver_can_open_chat(self) -> None:
        client = self._client_for(self.driver_user)
        response = client.post(
            "/api/v1/chat/chats/open/",
            {"order_id": self.order.pk},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["order_id"], self.order.pk)

    def test_existing_conversation_is_reused(self) -> None:
        thread, _ = get_or_create_conversation(user=self.passenger, order_id=self.order.pk)
        self.assertIsNotNone(thread)
        thread2, created = get_or_create_conversation(user=self.driver_user, order_id=self.order.pk)
        self.assertFalse(created)
        self.assertEqual(thread.pk, thread2.pk)

    def test_chat_from_trip_id_passenger(self) -> None:
        client = self._client_for(self.passenger)
        response = client.post(
            "/api/v1/chat/chats/open/",
            {"trip_id": self.trip.pk},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["order_id"], self.order.pk)
        self.assertFalse(response.data["created"])

    def test_chat_from_request_id_driver_creates_new_thread(self) -> None:
        fresh_passenger = self.data.create_passenger()
        request = self._make_request(fresh_passenger)
        client = self._client_for(self.driver_user)
        response = client.post(
            "/api/v1/chat/chats/open/",
            {"request_id": request.pk},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data["created"])

    def test_chat_from_request_id_driver_reuses_existing_thread(self) -> None:
        """The setUp order already links this passenger to the driver."""
        request = self._make_request(self.passenger)
        client = self._client_for(self.driver_user)
        response = client.post(
            "/api/v1/chat/chats/open/",
            {"request_id": request.pk},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["created"])
        self.assertEqual(response.data["order_id"], self.order.pk)

    def test_messages_can_be_exchanged_after_booking(self) -> None:
        posted = self._client_for(self.passenger).post(
            f"/api/v1/chat/chats/{self.order.pk}/messages/",
            {"text": " Salom!"},
            format="json",
        )
        self.assertEqual(posted.status_code, status.HTTP_201_CREATED)

        received = self._client_for(self.driver_user).get(
            f"/api/v1/chat/chats/{self.order.pk}/messages/"
        )
        self.assertEqual(received.status_code, status.HTTP_200_OK)
        texts = [item["text"] for item in received.data["results"]]
        self.assertIn("Salom!", texts)

    def test_stranger_cannot_read_messages(self) -> None:
        response = self._client_for(self.stranger).get(
            f"/api/v1/chat/chats/{self.order.pk}/messages/"
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthorized_cannot_open_chat(self) -> None:
        client = self._client_for(self.stranger)
        response = client.post(
            "/api/v1/chat/chats/open/",
            {"order_id": self.order.pk},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data["error"]["code"], "unauthorized_chat_access")