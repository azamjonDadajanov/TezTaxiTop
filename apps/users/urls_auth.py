"""URL configuration for authentication endpoints."""

from __future__ import annotations

from django.urls import path

from apps.users import views_auth

app_name = "auth"

urlpatterns = [
    path("telegram-mini-app/", views_auth.telegram_mini_app_auth, name="telegram-mini-app-auth"),
    # Keep the old path, but it now accepts signed initData rather than a raw Telegram ID.
    path("register-telegram/", views_auth.telegram_mini_app_auth, name="register-telegram"),
    path("me/", views_auth.me, name="me"),
    path("me/role/", views_auth.set_role, name="set-role"),
]
