"""URL configuration for the subscriptions app."""

from __future__ import annotations

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.subscriptions import views

app_name = "subscriptions"

router = DefaultRouter()
router.register("plans", views.SubscriptionPlanViewSet, basename="subscription-plan")
router.register("subscriptions", views.DriverSubscriptionViewSet, basename="driver-subscription")

urlpatterns = [
    path("", include(router.urls)),
    path(
        "subscriptions/<int:pk>/cancel/",
        views.CancelSubscriptionView.as_view(),
        name="cancel-subscription",
    ),
]
