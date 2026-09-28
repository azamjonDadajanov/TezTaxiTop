"""Order domain constants."""

from __future__ import annotations

from decimal import Decimal

MONEY_MAX_DIGITS = 12
MONEY_DECIMAL_PLACES = 2
ZERO = Decimal("0.00")

#: Maximum seats a single passenger may book on one trip.
MAX_SEATS_PER_ORDER = 8

#: Legal order state machine. Every transition must appear here, otherwise
#: `apps.orders.services` refuses the change with `InvalidOrderTransition`.
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "pending": frozenset(
        {
            "accepted",
            "rejected",
            "cancelled_by_passenger",
            "cancelled_by_driver",
        }
    ),
    "accepted": frozenset(
        {
            "driver_arrived",
            "in_progress",
            "cancelled_by_passenger",
            "cancelled_by_driver",
            "no_show",
        }
    ),
    "driver_arrived": frozenset({"in_progress", "no_show", "cancelled_by_driver"}),
    "in_progress": frozenset({"completed"}),
    "completed": frozenset(),
    "rejected": frozenset(),
    "cancelled_by_passenger": frozenset(),
    "cancelled_by_driver": frozenset(),
    "no_show": frozenset(),
}

#: Statuses in which the booked seats are held against the trip counter.
SEAT_HOLDING_STATUSES: frozenset[str] = frozenset(
    {"accepted", "driver_arrived", "in_progress"}
)

#: Statuses that end the order for good.
TERMINAL_STATUSES: frozenset[str] = frozenset(
    {
        "completed",
        "rejected",
        "cancelled_by_passenger",
        "cancelled_by_driver",
        "no_show",
    }
)

#: Statuses where the passenger may still cancel.
CANCELLABLE_BY_PASSENGER: frozenset[str] = frozenset({"pending", "accepted"})

#: Statuses where the driver may still cancel.
CANCELLABLE_BY_DRIVER: frozenset[str] = frozenset({"pending", "accepted"})

#: Statuses in which the driver and the passenger may exchange messages.
CHAT_ALLOWED_ORDER_STATUSES: frozenset[str] = frozenset(
    {"pending", "accepted", "driver_arrived", "in_progress"}
)
