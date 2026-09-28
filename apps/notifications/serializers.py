"""Serializers for the notifications app."""

from __future__ import annotations

from rest_framework import serializers

from apps.notifications.models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    type_display = serializers.CharField(source="get_type_display", read_only=True)

    class Meta:
        model = Notification
        fields = (
            "id",
            "type",
            "type_display",
            "title",
            "message",
            "is_read",
            "is_sent",
            "sent_at",
            "created_at",
        )
        read_only_fields = fields


class MarkReadSerializer(serializers.Serializer):
    """Payload for the bulk "mark as read" action."""

    notification_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False, allow_empty=True
    )
    mark_all = serializers.BooleanField(required=False, default=False)
