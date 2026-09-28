"""Bot configuration — reads values from environment variables / ``.env``.

All tokens and secrets come from ``os.environ``, never from source code.
"""

from __future__ import annotations

import os
from typing import Final

BOT_TOKEN: str = os.environ.get("TELEGRAM_BOT_TOKEN", "")
BOT_USERNAME: str = os.environ.get("TELEGRAM_BOT_USERNAME", "")
WEBHOOK_URL: str = os.environ.get("TELEGRAM_WEBHOOK_URL", "")
WEBHOOK_SECRET: str = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")
TELEGRAM_WEBAPP_URL: str = os.environ.get("TELEGRAM_WEBAPP_URL", "")

POLL_TIMEOUT: Final[int] = 30
WEBHOOK_HOST: Final[str] = os.environ.get("TELEGRAM_WEBHOOK_HOST", "localhost")
WEBHOOK_PORT: Final[int] = int(os.environ.get("TELEGRAM_WEBHOOK_PORT", "8443"))
WEBHOOK_PATH: Final[str] = os.environ.get("TELEGRAM_WEBHOOK_PATH", f"/bot{BOT_TOKEN}")


def is_configured() -> bool:
    """True when the bot token is present."""
    return bool(BOT_TOKEN)