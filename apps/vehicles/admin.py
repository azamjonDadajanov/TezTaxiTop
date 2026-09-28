"""Django Admin configuration for the vehicles app."""

from __future__ import annotations

from django.contrib import admin, messages
from django.utils.translation import gettext_lazy as _

from apps.vehicles import services as vehicle_services
from apps.vehicles.models import Vehicle
from apps.vehicles.selectors import VEHICLE_ORDERING_FIELDS, VEHICLE_SEARCH_FIELDS


@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    """Verification queue plus the driver's own car list."""

    list_display = (
        "id",
        "plate_number",
        "brand",
        "model",
        "color",
        "year",
        "seats_count",
        "seats_for_passengers",
        "driver",
        "driver_phone",
        "driver_verified",
        "is_active",
        "is_verified",
        "created_at",
    )
    list_display_links = ("id", "plate_number")
    list_filter = (
        "is_active",
        "is_verified",
        "brand",
        "year",
        "seats_count",
        "driver__is_verified",
        "created_at",
    )
    search_fields = VEHICLE_SEARCH_FIELDS
    ordering = ("-created_at",)
    date_hierarchy = "created_at"
    autocomplete_fields = ("driver",)
    list_select_related = ("driver", "driver__user")
    list_per_page = 50
    readonly_fields = ("verified_at", "created_at", "updated_at", "seats_for_passengers")
    fieldsets = (
        (
            _("Avtomobil ma'lumotlari"),
            {
                "fields": (
                    "driver",
                    "brand",
                    "model",
                    "color",
                    "plate_number",
                    "year",
                    "seats_count",
                    "seats_for_passengers",
                    "photo",
                    "notes",
                )
            },
        ),
        (
            _("Holat"),
            {
                "fields": ("is_active", "is_verified", "verified_at"),
                "description": _(
                    "Faqat `is_active` va `is_verified` True bo'lgan mashina yo'lovga biriktirilishi mumkin."
                ),
            },
        ),
        (_("Vaqtlar"), {"fields": ("created_at", "updated_at")}),
    )
    actions = ("verify_selected", "unverify_selected", "activate_selected", "deactivate_selected")

    @admin.display(description=_("Sotiladigan o'rin"))
    def seats_available(self, obj: Vehicle) -> int:
        return obj.seats_for_passengers

    @admin.display(description=_("Telefon"), empty_value="-")
    def driver_phone(self, obj: Vehicle) -> str:
        return obj.driver.user.phone_number or "-"

    @admin.display(description=_("Haydovchi tasdiqlangan"), boolean=True)
    def driver_verified(self, obj: Vehicle) -> bool:
        return obj.driver.is_verified

    @admin.action(description=_("Tanlangan avtomobillarni tasdiqlash"))
    def verify_selected(self, request, queryset) -> None:
        for vehicle in queryset:
            vehicle_services.verify_vehicle(vehicle, verified=True)
        self.message_user(request, _("Tanlangan avtomobillar tasdiqlandi."), messages.SUCCESS)

    @admin.action(description=_("Tanlangan avtomobillardan tasdiqni olish"))
    def unverify_selected(self, request, queryset) -> None:
        for vehicle in queryset:
            vehicle_services.verify_vehicle(vehicle, verified=False)
        self.message_user(request, _("Tanlangan avtomobillardan tasdiq olindi."), messages.SUCCESS)

    @admin.action(description=_("Tanlangan avtomobillarni faollashtirish"))
    def activate_selected(self, request, queryset) -> None:
        for vehicle in queryset:
            vehicle_services.set_vehicle_active(vehicle, is_active=True)
        self.message_user(request, _("Tanlangan avtomobillar faollashtirildi."), messages.SUCCESS)

    @admin.action(description=_("Tanlangan avtomobillarni o'chirish (soft delete)"))
    def deactivate_selected(self, request, queryset) -> None:
        for vehicle in queryset:
            vehicle_services.set_vehicle_active(vehicle, is_active=False)
        self.message_user(request, _("Tanlangan avtomobillar o'chirildi."), messages.SUCCESS)
