"""Keyboard builders for the Telegram bot."""

from __future__ import annotations

from datetime import timedelta

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    WebAppInfo,
)
from django.utils import timezone

from bot.config import TELEGRAM_WEBAPP_URL, validate_telegram_webapp_url


async def make_date_keyboard() -> InlineKeyboardMarkup:
    """Inline calendar: pick a date first."""
    now = timezone.localtime()
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for i in range(7):
        date = (now + timedelta(days=i)).strftime("%d.%m.%Y")
        row.append(InlineKeyboardButton(text=date, callback_data=f"datetime:date:{date}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel_flow")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def make_time_keyboard(date_str: str) -> InlineKeyboardMarkup:
    """Inline time picker for a chosen date: 00:00 through 23:00."""
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for hour in range(24):
        time_str = f"{hour:02d}:00"
        row.append(
            InlineKeyboardButton(
                text=time_str,
                callback_data=f"datetime:time:{date_str}:{time_str}",
            )
        )
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([
        InlineKeyboardButton(text="🔙 Orqaga", callback_data="datetime:back"),
        InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel_flow"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def main_menu_keyboard(is_driver: bool = False) -> ReplyKeyboardMarkup:
    """Build main menu keyboard based on user role."""
    if is_driver:
        rows = [
                [KeyboardButton(text="🚗 Yo'lov yaratish"), KeyboardButton(text="📋 Mening yo'lovlarim")],
                [KeyboardButton(text="👥 Yo'lovchi so'rovlari"), KeyboardButton(text="📦 Buyurtmalarim")],
                [KeyboardButton(text="🚙 Avtomobillarim"), KeyboardButton(text="💳 Obuna")],
                [KeyboardButton(text="💰 To'lovlar"), KeyboardButton(text="🔔 Bildirishnomalar")],
                [KeyboardButton(text="👤 Profil"), KeyboardButton(text="🆘 Qo'llab-quvvatlash")],
                [KeyboardButton(text="🔄 Rolni o'zgartirish")],
            ]
    else:
        rows = [
                [KeyboardButton(text="🔍 Yo'lov topish"), KeyboardButton(text="📝 So'rov yaratish")],
                [KeyboardButton(text="📋 Mening so'rovlarim"), KeyboardButton(text="📦 Buyurtmalarim")],
                [KeyboardButton(text="🔔 Bildirishnomalar"), KeyboardButton(text="👤 Profil")],
                [KeyboardButton(text="🆘 Qo'llab-quvvatlash")],
                [KeyboardButton(text="🔄 Haydovchi bo'lish")],
            ]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def mini_app_inline_keyboard() -> InlineKeyboardMarkup | None:
    """Build an inline Mini App launch button that receives signed initData."""
    if not TELEGRAM_WEBAPP_URL:
        return None
    web_app_url = validate_telegram_webapp_url(TELEGRAM_WEBAPP_URL)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🚕 TezTaxiTop ilovasini ochish", web_app=WebAppInfo(url=web_app_url))]
        ]
    )


def back_keyboard() -> InlineKeyboardMarkup:
    """Build back button keyboard."""
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="← Orqaga", callback_data="back_to_menu")]]
    )


def cancel_keyboard() -> InlineKeyboardMarkup:
    """Build cancel keyboard."""
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel_flow")]]
    )


def passenger_menu_keyboard() -> InlineKeyboardMarkup:
    """Build passenger menu inline keyboard."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔍 Yo'lov topish", callback_data="passenger_find_ride")],
            [InlineKeyboardButton(text="📝 So'rov yaratish", callback_data="passenger_create_request")],
            [InlineKeyboardButton(text="📋 Mening so'rovlarim", callback_data="passenger_my_requests")],
            [InlineKeyboardButton(text="📦 Buyurtmalarim", callback_data="passenger_my_orders")],
            [InlineKeyboardButton(text="🔔 Bildirishnomalar", callback_data="notifications")],
            [InlineKeyboardButton(text="👤 Profil", callback_data="profile")],
            [InlineKeyboardButton(text="🆘 Qo'llab-quvvatlash", callback_data="support")],
        ]
    )


def driver_menu_keyboard() -> InlineKeyboardMarkup:
    """Build driver menu inline keyboard."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🚗 Yo'lov yaratish", callback_data="driver_create_trip")],
            [InlineKeyboardButton(text="📋 Mening yo'lovlarim", callback_data="driver_my_trips")],
            [InlineKeyboardButton(text="👥 Yo'lovchi so'rovlari", callback_data="driver_passenger_requests")],
            [InlineKeyboardButton(text="📦 Buyurtmalarim", callback_data="driver_my_orders")],
            [InlineKeyboardButton(text="🚙 Avtomobillarim", callback_data="driver_my_vehicles")],
            [InlineKeyboardButton(text="💳 Obuna", callback_data="subscription")],
            [InlineKeyboardButton(text="💰 To'lovlar", callback_data="payments")],
            [InlineKeyboardButton(text="🔔 Bildirishnomalar", callback_data="notifications")],
            [InlineKeyboardButton(text="👤 Profil", callback_data="profile")],
            [InlineKeyboardButton(text="🆘 Qo'llab-quvvatlash", callback_data="support")],
        ]
    )


def order_actions_keyboard(order_id: int, status: str) -> InlineKeyboardMarkup:
    """Build order action buttons based on status."""
    buttons = []
    if status == "pending":
        buttons.append(InlineKeyboardButton(text="✅ Qabul qilish", callback_data=f"order:accept:{order_id}"))
        buttons.append(InlineKeyboardButton(text="❌ Rad etish", callback_data=f"order:reject:{order_id}"))
    elif status == "accepted":
        buttons.append(InlineKeyboardButton(text="🚗 Yo'lga chiqdi", callback_data=f"order:start:{order_id}"))
        buttons.append(InlineKeyboardButton(text="❌ Bekor qilish", callback_data=f"order:cancel:{order_id}"))
    elif status == "in_progress":
        buttons.append(InlineKeyboardButton(text="✅ Yakunlash", callback_data=f"order:complete:{order_id}"))
    elif status == "driver_arrived":
        buttons.append(InlineKeyboardButton(text="🚗 Yo'lga chiqdi", callback_data=f"order:start:{order_id}"))

    if buttons:
        return InlineKeyboardMarkup(inline_keyboard=[buttons])
    return InlineKeyboardMarkup(inline_keyboard=[])


def match_keyboard(request_id: int, match_id: int) -> InlineKeyboardMarkup:
    """Build keyboard for a matching result."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎫 Band qilish", callback_data=f"book_match:{request_id}:{match_id}")],
            [InlineKeyboardButton(text="💬 Suhbat", callback_data=f"open_chat:{request_id}:{match_id}")],
            [InlineKeyboardButton(text="🔍 Boshqa mosliklar", callback_data=f"refresh_matches:{request_id}")],
        ]
    )


def subscription_keyboard(plans: list) -> InlineKeyboardMarkup:
    """Build keyboard for subscription plans."""
    buttons = []
    for plan in plans:
        buttons.append(
            InlineKeyboardButton(
                text=f"{plan.name} - {plan.price_as_int} so'm",
                callback_data=f"buy_subscription:{plan.id}",
            )
        )

    if not buttons:
        return InlineKeyboardMarkup(inline_keyboard=[])

    return InlineKeyboardMarkup(
        inline_keyboard=[buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    )


def seats_keyboard(current: int = 1, max_seats: int = 9) -> InlineKeyboardMarkup:
    """Build seat selection keyboard."""
    buttons = []
    for seats in range(1, min(max_seats + 1, 6)):
        buttons.append(
            InlineKeyboardButton(
                text=f"{seats} ta o'rin" + (" ✓" if seats == current else ""),
                callback_data=f"seats:{seats}",
            )
        )

    return InlineKeyboardMarkup(
        inline_keyboard=[buttons[i : i + 3] for i in range(0, len(buttons), 3)]
    )


def location_keyboard() -> ReplyKeyboardMarkup:
    """Build location sharing keyboard."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📍 Manzilni yuborish", request_location=True)],
            [KeyboardButton(text="❌ Bekor qilish")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def contact_keyboard() -> ReplyKeyboardMarkup:
    """Build a keyboard that asks Telegram to share the user's contact."""
    rows = [[KeyboardButton(text="📱 Telefon raqamini yuborish", request_contact=True)]]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, one_time_keyboard=True)