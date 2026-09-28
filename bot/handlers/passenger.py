"""Passenger handlers — ride requests, orders, and matching."""

from __future__ import annotations

import html
import logging
import re
from datetime import datetime, time

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from apps.core.exceptions import BusinessError

from bot.keyboards import cancel_keyboard
from bot.services import platform
from bot.states import PassengerRequestStates
from bot.services.passenger import (
    create_passenger_request,
    get_matching_trips,
    format_matches_for_user,
    get_my_requests,
    get_my_orders,
)

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


@router.message(F.text == "📝 So'rov yaratish")
async def start_passenger_request(message: Message, state: FSMContext) -> None:
    """Start creating a passenger request."""
    await state.set_state(PassengerRequestStates.waiting_for_origin)
    await message.answer(
        "📍 <b>Qo'shilish manzilini tanlang:</b>\n\n"
        "Manzilni yuboring yoki ro'yxatdan tanlang.",
        parse_mode="HTML",
        reply_markup=cancel_keyboard(),
    )


@router.message(PassengerRequestStates.waiting_for_origin, F.location)
async def handle_origin_location(message: Message, state: FSMContext) -> None:
    """Handle origin location selection."""
    from bot.services.locations import get_nearest_location_from_coordinates

    try:
        location = await get_nearest_location_from_coordinates(
            message.location.latitude, message.location.longitude
        )
    except BusinessError as error:
        await message.answer(html.escape(error.message))
        return
    await state.update_data(
        origin_location_id=location.pk,
        origin_location_name=location.name,
    )
    await state.set_state(PassengerRequestStates.waiting_for_destination)

    await message.answer(
        f"✅ Manba: <b>{html.escape(location.name)}</b>\n\n"
        "📍 Endi <b>qo'nish manzilini</b> tanlang:",
        parse_mode="HTML",
        reply_markup=cancel_keyboard(),
    )


@router.message(PassengerRequestStates.waiting_for_destination, F.location)
async def handle_destination_location(message: Message, state: FSMContext) -> None:
    """Handle destination location selection."""
    from bot.services.locations import get_nearest_location_from_coordinates

    try:
        location = await get_nearest_location_from_coordinates(
            message.location.latitude, message.location.longitude
        )
    except BusinessError as error:
        await message.answer(html.escape(error.message))
        return
    data = await state.get_data()
    if location.pk == data.get("origin_location_id"):
        await message.answer("Borish manzili jo'nash manzilidan farq qilishi kerak.")
        return
    await state.update_data(
        destination_location_id=location.pk,
        destination_location_name=location.name,
    )
    await state.set_state(PassengerRequestStates.waiting_for_passenger_count)

    await message.answer(
        f"✅ Maqsad: <b>{html.escape(location.name)}</b>\n\n"
        "👥 <b>Yo'lovchilar sonini kiriting (1-9):</b>",
        parse_mode="HTML",
        reply_markup=cancel_keyboard(),
    )


@router.message(PassengerRequestStates.waiting_for_passenger_count, F.text.isdigit())
async def handle_passenger_count(message: Message, state: FSMContext) -> None:
    """Handle passenger count input."""
    count = int(message.text)
    if count < 1 or count > 9:
        await message.answer("Iltimos, 1 dan 9 gacha son kiriting.")
        return

    await state.update_data(passenger_count=count)
    await state.set_state(PassengerRequestStates.waiting_for_departure_date)

    await message.answer(
        "📅 <b>Chuqish kunini kiriting (DD.MM.YYYY):</b>\n\n"
        "Masalan: 28.09.2026",
        parse_mode="HTML",
        reply_markup=cancel_keyboard(),
    )


@router.message(PassengerRequestStates.waiting_for_passenger_count, F.text)
async def handle_invalid_passenger_count(message: Message) -> None:
    """Explain the accepted format when passenger count is not numeric."""
    await message.answer("Yo'lovchilar sonini 1 dan 9 gacha butun son bilan kiriting.")


@router.message(PassengerRequestStates.waiting_for_departure_date, F.text)
async def handle_departure_date(message: Message, state: FSMContext) -> None:
    """Handle departure date input."""
    if not re.match(r"^\d{2}\.\d{2}\.\d{4}$", message.text):
        await message.answer("Noto'g'ri format. Iltimos DD.MM.YYYY formatida kiriting.")
        return

    try:
        date = datetime.strptime(message.text, "%d.%m.%Y").date()
    except ValueError:
        await message.answer("Noto'g'ri sana. Qayta urinib ko'ring.")
        return

    await state.update_data(departure_date=date)
    await state.set_state(PassengerRequestStates.waiting_for_departure_time)

    await message.answer(
        "🕐 <b>Chuqish vaqtini kiriting (HH:MM):</b>\n\n"
        "Masalan: 18:30",
        parse_mode="HTML",
        reply_markup=cancel_keyboard(),
    )


@router.message(PassengerRequestStates.waiting_for_departure_time, F.text)
async def handle_departure_time(message: Message, state: FSMContext) -> None:
    """Handle departure time input."""
    if not re.match(r"^\d{2}:\d{2}$", message.text):
        await message.answer("Noto'g'ri format. Iltimos HH:MM formatida kiriting.")
        return

    try:
        t = time(*map(int, message.text.split(":")))
    except ValueError:
        await message.answer("Noto'g'ri vaqt. Qayta urinib ko'ring.")
        return

    await state.update_data(departure_time=t)
    await state.set_state(PassengerRequestStates.waiting_for_max_price)

    await message.answer(
        "💰 <b>Maksimal narxni kiriting (so'm, ixtiyoriy):</b>\n\n"
        "Agar cheklov yo'q bo'lsa, '0' yoki hech narsa yozmasdan keyingi bosqichga o'ting.",
        parse_mode="HTML",
        reply_markup=cancel_keyboard(),
    )


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

    summary = (
        "📋 <b>So'rovingiz tasdiqlash uchun:</b>\n\n"
        f"📍 Qayerdan: <b>{html.escape(data.get('origin_location_name', 'Noma\'lum'))}</b>\n"
        f"📍 Qayerga: <b>{html.escape(data.get('destination_location_name', 'Noma\'lum'))}</b>\n"
        f"👥 Yo'lovchilar: <b>{data.get('passenger_count', 1)}</b>\n"
        f"📅 Sana: <b>{data.get('departure_date', 'Noma\'lum')}</b>\n"
        f"🕐 Vaqt: <b>{data.get('departure_time', 'Noma\'lum')}</b>\n"
    )
    if data.get("max_price_per_seat"):
        summary += f"💰 Maksimal narx: <b>{data['max_price_per_seat']:,} so'm</b>\n"
    if data.get("comment"):
        summary += f"💬 Izoh: <b>{html.escape(data['comment'])}</b>\n"

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

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

    # Create the request through Django service
    from bot.services.passenger import create_passenger_request

    try:
        request = await create_passenger_request(
            user_id=callback.from_user.id,
            origin_location_id=data["origin_location_id"],
            destination_location_id=data["destination_location_id"],
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
    except BusinessError as error:
        await callback.message.edit_text(
            f"❌ {html.escape(error.message)}\n\n"
            "Qayta urinib ko'ring."
        )
    except Exception:
        logger.exception("Passenger request creation failed")
        await callback.message.edit_text("❌ Kutilmagan xatolik yuz berdi. Keyinroq qayta urinib ko'ring.")


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
            f"#{req.id}: {req.from_location.name} → {req.to_location.name}\n"
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


@router.message(F.text == "🔍 Yo'lov topish")
async def find_ride(message: Message, user_id: int | None = None) -> None:
    """Show active requests that can be matched."""
    from bot.services.passenger import get_active_requests

    requests = await get_active_requests(user_id or message.from_user.id)
    if not requests:
        await message.answer("Sizda faol so'rovlar yo'q. Avval so'rov yarating.")
        return

    for passenger_request in requests:
        matches = await get_matching_trips(passenger_request.pk)
        if matches:
            await _send_matches(message, passenger_request.pk, matches)
        else:
            await message.answer(
                f"So'rov #{passenger_request.pk} uchun hozircha mos yo'lov topilmadi."
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
    await message.answer("Manzilni Telegram lokatsiya sifatida yuboring yoki /cancel bosing.")


@router.message(StateFilter(
    PassengerRequestStates.waiting_for_passenger_count,
    PassengerRequestStates.waiting_for_departure_date,
    PassengerRequestStates.waiting_for_departure_time,
    PassengerRequestStates.waiting_for_max_price,
    PassengerRequestStates.waiting_for_comment,
))
async def passenger_text_step_invalid_input(message: Message) -> None:
    await message.answer("Bu bosqichda matn yuboring yoki /cancel buyrug'ini bosing.")


@router.callback_query(F.data == "cancel_flow")
async def cancel_flow(callback: CallbackQuery, state: FSMContext) -> None:
    """Cancel the current passenger flow."""
    await state.clear()
    if callback.message:
        await callback.message.edit_text("Amal bekor qilindi.")
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
            "📍 <b>Qo'shilish manzilini tanlang:</b>",
            parse_mode="HTML",
            reply_markup=cancel_keyboard(),
        )
    await callback.answer()