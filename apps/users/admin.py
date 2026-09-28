"""Django Admin configuration for the users app.

The admin is the operational tool of the platform (verification, blocking,
moderation), therefore it is configured with wide search, filters and
autocomplete links to related objects.
"""

from __future__ import annotations

from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _

from apps.users import services as user_services
from apps.users.models import DriverProfile, User
from apps.users.selectors import USER_ORDERING_FIELDS, USER_SEARCH_FIELDS


class DriverProfileInline(admin.StackedInline):
    """Driver data lives on the user page as well."""

    model = DriverProfile
    can_delete = False
    verbose_name = _("Haydovchi profili")
    verbose_name_plural = _("Haydovchi profili")
    extra = 0
    fields = (
        "is_verified",
        "verified_at",
        "rating",
        "rating_count",
        "total_trips",
        "completed_trips",
        "cancelled_trips",
        "bio",
    )
    readonly_fields = ("rating", "rating_count", "total_trips", "completed_trips", "cancelled_trips")


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Telegram aware user admin."""

    list_display = (
        "id",
        "display_name",
        "telegram_id",
        "phone_number",
        "role",
        "driver_verified",
        "is_active",
        "is_blocked",
        "last_seen_at",
        "created_at",
    )
    list_display_links = ("id", "display_name")
    list_filter = (
        "role",
        "is_active",
        "is_blocked",
        "is_staff",
        "is_superuser",
        "driver_profile__is_verified",
        "date_joined",
    )
    search_fields = USER_SEARCH_FIELDS
    ordering = ("-created_at",)
    date_hierarchy = "created_at"
    autocomplete_fields = ()
    list_per_page = 50
    filter_horizontal = ("groups", "user_permissions")

    fieldsets = (
        (None, {"fields": ("username", "password")}),
        (
            _("Telegram ma'lumotlari"),
            {
                "fields": ("telegram_id", "language_code", "last_seen_at"),
                "description": _("Telegram bot orqali avtomatik to'ldiriladigan maydonlar."),
            },
        ),
        (
            _("Shaxsiy ma'lumotlar"),
            {"fields": ("first_name", "last_name", "phone_number", "email")},
        ),
        (
            _("Platforma holati"),
            {
                "fields": ("role", "is_active", "is_blocked"),
                "description": _(
                    "Rol foydalanuvchi arizasi orqali o'zgaradi: `DriverProfile` mavjudligiga "
                    "qarab avtomatik `driver`/`both` qiymatiga o'tadi."
                ),
            },
        ),
        (
            _("Ruxsatlar"),
            {"fields": ("is_staff", "is_superuser", "groups", "user_permissions")},
        ),
        (_("Vaqtlar"), {"fields": ("last_login", "date_joined", "created_at", "updated_at")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "username",
                    "telegram_id",
                    "first_name",
                    "last_name",
                    "phone_number",
                    "role",
                    "password1",
                    "password2",
                ),
            },
        ),
    )
    readonly_fields = ("last_login", "date_joined", "created_at", "updated_at")

    @admin.display(description=_("Haydovchi"), boolean=True)
    def driver_verified(self, obj: User) -> bool:
        return bool(getattr(obj, "driver_profile", None) and obj.driver_profile.is_verified)

    @admin.action(description=_("Tanlangan foydalanuvchilarni bloklash"))
    def block_selected(self, request, queryset) -> None:
        count = 0
        for user in queryset:
            user_services.block_user(user)
            count += 1
        self.message_user(request, _("%(count)d ta foydalanuvchi bloklandi.") % {"count": count}, messages.SUCCESS)

    @admin.action(description=_("Tanlangan foydalanuvchilarning blokini olish"))
    def unblock_selected(self, request, queryset) -> None:
        count = 0
        for user in queryset:
            user_services.unblock_user(user)
            count += 1
        self.message_user(
            request, _("%(count)d ta foydalanuvchining bloki olindi.") % {"count": count}, messages.SUCCESS
        )

    actions = ("block_selected", "unblock_selected")
    inlines = (DriverProfileInline,)


@admin.register(DriverProfile)
class DriverProfileAdmin(admin.ModelAdmin):
    """Verification and statistics screen for drivers."""

    list_display = (
        "id",
        "user",
        "phone_number_display",
        "is_verified",
        "rating",
        "rating_count",
        "total_trips",
        "completed_trips",
        "cancelled_trips",
        "created_at",
    )
    list_display_links = ("id", "user")
    list_filter = ("is_verified", "user__role", "user__is_blocked", "created_at")
    search_fields = (
        "id",
        "user__username",
        "user__first_name",
        "user__last_name",
        "user__phone_number",
        "user__telegram_id",
    )
    ordering = ("-created_at",)
    date_hierarchy = "created_at"
    autocomplete_fields = ("user",)
    list_select_related = ("user",)
    list_per_page = 50
    readonly_fields = (
        "rating",
        "rating_count",
        "total_trips",
        "completed_trips",
        "cancelled_trips",
        "created_at",
        "updated_at",
    )
    fieldsets = (
        (None, {"fields": ("user", "bio")}),
        (
            _("Tasdiqlash"),
            {"fields": ("is_verified", "verified_at")},
        ),
        (
            _("Reyting"),
            {
                "fields": ("rating", "rating_count"),
                "description": _("Reyting `apps.reviews` servisi tomonidan avtomatik hisoblanadi."),
            },
        ),
        (
            _("Statistika"),
            {"fields": ("total_trips", "completed_trips", "cancelled_trips")},
        ),
        (_("Vaqtlar"), {"fields": ("created_at", "updated_at")}),
    )
    actions = ("verify_selected", "unverify_selected")

    @admin.display(description=_("Telefon"), ordering="user__phone_number")
    def phone_number_display(self, obj: DriverProfile) -> str:
        return obj.user.phone_number or "-"

    @admin.action(description=_("Tanlangan haydovchilarni tasdiqlash"))
    def verify_selected(self, request, queryset) -> None:
        for profile in queryset:
            user_services.verify_driver_profile(profile, verified=True)
        self.message_user(request, _("Tanlangan haydovchilar tasdiqlandi."), messages.SUCCESS)

    @admin.action(description=_("Tanlangan haydovchilardan tasdiqni olish"))
    def unverify_selected(self, request, queryset) -> None:
        for profile in queryset:
            user_services.verify_driver_profile(profile, verified=False)
        self.message_user(request, _("Tanlangan haydovchilardan tasdiq olindi."), messages.SUCCESS)
