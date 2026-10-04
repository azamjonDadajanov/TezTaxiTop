"""Bot dispatcher — the single place that registers all routers."""

from __future__ import annotations

from aiogram import Dispatcher, Router


def get_routers() -> list[Router]:
    """Return all registered bot routers in priority order."""
    from bot.handlers.menu import router as menu_router
    from bot.handlers.start import router as start_router
    from bot.handlers.registration import router as registration_router
    from bot.handlers.review import router as review_router
    from bot.handlers.passenger import router as passenger_router
    from bot.handlers.driver import router as driver_router

    return [
        menu_router,
        start_router,
        registration_router,
        review_router,
        passenger_router,
        driver_router,
    ]


def create_dispatcher() -> Dispatcher:
    """Build a Dispatcher with all routers loaded."""
    dp = Dispatcher()
    for router in get_routers():
        dp.include_router(router)
    return dp