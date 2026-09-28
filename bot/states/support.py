"""States for support ticket creation."""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class SupportStates(StatesGroup):
    """States for support ticket creation."""

    waiting_for_subject = State()
    waiting_for_message = State()