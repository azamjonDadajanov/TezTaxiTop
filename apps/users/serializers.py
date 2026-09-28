"""Serializers for the users app.

Serializers only translate data. All business rules are enforced in
``apps.users.services`` (write) and ``apps.users.selectors`` (read), which the
views call explicitly.
"""

from __future__ import annotations

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.users.constants import UserRole
from apps.users.models import DriverProfile, User


class TelegramRegistrationSerializer(serializers.Serializer):
    """Input of ``POST /api/v1/auth/register-telegram/``."""

    telegram_id = serializers.IntegerField(min_value=1)
    username = serializers.CharField(max_length=150, required=False, allow_blank=True, allow_null=True)
    first_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    phone_number = serializers.CharField(max_length=20, required=False, allow_blank=True)
    language_code = serializers.CharField(max_length=10, required=False, allow_blank=True)

    def validate_telegram_id(self, value: int) -> int:
        # Telegram ids are 32 bit unsigned; anything larger is a client error.
        if value > 2_147_483_647:
            raise serializers.ValidationError("Telegram ID 32 bitli butun son bo'lishi kerak.")
        return value


class DriverProfileSerializer(serializers.ModelSerializer):
    """Read representation of a driver profile."""

    user_id = serializers.IntegerField(read_only=True)
    username = serializers.CharField(source="user.username", read_only=True)
    full_name = serializers.CharField(source="user.display_name", read_only=True)
    phone_number = serializers.CharField(source="user.phone_number", read_only=True)
    telegram_id = serializers.IntegerField(source="user.telegram_id", read_only=True)
    vehicles_count = serializers.IntegerField(read_only=True, required=False)
    has_active_subscription = serializers.SerializerMethodField()
    subscription_expires_at = serializers.SerializerMethodField()

    class Meta:
        model = DriverProfile
        fields = (
            "id",
            "user_id",
            "username",
            "full_name",
            "phone_number",
            "telegram_id",
            "is_verified",
            "verified_at",
            "rating",
            "rating_count",
            "total_trips",
            "completed_trips",
            "cancelled_trips",
            "bio",
            "vehicles_count",
            "has_active_subscription",
            "subscription_expires_at",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_has_active_subscription(self, obj: DriverProfile) -> bool:
        # Imported lazily to avoid a circular import between apps.
        from apps.subscriptions.services import has_active_subscription

        return has_active_subscription(obj)

    @extend_schema_field(serializers.DateTimeField(allow_null=True))
    def get_subscription_expires_at(self, obj: DriverProfile):
        from apps.subscriptions.selectors import get_active_subscription

        subscription = get_active_subscription(obj)
        return subscription.expires_at if subscription else None


class UserSerializer(serializers.ModelSerializer):
    """Full read representation of an account."""

    full_name = serializers.CharField(source="display_name", read_only=True)
    role_display = serializers.CharField(source="get_role_display", read_only=True)
    driver_profile = DriverProfileSerializer(read_only=True)

    class Meta:
        model = User
        fields = (
            "id",
            "telegram_id",
            "username",
            "first_name",
            "last_name",
            "full_name",
            "phone_number",
            "role",
            "role_display",
            "is_active",
            "is_blocked",
            "is_staff",
            "language_code",
            "last_seen_at",
            "driver_profile",
            "date_joined",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class UserUpdateSerializer(serializers.ModelSerializer):
    """Self-service update.

    ``role``, ``telegram_id``, ``is_blocked`` and permission flags are excluded
    on purpose: role changes must go through ``set_user_role`` and moderation
    through the admin / dedicated service functions.
    """

    class Meta:
        model = User
        fields = ("first_name", "last_name", "phone_number", "language_code")
        extra_kwargs = {
            "first_name": {"required": False, "allow_blank": True},
            "last_name": {"required": False, "allow_blank": True},
            "phone_number": {"required": False, "allow_blank": True},
            "language_code": {"required": False, "allow_blank": True},
        }


class UserRoleUpdateSerializer(serializers.Serializer):
    """Role change request - still validated by the service layer."""

    role = serializers.ChoiceField(choices=UserRole.choices)


class DriverProfileUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = DriverProfile
        fields = ("bio",)
        extra_kwargs = {"bio": {"required": False, "allow_blank": True}}
