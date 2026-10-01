"""Tests for the subscriptions app."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.contrib import admin
from django.db import IntegrityError, transaction
from django.test import TestCase
from rest_framework.test import APIClient
from django.utils import timezone

from apps.core.exceptions import BusinessValidationError, InvalidSubscription
from apps.core.testing import TaxiTestData
from apps.payments import services as payment_services
from apps.payments.models import Payment, PaymentProvider
from apps.payments.providers import VerificationResult
from apps.subscriptions import services as subscription_services
from apps.subscriptions.models import (
    DriverSubscription,
    DriverSubscriptionStatus,
    SubscriptionPlan,
)
from apps.users import services as user_services
from apps.users.constants import UserRole
from apps.users.models import User


class SubscriptionPlanTests(TestCase):
    def test_create_plan(self) -> None:
        plan = subscription_services.create_plan(
            name="1 oy", duration_days=30, price=Decimal("45000.00"), description="Oylik obuna"
        )
        self.assertEqual(plan.duration_days, 30)
        self.assertEqual(plan.price, Decimal("45000.00"))
        self.assertTrue(plan.is_active)

    def test_duration_must_be_positive(self) -> None:
        with self.assertRaises(BusinessValidationError):
            subscription_services.create_plan(name="X", duration_days=0, price=Decimal("1000.00"))

    def test_negative_price_rejected(self) -> None:
        with self.assertRaises(BusinessValidationError):
            subscription_services.create_plan(name="X", duration_days=30, price=Decimal("-1.00"))

    def test_duration_is_configurable(self) -> None:
        trial = subscription_services.create_plan(
            name="Sinov", duration_days=10, price=Decimal("0.00")
        )
        self.assertEqual(trial.duration_days, 10)
        self.assertEqual(trial.price, Decimal("0.00"))


class DriverSubscriptionTests(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(username="ali", telegram_id=1, role=UserRole.DRIVER)
        self.driver = user_services.create_driver_profile(self.user)
        self.plan = subscription_services.create_plan(
            name="1 oy", duration_days=30, price=Decimal("45000.00")
        )

    def test_create_subscription_is_pending(self) -> None:
        subscription = subscription_services.create_subscription(driver=self.driver, plan=self.plan)
        self.assertEqual(subscription.status, DriverSubscriptionStatus.PENDING)
        self.assertFalse(subscription_services.has_active_subscription(self.driver))

    def test_activate_subscription(self) -> None:
        subscription = subscription_services.create_subscription(driver=self.driver, plan=self.plan)
        subscription = subscription_services.activate_subscription(subscription)
        self.assertEqual(subscription.status, DriverSubscriptionStatus.ACTIVE)
        self.assertTrue(subscription_services.has_active_subscription(self.driver))
        self.assertEqual(subscription.expires_at - subscription.starts_at, timedelta(days=30))

    def test_activation_is_idempotent(self) -> None:
        subscription = subscription_services.create_subscription(driver=self.driver, plan=self.plan)
        first = subscription_services.activate_subscription(subscription)
        expiry_after_first = first.expires_at
        second = subscription_services.activate_subscription(first)
        self.assertEqual(second.expires_at, expiry_after_first)
        self.assertEqual(DriverSubscription.objects.count(), 1)

    def test_price_is_snapshotted_at_purchase(self) -> None:
        subscription = subscription_services.create_subscription(driver=self.driver, plan=self.plan)
        self.assertEqual(subscription.price_at_purchase, Decimal("45000.00"))
        # Administrator raises the plan price afterwards.
        subscription_services.update_plan(self.plan, price=Decimal("60000.00"))
        subscription.refresh_from_db()
        self.assertEqual(subscription.price_at_purchase, Decimal("45000.00"))

    def test_expire_subscription(self) -> None:
        subscription = subscription_services.create_subscription(driver=self.driver, plan=self.plan)
        subscription = subscription_services.activate_subscription(subscription)
        subscription = subscription_services.expire_subscription(subscription)
        self.assertEqual(subscription.status, DriverSubscriptionStatus.EXPIRED)
        self.assertFalse(subscription_services.has_active_subscription(self.driver))

    def test_expire_is_idempotent(self) -> None:
        subscription = subscription_services.create_subscription(driver=self.driver, plan=self.plan)
        subscription = subscription_services.activate_subscription(subscription)
        subscription_services.expire_subscription(subscription)
        subscription_services.expire_subscription(subscription)
        self.assertEqual(DriverSubscription.objects.count(), 1)

    def test_expire_due_subscriptions_task(self) -> None:
        subscription = subscription_services.create_subscription(driver=self.driver, plan=self.plan)
        subscription_services.activate_subscription(subscription)
        DriverSubscription.objects.filter(pk=subscription.pk).update(
            starts_at=timezone.now() - timedelta(days=1),
            expires_at=timezone.now() - timedelta(minutes=1),
        )
        expired = subscription_services.expire_due_subscriptions()
        self.assertEqual(expired, 1)
        # Running the task again changes nothing.
        self.assertEqual(subscription_services.expire_due_subscriptions(), 0)

    def test_cancel_subscription_keeps_history(self) -> None:
        subscription = subscription_services.create_subscription(driver=self.driver, plan=self.plan)
        subscription = subscription_services.activate_subscription(subscription)
        subscription = subscription_services.cancel_subscription(subscription)
        self.assertEqual(subscription.status, DriverSubscriptionStatus.CANCELLED)
        self.assertEqual(DriverSubscription.objects.filter(driver=self.driver).count(), 1)
        self.assertIsNotNone(subscription.cancelled_at)

    def test_extend_subscription(self) -> None:
        subscription = subscription_services.create_subscription(driver=self.driver, plan=self.plan)
        subscription = subscription_services.activate_subscription(subscription)
        original_expiry = subscription.expires_at
        subscription = subscription_services.extend_subscription(subscription, days=10)
        self.assertEqual(subscription.expires_at, original_expiry + timedelta(days=10))

    def test_extend_expired_subscription_restarts_period(self) -> None:
        subscription = subscription_services.create_subscription(driver=self.driver, plan=self.plan)
        subscription_services.activate_subscription(subscription)
        DriverSubscription.objects.filter(pk=subscription.pk).update(
            starts_at=timezone.now() - timedelta(days=31),
            expires_at=timezone.now() - timedelta(days=1),
        )
        subscription.refresh_from_db()
        subscription = subscription_services.extend_subscription(subscription, days=30)
        self.assertGreater(subscription.expires_at, timezone.now())
        self.assertEqual(subscription.status, DriverSubscriptionStatus.ACTIVE)

    def test_historical_subscriptions_are_kept(self) -> None:
        first = subscription_services.create_subscription(driver=self.driver, plan=self.plan)
        subscription_services.activate_subscription(first)
        subscription_services.cancel_subscription(first)
        second = subscription_services.create_subscription(driver=self.driver, plan=self.plan)
        subscription_services.activate_subscription(second)
        self.assertEqual(DriverSubscription.objects.filter(driver=self.driver).count(), 2)

    def test_only_one_active_subscription_per_driver(self) -> None:
        first = subscription_services.create_subscription(driver=self.driver, plan=self.plan)
        subscription_services.activate_subscription(first)
        second = subscription_services.create_subscription(driver=self.driver, plan=self.plan)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                DriverSubscription.objects.filter(pk=second.pk).update(
                    status=DriverSubscriptionStatus.ACTIVE
                )

    def test_new_purchase_extends_the_active_period(self) -> None:
        first = subscription_services.create_subscription(driver=self.driver, plan=self.plan)
        first = subscription_services.activate_subscription(first)
        expiry_before = first.expires_at
        second = subscription_services.create_subscription(driver=self.driver, plan=self.plan)
        merged = subscription_services.activate_subscription(second)
        self.assertEqual(merged.pk, first.pk)
        self.assertEqual(merged.expires_at, expiry_before + timedelta(days=30))
        second.refresh_from_db()
        self.assertEqual(second.status, DriverSubscriptionStatus.CANCELLED)

    def test_has_active_subscription_ignores_stale_status(self) -> None:
        subscription = subscription_services.create_subscription(driver=self.driver, plan=self.plan)
        subscription_services.activate_subscription(subscription)
        # The periodic task has not run yet, but the period is over.
        DriverSubscription.objects.filter(pk=subscription.pk).update(
            starts_at=timezone.now() - timedelta(days=1),
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        self.assertFalse(subscription_services.has_active_subscription(self.driver))

    def test_cannot_activate_cancelled_subscription(self) -> None:
        subscription = subscription_services.create_subscription(driver=self.driver, plan=self.plan)
        subscription_services.cancel_subscription(subscription)
        with self.assertRaises(InvalidSubscription):
            subscription_services.activate_subscription(subscription)

    def test_inactive_plan_cannot_be_purchased(self) -> None:
        subscription_services.update_plan(self.plan, is_active=False)
        with self.assertRaises(InvalidSubscription):
            subscription_services.create_subscription(driver=self.driver, plan=self.plan)

    def test_invalid_dates_rejected_by_database(self) -> None:
        subscription = subscription_services.create_subscription(driver=self.driver, plan=self.plan)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                DriverSubscription.objects.filter(pk=subscription.pk).update(
                    expires_at=subscription.starts_at
                )

    def test_subscription_model_helpers(self) -> None:
        subscription = subscription_services.create_subscription(driver=self.driver, plan=self.plan)
        subscription = subscription_services.activate_subscription(subscription)
        self.assertTrue(subscription.is_active_now())
        self.assertIn(subscription.days_remaining(), range(29, 31))
        plan = SubscriptionPlan.objects.get(pk=self.plan.pk)
        self.assertEqual(plan.price_as_int, 45000)

class SubscriptionPurchaseApiTests(TestCase):
    """The purchase endpoint must hand back a payable invoice, not just a row."""

    def setUp(self) -> None:
        self.data = TaxiTestData()
        self.driver = self.data.create_driver(with_subscription=False)
        self.plan = self.data.get_or_create_plan()
        self.client = APIClient()
        self.client.force_authenticate(self.driver.user)

    def test_purchase_creates_a_pending_subscription_and_an_invoice(self) -> None:
        with mock.patch("apps.payments.services.get_payment_provider") as provider:
            provider.return_value.build_invoice.return_value = {
                "url": "https://pay.test/inv",
                "transaction_id": "click-abc",
            }
            response = self.client.post(
                "/api/v1/subscriptions/subscriptions/purchase/",
                {"plan_id": self.plan.pk, "auto_renew": False},
                format="json",
            )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["subscription"]["status"], "pending")
        self.assertEqual(response.data["payment"]["status"], "pending")
        self.assertEqual(response.data["payment"]["amount"], str(self.plan.price))
        self.assertEqual(response.data["invoice"]["url"], "https://pay.test/inv")

        payment = Payment.objects.get(pk=response.data["payment"]["id"])
        subscription = DriverSubscription.objects.get(pk=response.data["subscription"]["id"])
        self.assertEqual(payment.metadata["subscription_id"], subscription.pk)
        # The provider id is what its webhook will quote back to us.
        self.assertEqual(payment.external_transaction_id, "click-abc")

    def test_provider_callback_activates_exactly_that_subscription(self) -> None:
        with mock.patch("apps.payments.services.get_payment_provider") as provider:
            provider.return_value.build_invoice.return_value = {
                "url": "https://pay.test/inv",
                "transaction_id": "click-xyz",
            }
            response = self.client.post(
                "/api/v1/subscriptions/subscriptions/purchase/",
                {"plan_id": self.plan.pk},
                format="json",
            )
        subscription_id = response.data["subscription"]["id"]

        with mock.patch("apps.payments.services.get_payment_provider") as provider:
            provider.return_value.verify.return_value = VerificationResult(is_verified=True)
            payment_services.handle_provider_callback(
                provider=PaymentProvider.CLICK,
                external_transaction_id="click-xyz",
                payload={},
            )
        self.assertEqual(DriverSubscription.objects.get(pk=subscription_id).status, "active")
        self.assertEqual(
            Payment.objects.get(pk=response.data["payment"]["id"]).status, "success"
        )

    def test_purchase_requires_authentication(self) -> None:
        self.client.force_authenticate(None)
        response = self.client.post(
            "/api/v1/subscriptions/subscriptions/purchase/", {"plan_id": self.plan.pk}, format="json"
        )
        self.assertIn(response.status_code, (401, 403))

    def test_purchase_requires_a_driver_profile(self) -> None:
        self.client.force_authenticate(self.data.create_passenger())
        response = self.client.post(
            "/api/v1/subscriptions/subscriptions/purchase/", {"plan_id": self.plan.pk}, format="json"
        )
        # The permission layer rejects a passenger before the view body runs.
        self.assertEqual(response.status_code, 403)


class SubscriptionAdminTests(TestCase):
    """`price_at_purchase` is a NOT NULL column with no default.

    It was listed in ``readonly_fields``, so the add form never submitted it
    and every hand-created subscription raised ``IntegrityError: NOT NULL
    constraint failed: subscriptions_driversubscription.price_at_purchase``.
    """

    def setUp(self) -> None:
        self.data = TaxiTestData()
        self.admin = self.data.create_superuser()
        self.driver = self.data.create_driver(with_subscription=False)
        self.plan = self.data.get_or_create_plan()
        self.client.force_login(self.admin)

    def _payload(self, **overrides) -> dict:
        data = {
            "driver": self.driver.profile.pk,
            "plan": self.plan.pk,
            "starts_at_0": "2026-01-01",
            "starts_at_1": "10:00:00",
            "expires_at_0": "2026-02-01",
            "expires_at_1": "10:00:00",
            "status": DriverSubscriptionStatus.PENDING,
            "price_at_purchase": "45000.00",
        }
        data.update(overrides)
        return data

    def test_add_form_is_reachable(self) -> None:
        self.assertEqual(self.client.get("/admin/subscriptions/driversubscription/add/").status_code, 200)

    def test_add_form_exposes_the_price(self) -> None:
        response = self.client.get("/admin/subscriptions/driversubscription/add/")
        self.assertContains(response, 'name="price_at_purchase"')

    def test_creating_a_subscription_no_longer_raises_integrity_error(self) -> None:
        before = DriverSubscription.objects.count()
        response = self.client.post("/admin/subscriptions/driversubscription/add/", self._payload())
        self.assertEqual(response.status_code, 302)
        self.assertEqual(DriverSubscription.objects.count(), before + 1)

    def test_price_defaults_from_the_plan_when_omitted(self) -> None:
        """``save_model`` snapshots the plan price, so the column can never be
        left null by a crafted POST."""
        subscription = subscription_services.create_subscription(
            driver=self.driver.profile, plan=self.plan
        )
        subscription.price_at_purchase = None
        admin_obj = admin.site._registry[DriverSubscription]
        admin_obj.save_model(None, subscription, None, False)
        self.assertEqual(subscription.price_at_purchase, self.plan.price)

    def test_existing_subscription_price_is_still_read_only(self) -> None:
        subscription = subscription_services.create_subscription(
            driver=self.driver.profile, plan=self.plan
        )
        response = self.client.get(
            f"/admin/subscriptions/driversubscription/{subscription.pk}/change/"
        )
        self.assertNotContains(response, 'name="price_at_purchase"')