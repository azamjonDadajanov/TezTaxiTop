"""Django Admin configuration for the payments app."""

from __future__ import annotations

from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from apps.payments import services as payment_services
from apps.payments.models import Payment, PaymentProvider, PaymentStatus
from apps.payments.providers import PROVIDER_REGISTRY
from apps.payments.selectors import PAYMENT_ORDERING_FIELDS, PAYMENT_SEARCH_FIELDS

#: Providers that need no credentials. Cash is settled by an admin action and
#: `other` is a bookkeeping bucket, so reporting them as unconfigured would be
#: noise in the gateway panel.
_CREDENTIAL_FREE_PROVIDERS = frozenset({PaymentProvider.CASH, PaymentProvider.OTHER})


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    """Financial ledger.

    New rows may be typed in (offline/cash sales, corrections) but they are
    always stored as ``PENDING`` and must be settled through the actions, which
    run the real service functions. Editing an existing row stays forbidden.
    """

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
    # Fields an operator may supply when creating a payment by hand. Everything
    # else is derived by the system.
    add_fieldsets = (
        (
            _("To'lov"),
            {
                "fields": ("user", "payment_type", "amount", "provider", "external_transaction_id"),
                "description": _(
                    "Qo'lda kiritilgan to'lov avtomatik ravishda 'Kutilmoqda' holatida saqlanadi. "
                    "Uni tasdiqlash uchun ro'yxatdagi to'lovni tanlab 'Tasdiqlash' amalini ishlating."
                ),
            },
        ),
        (_("Qo'shimcha"), {"fields": ("metadata",), "classes": ("collapse",)}),
    )
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

    def get_readonly_fields(self, request, obj=None):
        """On the add form the operator's own inputs must be editable."""
        if obj is None:
            return ("status", "paid_at", "refunded_at", "created_at", "updated_at")
        return self.readonly_fields

    def get_fieldsets(self, request, obj=None):
        if obj is None:
            return self.add_fieldsets
        return self.fieldsets

    def has_add_permission(self, request) -> bool:
        """Offline sales and corrections still need to be recordable.

        Superuser only: the permission is granted by Django's own model
        permission system, but an accidental ``status=success`` would bypass
        payment verification, so the entry point is deliberately narrow.
        """
        return bool(request.user.is_active and request.user.is_superuser)

    def has_change_permission(self, request, obj=None) -> bool:
        """The ledger is immutable; only the explicit actions may change it."""
        return False

    def save_model(self, request, obj, form, change) -> None:
        """Force a hand-entered payment to ``PENDING``.

        ``status`` is not on the add form, but a crafted POST could still set
        it. Storing anything but ``PENDING`` here would skip
        :func:`process_successful_payment` and with it the subscription
        activation and the user notification that a real payment triggers.
        The row is then settled through the actions, which do run those.
        """
        obj.status = PaymentStatus.PENDING
        obj.paid_at = None
        obj.refunded_at = None
        obj.failure_reason = ""
        super().save_model(request, obj, form, change)

    @admin.action(description=_("Tanlangan to'lovlarni muvaffaqiyatli deb tasdiqlash (naqd)"))
    def confirm_cash_payments(self, request, queryset) -> None:
        """Settle a payment the admin has confirmed out of band.

        ``verified=True`` is the operator asserting the money arrived. The
        scope stays limited to cash and to ``other`` - the two providers with
        no server-side callback - so a payment that a real gateway still owes
        us cannot be marked paid from the admin.
        """
        confirmed = 0
        for payment in queryset.filter(status=PaymentStatus.PENDING).filter(
            provider__in=(PaymentProvider.CASH, PaymentProvider.OTHER)
        ):
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
                # Cash and the generic `other` bucket take no credentials, so the
                # base check would always call them "unconfigured" and train the
                # operator to ignore the panel.
                "configured": True
                if code in _CREDENTIAL_FREE_PROVIDERS
                else provider_class().is_configured(),
            }
            for code, provider_class in PROVIDER_REGISTRY.items()
        ]
        return super().changelist_view(request, extra_context=extra_context)
