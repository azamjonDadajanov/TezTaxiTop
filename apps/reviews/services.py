"""Write/business layer for the reviews app.

Rules enforced here (and mirrored by database constraints):

* the order must be ``completed``;
* the reviewer must be one of the two participants;
* the reviewed user must be the *other* participant;
* nobody reviews themselves;
* one review per (order, reviewer, reviewed user) - enforced by a unique index;
* after every change the driver rating is **recomputed from the reviews table**,
  so the cached ``DriverProfile.rating`` can never drift.
"""

from __future__ import annotations

import logging
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.db.models import Avg, Count

from apps.core.exceptions import (
    BusinessValidationError,
    DuplicateReview,
    InvalidReview,
    ReviewNotAllowed,
)
from apps.orders.models import Order, OrderStatus
from apps.reviews.models import Review
from apps.reviews.selectors import get_review_by_id, has_reviewed
from apps.users.models import User

logger = logging.getLogger(__name__)

#: Ratings are stored as Decimal; the average is rounded to 2 decimals.
RATING_QUANT = Decimal("0.01")
DEFAULT_RATING = Decimal("5.00")
MIN_RATING = Decimal("1.00")
MAX_RATING = Decimal("5.00")


@transaction.atomic
def create_review(
    *,
    order: Order,
    reviewer: User,
    reviewed_user: User,
    rating: int,
    comment: str = "",
) -> Review:
    """Create a review after a completed order and refresh the driver rating."""
    _assert_review_allowed(order, reviewer, reviewed_user, rating)

    if has_reviewed(order, reviewer, reviewed_user):
        raise DuplicateReview(
            details={"order_id": order.pk, "reviewed_user_id": reviewed_user.pk}
        )

    review = Review(
        order=order,
        reviewer=reviewer,
        reviewed_user=reviewed_user,
        rating=rating,
        comment=comment.strip(),
    )
    try:
        review.full_clean()
    except Exception as exc:  # noqa: BLE001
        raise InvalidReview(str(exc)) from exc
    review.save()

    recalculate_driver_rating(reviewed_user)
    logger.info("Baholash yaratildi: #%s (%s -> %s: %s)", review.pk, reviewer.pk, reviewed_user.pk, rating)
    return review


@transaction.atomic
def update_review(review: Review, *, rating: int | None = None, comment: str | None = None) -> Review:
    """Update a review (author only) and recompute the driver rating."""
    if rating is not None:
        if not (1 <= rating <= 5):
            raise BusinessValidationError("Baho 1 dan 5 gacha bo'lishi kerak.")
        review.rating = rating
    if comment is not None:
        review.comment = comment.strip()
    try:
        review.full_clean()
    except Exception as exc:  # noqa: BLE001
        raise InvalidReview(str(exc)) from exc
    review.save(update_fields=["rating", "comment", "updated_at"])

    recalculate_driver_rating(review.reviewed_user)
    return review


@transaction.atomic
def delete_review(review: Review) -> None:
    """Delete a review and repair the cached driver rating."""
    reviewed_user = review.reviewed_user
    review.delete()
    recalculate_driver_rating(reviewed_user)


@transaction.atomic
def recalculate_driver_rating(user: User) -> Decimal | None:
    """Recompute ``DriverProfile.rating`` from all reviews of ``user``.

    Returns the new rating, or ``None`` when the user has no driver profile.
    """
    driver_profile = getattr(user, "driver_profile", None)
    if driver_profile is None:
        return None

    aggregate = Review.objects.filter(reviewed_user=user).aggregate(
        average=Avg("rating"), total=Count("id")
    )
    average = aggregate["average"]
    total = aggregate["total"] or 0

    if average is None:
        new_rating = DEFAULT_RATING
    else:
        new_rating = Decimal(str(average)).quantize(RATING_QUANT, rounding=ROUND_HALF_UP)
        new_rating = max(MIN_RATING, min(MAX_RATING, new_rating))

    driver_profile.rating = new_rating
    driver_profile.rating_count = total
    driver_profile.save(update_fields=["rating", "rating_count", "updated_at"])
    return new_rating


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------
def _assert_review_allowed(order: Order, reviewer: User, reviewed_user: User, rating: int) -> None:
    if order.status != OrderStatus.COMPLETED:
        raise ReviewNotAllowed(
            f"Faqat yakunlangan buyurtmalar baholanadi (joriy holat: {order.get_status_display()})."
        )
    if rating is None or not (1 <= rating <= 5):
        raise InvalidReview("Baho 1 dan 5 gacha bo'lishi kerak.")
    if reviewer.pk == reviewed_user.pk:
        raise InvalidReview("O'zingizni baholash mumkin emas.")
    if not order.is_participant(reviewer):
        raise ReviewNotAllowed("Faqat buyurtma ishtirokchilari baholaydi.")
    if not order.is_participant(reviewed_user):
        raise ReviewNotAllowed("Faqat buyurtma ishtirokchilari baholanadi.")
    if reviewer.pk == reviewed_user.pk:
        raise InvalidReview("O'zingizni baholash mumkin emas.")


def get_required_review(review_id: int) -> Review:
    review = get_review_by_id(review_id)
    if review is None:
        from apps.core.exceptions import ResourceNotFound

        raise ResourceNotFound("Baholash topilmadi.")
    return review


__all__ = [
    "create_review",
    "delete_review",
    "recalculate_driver_rating",
    "update_review",
]
