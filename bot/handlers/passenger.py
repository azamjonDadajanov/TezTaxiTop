"""Passenger handlers — ride requests, orders, and matching."""

from __future__ import annotations

import html
import logging
from datetime import datetime

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from apps.core.exceptions import BusinessError
from apps.orders.constants import MAX_SEATS_PER_ORDER
from django.utils import timezone

from bot.keyboards import (
    cancel_keyboard,
    location_keyboard,
    main_menu_keyboard,
    make_date_keyboard,
    make_time_keyboard,
)
from bot.services import platform
from bot.services.locations import describe_point, normalize_location, route_distance_km, route_error
from bot.services.passenger import (
    create_passenger_request,
    format_matches_for_user,
    format_trip_for_user,
    get_matching_trips,
    get_my_orders,
    get_my_requests,
)
from bot.states import PassengerRequestStates

router = Router(name="passenger")
logger = logging.getLogger(__name__)


async def _send_matches(message: Message, request_id: int, matches: list) -> None:
    from bot.keyboards import match_keyboard

    for match in matches:
        await message.answer(
            format_matches_for_user([match]),
            parse_mode="HTML",
            reply_markup=match_keyboard(request_id, match.pk),
        )


async def _send_main_menu(message: Message, user_id: int) -> None:
    try:
        user = await platform.get_user(user_id)
        is_driver = user.is_driver_role
    except BusinessError:
        is_driver = False
    await message.answer("Asosiy menyu:", reply_markup=main_menu_keyboard(is_driver))


@router.message(F.text == "📝 So'rov yaratish")
async def start_passenger_request(message: Message, state: FSMContext) -> None:
    """Start creating a passenger request."""
    await state.set_state(PassengerRequestStates.waiting_for_origin)
    await message.answer(
        "📍 <b>Qo'shilish manzilini yuboring:</b>\n\n"
        "Pastdagi tugma orqali lokatsiyangizni yuboring.",
        parse_mode="HTML",
        reply_markup=location_keyboard(),
    )


@router.message(PassengerRequestStates.waiting_for_origin, F.location)
async def handle_origin_location(message: Message, state: FSMContext) -> None:
    """Handle origin location selection."""
    try:
        point = await normalize_location(message.location.latitude, message.location.longitude)
    except BusinessError as error:
        await message.answer(html.escape(error.message))
        return
    await state.update_data(origin=point, origin_label=describe_point(point))
    await state.set_state(PassengerRequestStates.waiting_for_destination)

    await message.answer(
        f"✅ Manba: <b>{html.escape(describe_point(point))}</b>\n\n"
        "📍 Endi <b>qo'nish nuqtasini</b> yuboring:",
        parse_mode="HTML",
        reply_markup=location_keyboard(),
    )


@router.message(PassengerRequestStates.waiting_for_destination, F.location)
async def handle_destination_location(message: Message, state: FSMContext) -> None:
    """Handle destination location selection."""
    try:
        point = await normalize_location(message.location.latitude, message.location.longitude)
    except BusinessError as error:
        await message.answer(html.escape(error.message))
        return
    data = await state.get_data()
    origin = data.get("origin")
    if origin is None:
        await message.answer("Avval qo'shilish nuqtasini yuboring.")
        return
    error_message = route_error(origin, point)
    if error_message:
        await message.answer(error_message)
        return
    await state.update_data(destination=point, destination_label=describe_point(point))
    await state.set_state(PassengerRequestStates.waiting_for_departure_date)

    await message.answer(
        f"✅ Maqsad: <b>{html.escape(describe_point(point))}</b>\n"
        f"📏 Masofa: <b>~{route_distance_km(origin, point):.1f} km</b>\n\n"
        "📅 <b>Chuqish sanasini tanlang:</b>",
        parse_mode="HTML",
        reply_markup=await make_date_keyboard(),
    )


@router.callback_query(
    StateFilter(
        PassengerRequestStates.waiting_for_departure_date,
        PassengerRequestStates.waiting_for_departure_time,
    ),
    F.data.startswith("datetime:"),
)
async def request_departure_datetime_callback(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """Drive the inline date → time picker for a passenger request."""
    parts = callback.data.split(":", maxsplit=3)
    if parts[1] == "date":
        date_str = parts[2]
        await state.update_data(departure_date_str=date_str)
        await state.set_state(PassengerRequestStates.waiting_for_departure_time)
        if callback.message:
            await callback.message.edit_text(
                f"📅 Sana: {date_str}\nVaqtni tanlang:",
                reply_markup=await make_time_keyboard(date_str),
            )
        await callback.answer()
        return
    if parts[1] == "back":
        await state.set_state(PassengerRequestStates.waiting_for_departure_date)
        if callback.message:
            await callback.message.edit_text(
                "Chuqish sanasini tanlang:",
                reply_markup=await make_date_keyboard(),
            )
        await callback.answer()
        return
    try:
        date_str = parts[2]
        time_str = parts[3]
        naive = datetime.strptime(f"{date_str} {time_str}", "%d.%m.%Y %H:%M")  # noqa: DTZ007
        departure = timezone.make_aware(naive)
        if departure <= timezone.now():
            raise ValueError
    except (IndexError, ValueError):
        await callback.answer("Bu vaqt o'tib ketgan, boshqa sana tanlang.", show_alert=True)
        return
    await state.update_data(departure_date=naive.date(), departure_time=naive.time())
    await state.set_state(PassengerRequestStates.waiting_for_passenger_count)
    if callback.message:
        await callback.message.edit_text(f"🕐 Chuqish vaqti: {date_str} {time_str}")
        await callback.message.answer(
            "👥 <b>Yo'lovchilar sonini kiriting (1-9):</b>",
            parse_mode="HTML",
            reply_markup=cancel_keyboard(),
        )
    await callback.answer("Sana va vaqt tanlandi")


@router.message(PassengerRequestStates.waiting_for_passenger_count, F.text.isdigit())
async def handle_passenger_count(message: Message, state: FSMContext) -> None:
    """Handle passenger count input."""
    count = int(message.text)
    if count < 1 or count > 9:
        await message.answer("Iltimos, 1 dan 9 gacha son kiriting.")
        return

    await state.update_data(passenger_count=count)
    await state.set_state(PassengerRequestStates.waiting_for_max_price)

    await message.answer(
        "💰 <b>Maksimal narxni kiriting (so'm, ixtiyoriy):</b>\n\n"
        "Agar cheklov yo'q bo'lsa, '0' yuboring.",
        parse_mode="HTML",
        reply_markup=cancel_keyboard(),
    )


@router.message(PassengerRequestStates.waiting_for_passenger_count, F.text)
async def handle_invalid_passenger_count(message: Message) -> None:
    """Explain the accepted format when passenger count is not numeric."""
    await message.answer("Yo'lovchilar sonini 1 dan 9 gacha butun son bilan kiriting.")


@router.message(PassengerRequestStates.waiting_for_max_price, F.text)
async def handle_max_price(message: Message, state: FSMContext) -> None:
    """Handle max price input."""
    raw_price = message.text.strip()
    if raw_price and (not raw_price.isdigit()):
        await message.answer("Narxni 0 yoki musbat butun son bilan kiriting.")
        return
    max_price = int(raw_price) if raw_price and int(raw_price) > 0 else None

    await state.update_data(max_price_per_seat=max_price)
    await state.set_state(PassengerRequestStates.waiting_for_comment)

    await message.answer(
        "💬 <b>Qo'shimcha izoh (ixtiyoriy):</b>\n\n"
        "Masalan: 'Kondisioner kerak', 'Tinchlik kerak' va h.k.\n"
        "Izoh bo'lmasa, '-' yuboring.",
        parse_mode="HTML",
        reply_markup=cancel_keyboard(),
    )


@router.message(PassengerRequestStates.waiting_for_comment, F.text)
async def handle_comment(message: Message, state: FSMContext) -> None:
    """Handle comment input and show confirmation."""
    comment = "" if message.text.strip() == "-" else message.text.strip()
    await state.update_data(comment=comment)
    data = await state.get_data()

    await state.set_state(PassengerRequestStates.waiting_for_confirmation)

    departure_date = data.get("departure_date")
    departure_time = data.get("departure_time")
    max_price = data.get("max_price_per_seat")
    date_display = departure_date.strftime("%d.%m.%Y") if departure_date else "Noma'lum"
    time_display = departure_time.strftime("%H:%M") if departure_time else "Noma'lum"
    price_display = f"{max_price:,} so'm" if max_price else "cheklanmagan"
    comment_display = html.escape(comment) if comment else "yo'q"

    summary = (
        "📋 <b>So'rovingiz tasdiqlash uchun:</b>\n\n"
        f"📍 Qayerdan: <b>{html.escape(data.get('origin_label', 'Noma\'lum'))}</b>\n"
        f"📍 Qayerga: <b>{html.escape(data.get('destination_label', 'Noma\'lum'))}</b>\n"
        f"👥 Yo'lovchilar: <b>{data.get('passenger_count', 1)}</b>\n"
        f"📅 Sana: <b>{date_display}</b>\n"
        f"🕐 Vaqt: <b>{time_display}</b>\n"
        f"💰 Maksimal narx: <b>{price_display}</b>\n"
        f"💬 Izoh: <b>{comment_display}</b>\n"
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Tasdiqlash", callback_data="confirm_request"),
                InlineKeyboardButton(text="✏️ Tahrirlash", callback_data="edit_request"),
            ],
            [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel_flow")],
        ]
    )

    await message.answer(summary, parse_mode="HTML", reply_markup=keyboard)


@router.callback_query(F.data == "confirm_request", PassengerRequestStates.waiting_for_confirmation)
async def confirm_request(callback: CallbackQuery, state: FSMContext) -> None:
    """Confirm and create the passenger request."""
    data = await state.get_data()

    try:
        request = await create_passenger_request(
            user_id=callback.from_user.id,
            origin=data["origin"],
            destination=data["destination"],
            departure_date=data["departure_date"],
            departure_time=data["departure_time"],
            passenger_count=data["passenger_count"],
            max_price_per_seat=data.get("max_price_per_seat"),
            comment=data.get("comment", ""),
        )

        await state.clear()
        await callback.message.edit_text(
            f"✅ So'rov yaratildi! (ID: #{request.id})\n\n"
            "Endi mos yo'lovlarni qidirishni boshlaymiz..."
        )

        matches = await get_matching_trips(request.id)
        if matches:
            await _send_matches(callback.message, request.id, matches)
        else:
            await callback.message.answer(
                "Hozircha mos yo'lov topilmadi. So'rovingiz faol, "
                "haydovchi e'lon qilganda sizga xabar beramiz."
            )
        await _send_main_menu(callback.message, callback.from_user.id)
    except BusinessError as error:
        await state.clear()
        await callback.message.edit_text(f"❌ {html.escape(error.message)}")
        await _send_main_menu(callback.message, callback.from_user.id)
    except Exception:
        logger.exception("Passenger request creation failed")
        await state.clear()
        await callback.message.edit_text("❌ Kutilmagan xatolik yuz berdi.")
        await _send_main_menu(callback.message, callback.from_user.id)


@router.message(F.text == "📋 Mening so'rovlarim")
async def show_my_requests(message: Message, user_id: int | None = None) -> None:
    """Show user's passenger requests."""
    requests = await get_my_requests(user_id or message.from_user.id)
    if not requests:
        await message.answer("Sizda hali so'rovlar yo'q.")
        return

    text = "📋 <b>Mening so'rovlarim:</b>\n\n"
    for req in requests:
        text += (
            f"#{req.id}: {req.origin_display} → {req.destination_display}\n"
            f"   👥 {req.passenger_count} kishi | 📅 {req.departure_from:%d.%m %H:%M}\n"
            f"   📊 {req.get_status_display()}\n\n"
        )
        if req.is_matchable:
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="So'rovni bekor qilish", callback_data=f"request:cancel:{req.pk}")]]
            )
            await message.answer(text, parse_mode="HTML", reply_markup=keyboard)
            text = ""
    if text:
        await message.answer(text, parse_mode="HTML")


@router.message(F.text == "📦 Buyurtmalarim")
async def show_my_orders(message: Message, user_id: int | None = None) -> None:
    """Show user's orders."""
    orders = await get_my_orders(user_id or message.from_user.id)
    if not orders:
        await message.answer("Sizda hali buyurtmalar yo'q.")
        return

    text = "📦 <b>Mening buyurtmalarim:</b>\n\n"
    for order in orders:
        text += (
            f"#{order.id}: {order.trip.route_label()}\n"
            f"   💺 {order.seats_booked} o'rin | 💰 {order.total_amount:,} so'm\n"
            f"   📊 {order.get_status_display()}\n\n"
        )
    await message.answer(text, parse_mode="HTML")


def _seat_keyboard(trip) -> InlineKeyboardMarkup:
    seats = min(trip.available_seats, MAX_SEATS_PER_ORDER)
    buttons = [
        InlineKeyboardButton(text=f"💺 {n}", callback_data=f"booktrip:{trip.pk}:{n}")
        for n in range(1, seats + 1)
    ]
    rows = [buttons[i : i + 4] for i in range(0, len(buttons), 4)]
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(F.text == "🔍 Yo'lov topish")
async def find_ride(message: Message, user_id: int | None = None) -> None:
    """Show drivers' trips that can be booked right now."""
    trips = await platform.get_bookable_trips(user_id or message.from_user.id)
    if not trips:
        await message.answer(
            "Hozircha sotiladigan yo'lovlar yo'q. Keyinroq qayta urinib ko'ring."
        )
        return
    for trip in trips:
        await message.answer(
            format_trip_for_user(trip),
            parse_mode="HTML",
            reply_markup=_seat_keyboard(trip),
        )


@router.callback_query(F.data.startswith("booktrip:"))
async def book_trip(callback: CallbackQuery) -> None:
    try:
        _, trip_id, seats = callback.data.split(":", maxsplit=3)
        order = await platform.book_trip(callback.from_user.id, int(trip_id), int(seats))
    except (ValueError, BusinessError) as error:
        text = error.message if isinstance(error, BusinessError) else "Band qilish tugmasi noto'g'ri."
        await callback.answer(text, show_alert=True)
        return
    await callback.answer("Buyurtma haydovchiga yuborildi.")
    if callback.message:
        await callback.message.answer(
            f"Buyurtma #{order.pk} yaratildi. Holati: {order.get_status_display()}. "
            "O'rinlar haydovchi qabul qilgandan keyin band qilinadi."
        )


@router.callback_query(F.data.startswith("book_match:"))
async def book_matching_trip(callback: CallbackQuery) -> None:
    try:
        _, request_id, match_id = callback.data.split(":", maxsplit=2)
        order = await platform.book_match(
            callback.from_user.id,
            int(request_id),
            int(match_id),
        )
    except (ValueError, BusinessError) as error:
        text = error.message if isinstance(error, BusinessError) else "Band qilish tugmasi noto'g'ri."
        await callback.answer(text, show_alert=True)
        return
    await callback.answer("Buyurtma haydovchiga yuborildi.")
    if callback.message:
        await callback.message.answer(
            f"Buyurtma #{order.pk} yaratildi. Holati: {order.get_status_display()}. "
            "O'rinlar haydovchi qabul qilgandan keyin band qilinadi."
        )
        # Ask if passenger wants to open chat
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="💬 Ha, suhbat ochish", callback_data=f"open_chat_after_book:{order.pk}")],
                [InlineKeyboardButton(text="❌ Yo'q, hozir qolish", callback_data="back_to_menu")],
            ]
        )
        await callback.message.answer(
            "Siz haydovchi bilan suhbatlashishingiz mumkinmi?",
            reply_markup=keyboard,
        )


@router.callback_query(F.data.startswith("open_chat_after_book:"))
async def open_chat_after_book(callback: CallbackQuery) -> None:
    try:
        order_id = int(callback.data.partition(":")[2])
        from bot.services.platform import _get_user
        user = _get_user(callback.from_user.id)
        from apps.chat.services import get_or_create_conversation
        thread, created = get_or_create_conversation(user=user, order_id=order_id)
    except (ValueError, BusinessError) as error:
        text = error.message if isinstance(error, BusinessError) else "Suhbat ochilshida xatolik."
        await callback.answer(text, show_alert=True)
        return
    await callback.answer("Suhbat ochildi!")
    if callback.message:
        await callback.message.answer(
            f"Suhbatga ochildi! Yo'lovchi: {thread.order.passenger.display_name}. "
            f"Buyurtma #{thread.order_id} bo'yicha suhbat ochildi."
        )


@router.callback_query(F.data.startswith("open_chat:"))
async def open_chat_from_match(callback: CallbackQuery) -> None:
    try:
        _, request_id, match_id = callback.data.split(":", maxsplit=2)
        from apps.matching.models import TripMatch
        from apps.chat.services import get_or_create_conversation
        from bot.services.platform import _get_user
        user = _get_user(callback.from_user.id)
        match = TripMatch.objects.select_related("request", "trip").filter(pk=match_id).first()
        if match is None:
            await callback.answer("Mos yo'lov topilmadi.", show_alert=True)
            return
        if match.request_id != request_id or match.request.passenger_id != user.pk:
            await callback.answer("Bu suhbatga kirish huquqingiz yo'q.", show_alert=True)
            return
        thread, created = get_or_create_conversation(user=user, order_id=None, trip_id=match.trip_id, request_id=match.request_id)
    except (ValueError, BusinessError) as error:
        text = error.message if isinstance(error, BusinessError) else "Suhbat ochilshida xatolik."
        await callback.answer(text, show_alert=True)
        return
    await callback.answer("Suhbat ochildi!")
    if callback.message:
        await callback.message.answer(
            f"Suhbatga ochildi! Yo'lovchi: {thread.order.passenger.display_name}. "
            f"Buyurtma #{thread.order_id} bo'yicha suhbat ochildi."
        )


@router.callback_query(F.data.startswith("request:cancel:"))
async def cancel_request(callback: CallbackQuery) -> None:
    try:
        request_id = int(callback.data.rsplit(":", maxsplit=1)[1])
        passenger_request = await platform.cancel_passenger_request_for_user(
            callback.from_user.id,
            request_id,
        )
    except (ValueError, BusinessError) as error:
        text = error.message if isinstance(error, BusinessError) else "So'rov tugmasi noto'g'ri."
        await callback.answer(text, show_alert=True)
        return
    await callback.answer("So'rov bekor qilindi.")
    if callback.message:
        await callback.message.edit_text(
            f"So'rov #{passenger_request.pk} bekor qilindi."
        )


@router.callback_query(F.data.startswith("refresh_matches:"))
async def refresh_matches(callback: CallbackQuery) -> None:
    try:
        request_id = int(callback.data.partition(":")[2])
        matches = await platform.get_matching_for_user(callback.from_user.id, request_id)
    except (ValueError, BusinessError) as error:
        text = error.message if isinstance(error, BusinessError) else "So'rov tugmasi noto'g'ri."
        await callback.answer(text, show_alert=True)
        return
    await callback.answer()
    if not callback.message:
        return
    if matches:
        await _send_matches(callback.message, request_id, matches)
    else:
        await callback.message.answer("Hozircha boshqa mos yo'lov topilmadi.")


@router.message(StateFilter(
    PassengerRequestStates.waiting_for_origin,
    PassengerRequestStates.waiting_for_destination,
))
async def location_invalid_input(message: Message) -> None:
    await message.answer(
        "Manzilni Telegram lokatsiya sifatida yuboring.",
        reply_markup=location_keyboard(),
    )


@router.message(StateFilter(
    PassengerRequestStates.waiting_for_passenger_count,
    PassengerRequestStates.waiting_for_departure_date,
    PassengerRequestStates.waiting_for_departure_time,
    PassengerRequestStates.waiting_for_max_price,
    PassengerRequestStates.waiting_for_comment,
))
async def passenger_text_step_invalid_input(message: Message, state: FSMContext) -> None:
    current = await state.get_state()
    if current == PassengerRequestStates.waiting_for_departure_date.state:
        await message.answer(
            "Sana tanlash uchun tugmalardan foydalaning:",
            reply_markup=await make_date_keyboard(),
        )
        return
    if current == PassengerRequestStates.waiting_for_departure_time.state:
        data = await state.get_data()
        date_str = data.get("departure_date_str")
        if date_str:
            await message.answer(
                "Vaqtni tanlash uchun tugmalardan foydalaning:",
                reply_markup=await make_time_keyboard(date_str),
            )
        else:
            await state.set_state(PassengerRequestStates.waiting_for_departure_date)
            await message.answer(
                "Avval sanani tanlang:",
                reply_markup=await make_date_keyboard(),
            )
        return
    await message.answer("Bu bosqichda matn yuboring yoki /cancel buyrug'ini bosing.")


@router.callback_query(F.data == "cancel_flow")
async def cancel_flow(callback: CallbackQuery, state: FSMContext) -> None:
    """Cancel the current flow and return to the main menu."""
    from aiogram.exceptions import TelegramBadRequest

    await state.clear()
    if callback.message:
        try:
            user = await platform.get_user(callback.from_user.id)
            is_driver = user.is_driver_role
        except BusinessError:
            is_driver = False
        try:
            await callback.message.edit_text("Amal bekor qilindi.")
        except TelegramBadRequest:
            pass
        await callback.message.answer(
            "Asosiy menyu:",
            reply_markup=main_menu_keyboard(is_driver),
        )
    await callback.answer()


@router.callback_query(
    F.data == "edit_request",
    PassengerRequestStates.waiting_for_confirmation,
)
async def edit_request(callback: CallbackQuery, state: FSMContext) -> None:
    """Restart the request flow so its details can be corrected."""
    await state.clear()
    await state.set_state(PassengerRequestStates.waiting_for_origin)
    if callback.message:
        await callback.message.edit_text("So'rovni boshidan tahrirlashni boshlaymiz.")
        await callback.message.answer(
            "📍 <b>Qo'shilish manzilini yuboring:</b>\n\n"
            "Pastdagi tugma orqali lokatsiyangizni yuboring.",
            parse_mode="HTML",
            reply_markup=location_keyboard(),
        )
    await callback.answer()