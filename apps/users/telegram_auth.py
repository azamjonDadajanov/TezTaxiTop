"""Validation helpers for Telegram Mini App initData."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from urllib.parse import parse_qsl
from typing import Any

HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
INIT_DATA_MAX_AGE_SECONDS = 24 * 60 * 60
FUTURE_CLOCK_SKEW_SECONDS = 30


class InvalidTelegramInitData(ValueError):
    """Raised when Telegram Mini App initData is invalid or expired."""


def validate_telegram_init_data(
    init_data: str,
    bot_token: str,
    *,
    now: int | None = None,
) -> dict[str, Any]:
    """Verify initData's Telegram HMAC and return its trusted fields."""
    if not bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured on the backend.")
    if not init_data or len(init_data) > 8192:
        raise InvalidTelegramInitData("Telegram sessiya ma’lumoti bo‘sh yoki juda uzun.")

    try:
        pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True, max_num_fields=64)
    except ValueError as error:
        raise InvalidTelegramInitData("Telegram sessiya ma’lumoti noto‘g‘ri formatda.") from error

    fields = dict(pairs)
    if len(fields) != len(pairs):
        raise InvalidTelegramInitData("Telegram sessiya ma’lumotida takroriy maydon bor.")

    received_hash = fields.get("hash", "")
    if not HASH_PATTERN.fullmatch(received_hash):
        raise InvalidTelegramInitData("Telegram imzosi topilmadi yoki noto‘g‘ri.")

    data_check_string = "\n".join(
        f"{key}={value}" for key, value in sorted(fields.items()) if key != "hash"
    )
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_hash, received_hash):
        raise InvalidTelegramInitData("Telegram imzosi tekshiruvdan o‘tmadi.")

    try:
        auth_date = int(fields["auth_date"])
    except (KeyError, TypeError, ValueError) as error:
        raise InvalidTelegramInitData("Telegram auth_date maydoni noto‘g‘ri.") from error

    current_time = int(time.time()) if now is None else now
    if auth_date > current_time + FUTURE_CLOCK_SKEW_SECONDS:
        raise InvalidTelegramInitData("Telegram sessiya vaqti kelajakda.")
    if current_time - auth_date > INIT_DATA_MAX_AGE_SECONDS:
        raise InvalidTelegramInitData("Telegram sessiya muddati tugagan. Mini App’ni qayta oching.")

    try:
        user = json.loads(fields["user"])
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise InvalidTelegramInitData("Telegram foydalanuvchi ma’lumoti topilmadi.") from error

    if not isinstance(user, dict) or isinstance(user.get("id"), bool) or not isinstance(user.get("id"), int) or user["id"] <= 0:
        raise InvalidTelegramInitData("Telegram foydalanuvchi ID’si noto‘g‘ri.")
    for name in ("first_name", "last_name", "username", "language_code"):
        if name in user and user[name] is not None and not isinstance(user[name], str):
            raise InvalidTelegramInitData(f"Telegram {name} maydoni noto‘g‘ri.")

    return user