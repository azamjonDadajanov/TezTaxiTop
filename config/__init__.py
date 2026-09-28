"""Config package.

Importing the Celery application here guarantees that ``@shared_task``
decorators bind to the correct app as soon as Django starts.
"""

from __future__ import annotations

from config.celery import app as celery_app

__all__ = ("celery_app",)
