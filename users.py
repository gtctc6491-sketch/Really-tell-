from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from admin.common import AdminFilter, back_btn, cancel_row, find_users, home_btn, log_action, sep, user_label
from bot.keyboards.common import btn, ikb, pager_row
from bot.services.messaging import send_text, show_text
from bot.services.settings import cfg
from bot.states import AdminStates
from database.models import Admin, Gift, Request, Ticket, User, UserGift
from utils.helpers import (PAGE_SIZE, REQUEST_EMOJI, TICKET_EMOJI, clamp_page, fmt_amount, fmt_dt, full_name,
                           page_count, uname)

router = Router()
router.message.filter(AdminFilter("users"))
router.callback_query.filter(AdminFilter("users"))


def users_kb(users: list[User]):
    return [[btn(("🚫 " if u.is_blocked else "👤 ") + f"{(u.first_name or '—')[:18]} • {u.id}", f"a:u:{u.id}")]
            for u in users]


@router.callback_query(F.data.startswith("a:users:"))
async def users_list(cb: CallbackQuery, session: AsyncSession):
    await cb.answer()
    total = await session.scalar(select(func.count(User.id))) or 0
    pages = page_count(total)
    page = clamp_page(int(cb.data.split(":")[2]), pages)
    users = (await session.execute(select(User).order_by(User.joined_at.desc())
                                   .offset(page * PAGE_SIZE).limit(PAGE_SIZE))).scalars().all()
    rows = users_kb(users)
    rows.append(pager_row(lambda p: f"a:users:{p}", page, pages))
    rows.append([btn("🔍 جستجوی کاربر", "a:usearch")])
    rows.append([back_btn()])
    await show_text(cb, f"👥 کاربران ({total})\n{sep()}", None, ikb(rows))


@router.callback_query(F.data == "a:usearch")
async def usearch(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.set_state(AdminStates.search_user)
    await show_text(cb, "🔍 آیدی عددی، یوزرنیم یا بخشی از نام کاربر را بفرستید:", None, ikb([cancel_row()]))


@router.message(AdminStates.search_user, F.text)
async def usearch_do(message: Message, state: FSMContext, session: AsyncSession):
    users = await find_users(session, message.text)
    await state.clear()
    if not users:
        await send_text(message.bot, message.chat.id, "❌ کاربری پیدا نشد.", None,
                        ikb([[btn("🔍 جستجوی دوباره", "a:usearch")], [back_btn()]]))
        return
    rows = users_kb(users) + [[back_btn()]]
    await send_text(message.bot, message.chat.id, f"🔍 نتایج ({len(users)})", None, ikb(rows))


async def user_card(session: AsyncSession, u: User) -> str:
    rc = await session.scalar(select(func.count(Request.id)).where(Request.user_id == u.id)) or 0
    tc = await session.scalar(select(func.count(Ticket.id)).where(Ticket.user_id == u.id)) or 0
    gc = await session.scalar(select(func.count(UserGift.id)).where(UserGift.user_id == u.id)) or 0
    is_adm = await session.get(Admin, u.id)
    return (f"👤 اطلاعات کاربر\n{sep()}\n🆔 {u.id}\n📛 {full_name(u.first_name, u.last_name)}\n🔗 {uname(u.username)}\n"
            f"📅 عضویت: {fmt_dt(u.joined_at)}\n🕒 آخرین فعالیت: {fmt_dt(u.last_seen)}\n"
            f"🚫 وضعیت: {'مسدود' if u.is_blocked else 'فعال'}{' • 👮 ادمین' if is_adm else ''}\n{sep()}\n"
            f"💰 درخواست‌ها: {rc}\n🎫 تیکت‌ها: {tc}\n🎁 گیفت‌ها: {gc}")


def user_kb(u: User):
    return ikb([
        [btn("✅ رفع مسدودی" if u.is_blocked else "🚫 مسدودسازی", f"a:ublock:{u.id}"),
         btn("✉️ پیام اختصاصی", f"a:umsg:{u.id}")],
        [btn("📜 سوابق", f"a:uhist:{u.id}"), btn("💰 درخواست‌ها", f"a:reqs_u:{u.id}")],
        [back_btn("a:users:0")], [home_btn()]])


@router.callback_query(F.data.startswith("a:u:"))
async def user_view(cb: CallbackQuery, session: AsyncSession, state: FSMContext):
    await state.clear()
    u = await session.get(User, int(cb.data.split(":")[2]))
    if not u:
        await cb.answer("کاربر پیدا نشد", show_alert=True)
        return
    await cb.answer()
    await show_text(cb, await user_card(session, u), None, user_kb(u))


@router.callback_query(F.data.startswith("a:ublock:"))
async def user_block(cb: CallbackQuery, session: AsyncSession, admin):
    u = await session.get(User, int(cb.data.split(":")[2]))
    if not u:
        await cb.answer("کاربر پیدا نشد", show_alert=True)
        return
    if await session.get(Admin, u.id):
        await cb.answer("⛔ ادمین‌ها را نمی‌توان مسدود کرد.", show_alert=True)
        return
    u.is_blocked = not u.is_blocked
    await log_action(session, admin.user_id, "block" if u.is_blocked else "unblock", str(u.id))
    await cb.answer("🚫 مسدود شد" if u.is_blocked else "✅ رفع مسدودی شد")
    await show_text(cb, await user_card(session, u), None, user_kb(u))


@router.callback_query(F.data.startswith("a:umsg:"))
async def user_msg(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    uid = int(cb.data.split(":")[2])
    await state.set_state(AdminStates.user_message)
    await state.update_data(uid=uid)
    await show_text(cb, f"✉️ پیام خود را برای کاربر {uid} بفرستید (متن، عکس، فایل...):", None,
                    ikb([[btn("❌ انصراف", f"a:u:{uid}")]]))


@router.message(AdminStates.user_message)
async def user_msg_send(message: Message, state: FSMContext, session: AsyncSession, admin):
    uid = (await state.get_data())["uid"]
    await state.clear()
    try:
        await message.copy_to(uid)
        result = "✅ پیام ارسال شد."
        await log_action(session, admin.user_id, "user_message", str(uid))
    except Exception as e:
        result = f"⚠️ ارسال ناموفق: {e}"
    await send_text(message.bot, message.chat.id, result, None, ikb([[back_btn(f"a:u:{uid}", "🔙 کاربر")], [home_btn()]]))


@router.callback_query(F.data.startswith("a:uhist:"))
async def user_hist(cb: CallbackQuery, session: AsyncSession):
    await cb.answer()
    uid = int(cb.data.split(":")[2])
    reqs = (await session.execute(select(Request).where(Request.user_id == uid).order_by(Request.id.desc()).limit(10))).scalars().all()
    tks = (await session.execute(select(Ticket).where(Ticket.user_id == uid).order_by(Ticket.id.desc()).limit(5))).scalars().all()
    gifts = (await session.execute(select(UserGift, Gift.name).join(Gift, Gift.id == UserGift.gift_id)
                                   .where(UserGift.user_id == uid).order_by(UserGift.id.desc()).limit(5))).all()
    lines = [f"📜 سوابق کاربر {uid}\n{sep()}", "💰 درخواست‌ها:"]
    lines += [f"{REQUEST_EMOJI.get(r.status, '•')} #{r.id} • {fmt_amount(r.amount)}$ • {r.year} • {fmt_dt(r.created_at)}" for r in reqs] or ["—"]
    lines.append("\n🎫 تیکت‌ها:")
    lines += [f"{TICKET_EMOJI.get(t.status, '•')} #{t.id} {t.title[:30]}" for t in tks] or ["—"]
    lines.append("\n🎁 گیفت‌ها:")
    lines += [f"• {name} ({ug.source}) • {fmt_dt(ug.created_at)}" for ug, name in gifts] or ["—"]
    await show_text(cb, "\n".join(lines), None, ikb([[back_btn(f"a:u:{uid}", "🔙 کاربر")]]))
