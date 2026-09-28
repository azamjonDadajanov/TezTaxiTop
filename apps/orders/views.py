"""REST API views for the orders app.

The viewset is intentionally thin: it resolves the target order, delegates to
``apps.orders.services`` and serialises the result. No state transition logic
lives here.
"""

from __future__ import annotations

from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.exceptions import BusinessError, ResourceNotFound
from apps.orders import selectors as order_selectors
from apps.orders import services as order_services
from apps.orders.models import Order, OrderStatus
from apps.orders.permissions import IsOrderDriver, IsOrderParticipant
from apps.orders.serializers import (
    OrderCancelSerializer,
    OrderCreateSerializer,
    OrderSerializer,
)
from apps.rides.selectors import get_trip_by_id


def _raise_business(exc: BusinessError) -> DRFValidationError:
    return DRFValidationError({"detail": exc.message, "code": exc.code, "details": exc.details})


@extend_schema_view(
    list=extend_schema(
        summary="Buyurtmalar ro'yxati",
        description="Faqat foydalanuvchining o'z buyurtmalari (haydovchi va yo'lovchi sifatida).",
        parameters=[
            OpenApiParameter("search", str, description="Yo'lovchi ismi, telefon yoki davlat raqami."),
            OpenApiParameter("status", str, description="pending / accepted / completed ..."),
            OpenApiParameter("role", str, description="passenger | driver"),
        ],
        responses={200: OrderSerializer(many=True)},
    ),
    retrieve=extend_schema(summary="Buyurtma", responses={200: OrderSerializer}),
)
class OrderViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    queryset = order_selectors.get_order_queryset()
    serializer_class = OrderSerializer
    permission_classes = [IsAuthenticated, IsOrderParticipant]
    filterset_fields = ["status", "trip", "passenger"]
    search_fields = order_selectors.ORDER_SEARCH_FIELDS
    ordering_fields = order_selectors.ORDER_ORDERING_FIELDS
    ordering = ["-created_at"]

    def get_queryset(self):
        user = self.request.user
        queryset = super().get_queryset()
        if user.is_staff:
            return queryset

        driver_profile = getattr(user, "driver_profile", None)
        role = self.request.query_params.get("role")
        if role == "driver":
            if driver_profile is None:
                return queryset.none()
            queryset = queryset.filter(trip__driver=driver_profile)
        elif role == "passenger":
            queryset = queryset.filter(passenger=user)
        else:
            from django.db.models import Q

            condition = Q(passenger=user)
            if driver_profile is not None:
                condition |= Q(trip__driver=driver_profile)
            queryset = queryset.filter(condition)
        return order_selectors.search_orders(queryset, self.request.query_params.get("search"))

    def create(self, request, *args, **kwargs):
        serializer = OrderCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        companion = data.pop("companion", None)

        trip = get_trip_by_id(data.pop("trip"))
        if trip is None:
            raise ResourceNotFound("Yo'lov topilmadi.")

        try:
            order = order_services.create_order(
                passenger=request.user, trip=trip, **data, companion=companion
            )
        except BusinessError as exc:
            raise _raise_business(exc) from exc
        return Response(OrderSerializer(order).data, status=status.HTTP_201_CREATED)

    # -- driver side actions --------------------------------------------------
    @extend_schema(summary="Buyurtmani qabul qilish (o'rinlar band qilinadi)", request=None, responses={200: OrderSerializer})
    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated, IsOrderDriver])
    def accept(self, request, pk=None) -> Response:
        try:
            order = order_services.accept_order(self.get_object())
        except BusinessError as exc:
            raise _raise_business(exc) from exc
        return Response(OrderSerializer(order).data)

    @extend_schema(
        summary="Buyurtmani rad etish",
        request=OrderCancelSerializer,
        responses={200: OrderSerializer},
    )
    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated, IsOrderDriver])
    def reject(self, request, pk=None) -> Response:
        serializer = OrderCancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            order = order_services.reject_order(
                self.get_object(), reason=serializer.validated_data.get("reason", "")
            )
        except BusinessError as exc:
            raise _raise_business(exc) from exc
        return Response(OrderSerializer(order).data)

    @extend_schema(summary="Haydovchi yetib keldi", request=None, responses={200: OrderSerializer})
    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated, IsOrderDriver])
    def arrived(self, request, pk=None) -> Response:
        try:
            order = order_services.mark_driver_arrived(self.get_object())
        except BusinessError as exc:
            raise _raise_business(exc) from exc
        return Response(OrderSerializer(order).data)

    @extend_schema(summary="Yo'lni boshlash", request=None, responses={200: OrderSerializer})
    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated, IsOrderDriver])
    def start(self, request, pk=None) -> Response:
        try:
            order = order_services.start_order(self.get_object())
        except BusinessError as exc:
            raise _raise_business(exc) from exc
        return Response(OrderSerializer(order).data)

    @extend_schema(summary="Buyurtmani yakunlash", request=None, responses={200: OrderSerializer})
    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated, IsOrderDriver])
    def complete(self, request, pk=None) -> Response:
        try:
            order = order_services.complete_order(self.get_object())
        except BusinessError as exc:
            raise _raise_business(exc) from exc
        return Response(OrderSerializer(order).data)

    @extend_schema(
        summary="Yo'lovchi kelmadi (no-show)",
        request=OrderCancelSerializer,
        responses={200: OrderSerializer},
    )
    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated, IsOrderDriver])
    def no_show(self, request, pk=None) -> Response:
        serializer = OrderCancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            order = order_services.mark_no_show(
                self.get_object(), reason=serializer.validated_data.get("reason", "")
            )
        except BusinessError as exc:
            raise _raise_business(exc) from exc
        return Response(OrderSerializer(order).data)

    # -- passenger side actions -----------------------------------------------
    @extend_schema(
        summary="Buyurtmani bekor qilish (yo'lovchi)",
        request=OrderCancelSerializer,
        responses={200: OrderSerializer},
    )
    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request, pk=None) -> Response:
        serializer = OrderCancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = self.get_object()
        user = request.user
        driver_profile = getattr(user, "driver_profile", None)
        is_driver = driver_profile is not None and driver_profile.pk == order.trip.driver_id
        try:
            if is_driver:
                order = order_services.cancel_order_by_driver(
                    order, reason=serializer.validated_data.get("reason", "")
                )
            else:
                order = order_services.cancel_order_by_passenger(
                    order, reason=serializer.validated_data.get("reason", "")
                )
        except BusinessError as exc:
            raise _raise_business(exc) from exc
        return Response(OrderSerializer(order).data)

    @extend_schema(
        summary="Buyurtma xabarlari",
        description="Bu buyurtma doirasidagi xabarlar (suhbat).",
        responses={200: "apps.chat.serializers.OrderMessageSerializer(many=True)"},
    )
    @action(detail=True, methods=["get"])
    def messages(self, request, pk=None) -> Response:
        from apps.chat.serializers import OrderMessageSerializer

        order = self.get_object()
        from apps.chat.services import list_order_messages

        return Response(OrderMessageSerializer(list_order_messages(order), many=True).data)

    @extend_schema(summary="Mening buyurtmalarim", responses={200: OrderSerializer(many=True)})
    @action(detail=False, methods=["get"])
    def my_orders(self, request) -> Response:
        role = request.query_params.get("role", "passenger")
        if role == "driver":
            driver_profile = getattr(request.user, "driver_profile", None)
            orders = (
                order_selectors.get_orders_by_driver(driver_profile)
                if driver_profile is not None
                else Order.objects.none()
            )
        else:
            orders = order_selectors.get_orders_by_passenger(request.user)
        return Response(OrderSerializer(orders, many=True).data)


@extend_schema_view(
    get=extend_schema(
        summary="Reyting uchun kutilayotgan buyurtmalarim",
        description="Yakunlangan va hali baholanmagan buyurtmalar.",
        responses={200: OrderSerializer(many=True)},
    )
)
class ReviewableOrdersView(APIView):
    """Helper endpoint that powers the "rate your driver" flow."""

    permission_classes = [IsAuthenticated]
    serializer_class = OrderSerializer

    def get(self, request) -> Response:
        orders = order_selectors.get_reviewable_orders(request.user)
        return Response(OrderSerializer(orders, many=True).data)
