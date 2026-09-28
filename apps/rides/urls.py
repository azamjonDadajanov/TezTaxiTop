"""URL configuration for the rides app."""

from __future__ import annotations

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.rides import views

app_name = "rides"

router = DefaultRouter()
router.register("trips", views.DriverTripViewSet, basename="trip")
router.register("requests", views.PassengerRequestViewSet, basename="passenger-request")

urlpatterns = [path("", include(router.urls))]
