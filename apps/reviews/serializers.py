"""Serializers for the reviews app."""

from __future__ import annotations

from rest_framework import serializers

from apps.reviews.models import Review


class ReviewSerializer(serializers.ModelSerializer):
    reviewer_name = serializers.CharField(source="reviewer.display_name", read_only=True)
    reviewed_user_name = serializers.CharField(source="reviewed_user.display_name", read_only=True)
    order_status = serializers.CharField(source="order.status", read_only=True)

    class Meta:
        model = Review
        fields = (
            "id",
            "order",
            "order_status",
            "reviewer",
            "reviewer_name",
            "reviewed_user",
            "reviewed_user_name",
            "rating",
            "comment",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "order",
            "order_status",
            "reviewer",
            "reviewer_name",
            "reviewed_user_name",
            "created_at",
            "updated_at",
        )


class ReviewCreateSerializer(serializers.Serializer):
    """Payload of ``POST /api/v1/reviews/``.

    ``reviewer`` is always the authenticated user, and the reviewed user is
    derived from the order, so neither can be spoofed by the client.
    """

    order_id = serializers.IntegerField()
    rating = serializers.IntegerField(min_value=1, max_value=5)
    comment = serializers.CharField(required=False, allow_blank=True, max_length=1000)


class ReviewUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Review
        fields = ("rating", "comment")
        extra_kwargs = {
            "rating": {"required": False, "min_value": 1, "max_value": 5},
            "comment": {"required": False, "allow_blank": True, "max_length": 1000},
        }
