import json

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from admin.common import AdminFilter, back_btn, cancel_row, home_btn, log_action, sep
from bot.keyboards.common import btn, ikb, pager_row
from bot.services.messaging import send_key, send_text, show_text
from bot.services.notify import send_file
from bot.states import AdminStates
from database.models import Request, User, utcnow
from utils.helpers import (PAGE_SIZE, REQUEST_EMOJI, REQUEST_STATUS, clamp_page, fmt_amount, fmt_dt, full_name,
                           norm_digits, page_count, uname)

router = Router()
router.message.filter(AdminFilter("requests"))
router.callback_query.filter(AdminFilter("requests"))

FILTERS = [("all", "📋 همه"), ("pending", "⏳"), ("in_review", "🔍"), ("approved", "✅"), ("rejected", "❌")]


def req_buttons(reqs: list[Request]):
    return [[btn(f"{REQUEST_EMOJI.get(r.status, '•')} #{r.id} • {fmt_amount(r.amount)}$ • {r.year}", f"a:r:{r.id}")]
            for r in reqs]


@router.callback_query(F.data.startswith("a:reqs:"))
async def reqs_list(cb: CallbackQuery, session: AsyncSession, state: FSMContext):
    await state.clear()
    await cb.answer()
    _, _, status, page = cb.data.split(":")
    cond = [] if status == "all" else [Request.status == status]
    total = await session.scalar(select(func.count(Request.id)).where(*cond)) or 0
    pages = page_count(total)
    page = clamp_page(int(page), pages)
    reqs = (await session.execute(select(Request).where(*cond).order_by(Request.id.desc())
                                  .offset(page * PAGE_SIZE).limit(PAGE_SIZE))).scalars().all()
    rows = [[btn(("🔸" if k == status else "") + label, f"a:reqs:{k}:0") for k, label in FILTERS]]
    rows += req_buttons(reqs)
    rows.append(pager_row(lambda p: f"a:reqs:{status}:{p}", page, pages))
    rows.append([btn("🔍 جستجو", "a:rsearch")])
    rows.append([back_btn()])
    title = "همه" if status == "all" else REQUEST_STATUS[status]
    await show_text(cb, f"💰 درخواست‌ها • {title} ({total})\n{sep()}", None, ikb(rows))


@router.callback_query(F.data.startswith("a:reqs_u:"))
async def reqs_of_user(cb: CallbackQuery, session: AsyncSession):
    await cb.answer()
    uid = int(cb.data.split(":")[2])
    reqs = (await session.execute(select(Request).where(Request.user_id == uid)
                                  .order_by(Request.id.desc()).limit(15))).scalars().all()
    rows = req_buttons(reqs) + [[back_btn(f"a:u:{uid}", "🔙 کاربر")]]
    await show_text(cb, f"💰 درخواست‌های کاربر {uid} ({len(reqs)})", None, ikb(rows))


@router.callback_query(F.data == "a:rsearch")
async def rsearch(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.set_state(AdminStates.search_request)
    await show_text(cb, "🔍 شماره درخواست، آیدی عددی کاربر یا یوزرنیم را بفرستید:", None, ikb([cancel_row()]))


@router.message(AdminStates.search_request, F.text)
async def rsearch_do(message: Message, state: FSMContext, session: AsyncSession):
    q = norm_digits(message.text.strip()).lstrip("#")
    await state.clear()
    reqs: list[Request] = []
    if q.isdigit():
        n = int(q)
        reqs = list((await session.execute(select(Request).where(or_(Request.id == n, Request.user_id == n))
                                           .order_by(Request.id.desc()).limit(15))).scalars().all())
    else:
        un = q.lstrip("@")
        reqs = list((await session.execute(select(Request).join(User, User.id == Request.user_id)
                                           .where(User.username.ilike(f"%{un}%")).order_by(Request.id.desc())
                                           .limit(15))).scalars().all())
    if not reqs:
        await send_text(message.bot, message.chat.id, "❌ درخواستی پیدا نشد.", None,
                        ikb([[btn("🔍 جستجوی دوباره", "a:rsearch")], [back_btn("a:reqs:all:0")]]))
        return
    await send_text(message.bot, message.chat.id, f"🔍 نتایج ({len(reqs)})", None,
                    ikb(req_buttons(reqs) + [[back_btn("a:reqs:all:0")]]))


async def request_card(session: AsyncSession, r: Request) -> str:
    u = await session.get(User, r.user_id)
    docs = json.loads(r.docs or "[]")
    handler = await session.get(User, r.handled_by) if r.handled_by else None
    return (f"💰 درخواست #{r.id}\n{sep()}\n"
            f"👤 کاربر: {full_name(u.first_name if u else '', u.last_name if u else '')} • {uname(u.username if u else None)} • {r.user_id}\n"
            f"💵 مبلغ: {fmt_amount(r.amount)} دلار\n📅 سال اکانت: {r.year}\n📎 مدارک: {len(docs)} فایل\n"
            f"📊 وضعیت: {REQUEST_STATUS.get(r.status, r.status)}\n📝 توضیحات: {r.admin_note or '—'}\n"
            f"🕒 ثبت: {fmt_dt(r.created_at)}\n🔄 آخرین تغییر: {fmt_dt(r.updated_at)}\n"
            f"👮 رسیدگی: {handler.first_name if handler else (r.handled_by or '—')}")


def request_kb(r: Request):
    return ikb([
        [btn("✅ تأیید", f"a:rset:{r.id}:approved"), btn("❌ رد", f"a:rset:{r.id}:rejected")],
        [btn("🔍 در حال بررسی", f"a:rset:{r.id}:in_review"), btn("⏳ در انتظار", f"a:rset:{r.id}:pending")],
        [btn("📝 ثبت توضیحات", f"a:rnote:{r.id}"), btn("✉️ پیام به کاربر", f"a:rmsg:{r.id}")],
        [btn("📎 مشاهده مدارک", f"a:rdocs:{r.id}"), btn("👤 کاربر", f"a:u:{r.user_id}")],
        [back_btn("a:reqs:all:0")], [home_btn()]])


@router.callback_query(F.data.startswith("a:r:"))
async def req_view(cb: CallbackQuery, session: AsyncSession, state: FSMContext):
    await state.clear()
    r = await session.get(Request, int(cb.data.split(":")[2]))
    if not r:
        await cb.answer("درخواست پیدا نشد", show_alert=True)
        return
    await cb.answer()
    await show_text(cb, await request_card(session, r), None, request_kb(r))


@router.callback_query(F.data.startswith("a:rset:"))
async def req_set(cb: CallbackQuery, session: AsyncSession, admin, bot):
    _, _, rid, status = cb.data.split(":")
    r = await session.get(Request, int(rid))
    if not r or status not in REQUEST_STATUS:
        await cb.answer("نامعتبر", show_alert=True)
        return
    changed = r.status != status
    r.status, r.handled_by, r.updated_at = status, admin.user_id, utcnow()
    await log_action(session, admin.user_id, "request_status", f"#{r.id} -> {status}")
    await cb.answer("✅ وضعیت تغییر کرد")
    if changed:
        user = await session.get(User, r.user_id)
        try:
            await send_key(bot, r.user_id, "request_status_update", None, user, request_id=r.id,
                           amount=fmt_amount(r.amount), year=r.year, status=REQUEST_STATUS[status],
                           note=r.admin_note or "—")
        except Exception:
            pass
    await show_text(cb, await request_card(session, r), None, request_kb(r))


@router.callback_query(F.data.startswith("a:rnote:"))
async def req_note(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    rid = int(cb.data.split(":")[2])
    await state.set_state(AdminStates.request_note)
    await state.update_data(rid=rid)
    await show_text(cb, f"📝 توضیحات درخواست #{rid} را بفرستید (برای پاک‌کردن «-» بفرستید).\n"
                        "این متن در اعلان‌های تغییر وضعیت برای کاربر هم نمایش داده می‌شود.", None,
                    ikb([[btn("❌ انصراف", f"a:r:{rid}")]]))


@router.message(AdminStates.request_note, F.text)
async def req_note_save(message: Message, state: FSMContext, session: AsyncSession, admin):
    rid = (await state.get_data())["rid"]
    await state.clear()
    r = await session.get(Request, rid)
    if r:
        r.admin_note = None if message.text.strip() == "-" else message.text.strip()[:1500]
        r.updated_at = utcnow()
        await log_action(session, admin.user_id, "request_note", f"#{rid}")
    await send_text(message.bot, message.chat.id, "✅ توضیحات ذخیره شد.", None,
                    ikb([[btn("🔙 درخواست", f"a:r:{rid}")], [home_btn()]]))


@router.callback_query(F.data.startswith("a:rmsg:"))
async def req_msg(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    rid = int(cb.data.split(":")[2])
    await state.set_state(AdminStates.request_message)
    await state.update_data(rid=rid)
    await show_text(cb, f"✉️ پیام خود را برای صاحب درخواست #{rid} بفرستید:", None, ikb([[btn("❌ انصراف", f"a:r:{rid}")]]))


@router.message(AdminStates.request_message)
async def req_msg_send(message: Message, state: FSMContext, session: AsyncSession, admin):
    rid = (await state.get_data())["rid"]
    await state.clear()
    r = await session.get(Request, rid)
    try:
        await message.bot.send_message(r.user_id, f"📩 پیام مدیریت درباره درخواست #{rid}:", parse_mode=None)
        await message.copy_to(r.user_id)
        result = "✅ پیام ارسال شد."
        await log_action(session, admin.user_id, "request_message", f"#{rid}")
    except Exception as e:
        result = f"⚠️ ارسال ناموفق: {e}"
    await send_text(message.bot, message.chat.id, result, None, ikb([[btn("🔙 درخواست", f"a:r:{rid}")], [home_btn()]]))


@router.callback_query(F.data.startswith("a:rdocs:"))
async def req_docs(cb: CallbackQuery, session: AsyncSession, bot):
    r = await session.get(Request, int(cb.data.split(":")[2]))
    docs = json.loads(r.docs or "[]") if r else []
    if not docs:
        await cb.answer("مدرکی ثبت نشده", show_alert=True)
        return
    await cb.answer("📎 در حال ارسال...")
    for d in docs:
        try:
            await send_file(bot, cb.from_user.id, d["t"], d["f"], caption=f"📎 مدرک درخواست #{r.id}")
        except Exception:
            pass
