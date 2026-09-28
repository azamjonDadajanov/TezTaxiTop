"""Serializers for the subscriptions app."""

from __future__ import annotations

from rest_framework import serializers

from apps.subscriptions.models import DriverSubscription, SubscriptionPlan


class SubscriptionPlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubscriptionPlan
        fields = (
            "id",
            "name",
            "duration_days",
            "price",
            "description",
            "is_active",
            "sort_order",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")


class SubscriptionPlanWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubscriptionPlan
        fields = ("name", "duration_days", "price", "description", "is_active", "sort_order")
        extra_kwargs = {
            "duration_days": {"min_value": 1},
            "price": {"min_value": 0},
            "description": {"required": False, "allow_blank": True},
            "is_active": {"required": False, "default": True},
            "sort_order": {"required": False, "default": 0},
        }


class DriverSubscriptionSerializer(serializers.ModelSerializer):
    """Read representation including the snapshotted purchase price."""

    driver_name = serializers.CharField(source="driver.user.display_name", read_only=True)
    plan_name = serializers.CharField(source="plan.name", read_only=True)
    plan_duration_days = serializers.IntegerField(source="plan.duration_days", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    days_remaining = serializers.IntegerField(read_only=True)
    is_active_now = serializers.SerializerMethodField()

    class Meta:
        model = DriverSubscription
        fields = (
            "id",
            "driver",
            "driver_name",
            "plan",
            "plan_name",
            "plan_duration_days",
            "starts_at",
            "expires_at",
            "days_remaining",
            "status",
            "status_display",
            "is_active_now",
            "price_at_purchase",
            "auto_renew",
            "payment",
            "activated_at",
            "cancelled_at",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_is_active_now(self, obj: DriverSubscription) -> bool:
        return obj.is_active_now()


class SubscriptionPurchaseSerializer(serializers.Serializer):
    """Payload of ``POST /api/v1/subscriptions/purchase/``."""

    plan_id = serializers.IntegerField()
    auto_renew = serializers.BooleanField(required=False, default=False)
