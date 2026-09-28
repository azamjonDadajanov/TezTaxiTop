"""Bot entry point.

Usage:
    Development:  python -m bot

Set TELEGRAM_BOT_MODE=webhook and TELEGRAM_WEBHOOK_URL to run in webhook mode.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if PROJECT_ROOT in sys.path:
    sys.path.remove(PROJECT_ROOT)
sys.path.insert(0, PROJECT_ROOT)

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage



# Configure logging before anything else.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


def _setup_django() -> None:
    """Initialise Django so that all models/services are importable."""
    import django  # noqa: F401
    from django.conf import settings

    # Prevent re-initialisation.
    if settings.configured:
        return

    import os

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")

    import django

    django.setup()


def create_dispatcher() -> tuple[Bot, Dispatcher]:
    """Build a Bot and Dispatcher with all routers loaded."""
    from bot.config import BOT_TOKEN

    if not BOT_TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is not set. "
            "Copy .env.example to .env and fill in the value."
        )

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())

    from bot.middlewares.user import UserMiddleware
    from bot.dispatcher import get_routers

    dp.update.outer_middleware(UserMiddleware())
    for router in get_routers():
        dp.include_router(router)

    return bot, dp


async def run_polling() -> None:
    """Start the bot using long polling."""
    _setup_django()
    bot, dp = create_dispatcher()
    try:
        await configure_web_app_menu(bot)
        await dp.start_polling(bot, drop_pending_updates=True)
    finally:
        await bot.session.close()


async def run_webhook() -> None:
    """Start the bot using webhook mode."""
    from aiohttp import web
    from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

    _setup_django()

    from bot.config import (
        WEBHOOK_HOST,
        WEBHOOK_PATH,
        WEBHOOK_PORT,
        WEBHOOK_SECRET,
        WEBHOOK_URL,
    )

    if not WEBHOOK_URL:
        raise RuntimeError("TELEGRAM_WEBHOOK_URL is required in webhook mode.")

    bot, dp = create_dispatcher()
    runner = None
    try:
        await configure_web_app_menu(bot)
        app = web.Application()
        SimpleRequestHandler(
            dispatcher=dp,
            bot=bot,
            secret_token=WEBHOOK_SECRET or None,
        ).register(app, path=WEBHOOK_PATH)
        setup_application(app, dp, bot=bot)

        await bot.set_webhook(
            f"{WEBHOOK_URL.rstrip('/')}{WEBHOOK_PATH}",
            secret_token=WEBHOOK_SECRET or None,
            drop_pending_updates=True,
        )

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, host=WEBHOOK_HOST, port=WEBHOOK_PORT)
        await site.start()
        await asyncio.Event().wait()
    finally:
        if runner is not None:
            await runner.cleanup()
        await bot.session.close()


async def configure_web_app_menu(bot: Bot) -> None:
    """Expose the Mini App from Telegram's persistent chat menu when configured."""
    from aiogram.types import MenuButtonWebApp, WebAppInfo

    from bot.config import TELEGRAM_WEBAPP_URL, validate_telegram_webapp_url

    web_app_url = validate_telegram_webapp_url(TELEGRAM_WEBAPP_URL)
    if not web_app_url:
        logging.info("Telegram Mini App menu button is disabled: TELEGRAM_WEBAPP_URL is empty.")
        return

    await bot.set_chat_menu_button(
        menu_button=MenuButtonWebApp(
            text="TezTaxiTop",
            web_app=WebAppInfo(url=web_app_url),
        )
    )


def main() -> None:
    """Entry point for ``python -m bot``."""
    import os

    _setup_django()
    mode = os.environ.get("TELEGRAM_BOT_MODE", "polling").lower()
    if mode == "webhook":
        asyncio.run(run_webhook())
    else:
        asyncio.run(run_polling())


if __name__ == "__main__":
    main()