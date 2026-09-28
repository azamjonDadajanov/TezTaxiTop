"""Django Admin configuration for the subscriptions app."""

from __future__ import annotations

from django.contrib import admin, messages
from django.utils.translation import gettext_lazy as _

from apps.subscriptions import services as subscription_services
from apps.subscriptions.models import DriverSubscription, DriverSubscriptionStatus, SubscriptionPlan


@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "duration_days",
        # "duration_months",
        "price",
        "is_active",
        "sort_order",
        # "subscriptions_count",
        "created_at",
    )
    list_display_links = ("id", "name")
    list_filter = ("is_active", "duration_days")
    search_fields = ("id", "name", "description")
    ordering = ("sort_order", "duration_days")
    readonly_fields = ("created_at", "updated_at")
    list_per_page = 50
    fieldsets = (
        (
            _("Reja"),
            {
                "fields": (
                    "name",
                    "duration_days",
                    # "duration_months",
                    "price",
                    "description",
                    "sort_order",
                )
            },
        ),
        (_("Holat"), {"fields": ("is_active",)}),
        (_("Vaqtlar"), {"fields": ("created_at", "updated_at")}),
    )

    # @admin.display(description=_("Oylar"))
    # def duration_months(self, obj: SubscriptionPlan) -> int:
    #     return round(obj.duration_days / 30) if obj.duration_days else 0

    @admin.display(description=_("Obunalar soni"))
    def subscriptions_count(self, obj: SubscriptionPlan) -> int:
        return obj.subscriptions.count()

    def has_delete_permission(self, request, obj=None) -> bool:
        """Plans referenced by a subscription must not be deletable."""
        if obj is not None and obj.subscriptions.exists():
            return False
        return super().has_delete_permission(request, obj)


class DriverSubscriptionInline(admin.TabularInline):
    model = DriverSubscription
    extra = 0
    can_delete = False
    fields = ("plan", "starts_at", "expires_at", "price_at_purchase", "status", "payment")
    readonly_fields = fields
    show_change_link = True


@admin.register(DriverSubscription)
class DriverSubscriptionAdmin(admin.ModelAdmin):
    """Driver, plan, dates, status and the related payment - all in one row."""

    list_display = (
        "id",
        "driver_name",
        "driver_phone",
        "plan_name",
        "starts_at",
        "expires_at",
        "days_remaining",
        "status",
        "price_at_purchase",
        "payment_link",
        "auto_renew",
        "created_at",
    )
    list_display_links = ("id", "driver_name")
    list_filter = ("status", "plan", "auto_renew", "starts_at", "expires_at", "created_at")
    search_fields = (
        "id",
        "driver__user__username",
        "driver__user__first_name",
        "driver__user__last_name",
        "driver__user__phone_number",
        "driver__user__telegram_id",
        "plan__name",
    )
    ordering = ("-created_at",)
    date_hierarchy = "expires_at"
    autocomplete_fields = ("driver", "plan", "payment")
    list_select_related = ("driver__user", "plan", "payment")
    readonly_fields = (
        "price_at_purchase",
        "activated_at",
        "cancelled_at",
        "created_at",
        "updated_at",
        "days_remaining",
        "status_help",
    )
    list_per_page = 50
    fieldsets = (
        (
            _("Obuna"),
            {
                "fields": (
                    "driver",
                    "plan",
                    "starts_at",
                    "expires_at",
                    "days_remaining",
                    "price_at_purchase",
                )
            },
        ),
        (_("Holat"), {"fields": ("status", "status_help", "auto_renew", "activated_at", "cancelled_at")}),
        (_("To'lov"), {"fields": ("payment",)}),
        (_("Vaqtlar"), {"fields": ("created_at", "updated_at")}),
    )
    actions = ("activate_selected", "expire_selected", "cancel_selected", "extend_selected")

    def has_delete_permission(self, request, obj=None) -> bool:
        """Subscription history is never deleted."""
        return False

    @admin.display(description=_("Haydovchi"), ordering=("driver__user__first_name",))
    def driver_name(self, obj: DriverSubscription) -> str:
        return obj.driver.user.display_name

    @admin.display(description=_("Telefon"), empty_value="-")
    def driver_phone(self, obj: DriverSubscription) -> str:
        return obj.driver.user.phone_number or "-"

    @admin.display(description=_("Reja"), ordering=("plan__duration_days",))
    def plan_name(self, obj: DriverSubscription) -> str:
        return obj.plan.name

    @admin.display(description=_("Qolgan kun"))
    def days_remaining(self, obj: DriverSubscription) -> int:
        return obj.days_remaining()

    @admin.display(description=_("To'lov"))
    def payment_link(self, obj: DriverSubscription) -> str:
        if obj.payment_id is None:
            return "-"
        return f"#{obj.payment_id} ({obj.payment.get_status_display()})"

    @admin.display(description=_("Holat bo'yicha ko'rsatma"))
    def status_help(self, obj: DriverSubscription) -> str:
        return _(
            "Holat `pending` to'lovni kutmoqda, `active` faol, `expired` muddati tugagan, "
            "`cancelled` bekor qilingan. Eskirgan `active` holatlar Celery vazifasi orqali "
            "avtomatik `expired` ga o'tadi."
        )

    @admin.action(description=_("Tanlangan obunalarni faollashtirish"))
    def activate_selected(self, request, queryset) -> None:
        for subscription in queryset.filter(status=DriverSubscriptionStatus.PENDING):
            subscription_services.activate_subscription(subscription)
        self.message_user(request, _("Tanlangan obunalar faollashtirildi."), messages.SUCCESS)

    @admin.action(description=_("Tanlangan obunalarni muddati tugagan deb belgilash"))
    def expire_selected(self, request, queryset) -> None:
        for subscription in queryset:
            subscription_services.expire_subscription(subscription)
        self.message_user(request, _("Tanlangan obunalar muddati tugagan deb belgilandi."), messages.SUCCESS)

    @admin.action(description=_("Tanlangan obunalarni bekor qilish"))
    def cancel_selected(self, request, queryset) -> None:
        for subscription in queryset:
            subscription_services.cancel_subscription(subscription)
        self.message_user(request, _("Tanlangan obunalar bekor qilildi."), messages.SUCCESS)

    @admin.action(description=_("Tanlangan obunalarni 1 oyga uzaytirish"))
    def extend_selected(self, request, queryset) -> None:
        for subscription in queryset:
            subscription_services.extend_subscription(subscription, days=30)
        self.message_user(request, _("Tanlangan obunalar 1 oyga uzaytirildi."), messages.SUCCESS)
