"""Django Admin configuration for the rides app."""

from __future__ import annotations

from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from apps.orders.models import Order
from apps.rides import services as ride_services
from apps.rides.models import DriverTrip, DriverTripStatus, PassengerRequest, PassengerRequestStatus
from apps.rides.selectors import (
    REQUEST_ORDERING_FIELDS,
    REQUEST_SEARCH_FIELDS,
    TRIP_ORDERING_FIELDS,
    TRIP_SEARCH_FIELDS,
)


class OrderInline(admin.TabularInline):
    """Quick view of the orders attached to a trip."""

    model = Order
    extra = 0
    can_delete = False
    fields = ("id", "passenger", "seats_booked", "price_per_seat", "total_amount", "status")
    readonly_fields = fields
    show_change_link = True

    def has_add_permission(self, request, obj=None) -> bool:
        return False


@admin.register(DriverTrip)
class DriverTripAdmin(admin.ModelAdmin):
    """Searchable by driver name, phone, Telegram id, plate and route."""

    list_display = (
        "id",
        "route",
        "driver_name",
        "driver_phone",
        "driver_telegram_id",
        "plate_number",
        "departure_time",
        "total_seats",
        "available_seats",
        "price_per_seat",
        "status",
        "created_at",
    )
    list_display_links = ("id", "route")
    list_filter = (
        "status",
        "departure_time",
        "vehicle__is_verified",
        "driver__is_verified",
        "from_location__district__region",
        "created_at",
    )
    search_fields = TRIP_SEARCH_FIELDS
    ordering = ("-created_at",)
    date_hierarchy = "departure_time"
    autocomplete_fields = ("driver", "vehicle", "from_location", "to_location")
    list_select_related = ("driver__user", "vehicle", "from_location", "to_location")
    readonly_fields = ("available_seats", "created_at", "updated_at", "route")
    list_per_page = 50
    inlines = (OrderInline,)
    fieldsets = (
        (
            _("Yo'lov"),
            {
                "fields": (
                    "driver",
                    "vehicle",
                    "from_location",
                    "to_location",
                    "route",
                    "departure_time",
                )
            },
        ),
        (
            _("O'rinlar va narx"),
            {
                "fields": ("total_seats", "available_seats", "price_per_seat", "comment"),
                "description": _(
                    "Faqat tasdiqlangan va faol avtomobil tanlanishi mumkin. "
                    "`available_seats` faqat buyurtma qabul qilish/bekor qilish orqali o'zgaradi."
                ),
            },
        ),
        (_("Holat"), {"fields": ("status",)}),
        (_("Vaqtlar"), {"fields": ("created_at", "updated_at")}),
    )
    actions = ("cancel_selected", "expire_selected")

    @admin.display(description=_("Marshrut"), ordering=("from_location__name",))
    def route(self, obj: DriverTrip) -> str:
        return f"{obj.from_location.name} -> {obj.to_location.name}"

    @admin.display(description=_("Haydovchi"), ordering=("driver__user__first_name",))
    def driver_name(self, obj: DriverTrip) -> str:
        return obj.driver.user.display_name

    @admin.display(description=_("Telefon"), empty_value="-")
    def driver_phone(self, obj: DriverTrip) -> str:
        return obj.driver.user.phone_number or "-"

    @admin.display(description=_("Telegram ID"), empty_value="-")
    def driver_telegram_id(self, obj: DriverTrip) -> str:
        return str(obj.driver.user.telegram_id or "-")

    @admin.display(description=_("Davlat raqami"), ordering=("vehicle__plate_number",))
    def plate_number(self, obj: DriverTrip) -> str:
        return obj.vehicle.plate_number

    @admin.action(description=_("Tanlangan yo'lovlarni bekor qilish"))
    def cancel_selected(self, request, queryset) -> None:
        for trip in queryset:
            ride_services.cancel_trip(trip, reason="Admin orqali bekor qilindi")
        self.message_user(request, _("Tanlangan yo'lovlar bekor qilindi."))

    @admin.action(description=_("Tanlangan yo'lovlarni muddati tugagan deb belgilash"))
    def expire_selected(self, request, queryset) -> None:
        for trip in queryset:
            trip.status = DriverTripStatus.EXPIRED
            trip.save(update_fields=["status", "updated_at"])
        self.message_user(request, _("Tanlangan yo'lovlar muddati tugagan deb belgilandi."))


@admin.register(PassengerRequest)
class PassengerRequestAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "passenger_name",
        "passenger_phone",
        "passenger_telegram_id",
        "route",
        "passenger_count",
        "max_price_per_seat",
        "departure_from",
        "departure_until",
        "status",
        "created_at",
    )
    list_display_links = ("id", "route")
    list_filter = (
        "status",
        "from_location__district__region",
        "created_at",
        "departure_from",
    )
    search_fields = REQUEST_SEARCH_FIELDS
    ordering = ("-created_at",)
    date_hierarchy = "created_at"
    autocomplete_fields = ("passenger", "from_location", "to_location")
    list_select_related = ("passenger", "from_location", "to_location")
    readonly_fields = ("created_at", "updated_at", "route")
    list_per_page = 50
    actions = ("cancel_selected", "expire_selected")

    @admin.display(description=_("Marshrut"))
    def route(self, obj: PassengerRequest) -> str:
        return f"{obj.from_location.name} -> {obj.to_location.name}"

    @admin.display(description=_("Yo'lovchi"), ordering=("passenger__first_name",))
    def passenger_name(self, obj: PassengerRequest) -> str:
        return obj.passenger.display_name

    @admin.display(description=_("Telefon"), empty_value="-")
    def passenger_phone(self, obj: PassengerRequest) -> str:
        return obj.passenger.phone_number or "-"

    @admin.display(description=_("Telegram ID"), empty_value="-")
    def passenger_telegram_id(self, obj: PassengerRequest) -> str:
        return str(obj.passenger.telegram_id or "-")

    @admin.action(description=_("Tanlangan so'rovlarni bekor qilish"))
    def cancel_selected(self, request, queryset) -> None:
        for passenger_request in queryset:
            ride_services.cancel_passenger_request(passenger_request)
        self.message_user(request, _("Tanlangan so'rovlar bekor qilindi."))

    @admin.action(description=_("Tanlangan so'rovlarni muddati tugagan deb belgilash"))
    def expire_selected(self, request, queryset) -> None:
        for passenger_request in queryset:
            passenger_request.status = PassengerRequestStatus.EXPIRED
            passenger_request.save(update_fields=["status", "updated_at"])
        self.message_user(request, _("Tanlangan so'rovlar muddati tugagan deb belgilandi."))
