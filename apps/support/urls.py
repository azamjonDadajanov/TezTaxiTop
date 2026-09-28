"""URL configuration for the support app."""

from __future__ import annotations

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.support import views

app_name = "support"

router = DefaultRouter()
router.register("support", views.SupportTicketViewSet, basename="support-ticket")

urlpatterns = [
    path("", include(router.urls)),
    path("support/<int:ticket_id>/messages/", views.SupportMessageView.as_view(), name="ticket-messages"),
    path("support/stats/", views.SupportStatsView.as_view(), name="stats"),
]
