"""REST API views for the matching app.

The matcher itself lives in :mod:`apps.matching.services`; these views are thin
adapters. Two audiences are supported:

* a **driver** asking "which requests match my trip?",
* a **passenger** asking "which trips match my request, in which order?".
"""

from __future__ import annotations

from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import mixins, viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.matching import selectors as matching_selectors
from apps.matching import services as matching_services
from apps.matching.serializers import (
    MatchingWeightsSerializer,
    RankedRequestsResponseSerializer,
    RankedTripsResponseSerializer,
    RefreshMatchesResponseSerializer,
    TripMatchSerializer,
)
from apps.rides import selectors as ride_selectors


@extend_schema_view(
    list=extend_schema(
        summary="Mening mosliklarim (haydovchi)",
        description="Faol yo'lovlarim uchun topilgan so'rovlar, ball bo'yicha tartiblangan.",
        responses={200: TripMatchSerializer(many=True)},
    ),
    retrieve=extend_schema(summary="Moslik", responses={200: TripMatchSerializer}),
)
class DriverTripMatchViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = TripMatchSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "head", "options"]
    filterset_fields = ["trip"]

    def get_queryset(self):
        driver = getattr(self.request.user, "driver_profile", None)
        if driver is None:
            return matching_selectors.get_match_queryset().none()
        return matching_selectors.get_match_queryset().filter(trip__driver=driver).order_by(
            "trip__departure_time", "-score"
        )


@extend_schema_view(
    list=extend_schema(
        summary="Mening mos so'rovlarim (yo'lovchi)",
        description="So'rovlarim uchun topilgan yo'lovlar, ball bo'yicha tartiblangan.",
        responses={200: TripMatchSerializer(many=True)},
    )
)
class RequestTripMatchViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = TripMatchSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "head", "options"]
    filterset_fields = ["request"]

    def get_queryset(self):
        return matching_selectors.get_match_queryset().filter(
            request__passenger=self.request.user
        ).order_by("rank", "-score", "trip__departure_time")


class RequestTripsRankingView(APIView):
    """``GET /api/v1/matching/requests/<request_id>/trips/`` - ranked trips."""

    permission_classes = [IsAuthenticated]
    serializer_class = RankedTripsResponseSerializer

    @extend_schema(
        summary="So'rov uchun mos yo'lovlar (Reyting bo'yicha)",
        description="Yo'lovchi o'z so'rovi bo'yicha eng mos yo'lovlarni ball kamayish tartibida oladi.",
        responses={200: RankedTripsResponseSerializer},
    )
    def get(self, request, request_id: int) -> Response:
        passenger_request = matching_services.get_required_request(request_id)
        if passenger_request.passenger_id != request.user.pk and not request.user.is_staff:
            raise PermissionDenied("Bu so'rovga kirish huquqingiz yo'q.")
        matches = matching_services.get_ranked_matches(passenger_request)
        return Response(
            {
                "request_id": passenger_request.pk,
                "max_score": str(matching_services.MAX_SCORE),
                "results": TripMatchSerializer(matches, many=True, context={"request": request}).data,
            }
        )


class TripRequestsRankingView(APIView):
    """``GET /api/v1/matching/trips/<trip_id>/requests/`` - ranked requests."""

    permission_classes = [IsAuthenticated]
    serializer_class = RankedRequestsResponseSerializer

    @extend_schema(
        summary="Yo'lov uchun mos so'rovlar (Reyting bo'yicha)",
        description="Haydovchi o'z yo'lovi bo'yicha mos so'rovlarni ball kamayish tartibida oladi.",
        responses={200: RankedRequestsResponseSerializer},
    )
    def get(self, request, trip_id: int) -> Response:
        trip = ride_selectors.get_trip_by_id(trip_id)
        if trip is None:
            from apps.core.exceptions import ResourceNotFound

            raise ResourceNotFound("Yo'lov topilmadi.")
        if not request.user.is_staff:
            driver = getattr(request.user, "driver_profile", None)
            if driver is None or driver.pk != trip.driver_id:
                raise PermissionDenied("Bu yo'lovga kirish huquqingiz yo'q.")

        matches = matching_selectors.get_match_queryset().filter(trip=trip).order_by(
            "-score", "request__departure_from"
        )
        return Response(
            {
                "trip_id": trip.pk,
                "max_score": str(matching_services.MAX_SCORE),
                "results": TripMatchSerializer(matches, many=True, context={"request": request}).data,
            }
        )


class RefreshMatchesView(APIView):
    """Force a rescore (driver for a trip, passenger for a request)."""

    permission_classes = [IsAuthenticated]
    serializer_class = RefreshMatchesResponseSerializer

    @extend_schema(
        summary="So'rovni qayta baholash",
        description="So'rov uchun mos yo'lovlarni shu zahoti qayta hisoblaydi.",
        request=None,
        responses={200: RefreshMatchesResponseSerializer},
    )
    def post(self, request, request_id: int) -> Response:
        passenger_request = matching_services.get_required_request(request_id)
        if passenger_request.passenger_id != request.user.pk and not request.user.is_staff:
            raise PermissionDenied("Bu so'rovni qayta baholash huquqingiz yo'q.")
        matches = matching_services.refresh_matches_for_request(passenger_request)
        return Response({"refreshed": len(matches)})

    @extend_schema(
        summary="Yo'lovni qayta baholash",
        description="Yo'lovga mos so'rovlarni shu zahoti qayta hisoblaydi.",
        request=None,
        responses={200: RefreshMatchesResponseSerializer},
    )
    def post_trip(self, request, trip_id: int) -> Response:  # pragma: no cover - helper
        trip = ride_selectors.get_trip_by_id(trip_id)
        if trip is None:
            from apps.core.exceptions import ResourceNotFound

            raise ResourceNotFound("Yo'lov topilmadi.")
        driver = getattr(request.user, "driver_profile", None)
        if driver is None or driver.pk != trip.driver_id:
            raise PermissionDenied("Bu yo'lovni qayta baholash huquqingiz yo'q.")
        matches = matching_services.refresh_matches_for_trip(trip)
        return Response({"refreshed": len(matches)})


class WeightsView(APIView):
    """Expose the scoring weights so the UI can explain the ranking."""

    permission_classes = [IsAuthenticated]
    serializer_class = MatchingWeightsSerializer

    @extend_schema(
        summary="Reyting vazn'lari",
        description="Reyting qanday hisoblanishini tushuntirish uchun vaznlar.",
        responses={200: MatchingWeightsSerializer},
    )
    def get(self, request) -> Response:
        return Response(
            {
                "time": str(matching_services.WEIGHT_TIME),
                "price": str(matching_services.WEIGHT_PRICE),
                "rating": str(matching_services.WEIGHT_RATING),
                "subscription": str(matching_services.WEIGHT_SUBSCRIPTION),
                "vehicle": str(matching_services.WEIGHT_VEHICLE),
                "max_score": str(matching_services.MAX_SCORE),
            }
        )
