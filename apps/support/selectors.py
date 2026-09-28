"""Read/query layer for the support app."""

from __future__ import annotations

from django.db.models import Count, Q, QuerySet

from apps.support.models import SupportMessage, SupportTicket, TicketStatus


def get_ticket_queryset() -> QuerySet[SupportTicket]:
    return SupportTicket.objects.select_related("user", "order")


def get_ticket_by_id(ticket_id: int) -> SupportTicket | None:
    return get_ticket_queryset().filter(pk=ticket_id).first()


def get_tickets_for_user(user) -> QuerySet[SupportTicket]:
    return get_ticket_queryset().filter(user=user)


def get_open_tickets_for_user(user) -> QuerySet[SupportTicket]:
    return get_tickets_for_user(user).filter(status__in=[TicketStatus.OPEN, TicketStatus.IN_PROGRESS])


def get_all_tickets() -> QuerySet[SupportTicket]:
    return get_ticket_queryset()


def get_tickets_by_status(status: str) -> QuerySet[SupportTicket]:
    return get_ticket_queryset().filter(status=status)


def search_tickets(queryset: QuerySet[SupportTicket], search_term: str | None) -> QuerySet[SupportTicket]:
    if not search_term:
        return queryset
    term = search_term.strip()
    return queryset.filter(
        Q(subject__icontains=term)
        | Q(category__icontains=term)
        | Q(user__username__icontains=term)
        | Q(user__first_name__icontains=term)
        | Q(user__last_name__icontains=term)
    )


def get_message_queryset() -> QuerySet[SupportMessage]:
    return SupportMessage.objects.select_related("sender", "ticket")


def get_messages_for_ticket(ticket, after_id: int | None = None, limit: int = 100) -> QuerySet[SupportMessage]:
    queryset = get_message_queryset().filter(ticket=ticket)
    if after_id:
        queryset = queryset.filter(id__gt=after_id)
    return queryset.order_by("id")[:limit]


def get_unread_ticket_count(user) -> int:
    """Tickets that have a newer message than the one the user last saw."""
    rows = (
        get_ticket_queryset()
        .filter(user=user)
        .annotate(total=Count("messages", filter=Q(messages__is_from_support=True)))
        .filter(total__gt=0)
    )
    return rows.count()
