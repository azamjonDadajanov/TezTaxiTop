"""Django Admin configuration for the orders app."""

from __future__ import annotations

from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from apps.orders import services as order_services
from apps.orders.models import Order, OrderPassenger, OrderStatus
from apps.orders.selectors import ORDER_ORDERING_FIELDS, ORDER_SEARCH_FIELDS


class OrderPassengerInline(admin.TabularInline):
    model = OrderPassenger
    extra = 0
    fields = ("first_name", "last_name", "phone_number")
    verbose_name = _("Buyurtma yo'lovchisi")
    verbose_name_plural = _("Buyurtma yo'lovchilari")


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    """Orders are read mostly; every state change goes through the service."""

    list_display = (
        "id",
        "trip_route",
        "passenger_name",
        "passenger_phone",
        "driver_name",
        "plate_number",
        "seats_booked",
        "price_per_seat",
        "total_amount",
        "status",
        "created_at",
        "accepted_at",
        "completed_at",
    )
    list_display_links = ("id", "trip_route")
    list_filter = (
        "status",
        "trip__status",
        "trip__from_location__district__region",
        "created_at",
        "accepted_at",
        "completed_at",
    )
    search_fields = ORDER_SEARCH_FIELDS
    ordering = ("-created_at",)
    date_hierarchy = "created_at"
    autocomplete_fields = ("trip", "passenger")
    list_select_related = ("passenger", "trip__driver__user", "trip__vehicle", "trip__from_location", "trip__to_location")
    readonly_fields = (
        "price_per_seat",
        "total_amount",
        "accepted_at",
        "cancelled_at",
        "completed_at",
        "created_at",
        "updated_at",
        "trip_route",
        "driver_name",
    )
    list_per_page = 50
    inlines = (OrderPassengerInline,)
    fieldsets = (
        (
            _("Buyurtma"),
            {
                "fields": (
                    "trip",
                    "trip_route",
                    "passenger",
                    "seats_booked",
                    "price_per_seat",
                    "total_amount",
                    "passenger_note",
                )
            },
        ),
        (_("Holat"), {"fields": ("status", "cancellation_reason")}),
        (
            _("Vaqtlar"),
            {"fields": ("accepted_at", "cancelled_at", "completed_at", "created_at", "updated_at")},
        ),
    )
    actions = (
        "accept_selected",
        "reject_selected",
        "complete_selected",
        "cancel_selected",
    )

    @admin.display(description=_("Marshrut"))
    def trip_route(self, obj: Order) -> str:
        return obj.trip.route_label()

    @admin.display(description=_("Yo'lovchi"), ordering=("passenger__first_name",))
    def passenger_name(self, obj: Order) -> str:
        return obj.passenger.display_name

    @admin.display(description=_("Yo'lovchi telefoni"), empty_value="-")
    def passenger_phone(self, obj: Order) -> str:
        return obj.passenger.phone_number or "-"

    @admin.display(description=_("Haydovchi"))
    def driver_name(self, obj: Order) -> str:
        return obj.trip.driver.user.display_name

    @admin.display(description=_("Davlat raqami"), ordering=("trip__vehicle__plate_number",))
    def plate_number(self, obj: Order) -> str:
        return obj.trip.vehicle.plate_number

    @admin.action(description=_("Tanlangan buyurtmalarni qabul qilish"))
    def accept_selected(self, request, queryset) -> None:
        for order in queryset:
            order_services.accept_order(order)
        self.message_user(request, _("Tanlangan buyurtmalar qabul qilindi."))

    @admin.action(description=_("Tanlangan buyurtmalarni rad etish"))
    def reject_selected(self, request, queryset) -> None:
        for order in queryset:
            order_services.reject_order(order, reason="Admin tomonidan rad etildi")
        self.message_user(request, _("Tanlangan buyurtmalar rad etildi."))

    @admin.action(description=_("Tanlangan buyurtmalarni yakunlash"))
    def complete_selected(self, request, queryset) -> None:
        for order in queryset:
            order_services.complete_order(order)
        self.message_user(request, _("Tanlangan buyurtmalar yakunlandi."))

    @admin.action(description=_("Tanlangan buyurtmalarni bekor qilish (haydovchi)"))
    def cancel_selected(self, request, queryset) -> None:
        for order in queryset:
            order_services.cancel_order_by_driver(order, reason="Admin tomonidan bekor qilindi")
        self.message_user(request, _("Tanlangan buyurtmalar bekor qilindi."))
