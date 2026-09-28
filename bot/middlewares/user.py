"""User resolution middleware — resolves Telegram user to Django user."""

from __future__ import annotations

from typing import Callable, Dict, Awaitable, Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject


class UserMiddleware(BaseMiddleware):
    """Resolve the Telegram user for every incoming update."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        """Attach resolved user to data."""
        from bot.services.telegram import get_user

        telegram_user = getattr(event, "from_user", None) or data.get("event_from_user")
        if telegram_user is None:
            for field_name in ("message", "edited_message", "callback_query", "inline_query"):
                nested_event = getattr(event, field_name, None)
                telegram_user = getattr(nested_event, "from_user", None)
                if telegram_user is not None:
                    break
        if telegram_user is None:
            return await handler(event, data)

        try:
            user = await get_user(telegram_user.id)
            if user is not None:
                data["user"] = user
                data["telegram_user"] = telegram_user
        except Exception:
            # Don't block the handler if user resolution fails
            pass

        return await handler(event, data)