"""Registration handler — phone number collection and user setup."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, ReplyKeyboardMarkup
from django.core.exceptions import ValidationError

from apps.core.exceptions import BusinessError
from bot.keyboards import contact_keyboard, main_menu_keyboard
from bot.states.registration import RegistrationStates
from bot.services.telegram import set_user_phone_number

router = Router(name="registration")


def request_phone_number() -> ReplyKeyboardMarkup:
    """Return contact request keyboard."""
    return contact_keyboard()


@router.message(F.contact)
async def handle_contact(message: Message, state: FSMContext) -> None:
    """Handle contact sharing."""
    if message.contact.user_id not in (None, message.from_user.id):
        await message.answer("Faqat o'zingizning telefon raqamingizni yuboring.")
        return
    phone_number = message.contact.phone_number
    try:
        await set_user_phone_number(message.from_user.id, phone_number)
    except (BusinessError, ValidationError) as error:
        await message.answer(str(getattr(error, "message", error)))
        return
    await state.clear()

    await message.answer(
        "✅ Telefon raqamingiz saqlandi!\n"
        "Endi botdan to'liq foydalanishingiz mumkin.",
        reply_markup=await get_main_menu(message.from_user.id),
    )


@router.message(RegistrationStates.waiting_for_phone, F.text & ~F.command)
async def handle_unexpected_text(message: Message, state: FSMContext) -> None:
    """Handle unexpected text input during registration."""
    if await state.get_state() is None:
        return
    await message.answer(
        "Iltimos, telefon raqamingizni yuborish tugmasini bosing.",
        reply_markup=request_phone_number(),
    )


@router.message(StateFilter(RegistrationStates.waiting_for_phone))
async def handle_invalid_contact_input(message: Message) -> None:
    await message.answer(
        "Telefon raqamini yuborish tugmasini bosing.",
        reply_markup=request_phone_number(),
    )


async def get_main_menu(user_id: int) -> ReplyKeyboardMarkup:
    """Build main menu keyboard based on user role."""
    from bot.services.platform import get_user
    user = await get_user(user_id)
    return main_menu_keyboard(user.is_driver_role)


async def request_phone_number_prompt(message: Message, state: FSMContext) -> None:
    """Send phone number request prompt."""
    await state.set_state(RegistrationStates.waiting_for_phone)
    await message.answer(
        "🇺🇿 TezTaxiTop ga xush kelibsiz!\n\n"
        "Ro'yxatdan o'tish uchun telefon raqamingizni yuboring.",
        reply_markup=request_phone_number(),
    )