"""Serializers for the payments app."""

from __future__ import annotations

from rest_framework import serializers

from apps.payments.models import Payment, PaymentProvider, PaymentStatus, PaymentType


class PaymentSerializer(serializers.ModelSerializer):
    """Read representation. ``status`` is always read-only."""

    user_name = serializers.CharField(source="user.display_name", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    provider_display = serializers.CharField(source="get_provider_display", read_only=True)
    payment_type_display = serializers.CharField(source="get_payment_type_display", read_only=True)

    class Meta:
        model = Payment
        fields = (
            "id",
            "user",
            "user_name",
            "payment_type",
            "payment_type_display",
            "amount",
            "provider",
            "provider_display",
            "external_transaction_id",
            "status",
            "status_display",
            "paid_at",
            "failure_reason",
            "refunded_at",
            "metadata",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class PaymentCreateSerializer(serializers.Serializer):
    """Create a pending payment.

    ``status``, ``paid_at`` and ``metadata`` are intentionally absent: a client
    can never declare its own payment successful.
    """

    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0)
    payment_type = serializers.ChoiceField(
        choices=PaymentType.choices, default=PaymentType.SUBSCRIPTION
    )
    provider = serializers.ChoiceField(choices=PaymentProvider.choices, default=PaymentProvider.CLICK)
    description = serializers.CharField(required=False, allow_blank=True, max_length=255)


class PaymentConfirmSerializer(serializers.Serializer):
    """Admin-only manual confirmation (used for cash payments)."""

    payment_id = serializers.IntegerField()


class PaymentRefundSerializer(serializers.Serializer):
    amount = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, allow_null=True, min_value=0
    )
    reason = serializers.CharField(required=False, allow_blank=True, max_length=255)


class ProviderCallbackSerializer(serializers.Serializer):
    """Webhook payload shape (the exact keys differ per provider)."""

    provider = serializers.ChoiceField(choices=PaymentProvider.choices)
    external_transaction_id = serializers.CharField(max_length=120)
    payload = serializers.DictField(required=False, default=dict)
