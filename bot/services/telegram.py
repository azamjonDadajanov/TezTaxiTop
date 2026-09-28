"""Telegram services — thin wrappers around Django service layer."""

from __future__ import annotations

import os

from asgiref.sync import sync_to_async

# Set up Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")


async def get_user(telegram_id: int):
    """Get Django user by Telegram ID."""
    from apps.users.selectors import get_user_by_telegram_id

    return await sync_to_async(get_user_by_telegram_id)(telegram_id)


async def get_or_create_user(telegram_user):
    """Get or create Django user from Telegram user object."""
    from apps.users.services import get_or_create_user_from_telegram

    return await sync_to_async(get_or_create_user_from_telegram)(
        telegram_id=telegram_user.id,
        username=telegram_user.username,
        first_name=telegram_user.first_name,
        last_name=telegram_user.last_name,
        language_code=telegram_user.language_code,
    )


async def set_user_phone_number(telegram_id: int, phone_number: str):
    """Update user's phone number."""
    from apps.users.services import update_user_profile

    user = await get_user(telegram_id)
    if user:
        await sync_to_async(update_user_profile)(user, phone_number=phone_number)


async def switch_user_role(telegram_user):
    """Switch user between passenger and driver role."""
    from apps.users.services import set_user_role
    from apps.users.constants import UserRole

    user = await get_user(telegram_user.id)
    if user:
        new_role = UserRole.DRIVER if not user.is_driver_role else UserRole.PASSENGER
        await sync_to_async(set_user_role)(user, new_role)
    return await get_user(telegram_user.id)


async def get_driver_profile(telegram_id: int):
    """Get driver profile for user."""
    from apps.users.models import DriverProfile

    user = await get_user(telegram_id)
    if user and hasattr(user, "driver_profile"):
        return user.driver_profile
    return None


async def create_driver_profile(telegram_user, bio: str = ""):
    """Create driver profile for user."""
    from apps.users.services import register_as_driver

    user = await get_or_create_user(telegram_user)
    return await sync_to_async(register_as_driver)(user, bio=bio)