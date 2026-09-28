"""Django Admin configuration for the locations app."""

from __future__ import annotations

from django.contrib import admin, messages
from django.utils.translation import gettext_lazy as _

from apps.locations import services as location_services
from apps.locations.models import District, Location, Region
from apps.locations.selectors import DISTRICT_SEARCH_FIELDS, LOCATION_SEARCH_FIELDS


class DistrictInline(admin.TabularInline):
    model = District
    extra = 0
    fields = ("name", "is_active")
    show_change_link = True


@admin.register(Region)
class RegionAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "code", "districts_count", "is_active", "created_at")
    list_display_links = ("id", "name")
    list_filter = ("is_active", "created_at")
    search_fields = ("id", "name", "code")
    ordering = ("name",)
    autocomplete_fields = ()
    inlines = (DistrictInline,)
    readonly_fields = ("created_at", "updated_at")
    list_per_page = 50
    actions = ("activate_selected", "deactivate_selected")

    @admin.display(description=_("Tumanlar soni"))
    def districts_count(self, obj: Region) -> int:
        return obj.districts.count()

    @admin.action(description=_("Tanlangan viloyatlarni faollashtirish"))
    def activate_selected(self, request, queryset) -> None:
        for region in queryset:
            location_services.update_region(region, is_active=True)
        self.message_user(request, _("Tanlangan viloyatlar faollashtirildi."), messages.SUCCESS)

    @admin.action(description=_("Tanlangan viloyatlarni o'chirish"))
    def deactivate_selected(self, request, queryset) -> None:
        for region in queryset:
            location_services.update_region(region, is_active=False)
        self.message_user(request, _("Tanlangan viloyatlar o'chirildi."), messages.SUCCESS)


@admin.register(District)
class DistrictAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "region", "locations_count", "is_active", "created_at")
    list_display_links = ("id", "name")
    list_filter = ("is_active", "region", "created_at")
    search_fields = DISTRICT_SEARCH_FIELDS
    ordering = ("region__name", "name")
    autocomplete_fields = ("region",)
    list_select_related = ("region",)
    readonly_fields = ("created_at", "updated_at")
    list_per_page = 50
    actions = ("activate_selected", "deactivate_selected")

    @admin.display(description=_("Manzillar soni"))
    def locations_count(self, obj: District) -> int:
        return obj.locations.count()

    @admin.action(description=_("Tanlangan tumanlarni faollashtirish"))
    def activate_selected(self, request, queryset) -> None:
        for district in queryset:
            location_services.update_district(district, is_active=True)
        self.message_user(request, _("Tanlangan tumanlar faollashtirildi."), messages.SUCCESS)

    @admin.action(description=_("Tanlangan tumanlarni o'chirish"))
    def deactivate_selected(self, request, queryset) -> None:
        for district in queryset:
            location_services.update_district(district, is_active=False)
        self.message_user(request, _("Tanlangan tumanlar o'chirildi."), messages.SUCCESS)


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    """Trip search works by location, so the admin keeps coordinates visible."""

    list_display = (
        "id",
        "name",
        "district",
        "region",
        "latitude",
        "longitude",
        "address",
        "is_active",
        "created_at",
    )
    list_display_links = ("id", "name")
    list_filter = ("is_active", "district__region", "district", "created_at")
    search_fields = LOCATION_SEARCH_FIELDS
    ordering = ("district__region__name", "district__name", "name")
    date_hierarchy = "created_at"
    autocomplete_fields = ("district",)
    list_select_related = ("district", "district__region")
    readonly_fields = ("created_at", "updated_at")
    list_per_page = 50
    fieldsets = (
        (
            _("Manzil"),
            {
                "fields": (
                    "district",
                    "name",
                    "address",
                    "latitude",
                    "longitude",
                )
            },
        ),
        (_("Holat"), {"fields": ("is_active",)}),
        (_("Vaqtlar"), {"fields": ("created_at", "updated_at")}),
    )
    actions = ("activate_selected", "deactivate_selected")

    @admin.display(description=_("Viloyat"))
    def region(self, obj: Location) -> str:
        return obj.district.region.name

    @admin.action(description=_("Tanlangan manzillarni faollashtirish"))
    def activate_selected(self, request, queryset) -> None:
        for location in queryset:
            location_services.set_location_active(location, is_active=True)
        self.message_user(request, _("Tanlangan manzillar faollashtirildi."), messages.SUCCESS)

    @admin.action(description=_("Tanlangan manzillarni o'chirish"))
    def deactivate_selected(self, request, queryset) -> None:
        for location in queryset:
            location_services.set_location_active(location, is_active=False)
        self.message_user(request, _("Tanlangan manzillar o'chirildi."), messages.SUCCESS)
