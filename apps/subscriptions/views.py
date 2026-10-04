"""REST API views for the subscriptions app."""

from __future__ import annotations

from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.exceptions import NotADriver
from apps.core.permissions import IsAdminOrReadOnly
from apps.payments.serializers import PaymentSerializer
from apps.subscriptions import selectors as subscription_selectors
from apps.subscriptions import services as subscription_services
from apps.subscriptions.serializers import (
    DriverSubscriptionSerializer,
    SubscriptionPlanSerializer,
    SubscriptionPlanWriteSerializer,
    SubscriptionPurchaseSerializer,
)


@extend_schema_view(
    list=extend_schema(summary="Obuna rejalari", responses={200: SubscriptionPlanSerializer(many=True)}),
    retrieve=extend_schema(summary="Obuna rejasi", responses={200: SubscriptionPlanSerializer}),
    create=extend_schema(
        summary="Reja qo'shish (admin)",
        request=SubscriptionPlanWriteSerializer,
        responses={201: SubscriptionPlanSerializer},
    ),
    partial_update=extend_schema(
        summary="Rejani tahrirlash (admin)",
        request=SubscriptionPlanWriteSerializer,
        responses={200: SubscriptionPlanSerializer},
    ),
)
class SubscriptionPlanViewSet(viewsets.ModelViewSet):
    """The plan catalogue is shared reference data; only staff may change it."""

    queryset = subscription_selectors.get_plan_queryset()
    serializer_class = SubscriptionPlanSerializer
    permission_classes = [IsAuthenticated, IsAdminOrReadOnly]
    filterset_fields = ["is_active"]
    search_fields = ["name", "description"]
    ordering_fields = ["id", "name", "duration_days", "price", "sort_order"]
    ordering = ["sort_order", "duration_days"]

    def get_serializer_class(self):
        if self.action in {"create", "update", "partial_update"}:
            return SubscriptionPlanWriteSerializer
        return SubscriptionPlanSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        if not self.request.user.is_staff:
            queryset = queryset.filter(is_active=True)
        return queryset

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        plan = subscription_services.create_plan(**serializer.validated_data)
        return Response(SubscriptionPlanSerializer(plan).data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        serializer = self.get_serializer(data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        plan = subscription_services.update_plan(self.get_object(), **serializer.validated_data)
        return Response(SubscriptionPlanSerializer(plan).data)


@extend_schema_view(
    list=extend_schema(summary="Obunalar ro'yxati", responses={200: DriverSubscriptionSerializer(many=True)}),
    retrieve=extend_schema(summary="Obuna", responses={200: DriverSubscriptionSerializer}),
)
class DriverSubscriptionViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """A driver sees their own history; staff see everything."""

    queryset = subscription_selectors.get_subscription_queryset()
    serializer_class = DriverSubscriptionSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["status", "plan", "driver"]
    search_fields = ["driver__user__first_name", "driver__user__phone_number", "driver__user__telegram_id"]
    ordering_fields = ["id", "starts_at", "expires_at", "created_at", "price_at_purchase"]
    ordering = ["-created_at"]

    def get_queryset(self):
        queryset = super().get_queryset()
        if not self.request.user.is_staff:
            driver_profile = getattr(self.request.user, "driver_profile", None)
            if driver_profile is None:
                return queryset.none()
            queryset = queryset.filter(driver=driver_profile)
        return queryset

    @extend_schema(
        summary="Rejani xarid qilish (to'lov hisobini yaratadi)",
        description=(
            "Obuna `pending` holatida yaratiladi va uning uchun to'lov hisobi tuziladi. "
            "To'lov tasdiqlangach obuna faollashtirilmaydi. Tasdiqlash faqat server "
            "tomonda (`apps.payments`) amalga oshiriladi."
        ),
        request=SubscriptionPurchaseSerializer,
        responses={
            201: SubscriptionPurchaseSerializer,
            402: {"description": "To'lov provayderi sozlanmagan."},
        },
    )
    @action(detail=False, methods=["post"])
    def purchase(self, request) -> Response:
        # Imported here: payments depends on subscriptions (activation), so a
        # module level import would create a cycle.
        from apps.payments.services import build_subscription_payment_invoice

        driver_profile = getattr(request.user, "driver_profile", None)
        if driver_profile is None:
            raise NotADriver()

        serializer = SubscriptionPurchaseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        plan = subscription_services.get_required_plan(serializer.validated_data["plan_id"])
        subscription = subscription_services.create_subscription(
            driver=driver_profile,
            plan=plan,
            auto_renew=serializer.validated_data.get("auto_renew", False),
        )
        payment, invoice = build_subscription_payment_invoice(
            user=request.user, subscription=subscription
        )
        return Response(
            {
                "subscription": DriverSubscriptionSerializer(subscription).data,
                "payment": PaymentSerializer(payment).data,
                "invoice": invoice,
            },
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(summary="Faol obunam", responses={200: DriverSubscriptionSerializer})
    @action(detail=False, methods=["get"])
    def my_active(self, request) -> Response:
        driver_profile = getattr(request.user, "driver_profile", None)
        if driver_profile is None:
            raise NotADriver()
        subscription = subscription_selectors.get_active_subscription(driver_profile)
        if subscription is None:
            return Response({}, status=status.HTTP_404_NOT_FOUND)
        return Response(DriverSubscriptionSerializer(subscription).data)

    @extend_schema(summary="Obuna tarixi", responses={200: DriverSubscriptionSerializer(many=True)})
    @action(detail=False, methods=["get"])
    def history(self, request) -> Response:
        driver_profile = getattr(request.user, "driver_profile", None)
        if driver_profile is None:
            raise NotADriver()
        subscriptions = subscription_selectors.get_subscriptions_by_driver(driver_profile)
        return Response(DriverSubscriptionSerializer(subscriptions, many=True).data)

    @extend_schema(summary="Faollikni tekshirish", responses={200: {"type": "object"}})
    @action(detail=False, methods=["get"], url_path="has-active")
    def has_active(self, request) -> Response:
        driver_profile = getattr(request.user, "driver_profile", None)
        return Response(
            {"has_active_subscription": subscription_services.has_active_subscription(driver_profile)}
        )


@extend_schema_view(
    post=extend_schema(
        summary="Obunani bekor qilish",
        description="Tarix saqlanadi, faqat `cancelled` holatiga o'tadi.",
        responses={200: DriverSubscriptionSerializer},
    )
)
class CancelSubscriptionView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = DriverSubscriptionSerializer

    def post(self, request, pk: int) -> Response:
        subscription = subscription_services.get_subscription_or_raise(pk)
        driver_profile = getattr(request.user, "driver_profile", None)
        if not request.user.is_staff and (
            driver_profile is None or subscription.driver_id != driver_profile.pk
        ):
            from apps.core.exceptions import UnauthorizedOrderAccess

            raise UnauthorizedOrderAccess()
        subscription = subscription_services.cancel_subscription(subscription)
        return Response(DriverSubscriptionSerializer(subscription).data)
