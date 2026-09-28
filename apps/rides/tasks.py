"""Celery tasks for the rides app (expiring stale trips and requests)."""

from __future__ import annotations

import logging

from celery import shared_task

from apps.rides import services as ride_services

logger = logging.getLogger(__name__)


@shared_task(name="apps.rides.tasks.expire_trips_task")
def expire_trips_task() -> dict:
    """Hourly: expire trips whose departure time has passed.

    Idempotent - only trips that are still ``draft``/``active``/``full`` are
    touched, so a second run in the same hour returns ``0``.
    """
    expired = ride_services.expire_trips()
    logger.info("Muddati tugagan yo'lovlar soni: %s", expired)
    return {"expired": expired}


@shared_task(name="apps.rides.tasks.expire_passenger_requests_task")
def expire_passenger_requests_task() -> dict:
    """Hourly: expire passenger requests nobody acted on."""
    expired = ride_services.expire_passenger_requests()
    logger.info("Muddati tugagan so'rovlar soni: %s", expired)
    return {"expired": expired}
