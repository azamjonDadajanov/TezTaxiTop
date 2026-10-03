"""Typed access to the business rule settings.

Business rules are deployment decisions, not code constants, therefore they
live in ``config/settings/base.py`` and are read here through a single typed
module. Service functions import from ``apps.core.conf`` so that a rule can be
toggled per environment without touching business code.
"""

from __future__ import annotations

from django.conf import settings

# --- Feature switches ------------------------------------------------------

#: A driver needs an active subscription to publish a new trip.
TRIP_REQUIRES_ACTIVE_SUBSCRIPTION: bool = getattr(
    settings, "TRIP_REQUIRES_ACTIVE_SUBSCRIPTION", True
)

#: Only admin-verified drivers may publish trips.
TRIP_REQUIRES_VERIFIED_DRIVER: bool = getattr(settings, "TRIP_REQUIRES_VERIFIED_DRIVER", True)

#: Only admin-verified vehicles may be used for a published trip.
TRIP_REQUIRES_VERIFIED_VEHICLE: bool = getattr(settings, "TRIP_REQUIRES_VERIFIED_VEHICLE", True)

# --- Time windows ----------------------------------------------------------

#: How many days before expiry a driver is warned about a subscription.
SUBSCRIPTION_EXPIRING_WARNING_DAYS: int = getattr(settings, "SUBSCRIPTION_EXPIRING_WARNING_DAYS", 3)

#: A passenger request older than this many hours is auto-expired.
PASSENGER_REQUEST_EXPIRY_HOURS: int = getattr(settings, "PASSENGER_REQUEST_EXPIRY_HOURS", 6)

#: A trip whose departure time passed by more than this is auto-expired.
TRIP_DEPARTURE_GRACE_MINUTES: int = getattr(settings, "TRIP_DEPARTURE_GRACE_MINUTES", 60)

#: Maximum |departure difference| considered by the matching scorer.
MATCHING_TIME_WINDOW_HOURS: int = getattr(settings, "MATCHING_TIME_WINDOW_HOURS", 6)

#: Upper bound of trips returned by `matching.services.find_matching_trips`.
MATCHING_MAX_RESULTS: int = getattr(settings, "MATCHING_MAX_RESULTS", 20)

#: Hard filter: the largest geographic difference (km) allowed between the
#: corresponding pickup / drop-off points of two routes.
MATCHING_MAX_ROUTE_DISTANCE_KM: float = float(
    getattr(settings, "MATCHING_MAX_ROUTE_DISTANCE_KM", 25)
)

#: Hard filter: how far (minutes) the trip departure may sit outside the
#: requested departure window and still count as a time match.
MATCHING_TIME_TOLERANCE_MINUTES: int = getattr(
    settings, "MATCHING_TIME_TOLERANCE_MINUTES", 60
)

# --- Driver map -------------------------------------------------------------

#: Default radius (km) of the "passengers near me" map feed.
DRIVER_MAP_RADIUS_KM: float = float(getattr(settings, "DRIVER_MAP_RADIUS_KM", 25))

#: Hard ceiling for a client supplied radius (km).
DRIVER_MAP_MAX_RADIUS_KM: float = float(getattr(settings, "DRIVER_MAP_MAX_RADIUS_KM", 50))

#: Upper bound of markers one map response may carry.
DRIVER_MAP_MAX_RESULTS: int = getattr(settings, "DRIVER_MAP_MAX_RESULTS", 120)

# --- Passenger map ---------------------------------------------------------

#: Default radius (km) of the "taxis near me" map feed.
PASSENGER_MAP_RADIUS_KM: float = float(getattr(settings, "PASSENGER_MAP_RADIUS_KM", 25))

#: Hard ceiling for a client supplied radius (km) on the passenger map.
PASSENGER_MAP_MAX_RADIUS_KM: float = float(getattr(settings, "PASSENGER_MAP_MAX_RADIUS_KM", 50))

#: Upper bound of taxi markers one passenger-map response may carry.
PASSENGER_MAP_MAX_RESULTS: int = getattr(settings, "PASSENGER_MAP_MAX_RESULTS", 120)


def require_active_subscription_to_drive() -> bool:
    """Return whether creating a trip requires an active subscription."""
    return TRIP_REQUIRES_ACTIVE_SUBSCRIPTION


def require_verified_driver_to_drive() -> bool:
    """Return whether creating a trip requires a verified driver profile."""
    return TRIP_REQUIRES_VERIFIED_DRIVER


def require_verified_vehicle_to_drive() -> bool:
    """Return whether creating a trip requires a verified, active vehicle."""
    return TRIP_REQUIRES_VERIFIED_VEHICLE
