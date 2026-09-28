"""URL configuration for the users app."""

from __future__ import annotations

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.users import views

app_name = "users"

router = DefaultRouter()
router.register("users", views.UserViewSet, basename="user")
router.register("drivers", views.DriverProfileViewSet, basename="driver-profile")

urlpatterns = [
    path("", include(router.urls)),
    path("become-driver/", views.BecomeDriverView.as_view(), name="become-driver"),
    path("my-driver-profile/", views.MyDriverProfileView.as_view(), name="my-driver-profile"),
]
