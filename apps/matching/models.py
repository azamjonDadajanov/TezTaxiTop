"""Persisted match result (one row per request/trip pair)."""

from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel


class MatchReason(models.TextChoices):
    NEW_MATCH = "new_match", "Yangi moslik"
    RESCORE = "rescore", "Qayta baholash"
    SEATS_CHANGED = "seats_changed", "O'rinlar o'zgardi"
    REACTIVATED = "reactivated", "Qayta faollashtirildi"


class TripMatch(TimeStampedModel):
    """A scored candidate trip for a passenger request.

    The numeric columns are the *components* of the final ``score`` so the UI
    (and the tests) can explain the ranking. ``MAX_TOTAL_SCORE`` is the sum of
    all weights, which keeps ``score`` inside ``0..100``.
    """

    request = models.ForeignKey(
        "rides.PassengerRequest",
        on_delete=models.CASCADE,
        related_name="matches",
        verbose_name="Yo'lovchi so'rovi",
    )
    trip = models.ForeignKey(
        "rides.DriverTrip",
        on_delete=models.CASCADE,
        related_name="matches",
        verbose_name="Yo'lov",
    )
    score = models.DecimalField(
        verbose_name="Ball",
        max_digits=5,
        decimal_places=2,
        help_text="0 dan 100 gacha.",
    )
    time_score = models.DecimalField(verbose_name="Vaqt bali", max_digits=5, decimal_places=2, default=0)
    price_score = models.DecimalField(verbose_name="Narx bali", max_digits=5, decimal_places=2, default=0)
    rating_score = models.DecimalField(verbose_name="Reyting bali", max_digits=5, decimal_places=2, default=0)
    subscription_score = models.DecimalField(
        verbose_name="Obuna bali", max_digits=5, decimal_places=2, default=0
    )
    vehicle_score = models.DecimalField(verbose_name="Avtomobil bali", max_digits=5, decimal_places=2, default=0)
    minutes_difference = models.IntegerField(
        verbose_name="Vaqt farqi (daqiqa)",
        default=0,
        help_text="So'rov oynaning boshlanishi va yo'lov chuqishi o'rtasidagi farq.",
    )
    price_difference = models.DecimalField(
        verbose_name="Narx farqi",
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text="Yo'lov narxi - so'rovdagi maksimal narx (manfiy = qimmatroq emas).",
    )
    reason = models.CharField(
        verbose_name="Sabab",
        max_length=20,
        choices=MatchReason.choices,
        default=MatchReason.NEW_MATCH,
    )
    rank = models.PositiveSmallIntegerField(
        verbose_name="O'rin",
        default=0,
        help_text="Shu so'rov bo'yicha reytingdagi o'rni (1 - eng yaxshi).",
    )

    class Meta:
        verbose_name = "Moslik"
        verbose_name_plural = "Mosliklar"
        ordering = ("-score", "trip__departure_time", "trip_id")
        indexes = [
            models.Index(fields=("request", "-score"), name="match_request_score_idx"),
            models.Index(fields=("trip",), name="match_trip_idx"),
            models.Index(fields=("request", "rank"), name="match_request_rank_idx"),
        ]
        constraints = [
            models.UniqueConstraint(fields=("request", "trip"), name="uniq_match_per_request_trip"),
            models.CheckConstraint(condition=models.Q(score__gte=0) & models.Q(score__lte=100), name="match_score_0_100"),
        ]

    def __str__(self) -> str:
        return f"Match r{self.request_id}-t{self.trip_id}: {self.score}"

    # -- helpers -------------------------------------------------------------
    @property
    def components(self) -> dict:
        """The score breakdown, handy for the API and the bot."""
        return {
            "time": self.time_score,
            "price": self.price_score,
            "rating": self.rating_score,
            "subscription": self.subscription_score,
            "vehicle": self.vehicle_score,
        }

    def top_reasons(self) -> list[str]:
        """Human readable explanation of the strongest components."""
        labels = {
            "time": "Chuqish vaqti yaqin",
            "price": "Narx qulay",
            "rating": "Yuqori reyting",
            "subscription": "Faol obuna",
            "vehicle": "Ishonchli avtomobil",
        }
        ordered = sorted(self.components.items(), key=lambda item: item[1], reverse=True)
        return [labels[name] for name, value in ordered if value and value > 0][:2]
