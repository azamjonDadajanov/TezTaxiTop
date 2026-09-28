"""Object level permissions for the users app."""

from __future__ import annotations

from rest_framework import permissions


class IsSelfOrAdmin(permissions.BasePermission):
    """Read own profile, write own profile; staff can read everything."""

    message = "Faqat o'z profilini ko'rish yoki tahrirlash mumkin."

    def has_object_permission(self, request, view, obj) -> bool:
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if user.is_staff:
            return True
        return obj == user


class IsAdminOrReadOnlyUser(permissions.BasePermission):
    """Only staff may change roles, block users or verify drivers."""

    message = "Faqat administratorlar bu amalni bajarishi mumkin."

    def has_permission(self, request, view) -> bool:
        if request.method in permissions.SAFE_METHODS:
            return bool(request.user and request.user.is_authenticated)
        return bool(request.user and request.user.is_staff)
