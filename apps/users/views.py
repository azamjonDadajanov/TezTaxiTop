"""REST API views for the users app.

Read paths use ``selectors``; every write delegates to ``services``.
"""

from __future__ import annotations

from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.exceptions import ResourceNotFound
from apps.core.permissions import IsAdminOrReadOnly, IsOwnerOrReadOnly
from apps.users import selectors as user_selectors
from apps.users import services as user_services
from apps.users.models import DriverProfile, User
from apps.users.permissions import IsAdminOrReadOnlyUser, IsSelfOrAdmin
from apps.users.serializers import (
    DriverProfileSerializer,
    DriverProfileUpdateSerializer,
    UserSerializer,
)


@extend_schema_view(
    list=extend_schema(
        summary="Foydalanuvchilar ro'yxati",
        parameters=[
            OpenApiParameter("search", str, description="Ism, telefon yoki Telegram ID bo'yicha qidirish."),
            OpenApiParameter("role", str, description="passenger / driver / both"),
            OpenApiParameter("is_blocked", bool),
        ],
        responses={200: UserSerializer(many=True)},
    ),
    retrieve=extend_schema(summary="Foydalanuvchi", responses={200: UserSerializer}),
    partial_update=extend_schema(summary="Foydalanuvchini yangilash", responses={200: UserSerializer}),
)
class UserViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Read the directory, moderate accounts as staff."""

    queryset = user_selectors.get_user_queryset()
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated, IsAdminOrReadOnlyUser, IsSelfOrAdmin]
    filterset_fields = ["role", "is_blocked", "is_active", "is_staff"]
    search_fields = ["username", "first_name", "last_name", "phone_number", "telegram_id"]
    ordering_fields = ["id", "username", "created_at", "last_seen_at", "role"]
    ordering = ["-created_at"]

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.request.user.is_staff:
            return queryset
        # Non staff users only see their own account.
        return queryset.filter(pk=self.request.user.pk)

    def perform_update(self, serializer):
        user_services.update_user_profile(
            serializer.instance,
            first_name=serializer.validated_data.get("first_name"),
            last_name=serializer.validated_data.get("last_name"),
            phone_number=serializer.validated_data.get("phone_number"),
            language_code=serializer.validated_data.get("language_code"),
        )

    @extend_schema(
        summary="Foydalanuvchini bloklash",
        request=None,
        responses={200: UserSerializer},
    )
    @action(detail=True, methods=["post"], permission_classes=[IsAdminOrReadOnly])
    def block(self, request, pk=None) -> Response:
        user = self.get_object()
        return Response(UserSerializer(user_services.block_user(user)).data)

    @extend_schema(summary="Blokni olib tashlash", request=None, responses={200: UserSerializer})
    @action(detail=True, methods=["post"], permission_classes=[IsAdminOrReadOnly])
    def unblock(self, request, pk=None) -> Response:
        user = self.get_object()
        return Response(UserSerializer(user_services.unblock_user(user)).data)


@extend_schema_view(
    list=extend_schema(summary="Haydovchi profillari", responses={200: DriverProfileSerializer(many=True)}),
    retrieve=extend_schema(summary="Haydovchi profili", responses={200: DriverProfileSerializer}),
    partial_update=extend_schema(
        summary="O'z haydovchi profilini tahrirlash", responses={200: DriverProfileSerializer}
    ),
)
class DriverProfileViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Driver directory with verification and statistics."""

    queryset = user_selectors.get_driver_profile_queryset()
    serializer_class = DriverProfileSerializer
    permission_classes = [IsAuthenticated, IsOwnerOrReadOnly]
    filterset_fields = ["is_verified", "user__role", "user__is_blocked"]
    search_fields = [
        "user__first_name",
        "user__last_name",
        "user__username",
        "user__phone_number",
        "user__telegram_id",
    ]
    ordering_fields = ["rating", "total_trips", "completed_trips", "created_at"]
    ordering = ["-rating"]

    owner_field = "user"

    def get_serializer_class(self):
        if self.action == "partial_update":
            return DriverProfileUpdateSerializer
        return DriverProfileSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        search_term = self.request.query_params.get("search")
        return user_selectors.get_drivers_search(queryset, search_term)

    def perform_update(self, serializer):
        user_services.update_driver_profile(
            serializer.instance, bio=serializer.validated_data.get("bio")
        )


@extend_schema_view(
    post=extend_schema(
        summary="Haydovchi roliga o'tish",
        description="Yo'lovchi hisobini haydovchiga aylantiradi va `DriverProfile` yaratadi.",
        responses={201: DriverProfileSerializer, 200: DriverProfileSerializer},
    )
)
class BecomeDriverView(APIView):
    """Self-service driver registration (vehicle creation is a next step)."""

    permission_classes = [IsAuthenticated]
    serializer_class = DriverProfileSerializer

    def post(self, request) -> Response:
        profile = user_services.register_as_driver(request.user)
        http_status = status.HTTP_201_CREATED if profile.created_at else status.HTTP_200_OK
        return Response(DriverProfileSerializer(profile).data, status=http_status)


@extend_schema_view(
    get=extend_schema(summary="Mening haydovchi profilim", responses={200: DriverProfileSerializer}),
)
class MyDriverProfileView(APIView):
    """Convenience endpoint used by the Telegram bot and Mini App."""

    permission_classes = [IsAuthenticated]
    serializer_class = DriverProfileSerializer

    def get(self, request) -> Response:
        profile = user_selectors.get_driver_profile_by_user(request.user)
        if profile is None:
            raise ResourceNotFound("Haydovchi profili topilmadi.")
        return Response(DriverProfileSerializer(profile).data)
