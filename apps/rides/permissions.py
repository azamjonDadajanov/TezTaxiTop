"""Object level permissions for the rides app."""

from __future__ import annotations

from rest_framework import permissions

from apps.rides.models import DriverTrip, PassengerRequest


class IsTripDriver(permissions.BasePermission):
    """Only the driver who published the trip may modify it."""

    message = "Faqat bu yo'lovni yaratgan haydovchi o'zgartirishi mumkin."

    def has_object_permission(self, request, view, obj: DriverTrip) -> bool:
        if request.method in permissions.SAFE_METHODS:
            return True
        if request.user.is_staff:
            return True
        driver_profile = getattr(request.user, "driver_profile", None)
        return driver_profile is not None and driver_profile.pk == obj.driver_id


class IsPassengerRequestOwner(permissions.BasePermission):
    """Only the passenger who created the request may modify it."""

    message = "Faqat so'rovni yaratgan yo'lovchi o'zgartirishi mumkin."

    def has_object_permission(self, request, view, obj: PassengerRequest) -> bool:
        if request.method in permissions.SAFE_METHODS:
            return True
        if request.user.is_staff:
            return True
        return obj.passenger_id == request.user.pk
