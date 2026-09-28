"""REST API views for the payments app.

Security notes
--------------
* ``verify``, ``confirm`` and ``refund`` are staff-only: a client can request a
  payment but can never mark it successful.
* Webhooks come in through :func:`apps.payments.services.handle_provider_callback`
  which is idempotent.
"""

from __future__ import annotations

from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.exceptions import BusinessError
from apps.core.permissions import IsAdminOrReadOnly
from apps.payments import selectors as payment_selectors
from apps.payments import services as payment_services
from apps.payments.serializers import (
    PaymentCreateSerializer,
    PaymentRefundSerializer,
    PaymentSerializer,
    ProviderCallbackSerializer,
)


def _raise_business(exc: BusinessError) -> DRFValidationError:
    return DRFValidationError({"detail": exc.message, "code": exc.code, "details": exc.details})


@extend_schema_view(
    list=extend_schema(summary="To'lovlar ro'yxati", responses={200: PaymentSerializer(many=True)}),
    retrieve=extend_schema(summary="To'lov", responses={200: PaymentSerializer}),
    create=extend_schema(
        summary="To'lov yaratish (pending holatda)",
        description="Yaratilgan to'lov `pending` holatida bo'ladi va faqat server tomonidan tasdiqlanadi.",
        request=PaymentCreateSerializer,
        responses={201: PaymentSerializer},
    ),
)
class PaymentViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    queryset = payment_selectors.get_payment_queryset()
    serializer_class = PaymentSerializer
    permission_classes = [IsAuthenticated, IsAdminOrReadOnly]
    filterset_fields = ["status", "provider", "payment_type", "user"]
    search_fields = payment_selectors.PAYMENT_SEARCH_FIELDS
    ordering_fields = payment_selectors.PAYMENT_ORDERING_FIELDS
    ordering = ["-created_at"]

    def get_queryset(self):
        queryset = super().get_queryset()
        if not self.request.user.is_staff:
            queryset = queryset.filter(user=self.request.user)
        return payment_selectors.search_payments(queryset, self.request.query_params.get("search"))

    def create(self, request, *args, **kwargs):
        serializer = PaymentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            payment, invoice = payment_services.build_payment_invoice(
                user=request.user,
                amount=data["amount"],
                payment_type=data["payment_type"],
                provider=data["provider"],
                description=data.get("description", ""),
            )
        except BusinessError as exc:
            raise _raise_business(exc) from exc
        response_data = PaymentSerializer(payment).data
        response_data["invoice"] = invoice
        return Response(response_data, status=status.HTTP_201_CREATED)

    @extend_schema(summary="To'lovni tasdiqlash (admin, naqd)", request=None, responses={200: PaymentSerializer})
    @action(detail=True, methods=["post"], permission_classes=[IsAdminOrReadOnly])
    def confirm(self, request, pk=None) -> Response:
        try:
            payment = payment_services.process_successful_payment(self.get_object(), verified=True)
        except BusinessError as exc:
            raise _raise_business(exc) from exc
        return Response(PaymentSerializer(payment).data)

    @extend_schema(
        summary="To'lovni qaytarish (admin)",
        request=PaymentRefundSerializer,
        responses={200: PaymentSerializer},
    )
    @action(detail=True, methods=["post"], permission_classes=[IsAdminOrReadOnly])
    def refund(self, request, pk=None) -> Response:
        serializer = PaymentRefundSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            payment = payment_services.refund_payment(
                self.get_object(),
                amount=serializer.validated_data.get("amount"),
                reason=serializer.validated_data.get("reason", ""),
            )
        except BusinessError as exc:
            raise _raise_business(exc) from exc
        return Response(PaymentSerializer(payment).data)

    @extend_schema(summary="Mening to'lovlarim", responses={200: PaymentSerializer(many=True)})
    @action(detail=False, methods=["get"], permission_classes=[IsAuthenticated])
    def my_payments(self, request) -> Response:
        payments = payment_selectors.get_payments_by_user(request.user)
        return Response(PaymentSerializer(payments, many=True).data)


@extend_schema_view(
    post=extend_schema(
        summary="Provayder webhook qabul qilish",
        description=(
            "Idempotent endpoint. Xuddi shu so'rov qayta yuborilsa ham to'lov "
            "ikki marta qayta ishlanmaydi."
        ),
        request=ProviderCallbackSerializer,
        responses={
            200: PaymentSerializer,
            404: {"description": "Tranzaksiya topilmadi."},
            400: {"description": "Tasdiqlash muvaffaqiyatsiz."},
        },
    )
)
class PaymentCallbackView(APIView):
    """Provider callback endpoint (shared shape, provider specific fields)."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request) -> Response:
        serializer = ProviderCallbackSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            payment = payment_services.handle_provider_callback(
                provider=data["provider"],
                external_transaction_id=data["external_transaction_id"],
                payload=data.get("payload") or {},
            )
        except BusinessError as exc:
            from rest_framework.response import Response as DRFResponse

            return DRFResponse(
                {"error": exc.as_dict()},
                status=exc.status_code,
            )
        return Response(PaymentSerializer(payment).data)
