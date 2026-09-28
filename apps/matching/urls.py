"""URL configuration for the matching app."""

from __future__ import annotations

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.matching import views

app_name = "matching"

router = DefaultRouter()
router.register("matching/trip-requests", views.DriverTripMatchViewSet, basename="trip-match")
router.register("matching/request-trips", views.RequestTripMatchViewSet, basename="request-trip-match")

urlpatterns = [
    path("", include(router.urls)),
    path("matching/requests/<int:request_id>/trips/", views.RequestTripsRankingView.as_view(), name="request-trips"),
    path("matching/requests/<int:request_id>/refresh/", views.RefreshMatchesView.as_view(), name="request-refresh"),
    path("matching/trips/<int:trip_id>/requests/", views.TripRequestsRankingView.as_view(), name="trip-requests"),
    path("matching/weights/", views.WeightsView.as_view(), name="weights"),
]
