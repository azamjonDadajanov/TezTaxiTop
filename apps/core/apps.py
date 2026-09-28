from __future__ import annotations

from django.apps import AppConfig


class CoreConfig(AppConfig):
    """Application config for the shared technical layer."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"
    label = "core"
    verbose_name = "Umumiy texnik qatlam"
