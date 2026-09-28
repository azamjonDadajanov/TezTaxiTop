"""Read/query layer for the subscriptions app."""

from __future__ import annotations

from datetime import timedelta

from django.db.models import QuerySet
from django.utils import timezone

from apps.subscriptions.models import (
    DriverSubscription,
    DriverSubscriptionStatus,
    SubscriptionPlan,
)


def get_plan_queryset() -> QuerySet[SubscriptionPlan]:
    return SubscriptionPlan.objects.all()


def get_active_plans() -> QuerySet[SubscriptionPlan]:
    return get_plan_queryset().filter(is_active=True).order_by("sort_order", "duration_days")


def get_plan_by_id(plan_id: int) -> SubscriptionPlan | None:
    return get_plan_queryset().filter(pk=plan_id).first()


def get_subscription_queryset() -> QuerySet[DriverSubscription]:
    return DriverSubscription.objects.select_related("plan", "driver__user", "payment")


def get_subscription_by_id_queryset() -> QuerySet[DriverSubscription]:
    """Optimised single-row lookup used by ``get_subscription_or_raise``."""
    return get_subscription_queryset()


def get_subscriptions_by_driver(driver) -> QuerySet[DriverSubscription]:
    """Full history, newest first."""
    return get_subscription_queryset().filter(driver=driver)


def get_active_subscription(driver) -> DriverSubscription | None:
    """Return the driver subscription that is genuinely usable right now.

    The cached ``status`` **and** the validity window are verified, so a
    subscription whose ``expires_at`` has passed but whose periodic expiry task
    has not run yet is still correctly reported as "no active subscription".
    """
    now = timezone.now()
    return (
        get_subscription_queryset()
        .filter(
            driver=driver,
            status=DriverSubscriptionStatus.ACTIVE,
            starts_at__lte=now,
            expires_at__gt=now,
        )
        .order_by("-expires_at")
        .first()
    )


def get_pending_subscriptions() -> QuerySet[DriverSubscription]:
    return get_subscription_queryset().filter(status=DriverSubscriptionStatus.PENDING)


def get_expired_subscription_candidates() -> QuerySet[DriverSubscription]:
    """Active subscriptions whose ``expires_at`` has passed."""
    return (
        get_subscription_queryset()
        .filter(status=DriverSubscriptionStatus.ACTIVE, expires_at__lte=timezone.now())
        .order_by("pk")
    )


def get_expiring_subscriptions(days: int) -> QuerySet[DriverSubscription]:
    """Valid subscriptions expiring within the next ``days`` days."""
    now = timezone.now()
    return (
        get_subscription_queryset()
        .filter(
            status=DriverSubscriptionStatus.ACTIVE,
            expires_at__gt=now,
            expires_at__lte=now + timedelta(days=days),
        )
        .order_by("expires_at")
    )


def get_recent_subscriptions(limit: int = 20) -> QuerySet[DriverSubscription]:
    return get_subscription_queryset().order_by("-created_at")[:limit]


def has_active_subscription_record(driver) -> bool:
    """Read-only helper used by list endpoints (no side effects)."""
    return get_active_subscription(driver) is not None
