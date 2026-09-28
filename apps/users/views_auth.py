"""Authentication and "current user" endpoints."""

from __future__ import annotations

from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from apps.users import services as user_services
from apps.users.serializers import (
    TelegramRegistrationSerializer,
    UserRoleUpdateSerializer,
    UserSerializer,
    UserUpdateSerializer,
)
from apps.users.services import UserIsBlocked


@extend_schema_view(
    get=extend_schema(
        summary="Joriy foydalanuvchi",
        description="Token orqali autentifikatsiyalangan foydalanuvchi ma'lumotlarini qaytaradi.",
        responses={200: UserSerializer},
    ),
    patch=extend_schema(
        summary="O'z profilini tahrirlash",
        description="Rol va bloklash holati bu endpoint orqali o'zgartirilmaydi.",
        request=UserUpdateSerializer,
        responses={200: UserSerializer},
    ),
)
@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def me(request):
    """Read or update the authenticated account."""
    if request.method == "GET":
        return Response(UserSerializer(request.user).data)

    user = user_services.update_user_profile(
        request.user,
        first_name=request.data.get("first_name"),
        last_name=request.data.get("last_name"),
        phone_number=request.data.get("phone_number"),
        language_code=request.data.get("language_code"),
    )
    return Response(UserSerializer(user).data)


@extend_schema(
    summary="Telegram orqali ro'yxatdan o'tish",
    description=(
        "Bot yoki Mini App uchun. `telegram_id` bo'yicha mavjud hisob qaytariladi, "
        "yo'q bo'lsa yangi yaratiladi. Bot tokeni tekshiruvi transport qatlamida "
        "amalga oshiriladi."
    ),
    request=TelegramRegistrationSerializer,
    responses={
        201: OpenApiResponse(UserSerializer, description="Yangi hisob yaratildi."),
        200: OpenApiResponse(UserSerializer, description="Mavjud hisob qaytarildi."),
        403: OpenApiResponse(description="Hisob bloklangan."),
    },
)
@api_view(["POST"])
@permission_classes([AllowAny])
def register_telegram(request):
    """Idempotent registration endpoint used by the Telegram layer."""
    serializer = TelegramRegistrationSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    user, created = user_services.get_or_create_user_from_telegram(
        telegram_id=data["telegram_id"],
        username=data.get("username"),
        first_name=data.get("first_name", ""),
        last_name=data.get("last_name", ""),
        phone_number=data.get("phone_number", ""),
        language_code=data.get("language_code"),
    )
    if user.is_blocked:
        raise UserIsBlocked()

    token, _ = Token.objects.get_or_create(user=user)
    response_data = {
        "user": UserSerializer(user).data,
        "token": token.key,
        "is_new": created,
    }
    return Response(response_data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


@extend_schema(
    summary="Rolni o'zgartirish",
    description="`passenger`, `driver` yoki `both`. Haydovchi roli `DriverProfile` yaratadi.",
    request=UserRoleUpdateSerializer,
    responses={200: UserSerializer},
)
@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def set_role(request):
    """Self-service role switching (business rules enforced in the service)."""
    serializer = UserRoleUpdateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    user = user_services.set_user_role(request.user, serializer.validated_data["role"])
    return Response(UserSerializer(user).data)
