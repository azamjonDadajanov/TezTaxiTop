"""REST API views for the vehicles app."""

from __future__ import annotations

from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.exceptions import BusinessValidationError, VehicleNotVerified
from apps.core.permissions import IsAdminOrOwner, IsAdminOrReadOnly
from apps.vehicles import selectors as vehicle_selectors
from apps.vehicles import services as vehicle_services
from apps.vehicles.serializers import VehicleSerializer, VehicleWriteSerializer


@extend_schema_view(
    list=extend_schema(
        summary="Avtomobillar ro'yxati",
        parameters=[
            OpenApiParameter("search", str, description="Davlat raqami, brend, model yoki haydovchi bo'yicha."),
            OpenApiParameter("is_active", bool),
            OpenApiParameter("is_verified", bool),
        ],
        responses={200: VehicleSerializer(many=True)},
    ),
    retrieve=extend_schema(summary="Avtomobil", responses={200: VehicleSerializer}),
    create=extend_schema(summary="Avtomobil qo'shish", request=VehicleWriteSerializer, responses={201: VehicleSerializer}),
    partial_update=extend_schema(
        summary="Avtomobilni tahrirlash", request=VehicleWriteSerializer, responses={200: VehicleSerializer}
    ),
    destroy=extend_schema(summary="Avtomobilni o'chirish (soft delete)", responses={204: None}),
)
class VehicleViewSet(viewsets.ModelViewSet):
    """Drivers manage their own cars; staff verify them."""

    queryset = vehicle_selectors.get_vehicle_queryset()
    serializer_class = VehicleSerializer
    permission_classes = [IsAuthenticated, IsAdminOrOwner]
    filterset_fields = ["is_active", "is_verified", "year", "brand", "driver__is_verified"]
    search_fields = vehicle_selectors.VEHICLE_SEARCH_FIELDS
    ordering_fields = vehicle_selectors.VEHICLE_ORDERING_FIELDS
    ordering = ["-created_at"]

    def get_serializer_class(self):
        if self.action in {"create", "update", "partial_update"}:
            return VehicleWriteSerializer
        return VehicleSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user
        if not user.is_staff:
            # Drivers only see their own cars.
            if hasattr(user, "driver_profile"):
                queryset = queryset.filter(driver=user.driver_profile)
            else:
                queryset = queryset.none()
        return vehicle_selectors.search_vehicles(queryset, self.request.query_params.get("search"))

    def get_permissions(self):
        if self.action in {"verify", "unverify"}:
            return [IsAuthenticated(), IsAdminOrReadOnly()]
        return super().get_permissions()

    def create(self, request, *args, **kwargs):
        driver_profile = getattr(request.user, "driver_profile", None)
        if driver_profile is None:
            raise DRFValidationError(
                {"driver": "Avtomobil qo'shish uchun avval haydovchi roliga o'ting."}
            )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            vehicle = vehicle_services.create_vehicle(
                driver=driver_profile, **serializer.validated_data
            )
        except BusinessValidationError as exc:
            raise DRFValidationError({"detail": exc.message}) from exc
        return Response(VehicleSerializer(vehicle).data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        serializer = self.get_serializer(data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        try:
            vehicle = vehicle_services.update_vehicle(
                self.get_object(), **serializer.validated_data
            )
        except BusinessValidationError as exc:
            raise DRFValidationError({"detail": exc.message}) from exc
        return Response(VehicleSerializer(vehicle).data)

    def destroy(self, request, *args, **kwargs):
        vehicle = self.get_object()
        vehicle_services.delete_vehicle(vehicle)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(summary="Avtomobilni tasdiqlash (admin)", request=None, responses={200: VehicleSerializer})
    @action(detail=True, methods=["post"])
    def verify(self, request, pk=None) -> Response:
        vehicle = vehicle_services.verify_vehicle(self.get_object(), verified=True)
        return Response(VehicleSerializer(vehicle).data)

    @extend_schema(summary="Tasdiqni olish (admin)", request=None, responses={200: VehicleSerializer})
    @action(detail=True, methods=["post"])
    def unverify(self, request, pk=None) -> Response:
        vehicle = vehicle_services.verify_vehicle(self.get_object(), verified=False)
        return Response(VehicleSerializer(vehicle).data)

    @extend_schema(summary="Faollashtirish / o'chirish", request=None, responses={200: VehicleSerializer})
    @action(detail=True, methods=["post"])
    def set_active(self, request, pk=None) -> Response:
        is_active = bool(request.data.get("is_active", True))
        vehicle = vehicle_services.set_vehicle_active(self.get_object(), is_active=is_active)
        return Response(VehicleSerializer(vehicle).data)

    @extend_schema(
        summary="Yo'lov yaratish uchun mavjud mashinalarim",
        responses={200: VehicleSerializer(many=True)},
    )
    @action(detail=False, methods=["get"])
    def usable(self, request) -> Response:
        if not hasattr(request.user, "driver_profile"):
            raise VehicleNotVerified()
        vehicles = vehicle_selectors.get_usable_vehicles_by_driver(request.user.driver_profile)
        return Response(VehicleSerializer(vehicles, many=True).data)
