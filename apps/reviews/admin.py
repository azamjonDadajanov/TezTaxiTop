"""Django Admin configuration for the reviews app."""

from __future__ import annotations

from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from apps.reviews import services as review_services
from apps.reviews.models import Review
from apps.reviews.selectors import REVIEW_SEARCH_FIELDS


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "order_link",
        "reviewer",
        "reviewed_user",
        "rating_stars",
        "comment_short",
        "created_at",
    )
    list_display_links = ("id", "order_link")
    list_filter = ("rating", "created_at")
    search_fields = REVIEW_SEARCH_FIELDS
    ordering = ("-created_at",)
    date_hierarchy = "created_at"
    autocomplete_fields = ("order", "reviewer", "reviewed_user")
    list_select_related = ("order", "reviewer", "reviewed_user")
    readonly_fields = ("created_at", "updated_at", "order_link", "rating_stars")
    list_per_page = 50
    fieldsets = (
        (
            _("Baholash"),
            {
                "fields": (
                    "order",
                    "order_link",
                    "reviewer",
                    "reviewed_user",
                    "rating",
                    "rating_stars",
                    "comment",
                )
            },
        ),
        (_("Vaqtlar"), {"fields": ("created_at", "updated_at")}),
    )

    @admin.display(description=_("Buyurtma"))
    def order_link(self, obj: Review) -> str:
        return f"#{obj.order_id} ({obj.order.get_status_display()})"

    @admin.display(description=_("Baho"), ordering="rating")
    def rating_stars(self, obj: Review) -> str:
        return "*" * obj.rating + "-" * (5 - obj.rating)

    @admin.display(description=_("Izoh"))
    def comment_short(self, obj: Review) -> str:
        return (obj.comment[:60] + "...") if len(obj.comment) > 60 else obj.comment

    def save_model(self, request, obj, form, change) -> None:
        """Keep the cached driver rating consistent with the reviews table."""
        super().save_model(request, obj, form, change)
        review_services.recalculate_driver_rating(obj.reviewed_user)
