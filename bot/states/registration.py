"""FSM states for registration flow."""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class RegistrationStates(StatesGroup):
    """States for user registration."""

    waiting_for_phone = State()
    waiting_for_profile = State()


class DriverRegistrationStates(StatesGroup):
    """States for driver registration."""

    waiting_for_vehicle_brand = State()
    waiting_for_vehicle_model = State()
    waiting_for_vehicle_color = State()
    waiting_for_vehicle_plate = State()
    waiting_for_vehicle_year = State()
    waiting_for_vehicle_seats = State()
    waiting_for_vehicle_photo = State()
    waiting_for_driver_verification = State()


class PassengerRequestStates(StatesGroup):
    """States for passenger ride request flow."""

    waiting_for_origin = State()
    waiting_for_destination = State()
    waiting_for_passenger_count = State()
    waiting_for_departure_date = State()
    waiting_for_departure_time = State()
    waiting_for_max_price = State()
    waiting_for_comment = State()
    waiting_for_confirmation = State()


class DriverTripStates(StatesGroup):
    """States for driver trip creation flow."""

    waiting_for_vehicle = State()
    waiting_for_origin = State()
    waiting_for_destination = State()
    waiting_for_departure_datetime = State()
    waiting_for_seats = State()
    waiting_for_price = State()
    waiting_for_comment = State()
    waiting_for_confirmation = State()


class SupportStates(StatesGroup):
    """States for support ticket creation."""

    waiting_for_subject = State()
    waiting_for_message = State()