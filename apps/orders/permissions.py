"""Object level permissions for the orders app."""

from __future__ import annotations

from rest_framework import permissions

from apps.orders.models import Order


class IsOrderParticipant(permissions.BasePermission):
    """Only the passenger or the driver of the order may see/change it.

    This is the single place where "who belongs to this order" is decided, so
    neither the chat, the reviews nor the order API can leak another user's
    data.
    """

    message = "Bu buyurtmaga kirish huquqingiz yo'q."

    def has_object_permission(self, request, view, obj: Order) -> bool:
        return obj.is_participant(request.user)


class IsOrderDriver(IsOrderParticipant):
    """Driver side only (accept / reject / arrive / start / complete)."""

    message = "Bu amal faqat buyurtmaning haydovchisi uchun."

    def has_object_permission(self, request, view, obj: Order) -> bool:
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if user.is_staff:
            return True
        driver_profile = getattr(user, "driver_profile", None)
        return driver_profile is not None and driver_profile.pk == obj.trip.driver_id


class IsOrderPassenger(IsOrderParticipant):
    """Passenger side only (create / cancel)."""

    message = "Bu amal faqat buyurtmaning yo'lovchisi uchun."

    def has_object_permission(self, request, view, obj: Order) -> bool:
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if user.is_staff:
            return True
        return obj.passenger_id == user.pk
