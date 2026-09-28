"""Django Admin configuration for the matching app."""

from __future__ import annotations

from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from apps.matching import services as matching_services
from apps.matching.models import TripMatch


@admin.register(TripMatch)
class TripMatchAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "request_link",
        "trip_link",
        "score",
        "rank",
        "time_score",
        "price_score",
        "rating_score",
        "subscription_score",
        "vehicle_score",
        "created_at",
    )
    list_display_links = ("id", "request_link", "trip_link")
    list_filter = ("reason", "created_at")
    search_fields = ("request__passenger__username", "trip__vehicle__plate_number", "id")
    ordering = ("-score",)
    date_hierarchy = "created_at"
    autocomplete_fields = ("request", "trip")
    list_select_related = ("request", "trip")
    readonly_fields = (
        "score",
        "rank",
        "time_score",
        "price_score",
        "rating_score",
        "subscription_score",
        "vehicle_score",
        "minutes_difference",
        "price_difference",
        "components_detail",
        "created_at",
        "updated_at",
    )
    list_per_page = 50
    actions = ("rescore_selected",)
    fieldsets = (
        (
            _("Moslik"),
            {
                "fields": (
                    "request",
                    "request_link",
                    "trip",
                    "trip_link",
                    "score",
                    "rank",
                    "components_detail",
                )
            },
        ),
        (
            _("Tarkibiy ballar"),
            {
                "fields": (
                    "time_score",
                    "price_score",
                    "rating_score",
                    "subscription_score",
                    "vehicle_score",
                    "minutes_difference",
                    "price_difference",
                )
            },
        ),
        (_("Vaqtlar"), {"fields": ("reason", "created_at", "updated_at")}),
    )

    @admin.display(description=_("So'rov"))
    def request_link(self, obj: TripMatch) -> str:
        return f"#{obj.request_id} ({obj.request.route_label if hasattr(obj.request, 'route_label') else ''})"

    @admin.display(description=_("Yo'lov"))
    def trip_link(self, obj: TripMatch) -> str:
        return f"#{obj.trip_id} ({obj.trip.route_label()})"

    @admin.display(description=_("Ball tarkibi"))
    def components_detail(self, obj: TripMatch) -> str:
        return ", ".join(f"{key}={value}" for key, value in obj.components.items())

    @admin.action(description=_("Qayta baholash"))
    def rescore_selected(self, request, queryset) -> None:
        for match in queryset.select_related("request"):
            matching_services.refresh_matches_for_request(match.request)
