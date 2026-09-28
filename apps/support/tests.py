"""Tests for the support desk."""

from __future__ import annotations

from django.test import TestCase

from apps.core.exceptions import BusinessValidationError, SupportTicketClosed
from apps.core.testing import TaxiTestData
from apps.support import services as support_services
from apps.support.models import SupportMessage, SupportTicket, TicketStatus


class SupportTestBase(TestCase):
    def setUp(self) -> None:
        self.data = TaxiTestData()
        self.passenger = self.data.create_passenger()
        self.driver = self.data.create_driver()
        self.staff = self.passenger.__class__.objects.create_user(
            username="support",
            telegram_id=900001,
            first_name="Support",
            phone_number="+998909000001",
            is_staff=True,
        )


class TicketCreationTests(SupportTestBase):
    def test_user_creates_a_ticket(self) -> None:
        ticket = support_services.create_ticket(
            user=self.passenger, subject="Mashina kechikdi", category="complaint"
        )
        self.assertEqual(ticket.status, TicketStatus.OPEN)
        self.assertEqual(ticket.user, self.passenger)
        self.assertEqual(ticket.category, "complaint")

    def test_ticket_can_reference_an_order(self) -> None:
        trip = self.data.create_trip(self.driver)
        order = self.data.create_order(trip, self.passenger)
        ticket = support_services.create_ticket(
            user=self.passenger, subject="Buyurtma muammosi", order=order
        )
        self.assertEqual(ticket.order, order)

    def test_subject_is_required(self) -> None:
        with self.assertRaises(BusinessValidationError):
            support_services.create_ticket(user=self.passenger, subject="   ")

    def test_ticket_can_be_anonymous_in_the_api_layer(self) -> None:
        ticket = support_services.create_ticket(
            user=self.passenger, subject="Maxfiylik", is_anonymous=True
        )
        self.assertTrue(ticket.is_anonymous)


class TicketMessageTests(SupportTestBase):
    def setUp(self) -> None:
        super().setUp()
        self.ticket = support_services.create_ticket(
            user=self.passenger, subject="Yordam kerak"
        )

    def test_user_can_reply(self) -> None:
        message = support_services.add_message(
            ticket=self.ticket, sender=self.passenger, body="Yana bir savol"
        )
        self.assertFalse(message.is_from_support)
        self.assertEqual(SupportMessage.objects.filter(ticket=self.ticket).count(), 1)

    def test_staff_can_answer(self) -> None:
        message = support_services.add_message(
            ticket=self.ticket, sender=self.staff, body="Yordam beramiz", is_from_support=True
        )
        self.assertTrue(message.is_from_support)

    def test_empty_body_is_rejected(self) -> None:
        with self.assertRaises(BusinessValidationError):
            support_services.add_message(ticket=self.ticket, sender=self.passenger, body=" ")

    def test_stranger_cannot_write_to_a_ticket(self) -> None:
        stranger = self.data.create_passenger()
        with self.assertRaises(BusinessValidationError):
            support_services.add_message(ticket=self.ticket, sender=stranger, body="salom")

    def test_closed_ticket_rejects_new_messages(self) -> None:
        support_services.close_ticket(self.ticket)
        with self.assertRaises(SupportTicketClosed):
            support_services.add_message(ticket=self.ticket, sender=self.passenger, body="salom")


class TicketStateTests(SupportTestBase):
    def setUp(self) -> None:
        super().setUp()
        self.ticket = support_services.create_ticket(
            user=self.passenger, subject="Holatni o'zgartirish"
        )

    def test_only_staff_changes_the_status(self) -> None:
        with self.assertRaises(BusinessValidationError):
            support_services.set_ticket_status(
                self.ticket, TicketStatus.IN_PROGRESS, actor=self.passenger
            )

    def test_staff_moves_the_ticket_forward(self) -> None:
        ticket = support_services.set_ticket_status(
            self.ticket, TicketStatus.IN_PROGRESS, actor=self.staff
        )
        self.assertEqual(ticket.status, TicketStatus.IN_PROGRESS)

    def test_illegal_jump_is_rejected(self) -> None:
        support_services.set_ticket_status(
            self.ticket, TicketStatus.IN_PROGRESS, actor=self.staff
        )
        # in_progress -> open is allowed, open -> in_progress is allowed, but
        # a closed ticket can only be reopened by the owner in the API layer.
        with self.assertRaises(BusinessValidationError):
            support_services.set_ticket_status(
                self.ticket, "boshqa_holat", actor=self.staff
            )

    def test_closing_stamps_the_timestamp(self) -> None:
        ticket = support_services.close_ticket(self.ticket)
        self.assertTrue(ticket.is_closed)
        self.assertIsNotNone(ticket.closed_at)

    def test_closing_twice_is_idempotent(self) -> None:
        support_services.close_ticket(self.ticket)
        ticket = support_services.close_ticket(self.ticket)
        self.assertEqual(ticket.status, TicketStatus.CLOSED)

    def test_open_tickets_are_tracked(self) -> None:
        from apps.support import selectors as support_selectors

        self.assertEqual(support_selectors.get_tickets_for_user(self.passenger).count(), 1)
        self.assertEqual(support_selectors.get_open_tickets_for_user(self.passenger).count(), 1)
        support_services.add_message(
            ticket=self.ticket, sender=self.staff, body="Javob", is_from_support=True
        )
        self.assertEqual(support_selectors.get_unread_ticket_count(self.passenger), 1)
        support_services.close_ticket(self.ticket)
        self.assertEqual(support_selectors.get_open_tickets_for_user(self.passenger).count(), 0)
