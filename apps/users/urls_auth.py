"""URL configuration for authentication endpoints."""

from __future__ import annotations

from django.urls import path

from apps.users import views_auth

app_name = "auth"

urlpatterns = [
    path("register-telegram/", views_auth.register_telegram, name="register-telegram"),
    path("me/", views_auth.me, name="me"),
    path("me/role/", views_auth.set_role, name="set-role"),
]
