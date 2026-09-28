"""URL configuration for the vehicles app."""

from __future__ import annotations

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.vehicles import views

app_name = "vehicles"

router = DefaultRouter()
router.register("vehicles", views.VehicleViewSet, basename="vehicle")

urlpatterns = [path("", include(router.urls))]
