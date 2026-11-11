import re

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from admin.common import AdminFilter, back_btn, log_action, sep
from bot.keyboards.common import btn, ikb
from bot.services.messaging import send_text, show_text
from bot.services.settings import cfg
from bot.states import AdminStates
from utils.telegram_text import slice_u16

router = Router()
router.message.filter(AdminFilter("appearance"))
router.callback_query.filter(AdminFilter("appearance"))

NAME_RE = re.compile(r"^[A-Za-z0-9_]{1,20}$")


def app_kb():
    return ikb([
        [btn(f"{'🟢' if cfg.bool('premium_emoji') else '⚪️'} ایموجی پرمیوم: {'روشن' if cfg.bool('premium_emoji') else 'خاموش'}", "a:premtog")],
        [btn("➖ ویرایش جداکننده", "a:sep")],
        [btn("✨ کتابخانه ایموجی پرمیوم", "a:emojis")],
        [btn("📝 ویرایش متن‌ها و دکمه‌ها", "a:texts")],
        [back_btn()]])


async def app_page(event):
    await show_text(event, f"🎨 مدیریت ظاهر ربات\n{sep()}\n🖤 سبک: مشکی و طلایی\n"
                           f"➖ جداکننده فعلی:\n{cfg.get('separator')}\n{sep()}\n"
                           "ایموجی پرمیوم در صورت پشتیبانی نشدن، خودکار با ایموجی معمولی جایگزین می‌شود.", None, app_kb())


@router.callback_query(F.data == "a:app")
async def app_menu(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.answer()
    await app_page(cb)


@router.callback_query(F.data == "a:premtog")
async def prem_toggle(cb: CallbackQuery, session: AsyncSession, admin):
    new = "0" if cfg.bool("premium_emoji") else "1"
    await cfg.set(session, "premium_emoji", new)
    await log_action(session, admin.user_id, "premium_emoji", new)
    await cb.answer("انجام شد")
    await app_page(cb)


@router.callback_query(F.data == "a:sep")
async def sep_edit(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.set_state(AdminStates.separator_edit)
    await show_text(cb, "➖ جداکننده جدید را بفرستید (مثلاً ━━━━━━━━━━ یا ✦✦✦✦✦✦). حداکثر ۴۰ کاراکتر:", None,
                    ikb([[btn("❌ انصراف", "a:app")]]))


@router.message(AdminStates.separator_edit, F.text)
async def sep_save(message: Message, state: FSMContext, session: AsyncSession, admin):
    value = message.text.strip()
    if not value or len(value) > 40 or "\n" in value:
        await send_text(message.bot, message.chat.id, "⚠️ یک خط کوتاه (حداکثر ۴۰ کاراکتر) بفرستید.", None, None)
        return
    await cfg.set(session, "separator", value)
    await log_action(session, admin.user_id, "separator", value)
    await state.clear()
    await send_text(message.bot, message.chat.id, f"✅ ذخیره شد:\n{value}", None, ikb([[btn("🔙 ظاهر", "a:app")]]))


# ---------- custom emoji library ----------
@router.callback_query(F.data == "a:emojis")
async def emojis_list(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.answer()
    lib = cfg.emojis()
    lines = [f"✨ کتابخانه ایموجی پرمیوم\n{sep()}"]
    lines += [f"{v.get('fallback', '⭐')} {{e:{k}}} • {v.get('id')}" for k, v in lib.items()] or ["هنوز ایموجی ذخیره نشده."]
    lines.append("\nبرای استفاده در متن‌ها بنویسید: {e:نام}")
    rows = [[btn(f"🗑 {k}", f"a:emdel:{k}")] for k in lib]
    rows.append([btn("➕ افزودن ایموجی", "a:emadd")])
    rows.append([back_btn("a:app")])
    await show_text(cb, "\n".join(lines), None, ikb(rows))


@router.callback_query(F.data == "a:emadd")
async def emoji_add(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.set_state(AdminStates.emoji_add_emoji)
    await show_text(cb, "✨ یک پیام شامل ایموجی پرمیوم بفرستید تا شناسه (Custom Emoji ID) آن دریافت و ذخیره شود.", None,
                    ikb([[btn("❌ انصراف", "a:emojis")]]))


@router.message(AdminStates.emoji_add_emoji, F.text)
async def emoji_got(message: Message, state: FSMContext):
    ents = [e for e in (message.entities or []) if e.type == "custom_emoji"]
    if not ents:
        await send_text(message.bot, message.chat.id, "⚠️ ایموجی پرمیوم در پیام پیدا نشد. دوباره بفرستید.", None, None)
        return
    e = ents[0]
    fallback = slice_u16(message.text, e.offset, e.length) or "⭐"
    ids = "\n".join(f"{slice_u16(message.text, x.offset, x.length)} → {x.custom_emoji_id}" for x in ents)
    await state.update_data(eid=e.custom_emoji_id, fb=fallback)
    await state.set_state(AdminStates.emoji_add_name)
    await send_text(message.bot, message.chat.id,
                    f"🆔 شناسه‌های دریافت‌شده:\n{ids}\n\nیک نام لاتین برای اولین ایموجی بفرستید (حروف/عدد/_ ، حداکثر ۲۰):", None, None)


@router.message(AdminStates.emoji_add_name, F.text)
async def emoji_name(message: Message, state: FSMContext, session: AsyncSession, admin):
    name = message.text.strip()
    if not NAME_RE.match(name):
        await send_text(message.bot, message.chat.id, "⚠️ فقط حروف لاتین، عدد و _ (حداکثر ۲۰ کاراکتر).", None, None)
        return
    d = await state.get_data()
    lib = cfg.emojis()
    lib[name] = {"id": d["eid"], "fallback": d["fb"]}
    await cfg.set_emojis(session, lib)
    await log_action(session, admin.user_id, "emoji_add", name)
    await state.clear()
    await send_text(message.bot, message.chat.id, f"✅ ذخیره شد. در متن‌ها از {{e:{name}}} استفاده کنید.", None,
                    ikb([[btn("🔙 کتابخانه", "a:emojis")]]))


@router.callback_query(F.data.startswith("a:emdel:"))
async def emoji_del(cb: CallbackQuery, session: AsyncSession, admin):
    name = cb.data.split(":", 2)[2]
    lib = cfg.emojis()
    if name in lib:
        lib.pop(name)
        await cfg.set_emojis(session, lib)
        await log_action(session, admin.user_id, "emoji_del", name)
    await cb.answer("🗑 حذف شد")
    await _refresh_emojis(cb)


async def _refresh_emojis(cb: CallbackQuery):
    lib = cfg.emojis()
    lines = [f"✨ کتابخانه ایموجی پرمیوم\n{sep()}"]
    lines += [f"{v.get('fallback', '⭐')} {{e:{k}}} • {v.get('id')}" for k, v in lib.items()] or ["هنوز ایموجی ذخیره نشده."]
    rows = [[btn(f"🗑 {k}", f"a:emdel:{k}")] for k in lib]
    rows.append([btn("➕ افزودن ایموجی", "a:emadd")])
    rows.append([back_btn("a:app")])
    await show_text(cb, "\n".join(lines), None, ikb(rows))
