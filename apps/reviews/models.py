"""Review model.

Design decisions
----------------
* A review always belongs to a **completed order**, and the reviewer and the
  reviewed user must be the two participants of that order. Both directions are
  supported: passenger -> driver and driver -> passenger.
* ``UniqueConstraint(order, reviewer, reviewed_user)`` makes a duplicate review
  impossible at the database level, not just in the service layer.
* ``CheckConstraint`` enforces ``1 <= rating <= 5`` and ``reviewer !=
  reviewed_user``.
* ``DriverProfile.rating`` is a **derived cache**. It is recomputed from the
  reviews table by :func:`apps.reviews.services.recalculate_driver_rating`
  whenever a review changes, so it can never drift from the reviews.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel

MIN_RATING = 1
MAX_RATING = 5


class Review(TimeStampedModel):
    """A 1..5 rating one participant gives to the other after a completed order."""

    order = models.ForeignKey(
        "orders.Order",
        on_delete=models.PROTECT,
        related_name="reviews",
        verbose_name="Buyurtma",
        help_text="Faqat yakunlangan buyurtmalar baholanadi.",
    )
    reviewer = models.ForeignKey(
        "users.User",
        on_delete=models.PROTECT,
        related_name="given_reviews",
        verbose_name="Baholovchi",
    )
    reviewed_user = models.ForeignKey(
        "users.User",
        on_delete=models.PROTECT,
        related_name="received_reviews",
        verbose_name="Baholanuvchi",
    )
    rating = models.PositiveSmallIntegerField(
        verbose_name="Baho",
        help_text="1 dan 5 gacha butun son.",
    )
    comment = models.TextField(verbose_name="Izoh", max_length=1000, blank=True, default="")

    class Meta:
        verbose_name = "Baholash"
        verbose_name_plural = "Baholashlar"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("reviewed_user", "-created_at"), name="review_user_created_idx"),
            models.Index(fields=("order",), name="review_order_idx"),
            models.Index(fields=("rating",), name="review_rating_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(rating__gte=MIN_RATING) & models.Q(rating__lte=MAX_RATING),
                name="review_rating_between_1_and_5",
            ),
            models.CheckConstraint(
                condition=~models.Q(reviewer=models.F("reviewed_user")),
                name="review_not_self",
            ),
            models.UniqueConstraint(
                fields=("order", "reviewer", "reviewed_user"),
                name="uniq_review_per_order_and_pair",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.reviewer.display_name} -> {self.reviewed_user.display_name}: {self.rating}/5"

    def clean(self) -> None:
        super().clean()
        if self.reviewer_id and self.reviewer_id == self.reviewed_user_id:
            raise ValidationError({"reviewed_user": _("O'zingizni baholash mumkin emas.")})
        if self.rating is not None and not (MIN_RATING <= self.rating <= MAX_RATING):
            raise ValidationError({"rating": _("Baho 1 dan 5 gacha bo'lishi kerak.")})

    # -- helpers (small, non-business) ---------------------------------------
    @property
    def is_for_driver(self) -> bool:
        """Whether the reviewed user owns a driver profile."""
        return hasattr(self.reviewed_user, "driver_profile")
