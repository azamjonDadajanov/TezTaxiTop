"""FSM states for editing account profile details."""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class ProfileStates(StatesGroup):
    waiting_for_name = State()
    waiting_for_phone = State()
