"""Celery application for TezTaxiTop.

The Celery app is configured in :mod:`config.settings` and autoloads every
``tasks.py`` module inside the project. It is intentionally decoupled from the
Telegram bot: tasks only touch the Django service layer.
"""

from __future__ import annotations

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")

app = Celery("taxitop")

# All Celery options live in Django settings under the CELERY_ namespace.
app.config_from_object("django.conf:settings", namespace="CELERY")

# Discover `tasks.py` in every installed application.
app.autodiscover_tasks()


@app.task(bind=True, ignore_result=True)
def debug_task(self) -> str:  # pragma: no cover - operational helper
    """Print the request payload - useful to verify worker connectivity."""
    return f"Request: {self.request!r}"
