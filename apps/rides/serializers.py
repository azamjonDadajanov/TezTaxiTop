"""Serializers for the rides app."""

from __future__ import annotations

from rest_framework import serializers

from apps.rides.models import DriverTrip, DriverTripStatus, PassengerRequest


class TripLocationSerializer(serializers.Serializer):
    """Compact location block embedded in trip responses."""

    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(read_only=True)
    district = serializers.CharField(source="district.name", read_only=True)
    region = serializers.CharField(source="district.region.name", read_only=True)
    latitude = serializers.DecimalField(max_digits=9, decimal_places=6, read_only=True, coerce_to_string=False)
    longitude = serializers.DecimalField(max_digits=9, decimal_places=6, read_only=True, coerce_to_string=False)


class DriverTripSerializer(serializers.ModelSerializer):
    """Full read representation of a trip."""

    driver_name = serializers.CharField(source="driver.user.display_name", read_only=True)
    driver_phone = serializers.CharField(source="driver.user.phone_number", read_only=True)
    driver_telegram_id = serializers.IntegerField(source="driver.user.telegram_id", read_only=True)
    driver_rating = serializers.DecimalField(
        source="driver.rating", max_digits=3, decimal_places=2, read_only=True, coerce_to_string=False
    )
    vehicle_plate_number = serializers.CharField(source="vehicle.plate_number", read_only=True)
    vehicle_brand = serializers.CharField(source="vehicle.brand", read_only=True)
    vehicle_model = serializers.CharField(source="vehicle.model", read_only=True)
    from_location_detail = TripLocationSerializer(source="from_location", read_only=True)
    to_location_detail = TripLocationSerializer(source="to_location", read_only=True)
    booked_seats = serializers.IntegerField(read_only=True)
    has_available_seats = serializers.BooleanField(read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = DriverTrip
        fields = (
            "id",
            "driver_name",
            "driver_phone",
            "driver_telegram_id",
            "driver_rating",
            "vehicle",
            "vehicle_plate_number",
            "vehicle_brand",
            "vehicle_model",
            "from_location",
            "to_location",
            "from_location_detail",
            "to_location_detail",
            "departure_time",
            "total_seats",
            "available_seats",
            "booked_seats",
            "has_available_seats",
            "price_per_seat",
            "comment",
            "status",
            "status_display",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class DriverTripWriteSerializer(serializers.ModelSerializer):
    """Payload used to create or update a trip.

    ``available_seats`` is intentionally read-only: it is maintained by the
    service layer through seat reservations.
    """

    class Meta:
        model = DriverTrip
        fields = (
            "vehicle",
            "from_location",
            "to_location",
            "departure_time",
            "total_seats",
            "price_per_seat",
            "comment",
        )
        extra_kwargs = {
            "vehicle": {"required": True},
            "from_location": {"required": True},
            "to_location": {"required": True},
            "departure_time": {"required": True},
            "total_seats": {"required": True, "min_value": 1},
            "price_per_seat": {"required": True, "min_value": 0},
            "comment": {"required": False, "allow_blank": True, "max_length": 500},
        }

    def validate(self, attrs):
        from_location = attrs.get("from_location")
        to_location = attrs.get("to_location")
        if from_location and to_location and from_location.pk == to_location.pk:
            raise serializers.ValidationError(
                {"to_location": "Qayerdan va qayerga bir xil bo'lishi mumkin emas."}
            )
        return attrs


class PassengerRequestSerializer(serializers.ModelSerializer):
    """Full read representation of a passenger request."""

    passenger_name = serializers.CharField(source="passenger.display_name", read_only=True)
    passenger_phone = serializers.CharField(source="passenger.phone_number", read_only=True)
    from_location_detail = TripLocationSerializer(source="from_location", read_only=True)
    to_location_detail = TripLocationSerializer(source="to_location", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = PassengerRequest
        fields = (
            "id",
            "passenger",
            "passenger_name",
            "passenger_phone",
            "from_location",
            "to_location",
            "from_location_detail",
            "to_location_detail",
            "passenger_count",
            "max_price_per_seat",
            "departure_from",
            "departure_until",
            "comment",
            "status",
            "status_display",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class PassengerRequestWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = PassengerRequest
        fields = (
            "from_location",
            "to_location",
            "passenger_count",
            "max_price_per_seat",
            "departure_from",
            "departure_until",
            "comment",
        )
        extra_kwargs = {
            "from_location": {"required": True},
            "to_location": {"required": True},
            "passenger_count": {"required": False, "default": 1, "min_value": 1},
            "max_price_per_seat": {"required": False, "allow_null": True, "min_value": 0},
            "departure_from": {"required": False},
            "departure_until": {"required": False},
            "comment": {"required": False, "allow_blank": True, "max_length": 500},
        }

    def validate(self, attrs):
        from_location = attrs.get("from_location")
        to_location = attrs.get("to_location")
        if from_location and to_location and from_location.pk == to_location.pk:
            raise serializers.ValidationError(
                {"to_location": "Qayerdan va qayerga bir xil bo'lishi mumkin emas."}
            )
        departure_from = attrs.get("departure_from")
        departure_until = attrs.get("departure_until")
        if departure_from and departure_until and departure_until <= departure_from:
            raise serializers.ValidationError(
                {"departure_until": "Chuqish oxirgi vaqti boshlangan vaqtdan katta bo'lishi shart."}
            )
        return attrs


class TripStatusUpdateSerializer(serializers.Serializer):
    """Administrative / driver driven status change."""

    status = serializers.ChoiceField(choices=DriverTripStatus.choices)
    reason = serializers.CharField(required=False, allow_blank=True, max_length=500)
