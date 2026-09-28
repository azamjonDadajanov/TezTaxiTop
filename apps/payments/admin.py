"""Django Admin configuration for the payments app."""

from __future__ import annotations

from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from apps.payments import services as payment_services
from apps.payments.models import Payment, PaymentStatus
from apps.payments.providers import PROVIDER_REGISTRY
from apps.payments.selectors import PAYMENT_ORDERING_FIELDS, PAYMENT_SEARCH_FIELDS


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    """Financial ledger: strictly read-only except for the action buttons."""

    list_display = (
        "id",
        "user",
        "amount",
        "provider",
        "external_transaction_id",
        "payment_type",
        "status",
        "created_at",
        "paid_at",
    )
    list_display_links = ("id", "user")
    list_filter = ("status", "provider", "payment_type", "created_at", "paid_at")
    search_fields = PAYMENT_SEARCH_FIELDS
    ordering = ("-created_at",)
    date_hierarchy = "created_at"
    autocomplete_fields = ("user",)
    list_select_related = ("user",)
    list_per_page = 50
    readonly_fields = (
        "user",
        "payment_type",
        "amount",
        "provider",
        "external_transaction_id",
        "status",
        "paid_at",
        "refunded_at",
        "metadata",
        "failure_reason",
        "created_at",
        "updated_at",
    )
    fieldsets = (
        (_("To'lov"), {"fields": ("user", "payment_type", "amount", "provider", "external_transaction_id")}),
        (_("Holat"), {"fields": ("status", "paid_at", "refunded_at", "failure_reason")}),
        (_("Provayder javobi"), {"fields": ("metadata",)}),
        (_("Vaqtlar"), {"fields": ("created_at", "updated_at")}),
    )
    actions = ("confirm_cash_payments", "mark_failed", "refund_payments")

    def has_add_permission(self, request) -> bool:
        """Payments are created by the system, never typed in by hand."""
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        """The ledger is immutable; only the explicit actions may change it."""
        return False

    @admin.action(description=_("Tanlangan to'lovlarni muvaffaqiyatli deb tasdiqlash (naqd)"))
    def confirm_cash_payments(self, request, queryset) -> None:
        confirmed = 0
        for payment in queryset.filter(status=PaymentStatus.PENDING, provider="cash"):
            payment_services.process_successful_payment(payment, verified=True)
            confirmed += 1
        self.message_user(
            request, _("%(count)d ta to'lov tasdiqlandi.") % {"count": confirmed}
        )

    @admin.action(description=_("Tanlangan to'lovlarni muvaffaqiyatsiz deb belgilash"))
    def mark_failed(self, request, queryset) -> None:
        failed = 0
        for payment in queryset.filter(status=PaymentStatus.PENDING):
            payment_services.process_failed_payment(payment, reason="Admin tomonidan bekor qilindi")
            failed += 1
        self.message_user(
            request, _("%(count)d ta to'lov muvaffaqiyatsiz deb belgilandi.") % {"count": failed}
        )

    @admin.action(description=_("Tanlangan to'lovlarni qaytarish"))
    def refund_payments(self, request, queryset) -> None:
        refunded = 0
        for payment in queryset.filter(status=PaymentStatus.SUCCESS):
            try:
                payment_services.refund_payment(payment, reason="Admin tomonidan qaytarildi")
                refunded += 1
            except Exception as exc:  # noqa: BLE001 - surfaced to the admin
                self.message_user(request, _("#%s: %s") % (payment.pk, exc))
        self.message_user(
            request, _("%(count)d ta to'lov qaytarildi.") % {"count": refunded}
        )

    def changelist_view(self, request, extra_context=None):
        """Show which gateways are configured, so misconfiguration is visible."""
        extra_context = extra_context or {}
        extra_context["provider_status"] = [
            {
                "code": code,
                "configured": provider_class().is_configured(),
            }
            for code, provider_class in PROVIDER_REGISTRY.items()
        ]
        return super().changelist_view(request, extra_context=extra_context)
