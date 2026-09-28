"""States for passenger ride request flow."""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class PassengerRequestStates(StatesGroup):
    """States for passenger ride request FSM."""

    waiting_for_origin = State()
    waiting_for_destination = State()
    waiting_for_passenger_count = State()
    waiting_for_departure_date = State()
    waiting_for_departure_time = State()
    waiting_for_max_price = State()
    waiting_for_comment = State()
    waiting_for_confirmation = State()