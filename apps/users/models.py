"""User and driver profile models.

Design decisions
----------------
* ``AbstractUser`` (not a from-scratch identity model) keeps Django admin,
  ``django.contrib.auth``, permissions and password hashing working unchanged.
* ``telegram_id`` is the real platform identity. It is nullable so that staff
  accounts created from the admin panel do not need a Telegram account, and
  unique so that one Telegram identity can never own two accounts. PostgreSQL
  and SQLite both allow any number of ``NULL`` values in a unique index.
* ``role`` is *never* taken from client input; only
  :func:`apps.users.services.set_user_role` writes it.
* ``DriverProfile`` deliberately stores no vehicle data - a driver may own many
  vehicles (``apps.vehicles``) and profile/car are separate lifecycles.
"""

from __future__ import annotations

from decimal import Decimal

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel
from apps.core.validators import normalize_phone_number, validate_phone_number
from apps.users.constants import DRIVER_ROLES, UserRole
from apps.users.managers import UserManager

#: Ratings are stored as ``Decimal`` (never ``float``) so that averaging
#: thousands of reviews does not accumulate binary floating point error.
RATING_MAX_DIGITS = 3
RATING_DECIMAL_PLACES = 2
DEFAULT_RATING = Decimal("5.00")


class User(AbstractUser, TimeStampedModel):
    """Platform account for both passengers and drivers."""

    telegram_id = models.BigIntegerField(
        verbose_name="Telegram ID",
        unique=True,
        null=True,
        blank=True,
        db_index=True,
        help_text="Telegram hisobining noyob raqami. Bo'sh bo'lishi mumkin (admin panel orqali yaratilgan hisoblar uchun).",
    )
    phone_number = models.CharField(
        verbose_name="Telefon raqami",
        max_length=20,
        blank=True,
        default="",
        validators=[validate_phone_number],
        help_text="+998901234567 ko'rinishida saqlanadi.",
    )
    role = models.CharField(
        verbose_name="Rol",
        max_length=20,
        choices=UserRole.choices,
        default=UserRole.PASSENGER,
        db_index=True,
        help_text="Platformadagi vazifa: yo'lovchi, haydovchi yoki ikkalasi.",
    )
    is_blocked = models.BooleanField(
        verbose_name="Bloklangan",
        default=False,
        db_index=True,
        help_text="Administrator tomonidan bloklangan foydalanuvchi.",
    )
    language_code = models.CharField(
        verbose_name="Til kodi",
        max_length=10,
        default="uz",
        help_text="Foydalanuvchi interfeys tili (uz / ru / en).",
    )
    last_seen_at = models.DateTimeField(
        verbose_name="Oxirgi faollik",
        null=True,
        blank=True,
        help_text="Foydalanuvchi bot bilan oxirgi marta muloqot qilgan payt.",
    )

    # Inherited from AbstractUser and therefore documented here for the admin:
    #   username, first_name, last_name, email, is_active, is_staff,
    #   is_superuser, date_joined, last_login.
    objects = UserManager()

    class Meta:
        verbose_name = "Foydalanuvchi"
        verbose_name_plural = "Foydalanuvchilar"
        ordering = ("-created_at",)
        indexes = [
            # `telegram_id` already has a unique index created by `unique=True`.
            models.Index(fields=("role", "is_active"), name="user_role_active_idx"),
            models.Index(fields=("phone_number",), name="user_phone_idx"),
        ]

    def __str__(self) -> str:
        return self.display_name

    # -- helpers (small, non-business) ---------------------------------------
    def clean(self) -> None:
        super().clean()
        self.phone_number = normalize_phone_number(self.phone_number)
        if self.role not in UserRole.values:
            raise ValidationError({"role": _("Noma'lum rol qiymati.")})

    def save(self, *args, **kwargs) -> None:
        # Phone normalisation is a data-hygiene concern, safe to enforce on save.
        self.phone_number = normalize_phone_number(self.phone_number)
        super().save(*args, **kwargs)

    @property
    def display_name(self) -> str:
        """Best available human readable name."""
        full_name = self.get_full_name().strip()
        return full_name or self.username or f"telegram:{self.telegram_id}"

    @property
    def telegram_chat_id(self) -> int | None:
        """The Telegram chat used to deliver messages, or ``None``.

        Single source of truth for every delivery decision (Celery tasks, the
        bot and the Admin) so a user is never "reachable" in one module and
        "unreachable" in another.
        """
        if self.is_blocked:
            return None
        return self.telegram_id

    @property
    def can_receive_telegram(self) -> bool:
        return self.telegram_chat_id is not None

    @property
    def is_passenger(self) -> bool:
        return self.role in (UserRole.PASSENGER, UserRole.BOTH)

    @property
    def is_driver_role(self) -> bool:
        return self.role in DRIVER_ROLES

    @property
    def can_drive(self) -> bool:
        """The user owns a driver profile and it is not blocked.

        Subscription checks intentionally live in
        :func:`apps.subscriptions.services.has_active_subscription` and in
        :func:`apps.rides.services.assert_driver_can_create_trip`.
        """
        if self.is_blocked:
            return False
        profile = getattr(self, "driver_profile", None)
        return profile is not None

    @property
    def average_rating(self) -> Decimal:
        return getattr(getattr(self, "driver_profile", None), "rating", DEFAULT_RATING)


class DriverProfile(TimeStampedModel):
    """Driver specific data: verification flag, rating and trip statistics.

    ``user`` is a ``OneToOneField`` because exactly one profile per account is
    allowed; ``related_name="driver_profile"`` gives the natural reverse
    accessor used all over the codebase.
    """

    user = models.OneToOneField(
        "users.User",
        on_delete=models.PROTECT,
        related_name="driver_profile",
        verbose_name="Foydalanuvchi",
        help_text="Faqat DRIVER yoki BOTH roliga ega foydalanuvchilar profil yaratishi mumkin.",
    )
    is_verified = models.BooleanField(
        verbose_name="Tasdiqlangan",
        default=False,
        db_index=True,
        help_text="Administrator tomonidan tasdiqlangan. Tasdiqlanmagan haydovchi yo'lov yarata olmaydi.",
    )
    verified_at = models.DateTimeField(
        verbose_name="Tasdiqlangan vaqti",
        null=True,
        blank=True,
    )
    rating = models.DecimalField(
        verbose_name="Reyting",
        max_digits=RATING_MAX_DIGITS,
        decimal_places=RATING_DECIMAL_PLACES,
        default=DEFAULT_RATING,
        validators=[MinValueValidator(Decimal("1.00")), MaxValueValidator(Decimal("5.00"))],
        help_text="1.00 dan 5.00 gacha. `apps.reviews` servisi baholarni qayta hisoblaydi.",
    )
    rating_count = models.PositiveIntegerField(
        verbose_name="Baholar soni",
        default=0,
        help_text="Reyting o'rtachasi hisoblangan baholar soni.",
    )
    total_trips = models.PositiveIntegerField(
        verbose_name="Jami yo'lovlar",
        default=0,
        help_text="Haydovchi tomonidan yaratilgan yo'lovlar soni.",
    )
    completed_trips = models.PositiveIntegerField(
        verbose_name="Yakunlangan yo'lovlar",
        default=0,
        help_text="Muvaffaqiyatli yakunlangan yo'lovlar soni.",
    )
    cancelled_trips = models.PositiveIntegerField(
        verbose_name="Bekor qilingan yo'lovlar",
        default=0,
        help_text="Bekor qilingan yo'lovlar soni.",
    )
    bio = models.CharField(
        verbose_name="Izoh",
        max_length=500,
        blank=True,
        default="",
        help_text="Yo'lovchilar ko'radigan qisqacha tavsif.",
    )

    class Meta:
        verbose_name = "Haydovchi profili"
        verbose_name_plural = "Haydovchi profillari"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("is_verified", "-rating"), name="driverprofile_verified_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(rating__gte=Decimal("1.00")) & models.Q(rating__lte=Decimal("5.00")),
                name="driverprofile_rating_between_1_and_5",
            ),
            models.CheckConstraint(
                condition=models.Q(completed_trips__lte=models.F("total_trips")),
                name="driverprofile_completed_lte_total",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user.display_name} (haydovchi)"

    def clean(self) -> None:
        super().clean()
        if self.user_id and self.user.role not in DRIVER_ROLES:
            raise ValidationError(
                {
                    "user": _(
                        "Haydovchi profili faqat DRIVER yoki BOTH roliga ega foydalanuvchi uchun yaratiladi."
                    )
                }
            )

    # -- helpers (small, non-business) ---------------------------------------
    @property
    def rating_as_float(self) -> float:
        """Rounded float used only for display / analytics, never for storage."""
        return float(self.rating.quantize(Decimal("0.01")))

    def has_verified_vehicle(self) -> bool:
        """Whether the driver owns at least one active verified vehicle."""
        return self.vehicles.filter(is_active=True, is_verified=True).exists()
