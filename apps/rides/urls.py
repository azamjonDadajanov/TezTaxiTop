"""URL configuration for the rides app."""

from __future__ import annotations

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.rides import views

app_name = "rides"

router = DefaultRouter()
router.register("trips", views.DriverTripViewSet, basename="trip")
router.register("requests", views.PassengerRequestViewSet, basename="passenger-request")

urlpatterns = [
    # Declared before the router: the router's detail route matches any
    # non-slash segment, so `requests/nearby/` would otherwise be read as a
    # request id and answered with a 404.
    path("requests/nearby/", views.NearbyPassengerRequestsView.as_view(), name="nearby-requests"),
    path("trips/nearby/", views.NearbyDriverTripsView.as_view(), name="nearby-trips"),
    path("", include(router.urls)),
]
