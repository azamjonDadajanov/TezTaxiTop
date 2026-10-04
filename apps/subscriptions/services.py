"""Write/business layer for the subscriptions app.

The important rules implemented here:

* only one ``ACTIVE`` subscription per driver (enforced by a partial unique
  index, so a race cannot create two);
* ``has_active_subscription`` is the *only* authority used by the business
  layer - the stored ``status`` is treated as a cache that may be stale;
* activating an already active subscription **extends** it instead of creating a
  second one, and the historical price is snapshotted;
* expired subscriptions are never deleted, only marked ``EXPIRED``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core.exceptions import (
    ActiveSubscriptionAlreadyExists,
    BusinessValidationError,
    InvalidSubscription,
    ResourceNotFound,
    SubscriptionNotFound,
)
from apps.subscriptions.models import (
    DriverSubscription,
    DriverSubscriptionStatus,
    SubscriptionPlan,
)
from apps.subscriptions.selectors import (
    get_active_subscription,
    get_expired_subscription_candidates,
    get_plan_by_id,
    get_subscription_by_id_queryset,
    get_subscriptions_by_driver,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Plans
# ---------------------------------------------------------------------------
@transaction.atomic
def create_plan(*, name: str, duration_days: int, price, description: str = "", is_active: bool = True) -> SubscriptionPlan:
    plan = SubscriptionPlan(
        name=name.strip(),
        duration_days=duration_days,
        price=_to_decimal(price),
        description=description.strip(),
        is_active=is_active,
    )
    try:
        plan.full_clean()
    except Exception as exc:  # noqa: BLE001
        raise BusinessValidationError(str(exc)) from exc
    plan.save()
    return plan


@transaction.atomic
def update_plan(plan: SubscriptionPlan, **changes) -> SubscriptionPlan:
    allowed = {"name", "duration_days", "price", "description", "is_active", "sort_order"}
    if set(changes) - allowed:
        raise BusinessValidationError("Ruxsat berilmagan maydonlar.")
    for field, value in changes.items():
        if field == "price":
            value = _to_decimal(value)
        setattr(plan, field, value)
    try:
        plan.full_clean()
    except Exception as exc:  # noqa: BLE001
        raise BusinessValidationError(str(exc)) from exc
    plan.save()
    return plan


def _to_decimal(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


# ---------------------------------------------------------------------------
# Subscriptions
# ---------------------------------------------------------------------------
@transaction.atomic
def create_subscription(
    *,
    driver,
    plan: SubscriptionPlan,
    starts_at: datetime | None = None,
    payment=None,
    auto_renew: bool = False,
) -> DriverSubscription:
    """Create a ``PENDING`` subscription for a driver.

    Pending means "bought but not paid / not activated yet". Activation happens
    in :func:`activate_subscription`, which is normally called from the payment
    webhook. ``price_at_purchase`` is snapshotted from the plan immediately so
    that a later plan price change cannot rewrite this record.
    """
    if not plan.is_active:
        raise InvalidSubscription("Bu reja hozir faol emas.")

    starts_at = starts_at or timezone.now()
    if timezone.is_naive(starts_at):
        raise BusinessValidationError("Boshlanish vaqti timezone-aware bo'lishi shart.")

    expires_at = starts_at + timedelta(days=plan.duration_days)
    if expires_at <= starts_at:
        raise InvalidSubscription("Tugash vaqti boshlanish vaqtidan katta bo'lishi kerak.")

    subscription = DriverSubscription(
        driver=driver,
        plan=plan,
        starts_at=starts_at,
        expires_at=expires_at,
        status=DriverSubscriptionStatus.PENDING,
        price_at_purchase=plan.price,
        auto_renew=auto_renew,
        payment=payment,
    )
    subscription.full_clean()
    try:
        subscription.save()
    except IntegrityError as exc:  # pragma: no cover - guarded by unique index
        raise InvalidSubscription(str(exc)) from exc
    logger.info("Obuna yaratildi (pending): driver=%s plan=%s", driver.pk, plan.pk)
    return subscription


@transaction.atomic
def activate_subscription(
    subscription: DriverSubscription,
    *,
    payment=None,
    starts_at: datetime | None = None,
) -> DriverSubscription:
    """Activate a pending subscription (called after a successful payment).

    The row is locked first so that two payment webhooks arriving at the same
    time cannot double-activate or double-extend the same period.
    """
    locked = _lock_subscription(subscription.pk)

    if locked.status == DriverSubscriptionStatus.ACTIVE:
        # Idempotent: the payment webhook may be retried by the provider.
        logger.info("Obuna allaqachon faol: %s", locked.pk)
        if payment is not None and locked.payment_id is None:
            locked.payment = payment
            locked.save(update_fields=["payment", "updated_at"])
        return locked

    if locked.status == DriverSubscriptionStatus.CANCELLED:
        raise InvalidSubscription("Bekor qilingan obunani faollashtirib bo'lmaydi.")

    effective_start = starts_at or locked.starts_at
    if timezone.is_naive(effective_start):
        raise BusinessValidationError("Boshlanish vaqti timezone-aware bo'lishi shart.")

    # If the driver already has a valid period, the new purchase extends it
    # instead of creating an overlapping second active subscription.
    current = (
        DriverSubscription.objects.select_for_update()
        .filter(
            driver=locked.driver,
            status=DriverSubscriptionStatus.ACTIVE,
            expires_at__gt=effective_start,
        )
        .exclude(pk=locked.pk)
        .order_by("-expires_at")
        .first()
    )

    if current is not None:
        current.expires_at = current.expires_at + timedelta(days=locked.plan.duration_days)
        if payment is not None:
            current.payment = payment
        current.auto_renew = locked.auto_renew
        current.save(update_fields=["expires_at", "payment", "auto_renew", "updated_at"])
        locked.status = DriverSubscriptionStatus.CANCELLED
        locked.cancelled_at = timezone.now()
        locked.save(update_fields=["status", "cancelled_at", "updated_at"])
        logger.info("Obuna kengaytirildi: subscription=%s", current.pk)
        try:
            from apps.notifications.services import create_subscription_activated_notification

            create_subscription_activated_notification(current)
        except Exception:
            logger.exception("Obuna kengaytirish bildirishnomasi yaratilmadi")
        return current

    locked.starts_at = effective_start
    locked.expires_at = effective_start + timedelta(days=locked.plan.duration_days)
    locked.status = DriverSubscriptionStatus.ACTIVE
    locked.activated_at = timezone.now()
    if payment is not None:
        locked.payment = payment
    locked.save(
        update_fields=["starts_at", "expires_at", "status", "activated_at", "payment", "updated_at"]
    )
    try:
        locked.full_clean()
    except Exception as exc:  # noqa: BLE001 - pragma: no cover
        raise InvalidSubscription(str(exc)) from exc

    try:
        from apps.notifications.services import create_subscription_activated_notification

        create_subscription_activated_notification(locked)
    except Exception:
        logger.exception("Obuna faollashtirish bildirishnomasi yaratilmadi")

    return locked


@transaction.atomic
def extend_subscription(
    subscription: DriverSubscription,
    *,
    days: int | None = None,
    plan: SubscriptionPlan | None = None,
    payment=None,
) -> DriverSubscription:
    """Extend a subscription by the plan duration (or an explicit number of days)."""
    locked = _lock_subscription(subscription.pk)

    if days is None:
        if plan is not None:
            days = plan.duration_days
        else:
            days = locked.plan.duration_days
    if days is None or days <= 0:
        raise InvalidSubscription("Uzaytirish muddati 0 dan katta bo'lishi kerak.")

    base = locked.expires_at
    if locked.status != DriverSubscriptionStatus.ACTIVE or base <= timezone.now():
        # An expired subscription becomes a new active period starting now.
        base = timezone.now()
        locked.starts_at = base
        locked.status = DriverSubscriptionStatus.ACTIVE
        locked.activated_at = timezone.now()

    locked.expires_at = base + timedelta(days=days)
    if plan is not None:
        locked.plan = plan
        locked.price_at_purchase = plan.price
    if payment is not None:
        locked.payment = payment
    locked.save(update_fields=["starts_at", "expires_at", "status", "activated_at", "plan", "price_at_purchase", "payment", "updated_at"])
    logger.info("Obuna uzaytirildi: %s (+%s kun)", locked.pk, days)
    return locked


@transaction.atomic
def expire_subscription(subscription: DriverSubscription) -> DriverSubscription:
    """Mark one subscription as expired. Idempotent."""
    locked = _lock_subscription(subscription.pk)
    if locked.status == DriverSubscriptionStatus.EXPIRED:
        return locked
    if locked.status == DriverSubscriptionStatus.CANCELLED:
        return locked
    locked.status = DriverSubscriptionStatus.EXPIRED
    locked.save(update_fields=["status", "updated_at"])
    return locked


@transaction.atomic
def cancel_subscription(subscription: DriverSubscription, *, auto_renew: bool = False) -> DriverSubscription:
    """Cancel a subscription. The record is kept - history is never deleted."""
    locked = _lock_subscription(subscription.pk)
    if locked.status == DriverSubscriptionStatus.EXPIRED:
        raise InvalidSubscription("Muddati tugagan obunani bekor qilish mumkin emas.")
    locked.status = DriverSubscriptionStatus.CANCELLED
    locked.cancelled_at = timezone.now()
    locked.auto_renew = auto_renew
    locked.save(update_fields=["status", "cancelled_at", "auto_renew", "updated_at"])
    return locked


@transaction.atomic
def expire_due_subscriptions() -> int:
    """Expire every subscription whose end date has passed. Idempotent.

    Safe to run every hour: the inner ``update`` only touches rows that are
    still ``active``, so a second run in the same minute changes nothing.
    """
    expired_count = 0
    for subscription_id in get_expired_subscription_candidates().values_list("pk", flat=True):
        updated = DriverSubscription.objects.filter(
            pk=subscription_id, status=DriverSubscriptionStatus.ACTIVE
        ).update(status=DriverSubscriptionStatus.EXPIRED, updated_at=timezone.now())
        expired_count += updated
    return expired_count


# ---------------------------------------------------------------------------
# Authority helpers
# ---------------------------------------------------------------------------
def has_active_subscription(driver) -> bool:
    """Authoritative check used by every business rule.

    A driver "has an active subscription" when there is a row with
    ``status=ACTIVE`` **and** ``starts_at <= now < expires_at``. Stale cached
    statuses therefore cannot grant driving rights.
    """
    if driver is None:
        return False
    return get_active_subscription(driver) is not None


def get_subscription_or_raise(subscription_id: int) -> DriverSubscription:
    subscription = get_subscription_by_id_queryset().filter(pk=subscription_id).first()
    if subscription is None:
        raise SubscriptionNotFound()
    return subscription


def get_required_plan(plan_id: int) -> SubscriptionPlan:
    plan = get_plan_by_id(plan_id)
    if plan is None:
        raise ResourceNotFound("Obuna rejasi topilmadi.")
    return plan


def ensure_no_active_subscription_conflict(driver) -> None:
    """Raise when a driver already has a valid subscription.

    Used by the "buy another plan" flow where overlapping periods are not
    allowed; :func:`activate_subscription` instead merges them.
    """
    if has_active_subscription(driver):
        raise ActiveSubscriptionAlreadyExists()


def get_subscription_history(driver) -> list[DriverSubscription]:
    return list(get_subscriptions_by_driver(driver))


def _lock_subscription(subscription_id: int) -> DriverSubscription:
    from django.db import connection

    queryset = DriverSubscription.objects.all()
    if connection.features.has_select_for_update:
        queryset = DriverSubscription.objects.select_for_update()
    return queryset.select_related("plan", "driver__user").get(pk=subscription_id)


__all__ = [
    "activate_subscription",
    "cancel_subscription",
    "create_plan",
    "create_subscription",
    "ensure_no_active_subscription_conflict",
    "expire_due_subscriptions",
    "expire_subscription",
    "extend_subscription",
    "get_required_plan",
    "get_subscription_history",
    "get_subscription_or_raise",
    "has_active_subscription",
    "update_plan",
]
