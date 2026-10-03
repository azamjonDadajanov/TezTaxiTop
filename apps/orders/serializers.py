"""Serializers for the orders app."""

from __future__ import annotations

from rest_framework import serializers

from apps.orders.models import Order, OrderPassenger, OrderStatus


class OrderPassengerSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderPassenger
        fields = ("id", "first_name", "last_name", "phone_number", "created_at")
        read_only_fields = ("id", "created_at")


class OrderSerializer(serializers.ModelSerializer):
    """Full read representation of an order."""

    status_display = serializers.CharField(source="get_status_display", read_only=True)
    trip_route = serializers.CharField(source="trip.route_label", read_only=True)
    departure_time = serializers.DateTimeField(source="trip.departure_time", read_only=True)
    driver_name = serializers.CharField(source="trip.driver.user.display_name", read_only=True)
    driver_phone = serializers.CharField(source="trip.driver.user.phone_number", read_only=True)
    driver_rating = serializers.DecimalField(
        source="trip.driver.rating", max_digits=3, decimal_places=2, read_only=True, coerce_to_string=False
    )
    vehicle_plate_number = serializers.CharField(source="trip.vehicle.plate_number", read_only=True)
    passenger_name = serializers.CharField(source="passenger.display_name", read_only=True)
    passenger_phone = serializers.CharField(source="passenger.phone_number", read_only=True)
    companions = OrderPassengerSerializer(source="passengers", many=True, read_only=True)
    can_cancel = serializers.BooleanField(read_only=True)
    is_reviewable = serializers.BooleanField(read_only=True)

    class Meta:
        model = Order
        fields = (
            "id",
            "trip",
            "trip_route",
            "departure_time",
            "passenger",
            "passenger_name",
            "passenger_phone",
            "driver_name",
            "driver_phone",
            "driver_rating",
            "vehicle_plate_number",
            "seats_booked",
            "price_per_seat",
            "total_amount",
            "status",
            "status_display",
            "passenger_note",
            "cancellation_reason",
            "accepted_at",
            "cancelled_at",
            "completed_at",
            "companions",
            "can_cancel",
            "is_reviewable",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class OrderCreateSerializer(serializers.Serializer):
    """Payload of ``POST /api/v1/orders/orders/`` or booking."""

    trip = serializers.IntegerField(required=False, allow_null=True)
    request = serializers.IntegerField(required=False, allow_null=True)
    request_id = serializers.IntegerField(required=False, allow_null=True)
    seats_booked = serializers.IntegerField(min_value=1, max_value=8, required=False, default=1)
    passenger_note = serializers.CharField(
        required=False, allow_blank=True, max_length=500
    )
    companion = OrderPassengerSerializer(required=False, allow_null=True)

    def validate(self, attrs):
        trip_id = attrs.get("trip")
        req_id = attrs.get("request") or attrs.get("request_id")
        if trip_id is None and req_id is None:
            raise serializers.ValidationError("Yo'lov (trip) yoki so'rov (request) ko'rsatilishi shart.")
        if trip_id is not None:
            from apps.rides.selectors import get_trip_by_id

            if get_trip_by_id(trip_id) is None:
                raise serializers.ValidationError({"trip": "Yo'lov topilmadi."})
        if req_id is not None:
            from apps.rides.selectors import get_request_by_id

            if get_request_by_id(req_id) is None:
                raise serializers.ValidationError({"request": "So'rov topilmadi."})
        return attrs


class OrderPassengerCreateSerializer(serializers.Serializer):
    first_name = serializers.CharField(max_length=150)
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    phone_number = serializers.CharField(max_length=20, required=False, allow_blank=True)


class OrderCancelSerializer(serializers.Serializer):
    """Payload of the cancellation endpoints."""

    reason = serializers.CharField(required=False, allow_blank=True, max_length=500)


class OrderStatusUpdateSerializer(serializers.Serializer):
    """Explicit transition request (driver side)."""

    status = serializers.ChoiceField(
        choices=[
            OrderStatus.ACCEPTED,
            OrderStatus.REJECTED,
            OrderStatus.DRIVER_ARRIVED,
            OrderStatus.IN_PROGRESS,
            OrderStatus.COMPLETED,
            OrderStatus.NO_SHOW,
        ]
    )
    reason = serializers.CharField(required=False, allow_blank=True, max_length=500)
