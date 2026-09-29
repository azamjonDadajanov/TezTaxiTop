"""Bot configuration — reads values from environment variables / ``.env``.

All tokens and secrets come from ``os.environ``, never from source code.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Final
from urllib.parse import urlsplit

from dotenv import load_dotenv

# Without this the module only ever sees the inherited process environment, so
# editing .env had no effect on the bot even though this module documents .env
# support. Load it before any value below is read. Real environment variables
# still win, so process-level config keeps overriding the file.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

BOT_TOKEN: str = os.environ.get("TELEGRAM_BOT_TOKEN", "")
BOT_USERNAME: str = os.environ.get("TELEGRAM_BOT_USERNAME", "")
WEBHOOK_URL: str = os.environ.get("TELEGRAM_WEBHOOK_URL", "")
WEBHOOK_SECRET: str = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")
TELEGRAM_WEBAPP_URL: str = os.environ.get("TELEGRAM_WEBAPP_URL", "")


def validate_telegram_webapp_url(url: str) -> str:
    """Return a valid Telegram Web App URL or raise a clear configuration error."""
    value = url.strip()
    if not value:
        return ""

    try:
        parsed = urlsplit(value)
    except ValueError as error:
        raise ValueError("TELEGRAM_WEBAPP_URL must be a valid absolute HTTPS URL.") from error

    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise ValueError(
            "TELEGRAM_WEBAPP_URL must start with https:// and include a hostname; "
            "Telegram Web Apps do not accept HTTP URLs."
        )
    return value

POLL_TIMEOUT: Final[int] = 30
WEBHOOK_HOST: Final[str] = os.environ.get("TELEGRAM_WEBHOOK_HOST", "localhost")
WEBHOOK_PORT: Final[int] = int(os.environ.get("TELEGRAM_WEBHOOK_PORT", "8443"))
WEBHOOK_PATH: Final[str] = os.environ.get("TELEGRAM_WEBHOOK_PATH", f"/bot{BOT_TOKEN}")


def is_configured() -> bool:
    """True when the bot token is present."""
    return bool(BOT_TOKEN)