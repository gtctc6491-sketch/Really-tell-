from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from admin.common import AdminFilter, back_btn, log_action, sep
from bot.keyboards.common import btn, ikb
from bot.services.messaging import send_text, show_text
from bot.services.perms import ROLES
from bot.states import AdminStates
from config.settings import SUPER_ADMIN_IDS
from database.models import Admin, User
from utils.helpers import norm_digits

router = Router()
# only the super admin ("*") passes the "admins" permission
router.message.filter(AdminFilter("admins"))
router.callback_query.filter(AdminFilter("admins"))


async def admins_page(event, session: AsyncSession):
    admins = (await session.execute(select(Admin).order_by(Admin.created_at))).scalars().all()
    rows = []
    for a in admins:
        u = await session.get(User, a.user_id)
        name = u.first_name if u else "—"
        rows.append([btn(f"{ROLES.get(a.role, a.role)} • {name} • {a.user_id}", f"a:admv:{a.user_id}")])
    rows.append([btn("➕ افزودن ادمین", "a:admadd")])
    rows.append([back_btn()])
    await show_text(event, f"👮 مدیریت ادمین‌ها ({len(admins)})\n{sep()}", None, ikb(rows))


@router.callback_query(F.data == "a:adm")
async def adm_menu(cb: CallbackQuery, session: AsyncSession, state: FSMContext):
    await state.clear()
    await cb.answer()
    await admins_page(cb, session)


@router.callback_query(F.data.startswith("a:admv:"))
async def adm_view(cb: CallbackQuery, session: AsyncSession):
    await cb.answer()
    uid = int(cb.data.split(":")[2])
    a = await session.get(Admin, uid)
    if not a:
        await admins_page(cb, session)
        return
    protected = uid in SUPER_ADMIN_IDS
    rows = []
    if not protected:
        rows += [[btn(("✅ " if a.role == r else "") + title, f"a:admrole:{uid}:{r}")] for r, title in ROLES.items()]
        rows.append([btn("🗑 حذف ادمین", f"a:admdel:{uid}")])
    rows.append([back_btn("a:adm")])
    note = "\n🔒 این مدیر کل در تنظیمات سرور (ADMIN_IDS) تعریف شده و قابل تغییر نیست." if protected else ""
    await show_text(cb, f"👮 ادمین {uid}\n🎭 نقش: {ROLES.get(a.role, a.role)}{note}", None, ikb(rows))


@router.callback_query(F.data.startswith("a:admrole:"))
async def adm_role(cb: CallbackQuery, session: AsyncSession, admin):
    _, _, uid, role = cb.data.split(":")
    uid = int(uid)
    a = await session.get(Admin, uid)
    if not a or uid in SUPER_ADMIN_IDS or role not in ROLES:
        await cb.answer("⛔ امکان‌پذیر نیست", show_alert=True)
        return
    if uid == admin.user_id and role != "super":
        await cb.answer("⛔ نقش خودتان را نمی‌توانید کاهش دهید.", show_alert=True)
        return
    a.role = role
    await log_action(session, admin.user_id, "admin_role", f"{uid} -> {role}")
    await cb.answer("✅ تغییر کرد")
    await adm_view(cb, session)


@router.callback_query(F.data.startswith("a:admdel:"))
async def adm_del(cb: CallbackQuery, session: AsyncSession, admin):
    uid = int(cb.data.split(":")[2])
    a = await session.get(Admin, uid)
    if not a or uid in SUPER_ADMIN_IDS or uid == admin.user_id:
        await cb.answer("⛔ امکان حذف این ادمین وجود ندارد.", show_alert=True)
        return
    await session.delete(a)
    await log_action(session, admin.user_id, "admin_delete", str(uid))
    await session.flush()
    await cb.answer("🗑 حذف شد")
    await admins_page(cb, session)


@router.callback_query(F.data == "a:admadd")
async def adm_add(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.set_state(AdminStates.admin_add_id)
    await show_text(cb, "➕ آیدی عددی کاربری که می‌خواهید ادمین شود را بفرستید:", None, ikb([[btn("❌ انصراف", "a:adm")]]))


@router.message(AdminStates.admin_add_id, F.text)
async def adm_add_id(message: Message, state: FSMContext, session: AsyncSession):
    n = norm_digits(message.text.strip())
    if not n.isdigit():
        await send_text(message.bot, message.chat.id, "⚠️ فقط آیدی عددی بفرستید.", None, None)
        return
    uid = int(n)
    if await session.get(Admin, uid):
        await send_text(message.bot, message.chat.id, "ℹ️ این کاربر قبلاً ادمین است.", None, ikb([[btn("🔙", "a:adm")]]))
        await state.clear()
        return
    await state.update_data(new_uid=uid)
    rows = [[btn(title, f"a:admnew:{r}")] for r, title in ROLES.items()] + [[btn("❌ انصراف", "a:adm")]]
    await send_text(message.bot, message.chat.id, f"🎭 نقش کاربر {uid} را انتخاب کنید:", None, ikb(rows))


@router.callback_query(F.data.startswith("a:admnew:"))
async def adm_add_role(cb: CallbackQuery, state: FSMContext, session: AsyncSession, admin, bot):
    role = cb.data.split(":")[2]
    d = await state.get_data()
    uid = d.get("new_uid")
    if not uid or role not in ROLES:
        await cb.answer("منقضی شد", show_alert=True)
        return
    await state.clear()
    session.add(Admin(user_id=uid, role=role, added_by=admin.user_id))
    await log_action(session, admin.user_id, "admin_add", f"{uid} {role}")
    await session.flush()
    await cb.answer("✅ اضافه شد")
    try:
        await bot.send_message(uid, f"👮 شما به‌عنوان «{ROLES[role]}» به ربات اضافه شدید.\nبرای ورود به پنل /admin را بفرستید.", parse_mode=None)
    except Exception:
        pass
    await admins_page(cb, session)
