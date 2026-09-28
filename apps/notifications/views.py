"""REST API views for the notifications app."""

from __future__ import annotations

from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.notifications import selectors as notification_selectors
from apps.notifications import services as notification_services
from apps.notifications.models import Notification
from apps.notifications.serializers import MarkReadSerializer, NotificationSerializer


@extend_schema_view(
    list=extend_schema(summary="Bildirishnomalar ro'yxati", responses={200: NotificationSerializer(many=True)}),
    retrieve=extend_schema(summary="Bildirishnoma", responses={200: NotificationSerializer}),
    partial_update=extend_schema(
        summary="Bildirishnomani o'qilgan deb belgilash",
        request=NotificationSerializer,
        responses={200: NotificationSerializer},
    ),
)
class NotificationViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "patch", "head", "options"]
    filterset_fields = ["type", "is_read"]
    ordering_fields = ["id", "created_at"]
    ordering = ["-created_at"]

    def get_queryset(self):
        # A user can only ever see their own notifications.
        if getattr(self, "swagger_fake_view", False):
            # drf-spectacular builds the schema with an anonymous user; return an
            # empty queryset instead of raising on the user filter.
            return Notification.objects.none()
        return notification_selectors.get_notifications_for_user(self.request.user)

    def partial_update(self, request, *args, **kwargs):
        notification = self.get_object()
        if request.data.get("is_read"):
            notification_services.mark_as_read(notification)
        return Response(self.get_serializer(notification).data)

    @extend_schema(
        summary="O'qilgan deb belgilash",
        request=MarkReadSerializer,
        responses={200: {"type": "object", "properties": {"updated": {"type": "integer"}}}},
    )
    @action(detail=False, methods=["post"])
    def mark_read(self, request) -> Response:
        serializer = MarkReadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if data.get("mark_all"):
            updated = notification_services.mark_all_as_read(request.user)
        else:
            updated = 0
            for notification_id in data.get("notification_ids", []):
                notification = notification_selectors.get_notification_by_id(notification_id)
                if notification is not None and notification.user_id == request.user.pk:
                    notification_services.mark_as_read(notification)
                    updated += 1
        return Response({"updated": updated})

    @extend_schema(summary="O'qilmagan bildirishnomalar soni", responses={200: {"type": "object"}})
    @action(detail=False, methods=["get"])
    def unread_count(self, request) -> Response:
        return Response({"unread": notification_selectors.get_unread_count(request.user)})


@extend_schema_view(
    post=extend_schema(
        summary="Tizim bildirishnomasi yuborish",
        description="Faqat staff foydalanuvchilar uchun.",
        responses={201: NotificationSerializer},
    )
)
class SystemNotificationView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request) -> Response:
        if not request.user.is_staff:
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("Faqat administratorlar tizim xabarini yubora oladi.")
        notification = notification_services.create_notification(
            user=request.user,
            notification_type="system",
            title=request.data.get("title", "Tizim xabari"),
            message=request.data.get("message", ""),
        )
        return Response(NotificationSerializer(notification).data, status=201)
