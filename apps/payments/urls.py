"""URL configuration for the payments app."""

from __future__ import annotations

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.payments import views

app_name = "payments"

router = DefaultRouter()
router.register("payments", views.PaymentViewSet, basename="payment")

urlpatterns = [
    path("", include(router.urls)),
    path("callback/", views.PaymentCallbackView.as_view(), name="callback"),
]
