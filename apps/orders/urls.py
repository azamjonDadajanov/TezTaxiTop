"""URL configuration for the orders app."""

from __future__ import annotations

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.orders import views

app_name = "orders"

router = DefaultRouter()
router.register("orders", views.OrderViewSet, basename="order")

urlpatterns = [
    path("", include(router.urls)),
    path(
        "reviewable-orders/",
        views.ReviewableOrdersView.as_view(),
        name="reviewable-orders",
    ),
]
