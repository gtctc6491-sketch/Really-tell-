from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from admin.common import AdminFilter, back_btn, cancel_row, log_action, sep
from bot.keyboards.common import btn, ikb
from bot.services.broadcast import run_broadcast, spawn
from bot.services.messaging import send_text, show_text
from bot.states import AdminStates
from database.models import Broadcast, User
from utils.helpers import fmt_dt

router = Router()
router.message.filter(AdminFilter("broadcast"))
router.callback_query.filter(AdminFilter("broadcast"))


@router.callback_query(F.data == "a:bc")
async def bc_menu(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.answer()
    await show_text(cb, f"📢 پیام همگانی\n{sep()}", None, ikb([
        [btn("📣 ارسال پیام جدید", "a:bcnew")], [btn("📜 سوابق ارسال", "a:bchist")], [back_btn()]]))


@router.callback_query(F.data == "a:bcnew")
async def bc_new(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.set_state(AdminStates.broadcast_content)
    await show_text(cb, "📣 پیام همگانی را بفرستید (متن، عکس، ویدیو، فایل... با فرمت و ایموجی پرمیوم).\n"
                        "ابتدا پیش‌نمایش نشان داده می‌شود.", None, ikb([cancel_row()]))


@router.message(AdminStates.broadcast_content)
async def bc_preview(message: Message, state: FSMContext, session: AsyncSession):
    await state.update_data(chat=message.chat.id, mid=message.message_id, ctype=message.content_type,
                            preview=(message.text or message.caption or "")[:300])
    n = await session.scalar(select(func.count(User.id)).where(User.is_blocked.is_(False))) or 0
    await send_text(message.bot, message.chat.id, f"👆 پیش‌نمایش پیام شما.\n📬 گیرندگان: {n} کاربر\nارسال شود؟", None,
                    ikb([[btn("✅ ارسال", "a:bcok"), btn("❌ انصراف", "a:home")]]))


@router.callback_query(F.data == "a:bcok", AdminStates.broadcast_content)
async def bc_go(cb: CallbackQuery, state: FSMContext, session: AsyncSession, admin, bot):
    d = await state.get_data()
    await state.clear()
    b = Broadcast(admin_id=admin.user_id, content_type=str(d.get("ctype", "text")), text=d.get("preview"), status="running")
    session.add(b)
    await session.flush()
    await log_action(session, admin.user_id, "broadcast", f"#{b.id}")
    bid = b.id
    await session.commit()
    spawn(run_broadcast(bot, bid, cb.from_user.id, d["chat"], d["mid"]))
    await cb.answer("🚀 شروع شد")
    await show_text(cb, f"🚀 پیام همگانی #{bid} در پس‌زمینه در حال ارسال است.\nپس از پایان گزارش دریافت می‌کنید.", None,
                    ikb([[back_btn("a:bc")]]))


@router.callback_query(F.data == "a:bchist")
async def bc_hist(cb: CallbackQuery, session: AsyncSession):
    await cb.answer()
    rows = (await session.execute(select(Broadcast).order_by(Broadcast.id.desc()).limit(10))).scalars().all()
    lines = [f"📜 سوابق پیام همگانی\n{sep()}"]
    lines += [f"#{b.id} • {fmt_dt(b.created_at)} • {b.status}\n   📬 {b.sent}/{b.total} • ⚠️ {b.failed}\n   {(b.text or b.content_type)[:60]}" for b in rows] or ["—"]
    await show_text(cb, "\n".join(lines), None, ikb([[back_btn("a:bc")]]))
