"""Read/query layer for the reviews app."""

from __future__ import annotations

from typing import Sequence

from django.db.models import Avg, Count, Q, QuerySet

from apps.reviews.models import Review

REVIEW_SEARCH_FIELDS: Sequence[str] = (
    "id",
    "comment",
    "reviewer__username",
    "reviewer__first_name",
    "reviewer__last_name",
    "reviewed_user__username",
    "reviewed_user__first_name",
    "reviewed_user__last_name",
)


def get_review_queryset() -> QuerySet[Review]:
    return Review.objects.select_related("order", "reviewer", "reviewed_user")


def get_reviews() -> QuerySet[Review]:
    return get_review_queryset()


def get_review_by_id(review_id: int) -> Review | None:
    return get_review_queryset().filter(pk=review_id).first()


def get_reviews_for_user(user) -> QuerySet[Review]:
    """Reviews written **about** this user."""
    return get_review_queryset().filter(reviewed_user=user)


def get_reviews_by_user(user) -> QuerySet[Review]:
    """Reviews written **by** this user."""
    return get_review_queryset().filter(reviewer=user)


def get_driver_reviews(driver_profile) -> QuerySet[Review]:
    return get_review_queryset().filter(reviewed_user=driver_profile.user)


def get_review_for_pair(order, reviewer, reviewed_user) -> Review | None:
    return get_review_queryset().filter(
        order=order, reviewer=reviewer, reviewed_user=reviewed_user
    ).first()


def has_reviewed(order, reviewer, reviewed_user) -> bool:
    return get_review_for_pair(order, reviewer, reviewed_user) is not None


def get_rating_summary(user) -> dict:
    """Average rating and count, computed from the reviews table."""
    aggregate = get_reviews_for_user(user).aggregate(
        average=Avg("rating"), total=Count("id")
    )
    average = aggregate["average"]
    return {
        "average": round(float(average), 2) if average is not None else None,
        "count": aggregate["total"] or 0,
    }


def get_rating_distribution(user) -> dict[int, int]:
    """``{rating: number_of_reviews}`` used by the profile screen."""
    rows = (
        get_reviews_for_user(user)
        .values_list("rating", flat=True)
        .order_by()
    )
    distribution = {score: 0 for score in range(1, 6)}
    for score in rows:
        distribution[int(score)] = distribution.get(int(score), 0) + 1
    return distribution


def search_reviews(queryset: QuerySet[Review], search_term: str | None) -> QuerySet[Review]:
    if not search_term:
        return queryset
    term = search_term.strip()
    return queryset.filter(
        Q(comment__icontains=term)
        | Q(reviewer__username__icontains=term)
        | Q(reviewer__first_name__icontains=term)
        | Q(reviewer__last_name__icontains=term)
        | Q(reviewed_user__username__icontains=term)
        | Q(reviewed_user__first_name__icontains=term)
        | Q(reviewed_user__last_name__icontains=term)
    )
