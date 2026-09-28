"""Payment provider interface.

The platform must never trust a client (or a Telegram message) that says
"payment succeeded". Therefore every provider integration is expressed through
the abstract :class:`BasePaymentProvider`:

* :meth:`BasePaymentProvider.build_invoice` - create a payment intent.
* :meth:`BasePaymentProvider.verify` - **server to server** verification of a
  transaction; this is the only authority allowed to mark a payment successful.
* :meth:`BasePaymentProvider.refund` - optional refund request.

Concrete providers are deliberately *strict*: without configured credentials
they raise :class:`~apps.core.exceptions.PaymentProviderNotConfigured` instead
of pretending to succeed. That keeps the integration honest and testable while
the real merchant accounts are being obtained.
"""

from __future__ import annotations

import abc
import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from django.conf import settings

from apps.core.exceptions import (
    PaymentProviderNotConfigured,
    PaymentVerificationFailed,
)
from apps.payments.models import PaymentProvider

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VerificationResult:
    """Normalised result of a server side verification."""

    is_verified: bool
    external_transaction_id: str | None = None
    amount: Decimal | None = None
    paid_at: Any | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_metadata(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"verified": self.is_verified}
        if self.external_transaction_id:
            payload["external_transaction_id"] = self.external_transaction_id
        if self.amount is not None:
            payload["amount"] = str(self.amount)
        if self.paid_at is not None:
            payload["paid_at"] = str(self.paid_at)
        return payload


class BasePaymentProvider(abc.ABC):
    """Common interface implemented by every payment gateway."""

    #: Value of :class:`~apps.payments.models.PaymentProvider` this class serves.
    code: str = ""

    def __init__(self, credentials: dict[str, str] | None = None) -> None:
        self.credentials = credentials or self._credentials_from_settings()

    def _credentials_from_settings(self) -> dict[str, str]:
        return dict(getattr(settings, "PAYMENT_PROVIDERS", {}).get(self.code.upper(), {}))

    def is_configured(self) -> bool:
        """True when every credential required by the provider is present."""
        return all(value for value in self.credentials.values()) if self.credentials else False

    def _assert_configured(self) -> None:
        if not self.is_configured():
            raise PaymentProviderNotConfigured(
                f"'{self.code}' provayderi uchun sozlamalar to'liq emas "
                "(PAYMENT_* muhit o'zgaruvchilarini tekshiring)."
            )

    # -- interface ------------------------------------------------------------
    @abc.abstractmethod
    def build_invoice(self, *, amount: Decimal, reference: str, description: str = "") -> dict[str, Any]:
        """Return provider specific payment intent data for the client."""

    @abc.abstractmethod
    def verify(self, *, external_transaction_id: str | None, payload: dict[str, Any]) -> VerificationResult:
        """Verify a transaction **server side** and return the normalised result."""

    def refund(self, *, external_transaction_id: str, amount: Decimal | None = None) -> dict[str, Any]:
        """Request a refund. Not every provider supports it."""
        raise PaymentProviderNotConfigured(
            f"'{self.code}' provayderi orqali qaytarish hozircha qo'llab-quvvatlanmaydi."
        )


class UnconfiguredProvider(BasePaymentProvider):
    """Placeholder provider used when a gateway has no credentials yet.

    It fails loudly instead of silently "succeeding", which is the only safe
    behaviour for money.
    """

    def build_invoice(self, *, amount: Decimal, reference: str, description: str = "") -> dict[str, Any]:
        raise PaymentProviderNotConfigured(
            f"'{self.code}' provayderi hali sozlanmagan, to'lov yaratib bo'lmaydi."
        )

    def verify(self, *, external_transaction_id: str | None, payload: dict[str, Any]) -> VerificationResult:
        raise PaymentProviderNotConfigured(
            f"'{self.code}' provayderi hali sozlanmagan, to'lovni tasdiqlab bo'lmaydi."
        )


class ClickProvider(BasePaymentProvider):
    """Click payment gateway (Uzbekistan).

    Credentials: ``PAYMENT_CLICK_MERCHANT_ID`` / ``_SECRET_KEY`` / ``_SERVICE_TOKEN``.
    The real HTTP call is intentionally not faked: :meth:`verify` performs the
    documented service-token request and refuses to run without credentials.
    """

    code = PaymentProvider.CLICK
    service_url = "https://api.click.uz/v2/merchant_payment"

    def build_invoice(self, *, amount: Decimal, reference: str, description: str = "") -> dict[str, Any]:
        self._assert_configured()
        return {
            "provider": self.code,
            "amount": str(amount),
            "reference": reference,
            "description": description,
            "service_url": self.service_url,
        }

    def verify(self, *, external_transaction_id: str | None, payload: dict[str, Any]) -> VerificationResult:
        self._assert_configured()
        if not external_transaction_id:
            raise PaymentVerificationFailed("Click: tranzaksiya ID kelmagan.")
        return _verify_via_service_call(
            provider_name=self.code,
            url=self.service_url,
            token=self.credentials.get("SERVICE_TOKEN", ""),
            body={"transaction_id": external_transaction_id, **payload},
        )


class PaymeProvider(BasePaymentProvider):
    """Payme payment gateway (Uzbekistan)."""

    code = PaymentProvider.PAYME
    base_url = "https://api.payme.uz/v1"

    def build_invoice(self, *, amount: Decimal, reference: str, description: str = "") -> dict[str, Any]:
        self._assert_configured()
        return {
            "provider": self.code,
            "amount_in_tiyn": int(amount * Decimal("100")),
            "reference": reference,
            "description": description,
            "base_url": self.base_url,
        }

    def verify(self, *, external_transaction_id: str | None, payload: dict[str, Any]) -> VerificationResult:
        self._assert_configured()
        if not external_transaction_id:
            raise PaymentVerificationFailed("Payme: tranzaksiya ID kelmagan.")
        return _verify_via_service_call(
            provider_name=self.code,
            url=f"{self.base_url}/payments/{external_transaction_id}",
            token=self.credentials.get("SECRET_KEY", ""),
            body={},
        )


class UzumProvider(BasePaymentProvider):
    """Uzum payment gateway (Uzbekistan)."""

    code = PaymentProvider.UZUM
    base_url = "https://api.uzum.com/api"

    def build_invoice(self, *, amount: Decimal, reference: str, description: str = "") -> dict[str, Any]:
        self._assert_configured()
        return {
            "provider": self.code,
            "amount_in_sum": str(amount),
            "reference": reference,
            "description": description,
            "base_url": self.base_url,
        }

    def verify(self, *, external_transaction_id: str | None, payload: dict[str, Any]) -> VerificationResult:
        self._assert_configured()
        if not external_transaction_id:
            raise PaymentVerificationFailed("Uzum: tranzaksiya ID kelmagan.")
        return _verify_via_service_call(
            provider_name=self.code,
            url=f"{self.base_url}/transactions/{external_transaction_id}",
            token=self.credentials.get("SECRET_KEY", ""),
            body={},
        )


class CashProvider(BasePaymentProvider):
    """Offline cash payment.

    Cash has no server to call, so verification is an **explicit admin action**:
    the administrator confirms the money was collected. The bot may only
    *request* a payment; it can never mark it successful.
    """

    code = PaymentProvider.CASH

    def build_invoice(self, *, amount: Decimal, reference: str, description: str = "") -> dict[str, Any]:
        return {
            "provider": self.code,
            "amount": str(amount),
            "reference": reference,
            "description": description,
            "requires_manual_confirmation": True,
        }

    def verify(self, *, external_transaction_id: str | None, payload: dict[str, Any]) -> VerificationResult:
        raise PaymentProviderNotConfigured(
            "Naqd to'lov faqat administrator tasdig'i bilan tasdiqlanadi."
        )


class OtherProvider(UnconfiguredProvider):
    """Generic placeholder for future gateways."""

    code = PaymentProvider.OTHER


def _verify_via_service_call(
    *,
    provider_name: str,
    url: str,
    token: str,
    body: dict[str, Any],
) -> VerificationResult:
    """Perform the provider's verification request.

    The HTTP call is intentionally executed with ``urllib`` from the standard
    library so that the platform does not depend on a payment SDK. Failures are
    converted into business exceptions - a payment is never silently trusted.
    """
    import json
    import urllib.error
    import urllib.request

    if not token:
        raise PaymentProviderNotConfigured(f"{provider_name}: token/secret sozlanmagan.")

    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "X-Request-ID": body.get("transaction_id", ""),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310 - fixed https host
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise PaymentVerificationFailed(
            f"{provider_name}: tasdiqlash so'rovi bajarilmadi ({exc})."
        ) from exc

    status_text = str(data.get("status", "")).lower()
    verified = status_text in {"completed", "success", "paid", "confirmed", "ok"}
    return VerificationResult(
        is_verified=verified,
        external_transaction_id=str(
            data.get("transaction_id") or data.get("payment_id") or data.get("id") or ""
        )
        or None,
        amount=Decimal(str(data["amount"])) if data.get("amount") is not None else None,
        paid_at=data.get("paid_at") or data.get("created_at"),
        raw=data,
    )


#: Registry of provider implementations.
PROVIDER_REGISTRY: dict[str, type[BasePaymentProvider]] = {
    PaymentProvider.CLICK: ClickProvider,
    PaymentProvider.PAYME: PaymeProvider,
    PaymentProvider.UZUM: UzumProvider,
    PaymentProvider.CASH: CashProvider,
    PaymentProvider.OTHER: OtherProvider,
}


def get_payment_provider(provider: str) -> BasePaymentProvider:
    """Return a provider instance for the given code.

    An unknown provider code raises instead of returning a permissive default.
    """
    provider_class = PROVIDER_REGISTRY.get(provider)
    if provider_class is None:
        raise PaymentProviderNotConfigured(
            f"Noma'lum to'lov provayderi: {provider}. "
            f"Mavjudlar: {', '.join(sorted(PROVIDER_REGISTRY))}."
        )
    return provider_class()


__all__ = [
    "BasePaymentProvider",
    "CashProvider",
    "ClickProvider",
    "OtherProvider",
    "PROVIDER_REGISTRY",
    "PaymeProvider",
    "UnconfiguredProvider",
    "UzumProvider",
    "VerificationResult",
    "get_payment_provider",
]
