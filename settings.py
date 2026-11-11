from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from admin.common import AdminFilter, back_btn, log_action, sep
from bot.keyboards.common import btn, ikb, pager_row
from bot.services.backup import send_backup
from bot.services.messaging import send_text, show_text
from bot.services.settings import cfg
from bot.states import AdminStates
from database.models import AdminLog
from utils.defaults import SETTINGS_META
from utils.helpers import PAGE_SIZE, clamp_page, fmt_dt, norm_digits, page_count

router = Router()
router.message.filter(AdminFilter("settings"))
router.callback_query.filter(AdminFilter("settings"))


def value_label(key: str, typ: str) -> str:
    if typ == "bool":
        return "روشن ✅" if cfg.bool(key) else "خاموش ⚪️"
    return cfg.get(key) or "—"


async def settings_page(event):
    rows = [[btn(f"{title}: {value_label(k, typ)}", f"a:setv:{k}")] for k, (title, typ) in SETTINGS_META.items()]
    rows.append([btn("💾 پشتیبان‌گیری دیتابیس", "a:backup"), btn("📜 گزارش فعالیت‌ها", "a:logs:0")])
    rows.append([back_btn()])
    await show_text(event, f"⚙ تنظیمات\n{sep()}\nروی هر مورد بزنید تا تغییر کند.", None, ikb(rows))


@router.callback_query(F.data == "a:set")
async def set_menu(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.answer()
    await settings_page(cb)


@router.callback_query(F.data.startswith("a:setv:"))
async def set_value(cb: CallbackQuery, session: AsyncSession, state: FSMContext, admin):
    key = cb.data.split(":", 2)[2]
    if key not in SETTINGS_META:
        await cb.answer()
        return
    title, typ = SETTINGS_META[key]
    if typ == "bool":
        new = "0" if cfg.bool(key) else "1"
        await cfg.set(session, key, new)
        await log_action(session, admin.user_id, "setting", f"{key}={new}")
        await cb.answer("✅ تغییر کرد")
        await settings_page(cb)
        return
    await cb.answer()
    await state.set_state(AdminStates.setting_edit)
    await state.update_data(key=key)
    extra = " (برای حذف «-» بفرستید)" if key == "support_username" else " (عدد)"
    await show_text(cb, f"✏️ «{title}»\nمقدار فعلی: {cfg.get(key) or '—'}\nمقدار جدید را بفرستید{extra}:", None,
                    ikb([[btn("❌ انصراف", "a:set")]]))


@router.message(AdminStates.setting_edit, F.text)
async def set_save(message: Message, state: FSMContext, session: AsyncSession, admin):
    key = (await state.get_data())["key"]
    typ = SETTINGS_META[key][1]
    text = message.text.strip()
    if typ == "int":
        n = norm_digits(text)
        if not n.isdigit():
            await send_text(message.bot, message.chat.id, "⚠️ فقط عدد بفرستید.", None, None)
            return
        value = str(int(n))
    else:
        value = "" if text == "-" else text.lstrip("@")[:64]
    await cfg.set(session, key, value)
    await log_action(session, admin.user_id, "setting", f"{key}={value}")
    await state.clear()
    await send_text(message.bot, message.chat.id, "✅ ذخیره شد.", None, ikb([[btn("🔙 تنظیمات", "a:set")]]))


@router.callback_query(F.data == "a:backup")
async def backup_now(cb: CallbackQuery, session: AsyncSession, admin, bot):
    await cb.answer("در حال ساخت پشتیبان...")
    await session.commit()
    try:
        await send_backup(bot, cb.from_user.id)
    except Exception as e:
        await send_text(bot, cb.from_user.id, f"⚠️ پشتیبان‌گیری ناموفق: {e}", None, None)
        return
    await log_action(session, admin.user_id, "backup", "manual")


@router.callback_query(F.data.startswith("a:logs:"))
async def logs_view(cb: CallbackQuery, session: AsyncSession):
    await cb.answer()
    total = await session.scalar(select(func.count(AdminLog.id))) or 0
    pages = page_count(total)
    page = clamp_page(int(cb.data.split(":")[2]), pages)
    rows = (await session.execute(select(AdminLog).order_by(AdminLog.id.desc())
                                  .offset(page * PAGE_SIZE).limit(PAGE_SIZE))).scalars().all()
    lines = [f"📜 گزارش فعالیت‌ها ({total})\n{sep()}"]
    lines += [f"👮 {r.admin_id} • {r.action}\n   {r.details[:80]} • {fmt_dt(r.created_at)}" for r in rows] or ["—"]
    kb = [pager_row(lambda p: f"a:logs:{p}", page, pages), [back_btn("a:set")]]
    await show_text(cb, "\n".join(lines), None, ikb(kb))
