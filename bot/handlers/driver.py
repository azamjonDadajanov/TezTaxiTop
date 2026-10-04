"""Driver onboarding, vehicle, trip, and matching-request workflows."""

from __future__ import annotations

import html
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone

from apps.core.exceptions import BusinessError
from bot.keyboards import (
    cancel_keyboard,
    location_keyboard,
    main_menu_keyboard,
    make_date_keyboard,
    make_time_keyboard,
)
from bot.services import platform
from bot.services.locations import (
    describe_point,
    normalize_location,
    route_distance_km,
    route_error,
)
from bot.states import DriverRegistrationStates, DriverTripStates

router = Router(name="driver")


def _parse_departure(date_str: str, time_str: str) -> datetime:
    """Parse 'DD.MM.YYYY' and 'HH:MM' into an aware datetime."""
    naive = datetime.strptime(f"{date_str} {time_str}", "%d.%m.%Y %H:%M")  # noqa: DTZ007
    return timezone.make_aware(naive)


AVERAGE_SPEED_KMH = 40.0
CONFLICT_WINDOW = timedelta(hours=3)


def _estimated_minutes(distance_km: float) -> int:
    """Estimate driving time from distance at an average city speed."""
    return max(5, round(distance_km * 60 / AVERAGE_SPEED_KMH))


def _find_conflicting_trip(trips, departure):
    """Return an active trip departing within the conflict window, if any."""
    for trip in trips:
        if trip.status not in {"draft", "active", "full"}:
            continue
        if abs((trip.departure_time - departure).total_seconds()) <= CONFLICT_WINDOW.total_seconds():
            return trip
    return None


def conflict_keyboard() -> InlineKeyboardMarkup:
    """Yes/No buttons for cancelling a conflicting trip."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Ha, bekor qilaman", callback_data="tripconflict:yes"),
                InlineKeyboardButton(text="❌ Yo'q", callback_data="tripconflict:no"),
            ]
        ]
    )


async def _ask_seats(message: Message, state: FSMContext, departure: datetime) -> None:
    """Ask for seat count, including the estimated arrival time."""
    await state.set_state(DriverTripStates.waiting_for_seats)
    data = await state.get_data()
    lines = [f"🕐 Jo'nash: {departure:%d.%m.%Y %H:%M}"]
    distance = data.get("distance_km")
    if distance:
        minutes = _estimated_minutes(distance)
        arrival = departure + timedelta(minutes=minutes)
        hours, mins = divmod(minutes, 60)
        duration = f"{hours} soat {mins} daq" if hours else f"{mins} daq"
        lines.append(f"🛣 Taxminiy yo'l: {duration} ({distance:.1f} km)")
        lines.append(f"🏁 Taxminiy yetib borish: {arrival:%d.%m.%Y %H:%M}")
    lines.append("Yo'lovchilar uchun nechta o'rin bor? (1-9)")
    await message.answer("\n".join(lines), reply_markup=cancel_keyboard())


async def _proceed_after_departure(
    message: Message,
    state: FSMContext,
    user_id: int,
    departure: datetime,
) -> None:
    """Store departure, check for conflicts, then ask for seats."""
    await state.update_data(departure_time=departure)
    conflict = None
    try:
        trips = await platform.get_driver_trips(user_id)
        conflict = _find_conflicting_trip(trips, departure)
    except BusinessError:
        conflict = None
    if conflict is not None:
        await state.update_data(conflict_trip_id=conflict.pk)
        await state.set_state(DriverTripStates.waiting_for_trip_conflict)
        await message.answer(
            "⚠️ Bu vaqtda boshqa yo'lovingiz bor:\n"
            f"{html.escape(conflict.route_label())} · "
            f"{timezone.localtime(conflict.departure_time):%d.%m.%Y %H:%M}\n\n"
            "Oldingi yo'nalishni bekor qilasizmi?",
            reply_markup=conflict_keyboard(),
        )
        return
    await _ask_seats(message, state, departure)


async def start_vehicle_registration(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(DriverRegistrationStates.waiting_for_vehicle_brand)
    await message.answer("Avtomobil brendini kiriting (masalan, Chevrolet):")


async def show_vehicles(message: Message, user_id: int | None = None) -> None:
    try:
        vehicles = await platform.get_driver_vehicles(user_id or message.from_user.id)
    except BusinessError as error:
        await message.answer(html.escape(error.message))
        return
    lines = ["<b>Avtomobillarim</b>"]
    for vehicle in vehicles:
        verification = "tasdiqlangan" if vehicle.is_verified else "tasdiqlash kutilmoqda"
        active = "faol" if vehicle.is_active else "o'chirilgan"
        lines.append(
            f"#{vehicle.pk} · {html.escape(vehicle.display_name)} · "
            f"{vehicle.seats_for_passengers} yo'lovchi o'rni · {verification}, {active}"
        )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="➕ Avtomobil qo'shish", callback_data="vehicle:add")]]
    )
    await message.answer("\n".join(lines) if vehicles else "Avtomobillar ro'yxati bo'sh.", parse_mode="HTML", reply_markup=keyboard)


@router.callback_query(F.data == "vehicle:add")
async def vehicle_registration_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(DriverRegistrationStates.waiting_for_vehicle_brand)
    if callback.message:
        await callback.message.answer("Avtomobil brendini kiriting (masalan, Chevrolet):")
    await callback.answer()


@router.message(DriverRegistrationStates.waiting_for_vehicle_brand, F.text)
async def vehicle_brand(message: Message, state: FSMContext) -> None:
    await state.update_data(brand=message.text.strip())
    await state.set_state(DriverRegistrationStates.waiting_for_vehicle_model)
    await message.answer("Avtomobil modelini kiriting:")


@router.message(DriverRegistrationStates.waiting_for_vehicle_model, F.text)
async def vehicle_model(message: Message, state: FSMContext) -> None:
    await state.update_data(model=message.text.strip())
    await state.set_state(DriverRegistrationStates.waiting_for_vehicle_color)
    await message.answer("Avtomobil rangini kiriting:")


@router.message(DriverRegistrationStates.waiting_for_vehicle_color, F.text)
async def vehicle_color(message: Message, state: FSMContext) -> None:
    await state.update_data(color=message.text.strip())
    await state.set_state(DriverRegistrationStates.waiting_for_vehicle_plate)
    await message.answer("Davlat raqamini kiriting (masalan, 01B 123AA):")


@router.message(DriverRegistrationStates.waiting_for_vehicle_plate, F.text)
async def vehicle_plate(message: Message, state: FSMContext) -> None:
    await state.update_data(plate_number=message.text.strip())
    await state.set_state(DriverRegistrationStates.waiting_for_vehicle_year)
    await message.answer("Ishlab chiqarilgan yilini kiriting:")


@router.message(DriverRegistrationStates.waiting_for_vehicle_year, F.text)
async def vehicle_year(message: Message, state: FSMContext) -> None:
    try:
        year = int(message.text)
    except ValueError:
        await message.answer("Yilni raqam bilan kiriting.")
        return
    await state.update_data(year=year)
    await state.set_state(DriverRegistrationStates.waiting_for_vehicle_seats)
    await message.answer("Jami o'rindiqlar sonini kiriting (haydovchi o'rni bilan):")


@router.message(DriverRegistrationStates.waiting_for_vehicle_seats, F.text)
async def vehicle_seats(message: Message, state: FSMContext) -> None:
    try:
        seats_count = int(message.text)
        if not 2 <= seats_count <= 20:
            raise ValueError
        data = await state.get_data()
        vehicle = await platform.create_vehicle(
            message.from_user.id,
            **data,
            seats_count=seats_count,
        )
    except (ValueError, BusinessError) as error:
        text = error.message if isinstance(error, BusinessError) else "O'rindiqlar soni 2 dan 20 gacha bo'lishi kerak."
        await message.answer(html.escape(text))
        return
    await state.clear()
    await message.answer(
        f"Avtomobil #{vehicle.pk} saqlandi. Yo'lov e'lon qilishdan oldin administrator tasdiqlashi kerak.",
        reply_markup=main_menu_keyboard(is_driver=True),
    )


async def start_trip_creation(
    message: Message,
    state: FSMContext,
    user_id: int | None = None,
) -> None:
    await state.clear()
    try:
        vehicles = await platform.get_driver_vehicles(user_id or message.from_user.id)
    except BusinessError as error:
        await message.answer(html.escape(error.message))
        return
    usable = [vehicle for vehicle in vehicles if vehicle.is_active and vehicle.is_verified]
    if not usable:
        await message.answer("Yo'lov e'lon qilish uchun faol va tasdiqlangan avtomobil kerak. Avval '🚙 Avtomobillarim' bo'limidan avtomobil qo'shing.")
        return
    await state.set_state(DriverTripStates.waiting_for_vehicle)
    buttons = []
    for vehicle in usable:
        buttons.append([InlineKeyboardButton(
            text=html.escape(vehicle.display_name),
            callback_data=f"trip:select_vehicle:{vehicle.pk}"
        )])
    buttons.append([InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel_flow")])
    await message.answer("Avtomobilni tanlang:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@router.callback_query(F.data.startswith("trip:select_vehicle:"))
async def trip_select_vehicle_callback(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        vehicle_id = int(callback.data.split(":")[-1])
        vehicles = await platform.get_driver_vehicles(callback.from_user.id)
        vehicle = next(vehicle for vehicle in vehicles if vehicle.pk == vehicle_id and vehicle.is_active and vehicle.is_verified)
    except (ValueError, StopIteration, BusinessError) as error:
        text = error.message if isinstance(error, BusinessError) else "Avtomobil tanlashda xatolik."
        if callback.message:
            await callback.message.answer(html.escape(text))
        await callback.answer()
        return
    await state.update_data(vehicle_id=vehicle.pk)
    await state.set_state(DriverTripStates.waiting_for_origin)
    if callback.message:
        await callback.message.edit_text("Avtomobil tanlandi.")
        await callback.message.answer(
            "Jo'nash manzilini yuboring:",
            reply_markup=location_keyboard(),
        )
    await callback.answer()


@router.message(DriverTripStates.waiting_for_origin, F.location)
async def trip_origin(message: Message, state: FSMContext) -> None:
    try:
        point = await normalize_location(
            message.location.latitude,
            message.location.longitude,
        )
    except BusinessError as error:
        await message.answer(html.escape(error.message))
        return
    await state.update_data(origin=point, origin_label=describe_point(point))
    await state.set_state(DriverTripStates.waiting_for_destination)
    await message.answer(
        f"Jo'nash nuqtasi: {html.escape(describe_point(point))}\n"
        "Endi borish nuqtasini yuboring:",
        reply_markup=location_keyboard(),
    )


@router.message(DriverTripStates.waiting_for_destination, F.location)
async def trip_destination(message: Message, state: FSMContext) -> None:
    try:
        point = await normalize_location(
            message.location.latitude,
            message.location.longitude,
        )
    except BusinessError as error:
        await message.answer(html.escape(error.message))
        return
    data = await state.get_data()
    origin = data.get("origin")
    if origin is None:
        await message.answer("Avval jo'nash nuqtasini yuboring.")
        return
    error = route_error(origin, point)
    if error:
        await message.answer(error)
        return
    distance = route_distance_km(origin, point)
    await state.update_data(
        destination=point,
        destination_label=describe_point(point),
        distance_km=distance,
    )
    await state.set_state(DriverTripStates.waiting_for_departure_datetime)
    await message.answer(
        f"Borish nuqtasi: {html.escape(describe_point(point))}\n"
        f"Masofa: ~{distance:.1f} km · "
        f"taxminiy yo'l: {_estimated_minutes(distance)} daq\n"
        "Yo'lga chiqish sanasini tanlang:",
        reply_markup=await make_date_keyboard(),
    )


@router.message(DriverTripStates.waiting_for_departure_datetime, F.text)
async def trip_departure_text(message: Message, state: FSMContext) -> None:
    try:
        date_str, time_str = message.text.strip().split(" ", maxsplit=1)
        departure = _parse_departure(date_str, time_str)
        if departure <= timezone.now():
            raise ValueError
    except ValueError:
        await message.answer(
            "Noto'g'ri format. Sana va vaqtni quyidagi kalendardan tanlang:",
            reply_markup=await make_date_keyboard(),
        )
        return
    await _proceed_after_departure(message, state, message.from_user.id, departure)


@router.callback_query(
    StateFilter(DriverTripStates.waiting_for_departure_datetime),
    F.data.startswith("datetime:"),
)
async def trip_departure_datetime_callback(callback: CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split(":", maxsplit=3)
    if parts[1] == "date":
        date_str = parts[2]
        if callback.message:
            await callback.message.edit_text(
                f"📅 Sana: {date_str}\nVaqtni tanlang:",
                reply_markup=await make_time_keyboard(date_str),
            )
        await callback.answer()
        return
    if parts[1] == "back":
        if callback.message:
            await callback.message.edit_text(
                "Yo'lga chiqish sanasini tanlang:",
                reply_markup=await make_date_keyboard(),
            )
        await callback.answer()
        return
    try:
        date_str = parts[2]
        time_str = parts[3]
        departure = _parse_departure(date_str, time_str)
        if departure <= timezone.now():
            raise ValueError
    except (IndexError, ValueError):
        await callback.answer("Bu vaqt o'tib ketgan, boshqa sana tanlang.", show_alert=True)
        return
    if callback.message:
        await callback.message.edit_text(f"🕐 Jo'nash vaqti: {date_str} {time_str}")
    await callback.answer("Sana va vaqt tanlandi")
    if callback.message:
        await _proceed_after_departure(callback.message, state, callback.from_user.id, departure)


@router.callback_query(
    StateFilter(DriverTripStates.waiting_for_trip_conflict),
    F.data == "tripconflict:yes",
)
async def trip_conflict_yes(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    trip_id = data.get("conflict_trip_id")
    departure = data.get("departure_time")
    if trip_id is None or departure is None:
        await state.clear()
        await callback.answer("Ma'lumot topilmadi.", show_alert=True)
        return
    try:
        await platform.transition_trip(callback.from_user.id, int(trip_id), "cancel")
    except (ValueError, TypeError, BusinessError) as error:
        text = error.message if isinstance(error, BusinessError) else "Bekor qilib bo'lmadi."
        await callback.answer(html.escape(text), show_alert=True)
        return
    if callback.message:
        await callback.message.edit_text("✅ Eski yo'nalish bekor qilindi.")
        await _ask_seats(callback.message, state, departure)
    await callback.answer("Eski yo'nalish bekor qilindi")


@router.callback_query(
    StateFilter(DriverTripStates.waiting_for_trip_conflict),
    F.data == "tripconflict:no",
)
async def trip_conflict_no(callback: CallbackQuery, state: FSMContext) -> None:
    from aiogram.exceptions import TelegramBadRequest

    await state.clear()
    if callback.message:
        try:
            await callback.message.edit_text(
                "Amal bekor qilindi. Eski yo'nalish o'z holida qoldi."
            )
        except TelegramBadRequest:
            pass
        await callback.message.answer(
            "Asosiy menyu:",
            reply_markup=main_menu_keyboard(is_driver=True),
        )
    await callback.answer()


@router.message(DriverTripStates.waiting_for_seats, F.text)
async def trip_seats(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    vehicle_id = data.get("vehicle_id")
    try:
        seats = int(message.text)
        if not 1 <= seats <= 9:
            raise ValueError
        vehicles = await platform.get_driver_vehicles(message.from_user.id)
        vehicle = next(v for v in vehicles if v.pk == vehicle_id)
    except ValueError:
        await message.answer(
            "O'rinlar sonini 1 dan 9 gacha kiriting:",
            reply_markup=cancel_keyboard(),
        )
        return
    except (StopIteration, BusinessError):
        await message.answer(
            "Avtomobil topilmadi, qaytadan urinib ko'ring:",
            reply_markup=cancel_keyboard(),
        )
        return
    if seats > vehicle.seats_for_passengers:
        await message.answer(
            f"Bu avtomobilda {vehicle.seats_for_passengers} ta o'rin mavjud. "
            "Qaytadan yo'lovchilar sonini kiriting:",
            reply_markup=cancel_keyboard(),
        )
        return
    await state.update_data(total_seats=seats)
    await state.set_state(DriverTripStates.waiting_for_price)
    await message.answer("Bir o'rin narxini so'mda kiriting:", reply_markup=cancel_keyboard())


@router.message(DriverTripStates.waiting_for_price, F.text)
async def trip_price(message: Message, state: FSMContext) -> None:
    try:
        price = Decimal(message.text.strip().replace(" ", ""))
        if price < 0:
            raise InvalidOperation
    except (InvalidOperation, ValueError):
        await message.answer("Narxni manfiy bo'lmagan son bilan kiriting.")
        return
    await state.update_data(price_per_seat=price)
    await state.set_state(DriverTripStates.waiting_for_comment)
    await message.answer("Izoh kiriting yoki '-' yuboring:", reply_markup=cancel_keyboard())


@router.message(DriverTripStates.waiting_for_comment, F.text)
async def trip_comment(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    try:
        trip = await platform.create_trip(
            message.from_user.id,
            data["vehicle_id"],
            data["origin"],
            data["destination"],
            departure_time=data["departure_time"],
            total_seats=data["total_seats"],
            price_per_seat=data["price_per_seat"],
            comment="" if message.text.strip() == "-" else message.text.strip(),
        )
    except BusinessError as error:
        text = html.escape(error.message)
        await message.answer(text)
        if "o'rin" in error.message:
            await state.set_state(DriverTripStates.waiting_for_seats)
            await message.answer(
                "Yo'lovchilar uchun nechta o'rin bor? (1-9)",
                reply_markup=cancel_keyboard(),
            )
            return
        await state.clear()
        await message.answer(
            "Yo'lov yaratilmadi. Qaytadan urinib ko'ring:",
            reply_markup=main_menu_keyboard(is_driver=True),
        )
        return
    except DjangoValidationError as error:
        text = " ".join(str(item) for item in error.messages) or "Kiritilgan ma'lumot noto'g'ri."
        await message.answer(html.escape(text))
        await state.clear()
        await message.answer(
            "Yo'lov yaratilmadi. Qaytadan urinib ko'ring:",
            reply_markup=main_menu_keyboard(is_driver=True),
        )
        return
    except (KeyError, TypeError, ValueError):
        await state.clear()
        await message.answer(
            "Ma'lumotlar to'liq emas, yo'lov yaratishni boshidan boshlang:",
            reply_markup=main_menu_keyboard(is_driver=True),
        )
        return
    await state.clear()
    await message.answer(f"Yo'lov #{trip.pk} e'lon qilindi. Holati: {trip.get_status_display()}.")
    await message.answer(
        "Asosiy menyu:",
        reply_markup=main_menu_keyboard(is_driver=True),
    )


async def show_driver_trips(message: Message, user_id: int | None = None) -> None:
    try:
        trips = await platform.get_driver_trips(user_id or message.from_user.id)
    except BusinessError as error:
        await message.answer(html.escape(error.message))
        return
    if not trips:
        await message.answer("Siz hali yo'lov e'lon qilmagansiz.")
        return
    for trip in trips:
        text = (
            f"<b>Yo'lov #{trip.pk}</b> · {html.escape(trip.get_status_display())}\n"
            f"{html.escape(trip.route_label())}\n"
            f"🕐 {timezone.localtime(trip.departure_time):%d.%m.%Y %H:%M} · "
            f"💺 {trip.available_seats}/{trip.total_seats} · {trip.price_per_seat:,.0f} so'm"
        )
        actions = []
        if trip.status == "draft":
            actions.append([InlineKeyboardButton(text="E'lon qilish", callback_data=f"trip:publish:{trip.pk}")])
        if trip.status in {"draft", "active", "full"}:
            actions.append([InlineKeyboardButton(text="Bekor qilish", callback_data=f"trip:cancel:{trip.pk}")])
        markup = InlineKeyboardMarkup(inline_keyboard=actions) if actions else None
        await message.answer(text, parse_mode="HTML", reply_markup=markup)
    # After showing all trips, show main menu with song lyrics
    await message.answer(
        "Asosiy menyu:", 
        reply_markup=main_menu_keyboard(is_driver=True)
    )


async def show_driver_requests(message: Message, user_id: int | None = None) -> None:
    try:
        requests = await platform.get_driver_requests(user_id or message.from_user.id)
    except BusinessError as error:
        await message.answer(html.escape(error.message))
        return
    if not requests:
        await message.answer("Faol yo'lovlaringiz marshrutiga mos so'rov topilmadi.")
        return
    for request in requests:
        text = (
            f"<b>So'rov #{request.pk}</b> · {request.passenger_count} kishi\n"
            f"{html.escape(request.origin_display)} → {html.escape(request.destination_display)}\n"
            f"🕐 {timezone.localtime(request.departure_from):%d.%m.%Y %H:%M}\n"
            f"Maksimal narx: {request.max_price_per_seat or 'cheklanmagan'} so'm\n"
            f"Haydovchi: {html.escape(request.passenger.display_name)}\n\n"
            f"Boshlanish vaqti: {timezone.localtime(request.departure_from).strftime('%d.%m.%Y %H:%M')}\n"
        )
        actions = []
        # Driver can book this passenger if there's a compatible trip
        actions.append([InlineKeyboardButton(text="📕 Band qilish", callback_data=f"book_request:{request.pk}")])
        actions.append([InlineKeyboardButton(text="💬 Suhbat", callback_data=f"chat_request:{request.pk}")])
        markup = InlineKeyboardMarkup(inline_keyboard=actions)
        await message.answer(text, parse_mode="HTML", reply_markup=markup)


@router.callback_query(F.data.startswith("book_request:"))
async def book_request_from_driver(callback: CallbackQuery) -> None:
    try:
        request_id = int(callback.data.partition(":")[2])
        order = await platform.book_driver_request(callback.from_user.id, request_id)
    except (ValueError, BusinessError) as error:
        text = error.message if isinstance(error, BusinessError) else "So'rov band qilishda xatolik."
        await callback.answer(text, show_alert=True)
        return
    await callback.answer(f"Buyurtma #{order.pk} yaratildi. Holati: {order.get_status_display()}. "
                         "O'rinlar qabul qilgandan keyin band qilinadi.")
    if callback.message:
        await callback.message.edit_text(
            f"Buyurtma #{order.pk} yaratildi. Holati: {order.get_status_display()}. "
            "O'rinlar haydovchi qabul qilgandan keyin band qilinadi."
        )


@router.callback_query(F.data.startswith("chat_request:"))
async def chat_request_from_driver(callback: CallbackQuery) -> None:
    try:
        request_id = int(callback.data.partition(":")[2])
        from bot.services.platform import open_chat_for_request
        thread, created = await open_chat_for_request(callback.from_user.id, request_id)
    except (ValueError, BusinessError) as error:
        text = error.message if isinstance(error, BusinessError) else "Suhbat ochilshida xatolik."
        await callback.answer(text, show_alert=True)
        return
    await callback.answer(f"Suhbat ochildi{' (ja\'lanib)' if not created else ''}")
    if callback.message:
        await callback.message.answer(
            f"Suhbatga ochildi! Yo'lovchi: {thread.order.passenger.display_name}. "
            f"Buyurtma #{thread.order_id} bo'yicha suhbat ochildi."
        )


@router.callback_query(F.data.startswith("trip:"))
async def trip_action(callback: CallbackQuery) -> None:
    try:
        _, action, trip_id = callback.data.split(":", maxsplit=2)
        trip = await platform.transition_trip(callback.from_user.id, int(trip_id), action)
    except (ValueError, BusinessError) as error:
        text = error.message if isinstance(error, BusinessError) else "Yo'lov tugmasi noto'g'ri."
        await callback.answer(text, show_alert=True)
        return
    await callback.answer(f"Yo'lov holati: {trip.get_status_display()}")
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=None)


@router.message(StateFilter(
    DriverRegistrationStates.waiting_for_vehicle_brand,
    DriverRegistrationStates.waiting_for_vehicle_model,
    DriverRegistrationStates.waiting_for_vehicle_color,
    DriverRegistrationStates.waiting_for_vehicle_plate,
    DriverRegistrationStates.waiting_for_vehicle_year,
    DriverRegistrationStates.waiting_for_vehicle_seats,
))
async def vehicle_invalid_input(message: Message, state: FSMContext) -> None:
    prompts = {
        DriverRegistrationStates.waiting_for_vehicle_brand.state: "Brendni matn bilan yuboring.",
        DriverRegistrationStates.waiting_for_vehicle_model.state: "Modelni matn bilan yuboring.",
        DriverRegistrationStates.waiting_for_vehicle_color.state: "Rangni matn bilan yuboring.",
        DriverRegistrationStates.waiting_for_vehicle_plate.state: "Davlat raqamini matn bilan yuboring.",
        DriverRegistrationStates.waiting_for_vehicle_year.state: "Yilni raqam bilan yuboring.",
        DriverRegistrationStates.waiting_for_vehicle_seats.state: "O'rindiqlar sonini raqam bilan yuboring.",
    }
    await message.answer(prompts.get(await state.get_state(), "Kutilgan formatda yuboring."))


@router.message(StateFilter(
    DriverTripStates.waiting_for_vehicle,
    DriverTripStates.waiting_for_origin,
    DriverTripStates.waiting_for_destination,
    DriverTripStates.waiting_for_departure_datetime,
    DriverTripStates.waiting_for_trip_conflict,
    DriverTripStates.waiting_for_seats,
    DriverTripStates.waiting_for_price,
    DriverTripStates.waiting_for_comment,
))
async def trip_invalid_input(message: Message, state: FSMContext) -> None:
    current = await state.get_state()
    if current in {
        DriverTripStates.waiting_for_origin.state,
        DriverTripStates.waiting_for_destination.state,
    }:
        await message.answer(
            "Manzilni Telegram lokatsiya sifatida yuboring:",
            reply_markup=location_keyboard(),
        )
    elif current == DriverTripStates.waiting_for_vehicle.state:
        await message.answer("Avtomobilni quyidagi tugmalar orqali tanlang.")
    elif current == DriverTripStates.waiting_for_trip_conflict.state:
        await message.answer(
            "Oldingi yo'nalishni bekor qilasizmi?",
            reply_markup=conflict_keyboard(),
        )
    else:
        await message.answer(
            "Kutilgan formatda ma'lumot yuboring yoki /cancel buyrug'ini bosing.",
            reply_markup=cancel_keyboard(),
        )
