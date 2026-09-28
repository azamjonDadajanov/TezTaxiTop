"""Serializers for the vehicles app."""

from __future__ import annotations

from rest_framework import serializers

from apps.core.validators import validate_vehicle_year
from apps.vehicles.models import Vehicle


class VehicleSerializer(serializers.ModelSerializer):
    """Full representation, including the owner summary."""

    driver_id = serializers.IntegerField(read_only=True)
    driver_name = serializers.CharField(source="driver.user.display_name", read_only=True)
    driver_phone = serializers.CharField(source="driver.user.phone_number", read_only=True)
    seats_for_passengers = serializers.IntegerField(read_only=True)
    is_usable_for_trip = serializers.BooleanField(read_only=True)

    class Meta:
        model = Vehicle
        fields = (
            "id",
            "driver_id",
            "driver_name",
            "driver_phone",
            "brand",
            "model",
            "color",
            "plate_number",
            "year",
            "seats_count",
            "seats_for_passengers",
            "is_active",
            "is_verified",
            "verified_at",
            "is_usable_for_trip",
            "photo",
            "notes",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "driver_id",
            "driver_name",
            "driver_phone",
            "is_verified",
            "verified_at",
            "is_usable_for_trip",
            "seats_for_passengers",
            "created_at",
            "updated_at",
        )

    def validate_year(self, value: int) -> int:
        validate_vehicle_year(value)
        return value

    def validate_seats_count(self, value: int) -> int:
        if value < 1:
            raise serializers.ValidationError("Kamida 1 ta o'rindiq bo'lishi kerak.")
        return value


class VehicleWriteSerializer(serializers.ModelSerializer):
    """Payload used both for creation and for partial updates."""

    class Meta:
        model = Vehicle
        fields = ("brand", "model", "color", "plate_number", "year", "seats_count", "notes", "photo")
        extra_kwargs = {
            "brand": {"required": True},
            "model": {"required": True},
            "color": {"required": True},
            "plate_number": {"required": True},
            "year": {"required": True},
            "seats_count": {"required": False, "default": 4},
            "notes": {"required": False, "allow_blank": True},
            "photo": {"required": False, "allow_null": True},
        }

    def validate_year(self, value: int) -> int:
        validate_vehicle_year(value)
        return value
