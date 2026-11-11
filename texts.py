from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from admin.common import AdminFilter, back_btn, log_action, sep
from bot.keyboards.common import btn, ikb, pager_row
from bot.services.messaging import send_text, show_text
from bot.services.texts import T
from bot.states import AdminStates
from utils.defaults import CATEGORIES, DEFAULT_TEXTS, SAMPLE_VARS
from utils.helpers import PAGE_SIZE, clamp_page, page_count
from utils.telegram_text import entities_to_json

router = Router()
router.message.filter(AdminFilter("texts"))
router.callback_query.filter(AdminFilter("texts"))


@router.callback_query(F.data == "a:texts")
async def texts_menu(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.answer()
    rows = [[btn(title, f"a:tc:{cat}:0")] for cat, title in CATEGORIES.items()]
    rows.append([back_btn()])
    await show_text(cb, f"📝 ویرایش متن‌های ربات\n{sep()}\nیک دسته را انتخاب کنید.\n"
                        "💡 برای ایموجی پرمیوم، متن را همراه ایموجی پرمیوم بفرستید.", None, ikb(rows))


@router.callback_query(F.data.startswith("a:tc:"))
async def texts_cat(cb: CallbackQuery):
    await cb.answer()
    _, _, cat, page = cb.data.split(":")
    keys = [k for k, v in DEFAULT_TEXTS.items() if v[0] == cat]
    pages = page_count(len(keys))
    page = clamp_page(int(page), pages)
    chunk = keys[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
    rows = [[btn(DEFAULT_TEXTS[k][1], f"a:t:{k}")] for k in chunk]
    rows.append(pager_row(lambda p: f"a:tc:{cat}:{p}", page, pages))
    rows.append([back_btn("a:texts")])
    await show_text(cb, f"{CATEGORIES.get(cat, cat)}\n{sep()}", None, ikb(rows))


def text_kb(key: str):
    cat = DEFAULT_TEXTS[key][0]
    return ikb([[btn("✏️ ویرایش", f"a:tedit:{key}"), btn("♻️ بازنشانی", f"a:treset:{key}")],
                [btn("👁 پیش‌نمایش", f"a:tprev:{key}")], [back_btn(f"a:tc:{cat}:0")]])


async def view_text(event, key: str):
    cat, title, _default, hints = DEFAULT_TEXTS[key]
    value, ents = T.raw(key)
    n_ents = ents.count('"type"')
    shown = value if len(value) < 2500 else value[:2500] + "…"
    msg = (f"📝 {title}\n🔑 {key}\n{sep()}\n{shown}\n{sep()}\n"
           f"🧩 متغیرها: {hints or 'ندارد'}\n✨ فرمت/ایموجی ذخیره‌شده: {n_ents}\n"
           "ℹ️ {sep} جداکننده است و {e:name} ایموجی ذخیره‌شده در بخش «مدیریت ظاهر» را درج می‌کند.")
    await show_text(event, msg, None, text_kb(key))


@router.callback_query(F.data.startswith("a:t:"))
async def text_view(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.answer()
    key = cb.data[len("a:t:"):]
    if key in DEFAULT_TEXTS:
        await view_text(cb, key)


@router.callback_query(F.data.startswith("a:tprev:"))
async def text_preview(cb: CallbackQuery, bot):
    key = cb.data[len("a:tprev:"):]
    if key not in DEFAULT_TEXTS:
        await cb.answer()
        return
    await cb.answer("پیش‌نمایش ارسال شد")
    text, ents = T.render(key, cb.from_user, **SAMPLE_VARS)
    await send_text(bot, cb.from_user.id, text, ents, None)


@router.callback_query(F.data.startswith("a:tedit:"))
async def text_edit(cb: CallbackQuery, state: FSMContext):
    key = cb.data[len("a:tedit:"):]
    if key not in DEFAULT_TEXTS:
        await cb.answer()
        return
    await cb.answer()
    await state.set_state(AdminStates.text_edit)
    await state.update_data(key=key)
    is_btn = key.startswith("btn_")
    note = "برای دکمه‌ها فقط متن ساده (و ایموجی معمولی) ذخیره می‌شود." if is_btn else \
        "متن جدید را بفرستید. فرمت (بولد/ایتالیک...) و ایموجی پرمیوم حفظ می‌شود."
    await show_text(cb, f"✏️ ویرایش «{DEFAULT_TEXTS[key][1]}»\n{note}\n🧩 متغیرها: {DEFAULT_TEXTS[key][3] or 'ندارد'}", None,
                    ikb([[btn("❌ انصراف", f"a:t:{key}")]]))


@router.message(AdminStates.text_edit, F.text)
async def text_save(message: Message, state: FSMContext, session: AsyncSession, admin, bot):
    key = (await state.get_data())["key"]
    value = message.text
    if len(value) > 3900 or (key.startswith("btn_") and len(value) > 60):
        await send_text(bot, message.chat.id, "⚠️ متن بیش از حد طولانی است (دکمه حداکثر ۶۰ و پیام ۳۹۰۰ کاراکتر).", None, None)
        return
    ents = "[]" if key.startswith("btn_") else entities_to_json(message.entities)
    await T.set(session, key, value, ents)
    await log_action(session, admin.user_id, "text_edit", key)
    await state.clear()
    text, ents_r = T.render(key, message.from_user, **SAMPLE_VARS)
    await send_text(bot, message.chat.id, "✅ ذخیره شد. پیش‌نمایش:", None, None)
    await send_text(bot, message.chat.id, text, ents_r, ikb([[btn("🔙 بازگشت", f"a:t:{key}")]]))


@router.message(AdminStates.text_edit)
async def text_save_bad(message: Message):
    await send_text(message.bot, message.chat.id, "⚠️ فقط پیام متنی بفرستید.", None, None)


@router.callback_query(F.data.startswith("a:treset:"))
async def text_reset(cb: CallbackQuery, session: AsyncSession, admin):
    key = cb.data[len("a:treset:"):]
    if key not in DEFAULT_TEXTS:
        await cb.answer()
        return
    await T.reset(session, key)
    await log_action(session, admin.user_id, "text_reset", key)
    await cb.answer("♻️ بازنشانی شد")
    await view_text(cb, key)
