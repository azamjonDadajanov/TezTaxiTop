"""Handlers for the post-trip rating / review flow.

Flow:
1. After a trip is completed, both parties receive a Telegram message with
   inline star buttons (⭐ 1 … ⭐ 5).
2. Tapping a star stores the score in FSM and asks for an optional comment,
   with a "⏭ O'tkazib yuborish" skip button.
3a. If the user types a comment  → review is saved, "Rahmat!" + main menu.
3b. If the user taps skip        → review is saved without comment, main menu.
"""

from __future__ import annotations

import html
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from asgiref.sync import sync_to_async

from apps.core.exceptions import BusinessError
from bot.keyboards import main_menu_keyboard
from bot.states import ReviewStates

logger = logging.getLogger(__name__)
router = Router(name="review")


def _skip_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⏭ O'tkazib yuborish", callback_data="skip_review_comment")]
        ]
    )


def _create_review_sync(order_id: int, telegram_id: int, rating: int, comment: str = ""):
    """Create a review in the Django ORM (runs in sync context)."""
    from apps.orders.selectors import get_order_by_id
    from apps.reviews.services import create_review
    from apps.users.selectors import get_user_by_telegram_id

    user = get_user_by_telegram_id(telegram_id)
    if user is None:
        raise BusinessError("Foydalanuvchi topilmadi.")

    order = get_order_by_id(order_id)
    if order is None:
        raise BusinessError("Buyurtma topilmadi.")

    # Determine who is being reviewed: the *other* participant.
    if user.pk == order.passenger_id:
        reviewed_user = order.trip.driver.user
    else:
        reviewed_user = order.passenger

    return create_review(
        order=order,
        reviewer=user,
        reviewed_user=reviewed_user,
        rating=rating,
        comment=comment,
    )


# ── 1. Star rating callback ───────────────────────────────────────────────
@router.callback_query(F.data.startswith("rate_order:"))
async def on_rate_order(callback: CallbackQuery, state: FSMContext) -> None:
    """User tapped ⭐ N — store score, ask for optional comment."""
    try:
        parts = callback.data.split(":")
        order_id = int(parts[1])
        score = int(parts[2])
        if not 1 <= score <= 5:
            raise ValueError
    except (IndexError, ValueError):
        await callback.answer("Noto'g'ri ma'lumot.", show_alert=True)
        return

    await state.set_state(ReviewStates.waiting_for_comment)
    await state.update_data(review_order_id=order_id, review_score=score)
    await callback.answer(f"⭐ {score} tanlandi")

    if callback.message:
        await callback.message.answer(
            "✍️ Safar haqida izoh qoldiring yoki pastdagi tugmani bosing:",
            reply_markup=_skip_keyboard(),
        )


# ── 2. User sends a comment text ──────────────────────────────────────────
@router.message(ReviewStates.waiting_for_comment, F.text)
async def on_review_comment(message: Message, state: FSMContext) -> None:
    """User typed a comment — save rating + comment."""
    data = await state.get_data()
    order_id = data.get("review_order_id")
    score = data.get("review_score")
    comment = (message.text or "").strip()

    if not order_id or not score:
        await state.clear()
        await message.answer("Xatolik yuz berdi. Bosh menyu:")
        return

    try:
        is_driver = False
        try:
            from bot.services.platform import _get_user
            user = await sync_to_async(_get_user)(message.from_user.id)
            is_driver = user.is_driver_role
        except Exception:
            pass

        await sync_to_async(_create_review_sync)(order_id, message.from_user.id, score, comment)
        await state.clear()
        await message.answer(
            "✅ Baho va izohingiz uchun rahmat!",
            reply_markup=main_menu_keyboard(is_driver),
        )
    except BusinessError as exc:
        await state.clear()
        await message.answer(html.escape(exc.message))
    except Exception:
        logger.exception("Review yaratishda xato: order=%s", order_id)
        await state.clear()
        await message.answer("Xatolik yuz berdi. Qaytadan urinib ko'ring.")


# ── 3. User taps "O'tkazib yuborish" ──────────────────────────────────────
@router.callback_query(ReviewStates.waiting_for_comment, F.data == "skip_review_comment")
async def on_skip_review_comment(callback: CallbackQuery, state: FSMContext) -> None:
    """Save rating without a comment and return to main menu."""
    data = await state.get_data()
    order_id = data.get("review_order_id")
    score = data.get("review_score")

    if not order_id or not score:
        await state.clear()
        await callback.answer("Xatolik.", show_alert=True)
        return

    try:
        is_driver = False
        try:
            from bot.services.platform import _get_user
            user = await sync_to_async(_get_user)(callback.from_user.id)
            is_driver = user.is_driver_role
        except Exception:
            pass

        await sync_to_async(_create_review_sync)(order_id, callback.from_user.id, score, "")
        await state.clear()
        await callback.answer("Baho saqlandi!")

        if callback.message:
            await callback.message.answer(
                "Bosh menyudasiz",
                reply_markup=main_menu_keyboard(is_driver),
            )
    except BusinessError as exc:
        await state.clear()
        await callback.answer(html.escape(exc.message), show_alert=True)
    except Exception:
        logger.exception("Review yaratishda xato: order=%s", order_id)
        await state.clear()
        await callback.answer("Xatolik yuz berdi.", show_alert=True)
