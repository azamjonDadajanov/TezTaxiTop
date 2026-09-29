"""Business exception hierarchy.

Design decisions
----------------
* Every expected business failure is expressed as a :class:`BusinessError`
  subclass. Expected failures therefore **never** surface as HTTP 500.
* Each exception carries a stable machine readable ``code`` (used by the bot and
  by mobile clients) and an HTTP ``status_code`` used by the DRF exception
  handler.
* Services raise these exceptions; views/serializers never translate business
  rules into ad-hoc ``ValidationError`` strings.
"""

from __future__ import annotations

from typing import Any


class BusinessError(Exception):
    """Base class for every expected business failure."""

    code: str = "business_error"
    status_code: int = 400
    default_message: str = "Biznes mantiqida xatolik yuz berdi."

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message or self.default_message
        self.details = details or {}
        if code is not None:
            self.code = code
        super().__init__(self.message)

    def as_dict(self) -> dict[str, Any]:
        """Serialise the error for API and bot responses."""
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            payload["details"] = self.details
        return payload


# ---------------------------------------------------------------------------
# Generic validation / access problems
# ---------------------------------------------------------------------------
class BusinessValidationError(BusinessError):
    """Input violates a business rule that a field validator cannot express."""

    code = "validation_error"
    status_code = 400
    default_message = "Kiritilgan ma'lumotlar biznes qoidasiga mos emas."


class ResourceNotFound(BusinessError):
    """Requested object does not exist (or is hidden from the caller)."""

    code = "not_found"
    status_code = 404
    default_message = "So'ralgan ma'lumot topilmadi."


class UnauthorizedOrderAccess(BusinessError):
    """Caller is not a participant of the order / trip / conversation."""

    code = "unauthorized_order_access"
    status_code = 403
    default_message = "Bu buyurtmaga kirish huquqingiz yo'q."


class ActionNotAllowed(BusinessError):
    """The object exists but its current state forbids the requested action."""

    code = "action_not_allowed"
    status_code = 409
    default_message = "Bu amalni bajarish hozirda mumkin emas."


# ---------------------------------------------------------------------------
# Users / drivers
# ---------------------------------------------------------------------------
class UserIsBlocked(BusinessError):
    """A blocked user attempted to interact with the platform."""

    code = "user_is_blocked"
    status_code = 403
    default_message = "Hisobingiz vaqtincha bloklangan. Administratorga murojaat qiling."


class NotADriver(BusinessError):
    """The user has no ``DriverProfile`` or the wrong role."""

    code = "not_a_driver"
    status_code = 403
    default_message = "Bu amal faqat haydovchilar uchun mavjud."


class DriverNotVerified(BusinessError):
    """The driver profile has not been verified by an administrator."""

    code = "driver_not_verified"
    status_code = 403
    default_message = "Haydovchi profili hali tasdiqlanmagan."


class VehicleNotVerified(BusinessError):
    """The vehicle is inactive or not verified by an administrator."""

    code = "vehicle_not_verified"
    status_code = 409
    default_message = "Avtomobil tasdiqlanmagan yoki faol emas."


class VehicleOwnershipError(BusinessError):
    """The referenced vehicle does not belong to the driver."""

    code = "vehicle_ownership_error"
    status_code = 400
    default_message = "Bu avtomobil sizning profilga tegishli emas."


# ---------------------------------------------------------------------------
# Rides
# ---------------------------------------------------------------------------
class TripError(BusinessError):
    """Base class for trip related failures."""

    code = "trip_error"
    status_code = 400
    default_message = "Yo'lov bilan bog'liq xatolik yuz berdi."


class TripNotEditable(TripError):
    code = "trip_not_editable"
    status_code = 409
    default_message = "Bu yo'lovni hozir tahrirlash yoki bekor qilish mumkin emas."


class TripAlreadyCancelled(TripError):
    code = "trip_already_cancelled"
    status_code = 409
    default_message = "Bu yo'lov allaqachon bekor qilingan."


class TripNotActive(TripError):
    code = "trip_not_active"
    status_code = 409
    default_message = "Faqat faol yo'lovlarga buyurtma berish mumkin."


class TripIsFull(TripError):
    code = "trip_is_full"
    status_code = 409
    default_message = "Yo'lovdagi barcha o'rinlar band."


class TripAlreadyCompleted(TripError):
    code = "trip_already_completed"
    status_code = 409
    default_message = "Yo'lov allaqachon yakunlangan."


class InsufficientSeats(TripError):
    code = "insufficient_seats"
    status_code = 409
    default_message = "Yetarli bo'sh o'rin mavjud emas."


class PassengerRequestError(BusinessError):
    code = "passenger_request_error"
    status_code = 400
    default_message = "Yo'lov so'rovi bilan bog'liq xatolik."


class PassengerRequestNotActive(PassengerRequestError):
    code = "passenger_request_not_active"
    status_code = 409
    default_message = "Faqat faol so'rovlarni moslashtirish mumkin."


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------
class InvalidOrderState(BusinessError):
    """The order is not in a state that allows the requested transition."""

    code = "invalid_order_state"
    status_code = 409
    default_message = "Buyurtma joriy holati bu amalni qo'llab-quvvatlamaydi."


class InvalidOrderTransition(InvalidOrderState):
    code = "invalid_order_transition"
    default_message = "Buyurtma holatidan bu holatga o'tish mumkin emas."


class OrderNotFound(ResourceNotFound):
    code = "order_not_found"
    default_message = "Buyurtma topilmadi."


class OrderAlreadyCancelled(InvalidOrderState):
    code = "order_already_cancelled"
    default_message = "Buyurtma allaqachon bekor qilingan."


class DriverCannotBookOwnTrip(BusinessError):
    code = "driver_cannot_book_own_trip"
    status_code = 400
    default_message = "Haydovchi o'z yo'loviga buyurtma bera olmaydi."


# ---------------------------------------------------------------------------
# Subscriptions
# ---------------------------------------------------------------------------
class SubscriptionRequired(BusinessError):
    code = "subscription_required"
    status_code = 402
    default_message = "Yo'lov yaratish uchun faol obuna kerak."


class InvalidSubscription(BusinessError):
    code = "invalid_subscription"
    status_code = 400
    default_message = "Obuna holati yoki muddati noto'g'ri."


class ActiveSubscriptionAlreadyExists(InvalidSubscription):
    code = "active_subscription_already_exists"
    default_message = "Bu haydovchida allaqachon faol obuna mavjud."


class SubscriptionNotFound(ResourceNotFound):
    code = "subscription_not_found"
    default_message = "Obuna topilmadi."


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------
class PaymentError(BusinessError):
    code = "payment_error"
    status_code = 400
    default_message = "To'lov bilan bog'liq xatolik yuz berdi."


class PaymentAlreadyProcessed(PaymentError):
    """The payment already reached a final state - webhook replay."""

    code = "payment_already_processed"
    status_code = 409
    default_message = "To'lov allaqachon qayta ishlangan."


class PaymentNotFound(ResourceNotFound):
    code = "payment_not_found"
    default_message = "To'lov topilmadi."


class PaymentVerificationFailed(PaymentError):
    code = "payment_verification_failed"
    status_code = 400
    default_message = "To'lov tasdiqlanmadi."


class PaymentProviderNotConfigured(PaymentError):
    code = "payment_provider_not_configured"
    status_code = 503
    default_message = "To'lov provayderi sozlanmagan."


# ---------------------------------------------------------------------------
# Reviews
# ---------------------------------------------------------------------------
class InvalidReview(BusinessError):
    code = "invalid_review"
    status_code = 400
    default_message = "Baholash shartlari bajarilmadi."


class DuplicateReview(InvalidReview):
    code = "duplicate_review"
    status_code = 409
    default_message = "Siz bu buyurtma bo'yicha ushbu shaxsni allaqachon baholagansiz."


class ReviewNotAllowed(InvalidReview):
    code = "review_not_allowed"
    status_code = 403
    default_message = "Faqat yakunlangan buyurtma ishtirokchilari baho qo'yishi mumkin."


# ---------------------------------------------------------------------------
# Chat / notifications / support
# ---------------------------------------------------------------------------
class MessageNotAllowed(BusinessError):
    code = "message_not_allowed"
    status_code = 403
    default_message = "Bu suhbatga xabar yuborish huquqingiz yo'q."


class UnauthorizedChatAccess(MessageNotAllowed):
    code = "unauthorized_chat_access"
    default_message = "Bu suhbatga faqat ishtirokchilar kirishi mumkin."


class ChatClosed(BusinessError):
    code = "chat_closed"
    status_code = 409
    default_message = "Suhbat yopilgan, yangi xabar yuborib bo'lmaydi."


class EmptyMessage(BusinessError):
    code = "empty_message"
    status_code = 400
    default_message = "Xabar matni bo'sh bo'lishi mumkin emas."


class TicketClosed(BusinessError):
    code = "ticket_closed"
    status_code = 409
    default_message = "Murojaat yopilgan. Yopilishidan oldin xabar yuboring."


class SupportTicketClosed(TicketClosed):
    code = "support_ticket_closed"
    default_message = "Murojaat yopilgan. Yopilishidan oldin xabar yuboring."


# ---------------------------------------------------------------------------
# Geo / 2GIS Places API
# ---------------------------------------------------------------------------
class GeoProviderNotConfigured(BusinessError):
    """The 2GIS API key (or project region id) is missing from the settings."""

    code = "geo_provider_not_configured"
    status_code = 503
    default_message = "Xarita xizmati sozlanmagan. Iltimos, keyinroq urinib ko'ring."


class GeoProviderUnavailable(BusinessError):
    """2GIS was reachable in principle but did not answer usefully.

    Raised on transport errors, non-200 responses, malformed payloads and rate
    limits. Callers should degrade gracefully (for example: accept the raw
    coordinates and let the user type the address) instead of failing the whole
    trip submission.
    """

    code = "geo_provider_unavailable"
    status_code = 502
    default_message = "Xarita xizmatiga ulanib bo'lmadi. Iltimos, qayta urinib ko'ring."


class PlaceNotResolved(BusinessError):
    """Coordinates could not be translated into an address / administrative area."""

    code = "place_not_resolved"
    status_code = 422
    default_message = "Bu nuqtani manzilga aniqlab bo'lmadi. Manzilni qo'lda kiriting."


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------
class NoMatchingTrips(BusinessError):
    code = "no_matching_trips"
    status_code = 404
    default_message = "Hozircha mos yo'lovlar topilmadi."


class MatchNotFound(ResourceNotFound):
    code = "match_not_found"
    default_message = "Moslik yozuvi topilmadi."


__all__ = [
    "ActionNotAllowed",
    "ActiveSubscriptionAlreadyExists",
    "BusinessError",
    "BusinessValidationError",
    "ChatClosed",
    "EmptyMessage",
    "DriverCannotBookOwnTrip",
    "DriverNotVerified",
    "DuplicateReview",
    "GeoProviderNotConfigured",
    "GeoProviderUnavailable",
    "InsufficientSeats",
    "InvalidOrderState",
    "InvalidOrderTransition",
    "InvalidReview",
    "InvalidSubscription",
    "MatchNotFound",
    "MessageNotAllowed",
    "NoMatchingTrips",
    "NotADriver",
    "OrderAlreadyCancelled",
    "OrderNotFound",
    "PassengerRequestError",
    "PassengerRequestNotActive",
    "PaymentAlreadyProcessed",
    "PaymentError",
    "PaymentNotFound",
    "PaymentProviderNotConfigured",
    "PaymentVerificationFailed",
    "PlaceNotResolved",
    "ResourceNotFound",
    "ReviewNotAllowed",
    "SubscriptionNotFound",
    "SubscriptionRequired",
    "SupportTicketClosed",
    "TicketClosed",
    "TripAlreadyCancelled",
    "TripAlreadyCompleted",
    "TripError",
    "TripIsFull",
    "TripNotActive",
    "TripNotEditable",
    "UnauthorizedChatAccess",
    "UnauthorizedOrderAccess",
    "UserIsBlocked",
    "VehicleNotVerified",
    "VehicleOwnershipError",
]
