"""Read/query layer for the chat app."""

from __future__ import annotations

from django.db.models import Count, Max, Q, QuerySet

from apps.chat.models import ChatMessage, ChatThread


def get_thread_queryset() -> QuerySet[ChatThread]:
    return ChatThread.objects.select_related("order", "order__trip", "order__trip__driver")


def get_thread_by_order(order) -> ChatThread | None:
    return get_thread_queryset().filter(order=order).first()


def get_thread_by_id(thread_id: int) -> ChatThread | None:
    return get_thread_queryset().filter(pk=thread_id).first()


def get_threads_for_user(user) -> QuerySet[ChatThread]:
    """Threads where the user is the driver or a passenger with an order."""
    return get_thread_queryset().filter(
        Q(order__trip__driver__user=user) | Q(order__passenger=user)
    ).distinct()


def get_message_queryset() -> QuerySet[ChatMessage]:
    return ChatMessage.objects.select_related("sender", "thread")


def get_messages_for_thread(thread, after_id: int | None = None, limit: int = 100) -> QuerySet[ChatMessage]:
    """Polling query: everything after ``after_id`` in ascending order."""
    queryset = get_message_queryset().filter(thread=thread)
    if after_id:
        queryset = queryset.filter(id__gt=after_id)
    return queryset.order_by("id")[:limit]


def get_last_message(thread) -> ChatMessage | None:
    return get_message_queryset().filter(thread=thread).order_by("-id").first()


def get_last_message_id(thread) -> int | None:
    return (
        get_message_queryset().filter(thread=thread).order_by("-id").values_list("id", flat=True).first()
    )


def get_unread_count_for_thread(thread, reader) -> int:
    """Messages written by somebody else that ``reader`` has not opened yet."""
    return get_message_queryset().filter(thread=thread, is_read=False).exclude(sender=reader).count()


def get_unread_counts_for_user(user) -> dict[int, int]:
    """``{order_id: unread_count}`` for the chat list badge."""
    rows = (
        get_message_queryset()
        .filter(Q(thread__order__trip__driver__user=user) | Q(thread__order__passenger=user))
        .filter(is_read=False)
        .exclude(sender=user)
        .values("thread__order_id")
        .annotate(total=Count("id"))
    )
    return {row["thread__order_id"]: row["total"] for row in rows}


def get_total_unread_count(user) -> int:
    return sum(get_unread_counts_for_user(user).values())


def get_threads_with_unread(user) -> QuerySet[ChatThread]:
    unread = get_unread_counts_for_user(user)
    return get_threads_for_user(user).filter(order_id__in=list(unread.keys()))


def get_threads_with_stats(user) -> list[dict]:
    """Chat list payload: thread, counterpart, last message and unread count."""
    threads = list(
        get_thread_queryset()
        .filter(Q(order__trip__driver__user=user) | Q(order__passenger=user))
        .distinct()
    )
    unread = get_unread_counts_for_user(user)
    last_ids = ChatMessage.objects.filter(thread__in=threads).values("thread_id").annotate(
        last_id=Max("id")
    )
    last_map = {row["thread_id"]: row["last_id"] for row in last_ids}

    payload = []
    for thread in threads:
        last = None
        if last_map.get(thread.thread_id if hasattr(thread, "thread_id") else thread.pk):
            last = ChatMessage.objects.filter(id=last_map[thread.pk]).first()
        payload.append(
            {
                "thread": thread,
                "last_message": last,
                "unread": unread.get(thread.order_id, 0),
            }
        )
    payload.sort(key=lambda item: (item["last_message"].id if item["last_message"] else 0), reverse=True)
    return payload
