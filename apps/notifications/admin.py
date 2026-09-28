"""Django Admin configuration for the notifications app."""

from __future__ import annotations

from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from apps.notifications.models import Notification
from apps.notifications.selectors import get_unread_count


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "type",
        "title",
        "short_message",
        "is_read",
        "is_sent",
        "sent_at",
        "created_at",
    )
    list_display_links = ("id", "user")
    list_filter = ("type", "is_read", "is_sent", "created_at")
    search_fields = ("title", "message", "user__username", "user__first_name", "user__last_name")
    ordering = ("-created_at",)
    date_hierarchy = "created_at"
    autocomplete_fields = ("user",)
    list_select_related = ("user",)
    readonly_fields = ("created_at", "updated_at", "sent_at")
    list_per_page = 50
    actions = ("mark_as_read", "mark_as_sent", "resend_unread")
    fieldsets = (
        (_("Bildirishnoma"), {"fields": ("user", "type", "title", "short_message", "is_read", "is_sent", "sent_at")}),
        (_("Vaqtlar"), {"fields": ("created_at", "updated_at")}),
    )

    @admin.display(description=_("Matn"))
    def short_message(self, obj: Notification) -> str:
        return (obj.message[:70] + "...") if len(obj.message) > 70 else obj.message

    @admin.display(description=_("O'qilmagan soni"), ordering="is_read")
    def unread_count(self, obj: Notification) -> int:
        return get_unread_count(obj.user)

    @admin.action(description=_("O'qilgan deb belgilash"))
    def mark_as_read(self, request, queryset) -> None:
        queryset.update(is_read=True)

    @admin.action(description=_("Yuborilgan deb belgilash"))
    def mark_as_sent(self, request, queryset) -> None:
        from django.utils import timezone

        queryset.filter(is_sent=False).update(is_sent=True, sent_at=timezone.now())

    @admin.action(description=_("Yuborilmaganlarni qayta yuborishga qo'shish"))
    def resend_unread(self, request, queryset) -> None:
        queryset.update(is_sent=False, sent_at=None)
