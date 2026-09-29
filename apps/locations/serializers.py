"""Serializers for the locations app (read-only catalogue)."""

from __future__ import annotations

from rest_framework import serializers

from apps.locations.models import District, Location, Region


class RegionSerializer(serializers.ModelSerializer):
    districts_count = serializers.IntegerField(read_only=True, required=False)

    class Meta:
        model = Region
        fields = ("id", "name", "code", "is_active", "districts_count", "created_at", "updated_at")
        read_only_fields = ("id", "districts_count", "created_at", "updated_at")


class DistrictSerializer(serializers.ModelSerializer):
    region_name = serializers.CharField(source="region.name", read_only=True)
    full_name = serializers.CharField(read_only=True)

    class Meta:
        model = District
        fields = (
            "id",
            "region",
            "region_name",
            "name",
            "full_name",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "region_name", "full_name", "created_at", "updated_at")


class LocationSerializer(serializers.ModelSerializer):
    district_name = serializers.CharField(source="district.name", read_only=True)
    region_name = serializers.CharField(source="district.region.name", read_only=True)
    full_name = serializers.CharField(read_only=True)

    class Meta:
        model = Location
        fields = (
            "id",
            "district",
            "district_name",
            "region_name",
            "name",
            "full_name",
            "address",
            "latitude",
            "longitude",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "district_name", "region_name", "full_name", "created_at", "updated_at")


class LocationWriteSerializer(serializers.ModelSerializer):
    """Admin/API payload for creating a location."""

    latitude = serializers.DecimalField(max_digits=9, decimal_places=6, coerce_to_string=False)
    longitude = serializers.DecimalField(max_digits=9, decimal_places=6, coerce_to_string=False)

    class Meta:
        model = Location
        fields = ("district", "name", "address", "latitude", "longitude", "is_active")
        extra_kwargs = {
            "district": {"required": True},
            "name": {"required": True},
            "address": {"required": False, "allow_blank": True},
            "is_active": {"required": False, "default": True},
        }

    def validate_latitude(self, value):
        from apps.core.validators import validate_latitude

        validate_latitude(value)
        return value

    def validate_longitude(self, value):
        from apps.core.validators import validate_longitude

        validate_longitude(value)
        return value


class ResolvedPlaceSerializer(serializers.Serializer):
    """One 2GIS result, ready for the client to store as a trip endpoint.

    The field names mirror the trip snapshot columns (``address``,
    ``region_name``, ``city_name``, ``district_name``) so a client can forward
    the block straight into the ``origin`` / ``destination`` write payload.
    """

    place_id = serializers.CharField(read_only=True)
    display_name = serializers.CharField(read_only=True)
    short_name = serializers.CharField(read_only=True)
    full_address = serializers.CharField(read_only=True)
    address = serializers.CharField(read_only=True)
    latitude = serializers.DecimalField(
        max_digits=9, decimal_places=6, read_only=True, coerce_to_string=False
    )
    longitude = serializers.DecimalField(
        max_digits=9, decimal_places=6, read_only=True, coerce_to_string=False
    )
    region_name = serializers.CharField(read_only=True)
    city_name = serializers.CharField(read_only=True)
    district_name = serializers.CharField(read_only=True)
    district_area_name = serializers.CharField(read_only=True)
    living_area_name = serializers.CharField(read_only=True)
