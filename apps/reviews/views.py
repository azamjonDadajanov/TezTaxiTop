"""REST API views for the reviews app."""

from __future__ import annotations

from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.exceptions import ResourceNotFound
from apps.orders.selectors import get_order_by_id
from apps.reviews import selectors as review_selectors
from apps.reviews import services as review_services
from apps.reviews.serializers import (
    ReviewCreateSerializer,
    ReviewSerializer,
    ReviewUpdateSerializer,
)


@extend_schema_view(
    list=extend_schema(summary="Baholar ro'yxati", responses={200: ReviewSerializer(many=True)}),
    retrieve=extend_schema(summary="Baholash", responses={200: ReviewSerializer}),
    create=extend_schema(
        summary="Baholash qo'shish",
        description=(
            "Faqat yakunlangan buyurtma ishtiroklari o'zaro baholaydi. "
            "Baholovchi joriy foydalanuvchi, baholanuvchi esa buyurtmaning ikkinchi ishtirokchi."
        ),
        request=ReviewCreateSerializer,
        responses={201: ReviewSerializer, 409: {"description": "Takrorlangan baholash."}},
    ),
    partial_update=extend_schema(
        summary="Baholashni tahrirlash", request=ReviewUpdateSerializer, responses={200: ReviewSerializer}
    ),
    destroy=extend_schema(summary="Baholashni o'chirish", responses={204: None}),
)
class ReviewViewSet(viewsets.ModelViewSet):
    queryset = review_selectors.get_review_queryset()
    serializer_class = ReviewSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["rating", "order", "reviewer", "reviewed_user"]
    search_fields = review_selectors.REVIEW_SEARCH_FIELDS
    ordering_fields = ["id", "rating", "created_at"]
    ordering = ["-created_at"]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_serializer_class(self):
        if self.action == "create":
            return ReviewCreateSerializer
        if self.action in {"update", "partial_update"}:
            return ReviewUpdateSerializer
        return ReviewSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        return review_selectors.search_reviews(queryset, self.request.query_params.get("search"))

    def create(self, request, *args, **kwargs):
        serializer = ReviewCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        order = get_order_by_id(data["order_id"])
        if order is None:
            raise ResourceNotFound("Buyurtma topilmadi.")
        if not order.is_participant(request.user):
            from apps.core.exceptions import UnauthorizedOrderAccess

            raise UnauthorizedOrderAccess()

        # The reviewed user is always the *other* participant of the order.
        reviewed_user_id = order.driver_user_id
        reviewed_user = order.trip.driver.user if reviewed_user_id != request.user.pk else order.passenger

        review = review_services.create_review(
            order=order,
            reviewer=request.user,
            reviewed_user=reviewed_user,
            rating=data["rating"],
            comment=data.get("comment", ""),
        )
        return Response(ReviewSerializer(review).data, status=201)

    def partial_update(self, request, *args, **kwargs):
        review = self.get_object()
        if review.reviewer_id != request.user.pk and not request.user.is_staff:
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("Faqat baho qo'ygan foydalanuvchi uni tahrirlashi mumkin.")
        serializer = ReviewUpdateSerializer(review, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        review = review_services.update_review(
            review,
            rating=serializer.validated_data.get("rating"),
            comment=serializer.validated_data.get("comment"),
        )
        return Response(ReviewSerializer(review).data)

    def destroy(self, request, *args, **kwargs):
        review = self.get_object()
        if review.reviewer_id != request.user.pk and not request.user.is_staff:
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("Faqat baho qo'ygan foydalanuvchi uni o'chira oladi.")
        review_services.delete_review(review)
        return Response(status=204)

    @extend_schema(summary="Mening olgan baholarim", responses={200: ReviewSerializer(many=True)})
    @action(detail=False, methods=["get"])
    def received(self, request) -> Response:
        reviews = review_selectors.get_reviews_for_user(request.user)
        return Response(ReviewSerializer(reviews, many=True).data)

    @extend_schema(summary="Mening qo'ygan baholarim", responses={200: ReviewSerializer(many=True)})
    @action(detail=False, methods=["get"])
    def given(self, request) -> Response:
        reviews = review_selectors.get_reviews_by_user(request.user)
        return Response(ReviewSerializer(reviews, many=True).data)


@extend_schema_view(
    get=extend_schema(
        summary="Reyting umumiy ma'lumoti",
        description="O'rtacha baho, baholar soni va taqsimoti.",
        responses={200: {"type": "object"}},
    )
)
class RatingSummaryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request) -> Response:
        summary = review_selectors.get_rating_summary(request.user)
        summary["distribution"] = {
            str(score): count
            for score, count in review_selectors.get_rating_distribution(request.user).items()
        }
        summary["cached_rating"] = str(
            getattr(getattr(request.user, "driver_profile", None), "rating", "5.00")
        )
        return Response(summary)
