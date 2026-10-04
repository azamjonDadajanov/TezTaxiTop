"""REST API views for the support app."""

from __future__ import annotations

from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import status, viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.orders.selectors import get_order_by_id
from apps.support import selectors as support_selectors
from apps.support import services as support_services
from apps.support.models import SupportTicket, TicketStatus
from apps.support.serializers import (
    SupportMessageCreateSerializer,
    SupportMessageSerializer,
    SupportTicketCreateSerializer,
    SupportTicketSerializer,
)


@extend_schema_view(
    list=extend_schema(
        summary="Mening murojaatlarim",
        description="Staff foydalanuvchilar uchun barcha murojaatlar qaytariladi.",
        responses={200: SupportTicketSerializer(many=True)},
    ),
    retrieve=extend_schema(summary="Murojaat", responses={200: SupportTicketSerializer}),
    create=extend_schema(
        summary="Murojaat yaratish",
        request=SupportTicketCreateSerializer,
        responses={201: SupportTicketSerializer},
    ),
)
class SupportTicketViewSet(viewsets.ModelViewSet):
    serializer_class = SupportTicketSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "patch", "head", "options"]
    filterset_fields = ["status", "category", "priority"]
    ordering_fields = ["id", "created_at", "last_message_at", "priority"]
    ordering = ["-last_message_at"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            # Schema generation runs with an anonymous user; an empty queryset
            # keeps drf-spectacular from raising while it introspects.
            return SupportTicket.objects.none()
        user = self.request.user
        if user.is_staff:
            queryset = support_selectors.get_all_tickets()
        else:
            queryset = support_selectors.get_tickets_for_user(user)
        return support_selectors.search_tickets(queryset, self.request.query_params.get("search"))

    def create(self, request, *args, **kwargs):
        serializer = SupportTicketCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        order = None
        if data.get("order_id"):
            order = get_order_by_id(data["order_id"])
            if order is not None and not order.is_participant(request.user):
                raise PermissionDenied("Bu buyurtma bilan bog'liq murojaat yaratish huquqingiz yo'q.")

        ticket = support_services.create_ticket(
            user=request.user,
            subject=data["subject"],
            category=data.get("category", "other"),
            order=order,
            is_anonymous=data.get("is_anonymous", False),
        )
        support_services.add_message(ticket=ticket, sender=request.user, body=data["body"])
        return Response(SupportTicketSerializer(ticket).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        ticket = self.get_object()
        new_status = request.data.get("status")
        if new_status is None:
            return Response(SupportTicketSerializer(ticket).data)
        ticket = support_services.set_ticket_status(ticket, new_status, actor=request.user)
        return Response(SupportTicketSerializer(ticket).data)


@extend_schema_view(
    get=extend_schema(summary="Murojaat xabarlari", responses={200: SupportMessageSerializer(many=True)}),
    post=extend_schema(
        summary="Murojaatga xabar yozish",
        description="Staff javob yozishi mumkin, foydalanuvchi esa o'z murojaatiga.",
        request=SupportMessageCreateSerializer,
        responses={201: SupportMessageSerializer},
    ),
)
class SupportMessageView(APIView):
    permission_classes = [IsAuthenticated]

    def _get_ticket(self, request, ticket_id: int):
        ticket = support_selectors.get_ticket_by_id(ticket_id)
        if ticket is None:
            from apps.core.exceptions import ResourceNotFound

            raise ResourceNotFound("Murojaat topilmadi.")
        if ticket.user_id != request.user.pk and not request.user.is_staff:
            raise PermissionDenied("Bu murojaatga kirish huquqingiz yo'q.")
        return ticket

    def get(self, request, ticket_id: int) -> Response:
        ticket = self._get_ticket(request, ticket_id)
        messages = support_selectors.get_messages_for_ticket(ticket)
        return Response(
            SupportMessageSerializer(messages, many=True, context={"request": request}).data
        )

    def post(self, request, ticket_id: int) -> Response:
        ticket = self._get_ticket(request, ticket_id)
        serializer = SupportMessageCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        message = support_services.add_message(
                ticket=ticket,
                sender=request.user,
                body=data["body"],
                is_from_support=request.user.is_staff,
                attachment_url=data.get("attachment_url", ""),
            )
        return Response(
            SupportMessageSerializer(message, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


@extend_schema_view(
    get=extend_schema(summary="Statistika", responses={200: {"type": "object"}}),
)
class SupportStatsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request) -> Response:
        if not request.user.is_staff:
            raise PermissionDenied("Faqat administratorlar statistikani ko'ra oladi.")
        from django.db.models import Count

        rows = (
            support_selectors.get_all_tickets()
            .values("status")
            .annotate(total=Count("id"))
        )
        return Response(
            {
                "by_status": {row["status"]: row["total"] for row in rows},
                "total": support_selectors.get_all_tickets().count(),
                "open": support_selectors.get_tickets_by_status(TicketStatus.OPEN).count(),
            }
        )
