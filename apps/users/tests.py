"""Tests for the users app: registration, roles, driver profile, moderation."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from decimal import Decimal
from urllib.parse import urlencode

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.core.exceptions import BusinessValidationError, NotADriver, UserIsBlocked
from apps.users import services as user_services
from apps.users.constants import UserRole
from apps.users.models import DriverProfile, User


class UserRegistrationTests(TestCase):
    def test_create_user_from_telegram_creates_account(self) -> None:
        user, created = user_services.get_or_create_user_from_telegram(
            telegram_id=555000111,
            username="ali",
            first_name="Ali",
            last_name="Karimov",
        )
        self.assertTrue(created)
        self.assertEqual(user.telegram_id, 555000111)
        self.assertEqual(user.role, UserRole.PASSENGER)
        self.assertFalse(user.has_usable_password())
        self.assertEqual(user.display_name, "Ali Karimov")

    def test_registration_is_idempotent(self) -> None:
        first_user, first_created = user_services.get_or_create_user_from_telegram(telegram_id=1, username="ali")
        second_user, second_created = user_services.get_or_create_user_from_telegram(
            telegram_id=1, username="ali_renamed", first_name="Alisher"
        )
        self.assertTrue(first_created)
        self.assertFalse(second_created)
        self.assertEqual(first_user.pk, second_user.pk)
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(second_user.first_name, "Alisher")
        self.assertEqual(second_user.username, "ali_renamed")

    def test_telegram_id_must_be_unique(self) -> None:
        User.objects.create_user(username="one", telegram_id=42)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                User.objects.create_user(username="two", telegram_id=42)

    def test_telegram_id_is_nullable_for_staff_accounts(self) -> None:
        staff = User.objects.create_user(username="admin_only")
        self.assertIsNone(staff.telegram_id)
        self.assertEqual(User.objects.filter(telegram_id__isnull=True).count(), 1)

    def test_phone_number_is_normalized(self) -> None:
        user = user_services.get_or_create_user_from_telegram(telegram_id=7, phone_number="901234567")[0]
        self.assertEqual(user.phone_number, "+998901234567")

    def test_registration_requires_telegram_id(self) -> None:
        with self.assertRaises(BusinessValidationError):
            user_services.get_or_create_user_from_telegram(telegram_id=0)

    def test_touch_last_seen(self) -> None:
        user = User.objects.create_user(username="ali", telegram_id=1)
        self.assertIsNone(user.last_seen_at)
        user_services.touch_last_seen(user)
        self.assertIsNotNone(user.last_seen_at)


@override_settings(TELEGRAM_BOT_TOKEN="123456:test-secret")
class TelegramMiniAppAuthTests(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()

    @override_settings(CORS_ALLOWED_ORIGINS=["https://mini.example.com"])
    def test_allowlisted_frontend_origin_receives_cors_preflight(self) -> None:
        response = self.client.options(
            "/api/v1/auth/telegram-mini-app/",
            HTTP_ORIGIN="https://mini.example.com",
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
            HTTP_ACCESS_CONTROL_REQUEST_HEADERS="content-type",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Access-Control-Allow-Origin"],
            "https://mini.example.com",
        )

    def signed_init_data(self, *, auth_date: int | None = None) -> str:
        fields = {
            "auth_date": str(auth_date if auth_date is not None else int(time.time())),
            "user": json.dumps(
                {
                    "id": 876543210123,
                    "first_name": "Mini",
                    "last_name": "App",
                    "username": "mini_app_user",
                    "language_code": "uz",
                },
                separators=(",", ":"),
            ),
        }
        data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
        secret_key = hmac.new(b"WebAppData", b"123456:test-secret", hashlib.sha256).digest()
        fields["hash"] = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        return urlencode(fields)

    def test_signed_init_data_creates_user_and_returns_api_token(self) -> None:
        response = self.client.post(
            "/api/v1/auth/telegram-mini-app/",
            {"init_data": self.signed_init_data()},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertTrue(response.data["token"])
        self.assertTrue(response.data["is_new"])
        self.assertEqual(response.data["user"]["telegram_id"], 876543210123)
        self.assertEqual(response.data["user"]["role"], UserRole.PASSENGER)
        self.assertEqual(response.data["user"]["phone_number"], "")

        self.client.credentials(HTTP_AUTHORIZATION=f"Token {response.data['token']}")
        profile = self.client.get("/api/v1/auth/me/")
        self.assertEqual(profile.status_code, 200)
        self.assertEqual(profile.data["telegram_id"], 876543210123)

    def test_tampered_init_data_is_rejected(self) -> None:
        init_data = f"{self.signed_init_data()}&username=attacker"
        response = self.client.post(
            "/api/v1/auth/telegram-mini-app/",
            {"init_data": init_data},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(User.objects.count(), 0)

    def test_expired_init_data_is_rejected(self) -> None:
        expired_auth_date = int(time.time()) - 24 * 60 * 60 - 1
        response = self.client.post(
            "/api/v1/auth/telegram-mini-app/",
            {"init_data": self.signed_init_data(auth_date=expired_auth_date)},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(User.objects.count(), 0)

    def test_raw_telegram_id_cannot_register_or_obtain_a_token(self) -> None:
        response = self.client.post(
            "/api/v1/auth/register-telegram/",
            {"telegram_id": 876543210123, "first_name": "Spoofed"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(User.objects.count(), 0)


class UserRoleTests(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(username="ali", telegram_id=1)

    def test_set_driver_role_creates_profile(self) -> None:
        user_services.set_user_role(self.user, UserRole.DRIVER)
        self.user.refresh_from_db()
        self.assertEqual(self.user.role, UserRole.DRIVER)
        self.assertTrue(hasattr(self.user, "driver_profile"))

    def test_switch_back_to_passenger_removes_empty_profile(self) -> None:
        user_services.set_user_role(self.user, UserRole.DRIVER)
        user_services.set_user_role(self.user, UserRole.PASSENGER)
        self.user.refresh_from_db()
        self.assertEqual(self.user.role, UserRole.PASSENGER)
        self.assertFalse(DriverProfile.objects.filter(user=self.user).exists())

    def test_invalid_role_is_rejected(self) -> None:
        with self.assertRaises(BusinessValidationError):
            user_services.set_user_role(self.user, "superuser")

    def test_both_role_is_allowed(self) -> None:
        user_services.set_user_role(self.user, UserRole.BOTH)
        self.user.refresh_from_db()
        self.assertEqual(self.user.role, UserRole.BOTH)
        self.assertTrue(self.user.is_passenger)
        self.assertTrue(self.user.is_driver_role)


class DriverProfileTests(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(username="ali", telegram_id=1, role=UserRole.DRIVER)

    def test_create_driver_profile(self) -> None:
        profile = user_services.create_driver_profile(self.user)
        self.assertEqual(profile.user, self.user)
        self.assertFalse(profile.is_verified)
        self.assertEqual(profile.rating, Decimal("5.00"))
        self.assertEqual(profile.total_trips, 0)

    def test_profile_is_unique_per_user(self) -> None:
        user_services.create_driver_profile(self.user)
        again = user_services.create_driver_profile(self.user)
        self.assertEqual(DriverProfile.objects.filter(user=self.user).count(), 1)
        self.assertEqual(again.pk, DriverProfile.objects.get(user=self.user).pk)

    def test_profile_requires_driver_role(self) -> None:
        passenger = User.objects.create_user(username="vali", telegram_id=2, role=UserRole.PASSENGER)
        profile = DriverProfile(user=passenger)
        with self.assertRaises(ValidationError):
            profile.full_clean()

    def test_verify_driver_profile(self) -> None:
        profile = user_services.create_driver_profile(self.user)
        user_services.verify_driver_profile(profile)
        profile.refresh_from_db()
        self.assertTrue(profile.is_verified)
        self.assertIsNotNone(profile.verified_at)

    def test_rating_bounds_enforced_by_database(self) -> None:
        profile = user_services.create_driver_profile(self.user)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                DriverProfile.objects.filter(pk=profile.pk).update(rating=Decimal("9.99"))

    def test_completed_cannot_exceed_total(self) -> None:
        profile = user_services.create_driver_profile(self.user)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                DriverProfile.objects.filter(pk=profile.pk).update(total_trips=1, completed_trips=2)

    def test_increment_trip_statistics(self) -> None:
        profile = user_services.create_driver_profile(self.user)
        user_services.increment_driver_trip_statistics(profile)
        user_services.increment_driver_trip_statistics(profile, cancelled=True)
        profile.refresh_from_db()
        self.assertEqual(profile.total_trips, 2)
        self.assertEqual(profile.cancelled_trips, 1)

    def test_increment_completed_trips(self) -> None:
        profile = user_services.create_driver_profile(self.user)
        user_services.increment_completed_trips(profile)
        profile.refresh_from_db()
        self.assertEqual(profile.completed_trips, 1)

    def test_get_required_driver_profile_raises_for_passenger(self) -> None:
        passenger = User.objects.create_user(username="p", telegram_id=3, role=UserRole.PASSENGER)
        with self.assertRaises(NotADriver):
            user_services.get_required_driver_profile(passenger)

    def test_set_driver_rating_validates_bounds(self) -> None:
        profile = user_services.create_driver_profile(self.user)
        with self.assertRaises(BusinessValidationError):
            user_services.set_driver_rating(profile, rating=Decimal("6.00"))
        with self.assertRaises(BusinessValidationError):
            user_services.set_driver_rating(profile, rating=Decimal("0.50"))


class ModerationTests(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(username="ali", telegram_id=1)

    def test_block_and_unblock(self) -> None:
        user_services.block_user(self.user)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_blocked)
        self.assertFalse(self.user.is_active)

        user_services.unblock_user(self.user)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_blocked)
        self.assertTrue(self.user.is_active)

    def test_blocked_user_cannot_register_as_driver(self) -> None:
        user_services.block_user(self.user)
        with self.assertRaises(UserIsBlocked):
            user_services.register_as_driver(self.user)

    def test_blocking_preserves_historical_records(self) -> None:
        profile = user_services.create_driver_profile(self.user)
        user_services.block_user(self.user)
        self.assertTrue(DriverProfile.objects.filter(pk=profile.pk).exists())
