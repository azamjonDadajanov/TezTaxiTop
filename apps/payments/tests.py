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


class PaymentAdminTests(PaymentTestBase):
    """The admin is the only place an operator can settle a cash payment."""

    def setUp(self) -> None:
        super().setUp()
        self.client.force_login(self.data.create_superuser())

    def test_payment_changelist_renders(self) -> None:
        self.create_payment()
        response = self.client.get("/admin/payments/payment/")
        self.assertEqual(response.status_code, 200)

    def test_provider_panel_is_rendered_not_just_computed(self) -> None:
        """`changelist_view` used to pass provider_status into the context with
        no template to draw it, so a misconfigured gateway stayed invisible."""
        response = self.client.get("/admin/payments/payment/")
        self.assertIn("provider_status", response.context_data)
        self.assertContains(response, "provayderlari")

    def test_credential_free_providers_are_not_reported_as_broken(self) -> None:
        """Cash and `other` need no credentials; flagging them teaches the
        operator to ignore the panel."""
        response = self.client.get("/admin/payments/payment/")
        status = {item["code"]: item["configured"] for item in response.context_data["provider_status"]}
        self.assertTrue(status[PaymentProvider.CASH])
        self.assertTrue(status[PaymentProvider.OTHER])

    def test_existing_payments_render_read_only_and_reject_writes(self) -> None:
        """`has_change_permission = False` makes Django fall back to view-only
        rather than 403, so assert the invariant that matters: the row cannot be
        altered through this URL."""
        payment = self.create_payment(external_transaction_id="immutable-1")
        original_amount = payment.amount

        response = self.client.get(f"/admin/payments/payment/{payment.pk}/change/")
        self.assertEqual(response.status_code, 200)

        self.client.post(
            f"/admin/payments/payment/{payment.pk}/change/",
            {
                "user": self.driver.user.pk,
                "payment_type": PaymentType.SUBSCRIPTION,
                "amount": "1.00",
                "provider": PaymentProvider.CLICK,
                "external_transaction_id": "hijacked",
                "metadata": "{}",
            },
        )
        payment.refresh_from_db()
        self.assertEqual(payment.amount, original_amount)
        self.assertEqual(payment.external_transaction_id, "immutable-1")

    def test_superuser_can_open_the_add_form(self) -> None:
        response = self.client.get("/admin/payments/payment/add/")
        self.assertEqual(response.status_code, 200)

    def test_staff_without_superuser_cannot_add(self) -> None:
        """The add form is superuser-only: an accidental success row would skip
        payment verification entirely."""
        staff = self.data.create_passenger(is_staff=True, is_superuser=False)
        self.client.force_login(staff)
        self.assertEqual(self.client.get("/admin/payments/payment/add/").status_code, 403)

    def test_hand_entered_payment_is_forced_to_pending(self) -> None:
        """A crafted POST must not be able to set status=success, which would
        bypass process_successful_payment and skip the subscription activation
        and user notification it performs."""
        before = Payment.objects.count()
        response = self.client.post(
            "/admin/payments/payment/add/",
            {
                "user": self.driver.user.pk,
                "payment_type": PaymentType.SUBSCRIPTION,
                "amount": "25000.00",
                "provider": PaymentProvider.CASH,
                "external_transaction_id": "hand-entered-1",
                "metadata": "{}",
                "status": PaymentStatus.SUCCESS,
                "paid_at_0": "2026-01-01",
                "paid_at_1": "10:00:00",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Payment.objects.count(), before + 1)
        payment = Payment.objects.get(external_transaction_id="hand-entered-1")
        self.assertEqual(payment.status, PaymentStatus.PENDING)
        self.assertIsNone(payment.paid_at)

    def test_negative_amount_is_rejected(self) -> None:
        before = Payment.objects.count()
        response = self.client.post(
            "/admin/payments/payment/add/",
            {
                "user": self.driver.user.pk,
                "payment_type": PaymentType.SUBSCRIPTION,
                "amount": "-500.00",
                "provider": PaymentProvider.CASH,
                "external_transaction_id": "negative-1",
                "metadata": "{}",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Payment.objects.count(), before)

    def test_confirm_action_settles_a_hand_entered_payment(self) -> None:
        """The add form creates PENDING rows; the action is what finalises them,
        so the normal side effects still run."""
        payment = self.create_payment(
            provider=PaymentProvider.CASH,
            external_transaction_id="to-confirm-1",
            metadata={"subscription_id": self.subscription.pk},
        )
        self.client.post(
            "/admin/payments/payment/",
            {
                "action": "confirm_cash_payments",
                "_selected_action": [str(payment.pk)],
            },
            follow=True,
        )
        payment.refresh_from_db()
        self.assertEqual(payment.status, PaymentStatus.SUCCESS)
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, DriverSubscriptionStatus.ACTIVE)

    def test_confirm_action_refuses_a_gateway_payment(self) -> None:
        """Only providers with no server callback may be settled by hand."""
        payment = self.create_payment(provider=PaymentProvider.CLICK, external_transaction_id="click-1")
        self.client.post(
            "/admin/payments/payment/",
            {"action": "confirm_cash_payments", "_selected_action": [str(payment.pk)]},
            follow=True,
        )
        payment.refresh_from_db()
        self.assertEqual(payment.status, PaymentStatus.PENDING)
