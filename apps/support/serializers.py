"""Serializers for the support app."""

from __future__ import annotations

from rest_framework import serializers

from apps.support.models import SupportMessage, SupportTicket


class SupportMessageSerializer(serializers.ModelSerializer):
    sender_name = serializers.CharField(source="sender.display_name", read_only=True)
    is_mine = serializers.SerializerMethodField()

    class Meta:
        model = SupportMessage
        fields = ("id", "ticket", "sender", "sender_name", "body", "is_from_support", "attachment_url", "is_mine", "created_at")
        read_only_fields = ("id", "ticket", "sender", "sender_name", "is_from_support", "is_mine", "created_at")

    def get_is_mine(self, obj: SupportMessage) -> bool:
        request = self.context.get("request")
        return bool(request and request.user.is_authenticated and obj.sender_id == request.user.pk)


class SupportTicketSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    user_name = serializers.SerializerMethodField()

    class Meta:
        model = SupportTicket
        fields = (
            "id",
            "user_name",
            "order",
            "subject",
            "category",
            "priority",
            "status",
            "status_display",
            "is_anonymous",
            "last_message_at",
            "created_at",
        )
        read_only_fields = ("id", "user_name", "status", "status_display", "last_message_at", "created_at")

    def get_user_name(self, obj: SupportTicket) -> str:
        if obj.is_anonymous:
            return "Anonim"
        return obj.user.display_name


class SupportTicketCreateSerializer(serializers.Serializer):
    subject = serializers.CharField(max_length=200)
    category = serializers.ChoiceField(
        choices=["payment", "subscription", "ride", "verification", "account", "technical", "other"],
        default="other",
    )
    body = serializers.CharField(max_length=4000)
    order_id = serializers.IntegerField(required=False, allow_null=True)
    is_anonymous = serializers.BooleanField(required=False, default=False)


class SupportMessageCreateSerializer(serializers.Serializer):
    body = serializers.CharField(max_length=4000)
    attachment_url = serializers.URLField(required=False, allow_blank=True)
