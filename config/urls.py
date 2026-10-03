"""Root URL configuration.

The public API lives under ``/api/v1/``. Each Django app owns its own
``urls.py`` so that URL names stay unique and are prefixed by application
(``trips:detail``, ``orders:create`` ...).
"""

from __future__ import annotations

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)

admin.site.site_header = "TezTaxiTop boshqaruv paneli"
admin.site.site_title = "TezTaxiTop Admin"
admin.site.index_title = "Platformani boshqarish"

api_v1_patterns = [
    path("auth/", include("apps.users.urls_auth")),
    path("", include("apps.users.urls")),
    path("vehicles/", include("apps.vehicles.urls")),
    path("locations/", include("apps.locations.urls")),
    path("rides/", include("apps.rides.urls")),
    path("orders/", include("apps.orders.urls")),
    path("subscriptions/", include("apps.subscriptions.urls")),
    path("payments/", include("apps.payments.urls")),
    path("reviews/", include("apps.reviews.urls")),
    path("chat/", include("apps.chat.urls")),
    path("notifications/", include("apps.notifications.urls")),
    path("support/", include("apps.support.urls")),
    # This app owns its own prefix: its ``urls.py`` already declares
    # ``matching/...`` (and the router registers ``matching/trip-requests``),
    # so it is mounted at the root like ``apps.users.urls``. Mounting it under
    # another ``matching/`` would put every route behind a doubled
    # ``/api/v1/matching/matching/...`` that neither the frontend nor the
    # documented endpoints call.
    path("", include("apps.matching.urls")),
]

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include((api_v1_patterns, "api"), namespace="api")),
    # --- API documentation -------------------------------------------------
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
    path(
        "api/redoc/",
        SpectacularRedocView.as_view(url_name="schema"),
        name="redoc",
    ),
    path("api-auth/", include("rest_framework.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
