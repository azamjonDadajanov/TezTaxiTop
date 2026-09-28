"""URL configuration for the reviews app."""

from __future__ import annotations

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.reviews import views

app_name = "reviews"

router = DefaultRouter()
router.register("reviews", views.ReviewViewSet, basename="review")

urlpatterns = [
    path("", include(router.urls)),
    path("rating-summary/", views.RatingSummaryView.as_view(), name="rating-summary"),
]
