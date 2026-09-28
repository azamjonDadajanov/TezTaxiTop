"""URL configuration for the locations app."""

from __future__ import annotations

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.locations import views

app_name = "locations"

router = DefaultRouter()
router.register("regions", views.RegionViewSet, basename="region")
router.register("districts", views.DistrictViewSet, basename="district")
router.register("locations", views.LocationViewSet, basename="location")

urlpatterns = [path("", include(router.urls))]
