"""Write/business layer for the support app."""

from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from apps.core.exceptions import (
    BusinessValidationError,
    ResourceNotFound,
    SupportTicketClosed,
)
from apps.support.models import SupportMessage, SupportTicket, TicketStatus
from apps.support.selectors import get_ticket_by_id
from apps.users.models import User

logger = logging.getLogger(__name__)

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    TicketStatus.OPEN: {TicketStatus.IN_PROGRESS, TicketStatus.CLOSED},
    TicketStatus.IN_PROGRESS: {TicketStatus.CLOSED, TicketStatus.OPEN},
    TicketStatus.CLOSED: {TicketStatus.OPEN},  # a user may reopen within the same thread
}


@transaction.atomic
def create_ticket(
    *,
    user: User,
    subject: str,
    category: str = "other",
    order=None,
    priority: str = "normal",
    is_anonymous: bool = False,
) -> SupportTicket:
    if not subject.strip():
        raise BusinessValidationError("Mavzu bo'sh bo'lishi mumkin emas.")
    ticket = SupportTicket.objects.create(
        user=user,
        order=order,
        subject=subject.strip()[:200],
        category=category,
        priority=priority,
        is_anonymous=is_anonymous,
    )
    logger.info("Murojaat yaratildi: #%s (%s)", ticket.pk, subject[:40])
    return ticket


@transaction.atomic
def add_message(
    *,
    ticket: SupportTicket,
    sender: User,
    body: str,
    is_from_support: bool = False,
    attachment_url: str = "",
) -> SupportMessage:
    """Add a message to a ticket (user reply or support answer)."""
    if not body.strip():
        raise BusinessValidationError("Xabar matni bo'sh bo'lishi mumkin emas.")

    if is_from_support:
        if not sender.is_staff:
            raise BusinessValidationError("Faqat administratorlar support javobini yozishi mumkin.")
    else:
        _assert_owner(ticket, sender)
        if ticket.is_closed:
            raise SupportTicketClosed("Murojaat yopilgan. Iltimos, yangi murojaat yarating.")

    message = SupportMessage.objects.create(
        ticket=ticket,
        sender=sender,
        body=body.strip()[:4000],
        is_from_support=is_from_support,
        attachment_url=attachment_url,
    )
    ticket.last_message_at = message.created_at
    ticket.save(update_fields=["last_message_at", "updated_at"])
    return message


@transaction.atomic
def set_ticket_status(ticket: SupportTicket, new_status: str, *, actor: User) -> SupportTicket:
    """Change the status following the allowed transition map."""
    if not actor.is_staff:
        raise BusinessValidationError("Faqat administratorlar holatni o'zgartira oladi.")
    if new_status == ticket.status:
        return ticket
    allowed = ALLOWED_TRANSITIONS.get(ticket.status, set())
    if new_status not in allowed:
        raise BusinessValidationError(
            f"'{ticket.get_status_display()}' dan '{dict(SupportTicket._meta.get_field('status').choices).get(new_status, new_status)}' "
            "holatiga o'tish mumkin emas."
        )
    ticket.status = new_status
    ticket.closed_at = timezone.now() if new_status == TicketStatus.CLOSED else None
    ticket.save(update_fields=["status", "closed_at", "updated_at"])
    return ticket


@transaction.atomic
def close_ticket(ticket: SupportTicket) -> SupportTicket:
    if ticket.is_closed:
        return ticket
    ticket.status = TicketStatus.CLOSED
    ticket.closed_at = timezone.now()
    ticket.save(update_fields=["status", "closed_at", "updated_at"])
    return ticket


def _assert_owner(ticket: SupportTicket, user: User) -> None:
    if ticket.user_id != user.pk and not user.is_staff:
        raise BusinessValidationError("Bu murojaatga faqat muallif kirishi mumkin.")


def get_required_ticket(ticket_id: int) -> SupportTicket:
    ticket = get_ticket_by_id(ticket_id)
    if ticket is None:
        raise ResourceNotFound("Murojaat topilmadi.")
    return ticket


__all__ = ["add_message", "close_ticket", "create_ticket", "get_required_ticket", "set_ticket_status"]
