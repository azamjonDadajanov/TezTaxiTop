"""Domain constants for the rides app."""

from __future__ import annotations

from decimal import Decimal

#: Money precision for trip prices.
MONEY_MAX_DIGITS = 12
MONEY_DECIMAL_PLACES = 2

#: A trip may offer at most this many seats (comfort van upper bound).
MAX_SEATS_PER_TRIP = 16

#: Minimum seconds between a trip departure and "now" when creating a trip.
MIN_DEPARTURE_LEAD_SECONDS = 600  # 10 minutes

#: Statuses in which a trip still accepts new orders.
BOOKABLE_TRIP_STATUSES: frozenset[str] = frozenset({"active"})

#: Statuses in which a trip is considered finished (no further writes).
TERMINAL_TRIP_STATUSES: frozenset[str] = frozenset({"completed", "cancelled", "expired"})

#: Statuses in which a passenger request can still be matched.
MATCHABLE_REQUEST_STATUSES: frozenset[str] = frozenset({"active"})

#: Free seats threshold that turns a trip into ``FULL`` automatically.
ZERO_SEATS = Decimal("0")
