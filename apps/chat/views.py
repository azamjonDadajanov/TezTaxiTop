"""REST API views for the chat app (polling based)."""

from __future__ import annotations

from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import status, viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.chat import selectors as chat_selectors
from apps.chat import services as chat_services
from apps.chat.serializers import (
    ChatMessageCreateSerializer,
    ChatMessageSerializer,
    ChatReadResponseSerializer,
    ChatThreadListSerializer,
    ChatThreadSerializer,
    OpenChatRequestSerializer,
)
from apps.core.exceptions import BusinessError
from apps.orders.selectors import get_order_by_id


def _handle_business_error(exc: BusinessError):
    from rest_framework.exceptions import ValidationError as DRFValidationError

    return DRFValidationError({"detail": exc.message, "code": exc.code, "details": exc.details})


@extend_schema_view(
    post=extend_schema(
        summary="Suhbatni ochish yoki yaratish",
        description=(
            "Buyurtma (order_id), yo'lov (trip_id) yoki so'rov (request_id) bo'yicha "
            "suhbatni ochadi yoki yaratadi. Agar suhbat allaqachon mavjud bo'lsa, "
            "dublikat yaratmasdan mavjudini qaytaradi."
        ),
        request=OpenChatRequestSerializer,
        responses={200: ChatThreadSerializer, 201: ChatThreadSerializer},
    )
)
class OpenChatView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request) -> Response:
        serializer = OpenChatRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            thread, created = chat_services.get_or_create_conversation(
                user=request.user,
                order_id=data.get("order_id"),
                trip_id=data.get("trip_id"),
                request_id=data.get("request_id"),
            )
        except BusinessError as exc:
            raise _handle_business_error(exc) from exc

        status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        thread_data = ChatThreadSerializer(thread, context={"request": request}).data
        return Response(
            {
                "thread": thread_data,
                "order_id": thread.order_id,
                "created": created,
            },
            status=status_code,
        )


@extend_schema_view(
    get=extend_schema(
        summary="Suhbatlar ro'yxati",
        description="Haydovchi yoki yo'lovchi bo'lgan barcha buyurtmalar suhbatlari.",
        responses={200: ChatThreadListSerializer},
    )
)
class ChatThreadListView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ChatThreadListSerializer

    def get(self, request) -> Response:
        rows = chat_selectors.get_threads_with_stats(request.user)
        serializer = ChatThreadSerializer([row["thread"] for row in rows], many=True, context={"request": request})
        data = serializer.data
        for item, row in zip(data, rows):
            item["unread_count"] = row["unread"]
        return Response(data)


@extend_schema_view(
    get=extend_schema(
        summary="Xabarlar ro'yxati",
        description=(
            "Polling uchun: `?after=<message_id>` parametri orqali faqat yangi xabarlar "
            "qaytariladi. Javob `next_after_id` maydoni bilan keyingi so'rov uchun "
            "kursor beradi."
        ),
        parameters=[
            OpenApiParameter(
                name="after",
                type=int,
                required=False,
                description="Oxirgi ko'rilgan xabar id; undan keyingi xabarlar qaytariladi.",
            )
        ],
        responses={200: ChatMessageSerializer(many=True)},
    ),
    post=extend_schema(
        summary="Xabar yuborish",
        request=ChatMessageCreateSerializer,
        responses={201: ChatMessageSerializer},
    ),
)
class ChatMessageView(APIView):
    permission_classes = [IsAuthenticated]

    def _get_thread(self, request, order_id: int):
        order = get_order_by_id(order_id)
        if order is None:
            from apps.core.exceptions import ResourceNotFound

            raise ResourceNotFound("Buyurtma topilmadi.")
        if not order.is_participant(request.user):
            raise PermissionDenied("Bu buyurtma suhbatiga kirish huquqingiz yo'q.")
        return chat_services.get_or_create_thread(order)

    @extend_schema(
        summary="Xabarlarni olish",
        parameters=[{"name": "after", "type": "integer", "required": False, "description": "Oxirgi ko'rilgan xabar id"}],
        responses={200: ChatMessageSerializer(many=True)},
    )
    def get(self, request, order_id: int) -> Response:
        thread = self._get_thread(request, order_id)
        try:
            after = int(request.query_params.get("after") or 0)
        except (TypeError, ValueError):
            after = 0

        messages = list(chat_selectors.get_messages_for_thread(thread, after_id=after or None, limit=100))
        chat_services.mark_messages_read(thread, request.user)
        payload = {
            "results": ChatMessageSerializer(messages, many=True, context={"request": request}).data,
            "next_after_id": messages[-1].id if messages else after or 0,
            "is_closed": thread.is_closed,
        }
        return Response(payload)

    def post(self, request, order_id: int) -> Response:
        thread = self._get_thread(request, order_id)
        serializer = ChatMessageCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            message = chat_services.send_message(
                thread=thread,
                sender=request.user,
                text=data["text"],
                message_type=data.get("type", "text"),
            )
        except BusinessError as exc:
            raise _handle_business_error(exc) from exc
        return Response(
            ChatMessageSerializer(message, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


@extend_schema_view(
    post=extend_schema(
        summary="Xabarlarni o'qilgan deb belgilash",
        description="Barcha xabarlarni o'qilgan deb belgilaydi (idempotent).",
        request=None,
        responses={200: ChatReadResponseSerializer},
    )
)
class ChatReadView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ChatReadResponseSerializer

    def post(self, request, order_id: int) -> Response:
        order = get_order_by_id(order_id)
        if order is None:
            from apps.core.exceptions import ResourceNotFound

            raise ResourceNotFound("Buyurtma topilmadi.")
        if not order.is_participant(request.user):
            raise PermissionDenied("Bu buyurtma suhbatiga kirish huquqingiz yo'q.")
        thread = chat_services.get_or_create_thread(order)
        updated = chat_services.mark_messages_read(thread, request.user)
        return Response({"marked_read": updated})
