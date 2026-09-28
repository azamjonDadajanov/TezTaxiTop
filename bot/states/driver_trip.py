"""States for driver trip creation flow."""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class DriverTripStates(StatesGroup):
    """States for driver trip creation FSM."""

    waiting_for_vehicle = State()
    waiting_for_origin = State()
    waiting_for_destination = State()
    waiting_for_departure_datetime = State()
    waiting_for_seats = State()
    waiting_for_price = State()
    waiting_for_comment = State()
    waiting_for_confirmation = State()