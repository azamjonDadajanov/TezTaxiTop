"""Celery tasks that keep the matching ranking fresh."""

from __future__ import annotations

import logging

from celery import shared_task

from apps.matching import services as matching_services
from apps.matching.models import MatchReason

logger = logging.getLogger(__name__)


@shared_task(name="apps.matching.tasks.refresh_all_matches_task")
def refresh_all_matches_task() -> dict:
    """Recompute the ranking of every still relevant passenger request.

    Idempotent: rescoring an unchanged situation rewrites the same values.
    """
    result = matching_services.refresh_all_active_matches()
    logger.info("Mosliklar yangilandi: %s", result)
    return result


@shared_task(name="apps.matching.tasks.refresh_request_matches_task")
def refresh_request_matches_task(request_id: int) -> dict:
    """Rescore one request (called when a new trip appears)."""
    passenger_request = matching_services.get_required_request(request_id)
    matches = matching_services.refresh_matches_for_request(
        passenger_request, reason=MatchReason.NEW_MATCH
    )
    return {"request_id": request_id, "matches": len(matches)}


@shared_task(name="apps.matching.tasks.refresh_trip_matches_task")
def refresh_trip_matches_task(trip_id: int) -> dict:
    """Rescore one trip against the active requests."""
    from apps.rides.selectors import get_trip_by_id

    trip = get_trip_by_id(trip_id)
    if trip is None:
        return {"trip_id": trip_id, "matches": 0, "reason": "not_found"}
    matches = matching_services.refresh_matches_for_trip(trip, reason=MatchReason.NEW_MATCH)
    return {"trip_id": trip_id, "matches": len(matches)}
