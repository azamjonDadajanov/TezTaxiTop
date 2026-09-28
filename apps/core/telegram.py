"""Telegram gateway: the **only** module allowed to talk to the Bot API.

Why a gateway?

* Domain services and Celery tasks must stay Telegram agnostic. They create
  ``Notification`` rows or call ``gateway.send_message(...)`` and nothing else.
* The bot itself (aiogram, long polling) and the delivery tasks share the same
  HTTP client, so a message is formatted in one place.
* The gateway is a thin, **synchronous** wrapper around the Bot API. It is
  called from Celery workers and from request/response code (webhooks), never
  from an ``async def`` view, which keeps it usable everywhere.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

TELEGRAM_API_ROOT = "https://api.telegram.org"
DEFAULT_TIMEOUT = 10


class TelegramError(RuntimeError):
    """The Bot API answered with ``ok = false`` or was unreachable."""


@dataclass(frozen=True)
class TelegramGateway:
    """Minimal Bot API client (messages only, which is all we need)."""

    token: str
    api_root: str = TELEGRAM_API_ROOT
    timeout: int = DEFAULT_TIMEOUT

    # -- low level -----------------------------------------------------------
    def call(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.token:
            raise TelegramError("TELEGRAM_BOT_TOKEN sozlanmagan.")
        url = f"{self.api_root}/bot{self.token}/{method}"
        try:
            response = requests.post(url, json=payload, timeout=self.timeout)
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as exc:
            raise TelegramError(f"Telegram API so'rovi muvaffaqiyatsiz: {exc}") from exc
        except ValueError as exc:  # non JSON body
            raise TelegramError("Telegram API javobi JSON emas.") from exc

        if not data.get("ok"):
            description = data.get("description", "noma'lum xato")
            raise TelegramError(f"Telegram API xatosi: {description}")
        return data.get("result") or {}

    # -- messages ------------------------------------------------------------
    def send_message(
        self,
        *,
        chat_id: int | str,
        text: str,
        parse_mode: str | None = "HTML",
        reply_markup: dict[str, Any] | None = None,
        disable_web_page_preview: bool = True,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": disable_web_page_preview,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return self.call("sendMessage", payload)

    def send_photo(
        self,
        *,
        chat_id: int | str,
        photo: str,
        caption: str = "",
        parse_mode: str | None = "HTML",
    ) -> dict[str, Any]:
        """``photo`` is a file_id, an URL or a local path (``upload`` is used)."""
        if photo.startswith("http://") or photo.startswith("https://") or photo.startswith("file_id:"):
            return self.call(
                "sendPhoto",
                {
                    "chat_id": chat_id,
                    "photo": photo.replace("file_id:", ""),
                    "caption": caption,
                    "parse_mode": parse_mode,
                },
            )
        with open(photo, "rb") as handle:
            return self.call(
                "sendPhoto",
                {"chat_id": chat_id, "photo": handle, "caption": caption, "parse_mode": parse_mode},
            )

    def answer_callback_query(
        self, *, callback_data_id: str, text: str = "", show_alert: bool = False
    ) -> dict[str, Any]:
        return self.call(
            "answerCallbackQuery",
            {"callback_query_id": callback_data_id, "text": text, "show_alert": show_alert},
        )

    def get_me(self) -> dict[str, Any]:
        return self.call("getMe", {})

    # -- health --------------------------------------------------------------
    def is_available(self) -> bool:
        try:
            self.get_me()
        except TelegramError:
            return False
        return True


_gateway: TelegramGateway | None = None


def get_telegram_gateway() -> TelegramGateway:
    """Return the process wide gateway (built once from the settings)."""
    global _gateway
    if _gateway is None:
        _gateway = TelegramGateway(token=getattr(settings, "TELEGRAM_BOT_TOKEN", ""))
    return _gateway


def is_bot_configured() -> bool:
    return bool(getattr(settings, "TELEGRAM_BOT_TOKEN", ""))


__all__ = [
    "TelegramError",
    "TelegramGateway",
    "get_telegram_gateway",
    "is_bot_configured",
]
