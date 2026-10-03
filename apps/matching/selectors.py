"""Read/query layer for the matching app."""

from __future__ import annotations

from django.db.models import QuerySet

from apps.matching.models import TripMatch


def get_match_queryset() -> QuerySet[TripMatch]:
    """Both halves of the pair in one query.

    The API renders the passenger's name and route next to the trip's, so the
    passenger, both route endpoints and the vehicle all arrive with the row -
    serialising a page of matches must not turn into one query per match.
    """
    return TripMatch.objects.select_related(
        "request",
        "request__passenger",
        "request__from_location",
        "request__to_location",
        "trip",
        "trip__driver__user",
        "trip__vehicle",
        "trip__from_location",
        "trip__to_location",
    )


def get_matches_for_request(request) -> QuerySet[TripMatch]:
    return get_match_queryset().filter(request=request)


def get_best_matches_for_request(request) -> QuerySet[TripMatch]:
    return get_matches_for_request(request).order_by("rank", "-score", "trip__departure_time")


def get_matches_for_trip(trip) -> QuerySet[TripMatch]:
    return get_match_queryset().filter(trip=trip)


def get_match_by_id(match_id: int) -> TripMatch | None:
    return get_match_queryset().filter(pk=match_id).first()


def get_request_ids_for_trip(trip) -> list[int]:
    return list(
        get_match_queryset().filter(trip=trip).values_list("request_id", flat=True)
    )
