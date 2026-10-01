"""REST API views for the rides app.

All state changes call ``apps.rides.services``; views only translate HTTP into
service calls and service results into responses.
"""

from __future__ import annotations

from decimal import Decimal

from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError as DRFValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core import conf
from apps.core.exceptions import BusinessError
from apps.locations.models import Location
from apps.rides import selectors as ride_selectors
from apps.rides import services as ride_services
from apps.rides.models import DriverTrip, DriverTripStatus, PassengerRequest
from apps.rides.permissions import IsPassengerRequestOwner, IsTripDriver
from apps.rides.serializers import (
    DriverTripSerializer,
    DriverTripWriteSerializer,
    NearbyDriverTripSerializer,
    NearbyPassengerRequestSerializer,
    NearbyRequestsResponseSerializer,
    NearbyTripsResponseSerializer,
    PassengerRequestSerializer,
    PassengerRequestWriteSerializer,
)
from apps.users.models import DriverProfile
from apps.vehicles.models import Vehicle


def _handle_business_error(exc: BusinessError) -> DRFValidationError:
    """Convert a business error into a DRF validation error (keeps 4xx codes)."""
    return DRFValidationError({"detail": exc.message, "code": exc.code, "details": exc.details})


@extend_schema_view(
    list=extend_schema(
        summary="Yo'lovlar ro'yxati",
        parameters=[
            OpenApiParameter("search", str, description="Haydovchi ismi, telefon, davlat raqami yoki manzil."),
            OpenApiParameter("status", str, description="active / full / in_progress / completed ..."),
            OpenApiParameter("from_location", int),
            OpenApiParameter("to_location", int),
            OpenApiParameter("only_bookable", bool, description="Faqat band qilinmagan yo'lovlar."),
        ],
        responses={200: DriverTripSerializer(many=True)},
    ),
    retrieve=extend_schema(summary="Yo'lov", responses={200: DriverTripSerializer}),
    create=extend_schema(
        summary="Yo'lov yaratish",
        description="Faqat tasdiqlangan, obunasi faol haydovchi yarata oladi.",
        request=DriverTripWriteSerializer,
        responses={
            201: DriverTripSerializer,
            402: {"description": "Faol obuna talab qilinadi (SubscriptionRequired)."},
        },
    ),
    partial_update=extend_schema(
        summary="Yo'lovni tahrirlash", request=DriverTripWriteSerializer, responses={200: DriverTripSerializer}
    ),
)
class DriverTripViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    queryset = ride_selectors.get_trip_queryset()
    serializer_class = DriverTripSerializer
    permission_classes = [IsAuthenticated, IsTripDriver]
    filterset_fields = ["status", "vehicle", "from_location", "to_location", "driver", "vehicle__is_verified"]
    search_fields = ride_selectors.TRIP_SEARCH_FIELDS
    ordering_fields = ride_selectors.TRIP_ORDERING_FIELDS
    ordering = ["departure_time"]

    def get_serializer_class(self):
        if self.action in {"create", "update", "partial_update"}:
            return DriverTripWriteSerializer
        return DriverTripSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.request.query_params.get("only_bookable") in {"1", "true", "True"}:
            queryset = ride_selectors.get_bookable_trips()
        return ride_selectors.search_trips(queryset, self.request.query_params.get("search"))

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)

        try:
            driver_profile = ride_services.assert_driver_can_create_trip(request.user)
            vehicle = data.pop("vehicle", None)
            if vehicle is None:
                raise DRFValidationError({"vehicle": "Avtomobil tanlanishi shart."})
            trip = ride_services.create_trip(
                driver_profile=driver_profile,
                vehicle=vehicle,
                **data,
            )
        except Vehicle.DoesNotExist as exc:
            raise DRFValidationError({"vehicle": "Avtomobil topilmadi."}) from exc
        except BusinessError as exc:
            raise _handle_business_error(exc) from exc
        return Response(DriverTripSerializer(trip).data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        serializer = self.get_serializer(data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        try:
            trip = ride_services.update_trip(self.get_object(), **serializer.validated_data)
        except BusinessError as exc:
            raise _handle_business_error(exc) from exc
        return Response(DriverTripSerializer(trip).data)

    @extend_schema(summary="Yo'lovni e'lon qilish (qoralama)", request=None, responses={200: DriverTripSerializer})
    @action(detail=True, methods=["post"])
    def publish(self, request, pk=None) -> Response:
        try:
            trip = ride_services.publish_trip(self.get_object())
        except BusinessError as exc:
            raise _handle_business_error(exc) from exc
        return Response(DriverTripSerializer(trip).data)

    @extend_schema(
        summary="Yo'lovni bekor qilish",
        request={"application/json": {"type": "object", "properties": {"reason": {"type": "string"}}}},
        responses={200: DriverTripSerializer},
    )
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None) -> Response:
        try:
            trip = ride_services.cancel_trip(self.get_object(), reason=request.data.get("reason", ""))
        except BusinessError as exc:
            raise _handle_business_error(exc) from exc
        return Response(DriverTripSerializer(trip).data)

    @extend_schema(summary="Yo'lni boshlash", request=None, responses={200: DriverTripSerializer})
    @action(detail=True, methods=["post"])
    def start(self, request, pk=None) -> Response:
        try:
            trip = ride_services.start_trip(self.get_object())
        except BusinessError as exc:
            raise _handle_business_error(exc) from exc
        return Response(DriverTripSerializer(trip).data)

    @extend_schema(summary="Yo'lovni yakunlash", request=None, responses={200: DriverTripSerializer})
    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None) -> Response:
        try:
            trip = ride_services.complete_trip(self.get_object())
        except BusinessError as exc:
            raise _handle_business_error(exc) from exc
        return Response(DriverTripSerializer(trip).data)

    @extend_schema(summary="Mening yo'lovlarim", responses={200: DriverTripSerializer(many=True)})
    @action(detail=False, methods=["get"])
    def my_trips(self, request) -> Response:
        if not hasattr(request.user, "driver_profile"):
            return Response([], status=status.HTTP_200_OK)
        trips = ride_selectors.get_trips_by_driver(request.user.driver_profile)
        return Response(DriverTripSerializer(trips, many=True).data)


@extend_schema_view(
    list=extend_schema(summary="So'rovlar ro'yxati", responses={200: PassengerRequestSerializer(many=True)}),
    retrieve=extend_schema(summary="So'rov", responses={200: PassengerRequestSerializer}),
    create=extend_schema(
        summary="Yo'lovchi so'rovi yaratish",
        request=PassengerRequestWriteSerializer,
        responses={201: PassengerRequestSerializer},
    ),
    partial_update=extend_schema(
        summary="So'rovni tahrirlash",
        request=PassengerRequestWriteSerializer,
        responses={200: PassengerRequestSerializer},
    ),
)
class PassengerRequestViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    queryset = ride_selectors.get_request_queryset()
    serializer_class = PassengerRequestSerializer
    permission_classes = [IsAuthenticated, IsPassengerRequestOwner]
    filterset_fields = ["status", "from_location", "to_location", "passenger"]
    search_fields = ride_selectors.REQUEST_SEARCH_FIELDS
    ordering_fields = ride_selectors.REQUEST_ORDERING_FIELDS
    ordering = ["-created_at"]

    def get_serializer_class(self):
        if self.action in {"create", "update", "partial_update"}:
            return PassengerRequestWriteSerializer
        return PassengerRequestSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        if not self.request.user.is_staff:
            queryset = queryset.filter(passenger=self.request.user)
        return ride_selectors.search_requests(queryset, self.request.query_params.get("search"))

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            passenger_request = ride_services.create_passenger_request(
                passenger=request.user, **serializer.validated_data
            )
        except BusinessError as exc:
            raise _handle_business_error(exc) from exc

        # Matching is asynchronous: the request is answered immediately and the
        # Celery task (if a worker is available) computes the suggestions.
        try:
            from apps.matching.tasks import refresh_request_matches_task

            refresh_request_matches_task.delay(passenger_request.pk)
        except Exception:  # pragma: no cover - broker may be unavailable
            from apps.matching.services import refresh_matches_for_request

            refresh_matches_for_request(passenger_request)

        return Response(
            PassengerRequestSerializer(passenger_request).data, status=status.HTTP_201_CREATED
        )

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        serializer = self.get_serializer(data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        try:
            passenger_request = ride_services.update_passenger_request(
                self.get_object(), **serializer.validated_data
            )
        except BusinessError as exc:
            raise _handle_business_error(exc) from exc
        return Response(PassengerRequestSerializer(passenger_request).data)

    @extend_schema(summary="So'rovni bekor qilish", request=None, responses={200: PassengerRequestSerializer})
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None) -> Response:
        try:
            passenger_request = ride_services.cancel_passenger_request(self.get_object())
        except BusinessError as exc:
            raise _handle_business_error(exc) from exc
        return Response(PassengerRequestSerializer(passenger_request).data)

    @extend_schema(
        summary="So'rov uchun mos yo'lovlar",
        description="Deterministik ball asosida saralangan yo'lovlar (matching service).",
        responses={200: DriverTripSerializer(many=True)},
    )
    @action(detail=True, methods=["get"])
    def matches(self, request, pk=None) -> Response:
        passenger_request = self.get_object()
        from apps.matching.services import rank_trips_for_request

        ranked = rank_trips_for_request(passenger_request)
        trips = [trip for trip, _score in ranked][: conf.MATCHING_MAX_RESULTS]
        return Response(DriverTripSerializer(trips, many=True).data)


def _map_coordinate(request, name: str) -> Decimal | None:
    """Read and range-check one driver-map coordinate from the query string."""
    raw = request.query_params.get(name)
    if raw is None or raw == "":
        return None
    try:
        value = Decimal(raw)
    except (ArithmeticError, ValueError) as exc:
        raise DRFValidationError({name: "Raqamli koordinata kiriting."}) from exc
    lower, upper = (Decimal("-90"), Decimal("90")) if name == "lat" else (Decimal("-180"), Decimal("180"))
    if not (lower <= value <= upper):
        raise DRFValidationError({name: f"Qiymat {lower} va {upper} orasida bo'lishi kerak."})
    return value


def _map_radius_km(request) -> float:
    """Radius of the map feed, clamped to the configured ceiling."""
    raw = request.query_params.get("radius_km")
    if raw is None or raw == "":
        return conf.DRIVER_MAP_RADIUS_KM
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise DRFValidationError({"radius_km": "Masofani km da kiriting (masalan 25)."}) from exc
    if value <= 0:
        raise DRFValidationError({"radius_km": "Masofa 0 dan katta bo'lishi shart."})
    return min(value, conf.DRIVER_MAP_MAX_RADIUS_KM)


def _passenger_map_radius_km(request) -> float:
    """Radius of the passenger ("taxis near me") feed.

    Same parsing as the driver feed but against the passenger-map settings, so
    the two maps can be tuned independently.
    """
    raw = request.query_params.get("radius_km")
    if raw is None or raw == "":
        return conf.PASSENGER_MAP_RADIUS_KM
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise DRFValidationError({"radius_km": "Masofani km da kiriting (masalan 25)."}) from exc
    if value <= 0:
        raise DRFValidationError({"radius_km": "Masofa 0 dan katta bo'lishi shart."})
    return min(value, conf.PASSENGER_MAP_MAX_RADIUS_KM)


class NearbyPassengerRequestsView(APIView):
    """``GET /api/v1/rides/requests/nearby/`` - the driver map feed.

    Lists the still-active passenger requests whose pickup point lies within the
    requested radius of the driver, nearest first. Unlike the request list this is
    *not* scoped to the caller's own rows - seeing other people's requests is the
    whole point of the map - so the driver's own passenger request is filtered out
    explicitly instead of by the owner rule the list view applies.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = NearbyRequestsResponseSerializer

    @extend_schema(
        summary="Yaqin yo'lovchi so'rovlari (haydovchi xaritasi)",
        description=(
            "Faol so'rovlarni haydovchi joylashuvi atrofida, masofa bo'yicha "
            "tartiblangan holda qaytaradi. Har bir elementda `distance_km` "
            "(haydovchidan nuqtaga) va `trip_km` (nuqtadan manzilgacha) bor."
        ),
        parameters=[
            OpenApiParameter("lat", float, required=True, description="Haydovchi kengligi (-90..90)"),
            OpenApiParameter("lon", float, required=True, description="Haydovchi uzunligi (-180..180)"),
            OpenApiParameter(
                "radius_km",
                float,
                description=(
                    f"Kutish radiusi, km (standart {int(conf.DRIVER_MAP_RADIUS_KM)}, "
                    f"maksimum {int(conf.DRIVER_MAP_MAX_RADIUS_KM)})"
                ),
            ),
        ],
        responses={200: NearbyRequestsResponseSerializer},
    )
    def get(self, request) -> Response:
        driver = getattr(request.user, "driver_profile", None)
        if driver is None and not request.user.is_staff:
            raise PermissionDenied("Bu ro'yxat faqat haydovchilar uchun.")

        latitude = _map_coordinate(request, "lat")
        longitude = _map_coordinate(request, "lon")
        if latitude is None or longitude is None:
            raise DRFValidationError({"detail": "Xaritalash uchun lat va lon majburiy."})

        radius_km = _map_radius_km(request)
        measured = ride_selectors.get_nearby_requests(
            latitude,
            longitude,
            radius_km,
            exclude_passenger=request.user,
        )[: conf.DRIVER_MAP_MAX_RESULTS]
        distances = {passenger_request.pk: distance for passenger_request, distance in measured}
        return Response(
            {
                "center": {"latitude": latitude, "longitude": longitude},
                "radius_km": radius_km,
                "count": len(measured),
                "results": NearbyPassengerRequestSerializer(
                    [passenger_request for passenger_request, _ in measured],
                    many=True,
                    context={"distances": distances},
                ).data,
            }
        )


class NearbyDriverTripsView(APIView):
    """``GET /api/v1/rides/trips/nearby/`` - the passenger map feed.

    The mirror of :class:`NearbyPassengerRequestsView`: bookable taxi trips whose
    pickup point lies within the requested radius of the passenger, nearest
    first. The caller's own trip is filtered out when they are also a driver, so
    the map never offers a car they are driving themselves.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = NearbyTripsResponseSerializer

    @extend_schema(
        summary="Yaqin taksilar (yo'lovchi xaritasi)",
        description=(
            "Band qilishga ochiq yo'lovlarni yo'lovchi joylashuvi atrofida, "
            "masofa bo'yicha tartiblangan holda qaytaradi. Har bir elementda "
            "`distance_km` (yo'lovchidan nuqtaga) va `trip_km` (nuqtadan "
            "manzilgacha) bor. Haydovchining telefon raqami yuborilmaydi."
        ),
        parameters=[
            OpenApiParameter("lat", float, required=True, description="Yo'lovchi kengligi (-90..90)"),
            OpenApiParameter("lon", float, required=True, description="Yo'lovchi uzunligi (-180..180)"),
            OpenApiParameter(
                "radius_km",
                float,
                description=(
                    f"Kutish radiusi, km (standart {int(conf.PASSENGER_MAP_RADIUS_KM)}, "
                    f"maksimum {int(conf.PASSENGER_MAP_MAX_RADIUS_KM)})"
                ),
            ),
        ],
        responses={200: NearbyTripsResponseSerializer},
    )
    def get(self, request) -> Response:
        latitude = _map_coordinate(request, "lat")
        longitude = _map_coordinate(request, "lon")
        if latitude is None or longitude is None:
            raise DRFValidationError({"detail": "Xaritalash uchun lat va lon majburiy."})

        radius_km = _passenger_map_radius_km(request)
        measured = ride_selectors.get_nearby_trips(
            latitude,
            longitude,
            radius_km,
            exclude_driver=getattr(request.user, "driver_profile", None),
        )[: conf.PASSENGER_MAP_MAX_RESULTS]
        distances = {trip.pk: distance for trip, distance in measured}
        return Response(
            {
                "center": {"latitude": latitude, "longitude": longitude},
                "radius_km": radius_km,
                "count": len(measured),
                "results": NearbyDriverTripSerializer(
                    [trip for trip, _ in measured],
                    many=True,
                    context={"distances": distances},
                ).data,
            }
        )
