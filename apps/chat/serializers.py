"""Serializers for the chat app."""

from __future__ import annotations

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.chat.models import ChatMessage, ChatThread


class ChatMessageSerializer(serializers.ModelSerializer):
    sender_name = serializers.CharField(source="sender.display_name", read_only=True)
    is_mine = serializers.SerializerMethodField()

    class Meta:
        model = ChatMessage
        fields = ("id", "thread", "sender", "sender_name", "type", "text", "is_read", "read_at", "is_mine", "created_at")
        read_only_fields = fields

    def get_is_mine(self, obj: ChatMessage) -> bool:
        request = self.context.get("request")
        if request is None or not request.user.is_authenticated:
            return False
        return obj.sender_id == request.user.pk


class ChatMessageCreateSerializer(serializers.Serializer):
    text = serializers.CharField(max_length=2000, allow_blank=False, trim_whitespace=True)
    type = serializers.ChoiceField(choices=ChatMessage._meta.get_field("type").choices, default="text")


class ChatThreadSerializer(serializers.ModelSerializer):
    order_id = serializers.IntegerField(read_only=True)
    counterpart_name = serializers.SerializerMethodField()
    counterpart_id = serializers.SerializerMethodField()
    last_message = serializers.SerializerMethodField()
    unread_count = serializers.SerializerMethodField()
    is_closed = serializers.BooleanField(read_only=True)

    class Meta:
        model = ChatThread
        fields = (
            "id",
            "order_id",
            "counterpart_id",
            "counterpart_name",
            "last_message",
            "unread_count",
            "is_closed",
            "last_message_at",
            "created_at",
        )
        read_only_fields = fields

    def _counterpart(self, obj: ChatThread):
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return None
        return obj.order.passenger if obj.order.driver_user_id == user.pk else obj.order.trip.driver.user

    def get_counterpart_id(self, obj: ChatThread) -> int | None:
        counterpart = self._counterpart(obj)
        return counterpart.pk if counterpart else None

    def get_counterpart_name(self, obj: ChatThread) -> str | None:
        counterpart = self._counterpart(obj)
        return counterpart.display_name if counterpart else None

    @extend_schema_field(ChatMessageSerializer(allow_null=True))
    def get_last_message(self, obj: ChatThread):
        from apps.chat.selectors import get_last_message

        message = get_last_message(obj)
        return ChatMessageSerializer(message, context=self.context).data if message else None

    def get_unread_count(self, obj: ChatThread) -> int:
        from apps.chat.selectors import get_unread_count_for_thread

        user = getattr(self.context.get("request"), "user", None)
        if user is None or not user.is_authenticated:
            return 0
        return get_unread_count_for_thread(obj, user)


class ChatThreadListSerializer(ChatThreadSerializer):
    """Thread list entry with the unread counter filled in by the view."""

    unread_count = serializers.IntegerField(read_only=True)


class ChatReadResponseSerializer(serializers.Serializer):
    """Result of marking a whole thread as read."""

    marked_read = serializers.IntegerField(
        help_text="Bu chaqiruvda o'qilgan deb belgilangan xabarlar soni."
    )


class OpenChatRequestSerializer(serializers.Serializer):
    """Payload for opening or creating a conversation."""

    order_id = serializers.IntegerField(required=False, allow_null=True)
    trip_id = serializers.IntegerField(required=False, allow_null=True)
    request_id = serializers.IntegerField(required=False, allow_null=True)

    def validate(self, attrs):
        if not any(attrs.get(k) is not None for k in ("order_id", "trip_id", "request_id")):
            raise serializers.ValidationError(
                "Kamida bitta parametr ko'rsatilishi shart (order_id, trip_id yoki request_id)."
            )
        return attrs