"""Write/business layer for the payments app.

Security rules implemented here (non negotiable):

1. A payment is created as ``PENDING`` only. A client (bot, web, Mini App) can
   never post a successful status - the only way to reach ``SUCCESS`` is
   :func:`process_successful_payment`, which is called by the webhook **after**
   :func:`verify_payment` confirmed the transaction with the provider.
2. Webhooks are idempotent. The payment row is locked with
   ``select_for_update()``; a payment that already reached a final state
   raises :class:`~apps.core.exceptions.PaymentAlreadyProcessed` and performs
   no side effect, so a provider retry cannot double-activate a subscription.
3. Money is never a float - every amount is a ``Decimal``.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from django.db import connection, transaction
from django.utils import timezone

from apps.core.exceptions import (
    BusinessValidationError,
    PaymentAlreadyProcessed,
    PaymentError,
    PaymentNotFound,
    PaymentProviderNotConfigured,
    PaymentVerificationFailed,
)
from apps.payments.models import (
    FINAL_PAYMENT_STATUSES,
    Payment,
    PaymentProvider,
    PaymentStatus,
    PaymentType,
)
from apps.payments.providers import get_payment_provider
from apps.payments.selectors import get_payment_by_id, get_payment_by_transaction
from apps.users.models import User

logger = logging.getLogger(__name__)

NON_NEGATIVE = Decimal("0.00")


# ---------------------------------------------------------------------------
# Creation
# ---------------------------------------------------------------------------
@transaction.atomic
def create_payment(
    *,
    user: User,
    amount,
    payment_type: str = PaymentType.SUBSCRIPTION,
    provider: str = PaymentProvider.CLICK,
    external_transaction_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Payment:
    """Create a ``PENDING`` payment record.

    This function never contacts the provider; use
    :func:`build_payment_invoice` when an actual payment intent is needed.
    """
    amount_value = _to_decimal(amount)
    if amount_value < NON_NEGATIVE:
        raise BusinessValidationError("To'lov summasi manfiy bo'lishi mumkin emas.")
    if payment_type not in PaymentType.values:
        raise BusinessValidationError(f"Noma'lum to'lov turi: {payment_type}")
    if provider not in PaymentProvider.values:
        raise BusinessValidationError(f"Noma'lum to'lov provayderi: {provider}")

    payment = Payment(
        user=user,
        payment_type=payment_type,
        amount=amount_value,
        provider=provider,
        external_transaction_id=external_transaction_id or None,
        status=PaymentStatus.PENDING,
        metadata=metadata or {},
    )
    payment.full_clean()
    payment.save()
    logger.info("To'lov yaratildi: #%s (%s so'm, %s)", payment.pk, payment.amount, provider)
    return payment


def build_payment_invoice(
    *,
    user: User,
    amount,
    payment_type: str = PaymentType.SUBSCRIPTION,
    provider: str = PaymentProvider.CLICK,
    description: str = "",
    metadata: dict[str, Any] | None = None,
) -> tuple[Payment, dict[str, Any]]:
    """Create the payment record and ask the provider for a payment intent.

    Returns ``(payment, invoice)``. If the provider is not configured a
    :class:`~apps.core.exceptions.PaymentProviderNotConfigured` error is raised
    **before** any record is committed, so no orphan pending payment is left
    behind.
    """
    amount_value = _to_decimal(amount)
    gateway = get_payment_provider(provider)

    with transaction.atomic():
        payment = create_payment(
            user=user,
            amount=amount_value,
            payment_type=payment_type,
            provider=provider,
            metadata=metadata,
        )
        reference = f"payment-{payment.pk}"
        invoice = gateway.build_invoice(
            amount=amount_value, reference=reference, description=description
        )
        payment.metadata = {**(payment.metadata or {}), "invoice": invoice, "reference": reference}
        # The provider's own transaction id is what its webhook will quote, so
        # it has to be stored now - otherwise the callback cannot be matched.
        provider_transaction_id = _extract_transaction_id(invoice)
        if provider_transaction_id and not payment.external_transaction_id:
            payment.external_transaction_id = provider_transaction_id
        payment.save(update_fields=["metadata", "external_transaction_id", "updated_at"])
    return payment, invoice


# Keys different providers use for the transaction id in a create-invoice reply.
_TRANSACTION_ID_KEYS = ("transaction_id", "transactionId", "payment_id", "paymentId", "id")


def _extract_transaction_id(invoice: Any) -> str | None:
    if not isinstance(invoice, dict):
        return None
    for key in _TRANSACTION_ID_KEYS:
        value = invoice.get(key)
        if isinstance(value, (str, int)) and str(value).strip():
            return str(value).strip()
    return None


def build_subscription_payment_invoice(
    *,
    user: User,
    subscription: Any,
    provider: str = PaymentProvider.CLICK,
) -> tuple[Payment, dict[str, Any]]:
    """Create the invoice for buying ``subscription``.

    The payment is explicitly linked to the subscription through its metadata,
    which is the only thing :func:`_find_subscription_for_payment` trusts when the
    money arrives. The price snapshot of the subscription is used, never a
    client-supplied amount.
    """
    metadata = {"subscription_id": subscription.pk, "plan_id": subscription.plan_id}
    return build_payment_invoice(
        user=user,
        amount=subscription.price_at_purchase,
        payment_type=PaymentType.SUBSCRIPTION,
        provider=provider,
        description=f"{subscription.plan.name} obunasi",
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# Verification & state changes
# ---------------------------------------------------------------------------
@transaction.atomic
def verify_payment(payment: Payment, *, payload: dict[str, Any] | None = None) -> Payment:
    """Verify a payment **server side** and mark it successful when confirmed.

    This is the single trusted entry point used by provider webhooks.
    """
    locked = _lock_payment(payment.pk)
    gateway = get_payment_provider(locked.provider)

    result = gateway.verify(
        external_transaction_id=locked.external_transaction_id, payload=payload or {}
    )
    metadata = {**(locked.metadata or {}), "verification": result.to_metadata()}

    if not result.is_verified:
        # The provider gave a definitive negative answer (a failed or expired
        # transaction). Marking the payment FAILED is what stops the provider
        # from retrying the webhook forever and lets the user know the money did
        # not arrive. A *confirmation* that we cannot trust (amount mismatch,
        # foreign transaction id) still raises below and stays pending for a
        # human to look at.
        return process_failed_payment(
            locked,
            reason=f"{locked.get_provider_display()} to'lovi tasdiqlanmadi.",
            metadata=metadata,
        )

    if result.external_transaction_id and result.external_transaction_id != locked.external_transaction_id:
        # Guard against a provider sending a transaction id of another payment.
        existing = get_payment_by_transaction(locked.provider, result.external_transaction_id)
        if existing is not None and existing.pk != locked.pk:
            raise PaymentVerificationFailed(
                "Bu tranzaksiya ID boshqa to'lovga tegishli.",
                details={"external_transaction_id": result.external_transaction_id},
            )
        locked.external_transaction_id = result.external_transaction_id

    if result.amount is not None and result.amount != locked.amount:
        locked.metadata = metadata
        locked.save(update_fields=["metadata", "updated_at"])
        raise PaymentVerificationFailed(
            "To'lov summasi mos kelmadi.",
            details={"expected": str(locked.amount), "received": str(result.amount)},
        )

    locked.metadata = metadata
    process_successful_payment(locked, verified=True)
    locked.refresh_from_db()
    return locked


@transaction.atomic
def process_successful_payment(
    payment: Payment, *, verified: bool = False, metadata: dict[str, Any] | None = None
) -> Payment:
    """Mark a payment as ``SUCCESS`` and run its side effects.

    ``verified=True`` states that the provider confirmation already happened.
    Without it the function refuses to move the payment forward, which makes it
    impossible for a bot handler to fake a payment.

    Idempotency: if the payment already has a final status, the function raises
    :class:`~apps.core.exceptions.PaymentAlreadyProcessed` and changes nothing.
    """
    locked = _lock_payment(payment.pk)

    if locked.status in FINAL_PAYMENT_STATUSES:
        raise PaymentAlreadyProcessed(
            f"To'lov allaqachon '{locked.get_status_display()}' holatida.",
            details={"payment_id": locked.pk, "status": locked.status},
        )
    if not verified:
        raise PaymentVerificationFailed(
            "To'lov muvaffaqiyatli deb belgilanishi uchun avval server tomonda tasdiqlanishi shart."
        )

    locked.status = PaymentStatus.SUCCESS
    locked.paid_at = timezone.now()
    if metadata:
        locked.metadata = {**(locked.metadata or {}), **metadata}
    locked.failure_reason = ""
    locked.save(update_fields=["status", "paid_at", "metadata", "failure_reason", "updated_at"])

    _apply_payment_side_effects(locked)
    return locked


@transaction.atomic
def process_failed_payment(payment: Payment, *, reason: str = "", metadata: dict[str, Any] | None = None) -> Payment:
    """Mark a payment as ``FAILED``. Idempotent for already successful payments."""
    locked = _lock_payment(payment.pk)
    if locked.status == PaymentStatus.SUCCESS:
        raise PaymentAlreadyProcessed("Muvaffaqiyatli to'lovni muvaffaqiyatsizga o'tkazib bo'lmaydi.")
    if locked.status in FINAL_PAYMENT_STATUSES:
        return locked

    locked.status = PaymentStatus.FAILED
    locked.failure_reason = reason[:255]
    if metadata:
        locked.metadata = {**(locked.metadata or {}), **metadata}
    locked.save(update_fields=["status", "failure_reason", "metadata", "updated_at"])

    from apps.notifications.services import create_payment_notification

    create_payment_notification(locked, success=False)
    return locked


@transaction.atomic
def cancel_payment(payment: Payment, *, reason: str = "") -> Payment:
    """Cancel a still pending payment (e.g. the user closed the invoice)."""
    locked = _lock_payment(payment.pk)
    if locked.status in FINAL_PAYMENT_STATUSES:
        raise PaymentAlreadyProcessed()
    locked.status = PaymentStatus.CANCELLED
    locked.failure_reason = reason[:255]
    locked.save(update_fields=["status", "failure_reason", "updated_at"])
    return locked


@transaction.atomic
def refund_payment(payment: Payment, *, amount=None, reason: str = "") -> Payment:
    """Refund a successful payment.

    The refund itself is delegated to the provider; when the provider has no
    refund support the payment is **not** marked as refunded, so the ledger stays
    truthful.
    """
    locked = _lock_payment(payment.pk)
    if locked.status != PaymentStatus.SUCCESS:
        raise PaymentError("Faqat muvaffaqiyatli to'lovni qaytarish mumkin.")
    if not locked.external_transaction_id:
        raise PaymentError("Tashqi tranzaksiya ID yo'q, qaytarishni tasdiqlab bo'lmaydi.")

    refund_amount = _to_decimal(amount) if amount is not None else locked.amount
    if refund_amount <= NON_NEGATIVE or refund_amount > locked.amount:
        raise BusinessValidationError("Qaytarish summasi noto'g'ri.")

    gateway = get_payment_provider(locked.provider)
    response = gateway.refund(
        external_transaction_id=locked.external_transaction_id, amount=refund_amount
    )
    # A provider may report the refusal in the payload instead of raising. The
    # ledger must not claim a refund that never happened.
    if isinstance(response, dict):
        outcome = response.get("ok", response.get("success"))
        if outcome is False:
            raise PaymentError(
                "To'lovni qaytarishda provayder xatosi qaytardi.",
                details={"provider": locked.provider, "response": response},
            )
    locked.status = PaymentStatus.REFUNDED
    locked.refunded_at = timezone.now()
    locked.metadata = {**(locked.metadata or {}), "refund": response, "refund_reason": reason}
    locked.save(update_fields=["status", "refunded_at", "metadata", "updated_at"])
    return locked


# ---------------------------------------------------------------------------
# Subscription integration
# ---------------------------------------------------------------------------
def _apply_payment_side_effects(payment: Payment) -> None:
    """Run everything a successful payment implies.

    The user always learns the outcome, and a subscription payment additionally
    activates the (single) subscription it was created for.
    """
    from apps.notifications.services import create_payment_notification

    create_payment_notification(payment, success=True)

    if payment.payment_type != PaymentType.SUBSCRIPTION:
        return
    subscription = _find_subscription_for_payment(payment)
    if subscription is None:
        return
    from apps.subscriptions.models import DriverSubscriptionStatus
    from apps.subscriptions.services import activate_subscription

    if subscription.status == DriverSubscriptionStatus.ACTIVE:
        # Idempotency guard for repeated webhooks.
        return
    activate_subscription(subscription, payment=payment)


def _find_subscription_for_payment(payment: Payment):
    """Locate the subscription this payment was created for.

    The link is **explicit**: the payment metadata carries ``subscription_id``
    (written by :func:`build_subscription_payment_invoice`). A payment is never
    matched against a subscription heuristically - two purchases of the same
    plan are indistinguishable by amount alone, so guessing would activate an
    arbitrary subscription.
    """
    from apps.subscriptions.models import DriverSubscription

    subscription_id = (payment.metadata or {}).get("subscription_id")
    if not subscription_id:
        return None
    return DriverSubscription.objects.filter(pk=subscription_id).first()


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------
def get_required_payment(payment_id: int) -> Payment:
    payment = get_payment_by_id(payment_id)
    if payment is None:
        raise PaymentNotFound()
    return payment


def get_payment_by_external_reference(provider: str, external_transaction_id: str) -> Payment:
    payment = get_payment_by_transaction(provider, external_transaction_id)
    if payment is None:
        raise PaymentNotFound()
    return payment


def handle_provider_callback(
    *,
    provider: str,
    external_transaction_id: str,
    payload: dict[str, Any] | None = None,
) -> Payment:
    """Webhook entry point shared by every provider.

    The whole flow is idempotent: replaying the same callback twice is safe.
    """
    payment = get_payment_by_transaction(provider, external_transaction_id)
    if payment is None:
        raise PaymentNotFound(
            "Bunday tranzaksiya ID bo'yicha to'lov topilmadi.",
            details={"provider": provider, "external_transaction_id": external_transaction_id},
        )
    try:
        return verify_payment(payment, payload=payload or {})
    except PaymentAlreadyProcessed as exc:
        # A duplicated webhook is not an error for the provider: return the
        # current state so that they stop retrying.
        logger.info("To'lov allaqachon qayta ishlangan: #%s", payment.pk)
        payment.refresh_from_db()
        return payment
    except PaymentProviderNotConfigured:
        raise


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _lock_payment(payment_id: int) -> Payment:
    queryset = Payment.objects.all()
    if connection.features.has_select_for_update:
        queryset = Payment.objects.select_for_update()
    return queryset.select_related("user").get(pk=payment_id)


def _to_decimal(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


__all__ = [
    "build_payment_invoice",
    "build_subscription_payment_invoice",
    "cancel_payment",
    "create_payment",
    "get_payment_by_external_reference",
    "get_required_payment",
    "handle_provider_callback",
    "process_failed_payment",
    "process_successful_payment",
    "refund_payment",
    "verify_payment",
]
