"""Authentication and "current user" endpoints."""

from __future__ import annotations

from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from apps.users import services as user_services
from apps.users.serializers import (
    TelegramMiniAppAuthSerializer,
    UserRoleUpdateSerializer,
    UserSerializer,
    UserUpdateSerializer,
)
from apps.users.services import UserIsBlocked
from apps.users.telegram_auth import InvalidTelegramInitData, validate_telegram_init_data


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
    summary="Telegram Mini App orqali kirish",
    description="Telegram imzolagan `initData` tekshiriladi; brauzerdagi Telegram ID hech qachon ishonchli deb olinmaydi.",
    request=TelegramMiniAppAuthSerializer,
    responses={
        201: OpenApiResponse(UserSerializer, description="Yangi hisob yaratildi."),
        200: OpenApiResponse(UserSerializer, description="Mavjud hisob qaytarildi."),
        403: OpenApiResponse(description="Hisob bloklangan."),
    },
)
@api_view(["POST"])
@permission_classes([AllowAny])
def telegram_mini_app_auth(request):
    """Verify signed Mini App data and issue the account's DRF token."""
    serializer = TelegramMiniAppAuthSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    from django.conf import settings

    try:
        telegram_user = validate_telegram_init_data(
            serializer.validated_data["init_data"],
            settings.TELEGRAM_BOT_TOKEN,
        )
    except InvalidTelegramInitData as error:
        raise ValidationError({"init_data": str(error)}) from error

    user, created = user_services.get_or_create_user_from_telegram(
        telegram_id=telegram_user["id"],
        username=telegram_user.get("username"),
        first_name=telegram_user.get("first_name", ""),
        last_name=telegram_user.get("last_name", ""),
        language_code=telegram_user.get("language_code"),
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


register_telegram = telegram_mini_app_auth


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
