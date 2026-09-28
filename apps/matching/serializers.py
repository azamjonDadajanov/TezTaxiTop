"""Serializers for the matching app."""

from __future__ import annotations

from rest_framework import serializers

from apps.matching.models import TripMatch


class TripMatchSerializer(serializers.ModelSerializer):
    trip_id = serializers.IntegerField(read_only=True)
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
    vehicle_name = serializers.CharField(source="trip.vehicle.name", read_only=True)
    plate_number = serializers.CharField(source="trip.vehicle.plate_number", read_only=True)
    reasons = serializers.SerializerMethodField()
    components = serializers.SerializerMethodField()

    class Meta:
        model = TripMatch
        fields = (
            "id",
            "trip_id",
            "route",
            "departure_time",
            "price_per_seat",
            "available_seats",
            "driver_name",
            "driver_rating",
            "vehicle_name",
            "plate_number",
            "score",
            "rank",
            "components",
            "reasons",
            "created_at",
        )
        read_only_fields = fields

    def get_reasons(self, obj: TripMatch) -> list[str]:
        return obj.top_reasons()

    def get_components(self, obj: TripMatch) -> dict:
        return {key: str(value) for key, value in obj.components.items()}


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
