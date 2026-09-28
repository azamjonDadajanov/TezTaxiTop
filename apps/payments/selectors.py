"""Read/query layer for the payments app."""

from __future__ import annotations

from typing import Sequence

from django.db.models import Q, QuerySet
from django.utils import timezone

from apps.payments.models import Payment, PaymentStatus

#: Fields the Django admin can search by.
PAYMENT_SEARCH_FIELDS: Sequence[str] = (
    "id",
    "external_transaction_id",
    "user__username",
    "user__first_name",
    "user__last_name",
    "user__phone_number",
    "user__telegram_id",
)

#: Fields the Django admin can order by.
PAYMENT_ORDERING_FIELDS: Sequence[str] = (
    "id",
    "amount",
    "status",
    "created_at",
    "paid_at",
)


def get_payment_queryset() -> QuerySet[Payment]:
    return Payment.objects.select_related("user")


def get_payments() -> QuerySet[Payment]:
    return get_payment_queryset()


def get_payment_by_id(payment_id: int) -> Payment | None:
    return get_payment_queryset().filter(pk=payment_id).first()


def get_payment_by_transaction(provider: str, external_transaction_id: str) -> Payment | None:
    """Webhook lookup key: provider + external transaction id."""
    return (
        get_payment_queryset()
        .filter(provider=provider, external_transaction_id=external_transaction_id)
        .first()
    )


def get_payments_by_user(user) -> QuerySet[Payment]:
    return get_payment_queryset().filter(user=user)


def get_successful_payments() -> QuerySet[Payment]:
    return get_payment_queryset().filter(status=PaymentStatus.SUCCESS)


def get_pending_payments() -> QuerySet[Payment]:
    return get_payment_queryset().filter(status=PaymentStatus.PENDING)


def get_payments_in_status(status: str) -> QuerySet[Payment]:
    return get_payment_queryset().filter(status=status)


def get_recent_payments(limit: int = 20) -> QuerySet[Payment]:
    return get_payment_queryset().order_by("-created_at")[:limit]


def search_payments(queryset: QuerySet[Payment], search_term: str | None) -> QuerySet[Payment]:
    if not search_term:
        return queryset
    term = search_term.strip()
    return queryset.filter(
        Q(external_transaction_id__icontains=term)
        | Q(user__username__icontains=term)
        | Q(user__first_name__icontains=term)
        | Q(user__last_name__icontains=term)
        | Q(user__phone_number__icontains=term)
        | Q(user__telegram_id__icontains=term.replace("+", ""))
    )


def get_revenue_since(moment=None) -> QuerySet[Payment]:
    """Successfully paid amounts - used for the admin dashboard."""
    return get_successful_payments().filter(paid_at__gte=moment or timezone.now())


def get_stale_pending_payments(hours: int = 24) -> QuerySet[Payment]:
    from datetime import timedelta

    return get_pending_payments().filter(created_at__lte=timezone.now() - timedelta(hours=hours))
