"""Regression tests for the Telegram bot package."""

from __future__ import annotations

import importlib
import importlib.util
import os
from datetime import datetime, time, timedelta, timezone as datetime_timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage, StorageKey
from aiogram.types import CallbackQuery, Chat, Message, User
from django.test import SimpleTestCase, TransactionTestCase
from django.utils import timezone

from apps.locations import services as location_services
from apps.users.services import create_user
from bot import dispatcher
from bot.keyboards import main_menu_keyboard, order_actions_keyboard
from bot.handlers import menu as menu_handlers
from bot.handlers.passenger import router as passenger_router
from bot.handlers.registration import handle_unexpected_text, request_phone_number
from bot.handlers.start import cmd_start
from bot.middlewares.user import UserMiddleware
from bot.main import configure_web_app_menu, create_dispatcher
from bot.main import main as bot_main
from bot.services import platform
from bot.services import locations as bot_locations
from bot.services import passenger as bot_passenger
from bot.states import PassengerRequestStates
from bot.states import RegistrationStates
from bot.states.passenger_request import PassengerRequestStates as PassengerRequestStatesModule


class BotPackageTests(SimpleTestCase):
    def test_main_initializes_django_before_reading_mode(self) -> None:
        call_order = []

        def record_run(coroutine) -> None:
            call_order.append("run")
            coroutine.close()

        with (
            patch.dict(os.environ, {"TELEGRAM_BOT_MODE": "polling"}),
            patch("bot.main._setup_django", side_effect=lambda: call_order.append("setup")),
            patch("bot.main.asyncio.run", side_effect=record_run),
        ):
            bot_main()

        self.assertEqual(call_order, ["setup", "run"])

    def test_passenger_state_export_is_the_single_state_definition(self) -> None:
        self.assertIs(PassengerRequestStates, PassengerRequestStatesModule)

    def test_module_entry_point_exists(self) -> None:
        self.assertIsNotNone(importlib.util.find_spec("bot.__main__"))

    def test_all_bot_modules_import(self) -> None:
        bot_directory = Path(__file__).parent
        for source_file in bot_directory.rglob("*.py"):
            relative_path = source_file.relative_to(bot_directory).with_suffix("")
            if relative_path.name == "__init__":
                module_name = "bot" + (
                    "." + ".".join(relative_path.parts[:-1]) if relative_path.parts[:-1] else ""
                )
            else:
                module_name = "bot." + ".".join(relative_path.parts)
            with self.subTest(module=module_name):
                self.assertIsNotNone(importlib.import_module(module_name))

    async def test_dispatcher_creation_returns_bot_and_registers_routers(self) -> None:
        with patch("bot.config.BOT_TOKEN", "123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi"):
            bot, configured_dispatcher = create_dispatcher()

        try:
            self.assertIsInstance(bot, Bot)
            self.assertEqual(
                [router.name for router in configured_dispatcher.sub_routers],
                ["menu", "start", "registration", "passenger", "driver"],
            )
        finally:
            await bot.session.close()

    def test_dispatcher_registers_every_available_handler(self) -> None:
        self.assertEqual(
            [router.name for router in dispatcher.get_routers()],
            ["menu", "start", "registration", "passenger", "driver"],
        )

    def test_menu_router_precedes_all_fsm_routers(self) -> None:
        self.assertEqual(dispatcher.get_routers()[0], menu_handlers.router)

    def test_menu_router_exposes_every_menu_and_inline_workflow(self) -> None:
        message_handlers = {handler.callback.__name__ for handler in menu_handlers.router.message.handlers}
        callback_handlers = {handler.callback.__name__ for handler in menu_handlers.router.callback_query.handlers}

        self.assertTrue(
            {
                "show_profile",
                "show_orders",
                "show_notifications",
                "start_support",
                "show_subscription",
                "show_payments",
                "create_passenger_request",
                "find_passenger_ride",
                "list_passenger_requests",
                "create_driver_trip",
                "list_driver_trips",
                "list_driver_requests",
                "list_driver_vehicles",
                "become_driver",
            }.issubset(message_handlers)
        )
        self.assertTrue(
            {
                "profile_callback",
                "passenger_create_callback",
                "driver_create_callback",
                "notifications_callback",
                "support_callback",
            }.issubset(callback_handlers)
        )
        self.assertIn("refresh_matches", {handler.callback.__name__ for handler in passenger_router.callback_query.handlers})

    def test_phone_keyboard_requests_contact(self) -> None:
        with patch("bot.keyboards.TELEGRAM_WEBAPP_URL", "https://mini.example.com"):
            keyboard = request_phone_number()

        self.assertTrue(keyboard.keyboard[0][0].request_contact)
        self.assertEqual(keyboard.keyboard[1][0].web_app.url, "https://mini.example.com")

    def test_role_menus_include_mini_app_button_when_configured(self) -> None:
        with patch("bot.keyboards.TELEGRAM_WEBAPP_URL", "https://mini.example.com"):
            passenger_keyboard = main_menu_keyboard()
            driver_keyboard = main_menu_keyboard(is_driver=True)

        for keyboard in (passenger_keyboard, driver_keyboard):
            button = keyboard.keyboard[0][0]
            self.assertEqual(button.text, "🚕 Ilovani ochish")
            self.assertEqual(button.web_app.url, "https://mini.example.com")

    async def test_persistent_menu_button_uses_configured_web_app_url(self) -> None:
        bot = SimpleNamespace(set_chat_menu_button=AsyncMock())
        with patch("bot.config.TELEGRAM_WEBAPP_URL", "https://mini.example.com"):
            await configure_web_app_menu(bot)

        menu_button = bot.set_chat_menu_button.await_args.kwargs["menu_button"]
        self.assertEqual(menu_button.text, "TezTaxiTop")
        self.assertEqual(menu_button.web_app.url, "https://mini.example.com")

    async def test_persistent_menu_button_is_not_set_without_url(self) -> None:
        bot = SimpleNamespace(set_chat_menu_button=AsyncMock())
        with patch("bot.config.TELEGRAM_WEBAPP_URL", ""):
            await configure_web_app_menu(bot)

        bot.set_chat_menu_button.assert_not_awaited()

    def test_order_action_keyboard_matches_registered_callback_format(self) -> None:
        keyboard = order_actions_keyboard(17, "pending")

        self.assertEqual(
            [button.callback_data for row in keyboard.inline_keyboard for button in row],
            ["order:accept:17", "order:reject:17"],
        )

    def test_match_booking_uses_requested_passenger_count(self) -> None:
        from apps.matching.models import TripMatch

        user = SimpleNamespace(pk=123)
        request = SimpleNamespace(passenger_id=user.pk, passenger_count=3)
        trip = SimpleNamespace(pk=77)
        match = SimpleNamespace(request_id=5, request=request, trip=trip)
        manager = TripMatch.objects
        queryset = SimpleNamespace(filter=lambda **kwargs: SimpleNamespace(first=lambda: match))

        with (
            patch("bot.services.platform._get_user", return_value=user),
            patch.object(manager, "select_related", return_value=queryset),
            patch("apps.orders.services.create_order", return_value="order") as create_order_mock,
        ):
            result = platform._book_match(telegram_id=999, request_id=5, match_id=8)

        self.assertEqual(result, "order")
        create_order_mock.assert_called_once_with(passenger=user, trip=trip, seats_booked=3)

    async def test_unmatched_text_does_not_raise_outside_registration(self) -> None:
        message = SimpleNamespace(answer=AsyncMock())
        state = SimpleNamespace(get_state=AsyncMock(return_value=None))

        await handle_unexpected_text(message, state)

        message.answer.assert_not_awaited()

    async def test_new_start_enters_phone_registration_state(self) -> None:
        user = SimpleNamespace(id=555, username="new_user", first_name="New", last_name="")
        message = SimpleNamespace(from_user=user, answer=AsyncMock())
        state = SimpleNamespace(clear=AsyncMock(), set_state=AsyncMock())

        with patch(
            "bot.services.telegram.get_or_create_user",
            new=AsyncMock(return_value=(SimpleNamespace(), True)),
        ):
            await cmd_start(message, state)

        state.set_state.assert_awaited_once()
        self.assertEqual(state.set_state.await_args.args[0], RegistrationStates.waiting_for_phone)

    async def test_profile_navigation_clears_previous_fsm_state(self) -> None:
        message = SimpleNamespace(from_user=SimpleNamespace(id=123), answer=AsyncMock())
        state = SimpleNamespace(clear=AsyncMock())
        user = SimpleNamespace(
            display_name="Rider",
            phone_number="+998901234567",
            get_role_display=lambda: "Yo'lovchi",
            driver_profile=None,
        )

        with patch("bot.handlers.menu.platform.get_user", new=AsyncMock(return_value=user)):
            await menu_handlers.show_profile(message, state)

        state.clear.assert_awaited_once()
        message.answer.assert_awaited_once()

    async def test_profile_button_interrupts_active_passenger_state(self) -> None:
        bot = Bot("123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi")
        storage = MemoryStorage()
        state = FSMContext(storage, StorageKey(bot_id=bot.id, chat_id=123, user_id=123))
        await state.set_state(PassengerRequestStates.waiting_for_departure_date)
        message = Message(
            message_id=1,
            date=datetime.now(datetime_timezone.utc),
            chat=Chat(id=123, type="private"),
            from_user=User(id=123, is_bot=False, first_name="Rider"),
            text="👤 Profil",
        ).as_(bot)
        user = SimpleNamespace(
            display_name="Rider",
            phone_number="",
            get_role_display=lambda: "Yo'lovchi",
            driver_profile=None,
        )

        try:
            with (
                patch("bot.handlers.menu.platform.get_user", new=AsyncMock(return_value=user)),
                patch.object(Message, "answer", new=AsyncMock()),
            ):
                await menu_handlers.router.propagate_event("message", message, bot=bot, state=state)

            self.assertIsNone(await state.get_state())
        finally:
            await bot.session.close()

    async def test_inline_profile_callback_uses_clicking_user_id(self) -> None:
        bot = Bot("123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi")
        telegram_user = User(id=321, is_bot=False, first_name="Rider")
        message = Message(
            message_id=3,
            date=datetime.now(datetime_timezone.utc),
            chat=Chat(id=999, type="private"),
            from_user=User(id=bot.id, is_bot=True, first_name="Bot"),
        ).as_(bot)
        callback = CallbackQuery(
            id="callback-1",
            from_user=telegram_user,
            chat_instance="chat-1",
            message=message,
            data="profile",
        ).as_(bot)
        state = FSMContext(MemoryStorage(), StorageKey(bot_id=bot.id, chat_id=999, user_id=telegram_user.id))
        user = SimpleNamespace(
            display_name="Rider",
            phone_number="",
            get_role_display=lambda: "Yo'lovchi",
            driver_profile=None,
        )

        try:
            with (
                patch("bot.handlers.menu.platform.get_user", new=AsyncMock(return_value=user)) as get_user,
                patch.object(Message, "answer", new=AsyncMock()),
                patch.object(CallbackQuery, "answer", new=AsyncMock()),
            ):
                await menu_handlers.profile_callback(callback, state)

            get_user.assert_awaited_once_with(telegram_user.id)
        finally:
            await bot.session.close()

    async def test_invalid_location_step_input_is_handled(self) -> None:
        bot = Bot("123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi")
        storage = MemoryStorage()
        state = FSMContext(storage, StorageKey(bot_id=bot.id, chat_id=124, user_id=124))
        await state.set_state(PassengerRequestStates.waiting_for_origin)
        message = Message(
            message_id=2,
            date=datetime.now(datetime_timezone.utc),
            chat=Chat(id=124, type="private"),
            from_user=User(id=124, is_bot=False, first_name="Rider"),
            text="Toshkent",
        ).as_(bot)
        answer = AsyncMock()

        try:
            with patch.object(Message, "answer", new=answer):
                from bot.handlers.passenger import router as passenger_router

                await passenger_router.propagate_event(
                    "message",
                    message,
                    bot=bot,
                    state=state,
                    raw_state=await state.get_state(),
                )

            answer.assert_awaited_once()
            self.assertEqual(await state.get_state(), PassengerRequestStates.waiting_for_origin.state)
        finally:
            await bot.session.close()

    async def test_middleware_passes_senderless_updates_through(self) -> None:
        middleware = UserMiddleware()
        handler = AsyncMock(return_value="handled")
        event = SimpleNamespace()

        result = await middleware(handler, event, {})

        self.assertEqual(result, "handled")
        handler.assert_awaited_once_with(event, {})

    async def test_middleware_does_not_create_user_before_start(self) -> None:
        middleware = UserMiddleware()
        handler = AsyncMock(return_value="handled")
        event = SimpleNamespace(message=SimpleNamespace(from_user=SimpleNamespace(id=123)))
        data = {}

        with patch("bot.services.telegram.get_user", new=AsyncMock(return_value=None)):
            result = await middleware(handler, event, data)

        self.assertEqual(result, "handled")
        self.assertNotIn("user", data)
        handler.assert_awaited_once_with(event, data)

    def test_match_formatter_escapes_user_and_location_text(self) -> None:
        trip = SimpleNamespace(
            driver=SimpleNamespace(
                user=SimpleNamespace(display_name="<User>", username="user"),
                rating=Decimal("4.50"),
            ),
            departure_time=timezone.now(),
            available_seats=2,
            price_per_seat=Decimal("10000"),
            route_label=lambda: "<Origin> -> <Destination>",
        )
        match = SimpleNamespace(trip=trip)

        result = bot_passenger.format_matches_for_user([match])

        self.assertIn("&lt;Origin&gt;", result)
        self.assertIn("&lt;User&gt;", result)
        self.assertNotIn("<Origin>", result)


class BotServiceTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self) -> None:
        self.user = create_user(username="bot-passenger", telegram_id=123456789)
        region = location_services.get_or_create_region(name="Bot test region")
        district = location_services.get_or_create_district(region=region, name="Bot test district")
        self.origin = location_services.get_or_create_location(
            district=district,
            name="Origin",
            latitude="41.300000",
            longitude="69.200000",
        )
        self.destination = location_services.get_or_create_location(
            district=district,
            name="Destination",
            latitude="41.400000",
            longitude="69.300000",
        )

    async def test_create_passenger_request_maps_telegram_id_and_departure(self) -> None:
        departure_date = timezone.localdate() + timedelta(days=1)

        passenger_request = await bot_passenger.create_passenger_request(
            user_id=self.user.telegram_id,
            origin_location_id=self.origin.pk,
            destination_location_id=self.destination.pk,
            departure_date=departure_date,
            departure_time=time(14, 30),
            passenger_count=2,
            max_price_per_seat=Decimal("25000"),
            comment="Window seat",
        )

        self.assertEqual(passenger_request.passenger_id, self.user.pk)
        self.assertEqual(passenger_request.from_location_id, self.origin.pk)
        self.assertEqual(passenger_request.to_location_id, self.destination.pk)
        self.assertEqual(passenger_request.departure_from.date(), departure_date)
        self.assertTrue(timezone.is_aware(passenger_request.departure_from))
        self.assertEqual(passenger_request.max_price_per_seat, Decimal("25000.00"))
        self.assertEqual(passenger_request.comment, "Window seat")

    async def test_nearest_location_resolves_to_active_catalog_entry(self) -> None:
        nearest = await bot_locations.get_nearest_location_from_coordinates(
            41.301,
            69.201,
        )

        self.assertEqual(nearest.pk, self.origin.pk)

    async def test_nearest_location_rejects_invalid_coordinates(self) -> None:
        from apps.core.exceptions import BusinessValidationError

        with self.assertRaises(BusinessValidationError):
            await bot_locations.get_nearest_location_from_coordinates(91, 0)

    async def test_driver_onboarding_creates_backend_driver_profile(self) -> None:
        profile = await platform.register_driver(self.user.telegram_id)

        await self.user.arefresh_from_db()
        self.assertEqual(profile.user_id, self.user.pk)
        self.assertTrue(self.user.is_driver_role)

    async def test_driver_request_list_excludes_insufficient_seats_and_budget(self) -> None:
        from apps.rides.models import DriverTrip, PassengerRequest
        from apps.users.services import register_as_driver
        from apps.vehicles.models import Vehicle
        from asgiref.sync import sync_to_async
        from django.utils import timezone

        def create_fixtures() -> tuple[int, int]:
            driver_user = create_user(username="bot-driver", telegram_id=223456789)
            driver = register_as_driver(driver_user)
            vehicle = Vehicle.objects.create(
                driver=driver,
                brand="Test",
                model="Taxi",
                color="White",
                plate_number="01B 123AA",
                year=2024,
                seats_count=5,
                is_active=True,
                is_verified=True,
            )
            departure = timezone.now() + timedelta(days=2)
            DriverTrip.objects.create(
                driver=driver,
                vehicle=vehicle,
                from_location_id=self.origin.pk,
                to_location_id=self.destination.pk,
                departure_time=departure,
                total_seats=2,
                available_seats=2,
                price_per_seat=Decimal("10000"),
                status="active",
            )
            common = {
                "from_location_id": self.origin.pk,
                "to_location_id": self.destination.pk,
                "departure_from": departure - timedelta(minutes=30),
                "departure_until": departure + timedelta(minutes=30),
                "status": "active",
            }
            compatible = PassengerRequest.objects.create(
                passenger_id=self.user.pk,
                passenger_count=2,
                max_price_per_seat=Decimal("10000"),
                **common,
            )
            too_many_passengers = create_user(username="bot-large-request", telegram_id=323456789)
            PassengerRequest.objects.create(
                passenger=too_many_passengers,
                passenger_count=3,
                max_price_per_seat=None,
                **common,
            )
            too_expensive = create_user(username="bot-cheap-request", telegram_id=423456789)
            PassengerRequest.objects.create(
                passenger=too_expensive,
                passenger_count=1,
                max_price_per_seat=Decimal("5000"),
                **common,
            )
            return compatible.pk, driver_user.telegram_id

        compatible_id, driver_telegram_id = await sync_to_async(create_fixtures)()

        requests = await platform.get_driver_requests(driver_telegram_id)

        self.assertEqual([request.pk for request in requests], [compatible_id])
