"""Serializers for the matching app.

One row is read in both directions (a passenger reading trips, a driver
reading requests), so the payload carries *both* halves of the pair plus the
measurements the UI is required to show: how far the routes differ, how far
the departure sits from the requested window, and how many seats are on each
side of the bargain.

The measurements are derived from the stored coordinates and clocks by
:mod:`apps.matching.compatibility` instead of being copied into new columns -
they cannot drift away from the data they describe, and two reads of the same
rows always return the same numbers.
"""

from __future__ import annotations

from rest_framework import serializers

from apps.matching import compatibility
from apps.matching import services as matching_services
from apps.matching.models import TripMatch


class TripMatchSerializer(serializers.ModelSerializer):
    trip_id = serializers.IntegerField(read_only=True)
    request_id = serializers.IntegerField(read_only=True)
    route = serializers.CharField(source="trip.route_label", read_only=True)
    departure_time = serializers.DateTimeField(source="trip.departure_time", read_only=True)
    price_per_seat = serializers.DecimalField(
        source="trip.price_per_seat", max_digits=12, decimal_places=2, read_only=True
    )
    available_seats = serializers.IntegerField(source="trip.available_seats", read_only=True)
    driver_name = serializers.CharField(source="trip.driver.user.display_name", read_only=True)
    driver_rating = serializers.DecimalField(
        source="trip.driver.rating", max_digits=3, decimal_places=2, read_only=True
    )
    # ``Vehicle`` has no ``name`` column - only ``brand``/``model``/``plate_number``
    # and the ``display_name`` property. Pointing ``source`` at a missing
    # attribute does not raise here: a ``read_only`` field is not ``required``, so
    # DRF skipped it and ``vehicle_name`` was quietly absent from every payload.
    vehicle_name = serializers.CharField(source="trip.vehicle.display_name", read_only=True)
    plate_number = serializers.CharField(source="trip.vehicle.plate_number", read_only=True)
    # -- the passenger half of the pair ------------------------------------
    passenger_name = serializers.CharField(source="request.passenger.display_name", read_only=True)
    passenger_username = serializers.CharField(source="request.passenger.username", read_only=True)
    pickup_location = serializers.CharField(source="request.origin_display", read_only=True)
    dropoff_location = serializers.CharField(source="request.destination_display", read_only=True)
    required_seats = serializers.IntegerField(source="request.passenger_count", read_only=True)
    departure_from = serializers.DateTimeField(source="request.departure_from", read_only=True)
    departure_until = serializers.DateTimeField(source="request.departure_until", read_only=True)
    # -- how well the two halves fit together ------------------------------
    pickup_offset_km = serializers.SerializerMethodField()
    dropoff_offset_km = serializers.SerializerMethodField()
    distance_difference_km = serializers.SerializerMethodField()
    route_deviation_km = serializers.SerializerMethodField()
    time_difference_minutes = serializers.SerializerMethodField()
    route_compatible = serializers.SerializerMethodField()
    route_status = serializers.SerializerMethodField()
    route_match_basis = serializers.SerializerMethodField()
    reasons = serializers.SerializerMethodField()
    components = serializers.SerializerMethodField()

    class Meta:
        model = TripMatch
        fields = (
            "id",
            "trip_id",
            "request_id",
            "route",
            "pickup_location",
            "dropoff_location",
            "departure_time",
            "departure_from",
            "departure_until",
            "price_per_seat",
            "available_seats",
            "required_seats",
            "distance_difference_km",
            "pickup_offset_km",
            "dropoff_offset_km",
            "route_deviation_km",
            "time_difference_minutes",
            "route_compatible",
            "route_status",
            "route_match_basis",
            "driver_name",
            "driver_rating",
            "passenger_name",
            "passenger_username",
            "vehicle_name",
            "plate_number",
            "score",
            "rank",
            "components",
            "reasons",
            "created_at",
        )
        read_only_fields = fields

    # -- compatibility measurements ----------------------------------------
    def _measured(self, obj: TripMatch) -> compatibility.RouteCompatibility:
        """Measure one pair once per serializer, however many fields ask."""
        cache = getattr(self, "_compatibility_cache", None)
        if cache is None:
            cache = {}
            self._compatibility_cache = cache
        key = (obj.trip_id, obj.request_id)
        if key not in cache:
            cache[key] = compatibility.route_compatibility(obj.trip, obj.request)
        return cache[key]

    def get_pickup_offset_km(self, obj: TripMatch) -> float | None:
        return _kilometres(self._measured(obj).pickup_km)

    def get_dropoff_offset_km(self, obj: TripMatch) -> float | None:
        return _kilometres(self._measured(obj).dropoff_km)

    def get_distance_difference_km(self, obj: TripMatch) -> float | None:
        return _kilometres(self._measured(obj).distance_difference_km)

    def get_route_deviation_km(self, obj: TripMatch) -> float | None:
        return _kilometres(self._measured(obj).detour_km)

    def get_time_difference_minutes(self, obj: TripMatch) -> int:
        return compatibility.time_difference_minutes(obj.trip.departure_time, obj.request)

    def get_route_compatible(self, obj: TripMatch) -> bool:
        return matching_services.route_exclusion_reason(obj.trip, obj.request) == ""

    def get_route_status(self, obj: TripMatch) -> str:
        """``""`` when the routes fit, otherwise the machine readable reason."""
        return matching_services.route_exclusion_reason(obj.trip, obj.request)

    def get_route_match_basis(self, obj: TripMatch) -> str:
        """Which rule judged the route: measured coordinates or legacy identity.

        A ``route_identity`` row was matched on the catalogue / city pair
        because its coordinates do not exist, so its distance fields are
        ``None`` and the UI must show them as unknown rather than as a measured
        value inside the 25 km limit.
        """
        return matching_services.route_match_basis(obj.trip, obj.request)

    def get_reasons(self, obj: TripMatch) -> list[str]:
        return obj.top_reasons()

    def get_components(self, obj: TripMatch) -> dict:
        return {key: str(value) for key, value in obj.components.items()}


def _kilometres(value) -> float | None:
    """Two-decimal JSON number, or ``None`` when the distance is unknown."""
    if value is None:
        return None
    return float(value)


class MatchRequestSerializer(serializers.Serializer):
    """Input of ``POST /matching/requests/<id>/refresh/``."""

    refresh = serializers.BooleanField(required=False, default=True)


class RankedTripsResponseSerializer(serializers.Serializer):
    """Envelope of the ranked-trips endpoint (driver side answer)."""

    request_id = serializers.IntegerField()
    max_score = serializers.DecimalField(max_digits=8, decimal_places=2, read_only=True)
    results = TripMatchSerializer(many=True, read_only=True)


class RankedRequestsResponseSerializer(serializers.Serializer):
    """Envelope of the ranked-requests endpoint (passenger side answer)."""

    trip_id = serializers.IntegerField()
    max_score = serializers.DecimalField(max_digits=8, decimal_places=2, read_only=True)
    results = TripMatchSerializer(many=True, read_only=True)


class SuitableTripRequestsSerializer(serializers.Serializer):
    """One driver trip with the passengers that fit it, backend order.

    ``results`` is :func:`apps.matching.services.get_ranked_matches_for_trip`
    verbatim - already ordered by the backend ranking and already hard-filtered,
    so the screen has nothing left to decide. Every measurement a row carries is
    the value the matcher measured; nothing here is recomputed.
    """

    trip_id = serializers.IntegerField(source="trip.pk")
    route = serializers.CharField(source="trip.route_label")
    departure_time = serializers.DateTimeField(source="trip.departure_time")
    available_seats = serializers.IntegerField(source="trip.available_seats")
    total_seats = serializers.IntegerField(source="trip.total_seats")
    vehicle_name = serializers.CharField(source="trip.vehicle.display_name", read_only=True)
    plate_number = serializers.CharField(source="trip.vehicle.plate_number", read_only=True)
    results = TripMatchSerializer(many=True)


class DriverSuitableRequestsResponseSerializer(serializers.Serializer):
    """Envelope of the driver's "suitable passengers" screen feed.

    ``trips`` holds only the trips that actually have a match, so an empty list
    means "this driver has no suitable passenger at the moment" and not "the
    first trip was wrong".
    """

    max_score = serializers.DecimalField(max_digits=8, decimal_places=2, read_only=True)
    trips = SuitableTripRequestsSerializer(many=True)


class RefreshMatchesResponseSerializer(serializers.Serializer):
    """Result of a forced rescore."""

    refreshed = serializers.IntegerField(help_text="Yangilangan mosliklar soni.")


class MatchingWeightsSerializer(serializers.Serializer):
    """The scoring weights, exposed so the UI can explain a ranking."""

    time = serializers.DecimalField(max_digits=5, decimal_places=2, read_only=True)
    price = serializers.DecimalField(max_digits=5, decimal_places=2, read_only=True)
    rating = serializers.DecimalField(max_digits=5, decimal_places=2, read_only=True)
    subscription = serializers.DecimalField(max_digits=5, decimal_places=2, read_only=True)
    vehicle = serializers.DecimalField(max_digits=5, decimal_places=2, read_only=True)
    max_score = serializers.DecimalField(max_digits=8, decimal_places=2, read_only=True)
