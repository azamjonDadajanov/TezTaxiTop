"""REST API views for the locations app.

The catalogue is readable by every authenticated user and writable by staff
only, because it is a shared reference data set.
"""

from __future__ import annotations

from decimal import Decimal

from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.exceptions import BusinessValidationError
from apps.core.permissions import IsAdminOrReadOnly
from apps.locations import selectors as location_selectors
from apps.locations import services as location_services
from apps.locations import two_gis
from apps.locations.serializers import (
    DistrictSerializer,
    LocationSerializer,
    LocationWriteSerializer,
    RegionSerializer,
    ResolvedPlaceSerializer,
)


@extend_schema_view(
    list=extend_schema(summary="Viloyatlar ro'yxati", responses={200: RegionSerializer(many=True)}),
    retrieve=extend_schema(summary="Viloyat", responses={200: RegionSerializer}),
    create=extend_schema(summary="Viloyat qo'shish (admin)", request=RegionSerializer, responses={201: RegionSerializer}),
    partial_update=extend_schema(summary="Viloyatni tahrirlash", request=RegionSerializer, responses={200: RegionSerializer}),
    destroy=extend_schema(summary="Viloyatni o'chirish", responses={204: None}),
)
class RegionViewSet(viewsets.ModelViewSet):
    queryset = location_selectors.get_regions()
    serializer_class = RegionSerializer
    permission_classes = [IsAuthenticated, IsAdminOrReadOnly]
    filterset_fields = ["is_active"]
    search_fields = location_selectors.REGION_SEARCH_FIELDS
    ordering_fields = ["id", "name", "created_at"]
    ordering = ["name"]

    def get_queryset(self):
        queryset = super().get_queryset()
        if not self.request.user.is_staff:
            queryset = queryset.filter(is_active=True)
        return location_selectors.get_regions_search(queryset, self.request.query_params.get("search"))

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            region = location_services.create_region(**serializer.validated_data)
        except BusinessValidationError as exc:
            raise DRFValidationError({"detail": exc.message}) from exc
        return Response(RegionSerializer(region).data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        serializer = self.get_serializer(data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        try:
            region = location_services.update_region(self.get_object(), **serializer.validated_data)
        except BusinessValidationError as exc:
            raise DRFValidationError({"detail": exc.message}) from exc
        return Response(RegionSerializer(region).data)

    @extend_schema(
        summary="Viloyat tumanlari",
        responses={200: DistrictSerializer(many=True)},
    )
    @action(detail=True, methods=["get"])
    def districts(self, request, pk=None) -> Response:
        districts = location_selectors.get_districts_by_region(pk)
        return Response(DistrictSerializer(districts, many=True).data)


@extend_schema_view(
    list=extend_schema(summary="Tumanlar ro'yxati", responses={200: DistrictSerializer(many=True)}),
    retrieve=extend_schema(summary="Tuman", responses={200: DistrictSerializer}),
    create=extend_schema(summary="Tuman qo'shish (admin)", request=DistrictSerializer, responses={201: DistrictSerializer}),
    partial_update=extend_schema(summary="Tumani tahrirlash", request=DistrictSerializer, responses={200: DistrictSerializer}),
    destroy=extend_schema(summary="Tumanni o'chirish", responses={204: None}),
)
class DistrictViewSet(viewsets.ModelViewSet):
    queryset = location_selectors.get_districts()
    serializer_class = DistrictSerializer
    permission_classes = [IsAuthenticated, IsAdminOrReadOnly]
    filterset_fields = ["region", "is_active"]
    search_fields = location_selectors.DISTRICT_SEARCH_FIELDS
    ordering_fields = ["id", "name", "region__name", "created_at"]
    ordering = ["region__name", "name"]

    def get_queryset(self):
        queryset = super().get_queryset()
        if not self.request.user.is_staff:
            queryset = queryset.filter(is_active=True, region__is_active=True)
        return location_selectors.get_districts_search(queryset, self.request.query_params.get("search"))

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            district = location_services.create_district(**serializer.validated_data)
        except BusinessValidationError as exc:
            raise DRFValidationError({"detail": exc.message}) from exc
        return Response(DistrictSerializer(district).data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        serializer = self.get_serializer(data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        try:
            district = location_services.update_district(self.get_object(), **serializer.validated_data)
        except BusinessValidationError as exc:
            raise DRFValidationError({"detail": exc.message}) from exc
        return Response(DistrictSerializer(district).data)

    @extend_schema(summary="Tuman manzillari", responses={200: LocationSerializer(many=True)})
    @action(detail=True, methods=["get"])
    def locations(self, request, pk=None) -> Response:
        locations = location_selectors.get_locations_by_district(pk)
        return Response(LocationSerializer(locations, many=True).data)


@extend_schema_view(
    list=extend_schema(
        summary="Manzillar ro'yxati",
        parameters=[
            OpenApiParameter("search", str, description="Manzil, tuman yoki viloyat nomi."),
            OpenApiParameter("district", int),
        ],
        responses={200: LocationSerializer(many=True)},
    ),
    retrieve=extend_schema(summary="Manzil", responses={200: LocationSerializer}),
    create=extend_schema(summary="Manzil qo'shish (admin)", request=LocationWriteSerializer, responses={201: LocationSerializer}),
    partial_update=extend_schema(
        summary="Manzilni tahrirlash", request=LocationWriteSerializer, responses={200: LocationSerializer}
    ),
    destroy=extend_schema(summary="Manzilni o'chirish", responses={204: None}),
)
class LocationViewSet(viewsets.ModelViewSet):
    queryset = location_selectors.get_locations()
    serializer_class = LocationSerializer
    permission_classes = [IsAuthenticated, IsAdminOrReadOnly]
    filterset_fields = ["district", "is_active"]
    search_fields = location_selectors.LOCATION_SEARCH_FIELDS
    ordering_fields = ["id", "name", "created_at"]
    ordering = ["name"]

    def get_serializer_class(self):
        if self.action in {"create", "update", "partial_update"}:
            return LocationWriteSerializer
        return LocationSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        if not self.request.user.is_staff:
            queryset = location_selectors.get_active_locations().filter(
                district__is_active=True, district__region__is_active=True
            )
        return location_selectors.search_locations(queryset, self.request.query_params.get("search"))

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            location = location_services.create_location(**serializer.validated_data)
        except BusinessValidationError as exc:
            raise DRFValidationError({"detail": exc.message}) from exc
        return Response(LocationSerializer(location).data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        serializer = self.get_serializer(data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        try:
            location = location_services.update_location(self.get_object(), **serializer.validated_data)
        except BusinessValidationError as exc:
            raise DRFValidationError({"detail": exc.message}) from exc
        return Response(LocationSerializer(location).data)


def _query_coordinate(request, name: str) -> Decimal | None:
    """Read and range-check one coordinate from the query string."""
    raw = request.query_params.get(name)
    if raw is None or raw == "":
        return None
    try:
        value = Decimal(raw)
    except (ArithmeticError, ValueError) as exc:
        raise DRFValidationError({name: "Raqamli koordinata kiriting."}) from exc
    if name == "lat" and not (Decimal("-90") <= value <= Decimal("90")):
        raise DRFValidationError({"lat": "Kenglik -90 va 90 orasida bo'lishi kerak."})
    if name == "lon" and not (Decimal("-180") <= value <= Decimal("180")):
        raise DRFValidationError({"lon": "Uzunlik -180 va 180 orasida bo'lishi kerak."})
    return value


@extend_schema_view(
    list=extend_schema(
        summary="2GIS orqali manzil qidirish (forward geocoding)",
        description=(
            "Erkin matn bo'yicha qidiruv. `lat`/`lon` berilsa natija foydalanuvchi "
            "joylashuviga yaqinlashtiriladi va `TWOGIS_REGION_ID` sozlanmasidan "
            "mustaqil ishlaydi."
        ),
        parameters=[
            OpenApiParameter("q", str, required=True, description="Masalan: Amir Temur ko'chasi 12"),
            OpenApiParameter("lat", float, description="Foydalanuvchi kengligi (-90..90)"),
            OpenApiParameter("lon", float, description="Foydalanuvchi uzunligi (-180..180)"),
            OpenApiParameter("limit", int, description="Natijalar soni (1..50, default 10)"),
        ],
        responses={200: ResolvedPlaceSerializer(many=True)},
    ),
    reverse=extend_schema(
        summary="Koordinatadan manzil aniqlash (reverse geocoding)",
        description=(
            "GPS yoki xarita koordinatini manzil va administrativ ierarxiyaga "
            "(viloyat / shahar / tuman) aylantiradi. Bu natija tripga nusxalanadi, "
            "shuning uchun yo'lovchi va haydovchi bir xil matnni ko'radi."
        ),
        parameters=[
            OpenApiParameter("lat", float, required=True),
            OpenApiParameter("lon", float, required=True),
            OpenApiParameter("radius", int, description="Qidiruv radiusi, metr (default 300)"),
        ],
        responses={200: ResolvedPlaceSerializer},
    ),
)
class GeoViewSet(viewsets.ViewSet):
    """Read-only 2GIS proxy.

    The browser never talks to 2GIS directly: keeping the API key on the server
    means it cannot be extracted from the Mini App bundle, and it lets the
    backend cache responses for a day (coordinates do not move).
    """

    permission_classes = [IsAuthenticated]

    def list(self, request) -> Response:
        query = (request.query_params.get("q") or "").strip()
        if not query:
            raise DRFValidationError({"q": "Qidiruv so'rovi (q) majburiy."})

        try:
            limit = int(request.query_params.get("limit", 10))
        except ValueError as exc:
            raise DRFValidationError({"limit": "Butun son kiriting."}) from exc

        latitude = _query_coordinate(request, "lat")
        longitude = _query_coordinate(request, "lon")
        near = None
        if latitude is not None and longitude is not None:
            # 2GIS expects "lon, lat" ordering for the geographic parameters.
            near = (longitude, latitude)
        elif latitude is not None or longitude is not None:
            raise DRFValidationError({"detail": "lat va lon birga kiritilishi kerak."})

        places = two_gis.search_places(query, near=near, limit=limit)
        return Response(ResolvedPlaceSerializer(places, many=True).data)

    @action(detail=False, methods=["get"])
    def reverse(self, request) -> Response:
        latitude = _query_coordinate(request, "lat")
        longitude = _query_coordinate(request, "lon")
        if latitude is None or longitude is None:
            raise DRFValidationError({"detail": "lat va lon majburiy."})

        radius = request.query_params.get("radius")
        radius_m = None
        if radius:
            try:
                radius_m = int(radius)
            except ValueError as exc:
                raise DRFValidationError({"radius": "Butun son kiriting."}) from exc

        place = two_gis.reverse_geocode(latitude, longitude, radius_m=radius_m)
        return Response(ResolvedPlaceSerializer(place).data)
