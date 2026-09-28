"""Django Admin configuration for the support app."""

from __future__ import annotations

from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from apps.support import services as support_services
from apps.support.models import SupportMessage, SupportTicket


class SupportMessageInline(admin.TabularInline):
    model = SupportMessage
    extra = 0
    fields = ("created_at", "sender", "is_from_support", "body")
    readonly_fields = ("created_at",)
    ordering = ("created_at",)
    autocomplete_fields = ("sender",)


@admin.register(SupportTicket)
class SupportTicketAdmin(admin.ModelAdmin):
    list_display = ("id", "subject", "user", "category", "priority", "status", "created_at", "last_message_at")
    list_display_links = ("id", "subject")
    list_filter = ("status", "category", "priority", "is_anonymous", "created_at")
    search_fields = ("subject", "user__username", "user__first_name", "user__last_name", "id")
    ordering = ("-last_message_at",)
    date_hierarchy = "created_at"
    autocomplete_fields = ("user", "order")
    list_select_related = ("user", "order")
    readonly_fields = ("created_at", "updated_at", "last_message_at", "closed_at", "status_detail")
    list_per_page = 50
    actions = ("close_selected", "reopen_selected", "set_high_priority")
    inlines = (SupportMessageInline,)
    fieldsets = (
        (_("Murojaat"), {"fields": ("user", "order", "subject", "category", "priority", "is_anonymous", "status", "status_detail")}),
        (_("Vaqtlar"), {"fields": ("last_message_at", "closed_at", "created_at", "updated_at")}),
    )

    @admin.display(description=_("Holat"), ordering="status")
    def status_detail(self, obj: SupportTicket) -> str:
        return obj.get_status_display()

    @admin.action(description=_("Yopilgan deb belgilash"))
    def close_selected(self, request, queryset) -> None:
        for ticket in queryset:
            support_services.close_ticket(ticket)

    @admin.action(description=_("Ochiq deb belgilash"))
    def reopen_selected(self, request, queryset) -> None:
        for ticket in queryset:
            support_services.set_ticket_status(ticket, "open", actor=request.user)

    @admin.action(description=_("Yuqori ustuvorlik"))
    def set_high_priority(self, request, queryset) -> None:
        queryset.update(priority="high")


@admin.register(SupportMessage)
class SupportMessageAdmin(admin.ModelAdmin):
    list_display = ("id", "ticket", "sender", "is_from_support", "body_short", "created_at")
    list_display_links = ("id", "ticket")
    list_filter = ("is_from_support", "created_at")
    search_fields = ("body", "ticket__subject", "sender__username")
    ordering = ("-created_at",)
    date_hierarchy = "created_at"
    autocomplete_fields = ("ticket", "sender")
    list_select_related = ("ticket", "sender")
    readonly_fields = ("created_at", "updated_at")
    list_per_page = 50

    @admin.display(description=_("Matn"))
    def body_short(self, obj: SupportMessage) -> str:
        return (obj.body[:60] + "...") if len(obj.body) > 60 else obj.body
