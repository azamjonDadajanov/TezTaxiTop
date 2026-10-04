"""FSM states for the post-trip review / rating flow."""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class ReviewStates(StatesGroup):
    """After selecting a star rating, the user is asked for an optional comment."""

    waiting_for_comment = State()
