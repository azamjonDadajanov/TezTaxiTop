"""Write/business layer for the rides app.

Concurrency contract
--------------------
Seat accounting is the only place in the platform where two users can
contradict each other at the same instant. The rules are:

1. Every mutation of ``DriverTrip.available_seats`` happens inside
   ``transaction.atomic()`` and starts with
   ``DriverTrip.objects.select_for_update().get(pk=...)``. The row lock is held
   until the transaction commits, so the second transaction reads the *already
   updated* value instead of a stale one.
2. The check "are there enough seats?" is therefore performed **after** the lock
   was acquired, never before.
3. A final database level backstop
   (``available_seats <= total_seats`` and ``available_seats >= 0``) makes a
   negative seat count physically impossible even if application code were
   bypassed.
4. ``FOR UPDATE`` is skipped by SQLite (which locks the whole database), which
   keeps the production code identical for local development and the test suite.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from decimal import Decimal
from typing import Iterable

from django.db import DatabaseError, transaction
from django.db.models import F
from django.utils import timezone

from apps.core import conf
from apps.core.exceptions import (
    BusinessValidationError,
    InsufficientSeats,
    NotADriver,
    SubscriptionRequired,
    TripAlreadyCancelled,
    TripAlreadyCompleted,
    TripError,
    TripNotEditable,
)
from apps.locations.models import Location
from apps.rides.constants import (
    BOOKABLE_TRIP_STATUSES,
    MATCHABLE_REQUEST_STATUSES,
    MAX_SEATS_PER_TRIP,
    MONEY_DECIMAL_PLACES,
    MONEY_MAX_DIGITS,
)
from apps.rides.models import (
    DriverTrip,
    DriverTripStatus,
    PassengerRequest,
    PassengerRequestStatus,
)
from apps.rides.selectors import (
    get_expired_request_candidates,
    get_expired_trips_candidates,
    get_request_by_id,
    get_trip_by_id,
)
from apps.users.models import DriverProfile, User
from apps.vehicles.models import Vehicle

logger = logging.getLogger(__name__)

NON_NEGATIVE = Decimal("0.00")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _lock_trip(trip_id: int) -> DriverTrip:
    """Return a trip row locked for the current transaction.

    ``select_for_update()`` is skipped on backends that do not support row level
    locking (SQLite); on PostgreSQL it serialises concurrent seat operations.
    """
    queryset = DriverTrip.objects.select_for_update()
    if not _supports_select_for_update():
        queryset = DriverTrip.objects.all()
    trip = queryset.select_related("driver__user", "vehicle", "from_location", "to_location").get(pk=trip_id)
    return trip


def _supports_select_for_update() -> bool:
    from django.db import connection

    return connection.features.has_select_for_update


def _to_decimal(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _assert_trip_is_editable(trip: DriverTrip) -> None:
    if trip.status == DriverTripStatus.CANCELLED:
        raise TripAlreadyCancelled()
    if trip.status == DriverTripStatus.COMPLETED:
        raise TripAlreadyCompleted()


def _snapshot_point(snapshot: dict, prefix: str) -> tuple[Decimal, Decimal] | None:
    """Read one endpoint's ``(latitude, longitude)`` out of a snapshot dict."""
    latitude = snapshot.get(f"{prefix}_latitude")
    longitude = snapshot.get(f"{prefix}_longitude")
    if latitude is None or longitude is None:
        return None
    return (_to_decimal(latitude), _to_decimal(longitude))


def _model_point(obj, prefix: str) -> tuple[Decimal, Decimal] | None:
    """Same as :func:`_snapshot_point` but for an in-memory model instance."""
    return _snapshot_point(
        {
            f"{prefix}_latitude": getattr(obj, f"{prefix}_latitude", None),
            f"{prefix}_longitude": getattr(obj, f"{prefix}_longitude", None),
        },
        prefix,
    )


#: ``(write key, snapshot prefix, catalogue FK field)`` for one route endpoint.
#: Shared by both update paths so a map pin and a catalogue entry can never be
#: resolved differently for a trip than for a passenger request.
_ENDPOINT_WRITE_FIELDS = (
    ("origin", "from", "from_location"),
    ("destination", "to", "to_location"),
)


def _resolve_endpoint_updates(changes: dict) -> dict[str, object]:
    """Pop the endpoint keys out of ``changes``, returning their snapshot columns.

    Mirrors the precedence of :func:`create_trip`: an endpoint described by a
    catalogue ``Location`` resolves from that row, and an endpoint described by a
    bare map pin resolves from its coordinates.

    A pin also **clears** its endpoint's catalogue FK. Leaving the old FK in
    place would keep the read layer preferring it - ``_endpoint_payload`` returns
    the catalogue row whenever one is linked - so a trip edited onto a new pin
    would still display the place the driver moved away from.
    """
    from apps.locations.services import build_point_snapshot

    snapshot_columns: dict[str, object] = {}
    for write_key, prefix, location_field in _ENDPOINT_WRITE_FIELDS:
        payload = changes.pop(write_key, None)
        if location_field in changes:
            # An explicitly resupplied catalogue entry is the deliberate choice,
            # so the snapshot is rebuilt from it rather than from a bare pin.
            # That keeps the two halves of the endpoint from disagreeing.
            location = changes[location_field]
            if location is not None or payload is not None:
                snapshot_columns.update(
                    build_point_snapshot(prefix, location=location, **(payload or {}))
                )
            continue
        if payload is None:
            continue
        snapshot_columns.update(build_point_snapshot(prefix, **payload))
        changes[location_field] = None
    return snapshot_columns


def _assert_distinct_endpoints(
    *,
    from_location_id,
    to_location_id,
    from_point: tuple[Decimal, Decimal] | None,
    to_point: tuple[Decimal, Decimal] | None,
) -> None:
    """Reject a route whose two endpoints are the same place.

    Identity is the catalogue FK when both sides carry one, and the coordinates
    otherwise. Comparing only the FKs - the pre-map behaviour - would let a
    map-picked "Toshkent -> Toshkent" trip through, because such a trip has no
    FKs at all.
    """
    same_catalogue_place = from_location_id is not None and from_location_id == to_location_id
    same_point = from_point is not None and from_point == to_point
    if same_catalogue_place or same_point:
        raise BusinessValidationError("Qayerdan va qayerga bir xil bo'lishi mumkin emas.")


# ---------------------------------------------------------------------------
# Driver eligibility
# ---------------------------------------------------------------------------
def assert_driver_can_create_trip(user: User) -> DriverProfile:
    """Validate every business precondition for publishing a trip.

    Order of checks matters: the cheapest, most specific failures come first so
    the bot can show a precise message.
    """
    driver_profile = getattr(user, "driver_profile", None)
    if driver_profile is None:
        raise NotADriver()

    if user.is_blocked:
        from apps.core.exceptions import UserIsBlocked

        raise UserIsBlocked()

    if conf.require_verified_driver_to_drive() and not driver_profile.is_verified:
        from apps.core.exceptions import DriverNotVerified

        raise DriverNotVerified()

    if conf.require_active_subscription_to_drive():
        from apps.subscriptions.services import has_active_subscription

        if not has_active_subscription(driver_profile):
            raise SubscriptionRequired()
    return driver_profile


def _validate_vehicle_for_trip(driver_profile: DriverProfile, vehicle: Vehicle) -> Vehicle:
    """The vehicle must belong to the driver and be usable."""
    if vehicle.driver_id != driver_profile.pk:
        from apps.core.exceptions import VehicleOwnershipError

        raise VehicleOwnershipError(
            details={"vehicle_id": vehicle.pk, "driver_id": driver_profile.pk}
        )
    if not vehicle.is_active:
        from apps.core.exceptions import VehicleNotVerified

        raise VehicleNotVerified("Avtomobil o'chirilgan (is_active=False).")
    if conf.require_verified_vehicle_to_drive() and not vehicle.is_verified:
        from apps.core.exceptions import VehicleNotVerified

        raise VehicleNotVerified("Avtomobil administrator tomonidan tasdiqlanmagan.")
    return vehicle


# ---------------------------------------------------------------------------
# Trip lifecycle
# ---------------------------------------------------------------------------
def create_trip(
    *,
    driver_profile: DriverProfile,
    vehicle: Vehicle,
    departure_time,
    total_seats: int,
    price_per_seat,
    from_location: Location | None = None,
    to_location: Location | None = None,
    origin: dict | None = None,
    destination: dict | None = None,
    comment: str = "",
    publish: bool = True,
) -> DriverTrip:
    """Create a driver trip, resolving both route endpoints first.

    ``publish=True`` makes the trip immediately ``ACTIVE``; ``False`` keeps it a
    ``DRAFT`` that is invisible to passengers.

    Each route endpoint is described either by a catalogue ``*_location`` or by
    a snapshot dict (the seven ``from_*`` / ``to_*`` columns) - see
    :func:`apps.locations.services.build_point_snapshot`.

    The endpoint resolution (which may call 2GIS, up to ``TWOGIS_TIMEOUT``
    seconds per endpoint) deliberately happens **outside** the database
    transaction opened by :func:`_create_trip_in_transaction`, so a slow or
    hanging provider can never hold row locks.
    """
    from apps.locations.services import build_point_snapshot

    origin_snapshot = build_point_snapshot("from", location=from_location, **(origin or {}))
    destination_snapshot = build_point_snapshot("to", location=to_location, **(destination or {}))
    return _create_trip_in_transaction(
        driver_profile=driver_profile,
        vehicle=vehicle,
        from_location=from_location,
        to_location=to_location,
        departure_time=departure_time,
        total_seats=total_seats,
        price_per_seat=price_per_seat,
        comment=comment,
        publish=publish,
        origin_snapshot=origin_snapshot,
        destination_snapshot=destination_snapshot,
    )


@transaction.atomic
def _create_trip_in_transaction(
    *,
    driver_profile: DriverProfile,
    vehicle: Vehicle,
    from_location: Location | None,
    to_location: Location | None,
    departure_time,
    total_seats: int,
    price_per_seat,
    comment: str,
    publish: bool,
    origin_snapshot: dict,
    destination_snapshot: dict,
) -> DriverTrip:
    """Create a driver trip.

    ``publish=True`` makes the trip immediately ``ACTIVE``; ``False`` keeps it a
    ``DRAFT`` that is invisible to passengers.

    Each route endpoint is described either by a catalogue ``*_location`` or by
    a snapshot dict (the seven ``from_*`` / ``to_*`` columns) - see
    :func:`apps.locations.services.build_point_snapshot`.
    """
    if total_seats is None or total_seats <= 0:
        raise BusinessValidationError("Kamida 1 ta o'rin kerak.")
    if total_seats > MAX_SEATS_PER_TRIP:
        raise BusinessValidationError(f"Ko'pi bilan {MAX_SEATS_PER_TRIP} ta o'rin.")
    _assert_distinct_endpoints(
        from_location_id=from_location.pk if from_location is not None else None,
        to_location_id=to_location.pk if to_location is not None else None,
        from_point=_snapshot_point(origin_snapshot, "from"),
        to_point=_snapshot_point(destination_snapshot, "to"),
    )
    if departure_time is None:
        raise BusinessValidationError("Chuqish vaqti majburiy.")
    if timezone.is_naive(departure_time):
        raise BusinessValidationError("Chuqish vaqti vaqt zonasi bilan (timezone-aware) bo'lishi shart.")

    _validate_vehicle_for_trip(driver_profile, vehicle)
    if total_seats > vehicle.seats_for_passengers:
        raise BusinessValidationError(
            f"Bu avtomobilda {vehicle.seats_for_passengers} ta o'rin mavjud."
        )

    price = _to_decimal(price_per_seat)
    if price < NON_NEGATIVE:
        raise BusinessValidationError("Narx manfiy bo'lishi mumkin emas.")

    trip = DriverTrip(
        driver=driver_profile,
        vehicle=vehicle,
        from_location=from_location,
        to_location=to_location,
        departure_time=departure_time,
        total_seats=total_seats,
        available_seats=total_seats,
        price_per_seat=price,
        comment=comment.strip(),
        status=DriverTripStatus.ACTIVE if publish else DriverTripStatus.DRAFT,
        **origin_snapshot,
        **destination_snapshot,
    )
    trip.full_clean()
    trip.save()

    from apps.users.services import increment_driver_trip_statistics

    increment_driver_trip_statistics(driver_profile)
    logger.info("Yo'lov yaratildi: %s (haydovchi=%s)", trip.pk, driver_profile.pk)
    return trip


def update_trip(trip: DriverTrip, **changes) -> DriverTrip:
    """Update an editable trip.

    Allowed keys: ``vehicle``, ``from_location``, ``to_location``, ``origin``,
    ``destination``, ``departure_time``, ``total_seats``, ``price_per_seat``,
    ``comment``.

    ``available_seats`` is deliberately **not** editable: it is derived from the
    orders and is only changed through :func:`reserve_seats` /
    :func:`release_seats`.

    A new ``origin`` / ``destination`` is resolved before the transaction opens,
    for the same reason as in :func:`create_trip`.
    """
    snapshot_columns = _resolve_endpoint_updates(changes)
    return _update_trip_in_transaction(trip.pk, changes, snapshot_columns)


@transaction.atomic
def _update_trip_in_transaction(
    trip_pk: int, changes: dict, snapshot_columns: dict[str, object]
) -> DriverTrip:
    locked_trip = _lock_trip(trip_pk)
    _assert_trip_is_editable(locked_trip)

    allowed_fields = {
        "vehicle",
        "from_location",
        "to_location",
        "departure_time",
        "total_seats",
        "price_per_seat",
        "comment",
    }
    unknown = set(changes) - allowed_fields
    if unknown:
        raise BusinessValidationError(f"Ruxsat berilmagan maydonlar: {sorted(unknown)}")

    for field, value in changes.items():
        if field == "price_per_seat":
            value = _to_decimal(value)
            if value < NON_NEGATIVE:
                raise BusinessValidationError("Narx manfiy bo'lishi mumkin emas.")
        setattr(locked_trip, field, value)

    for column, value in snapshot_columns.items():
        setattr(locked_trip, column, value)

    _assert_distinct_endpoints(
        from_location_id=locked_trip.from_location_id,
        to_location_id=locked_trip.to_location_id,
        # The snapshot columns have already been applied above, so the instance
        # holds the post-update route - including any pin the caller just moved.
        from_point=_model_point(locked_trip, "from"),
        to_point=_model_point(locked_trip, "to"),
    )
    if locked_trip.total_seats < locked_trip.booked_seats:
        raise BusinessValidationError(
            f"Allaqachon {locked_trip.booked_seats} ta o'rin band, kamaytirib bo'lmaydi."
        )
    if locked_trip.total_seats > locked_trip.vehicle.seats_for_passengers:
        raise BusinessValidationError(
            f"Bu avtomobilda {locked_trip.vehicle.seats_for_passengers} ta o'rin mavjud."
        )

    locked_trip.full_clean()
    locked_trip.save()
    _sync_trip_status_after_seat_change(locked_trip)
    return locked_trip


@transaction.atomic
def publish_trip(trip: DriverTrip) -> DriverTrip:
    """Publish a draft trip."""
    locked_trip = _lock_trip(trip.pk)
    if locked_trip.status != DriverTripStatus.DRAFT:
        raise TripNotEditable("Faqat qoralama yo'lovni e'lon qilish mumkin.")
    locked_trip.status = DriverTripStatus.ACTIVE
    locked_trip.save(update_fields=["status", "updated_at"])
    return locked_trip


@transaction.atomic
def cancel_trip(trip: DriverTrip, *, reason: str = "") -> DriverTrip:
    """Cancel a trip.

    A cancelled trip never accepts new orders, and every seat that was still
    free is released implicitly by the status change (booked seats stay booked
    because the corresponding orders handle their own state transitions).
    """
    locked_trip = _lock_trip(trip.pk)
    if locked_trip.status == DriverTripStatus.CANCELLED:
        raise TripAlreadyCancelled()
    if locked_trip.status == DriverTripStatus.COMPLETED:
        raise TripAlreadyCompleted()

    locked_trip.status = DriverTripStatus.CANCELLED
    if reason:
        comment = locked_trip.comment or ""
        locked_trip.comment = f"{comment}\n[Bekor sababi] {reason}".strip()
    locked_trip.save(update_fields=["status", "comment", "updated_at"])

    # Notify / close every order that was still waiting for this trip.
    from apps.orders.models import OrderStatus

    locked_trip.orders.filter(status=OrderStatus.PENDING).update(
        status=OrderStatus.CANCELLED_BY_DRIVER
    )

    from apps.users.services import increment_driver_trip_statistics

    increment_driver_trip_statistics(locked_trip.driver, cancelled=True)
    logger.info("Yo'lov bekor qilindi: %s", locked_trip.pk)
    return locked_trip


@transaction.atomic
def start_trip(trip: DriverTrip) -> DriverTrip:
    """Driver declares the trip has started."""
    locked_trip = _lock_trip(trip.pk)
    if locked_trip.status not in (DriverTripStatus.ACTIVE, DriverTripStatus.FULL):
        raise TripNotEditable(
            f"Holat '{locked_trip.get_status_display()}' dan yo'lni boshlab bo'lmaydi."
        )
    locked_trip.status = DriverTripStatus.IN_PROGRESS
    locked_trip.save(update_fields=["status", "updated_at"])
    return locked_trip


@transaction.atomic
def complete_trip(trip: DriverTrip) -> DriverTrip:
    """Mark a trip as finished and bump the driver statistics."""
    locked_trip = _lock_trip(trip.pk)
    if locked_trip.status == DriverTripStatus.COMPLETED:
        raise TripAlreadyCompleted()
    if locked_trip.status == DriverTripStatus.CANCELLED:
        raise TripAlreadyCancelled()
    if locked_trip.status not in (DriverTripStatus.IN_PROGRESS, DriverTripStatus.ACTIVE, DriverTripStatus.FULL):
        raise TripNotEditable("Yakunlash uchun yo'lov faol yoki jarayonda bo'lishi shart.")

    locked_trip.status = DriverTripStatus.COMPLETED
    locked_trip.available_seats = 0
    locked_trip.save(update_fields=["status", "available_seats", "updated_at"])

    from apps.users.services import increment_completed_trips

    increment_completed_trips(locked_trip.driver)
    return locked_trip


@transaction.atomic
def expire_trips(grace_minutes: int | None = None) -> int:
    """Bulk expire trips whose departure time has passed. Idempotent."""
    grace = grace_minutes if grace_minutes is not None else conf.TRIP_DEPARTURE_GRACE_MINUTES
    expired_count = 0
    for candidate in get_expired_trips_candidates(grace).values_list("pk", flat=True):
        try:
            with transaction.atomic():
                trip = _lock_trip(candidate)
                if trip.status in (
                    DriverTripStatus.DRAFT,
                    DriverTripStatus.ACTIVE,
                    DriverTripStatus.FULL,
                ):
                    trip.status = DriverTripStatus.EXPIRED
                    trip.save(update_fields=["status", "updated_at"])
                    expired_count += 1
        except (DriverTrip.DoesNotExist, DatabaseError):  # pragma: no cover - race safety
            continue
    return expired_count


# ---------------------------------------------------------------------------
# Seat accounting - the concurrency critical part
# ---------------------------------------------------------------------------
@transaction.atomic
def reserve_seats(trip: DriverTrip, seats: int) -> DriverTrip:
    """Reserve ``seats`` on ``trip``.

    Raises :class:`InsufficientSeats` when the trip cannot supply them, so a
    caller never has to guess whether the reservation succeeded.
    """
    if seats is None or seats <= 0:
        raise BusinessValidationError("Kamida 1 ta o'rin band qilinishi kerak.")

    locked_trip = _lock_trip(trip.pk)

    if locked_trip.status not in BOOKABLE_TRIP_STATUSES:
        raise TripError(
            f"Bu yo'lov '{locked_trip.get_status_display()}' holatida, yangi buyurtma qabul qilinmaydi.",
            code="trip_not_bookable",
            status_code=409,
        )
    if locked_trip.available_seats < seats:
        raise InsufficientSeats(
            details={"available_seats": locked_trip.available_seats, "requested_seats": seats}
        )

    locked_trip.available_seats = F("available_seats") - seats
    locked_trip.save(update_fields=["available_seats", "updated_at"])
    locked_trip.refresh_from_db(fields=["available_seats", "status", "updated_at"])
    _sync_trip_status_after_seat_change(locked_trip)
    return locked_trip


@transaction.atomic
def release_seats(trip: DriverTrip, seats: int) -> DriverTrip:
    """Return ``seats`` to the pool (rejection / cancellation / no-show)."""
    if seats is None or seats <= 0:
        raise BusinessValidationError("Kamida 1 ta o'rin qaytarilishi kerak.")

    locked_trip = _lock_trip(trip.pk)
    if locked_trip.status in (DriverTripStatus.CANCELLED, DriverTripStatus.EXPIRED):
        # A cancelled/expired trip can no longer take bookings, but the counter
        # must stay consistent for the historical record.
        locked_trip.available_seats = F("available_seats") + seats
        locked_trip.save(update_fields=["available_seats", "updated_at"])
        locked_trip.refresh_from_db(fields=["available_seats"])
        return locked_trip

    new_available = locked_trip.available_seats + seats
    if new_available > locked_trip.total_seats:
        raise BusinessValidationError("O'rinlar soni jami o'rinlar sonidan oshdi.")

    locked_trip.available_seats = F("available_seats") + seats
    locked_trip.save(update_fields=["available_seats", "updated_at"])
    locked_trip.refresh_from_db(fields=["available_seats", "status", "updated_at"])
    _sync_trip_status_after_seat_change(locked_trip)
    return locked_trip


def _sync_trip_status_after_seat_change(trip: DriverTrip) -> None:
    """Flip ``ACTIVE <-> FULL`` automatically when the seat counter changes."""
    if trip.status == DriverTripStatus.FULL and trip.available_seats > 0:
        trip.status = DriverTripStatus.ACTIVE
        trip.save(update_fields=["status", "updated_at"])
    elif trip.status == DriverTripStatus.ACTIVE and trip.available_seats == 0:
        trip.status = DriverTripStatus.FULL
        trip.save(update_fields=["status", "updated_at"])


@transaction.atomic
def lock_trip_for_update(trip_id: int) -> DriverTrip:
    """Public entry point used by other services (e.g. ``apps.orders``)."""
    return _lock_trip(trip_id)


# ---------------------------------------------------------------------------
# Passenger requests
# ---------------------------------------------------------------------------
def create_passenger_request(
    *,
    passenger: User,
    from_location: Location | None = None,
    to_location: Location | None = None,
    passenger_count: int = 1,
    max_price_per_seat=None,
    departure_from=None,
    departure_until=None,
    comment: str = "",
    origin: dict | None = None,
    destination: dict | None = None,
) -> PassengerRequest:
    """Create a passenger request and immediately queue the matching job.

    Route endpoints are resolved before the transaction opens, exactly like
    :func:`create_trip`.
    """
    from apps.locations.services import build_point_snapshot

    origin_snapshot = build_point_snapshot("from", location=from_location, **(origin or {}))
    destination_snapshot = build_point_snapshot("to", location=to_location, **(destination or {}))

    return _create_passenger_request_in_transaction(
        passenger=passenger,
        from_location=from_location,
        to_location=to_location,
        passenger_count=passenger_count,
        max_price_per_seat=max_price_per_seat,
        departure_from=departure_from,
        departure_until=departure_until,
        comment=comment,
        origin_snapshot=origin_snapshot,
        destination_snapshot=destination_snapshot,
    )


@transaction.atomic
def _create_passenger_request_in_transaction(
    *,
    passenger: User,
    from_location: Location | None,
    to_location: Location | None,
    passenger_count: int,
    max_price_per_seat,
    departure_from,
    departure_until,
    comment: str,
    origin_snapshot: dict,
    destination_snapshot: dict,
) -> PassengerRequest:
    if passenger.is_blocked:
        from apps.core.exceptions import UserIsBlocked

        raise UserIsBlocked()
    if passenger_count is None or passenger_count <= 0:
        raise BusinessValidationError("Yo'lovchi soni 0 dan katta bo'lishi kerak.")
    _assert_distinct_endpoints(
        from_location_id=from_location.pk if from_location is not None else None,
        to_location_id=to_location.pk if to_location is not None else None,
        from_point=_snapshot_point(origin_snapshot, "from"),
        to_point=_snapshot_point(destination_snapshot, "to"),
    )

    departure_from = departure_from or timezone.now()
    if departure_until is None:
        departure_until = departure_from + timedelta(hours=conf.PASSENGER_REQUEST_EXPIRY_HOURS)
    if departure_until <= departure_from:
        raise BusinessValidationError("Chuqish oxirgi vaqti boshlangan vaqtdan katta bo'lishi shart.")
    if timezone.is_naive(departure_from) or timezone.is_naive(departure_until):
        raise BusinessValidationError("Vaqtlar timezone-aware bo'lishi shart.")

    price = None
    if max_price_per_seat is not None:
        price = _to_decimal(max_price_per_seat)
        if price < NON_NEGATIVE:
            raise BusinessValidationError("Maksimal narx manfiy bo'lishi mumkin emas.")

    passenger_request = PassengerRequest(
        passenger=passenger,
        from_location=from_location,
        to_location=to_location,
        passenger_count=passenger_count,
        max_price_per_seat=price,
        departure_from=departure_from,
        departure_until=departure_until,
        comment=comment.strip(),
        status=PassengerRequestStatus.ACTIVE,
        **origin_snapshot,
        **destination_snapshot,
    )
    passenger_request.full_clean()
    passenger_request.save()
    logger.info("Yo'lovchi so'rovi yaratildi: %s", passenger_request.pk)
    return passenger_request


def update_passenger_request(passenger_request: PassengerRequest, **changes) -> PassengerRequest:
    """Update an active passenger request.

    A new ``origin`` / ``destination`` is resolved before the transaction opens,
    exactly like :func:`create_passenger_request`, and through the same helper as
    :func:`update_trip` so both sides behave identically.
    """
    snapshot_columns = _resolve_endpoint_updates(changes)
    return _update_passenger_request_in_transaction(
        passenger_request.pk, changes, snapshot_columns
    )


@transaction.atomic
def _update_passenger_request_in_transaction(
    request_pk: int, changes: dict, snapshot_columns: dict[str, object]
) -> PassengerRequest:
    passenger_request = PassengerRequest.objects.select_for_update().get(pk=request_pk)
    if passenger_request.status != PassengerRequestStatus.ACTIVE:
        raise TripNotEditable("Faqat faol so'rovni tahrirlash mumkin.")

    allowed_fields = {
        "from_location",
        "to_location",
        "passenger_count",
        "max_price_per_seat",
        "departure_from",
        "departure_until",
        "comment",
    }
    unknown = set(changes) - allowed_fields
    if unknown:
        raise BusinessValidationError(f"Ruxsat berilmagan maydonlar: {sorted(unknown)}")

    for field, value in changes.items():
        if field == "max_price_per_seat" and value is not None:
            value = _to_decimal(value)
        setattr(passenger_request, field, value)

    for column, value in snapshot_columns.items():
        setattr(passenger_request, column, value)

    _assert_distinct_endpoints(
        from_location_id=passenger_request.from_location_id,
        to_location_id=passenger_request.to_location_id,
        from_point=_model_point(passenger_request, "from"),
        to_point=_model_point(passenger_request, "to"),
    )
    if passenger_request.passenger_count <= 0:
        raise BusinessValidationError("Yo'lovchi soni 0 dan katta bo'lishi kerak.")
    if passenger_request.departure_until <= passenger_request.departure_from:
        raise BusinessValidationError("Chuqish oxirgi vaqti boshlangan vaqtdan katta bo'lishi shart.")

    passenger_request.full_clean()
    passenger_request.save()
    return passenger_request


@transaction.atomic
def cancel_passenger_request(passenger_request: PassengerRequest) -> PassengerRequest:
    """Cancel an active request so that it is never matched again."""
    if passenger_request.status == PassengerRequestStatus.CANCELLED:
        return passenger_request
    if passenger_request.status == PassengerRequestStatus.COMPLETED:
        raise TripNotEditable("Yakunlangan so'rovni bekor qilish mumkin emas.")

    PassengerRequest.objects.filter(pk=passenger_request.pk).update(
        status=PassengerRequestStatus.CANCELLED
    )
    passenger_request.matches.filter(
        status__in=("pending", "notified", "accepted")
    ).update(status="rejected")
    passenger_request.refresh_from_db(fields=["status"])
    return passenger_request


@transaction.atomic
def complete_passenger_request(passenger_request: PassengerRequest) -> PassengerRequest:
    """Mark a request as fulfilled (at least one accepted order)."""
    if passenger_request.status == PassengerRequestStatus.COMPLETED:
        return passenger_request
    PassengerRequest.objects.filter(pk=passenger_request.pk).update(
        status=PassengerRequestStatus.COMPLETED
    )
    passenger_request.refresh_from_db(fields=["status"])
    return passenger_request


@transaction.atomic
def expire_passenger_requests(expiry_hours: int | None = None) -> int:
    """Expire stale active requests. Idempotent (safe to run repeatedly)."""
    hours = expiry_hours if expiry_hours is not None else conf.PASSENGER_REQUEST_EXPIRY_HOURS
    expired = 0
    for request_id in get_expired_request_candidates(hours).values_list("pk", flat=True):
        updated = PassengerRequest.objects.filter(
            pk=request_id, status=PassengerRequestStatus.ACTIVE
        ).update(status=PassengerRequestStatus.EXPIRED)
        expired += updated
    return expired


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------
def get_required_trip(trip_id: int) -> DriverTrip:
    trip = get_trip_by_id(trip_id)
    if trip is None:
        from apps.core.exceptions import ResourceNotFound

        raise ResourceNotFound("Yo'lov topilmadi.")
    return trip


def get_required_passenger_request(request_id: int) -> PassengerRequest:
    passenger_request = get_request_by_id(request_id)
    if passenger_request is None:
        from apps.core.exceptions import ResourceNotFound

        raise ResourceNotFound("So'rov topilmadi.")
    return passenger_request


def list_active_requests() -> Iterable[PassengerRequest]:
    return PassengerRequest.objects.filter(status__in=MATCHABLE_REQUEST_STATUSES)


__all__ = [
    "MONEY_DECIMAL_PLACES",
    "MONEY_MAX_DIGITS",
    "assert_driver_can_create_trip",
    "cancel_passenger_request",
    "cancel_trip",
    "complete_passenger_request",
    "complete_trip",
    "create_passenger_request",
    "create_trip",
    "expire_passenger_requests",
    "expire_trips",
    "get_required_passenger_request",
    "get_required_trip",
    "lock_trip_for_update",
    "publish_trip",
    "release_seats",
    "reserve_seats",
    "start_trip",
    "update_passenger_request",
    "update_trip",
]
