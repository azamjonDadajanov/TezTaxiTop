"""Reply-keyboard navigation and account-level bot workflows."""

from __future__ import annotations

import html
import logging

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from django.utils import timezone

from apps.core.exceptions import BusinessError
from bot.keyboards import contact_keyboard, main_menu_keyboard, subscription_keyboard
from bot.services import platform
from bot.states import ProfileStates, SupportStates

logger = logging.getLogger(__name__)
router = Router(name="menu")


async def _show_business_error(message: Message, error: BusinessError) -> None:
    await message.answer(html.escape(error.message))


@router.message(F.text == "/cancel")
@router.message(F.text == "❌ Bekor qilish")
async def cancel_current_flow(message: Message, state: FSMContext) -> None:
    await state.clear()
    try:
        user = await platform.get_user(message.from_user.id)
        is_driver = user.is_driver_role
    except BusinessError:
        is_driver = False
    await message.answer(
        "Joriy amal bekor qilindi.",
        reply_markup=main_menu_keyboard(is_driver),
    )


@router.message(Command("profile"))
async def profile_command(message: Message, state: FSMContext) -> None:
    await show_profile(message, state)


@router.message(Command("driver"))
async def driver_command(message: Message, state: FSMContext) -> None:
    await become_driver(message, state)


@router.message(Command("passenger"))
async def passenger_command(message: Message, state: FSMContext) -> None:
    await state.clear()
    from apps.users.constants import UserRole

    try:
        user = await platform.set_user_role(message.from_user.id, UserRole.PASSENGER)
    except BusinessError as error:
        await _show_business_error(message, error)
        return
    await message.answer("Yo'lovchi rejimi yoqildi.", reply_markup=main_menu_keyboard(user.is_driver_role))


@router.message(Command("my_trips"))
async def trips_command(message: Message, state: FSMContext) -> None:
    await list_driver_trips(message, state)


@router.message(Command("my_orders"))
async def orders_command(message: Message, state: FSMContext) -> None:
    await show_orders(message, state)


@router.message(Command("my_requests"))
async def requests_command(message: Message, state: FSMContext) -> None:
    await list_passenger_requests(message, state)


@router.message(Command("subscription"))
async def subscription_command(message: Message, state: FSMContext) -> None:
    await show_subscription(message, state)


@router.message(Command("support"))
async def support_command(message: Message, state: FSMContext) -> None:
    await start_support(message, state)


@router.message(F.text == "📝 So'rov yaratish")
async def create_passenger_request(message: Message, state: FSMContext) -> None:
    from bot.handlers.passenger import start_passenger_request

    await state.clear()
    await start_passenger_request(message, state)


@router.message(F.text == "🔍 Yo'lov topish")
async def find_passenger_ride(
    message: Message,
    state: FSMContext,
    user_id: int | None = None,
) -> None:
    from bot.handlers.passenger import find_ride

    await state.clear()
    await find_ride(message, user_id)


@router.message(F.text == "📋 Mening so'rovlarim")
async def list_passenger_requests(
    message: Message,
    state: FSMContext,
    user_id: int | None = None,
) -> None:
    from bot.handlers.passenger import show_my_requests

    await state.clear()
    await show_my_requests(message, user_id)


@router.message(F.text == "🚗 Yo'lov yaratish")
async def create_driver_trip(
    message: Message,
    state: FSMContext,
    user_id: int | None = None,
) -> None:
    from bot.handlers.driver import start_trip_creation

    await start_trip_creation(message, state, user_id)


@router.message(F.text == "📋 Mening yo'lovlarim")
async def list_driver_trips(
    message: Message,
    state: FSMContext,
    user_id: int | None = None,
) -> None:
    from bot.handlers.driver import show_driver_trips

    await state.clear()
    await show_driver_trips(message, user_id)


@router.message(F.text == "👥 Yo'lovchi so'rovlari")
async def list_driver_requests(
    message: Message,
    state: FSMContext,
    user_id: int | None = None,
) -> None:
    from bot.handlers.driver import show_driver_requests

    await state.clear()
    await show_driver_requests(message, user_id)


@router.message(F.text == "🚙 Avtomobillarim")
async def list_driver_vehicles(
    message: Message,
    state: FSMContext,
    user_id: int | None = None,
) -> None:
    from bot.handlers.driver import show_vehicles

    await state.clear()
    await show_vehicles(message, user_id)


@router.message(F.text == "👤 Profil")
async def show_profile(message: Message, state: FSMContext, user_id: int | None = None) -> None:
    await state.clear()
    user = await platform.get_user(user_id or message.from_user.id)
    driver = getattr(user, "driver_profile", None)
    rating = f"\n⭐ Reyting: {driver.rating} ({driver.rating_count} ta baho)" if driver else ""
    text = (
        f"<b>{html.escape(user.display_name)}</b>\n"
        f"Telefon: {html.escape(user.phone_number or 'Kiritilmagan')}\n"
        f"Rol: {html.escape(user.get_role_display())}{rating}"
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Ismni o'zgartirish", callback_data="profile:name")],
            [InlineKeyboardButton(text="Telefonni o'zgartirish", callback_data="profile:phone")],
        ]
    )
    await message.answer(text, parse_mode="HTML", reply_markup=keyboard)


@router.callback_query(F.data.startswith("profile:"))
async def edit_profile_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    field = callback.data.partition(":")[2]
    if field == "name":
        await state.set_state(ProfileStates.waiting_for_name)
        prompt = "Ism va familiyangizni yuboring."
    elif field == "phone":
        await state.set_state(ProfileStates.waiting_for_phone)
        prompt = "Telefon raqamingizni tugma orqali yuboring."
        if callback.message:
            await callback.message.answer(prompt, reply_markup=contact_keyboard())
        await callback.answer()
        return
    else:
        await callback.answer("Noma'lum amal", show_alert=True)
        return
    if callback.message:
        await callback.message.answer(prompt)
    await callback.answer()


@router.message(ProfileStates.waiting_for_name, F.text)
async def update_profile_name(message: Message, state: FSMContext) -> None:
    parts = message.text.strip().split(maxsplit=1)
    if not parts or not parts[0]:
        await message.answer("Ism bo'sh bo'lishi mumkin emas.")
        return
    await platform.update_profile(
        message.from_user.id,
        first_name=parts[0],
        last_name=parts[1] if len(parts) > 1 else "",
    )
    await state.clear()
    user = await platform.get_user(message.from_user.id)
    await message.answer("Profil yangilandi.", reply_markup=main_menu_keyboard(user.is_driver_role))


@router.message(ProfileStates.waiting_for_phone, F.contact)
async def update_profile_phone(message: Message, state: FSMContext) -> None:
    if message.contact.user_id not in (None, message.from_user.id):
        await message.answer("Faqat o'zingizning telefon raqamingizni yuboring.")
        return
    await platform.update_profile(message.from_user.id, phone_number=message.contact.phone_number)
    await state.clear()
    user = await platform.get_user(message.from_user.id)
    await message.answer(
        "Telefon raqamingiz yangilandi.",
        reply_markup=main_menu_keyboard(user.is_driver_role),
    )


@router.message(StateFilter(ProfileStates.waiting_for_name, ProfileStates.waiting_for_phone))
async def profile_invalid_input(message: Message, state: FSMContext) -> None:
    if await state.get_state() == ProfileStates.waiting_for_phone.state:
        await message.answer("Telefon raqamingizni Telegram contact sifatida yuboring.", reply_markup=contact_keyboard())
    else:
        await message.answer("Ism va familiyangizni matn ko'rinishida yuboring.")


@router.message(F.text == "🔄 Haydovchi bo'lish")
async def become_driver(message: Message, state: FSMContext) -> None:
    await state.clear()
    try:
        profile = await platform.register_driver(message.from_user.id)
    except BusinessError as error:
        await _show_business_error(message, error)
        return
    await message.answer(
        f"Haydovchi profilingiz yaratildi. Tasdiqlash holati: "
        f"{'tasdiqlangan' if profile.is_verified else 'kutilmoqda' }.",
        reply_markup=main_menu_keyboard(is_driver=True),
    )


@router.message(F.text == "📦 Buyurtmalarim")
async def show_orders(message: Message, state: FSMContext, user_id: int | None = None) -> None:
    await state.clear()
    user_id = user_id or message.from_user.id
    orders = await platform.get_user_orders(user_id)
    if not orders:
        await message.answer("Sizda buyurtmalar yo'q.")
        return
    for order in orders:
        owner_is_driver = order.trip.driver.user_id == user_id
        actions = []
        if owner_is_driver and order.status == "pending":
            actions = [
                [InlineKeyboardButton(text="✅ Qabul qilish", callback_data=f"order:accept:{order.pk}")],
                [InlineKeyboardButton(text="❌ Rad etish", callback_data=f"order:reject:{order.pk}")],
            ]
        elif owner_is_driver and order.status in {"accepted", "driver_arrived"}:
            actions = [[InlineKeyboardButton(text="🚗 Yo'lga chiqdi", callback_data=f"order:start:{order.pk}")]]
        elif owner_is_driver and order.status == "in_progress":
            actions = [[InlineKeyboardButton(text="✅ Yakunlash", callback_data=f"order:complete:{order.pk}")]]
        elif not owner_is_driver and order.can_cancel:
            actions = [[InlineKeyboardButton(text="❌ Bekor qilish", callback_data=f"order:cancel:{order.pk}")]]
        text = (
            f"<b>Buyurtma #{order.pk}</b> · {html.escape(order.get_status_display())}\n"
            f"{html.escape(order.trip.route_label())}\n"
            f"🕐 {timezone.localtime(order.trip.departure_time):%d.%m.%Y %H:%M} · "
            f"💺 {order.seats_booked} · 💰 {order.total_amount:,.0f} so'm"
        )
        markup = InlineKeyboardMarkup(inline_keyboard=actions) if actions else None
        await message.answer(text, parse_mode="HTML", reply_markup=markup)


@router.callback_query(F.data.startswith("order:"))
async def transition_order(callback: CallbackQuery) -> None:
    try:
        _, action, order_id = callback.data.split(":", maxsplit=2)
        order = await platform.transition_order(callback.from_user.id, int(order_id), action)
    except (ValueError, BusinessError) as error:
        text = error.message if isinstance(error, BusinessError) else "Buyurtma tugmasi noto'g'ri."
        await callback.answer(text, show_alert=True)
        return
    await callback.answer(f"Buyurtma holati: {order.get_status_display()}")
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=None)


@router.message(F.text == "🔔 Bildirishnomalar")
async def show_notifications(message: Message, state: FSMContext, user_id: int | None = None) -> None:
    await state.clear()
    notifications = await platform.get_notifications(user_id or message.from_user.id)
    if not notifications:
        await message.answer("Bildirishnomalar yo'q.")
        return
    lines = ["<b>So'nggi bildirishnomalar</b>"]
    for item in notifications:
        marker = "●" if not item.is_read else "○"
        lines.append(f"{marker} <b>{html.escape(item.title)}</b>\n{html.escape(item.message)}")
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Barchasini o'qilgan deb belgilash", callback_data="notifications:read")]]
    )
    await message.answer("\n\n".join(lines), parse_mode="HTML", reply_markup=keyboard)


@router.callback_query(F.data == "notifications:read")
async def mark_notifications_read(callback: CallbackQuery) -> None:
    count = await platform.mark_notifications_read(callback.from_user.id)
    await callback.answer(f"{count} ta bildirishnoma o'qilgan deb belgilandi.")
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=None)


@router.message(F.text == "🆘 Qo'llab-quvvatlash")
async def start_support(message: Message, state: FSMContext, user_id: int | None = None) -> None:
    await state.clear()
    await state.update_data(support_user_id=user_id or message.from_user.id)
    tickets = await platform.get_support_tickets(user_id or message.from_user.id)
    if tickets:
        summary = "\n".join(
            f"#{ticket.pk} · {html.escape(ticket.subject)} · {html.escape(ticket.get_status_display())}"
            for ticket in tickets
        )
        await message.answer(f"<b>Murojaatlaringiz</b>\n{summary}", parse_mode="HTML")
    await state.set_state(SupportStates.waiting_for_subject)
    await message.answer("Yangi murojaat mavzusini yozing:")


@router.message(SupportStates.waiting_for_subject, F.text)
async def support_subject(message: Message, state: FSMContext) -> None:
    subject = message.text.strip()
    if not subject:
        await message.answer("Mavzu bo'sh bo'lmasin. Qayta kiriting:")
        return
    await state.update_data(support_subject=subject)
    await state.set_state(SupportStates.waiting_for_message)
    await message.answer("Murojaat tafsilotlarini yozing:")


@router.message(SupportStates.waiting_for_message, F.text)
async def support_body(message: Message, state: FSMContext) -> None:
    body = message.text.strip()
    if not body:
        await message.answer("Xabar bo'sh bo'lmasin. Qayta kiriting:")
        return
    data = await state.get_data()
    try:
        ticket = await platform.create_support_ticket(
            data.get("support_user_id", message.from_user.id),
            data["support_subject"],
            body,
        )
    except BusinessError as error:
        await _show_business_error(message, error)
        return
    await state.clear()
    await message.answer(f"Murojaat #{ticket.pk} yuborildi. Javob kelganda bildirishnoma olasiz.")


@router.message(StateFilter(SupportStates.waiting_for_subject, SupportStates.waiting_for_message))
async def support_invalid_input(message: Message, state: FSMContext) -> None:
    prompt = (
        "Murojaat tafsilotlarini matn ko'rinishida yuboring."
        if await state.get_state() == SupportStates.waiting_for_message.state
        else "Murojaat mavzusini matn ko'rinishida yuboring."
    )
    await message.answer(prompt)


@router.message(F.text == "💳 Obuna")
async def show_subscription(message: Message, state: FSMContext, user_id: int | None = None) -> None:
    await state.clear()
    try:
        subscription, plans = await platform.get_subscription_info(user_id or message.from_user.id)
    except BusinessError as error:
        await _show_business_error(message, error)
        return
    lines = ["<b>Obuna</b>"]
    if subscription:
        lines.append(
            f"Faol: {html.escape(subscription.plan.name)} · "
            f"{timezone.localtime(subscription.expires_at):%d.%m.%Y gacha}"
        )
    else:
        lines.append("Faol obuna yo'q.")
    if plans:
        lines.append("\nMavjud rejalar:")
        await message.answer("\n".join(lines), parse_mode="HTML", reply_markup=subscription_keyboard(plans))
    else:
        lines.append("Faol reja mavjud emas.")
        await message.answer("\n".join(lines), parse_mode="HTML")


@router.callback_query(F.data.startswith("buy_subscription:"))
async def buy_subscription(callback: CallbackQuery) -> None:
    try:
        plan_id = int(callback.data.partition(":")[2])
        payment, invoice = await platform.create_subscription_invoice(callback.from_user.id, plan_id)
    except (ValueError, BusinessError) as error:
        text = error.message if isinstance(error, BusinessError) else "Obuna rejasi noto'g'ri."
        await callback.answer(text, show_alert=True)
        return
    invoice_url = invoice.get("url") or invoice.get("checkout_url")
    if invoice_url:
        await callback.message.answer(f"To'lov havolasi: {html.escape(invoice_url)}")
    else:
        await callback.message.answer(
            f"To'lov #{payment.pk} yaratildi. Provayder javobini kuting; "
            "to'lov faqat server tasdiqlagandan keyin faollashadi."
        )
    await callback.answer()


@router.message(F.text == "💰 To'lovlar")
async def show_payments(message: Message, state: FSMContext, user_id: int | None = None) -> None:
    await state.clear()
    payments = await platform.get_payments(user_id or message.from_user.id)
    if not payments:
        await message.answer("To'lovlar tarixi bo'sh.")
        return
    lines = ["<b>To'lovlar tarixi</b>"]
    for payment in payments:
        lines.append(
            f"#{payment.pk} · {payment.amount:,.0f} so'm · "
            f"{html.escape(payment.get_status_display())} · "
            f"{timezone.localtime(payment.created_at):%d.%m.%Y}"
        )
    await message.answer("\n".join(lines), parse_mode="HTML")


@router.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    if callback.message:
        user = await platform.get_user(callback.from_user.id)
        await callback.message.answer(
            "Asosiy menyu:",
            reply_markup=main_menu_keyboard(user.is_driver_role),
        )
    await callback.answer()


@router.callback_query(F.data == "profile")
async def profile_callback(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.message:
        await show_profile(callback.message, state, callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data == "notifications")
async def notifications_callback(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.message:
        await show_notifications(callback.message, state, callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data == "support")
async def support_callback(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.message:
        await start_support(callback.message, state, callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data == "subscription")
async def subscription_callback(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.message:
        await show_subscription(callback.message, state, callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data == "payments")
async def payments_callback(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.message:
        await show_payments(callback.message, state, callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data == "passenger_create_request")
async def passenger_create_callback(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.message:
        await create_passenger_request(callback.message, state)
    await callback.answer()


@router.callback_query(F.data == "passenger_find_ride")
async def passenger_find_callback(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.message:
        await find_passenger_ride(callback.message, state, callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data == "passenger_my_requests")
async def passenger_requests_callback(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.message:
        await list_passenger_requests(callback.message, state, callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data == "passenger_my_orders")
async def passenger_orders_callback(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.message:
        await show_orders(callback.message, state, callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data == "driver_create_trip")
async def driver_create_callback(callback: CallbackQuery, state: FSMContext) -> None:
    from bot.handlers.driver import start_trip_creation

    if callback.message:
        await start_trip_creation(callback.message, state, callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data == "driver_my_trips")
async def driver_trips_callback(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.message:
        await list_driver_trips(callback.message, state, callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data == "driver_passenger_requests")
async def driver_requests_callback(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.message:
        await list_driver_requests(callback.message, state, callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data == "driver_my_orders")
async def driver_orders_callback(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.message:
        await show_orders(callback.message, state, callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data == "driver_my_vehicles")
async def driver_vehicles_callback(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.message:
        await list_driver_vehicles(callback.message, state, callback.from_user.id)
    await callback.answer()
