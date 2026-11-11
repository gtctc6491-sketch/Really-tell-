from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from admin.common import AdminFilter, back_btn, sep
from bot.keyboards.common import btn, ikb
from bot.services.messaging import show_text, send_text
from bot.services.perms import ROLES, can
from database.models import Broadcast, Gift, Request, Ticket, User, UserGift, utcnow
from datetime import timedelta

router = Router()
router.message.filter(AdminFilter())
router.callback_query.filter(AdminFilter())

ITEMS = [
    ("📊 آمار ربات", "a:stats", None),
    ("👥 مدیریت کاربران", "a:users:0", "users"),
    ("💰 مدیریت درخواست‌ها", "a:reqs:all:0", "requests"),
    ("🎁 مدیریت گیفت", "a:gifts", "gifts"),
    ("🎫 مدیریت تیکت‌ها", "a:tks:waiting:0", "tickets"),
    ("📢 پیام همگانی", "a:bc", "broadcast"),
    ("📝 ویرایش متن‌های ربات", "a:texts", "texts"),
    ("🎨 مدیریت ظاهر ربات", "a:app", "appearance"),
    ("📣 مدیریت کانال‌ها", "a:ch", "channels"),
    ("👮 مدیریت ادمین‌ها", "a:adm", "admins"),
    ("⚙ تنظیمات", "a:set", "settings"),
]


def panel_text(admin) -> str:
    return f"👑 پنل مدیریت LBank Buyer\n{sep()}\n🎭 نقش شما: {ROLES.get(admin.role, admin.role)}\n{sep()}\nیک بخش را انتخاب کنید:"


def panel_kb(admin):
    allowed = [(t, d) for t, d, p in ITEMS if p is None or can(admin, p)]
    rows = [[btn(t, d) for t, d in allowed[i:i + 2]] for i in range(0, len(allowed), 2)]
    rows.append([btn("🏠 منوی کاربر", "menu")])
    return ikb(rows)


@router.message(Command("admin", "panel"))
async def cmd_admin(message: Message, state: FSMContext, admin):
    await state.clear()
    await send_text(message.bot, message.chat.id, panel_text(admin), None, panel_kb(admin))


@router.callback_query(F.data == "a:home")
async def home(cb: CallbackQuery, state: FSMContext, admin):
    await state.clear()
    await cb.answer()
    await show_text(cb, panel_text(admin), None, panel_kb(admin))


@router.callback_query(F.data == "a:stats")
async def stats(cb: CallbackQuery, session: AsyncSession):
    await cb.answer()
    day_ago = utcnow() - timedelta(days=1)
    total_users = await session.scalar(select(func.count(User.id))) or 0
    new_users = await session.scalar(select(func.count(User.id)).where(User.joined_at >= day_ago)) or 0
    active = await session.scalar(select(func.count(User.id)).where(User.last_seen >= day_ago)) or 0
    blocked = await session.scalar(select(func.count(User.id)).where(User.is_blocked.is_(True))) or 0

    async def count_req(status: str) -> int:
        return await session.scalar(select(func.count(Request.id)).where(Request.status == status)) or 0

    async def count_tk(status: str) -> int:
        return await session.scalar(select(func.count(Ticket.id)).where(Ticket.status == status)) or 0

    req_total = await session.scalar(select(func.count(Request.id))) or 0
    gifts = await session.scalar(select(func.count(Gift.id)).where(Gift.is_deleted.is_(False))) or 0
    given = await session.scalar(select(func.count(UserGift.id))) or 0
    bcs = await session.scalar(select(func.count(Broadcast.id))) or 0
    text = (
        f"📊 آمار ربات\n{sep()}\n"
        f"👥 کاربران: {total_users}\n🆕 عضو جدید (۲۴ ساعت): {new_users}\n🟢 فعال (۲۴ ساعت): {active}\n🚫 مسدود: {blocked}\n{sep()}\n"
        f"💰 کل درخواست‌ها: {req_total}\n"
        f"   ⏳ در انتظار: {await count_req('pending')}\n   🔍 در حال بررسی: {await count_req('in_review')}\n"
        f"   ✅ تأیید شده: {await count_req('approved')}\n   ❌ رد شده: {await count_req('rejected')}\n{sep()}\n"
        f"🎫 تیکت‌ها: در انتظار {await count_tk('waiting')} • پاسخ داده {await count_tk('answered')} • بسته {await count_tk('closed')}\n"
        f"🎁 گیفت‌ها: {gifts} • دریافت‌شده: {given}\n📢 پیام‌های همگانی: {bcs}"
    )
    await show_text(cb, text, None, ikb([[back_btn()]]))
