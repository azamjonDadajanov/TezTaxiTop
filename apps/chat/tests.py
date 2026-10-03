"""Tests for the order-scoped chat."""

from __future__ import annotations

from django.test import TestCase

from apps.chat import selectors as chat_selectors
from apps.chat import services as chat_services
from apps.chat.models import ChatMessage, ChatThread, MessageType
from apps.core.exceptions import (
    ChatClosed,
    EmptyMessage,
    UnauthorizedChatAccess,
)
from apps.core.testing import TaxiTestData
from apps.orders import services as order_services
from apps.users.models import User


class ChatTestBase(TestCase):
    def setUp(self) -> None:
        self.data = TaxiTestData()
        self.driver = self.data.create_driver()
        self.passenger = self.data.create_passenger()
        self.trip = self.data.create_trip(self.driver)
        self.order = self.data.create_order(self.trip, self.passenger)
        self.thread = chat_services.ensure_thread_for_order(self.order)
        # Start from a fully read thread so the unread assertions below count
        # only the messages each test creates itself.
        chat_services.mark_messages_read(self.thread, self.passenger)


class ThreadTests(ChatTestBase):
    def test_thread_is_created_with_the_order(self) -> None:
        self.assertIsNotNone(self.thread)
        self.assertEqual(self.thread.order, self.order)
        self.assertEqual(ChatThread.objects.count(), 1)

    def test_thread_creation_is_idempotent(self) -> None:
        again = chat_services.ensure_thread_for_order(self.order)
        self.assertEqual(again.pk, self.thread.pk)
        self.assertEqual(ChatThread.objects.count(), 1)

    def test_order_creation_opens_the_chat_automatically(self) -> None:
        trip2 = self.data.create_trip(self.driver)
        order = self.data.create_order(trip2, self.passenger)
        thread = ChatThread.objects.get(order=order)
        self.assertTrue(thread.is_open)

    def test_terminal_order_keeps_a_closed_thread(self) -> None:
        trip2 = self.data.create_trip(self.driver)
        order = self.data.create_order(trip2, self.passenger)
        order_services.accept_order(order)
        order_services.cancel_order_by_passenger(order)
        thread = chat_services.ensure_thread_for_order(order)
        self.assertIsNotNone(thread)
        self.assertTrue(thread.is_closed)

    def test_get_or_create_conversation_by_order_id(self) -> None:
        thread, created = chat_services.get_or_create_conversation(
            user=self.passenger,
            order_id=self.order.id,
        )
        self.assertFalse(created)
        self.assertEqual(thread.id, self.thread.id)

    def test_get_or_create_conversation_by_trip_id_deduplicates(self) -> None:
        # self.order already exists for self.trip and self.passenger
        thread, created = chat_services.get_or_create_conversation(
            user=self.passenger,
            trip_id=self.trip.id,
        )
        self.assertFalse(created)
        self.assertEqual(thread.id, self.thread.id)

    def test_open_chat_endpoint_by_order(self) -> None:
        from rest_framework.test import APIClient

        client = APIClient()
        client.force_authenticate(user=self.passenger)
        response = client.post("/api/v1/chat/chats/open/", {"order_id": self.order.id}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["order_id"], self.order.id)
        self.assertFalse(response.data["created"])


class MessageTests(ChatTestBase):
    def test_participants_can_exchange_messages(self) -> None:
        first = chat_services.send_message(
            thread=self.thread, sender=self.passenger, text=" Salom"
        )
        second = chat_services.send_message(
            thread=self.thread, sender=self.driver.user, text=" Salom!"
        )
        self.assertEqual(first.text, "Salom")
        self.assertEqual(second.text, "Salom!")

    def test_newest_message_updates_the_thread_preview(self) -> None:
        chat_services.send_message(thread=self.thread, sender=self.passenger, text="Qayerdan?")
        self.thread.refresh_from_db()
        self.assertEqual(self.thread.last_message_preview, "Qayerdan?")
        self.assertIsNotNone(self.thread.last_message_at)

    def test_preview_is_truncated(self) -> None:
        chat_services.send_message(thread=self.thread, sender=self.passenger, text="a" * 500)
        self.thread.refresh_from_db()
        self.assertEqual(len(self.thread.last_message_preview), chat_services.PREVIEW_LENGTH)

    def test_stranger_cannot_write_to_the_chat(self) -> None:
        stranger = self.data.create_passenger()
        with self.assertRaises(UnauthorizedChatAccess):
            chat_services.send_message(thread=self.thread, sender=stranger, text="salom")

    def test_empty_message_is_rejected(self) -> None:
        with self.assertRaises(EmptyMessage):
            chat_services.send_message(thread=self.thread, sender=self.passenger, text="   ")

    def test_long_message_is_truncated(self) -> None:
        message = chat_services.send_message(
            thread=self.thread, sender=self.passenger, text="a" * (chat_services.MAX_MESSAGE_LENGTH + 500)
        )
        self.assertEqual(len(message.text), chat_services.MAX_MESSAGE_LENGTH)

    def test_location_message_needs_no_text(self) -> None:
        message = chat_services.send_message(
            thread=self.thread,
            sender=self.passenger,
            text="",
            message_type=MessageType.LOCATION,
        )
        self.assertEqual(message.type, MessageType.LOCATION)

    def test_unread_count_is_per_reader(self) -> None:
        chat_services.send_message(thread=self.thread, sender=self.driver.user, text="1")
        chat_services.send_message(thread=self.thread, sender=self.driver.user, text="2")
        self.assertEqual(chat_selectors.get_unread_count_for_thread(self.thread, self.passenger), 2)
        self.assertEqual(chat_selectors.get_unread_count_for_thread(self.thread, self.driver.user), 0)
        self.assertEqual(chat_selectors.get_total_unread_count(self.passenger), 2)

    def test_polling_cursor_returns_only_new_messages(self) -> None:
        first = chat_services.send_message(thread=self.thread, sender=self.passenger, text="1")
        chat_services.send_message(thread=self.thread, sender=self.passenger, text="2")
        fresh = chat_selectors.get_messages_for_thread(self.thread, after_id=first.pk)
        self.assertEqual([m.text for m in fresh], ["2"])

    def test_mark_read_only_clears_the_other_side(self) -> None:
        chat_services.send_message(thread=self.thread, sender=self.passenger, text="salom")
        updated = chat_services.mark_messages_read(self.thread, self.driver.user)
        self.assertEqual(updated, 1)
        self.assertEqual(chat_selectors.get_unread_count_for_thread(self.thread, self.passenger), 0)
        self.assertEqual(chat_selectors.get_total_unread_count(self.passenger), 0)

    def test_mark_read_is_idempotent(self) -> None:
        chat_services.send_message(thread=self.thread, sender=self.passenger, text="salom")
        chat_services.mark_messages_read(self.thread, self.driver.user)
        self.assertEqual(chat_services.mark_messages_read(self.thread, self.driver.user), 0)

    def test_system_messages_are_written_by_the_service(self) -> None:
        before = ChatMessage.objects.filter(type=MessageType.SYSTEM).count()
        message = chat_services.create_system_message(self.thread, "Buyurtma tasdiqlandi")
        self.assertEqual(message.type, MessageType.SYSTEM)
        self.assertEqual(
            ChatMessage.objects.filter(type=MessageType.SYSTEM).count(), before + 1
        )


class ChatClosureTests(ChatTestBase):
    def test_closing_blocks_further_messages(self) -> None:
        chat_services.close_thread(self.thread)
        with self.assertRaises(ChatClosed):
            chat_services.send_message(thread=self.thread, sender=self.passenger, text="salom")

    def test_completed_order_closes_the_chat_automatically(self) -> None:
        order_services.accept_order(self.order)
        order_services.start_order(self.order)
        order_services.complete_order(self.order)
        self.thread.refresh_from_db()
        self.assertTrue(self.thread.is_closed)
        with self.assertRaises(ChatClosed):
            chat_services.send_message(thread=self.thread, sender=self.passenger, text="salom")

    def test_cancelled_order_closes_the_chat(self) -> None:
        order_services.accept_order(self.order)
        order_services.cancel_order_by_passenger(self.order)
        self.thread.refresh_from_db()
        self.assertTrue(self.thread.is_closed)

    def test_closing_twice_is_harmless(self) -> None:
        chat_services.close_thread(self.thread)
        chat_services.close_thread(self.thread)
        self.assertEqual(ChatThread.objects.filter(is_closed=True).count(), 1)

    def test_history_survives_closure(self) -> None:
        chat_services.send_message(thread=self.thread, sender=self.passenger, text="salom")
        before = ChatMessage.objects.filter(thread=self.thread).count()
        chat_services.close_thread(self.thread)
        self.assertEqual(ChatMessage.objects.filter(thread=self.thread).count(), before)


class ChatSafetyTests(ChatTestBase):
    def test_blocked_user_cannot_write(self) -> None:
        User.objects.filter(pk=self.passenger.pk).update(is_blocked=True)
        self.passenger.refresh_from_db()
        with self.assertRaises(UnauthorizedChatAccess):
            chat_services.send_message(thread=self.thread, sender=self.passenger, text="salom")

    def test_stranger_cannot_mark_as_read(self) -> None:
        stranger = self.data.create_passenger()
        with self.assertRaises(UnauthorizedChatAccess):
            chat_services.mark_messages_read(self.thread, stranger)

    def test_one_thread_per_order_forever(self) -> None:
        order_services.accept_order(self.order)
        order_services.start_order(self.order)
        order_services.complete_order(self.order)
        self.assertEqual(ChatThread.objects.filter(order=self.order).count(), 1)

    def test_thread_list_is_scoped_to_the_user(self) -> None:
        chat_services.send_message(thread=self.thread, sender=self.passenger, text="salom")
        stranger = self.data.create_passenger()
        self.assertEqual(chat_selectors.get_threads_for_user(stranger).count(), 0)
        self.assertEqual(chat_selectors.get_threads_for_user(self.passenger).count(), 1)
