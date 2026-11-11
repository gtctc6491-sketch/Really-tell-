import re

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from admin.common import AdminFilter, back_btn, log_action, sep
from bot.keyboards.common import btn, ikb
from bot.services.messaging import send_text, show_text
from bot.services.subscription import _ok_until
from bot.states import AdminStates
from database.models import MandatoryChannel
from utils.helpers import norm_digits

router = Router()
router.message.filter(AdminFilter("channels"))
router.callback_query.filter(AdminFilter("channels"))


async def channels_page(event, session: AsyncSession):
    chans = (await session.execute(select(MandatoryChannel).order_by(MandatoryChannel.id))).scalars().all()
    rows = []
    for c in chans:
        rows.append([btn(f"{'🟢' if c.is_active else '⚪️'} {c.title[:22]}", f"a:chtog:{c.id}"),
                     btn("🗑", f"a:chdel:{c.id}")])
    rows.append([btn("➕ افزودن کانال", "a:chadd")])
    rows.append([back_btn()])
    await show_text(event, f"📣 کانال‌های عضویت اجباری ({len(chans)})\n{sep()}\n"
                           "🟢 فعال • ⚪️ غیرفعال (برای تغییر وضعیت روی نام بزنید)\n"
                           "⚠️ ربات باید در کانال/گروه ادمین باشد.", None, ikb(rows))


@router.callback_query(F.data == "a:ch")
async def ch_menu(cb: CallbackQuery, session: AsyncSession, state: FSMContext):
    await state.clear()
    await cb.answer()
    await channels_page(cb, session)


@router.callback_query(F.data.startswith("a:chtog:"))
async def ch_toggle(cb: CallbackQuery, session: AsyncSession, admin):
    c = await session.get(MandatoryChannel, int(cb.data.split(":")[2]))
    if c:
        c.is_active = not c.is_active
        _ok_until.clear()
        await log_action(session, admin.user_id, "channel_toggle", f"{c.title} {c.is_active}")
    await cb.answer("انجام شد")
    await channels_page(cb, session)


@router.callback_query(F.data.startswith("a:chdel:"))
async def ch_delete(cb: CallbackQuery, session: AsyncSession, admin):
    c = await session.get(MandatoryChannel, int(cb.data.split(":")[2]))
    if c:
        await session.delete(c)
        _ok_until.clear()
        await log_action(session, admin.user_id, "channel_delete", c.title)
    await cb.answer("🗑 حذف شد")
    await session.flush()
    await channels_page(cb, session)


@router.callback_query(F.data == "a:chadd")
async def ch_add(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.set_state(AdminStates.channel_add)
    await show_text(cb, "➕ یوزرنیم کانال (@channel)، لینک t.me یا آیدی عددی (مثل -100123...) را بفرستید.\n"
                        "ربات باید ادمین آن کانال باشد.", None, ikb([[btn("❌ انصراف", "a:ch")]]))


def parse_chat_ref(text: str):
    t = norm_digits(text.strip())
    m = re.search(r"(?:t\.me/|telegram\.me/)([A-Za-z0-9_]{4,})", t)
    if m:
        return "@" + m.group(1)
    if re.fullmatch(r"-?\d{5,}", t):
        return int(t)
    if re.fullmatch(r"@?[A-Za-z0-9_]{4,}", t):
        return "@" + t.lstrip("@")
    return None


@router.message(AdminStates.channel_add, F.text)
async def ch_resolve(message: Message, state: FSMContext, session: AsyncSession, admin, bot):
    ref = parse_chat_ref(message.text)
    if ref is None:
        await send_text(bot, message.chat.id, "⚠️ ورودی نامعتبر است. یوزرنیم، لینک یا آیدی عددی بفرستید.", None, None)
        return
    try:
        chat = await bot.get_chat(ref)
    except Exception as e:
        await send_text(bot, message.chat.id, f"⚠️ کانال پیدا نشد یا ربات به آن دسترسی ندارد:\n{e}", None, None)
        return
    warn = ""
    try:
        me = await bot.get_chat_member(chat.id, bot.id)
        if me.status not in ("administrator", "creator"):
            warn = "\n⚠️ ربات در این کانال ادمین نیست؛ بررسی عضویت درست کار نمی‌کند."
    except Exception:
        warn = "\n⚠️ وضعیت ربات در کانال قابل بررسی نبود؛ ادمین‌بودن ربات را مطمئن شوید."
    link = f"https://t.me/{chat.username}" if chat.username else (chat.invite_link or None)
    if not link:
        try:
            link = await bot.export_chat_invite_link(chat.id)
        except Exception:
            link = None
    if not link:
        await state.update_data(chat_id=chat.id, title=chat.title or str(chat.id), warn=warn)
        await state.set_state(AdminStates.channel_link)
        await send_text(bot, message.chat.id, "🔗 این کانال خصوصی است. لینک دعوت آن را بفرستید:", None, None)
        return
    await _save_channel(message, state, session, admin, chat.id, chat.title or str(chat.id), link, warn)


@router.message(AdminStates.channel_link, F.text)
async def ch_link(message: Message, state: FSMContext, session: AsyncSession, admin):
    link = message.text.strip()
    if not re.match(r"^https?://", link):
        await send_text(message.bot, message.chat.id, "⚠️ لینک باید با https:// شروع شود.", None, None)
        return
    d = await state.get_data()
    await _save_channel(message, state, session, admin, d["chat_id"], d["title"], link, d.get("warn", ""))


async def _save_channel(message, state, session, admin, chat_id, title, link, warn):
    exists = (await session.execute(select(MandatoryChannel).where(MandatoryChannel.chat_id == chat_id))).scalar_one_or_none()
    await state.clear()
    if exists:
        exists.title, exists.link, exists.is_active = title, link, True
    else:
        session.add(MandatoryChannel(chat_id=chat_id, title=title, link=link, is_active=True))
    _ok_until.clear()
    await log_action(session, admin.user_id, "channel_add", f"{title} {chat_id}")
    await send_text(message.bot, message.chat.id, f"✅ کانال «{title}» ذخیره شد.{warn}", None,
                    ikb([[btn("🔙 کانال‌ها", "a:ch")]]))
