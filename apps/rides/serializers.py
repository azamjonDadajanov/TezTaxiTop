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


class RouteEndpointSerializer(serializers.Serializer):
    """Unified view of one route endpoint.

    A trip endpoint is either a curated catalogue ``Location`` or a
    geocoded snapshot (or both, when a driver picked a catalogue place and the
    client also sent coordinates). The client only ever has to read this one
    block: ``id`` is ``null`` for map-picked endpoints and the ``latitude`` /
    ``longitude`` / ``*_name`` fields are always populated from the snapshot,
    so a passenger and a driver rendering the same trip always agree.
    """

    id = serializers.IntegerField(read_only=True, allow_null=True)
    display = serializers.CharField(read_only=True)
    name = serializers.CharField(read_only=True)
    address = serializers.CharField(read_only=True)
    latitude = serializers.DecimalField(max_digits=9, decimal_places=6, read_only=True, coerce_to_string=False)
    longitude = serializers.DecimalField(max_digits=9, decimal_places=6, read_only=True, coerce_to_string=False)
    region_name = serializers.CharField(read_only=True)
    city_name = serializers.CharField(read_only=True)
    district_name = serializers.CharField(read_only=True)
    is_catalogue_place = serializers.BooleanField(read_only=True)


class RouteEndpointMixinSerializer(serializers.Serializer):
    """Adds ``origin`` / ``destination`` to a trip or request representation."""

    origin = serializers.SerializerMethodField()
    destination = serializers.SerializerMethodField()

    def get_origin(self, obj) -> dict:
        return _endpoint_payload(obj, "from")

    def get_destination(self, obj) -> dict:
        return _endpoint_payload(obj, "to")


def _endpoint_payload(obj, prefix: str) -> dict:
    """Flatten ``from_*`` / ``to_*`` for the API, preferring catalogue data."""
    fk_id = getattr(obj, f"{prefix}_location_id", None)
    snapshot_address = getattr(obj, f"{prefix}_address", "") or ""
    snapshot_name = getattr(obj, f"{prefix}_place_name", "") or ""
    region_name = getattr(obj, f"{prefix}_region_name", "") or ""
    city_name = getattr(obj, f"{prefix}_city_name", "") or ""
    district_name = getattr(obj, f"{prefix}_district_name", "") or ""

    if fk_id is not None:
        fk = getattr(obj, f"{prefix}_location", None)
        if fk is not None:
            return {
                "id": fk.pk,
                "display": fk.full_name,
                "name": fk.name,
                "address": fk.address or snapshot_address,
                "latitude": fk.latitude,
                "longitude": fk.longitude,
                "region_name": region_name or fk.district.region.name,
                "city_name": city_name or fk.district.name,
                "district_name": district_name or fk.district.name,
                "is_catalogue_place": True,
            }

    admin = ", ".join(dict.fromkeys(part for part in (region_name, city_name, district_name) if part))
    return {
        "id": None,
        "display": snapshot_address or snapshot_name or admin or "Aniqlanmagan nuqta",
        "name": snapshot_name or city_name,
        "address": snapshot_address,
        "latitude": getattr(obj, f"{prefix}_latitude", None),
        "longitude": getattr(obj, f"{prefix}_longitude", None),
        "region_name": region_name,
        "city_name": city_name,
        "district_name": district_name,
        "is_catalogue_place": False,
    }


class DriverTripSerializer(RouteEndpointMixinSerializer, serializers.ModelSerializer):
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
    origin_display = serializers.CharField(read_only=True)
    destination_display = serializers.CharField(read_only=True)

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
            "origin",
            "destination",
            "origin_display",
            "destination_display",
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


class RoutePointWriteSerializer(serializers.Serializer):
    """Write payload for one route endpoint.

    The client may send **either** ``from_location`` / ``to_location`` (a
    curated catalogue id) **or** this nested block with the raw coordinates.
    The text fields are optional: when they are omitted the backend
    reverse-geocodes through 2GIS so that the passenger and the driver end up
    reading byte-identical strings.
    """

    latitude = serializers.DecimalField(
        max_digits=9, decimal_places=6, required=False, allow_null=True, coerce_to_string=False
    )
    longitude = serializers.DecimalField(
        max_digits=9, decimal_places=6, required=False, allow_null=True, coerce_to_string=False
    )
    address = serializers.CharField(required=False, allow_blank=True, max_length=255)
    place_name = serializers.CharField(required=False, allow_blank=True, max_length=180)
    region_name = serializers.CharField(required=False, allow_blank=True, max_length=120)
    city_name = serializers.CharField(required=False, allow_blank=True, max_length=120)
    district_name = serializers.CharField(required=False, allow_blank=True, max_length=120)

    def validate(self, attrs: dict) -> dict:
        from apps.core.validators import validate_latitude, validate_longitude

        has_lat = attrs.get("latitude") is not None
        has_lng = attrs.get("longitude") is not None
        if has_lat != has_lng:
            raise serializers.ValidationError(
                {"latitude": "Kenglik va uzunlik birga kiritilishi kerak."}
            )
        if has_lat:
            validate_latitude(attrs["latitude"])
            validate_longitude(attrs["longitude"])
        return attrs


class RouteEndpointWriteMixin:
    """Shared validation for the trip and request write serializers."""

    #: Maps the nested write key onto the ``build_point_snapshot`` prefix.
    endpoint_fields = {
        "origin": ("from_location", "from"),
        "destination": ("to_location", "to"),
    }

    def _resolve_endpoints(self, attrs: dict) -> dict:
        """Turn nested ``origin``/``destination`` blocks into service kwargs.

        The nested keys are already named exactly like
        :func:`apps.locations.services.build_point_snapshot`'s keyword
        arguments, so the dict is forwarded with ``**`` and the snapshot prefix
        is added back by the service.
        """
        for write_key, (location_field, _prefix) in self.endpoint_fields.items():
            point = attrs.get(write_key)
            if point is None:
                # A PATCH does not have to repeat the endpoints it is not
                # touching; only a create does.
                if not self.partial and attrs.get(location_field) is None:
                    raise serializers.ValidationError(
                        {
                            write_key: (
                                "Xaritada nuqta tanlang yoki katalogdagi manzilni "
                                "tanlang (location_id)."
                            )
                        }
                    )
                continue
            attrs[write_key] = dict(point)

        self._assert_endpoints_differ(attrs)
        return attrs

    def _assert_endpoints_differ(self, attrs: dict) -> None:
        from_location = attrs.get("from_location")
        to_location = attrs.get("to_location")
        if (
            from_location is not None
            and to_location is not None
            and from_location.pk == to_location.pk
        ):
            raise serializers.ValidationError(
                {"destination": "Qayerdan va qayerga bir xil bo'lishi mumkin emas."}
            )

        origin = attrs.get("origin")
        destination = attrs.get("destination")
        if not origin or not destination:
            return
        if origin.get("latitude") is None or destination.get("latitude") is None:
            return

        # Asked of the service layer so the API answers with the same bound and
        # the same wording the bot and the Mini App show.
        from apps.rides.services import validate_route_points

        error = validate_route_points(
            (origin["latitude"], origin["longitude"]),
            (destination["latitude"], destination["longitude"]),
        )
        if error:
            raise serializers.ValidationError({"destination": error})


class DriverTripWriteSerializer(RouteEndpointWriteMixin, serializers.ModelSerializer):
    """Payload used to create or update a trip.

    ``available_seats`` is intentionally read-only: it is maintained by the
    service layer through seat reservations.
    """

    origin = RoutePointWriteSerializer(required=False, allow_null=True)
    destination = RoutePointWriteSerializer(required=False, allow_null=True)

    class Meta:
        model = DriverTrip
        fields = (
            "vehicle",
            "from_location",
            "to_location",
            "origin",
            "destination",
            "departure_time",
            "total_seats",
            "price_per_seat",
            "comment",
        )
        extra_kwargs = {
            "vehicle": {"required": True},
            "from_location": {"required": False, "allow_null": True},
            "to_location": {"required": False, "allow_null": True},
            "departure_time": {"required": True},
            "total_seats": {"required": True, "min_value": 1},
            "price_per_seat": {"required": True, "min_value": 0},
            "comment": {"required": False, "allow_blank": True, "max_length": 500},
        }

    def validate(self, attrs):
        return self._resolve_endpoints(attrs)


class PassengerRequestSerializer(RouteEndpointMixinSerializer, serializers.ModelSerializer):
    """Full read representation of a passenger request."""

    passenger_name = serializers.CharField(source="passenger.display_name", read_only=True)
    passenger_phone = serializers.CharField(source="passenger.phone_number", read_only=True)
    from_location_detail = TripLocationSerializer(source="from_location", read_only=True)
    to_location_detail = TripLocationSerializer(source="to_location", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    origin_display = serializers.CharField(read_only=True)
    destination_display = serializers.CharField(read_only=True)

    class Meta:
        model = PassengerRequest
        fields = (
            "id",
            "passenger",
            "passenger_name",
            "passenger_phone",
            "from_location",
            "to_location",
            "origin",
            "destination",
            "origin_display",
            "destination_display",
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


class PassengerRequestWriteSerializer(RouteEndpointWriteMixin, serializers.ModelSerializer):
    origin = RoutePointWriteSerializer(required=False, allow_null=True)
    destination = RoutePointWriteSerializer(required=False, allow_null=True)

    class Meta:
        model = PassengerRequest
        fields = (
            "from_location",
            "to_location",
            "origin",
            "destination",
            "passenger_count",
            "max_price_per_seat",
            "departure_from",
            "departure_until",
            "comment",
        )
        extra_kwargs = {
            "from_location": {"required": False, "allow_null": True},
            "to_location": {"required": False, "allow_null": True},
            "passenger_count": {"required": False, "default": 1, "min_value": 1},
            "max_price_per_seat": {"required": False, "allow_null": True, "min_value": 0},
            "departure_from": {"required": False},
            "departure_until": {"required": False},
            "comment": {"required": False, "allow_blank": True, "max_length": 500},
        }

    def validate(self, attrs):
        attrs = self._resolve_endpoints(attrs)
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


class NearbyPassengerRequestSerializer(PassengerRequestSerializer):
    """A passenger request as a driver reads it on the map.

    Two differences from :class:`PassengerRequestSerializer`:

    * ``passenger_phone`` is dropped. This feed lists *other* people's requests,
      so handing every driver every passenger's number before an order exists
      would leak it platform-wide. The Telegram username is the contact channel
      until then.
    * ``distance_km`` / ``trip_km`` are added - the driver-to-pickup distance the
      marker is coloured by, and the ride length the arrow spans. Both come from
      ``context["distances"]`` / the request's own snapshot so they are measured
      with the same formula everywhere else in the product.
    """

    passenger_username = serializers.CharField(source="passenger.username", read_only=True)
    distance_km = serializers.SerializerMethodField()
    trip_km = serializers.SerializerMethodField()

    class Meta(PassengerRequestSerializer.Meta):
        fields = (
            tuple(
                field
                for field in PassengerRequestSerializer.Meta.fields
                if field != "passenger_phone"
            )
            + ("passenger_username", "distance_km", "trip_km")
        )
        read_only_fields = fields

    def get_distance_km(self, obj) -> float:
        """Driver-to-pickup distance, computed by the selector."""
        distance = self.context.get("distances", {}).get(obj.pk)
        return None if distance is None else round(float(distance), 1)

    def get_trip_km(self, obj) -> float | None:
        """Pickup-to-dropoff length, or ``None`` when an endpoint is unresolved."""
        from apps.rides.services import haversine_km

        if not (obj.has_origin_coordinates() and obj.has_destination_coordinates()):
            return None
        length = float(
            haversine_km(
                (obj.from_latitude, obj.from_longitude),
                (obj.to_latitude, obj.to_longitude),
            )
        )
        return round(length, 1)


class NearbyRequestsResponseSerializer(serializers.Serializer):
    """Envelope of the driver map feed."""

    center = serializers.DictField(child=serializers.DecimalField(max_digits=9, decimal_places=6))
    radius_km = serializers.FloatField()
    count = serializers.IntegerField()
    results = NearbyPassengerRequestSerializer(many=True)
