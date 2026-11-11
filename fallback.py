from aiogram import F, Router
from aiogram.types import CallbackQuery

router = Router()


@router.callback_query(F.data.startswith("a:"))
async def denied(cb: CallbackQuery):
    await cb.answer("⛔ شما به این بخش دسترسی ندارید.", show_alert=True)
