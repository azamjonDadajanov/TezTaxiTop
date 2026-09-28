"""Start handler — entry point for /start command."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from apps.core.exceptions import BusinessError
from bot.keyboards import main_menu_keyboard
from bot.handlers.registration import request_phone_number
from bot.states import RegistrationStates

router = Router(name="start")


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext) -> None:
    """Handle /start command."""
    await state.clear()

    from bot.services.telegram import get_or_create_user

    user, created = await get_or_create_user(message.from_user)

    if created:
        await state.set_state(RegistrationStates.waiting_for_phone)
        await message.answer(
            "🇺🇿 TezTaxiTop ga xush kelibsiz!\n\n"
            "Ro'yxatdan o'tish uchun telefon raqamingizni yuboring.",
            reply_markup=request_phone_number(),
        )
    else:
        await message.answer(
            f"Qayta kelganingizdan xursandmiz, {user.first_name}!\n"
            "Asosiy menyuga o'tish uchun quyidagi tugmalardan birini tanlang:",
            reply_markup=await get_main_menu(user),
        )


async def get_main_menu(user) -> "ReplyKeyboardMarkup":
    """Build main menu keyboard based on user role."""
    return main_menu_keyboard(user.is_driver_role)


@router.message(F.text == "🔄 Rolni o'zgartirish")
@router.message(F.text == "🔄 Haydovchi bo'lish")
async def switch_role(message: Message, state: FSMContext) -> None:
    """Switch between passenger and driver modes."""
    await state.clear()
    from bot.services.telegram import switch_user_role

    try:
        user = await switch_user_role(message.from_user)
    except BusinessError as error:
        await message.answer(error.message)
        return
    await message.answer(
        f"Siz endi <b>{'Haydovchi' if user.is_driver_role else 'Yo\'lovchi'}</b> rejimidasiz.",
        parse_mode="HTML",
        reply_markup=await get_main_menu(user),
    )


@router.message(Command("help"))
async def cmd_help(message: Message, state: FSMContext) -> None:
    """Handle /help command."""
    await state.clear()
    await message.answer(
        "<b>TezTaxiTop - Yordam</b>\n\n"
        "<b>Asosiy buyruqlar:</b>\n"
        "/start - Botni ishga tushirish\n"
        "/help - Yordam\n"
        "/profile - Profilim\n"
        "/driver - Haydovchi rejimi\n"
        "/passenger - Yo'lovchi rejimi\n"
        "/my_trips - Mening yo'lovlarim\n"
        "/my_orders - Mening buyurtmalarim\n"
        "/my_requests - Mening so'rovlarim\n"
        "/subscription - Obuna\n"
        "/support - Qo'llab-quvvatlash\n"
        "/cancel - Hozirgi amalni bekor qilish\n\n"
        "Savollar uchun /support tugmasini bosing.",
        parse_mode="HTML",
    )