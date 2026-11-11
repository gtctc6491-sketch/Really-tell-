from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from admin.common import AdminFilter, back_btn, home_btn, log_action, sep
from bot.handlers.tickets import format_history, ticket_messages
from bot.keyboards.common import btn, ikb, pager_row, tb
from bot.services.messaging import send_key, send_text, show_text
from bot.services.notify import send_file
from bot.states import AdminStates
from database.models import Ticket, TicketMessage, User, utcnow
from utils.helpers import (PAGE_SIZE, TICKET_EMOJI, TICKET_STATUS, clamp_page, fmt_dt, page_count, uname)

router = Router()
router.message.filter(AdminFilter("tickets"))
router.callback_query.filter(AdminFilter("tickets"))

FILTERS = [("waiting", "🟡 در انتظار"), ("answered", "🟢 پاسخ داده"), ("closed", "⚫️ بسته"), ("all", "📋 همه")]


@router.callback_query(F.data.startswith("a:tks:"))
async def tickets_list(cb: CallbackQuery, session: AsyncSession, state: FSMContext):
    await state.clear()
    await cb.answer()
    _, _, status, page = cb.data.split(":")
    cond = [] if status == "all" else [Ticket.status == status]
    total = await session.scalar(select(func.count(Ticket.id)).where(*cond)) or 0
    pages = page_count(total)
    page = clamp_page(int(page), pages)
    tks = (await session.execute(select(Ticket).where(*cond).order_by(Ticket.updated_at.desc())
                                 .offset(page * PAGE_SIZE).limit(PAGE_SIZE))).scalars().all()
    rows = [[btn(("🔸" if k == status else "") + label, f"a:tks:{k}:0") for k, label in FILTERS[:2]],
            [btn(("🔸" if k == status else "") + label, f"a:tks:{k}:0") for k, label in FILTERS[2:]]]
    rows += [[btn(f"{TICKET_EMOJI.get(t.status, '•')} #{t.id} {t.title[:26]}", f"a:tk:{t.id}")] for t in tks]
    rows.append(pager_row(lambda p: f"a:tks:{status}:{p}", page, pages))
    rows.append([back_btn()])
    await show_text(cb, f"🎫 تیکت‌ها ({total})\n{sep()}", None, ikb(rows))


async def ticket_card(session: AsyncSession, t: Ticket) -> str:
    u = await session.get(User, t.user_id)
    msgs = await ticket_messages(session, t.id)
    return (f"🎫 تیکت #{t.id}\n📌 {t.title}\n👤 {u.first_name if u else '—'} • {uname(u.username if u else None)} • {t.user_id}\n"
            f"📊 {TICKET_STATUS.get(t.status, t.status)} • {fmt_dt(t.created_at)}\n{sep()}\n{format_history(msgs, 'admin')}")


def ticket_kb(t: Ticket):
    rows = []
    if t.status != "closed":
        rows.append([btn("💬 پاسخ", f"a:tkr:{t.id}"), btn("🔒 بستن تیکت", f"a:tkc:{t.id}")])
    rows.append([btn("👤 کاربر", f"a:u:{t.user_id}")])
    rows.append([back_btn("a:tks:waiting:0")])
    return ikb(rows)


@router.callback_query(F.data.startswith("a:tk:"))
async def ticket_view(cb: CallbackQuery, session: AsyncSession, bot, state: FSMContext):
    await state.clear()
    t = await session.get(Ticket, int(cb.data.split(":")[2]))
    if not t:
        await cb.answer("تیکت پیدا نشد", show_alert=True)
        return
    await cb.answer()
    await show_text(cb, await ticket_card(session, t), None, ticket_kb(t))
    files = (await session.execute(select(TicketMessage).where(TicketMessage.ticket_id == t.id, TicketMessage.file_id.is_not(None))
                                   .order_by(TicketMessage.id.desc()).limit(5))).scalars().all()
    for m in reversed(files):
        try:
            await send_file(bot, cb.from_user.id, m.file_type, m.file_id, caption=f"📎 تیکت #{t.id} ({'کاربر' if m.sender_role == 'user' else 'ادمین'})")
        except Exception:
            pass


@router.callback_query(F.data.startswith("a:tkr:"))
async def ticket_reply_start(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    tid = int(cb.data.split(":")[2])
    await state.set_state(AdminStates.ticket_reply)
    await state.update_data(tid=tid)
    await show_text(cb, f"💬 پاسخ تیکت #{tid} را بفرستید (متن، عکس یا فایل):", None, ikb([[btn("❌ انصراف", f"a:tk:{tid}")]]))


@router.message(AdminStates.ticket_reply, F.text | F.photo | F.document)
async def ticket_reply_send(message: Message, state: FSMContext, session: AsyncSession, admin, bot):
    tid = (await state.get_data())["tid"]
    await state.clear()
    t = await session.get(Ticket, tid)
    if not t:
        return
    text = message.text or message.caption
    file_id = file_type = None
    if message.photo:
        file_id, file_type = message.photo[-1].file_id, "photo"
    elif message.document:
        file_id, file_type = message.document.file_id, "document"
    session.add(TicketMessage(ticket_id=tid, sender_role="admin", sender_id=admin.user_id, text=text,
                              file_id=file_id, file_type=file_type))
    t.status, t.updated_at = "answered", utcnow()
    await log_action(session, admin.user_id, "ticket_reply", f"#{tid}")
    await session.flush()
    user = await session.get(User, t.user_id)
    kb = ikb([[btn(tb("btn_view_ticket"), f"tk:view:{tid}")]])
    try:
        await send_key(bot, t.user_id, "ticket_admin_replied", kb, user, ticket_id=tid, title=t.title,
                       reply=text or "📎 فایل")
        if file_id:
            await send_file(bot, t.user_id, file_type, file_id, caption=f"📎 تیکت #{tid}")
        result = "✅ پاسخ ارسال شد."
    except Exception as e:
        result = f"⚠️ پاسخ ثبت شد ولی به کاربر تحویل نشد: {e}"
    await send_text(bot, message.chat.id, result, None, ikb([[btn("🔙 تیکت", f"a:tk:{tid}")], [back_btn("a:tks:waiting:0", "📋 لیست")]]))


@router.callback_query(F.data.startswith("a:tkc:"))
async def ticket_close(cb: CallbackQuery, session: AsyncSession, admin, bot):
    t = await session.get(Ticket, int(cb.data.split(":")[2]))
    if not t:
        await cb.answer("پیدا نشد", show_alert=True)
        return
    t.status, t.updated_at = "closed", utcnow()
    await log_action(session, admin.user_id, "ticket_close", f"#{t.id}")
    await cb.answer("🔒 بسته شد")
    user = await session.get(User, t.user_id)
    try:
        await send_key(bot, t.user_id, "ticket_closed", None, user, ticket_id=t.id, title=t.title)
    except Exception:
        pass
    await show_text(cb, await ticket_card(session, t), None, ticket_kb(t))
