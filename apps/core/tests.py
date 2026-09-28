"""Tests for the shared technical layer."""

from __future__ import annotations

from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIRequestFactory

from apps.core.exceptions import BusinessError, InsufficientSeats, UserIsBlocked
from apps.core.permissions import IsAuthenticatedActiveUser, IsOwner, IsOwnerOrReadOnly
from apps.core.validators import normalize_phone_number, validate_phone_number

User = get_user_model()


class PhoneNumberValidatorTests(TestCase):
    def test_accepts_international_format(self) -> None:
        validate_phone_number("+998901234567")

    def test_rejects_letters(self) -> None:
        with self.assertRaises(Exception):
            validate_phone_number("+99890abc4567")

    def test_normalize_local_number(self) -> None:
        self.assertEqual(normalize_phone_number("901234567"), "+998901234567")

    def test_normalize_already_normalized(self) -> None:
        self.assertEqual(normalize_phone_number("+998901234567"), "+998901234567")

    def test_normalize_blank(self) -> None:
        self.assertEqual(normalize_phone_number(None), "")


class BusinessErrorTests(TestCase):
    def test_default_code_and_status(self) -> None:
        error = InsufficientSeats()
        self.assertEqual(error.code, "insufficient_seats")
        self.assertEqual(error.status_code, 409)

    def test_as_dict_contains_details(self) -> None:
        error = InsufficientSeats(details={"available_seats": 0})
        payload = error.as_dict()
        self.assertEqual(payload["code"], "insufficient_seats")
        self.assertEqual(payload["details"], {"available_seats": 0})

    def test_custom_message(self) -> None:
        error = BusinessError("Maxsus xabar")
        self.assertEqual(str(error), "Maxsus xabar")


class PermissionTests(TestCase):
    def setUp(self) -> None:
        self.factory = APIRequestFactory()
        self.user = User.objects.create_user(username="ali", password="pwd")
        self.other = User.objects.create_user(username="vali", password="pwd")
        self.request = self.factory.get("/")

    def test_blocked_user_is_denied(self) -> None:
        User.objects.filter(pk=self.user.pk).update(is_blocked=True)
        self.request.user = User.objects.get(pk=self.user.pk)
        self.assertFalse(IsAuthenticatedActiveUser().has_permission(self.request, None))

    def test_owner_permission_allows_owner(self) -> None:
        self.request.user = self.user
        obj = SimpleNamespace(user=self.user)
        self.assertTrue(IsOwner().has_object_permission(self.request, None, obj))

    def test_owner_permission_denies_other(self) -> None:
        self.request.user = self.user
        obj = SimpleNamespace(user=self.other)
        self.assertFalse(IsOwner().has_object_permission(self.request, None, obj))

    def test_read_methods_allowed_for_everyone(self) -> None:
        """``IsOwnerOrReadOnly`` opens reads up, ``IsOwner`` does not."""
        self.request.user = self.other
        self.request.method = "GET"
        obj = SimpleNamespace(user=self.user)
        self.assertTrue(IsOwnerOrReadOnly().has_object_permission(self.request, None, obj))
        self.assertFalse(IsOwner().has_object_permission(self.request, None, obj))

    def test_write_methods_denied_for_other(self) -> None:
        self.request.method = "PATCH"
        obj = SimpleNamespace(user=self.user)
        self.request.user = self.other
        self.assertFalse(IsOwnerOrReadOnly().has_object_permission(self.request, None, obj))
        self.request.user = self.user
        self.assertTrue(IsOwnerOrReadOnly().has_object_permission(self.request, None, obj))

    def test_user_is_blocked_error_code(self) -> None:
        self.assertEqual(UserIsBlocked().code, "user_is_blocked")
