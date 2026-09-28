"""Django Admin configuration for the chat app."""

from __future__ import annotations

from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from apps.chat.models import ChatMessage, ChatThread
from apps.chat.selectors import get_unread_count_for_thread


class ChatMessageInline(admin.TabularInline):
    model = ChatMessage
    extra = 0
    fields = ("created_at", "sender", "type", "text", "is_read", "read_at")
    readonly_fields = ("created_at", "read_at")
    ordering = ("created_at",)
    autocomplete_fields = ("sender",)
    max_num = 0
    can_delete = False

    def has_add_permission(self, request, obj=None) -> bool:
        return False


@admin.register(ChatThread)
class ChatThreadAdmin(admin.ModelAdmin):
    list_display = ("id", "order_link", "driver", "passenger", "unread", "preview", "is_closed", "last_message_at")
    list_display_links = ("id", "order_link")
    list_filter = ("is_closed", "created_at")
    search_fields = ("order__id", "order__trip__driver__user__username", "order__passenger__username")
    ordering = ("-last_message_at",)
    date_hierarchy = "created_at"
    autocomplete_fields = ("order",)
    list_select_related = ("order", "order__trip", "order__passenger")
    readonly_fields = ("last_message_at", "last_message_preview", "created_at", "updated_at", "participants")
    list_per_page = 50
    fieldsets = (
        (_("Suhbat"), {"fields": ("order", "order_link", "participants", "is_closed")}),
        (_("Oxirgi xabar"), {"fields": ("last_message_preview", "last_message_at")}),
        (_("Vaqtlar"), {"fields": ("created_at", "updated_at")}),
    )
    inlines = (ChatMessageInline,)

    @admin.display(description=_("Buyurtma"))
    def order_link(self, obj: ChatThread) -> str:
        return f"#{obj.order_id}"

    @admin.display(description=_("Haydovchi"))
    def driver(self, obj: ChatThread) -> str:
        return obj.order.trip.driver.user.display_name

    @admin.display(description=_("Yo'lovchi"))
    def passenger(self, obj: ChatThread) -> str:
        return obj.order.passenger.display_name

    @admin.display(description=_("Ishtirokchilar"))
    def participants(self, obj: ChatThread) -> str:
        return f"{obj.order.trip.driver.user.display_name} ↔ {obj.order.passenger.display_name}"

    @admin.display(description=_("O'qilmagan"), ordering="is_closed")
    def unread(self, obj: ChatThread) -> int:
        total = 0
        for user in (obj.order.trip.driver.user, obj.order.passenger):
            total += get_unread_count_for_thread(obj, user)
        return total

    @admin.display(description=_("Oxirgi xabar"))
    def preview(self, obj: ChatThread) -> str:
        return obj.last_message_preview[:60]


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ("id", "thread_link", "sender", "type", "text_short", "is_read", "read_at", "created_at")
    list_display_links = ("id", "thread_link")
    list_filter = ("type", "is_read", "created_at")
    search_fields = ("text", "sender__username", "thread__order__id")
    ordering = ("-created_at",)
    date_hierarchy = "created_at"
    autocomplete_fields = ("thread", "sender")
    list_select_related = ("thread", "sender")
    readonly_fields = ("created_at", "updated_at", "read_at")
    list_per_page = 50

    @admin.display(description=_("Suhbat"))
    def thread_link(self, obj: ChatMessage) -> str:
        return f"Chat #{obj.thread_id} (buyurtma #{obj.thread.order_id})"

    @admin.display(description=_("Matn"))
    def text_short(self, obj: ChatMessage) -> str:
        return (obj.text[:60] + "...") if len(obj.text) > 60 else obj.text
