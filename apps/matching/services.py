"""The deterministic matching engine.

Entry points:

``rank_trips_for_request(request)`` / ``get_ranked_matches(request)``
    Passenger side: which trips fit one request, best first.

``rank_requests_for_trip(trip)`` / ``get_ranked_matches_for_trip(trip)``
    Driver side: which passenger requests fit one trip - the list the
    "suitable trips" screen renders without asking the user to pick anything.

``get_suitable_requests_by_trip(driver)``
    Driver side, whole answer in one call: every bookable trip of that driver
    with its ranked passengers, trips without a match left out.

``score_trip_for_request(trip, request)``
    Pure scoring function - no database writes. Given a pair it returns the
    component scores and the total, or an ``excluded`` reason when one of the
    hard filters rejects the pair.

A pair must clear four hard filters before it is ranked (see
:func:`exclusion_reason`): the routes must be *geographically* compatible
(same direction, every corresponding point within
``MATCHING_MAX_ROUTE_DISTANCE_KM`` - inclusive, so exactly 25 km still
matches), the departure must be within ``MATCHING_TIME_TOLERANCE_MINUTES`` of
the requested window, the party must fit into the free seats, and the trip must
still be bookable, verified, subscribed and inside the budget.

The requested departure is a **window**, not an instant:
``apps.rides.models.PassengerRequest`` stores ``departure_from`` /
``departure_until``, and :func:`apps.matching.compatibility.time_difference_minutes`
measures the trip departure against the nearer end of that window. So "0
minutes apart" means "the departure sits inside the window", and the 60-minute
tolerance is the distance to the window's edge. That window semantics is the
stored business rule and is what the tests in
``apps.matching.test_suitable_requests.TimeRuleTests`` pin down.

Every weight is a module constant so the algorithm is auditable in one screen.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.utils import timezone

from apps.core import conf
from apps.core.exceptions import ResourceNotFound
from apps.matching import compatibility
from apps.matching.models import MatchReason, TripMatch
from apps.matching.selectors import get_best_matches_for_request
from apps.rides import selectors as ride_selectors
from apps.rides.models import DriverTrip, PassengerRequest
from apps.subscriptions.models import DriverSubscriptionStatus

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Weights - the sum of all weights is MAX_SCORE.
# ---------------------------------------------------------------------------
WEIGHT_TIME = Decimal("30")
WEIGHT_PRICE = Decimal("30")
WEIGHT_RATING = Decimal("20")
WEIGHT_SUBSCRIPTION = Decimal("10")
WEIGHT_VEHICLE = Decimal("10")
MAX_SCORE = WEIGHT_TIME + WEIGHT_PRICE + WEIGHT_RATING + WEIGHT_SUBSCRIPTION + WEIGHT_VEHICLE

QUANT = Decimal("0.01")
ZERO = Decimal("0.00")
MAX_RATING = Decimal("5")
MIN_RATING = Decimal("1")


@dataclass
class MatchScore:
    """Scoring result for one (trip, request) pair."""

    total: Decimal
    time_score: Decimal
    price_score: Decimal
    rating_score: Decimal
    subscription_score: Decimal
    vehicle_score: Decimal
    minutes_difference: int
    price_difference: Decimal
    excluded: str = ""
    reasons: list[str] = field(default_factory=list)

    @property
    def is_match(self) -> bool:
        return not self.excluded

    def as_components(self) -> dict:
        return {
            "time": self.time_score,
            "price": self.price_score,
            "rating": self.rating_score,
            "subscription": self.subscription_score,
            "vehicle": self.vehicle_score,
        }


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
def _quantize(value: Decimal) -> Decimal:
    return Decimal(value).quantize(QUANT, rounding=ROUND_HALF_UP)


def _time_component(trip: DriverTrip, request: PassengerRequest) -> tuple[Decimal, int]:
    """Closer departure (to the start of the window) = higher score."""
    reference = request.departure_from
    delta = trip.departure_time - reference
    minutes = int(abs(delta.total_seconds()) // 60)
    window_minutes = max(1, int(conf.MATCHING_TIME_WINDOW_HOURS * 60))
    if minutes >= window_minutes:
        return ZERO, minutes
    ratio = Decimal(window_minutes - minutes) / Decimal(window_minutes)
    return _quantize(WEIGHT_TIME * ratio), minutes


def _price_component(trip: DriverTrip, request: PassengerRequest) -> tuple[Decimal, Decimal]:
    """Cheaper than the budget = higher score.

    A trip *above* the budget never reaches this function (``exclusion_reason``
    already rejected it). Without a budget there is nothing to compare against,
    so every candidate gets the same neutral 50% and the ranking falls back to
    time, rating and vehicle - deterministic and explainable, just not decisive.
    """
    budget = request.max_price_per_seat
    if budget is None:
        return _quantize(WEIGHT_PRICE / 2), ZERO
    price = trip.price_per_seat
    difference = price - budget
    if budget == 0:
        return _quantize(WEIGHT_PRICE), difference
    # free -> full price weight, exactly at the budget -> 50% of the weight.
    ratio = Decimal("1") - (price / budget) * Decimal("0.5")
    return _quantize(WEIGHT_PRICE * max(Decimal("0.5"), ratio)), difference


def _rating_component(trip: DriverTrip) -> Decimal:
    rating = trip.driver.rating or MIN_RATING
    rating = max(MIN_RATING, min(MAX_RATING, Decimal(str(rating))))
    ratio = (rating - MIN_RATING) / (MAX_RATING - MIN_RATING)
    return _quantize(WEIGHT_RATING * ratio)


def _subscription_component(trip: DriverTrip) -> Decimal:
    """Drivers further from the expiry date get a small bonus."""
    if not conf.require_active_subscription_to_drive():
        return _quantize(WEIGHT_SUBSCRIPTION)
    subscription = (
        trip.driver.subscriptions.filter(
            status=DriverSubscriptionStatus.ACTIVE, expires_at__gt=timezone.now()
        )
        .order_by("-expires_at")
        .first()
    )
    if subscription is None:
        return ZERO
    days_left = (subscription.expires_at - timezone.now()).days
    if days_left >= 30:
        ratio = Decimal(1)
    elif days_left <= 0:
        ratio = Decimal("0.4")
    else:
        ratio = Decimal(days_left) / Decimal(30)
    return _quantize(WEIGHT_SUBSCRIPTION * ratio)


def _vehicle_component(trip: DriverTrip) -> Decimal:
    """Verified, active, comfortable vehicles score higher."""
    vehicle = trip.vehicle
    score = ZERO
    if conf.require_verified_vehicle_to_drive() and vehicle.is_verified:
        score += WEIGHT_VEHICLE * Decimal("0.6")
    if vehicle.is_active:
        score += WEIGHT_VEHICLE * Decimal("0.2")
    # Comfortable cars (more seats per row) get the remaining 20%.
    comfort = Decimal(min(vehicle.seats_for_passengers, 4)) / Decimal(4)
    score += WEIGHT_VEHICLE * Decimal("0.2") * comfort
    return _quantize(min(score, WEIGHT_VEHICLE))


# ---------------------------------------------------------------------------
# Hard filters
# ---------------------------------------------------------------------------
#: How the route rule reached its verdict for a pair. Sent to the UI so a
#: screen can tell a measured geographic match apart from a legacy
#: identity-only one and never present the latter as a 25 km measurement.
ROUTE_BASIS_COORDINATES = "coordinates"
ROUTE_BASIS_ROUTE_IDENTITY = "route_identity"
ROUTE_BASIS_INCOMPARABLE = "incomparable"


def route_match_basis(trip: DriverTrip, request: PassengerRequest) -> str:
    """Which rule judged this pair's route, as one of the ``ROUTE_BASIS_*`` names.

    ``"coordinates"``
        All four endpoints were known, so the great-circle rule decided.
    ``"route_identity"``
        At least one row carries no coordinates (anything written before the
        endpoint snapshots existed), so the pre-geocoding catalogue / city pair
        decided. The pair can be shown, but **no** kilometre figure exists for
        it and the API must not invent one.
    ``"incomparable"``
        Neither rule can judge the pair, so it is never shown.
    """
    measured = compatibility.route_compatibility(trip, request)
    if measured.reason != "missing_coordinates":
        return ROUTE_BASIS_COORDINATES
    if _same_route_identity(trip, request) or _same_route_identity(request, trip):
        return ROUTE_BASIS_ROUTE_IDENTITY
    return ROUTE_BASIS_INCOMPARABLE


def route_exclusion_reason(trip: DriverTrip, request: PassengerRequest) -> str:
    """Why these two routes cannot be served together, or ``""``.

    The geographic rule (same direction, every corresponding point within
    ``MATCHING_MAX_ROUTE_DISTANCE_KM``) decides whenever all four points are
    known. Rows that carry no coordinates fall back to the catalogue / city
    identity, which is the rule the platform used before coordinates were
    compared: never a guess, and never a place-name comparison of two free-text
    values. :func:`route_match_basis` reports which of the two fired.
    """
    measured = compatibility.route_compatibility(trip, request)
    if measured.reason != "missing_coordinates":
        return "" if measured.compatible else measured.reason
    if route_match_basis(trip, request) == ROUTE_BASIS_ROUTE_IDENTITY:
        return ""
    return "route_not_comparable"


def _same_route_identity(left, right) -> bool:
    """The pre-geocoding route rule: same catalogue pair, else same city pair."""
    if left.from_location_id and left.to_location_id:
        return (left.from_location_id, left.to_location_id) == (
            right.from_location_id,
            right.to_location_id,
        )
    if left.from_city_name and left.to_city_name:
        return (left.from_city_name, left.to_city_name) == (
            right.from_city_name,
            right.to_city_name,
        )
    return False


def exclusion_reason(trip: DriverTrip, request: PassengerRequest) -> str:
    """Return a machine readable reason why this pair must not be shown.

    The four criteria of the "suitable trips" screen, in order: the routes
    must fit together geographically, the departure must be within the time
    tolerance of the requested window, the party must fit into the free
    seats, and the trip must still be bookable and inside the budget.
    """
    if not trip.accepts_new_orders:
        return "trip_not_bookable"
    if trip.available_seats < request.passenger_count:
        return "not_enough_seats"
    route_reason = route_exclusion_reason(trip, request)
    if route_reason:
        return route_reason
    if not compatibility.time_is_compatible(trip.departure_time, request):
        return "outside_departure_window"
    if request.max_price_per_seat is not None and trip.price_per_seat > request.max_price_per_seat:
        return "above_budget"
    if conf.require_verified_driver_to_drive() and not trip.driver.is_verified:
        return "driver_not_verified"
    if conf.require_verified_vehicle_to_drive() and not (trip.vehicle.is_verified and trip.vehicle.is_active):
        return "vehicle_not_verified"
    if conf.require_active_subscription_to_drive() and not _has_active_subscription(trip):
        return "no_active_subscription"
    if trip.driver.user_id == request.passenger_id:
        return "own_trip"
    if trip.orders.filter(passenger=request.passenger).exists():
        return "already_ordered"
    return ""


def _has_active_subscription(trip: DriverTrip) -> bool:
    return (
        trip.driver.subscriptions.filter(
            status=DriverSubscriptionStatus.ACTIVE, expires_at__gt=timezone.now()
        ).exists()
    )


def score_trip_for_request(trip: DriverTrip, request: PassengerRequest) -> MatchScore:
    """Score one pair. Pure function: no writes, no hidden state."""
    excluded = exclusion_reason(trip, request)
    if excluded:
        return MatchScore(
            total=ZERO,
            time_score=ZERO,
            price_score=ZERO,
            rating_score=ZERO,
            subscription_score=ZERO,
            vehicle_score=ZERO,
            minutes_difference=0,
            price_difference=ZERO,
            excluded=excluded,
        )

    time_score, minutes = _time_component(trip, request)
    price_score, price_difference = _price_component(trip, request)
    rating_score = _rating_component(trip)
    subscription_score = _subscription_component(trip)
    vehicle_score = _vehicle_component(trip)

    total = time_score + price_score + rating_score + subscription_score + vehicle_score
    total = min(total, MAX_SCORE)

    score = MatchScore(
        total=_quantize(total),
        time_score=time_score,
        price_score=price_score,
        rating_score=rating_score,
        subscription_score=subscription_score,
        vehicle_score=vehicle_score,
        minutes_difference=minutes,
        price_difference=_quantize(price_difference),
    )
    score.reasons = _explain(score)
    return score


def _explain(score: MatchScore) -> list[str]:
    reasons: list[str] = []
    if score.time_score >= WEIGHT_TIME * Decimal("0.7"):
        reasons.append("Chuqish vaqti yaqin")
    if score.price_score >= WEIGHT_PRICE * Decimal("0.7"):
        reasons.append("Narx qulay")
    if score.rating_score >= WEIGHT_RATING * Decimal("0.6"):
        reasons.append("Yuqori reyting")
    if score.subscription_score > 0:
        reasons.append("Faol obuna")
    if score.vehicle_score >= WEIGHT_VEHICLE * Decimal("0.6"):
        reasons.append("Ishonchli avtomobil")
    return reasons[:2]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def _time_tolerance() -> timedelta:
    """Query padding around the configured time tolerance.

    The hard filter floors a difference to whole minutes, so a pair that sits
    60.9 minutes apart passes it; the query must fetch that pair instead of
    cutting it off a fraction early. The exact decision is always
    :func:`compatibility.time_difference_minutes`.
    """
    return timedelta(minutes=conf.MATCHING_TIME_TOLERANCE_MINUTES + 1)


def get_candidate_trips(request: PassengerRequest) -> list[DriverTrip]:
    """Hard-filtered candidate set, cheapest-first only for readability.

    The query only narrows the search (route bounding box, seat count, padded
    departure window); every survivor is then run through
    :func:`exclusion_reason`, which is the rule the API and the tests trust.
    """
    origin, destination = compatibility.route_points(request)
    tolerance = _time_tolerance()
    queryset = ride_selectors.get_trip_candidates_for_matching(
        origin=origin,
        destination=destination,
        seats=request.passenger_count,
        window_start=request.departure_from - tolerance,
        window_end=request.departure_until + tolerance,
        fallback_route_filter=ride_selectors.build_route_filter(
            from_location_id=request.from_location_id,
            to_location_id=request.to_location_id,
            from_city_name=request.from_city_name,
            to_city_name=request.to_city_name,
        ),
    )
    candidates = list(queryset.order_by("departure_time", "price_per_seat", "pk"))
    return [trip for trip in candidates if exclusion_reason(trip, request) == ""]


def rank_trips_for_request(request: PassengerRequest) -> list[tuple[DriverTrip, MatchScore]]:
    """Deterministic ranking of every candidate trip for one request."""
    scored: list[tuple[DriverTrip, MatchScore]] = []
    for trip in get_candidate_trips(request):
        score = score_trip_for_request(trip, request)
        if score.is_match:
            scored.append((trip, score))
    return sorted(scored, key=lambda item: _sort_key(item[0], item[1]))


def _sort_key(trip: DriverTrip, score: MatchScore) -> tuple:
    """Score desc, departure asc, price asc, rating desc, id asc.

    The last element (``pk``) makes the order total, so two runs with equal
    data always return the same list.
    """
    return (
        -score.total,
        trip.departure_time,
        trip.price_per_seat,
        -Decimal(str(trip.driver.rating or 0)),
        trip.pk,
    )


def get_candidate_requests(trip: DriverTrip) -> list[PassengerRequest]:
    """Passenger requests one trip could serve, hard-filtered.

    The mirror of :func:`get_candidate_trips`: route geometry, seat capacity
    and the padded departure window narrow the query, and every survivor is
    judged by :func:`exclusion_reason` before it can reach the UI.
    """
    origin, destination = compatibility.route_points(trip)
    tolerance = _time_tolerance()
    queryset = ride_selectors.get_request_candidates_for_matching(
        origin=origin,
        destination=destination,
        seats=trip.available_seats,
        window_start=trip.departure_time - tolerance,
        window_end=trip.departure_time + tolerance,
        fallback_route_filter=ride_selectors.build_route_filter(
            from_location_id=trip.from_location_id,
            to_location_id=trip.to_location_id,
            from_city_name=trip.from_city_name,
            to_city_name=trip.to_city_name,
        ),
    )
    candidates = list(queryset.order_by("departure_from", "pk"))
    return [passenger_request for passenger_request in candidates if exclusion_reason(trip, passenger_request) == ""]


def rank_requests_for_trip(trip: DriverTrip) -> list[tuple[PassengerRequest, MatchScore]]:
    """Deterministic ranking of every candidate request for one trip.

    Same scorer, same weights and the same tie-break rules as
    :func:`rank_trips_for_request` - only the direction changes, so a pair
    scores identically whether the driver or the passenger asks about it.
    """
    scored: list[tuple[PassengerRequest, MatchScore]] = []
    for passenger_request in get_candidate_requests(trip):
        score = score_trip_for_request(trip, passenger_request)
        if score.is_match:
            scored.append((passenger_request, score))
    return sorted(scored, key=lambda item: _request_sort_key(item[0], item[1]))


def _request_sort_key(passenger_request: PassengerRequest, score: MatchScore) -> tuple:
    """Score desc, window start asc, id asc - a total order, always reproducible."""
    return (-score.total, passenger_request.departure_from, passenger_request.pk)


@transaction.atomic
def refresh_matches_for_request(
    request: PassengerRequest, *, reason: str = MatchReason.NEW_MATCH
) -> list[TripMatch]:
    """Recompute and persist the ranking of one passenger request (idempotent)."""
    ranked = rank_trips_for_request(request)
    existing = {match.trip_id: match for match in request.matches.select_for_update()}

    persisted: list[TripMatch] = []
    for rank, (trip, score) in enumerate(ranked, start=1):
        match = existing.get(trip.pk)
        if match is None:
            match = TripMatch(request=request, trip=trip)
        elif match.score != score.total:
            match.reason = MatchReason.RESCORE
        match.score = score.total
        match.time_score = score.time_score
        match.price_score = score.price_score
        match.rating_score = score.rating_score
        match.subscription_score = score.subscription_score
        match.vehicle_score = score.vehicle_score
        match.minutes_difference = score.minutes_difference
        match.price_difference = score.price_difference
        match.rank = rank
        match.save()
        persisted.append(match)

    # Stale matches (trip no longer eligible) are removed instead of kept as
    # stale rows, otherwise a driver would see an unbookable trip.
    # NOTE: ``existing`` is keyed by *trip id* while ``persisted`` holds model
    # instances - the stale set must be built from ``match.pk``, never from the
    # dict key, otherwise a match of one trip can delete the match of another.
    keep_pks = {match.pk for match in persisted}
    stale_pks = [match.pk for match in existing.values() if match.pk not in keep_pks]
    if stale_pks:
        TripMatch.objects.filter(pk__in=stale_pks).delete()

    logger.info("So'rov #%s uchun %d ta moslik yangilandi", request.pk, len(persisted))
    return persisted


@transaction.atomic
def refresh_matches_for_trip(trip: DriverTrip, *, reason: str = MatchReason.NEW_MATCH) -> list[TripMatch]:
    """Recompute the ranking of the trip against every active request.

    The candidate query is :func:`get_candidate_trips` seen from the other
    side: the route bounding box (plus the catalogue identity for rows
    without coordinates), the departure window padded by the time tolerance
    around *the trip's* departure, and a party that fits into the free seats.
    Each surviving request is then judged pair by pair, so a request can only
    appear here when :func:`exclusion_reason` has nothing to object to.
    """
    origin, destination = compatibility.route_points(trip)
    tolerance = _time_tolerance()
    requests = (
        ride_selectors.get_request_candidates_for_matching(
            origin=origin,
            destination=destination,
            seats=trip.available_seats,
            window_start=trip.departure_time - tolerance,
            window_end=trip.departure_time + tolerance,
            fallback_route_filter=ride_selectors.build_route_filter(
                from_location_id=trip.from_location_id,
                to_location_id=trip.to_location_id,
                from_city_name=trip.from_city_name,
                to_city_name=trip.to_city_name,
            ),
        )
        # A total order, so two runs against the same rows produce the same
        # ranking even when their departure windows are identical.
        .order_by("departure_from", "pk")
    )

    all_matches: list[TripMatch] = []
    for request in requests.distinct():
        # ``refresh_matches_for_request`` re-ranks *all* trips of the request,
        # which is what we want for consistency, but the caller of this
        # function only cares about ``trip`` itself.
        all_matches.extend(
            match
            for match in refresh_matches_for_request(request, reason=reason)
            if match.trip_id == trip.pk
        )

    # Rank the trip's own matches (best request first).
    request_ids = [match.request_id for match in all_matches]
    existing = {match.request_id: match for match in trip.matches.select_for_update()}
    ordered = sorted(
        all_matches, key=lambda match: (-match.score, match.request_id)
    )
    for rank, match in enumerate(ordered, start=1):
        stored = existing.get(match.request_id)
        if stored is not None:
            stored.score = match.score
            stored.rank = rank
            stored.reason = MatchReason.RESCORE
            stored.save(update_fields=["score", "rank", "reason", "updated_at"])
            all_matches[all_matches.index(match)] = stored
    for request_id in existing:
        if request_id not in request_ids:
            existing[request_id].delete()
    return all_matches


def get_ranked_matches(request: PassengerRequest) -> list[TripMatch]:
    """Persisted ranking (falls back to a live ranking when nothing is stored)."""
    matches = list(get_best_matches_for_request(request))
    if matches:
        return matches
    return refresh_matches_for_request(request)


def _live_match(
    passenger_request: PassengerRequest, trip: DriverTrip, score: MatchScore, rank: int
) -> TripMatch:
    """A ranking row that is **not** written to the database.

    Same shape as a persisted :class:`TripMatch`, so the API serialises one
    payload either way; it simply has no primary key until somebody asks for
    the ranking to be stored (``refresh_matches_for_trip``).
    """
    return TripMatch(
        request=passenger_request,
        trip=trip,
        score=score.total,
        time_score=score.time_score,
        price_score=score.price_score,
        rating_score=score.rating_score,
        subscription_score=score.subscription_score,
        vehicle_score=score.vehicle_score,
        minutes_difference=score.minutes_difference,
        price_difference=score.price_difference,
        rank=rank,
    )


def get_ranked_matches_for_trip(trip: DriverTrip) -> list[TripMatch]:
    """Live ranking of one trip against every compatible passenger request.

    The driver's "suitable trips" screen reads this on every open. It is
    deliberately read-only: a page load must not rewrite rows, and in
    particular must not overwrite the request-side ``rank`` of matches the
    passenger side still orders by. The ranking is a pure function of the
    stored trips and requests, so recomputing it always yields the same list.
    """
    return [
        _live_match(passenger_request, trip, score, rank)
        for rank, (passenger_request, score) in enumerate(rank_requests_for_trip(trip), start=1)
    ]


@dataclass(frozen=True)
class SuitableTripRequests:
    """One driver trip together with the passengers that fit it.

    ``results`` is already ranked by the backend and already hard-filtered, so a
    consumer renders it as-is and never re-sorts or re-checks it.
    """

    trip: DriverTrip
    results: list[TripMatch]


def get_suitable_requests_by_trip(
    driver, *, max_results: int | None = None
) -> list[SuitableTripRequests]:
    """Every bookable trip of one driver with the passengers that fit it.

    This is the whole driver-side answer in one call: the screen asks "which
    passengers suit my trips?" and must not have to name a trip first, so no
    trip is ever picked for the driver. Each group is produced by
    :func:`get_ranked_matches_for_trip`, so the order inside a group is the
    backend ranking - the frontend renders it, it never re-sorts it.

    Trips whose ranking is empty are left out entirely: a trip with no
    suitable passenger has nothing to show. Trips are ordered by departure,
    then by id, so two reads against the same rows return the same groups.
    """
    limit = conf.MATCHING_MAX_RESULTS if max_results is None else max_results
    grouped: list[SuitableTripRequests] = []
    trips = ride_selectors.get_trips_by_driver(driver).bookable().order_by("departure_time", "pk")
    for trip in trips:
        matches = get_ranked_matches_for_trip(trip)
        if matches:
            grouped.append(SuitableTripRequests(trip=trip, results=matches[:limit]))
    return grouped


def refresh_all_active_matches() -> dict:
    """Used by the periodic Celery task; safe to run repeatedly."""
    requests = ride_selectors.get_matchable_requests().filter(
        departure_until__gte=timezone.now() + timedelta(minutes=conf.TRIP_DEPARTURE_GRACE_MINUTES)
    )
    total = 0
    for request in requests:
        total += len(refresh_matches_for_request(request, reason=MatchReason.RESCORE))
    return {"requests": requests.count(), "matches": total}


def get_required_request(request_id: int) -> PassengerRequest:
    passenger_request = ride_selectors.get_request_by_id(request_id)
    if passenger_request is None:
        raise ResourceNotFound("Yo'lovchi so'rovi topilmadi.")
    return passenger_request



@transaction.atomic
def match_passenger_request_to_trip(passenger_request: PassengerRequest, trips: DriverTrip) -> TripMatch:
    """Create a match between a passenger request and a driver trip."""
    matches = []
    for trip in trips:
        if trip.driver.user_id == passenger_request.passenger_id:
            raise ValueError(f"Cannot match request {passenger_request.pk} to trip {trip.pk}: own trip")
        
        score = score_trip_for_request(trip, passenger_request)
        if not score.is_match:
            # raise ValueError(f"Cannot match request {passenger_request.pk} to trip {trip.pk}: {score.excluded}")
            continue  # Skip this trip if it doesn't match
        match = TripMatch(
            request=passenger_request,
            trip=trip,
            score=score.total,
            time_score=score.time_score,
            price_score=score.price_score,
            rating_score=score.rating_score,
            subscription_score=score.subscription_score,
            vehicle_score=score.vehicle_score,
            minutes_difference=score.minutes_difference,
            price_difference=score.price_difference,
            rank=1,  # Initial rank; will be updated in refresh_matches_for_request
        )
        match.save()
        matches.append(match)
    if not matches:
        raise ValueError(f"No suitable trips found for request {passenger_request.pk}")
    return match

__all__ = [
    "MAX_SCORE",
    "ROUTE_BASIS_COORDINATES",
    "ROUTE_BASIS_INCOMPARABLE",
    "ROUTE_BASIS_ROUTE_IDENTITY",
    "MatchScore",
    "SuitableTripRequests",
    "exclusion_reason",
    "get_candidate_requests",
    "get_candidate_trips",
    "get_ranked_matches",
    "get_ranked_matches_for_trip",
    "get_required_request",
    "get_suitable_requests_by_trip",
    "match_passenger_request_to_trip",
    "rank_requests_for_trip",
    "rank_trips_for_request",
    "refresh_all_active_matches",
    "refresh_matches_for_request",
    "refresh_matches_for_trip",
    "route_exclusion_reason",
    "route_match_basis",
    "score_trip_for_request",
]
