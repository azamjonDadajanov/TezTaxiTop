"""Tests for the payments app.

Money is the one place where "close enough" is unacceptable, so the suite pins
down: no payment can be completed without server-side verification, every state
change is idempotent, refunds keep the ledger truthful, and a successful
subscription payment activates exactly one subscription.
"""

from __future__ import annotations

from decimal import Decimal
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from apps.core.exceptions import (
    BusinessValidationError,
    PaymentAlreadyProcessed,
    PaymentError,
    PaymentVerificationFailed,
)
from apps.payments.providers import VerificationResult
from apps.core.testing import TaxiTestData
from apps.payments import services as payment_services
from apps.payments.models import Payment, PaymentProvider, PaymentStatus, PaymentType
from apps.subscriptions.models import DriverSubscription, DriverSubscriptionStatus
from apps.subscriptions.services import create_subscription


class PaymentTestBase(TestCase):
    def setUp(self) -> None:
        self.data = TaxiTestData()
        self.driver = self.data.create_driver(with_subscription=False)
        self.plan = self.data.get_or_create_plan()
        self.subscription = create_subscription(driver=self.driver.profile, plan=self.plan)

    def create_payment(self, **kwargs) -> Payment:
        defaults = {
            "user": self.driver.user,
            "amount": self.plan.price,
            "payment_type": PaymentType.SUBSCRIPTION,
            "metadata": {"subscription_id": self.subscription.pk},
        }
        defaults.update(kwargs)
        return payment_services.create_payment(**defaults)


class PaymentCreationTests(PaymentTestBase):
    def test_payment_starts_pending(self) -> None:
        payment = self.create_payment()
        self.assertEqual(payment.status, PaymentStatus.PENDING)
        self.assertIsNone(payment.paid_at)
        self.assertEqual(payment.amount, self.plan.price)

    def test_amount_is_stored_as_decimal(self) -> None:
        payment = self.create_payment(amount="49999.99")
        self.assertIsInstance(payment.amount, Decimal)
        self.assertEqual(payment.amount, Decimal("49999.99"))

    def test_negative_amount_is_rejected(self) -> None:
        with self.assertRaises(BusinessValidationError):
            self.create_payment(amount=Decimal("-1.00"))

    def test_external_reference_is_unique_per_provider(self) -> None:
        from django.db import IntegrityError, transaction

        self.create_payment(external_transaction_id="tx-1")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Payment.objects.create(
                    user=self.driver.user,
                    payment_type=PaymentType.SUBSCRIPTION,
                    amount=Decimal("1000.00"),
                    provider=PaymentProvider.CLICK,
                    external_transaction_id="tx-1",
                )


class PaymentStateTests(PaymentTestBase):
    def test_unverified_payment_cannot_be_completed(self) -> None:
        payment = self.create_payment()
        with self.assertRaises(PaymentError):
            payment_services.process_successful_payment(payment)
        payment.refresh_from_db()
        self.assertEqual(payment.status, PaymentStatus.PENDING)

    def test_verified_payment_succeeds_and_activates_the_subscription(self) -> None:
        payment = self.create_payment()
        payment = payment_services.process_successful_payment(payment, verified=True)
        self.assertEqual(payment.status, PaymentStatus.SUCCESS)
        self.assertIsNotNone(payment.paid_at)
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, DriverSubscriptionStatus.ACTIVE)

    def test_successful_payment_notifies_the_user(self) -> None:
        from apps.notifications.models import Notification, NotificationType

        payment = self.create_payment()
        payment_services.process_successful_payment(payment, verified=True)
        self.assertTrue(
            Notification.objects.filter(
                user=self.driver.user, type=NotificationType.PAYMENT_SUCCESS
            ).exists()
        )

    def test_processing_twice_is_refused(self) -> None:
        payment = self.create_payment()
        payment_services.process_successful_payment(payment, verified=True)
        with self.assertRaises(PaymentAlreadyProcessed):
            payment_services.process_successful_payment(payment, verified=True)

    def test_success_cannot_be_turned_into_a_failure(self) -> None:
        payment = self.create_payment()
        payment_services.process_successful_payment(payment, verified=True)
        with self.assertRaises(PaymentAlreadyProcessed):
            payment_services.process_failed_payment(payment, reason="xatosi")

    def test_failure_is_recorded_with_a_reason(self) -> None:
        payment = self.create_payment()
        payment = payment_services.process_failed_payment(payment, reason="Karta rad etildi")
        self.assertEqual(payment.status, PaymentStatus.FAILED)
        self.assertEqual(payment.failure_reason, "Karta rad etildi")

    def test_failure_notifies_the_user(self) -> None:
        from apps.notifications.models import Notification, NotificationType

        payment = self.create_payment()
        payment_services.process_failed_payment(payment, reason="rad")
        self.assertTrue(
            Notification.objects.filter(
                user=self.driver.user, type=NotificationType.PAYMENT_FAILED
            ).exists()
        )

    def test_failure_twice_is_idempotent(self) -> None:
        payment = self.create_payment()
        payment_services.process_failed_payment(payment, reason="rad")
        again = payment_services.process_failed_payment(payment, reason="rad")
        self.assertEqual(again.status, PaymentStatus.FAILED)

    def test_pending_payment_can_be_cancelled(self) -> None:
        payment = self.create_payment()
        payment = payment_services.cancel_payment(payment, reason="yopdi")
        self.assertEqual(payment.status, PaymentStatus.CANCELLED)

    def test_successful_payment_cannot_be_cancelled(self) -> None:
        payment = self.create_payment()
        payment_services.process_successful_payment(payment, verified=True)
        with self.assertRaises(PaymentAlreadyProcessed):
            payment_services.cancel_payment(payment)

    def test_cancelled_payment_cannot_be_completed(self) -> None:
        payment = self.create_payment()
        payment_services.cancel_payment(payment)
        with self.assertRaises(PaymentAlreadyProcessed):
            payment_services.process_successful_payment(payment, verified=True)


class RefundTests(PaymentTestBase):
    def _successful(self) -> Payment:
        payment = self.create_payment(external_transaction_id="tx-refund-1")
        return payment_services.process_successful_payment(payment, verified=True)

    def test_pending_payment_cannot_be_refunded(self) -> None:
        payment = self.create_payment(external_transaction_id="tx-refund-2")
        with self.assertRaises(PaymentError):
            payment_services.refund_payment(payment)

    def test_successful_payment_without_a_transaction_id_cannot_be_refunded(self) -> None:
        payment = payment_services.process_successful_payment(
            self.create_payment(), verified=True
        )
        with self.assertRaises(PaymentError):
            payment_services.refund_payment(payment, reason="bekor")

    def test_refund_without_provider_support_keeps_the_ledger_truthful(self) -> None:
        payment = self._successful()
        with mock.patch("apps.payments.services.get_payment_provider") as provider:
            provider.return_value.refund.return_value = {"ok": False}
            with self.assertRaises(PaymentError):
                payment_services.refund_payment(payment, reason="bekor")
        payment.refresh_from_db()
        self.assertIsNone(payment.refunded_at)
        self.assertEqual(payment.status, PaymentStatus.SUCCESS)

    def test_successful_refund_is_stamped(self) -> None:
        payment = self._successful()
        with mock.patch("apps.payments.services.get_payment_provider") as provider:
            provider.return_value.refund.return_value = {"ok": True}
            result = payment_services.refund_payment(payment, reason="bekor")
        payment.refresh_from_db()
        self.assertIsNotNone(result)
        self.assertIsNotNone(payment.refunded_at)
        self.assertEqual(payment.status, PaymentStatus.REFUNDED)

    def test_refund_amount_cannot_exceed_the_payment(self) -> None:
        payment = self._successful()
        with self.assertRaises(BusinessValidationError):
            payment_services.refund_payment(payment, amount=Decimal("999999.00"))

    def test_refund_twice_is_refused(self) -> None:
        payment = self._successful()
        with mock.patch("apps.payments.services.get_payment_provider") as provider:
            provider.return_value.refund.return_value = {"ok": True}
            payment_services.refund_payment(payment)
        with self.assertRaises(PaymentError):
            payment_services.refund_payment(payment)


class CallbackTests(PaymentTestBase):
    def test_callback_marks_the_payment_successful(self) -> None:
        payment = self.create_payment(external_transaction_id="tx-callback-1")
        with mock.patch("apps.payments.services.get_payment_provider") as provider:
            provider.return_value.verify.return_value = VerificationResult(is_verified=True)
            result = payment_services.handle_provider_callback(
                provider=PaymentProvider.CLICK,
                external_transaction_id="tx-callback-1",
            )
        payment.refresh_from_db()
        self.assertEqual(result.status, PaymentStatus.SUCCESS)
        self.assertEqual(payment.status, PaymentStatus.SUCCESS)
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, DriverSubscriptionStatus.ACTIVE)

    def test_replaying_a_callback_is_safe(self) -> None:
        payment = self.create_payment(external_transaction_id="tx-callback-2")
        with mock.patch("apps.payments.services.get_payment_provider") as provider:
            provider.return_value.verify.return_value = VerificationResult(is_verified=True)
            payment_services.handle_provider_callback(
                provider=PaymentProvider.CLICK, external_transaction_id="tx-callback-2"
            )
            result = payment_services.handle_provider_callback(
                provider=PaymentProvider.CLICK, external_transaction_id="tx-callback-2"
            )
        self.assertEqual(result.status, PaymentStatus.SUCCESS)
        self.assertEqual(DriverSubscription.objects.filter(status="active").count(), 1)

    def test_callback_for_an_unknown_transaction_is_rejected(self) -> None:
        from apps.core.exceptions import PaymentNotFound

        with self.assertRaises(PaymentNotFound):
            payment_services.handle_provider_callback(
                provider=PaymentProvider.CLICK, external_transaction_id="nope"
            )

    def test_failed_callback_marks_the_payment_failed(self) -> None:
        self.create_payment(external_transaction_id="tx-callback-3")
        with mock.patch("apps.payments.services.get_payment_provider") as provider:
            provider.return_value.verify.return_value = VerificationResult(is_verified=False)
            result = payment_services.handle_provider_callback(
                provider=PaymentProvider.CLICK, external_transaction_id="tx-callback-3"
            )
        self.assertEqual(result.status, PaymentStatus.FAILED)
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, DriverSubscriptionStatus.PENDING)

    def test_callback_with_a_mismatched_amount_is_rejected(self) -> None:
        payment = self.create_payment(external_transaction_id="tx-callback-4")
        with mock.patch("apps.payments.services.get_payment_provider") as provider:
            provider.return_value.verify.return_value = VerificationResult(
                is_verified=True, amount=Decimal("1.00")
            )
            with self.assertRaises(PaymentVerificationFailed):
                payment_services.handle_provider_callback(
                    provider=PaymentProvider.CLICK, external_transaction_id="tx-callback-4"
                )
        payment.refresh_from_db()
        self.assertEqual(payment.status, PaymentStatus.PENDING)


class SubscriptionLinkTests(PaymentTestBase):
    def test_payment_without_a_link_does_not_activate_anything(self) -> None:
        payment = self.create_payment(metadata={})
        payment_services.process_successful_payment(payment, verified=True)
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, DriverSubscriptionStatus.PENDING)

    def test_a_link_is_never_guessed_from_the_amount(self) -> None:
        """Two purchases of the same plan must not activate each other."""
        other = create_subscription(driver=self.driver.profile, plan=self.plan)
        other_payment = self.create_payment(metadata={"subscription_id": other.pk})
        payment_services.process_successful_payment(other_payment, verified=True)
        self.subscription.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(other.status, DriverSubscriptionStatus.ACTIVE)
        self.assertEqual(self.subscription.status, DriverSubscriptionStatus.PENDING)

    def test_invoice_links_the_payment_to_the_subscription(self) -> None:
        from apps.payments.models import PaymentProvider as Provider

        with mock.patch("apps.payments.services.get_payment_provider") as provider:
            provider.return_value.build_invoice.return_value = {"url": "https://pay.test/x"}
            payment, invoice = payment_services.build_subscription_payment_invoice(
                user=self.driver.user, subscription=self.subscription
            )
        self.assertEqual(invoice, {"url": "https://pay.test/x"})
        self.assertEqual(payment.payment_type, PaymentType.SUBSCRIPTION)
        self.assertEqual(payment.amount, self.plan.price)
        self.assertEqual(payment.metadata["subscription_id"], self.subscription.pk)
        payment_services.process_successful_payment(payment, verified=True)
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, DriverSubscriptionStatus.ACTIVE)
        self.assertIsNotNone(Provider)

    def test_only_the_linked_subscription_is_activated(self) -> None:
        other = create_subscription(driver=self.driver.profile, plan=self.plan)
        payment = self.create_payment(metadata={"subscription_id": self.subscription.pk})
        payment_services.process_successful_payment(payment, verified=True)
        self.subscription.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(self.subscription.status, DriverSubscriptionStatus.ACTIVE)
        self.assertEqual(other.status, DriverSubscriptionStatus.PENDING)

    def test_activation_is_not_repeated_for_a_second_payment(self) -> None:
        payment = self.create_payment()
        payment_services.process_successful_payment(payment, verified=True)
        started = self.subscription.starts_at
        second = self.create_payment()
        payment_services.process_successful_payment(second, verified=True)
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, DriverSubscriptionStatus.ACTIVE)
        self.assertEqual(self.subscription.starts_at, started)
        self.assertEqual(Payment.objects.filter(status=PaymentStatus.SUCCESS).count(), 2)

    def test_order_payments_do_not_activate_subscriptions(self) -> None:
        trip = self.data.create_trip(self.driver)
        order = self.data.create_order(trip, self.data.create_passenger())
        payment = self.create_payment(
            payment_type=PaymentType.ORDER,
            amount=order.total_amount,
            metadata={"order_id": order.pk},
        )
        payment_services.process_successful_payment(payment, verified=True)
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, DriverSubscriptionStatus.PENDING)
