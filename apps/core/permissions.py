"""Reusable DRF permission classes.

Object level checks are implemented here so that a view can never forget them:
every queryset that exposes user data is already filtered in ``get_queryset`` and
these classes add the final ``has_object_permission`` guard.
"""

from __future__ import annotations

from rest_framework import permissions


class IsAuthenticatedActiveUser(permissions.BasePermission):
    """Authenticated, not blocked user."""

    message = "Faqat tizimga kirgan foydalanuvchilar uchun."

    def has_permission(self, request, view) -> bool:
        user = request.user
        return bool(user and user.is_authenticated and user.is_active and not getattr(user, "is_blocked", False))


class IsOwner(permissions.BasePermission):
    """Strict object level owner check (supports custom owner field names).

    Only the owner passes - for safe *and* unsafe methods. Use it for resources
    that are private to a single account (a profile, a private thread, ...).
    For public-but-owner-editable resources use :class:`IsOwnerOrReadOnly`.
    """

    message = "Bu resursga faqat egasi kirishi mumkin."

    owner_field = "user"

    def has_object_permission(self, request, view, obj) -> bool:
        return getattr(obj, self.owner_field, None) == request.user


class IsOwnerOrReadOnly(IsOwner):
    """Anyone authenticated may read, only the owner may write.

    The queryset of the view is expected to be already scoped, so this class is
    the final guard for the write operations.
    """

    message = "Faqat resurs egasi o'zgartirishi mumkin."

    def has_object_permission(self, request, view, obj) -> bool:
        if request.method in permissions.SAFE_METHODS:
            return True
        return getattr(obj, self.owner_field, None) == request.user


class IsAdminOrReadOnly(permissions.BasePermission):
    """Read for everybody authenticated, write for staff only."""

    message = "Faqat administratorlar o'zgartirishi mumkin."

    def has_permission(self, request, view) -> bool:
        if request.method in permissions.SAFE_METHODS:
            return True
        return bool(request.user and request.user.is_staff)

    def has_object_permission(self, request, view, obj) -> bool:
        return self.has_permission(request, view)


class IsAdminOrOwner(permissions.BasePermission):
    """Staff may write anything, everybody else only their own objects.

    Used for resources that are created by regular users (vehicles, payments,
    support tickets ...) but may also be corrected by an administrator. The
    queryset of the view is expected to be already filtered, so this class is
    the final guard.
    """

    message = "Faqat resurs egasi yoki administrator o'zgartirishi mumkin."

    owner_field = "user"

    def has_permission(self, request, view) -> bool:
        if not (request.user and request.user.is_authenticated):
            return False
        if request.method in permissions.SAFE_METHODS:
            return True
        return bool(request.user.is_staff)

    def has_object_permission(self, request, view, obj) -> bool:
        if request.method in permissions.SAFE_METHODS:
            return True
        if request.user.is_staff:
            return True
        owner = getattr(obj, self.owner_field, None)
        if self.owner_field == "driver":
            driver = getattr(request.user, "driver_profile", None)
            return driver is not None and driver.pk == obj.driver_id
        return owner == request.user


class IsDriver(permissions.BasePermission):
    """The caller must own a ``DriverProfile``."""

    message = "Bu amal faqat haydovchilar uchun."

    def has_permission(self, request, view) -> bool:
        user = request.user
        return bool(user and user.is_authenticated and hasattr(user, "driver_profile"))


class IsVerifiedDriver(permissions.BasePermission):
    """The caller must own a verified ``DriverProfile``."""

    message = "Faqat tasdiqlangan haydovchilar uchun."

    def has_permission(self, request, view) -> bool:
        user = request.user
        return bool(user and user.is_authenticated and getattr(user.driver_profile, "is_verified", False))


class ReadOnly(permissions.BasePermission):
    """Explicitly read-only endpoint (catalogue data)."""

    message = "Bu resurs faqat o'qish uchun."

    def has_permission(self, request, view) -> bool:
        return request.method in permissions.SAFE_METHODS
