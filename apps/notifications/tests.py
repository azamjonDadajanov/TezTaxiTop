"""Tests for the notification app and its Celery delivery task."""

from __future__ import annotations

from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from apps.core.testing import TaxiTestData
from apps.notifications import services as notification_services
from apps.notifications import tasks as notification_tasks
from apps.notifications.models import Notification, NotificationType
from apps.orders import services as order_services
from apps.users.models import User


class NotificationTestBase(TestCase):
    def setUp(self) -> None:
        self.data = TaxiTestData()
        self.driver = self.data.create_driver()
        self.passenger = self.data.create_passenger()
        self.trip = self.data.create_trip(self.driver)
        self.order = self.data.create_order(self.trip, self.passenger)


class NotificationCreationTests(NotificationTestBase):
    def test_new_order_notifies_the_driver(self) -> None:
        notification = Notification.objects.filter(
            user=self.driver.user, type=NotificationType.NEW_ORDER
        ).first()
        self.assertIsNotNone(notification)
        self.assertFalse(notification.is_read)
        self.assertFalse(notification.is_sent)
        self.assertTrue(notification.title)

    def test_accept_notifies_the_passenger(self) -> None:
        order_services.accept_order(self.order)
        self.assertTrue(
            Notification.objects.filter(
                user=self.passenger, type=NotificationType.ORDER_ACCEPTED
            ).exists()
        )

    def test_passenger_cancellation_notifies_the_driver_only(self) -> None:
        order_services.accept_order(self.order)
        Notification.objects.all().delete()
        order_services.cancel_order_by_passenger(self.order, reason="reja o'zgardi")
        recipients = set(Notification.objects.values_list("user_id", flat=True))
        self.assertEqual(recipients, {self.driver.user.pk})

    def test_driver_cancellation_notifies_the_passenger_only(self) -> None:
        order_services.accept_order(self.order)
        Notification.objects.all().delete()
        order_services.cancel_order_by_driver(self.order, reason="mashina buzildi")
        recipients = set(Notification.objects.values_list("user_id", flat=True))
        self.assertEqual(recipients, {self.passenger.pk})

    def test_every_notification_targets_exactly_one_user(self) -> None:
        order_services.accept_order(self.order)
        for notification in Notification.objects.all():
            self.assertIsNotNone(notification.user_id)
            self.assertNotEqual(notification.user_id, 0)

    def test_message_notification_is_created_for_the_other_side(self) -> None:
        from apps.chat import services as chat_services

        thread = chat_services.ensure_thread_for_order(self.order)
        message = chat_services.send_message(thread=thread, sender=self.passenger, text="salom")
        notification_services.create_new_message_notification(
            message, recipient=self.driver.user
        )
        self.assertTrue(
            Notification.objects.filter(
                user=self.driver.user, type=NotificationType.NEW_MESSAGE
            ).exists()
        )

    def test_bulk_creation(self) -> None:
        created = notification_services.create_notifications(
            users=[self.passenger, self.passenger],
            notification_type=NotificationType.SYSTEM,
            title="Sinov",
            message="Matn",
        )
        self.assertEqual(len(created), 2)


class NotificationReadStateTests(NotificationTestBase):
    def test_mark_single_as_read(self) -> None:
        notification = Notification.objects.filter(user=self.driver.user).first()
        self.assertIsNotNone(notification)
        updated = notification_services.mark_as_read(notification)
        self.assertTrue(updated.is_read)
        self.assertIsNotNone(updated.read_at)

    def test_mark_all_as_read_only_touches_the_owner(self) -> None:
        notification_services.mark_all_as_read(self.passenger)
        self.assertEqual(Notification.objects.filter(user=self.passenger, is_read=False).count(), 0)
        self.assertTrue(
            Notification.objects.filter(user=self.driver.user, is_read=False).exists()
        )

    def test_mark_all_is_idempotent(self) -> None:
        first = notification_services.mark_all_as_read(self.passenger)
        second = notification_services.mark_all_as_read(self.passenger)
        self.assertEqual(first, second)


class NotificationDeliveryTests(NotificationTestBase):
    def setUp(self) -> None:
        super().setUp()
        # Only the notifications created by a test itself take part in the
        # delivery assertions.
        Notification.objects.all().delete()
        User.objects.filter(pk=self.passenger.pk).update(telegram_id=555000111)

    def _pending(self) -> Notification:
        return Notification.objects.create(
            user=self.passenger,
            type=NotificationType.SYSTEM,
            title="Sinov",
            message="Matn",
        )

    def test_task_skips_users_without_telegram(self) -> None:
        User.objects.filter(pk=self.passenger.pk).update(telegram_id=None)
        notification = self._pending()
        result = notification_tasks.deliver_pending_notifications_task(limit=10)
        notification.refresh_from_db()
        self.assertEqual(result["sent"], 0)
        self.assertEqual(result["processed"], 0)
        self.assertFalse(notification.is_sent)

    def test_task_skips_blocked_users(self) -> None:
        User.objects.filter(pk=self.passenger.pk).update(is_blocked=True)
        notification = self._pending()
        notification_tasks.deliver_pending_notifications_task(limit=10)
        notification.refresh_from_db()
        self.assertFalse(notification.is_sent)

    def test_task_sends_and_marks_as_sent(self) -> None:
        notification = self._pending()
        with mock.patch("apps.core.telegram.TelegramGateway.send_message") as send:
            send.return_value = {"ok": True, "result": {"message_id": 1}}
            result = notification_tasks.deliver_pending_notifications_task(limit=10)
        notification.refresh_from_db()
        self.assertEqual(result["sent"], 1)
        self.assertTrue(notification.is_sent)
        self.assertIsNotNone(notification.sent_at)
        self.assertEqual(send.call_count, 1)
        self.assertEqual(send.call_args.kwargs["chat_id"], 555000111)

    def test_already_sent_notifications_are_not_resent(self) -> None:
        notification = self._pending()
        notification_services.mark_as_sent(notification)
        with mock.patch("apps.core.telegram.TelegramGateway.send_message") as send:
            result = notification_tasks.deliver_pending_notifications_task(limit=10)
        self.assertEqual(result["sent"], 0)
        self.assertEqual(send.call_count, 0)

    def test_failed_delivery_is_recorded_and_retried_later(self) -> None:
        notification = self._pending()
        with mock.patch("apps.core.telegram.TelegramGateway.send_message") as send:
            send.side_effect = RuntimeError("telegram down")
            result = notification_tasks.deliver_pending_notifications_task(limit=10)
        notification.refresh_from_db()
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["dropped"], 0)
        self.assertFalse(notification.is_sent)
        self.assertEqual(notification.attempts, 1)
        self.assertIn("telegram down", notification.last_error)

    def test_delivery_gives_up_after_the_retry_budget(self) -> None:
        from apps.notifications.constants import MAX_DELIVERY_ATTEMPTS

        notification = self._pending()
        Notification.objects.filter(pk=notification.pk).update(
            attempts=MAX_DELIVERY_ATTEMPTS - 1
        )
        with mock.patch("apps.core.telegram.TelegramGateway.send_message") as send:
            send.side_effect = RuntimeError("telegram down")
            result = notification_tasks.deliver_pending_notifications_task(limit=10)
        notification.refresh_from_db()
        self.assertEqual(result["dropped"], 1)
        self.assertEqual(notification.attempts, MAX_DELIVERY_ATTEMPTS)
        self.assertTrue(notification.is_sent)

        # ...and the parked notification is not picked up again.
        with mock.patch("apps.core.telegram.TelegramGateway.send_message") as send:
            notification_tasks.deliver_pending_notifications_task(limit=10)
        self.assertEqual(send.call_count, 0)

    def test_retry_eventually_succeeds(self) -> None:
        notification = self._pending()
        Notification.objects.filter(pk=notification.pk).update(attempts=2)
        with mock.patch("apps.core.telegram.TelegramGateway.send_message") as send:
            send.return_value = {"ok": True}
            result = notification_tasks.deliver_pending_notifications_task(limit=10)
        notification.refresh_from_db()
        self.assertEqual(result["sent"], 1)
        self.assertTrue(notification.is_sent)

    def test_single_notification_task(self) -> None:
        notification = self._pending()
        with mock.patch("apps.core.telegram.TelegramGateway.send_message") as send:
            result = notification_tasks.send_notification_task(notification.pk)
        self.assertTrue(result["sent"])
        notification.refresh_from_db()
        self.assertTrue(notification.is_sent)

    def test_cleanup_keeps_undelivered_unread_notifications(self) -> None:
        from apps.notifications.constants import RETENTION_DAYS

        old_seen = self._pending()
        old_delivered = self._pending()
        fresh = self._pending()
        stale = timezone.now() - timedelta(days=RETENTION_DAYS + 10)
        Notification.objects.filter(pk__in=[old_seen.pk, old_delivered.pk]).update(
            created_at=stale
        )
        Notification.objects.filter(pk=old_seen.pk).update(is_read=True)
        Notification.objects.filter(pk=old_delivered.pk).update(is_sent=True)

        kept = self._pending()
        Notification.objects.filter(pk=kept.pk).update(created_at=stale)

        result = notification_tasks.cleanup_old_notifications_task()
        self.assertEqual(result["deleted"], 2)
        self.assertTrue(Notification.objects.filter(pk=kept.pk).exists())
        self.assertTrue(Notification.objects.filter(pk=fresh.pk).exists())
