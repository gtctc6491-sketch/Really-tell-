from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from admin.common import AdminFilter, back_btn, cancel_row, find_users, home_btn, log_action, sep
from bot.keyboards.common import btn, ikb, pager_row
from bot.services.broadcast import run_gift_to_all, spawn
from bot.services.messaging import send_key_photo, send_photo_caption, send_text, show_photo, show_text
from bot.states import AdminStates
from database.models import Gift, User, UserGift
from utils.helpers import PAGE_SIZE, clamp_page, fmt_dt, norm_digits, page_count, uname

router = Router()
router.message.filter(AdminFilter("gifts"))
router.callback_query.filter(AdminFilter("gifts"))

FIELDS = {"name": "نام", "desc": "توضیحات", "stock": "موجودی", "limit": "محدودیت دریافت برای هر کاربر", "photo": "تصویر"}


@router.callback_query(F.data == "a:gifts")
async def gifts_menu(cb: CallbackQuery, session: AsyncSession, state: FSMContext):
    await state.clear()
    await cb.answer()
    gifts = (await session.execute(select(Gift).where(Gift.is_deleted.is_(False)).order_by(Gift.id.desc()).limit(30))).scalars().all()
    rows = [[btn(f"{'🟢' if g.is_active else '⚪️'} {g.name} • 📦{g.stock}", f"a:g:{g.id}")] for g in gifts]
    rows += [[btn("➕ گیفت جدید", "a:gnew"), btn("📜 سوابق دریافت", "a:ghist:0:0")],
             [btn("🌟 ارسال Telegram Gift واقعی", "a:rgift")], [back_btn()]]
    await show_text(cb, f"🎁 مدیریت گیفت داخلی ({len(gifts)})\n{sep()}", None, ikb(rows))


# ---------- create ----------
@router.callback_query(F.data == "a:gnew")
async def gnew(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.clear()
    await state.set_state(AdminStates.gift_name)
    await show_text(cb, "➕ گیفت جدید\n\n1️⃣ نام گیفت را بفرستید:", None, ikb([cancel_row()]))


@router.message(AdminStates.gift_name, F.text)
async def gift_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip()[:200])
    await state.set_state(AdminStates.gift_photo)
    await send_text(message.bot, message.chat.id, "2️⃣ تصویر گیفت را بفرستید (یا «-» برای بدون تصویر):", None, ikb([cancel_row()]))


@router.message(AdminStates.gift_photo)
async def gift_photo(message: Message, state: FSMContext):
    if message.photo:
        await state.update_data(photo=message.photo[-1].file_id)
    elif message.text and message.text.strip() == "-":
        await state.update_data(photo=None)
    else:
        await send_text(message.bot, message.chat.id, "⚠️ یک تصویر بفرستید یا «-» را ارسال کنید.", None, ikb([cancel_row()]))
        return
    await state.set_state(AdminStates.gift_desc)
    await send_text(message.bot, message.chat.id, "3️⃣ توضیحات گیفت را بفرستید:", None, ikb([cancel_row()]))


@router.message(AdminStates.gift_desc, F.text)
async def gift_desc(message: Message, state: FSMContext):
    await state.update_data(desc=message.text.strip()[:1500])
    await state.set_state(AdminStates.gift_stock)
    await send_text(message.bot, message.chat.id, "4️⃣ تعداد موجودی را بفرستید (عدد):", None, ikb([cancel_row()]))


@router.message(AdminStates.gift_stock, F.text)
async def gift_stock(message: Message, state: FSMContext):
    n = norm_digits(message.text.strip())
    if not n.isdigit():
        await send_text(message.bot, message.chat.id, "⚠️ فقط عدد بفرستید.", None, ikb([cancel_row()]))
        return
    await state.update_data(stock=int(n))
    await state.set_state(AdminStates.gift_limit)
    await send_text(message.bot, message.chat.id, "5️⃣ حداکثر دفعات دریافت برای هر کاربر (0 = نامحدود):", None, ikb([cancel_row()]))


@router.message(AdminStates.gift_limit, F.text)
async def gift_limit(message: Message, state: FSMContext, session: AsyncSession, admin):
    n = norm_digits(message.text.strip())
    if not n.isdigit():
        await send_text(message.bot, message.chat.id, "⚠️ فقط عدد بفرستید.", None, ikb([cancel_row()]))
        return
    d = await state.get_data()
    await state.clear()
    g = Gift(name=d["name"], photo_id=d.get("photo"), description=d.get("desc", ""), stock=d["stock"],
             per_user_limit=int(n), is_active=True)
    session.add(g)
    await session.flush()
    await log_action(session, admin.user_id, "gift_create", f"#{g.id} {g.name}")
    await send_text(message.bot, message.chat.id, f"✅ گیفت «{g.name}» ساخته شد.", None,
                    ikb([[btn("🎁 مشاهده", f"a:g:{g.id}")], [btn("🔙 لیست گیفت‌ها", "a:gifts")]]))


# ---------- view / edit ----------
async def gift_card(session: AsyncSession, g: Gift) -> str:
    claimed = await session.scalar(select(func.count(UserGift.id)).where(UserGift.gift_id == g.id)) or 0
    return (f"🎁 {g.name} (#{g.id})\n{sep()}\n📝 {g.description or '—'}\n📦 موجودی: {g.stock}\n"
            f"🔒 محدودیت هر کاربر: {g.per_user_limit or 'نامحدود'}\n🖼 تصویر: {'دارد' if g.photo_id else 'ندارد'}\n"
            f"📊 وضعیت: {'فعال' if g.is_active else 'غیرفعال'}\n🎯 تعداد دریافت: {claimed}")


def gift_kb(g: Gift):
    return ikb([
        [btn("⚪️ غیرفعال‌سازی" if g.is_active else "🟢 فعال‌سازی", f"a:gtog:{g.id}")],
        [btn("✏️ نام", f"a:gedit:{g.id}:name"), btn("✏️ توضیحات", f"a:gedit:{g.id}:desc")],
        [btn("✏️ موجودی", f"a:gedit:{g.id}:stock"), btn("✏️ محدودیت", f"a:gedit:{g.id}:limit")],
        [btn("🖼 تصویر", f"a:gedit:{g.id}:photo")],
        [btn("📤 ارسال به کاربر", f"a:gsend:{g.id}"), btn("📣 ارسال گروهی", f"a:gall:{g.id}")],
        [btn("📜 سوابق", f"a:ghist:{g.id}:0"), btn("🗑 حذف", f"a:gdel:{g.id}")],
        [back_btn("a:gifts")]])


async def render_gift(event, session: AsyncSession, gid: int):
    g = await session.get(Gift, gid)
    if not g or g.is_deleted:
        await show_text(event, "❌ گیفت پیدا نشد.", None, ikb([[back_btn("a:gifts")]]))
        return
    text = await gift_card(session, g)
    if g.photo_id and isinstance(event, CallbackQuery):
        await show_photo(event, g.photo_id, text, gift_kb(g))
    elif g.photo_id:
        await send_photo_caption(event.bot, event.chat.id, g.photo_id, text, None, gift_kb(g))
    else:
        await show_text(event, text, None, gift_kb(g))


@router.callback_query(F.data.startswith("a:g:"))
async def gift_view(cb: CallbackQuery, session: AsyncSession, state: FSMContext):
    await state.clear()
    await cb.answer()
    await render_gift(cb, session, int(cb.data.split(":")[2]))


@router.callback_query(F.data.startswith("a:gtog:"))
async def gift_toggle(cb: CallbackQuery, session: AsyncSession, admin):
    g = await session.get(Gift, int(cb.data.split(":")[2]))
    if g:
        g.is_active = not g.is_active
        await log_action(session, admin.user_id, "gift_toggle", f"#{g.id} {g.is_active}")
    await cb.answer("انجام شد")
    await render_gift(cb, session, g.id)


@router.callback_query(F.data.startswith("a:gedit:"))
async def gift_edit_start(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    _, _, gid, field = cb.data.split(":")
    await state.set_state(AdminStates.gift_edit)
    await state.update_data(gid=int(gid), field=field)
    hint = "تصویر جدید را بفرستید (یا «-» برای حذف تصویر)" if field == "photo" else f"مقدار جدید «{FIELDS[field]}» را بفرستید"
    await show_text(cb, f"✏️ {hint}:", None, ikb([[btn("❌ انصراف", f"a:g:{gid}")]]))


@router.message(AdminStates.gift_edit)
async def gift_edit_save(message: Message, state: FSMContext, session: AsyncSession, admin):
    d = await state.get_data()
    g = await session.get(Gift, d["gid"])
    field = d["field"]
    text = (message.text or "").strip()
    if not g:
        await state.clear()
        return
    if field == "photo":
        if message.photo:
            g.photo_id = message.photo[-1].file_id
        elif text == "-":
            g.photo_id = None
        else:
            await send_text(message.bot, message.chat.id, "⚠️ تصویر یا «-» بفرستید.", None, None)
            return
    elif field in ("stock", "limit"):
        n = norm_digits(text)
        if not n.isdigit():
            await send_text(message.bot, message.chat.id, "⚠️ فقط عدد بفرستید.", None, None)
            return
        if field == "stock":
            g.stock = int(n)
        else:
            g.per_user_limit = int(n)
    elif text:
        if field == "name":
            g.name = text[:200]
        else:
            g.description = text[:1500]
    else:
        await send_text(message.bot, message.chat.id, "⚠️ متن بفرستید.", None, None)
        return
    await state.clear()
    await log_action(session, admin.user_id, "gift_edit", f"#{g.id} {field}")
    await session.flush()
    await render_gift(message, session, g.id)


@router.callback_query(F.data.startswith("a:gdel:"))
async def gift_del(cb: CallbackQuery):
    await cb.answer()
    gid = cb.data.split(":")[2]
    await show_text(cb, "🗑 این گیفت حذف شود؟ (سوابق دریافت حفظ می‌شود)", None,
                    ikb([[btn("✅ بله، حذف", f"a:gdelok:{gid}"), btn("❌ خیر", f"a:g:{gid}")]]))


@router.callback_query(F.data.startswith("a:gdelok:"))
async def gift_del_ok(cb: CallbackQuery, session: AsyncSession, admin):
    g = await session.get(Gift, int(cb.data.split(":")[2]))
    if g:
        g.is_deleted, g.is_active = True, False
        await log_action(session, admin.user_id, "gift_delete", f"#{g.id}")
    await cb.answer("🗑 حذف شد")
    await show_text(cb, "🗑 گیفت حذف شد.", None, ikb([[btn("🔙 لیست گیفت‌ها", "a:gifts")]]))


# ---------- send to user / all ----------
@router.callback_query(F.data.startswith("a:gsend:"))
async def gift_send_start(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    gid = int(cb.data.split(":")[2])
    await state.set_state(AdminStates.gift_send_user)
    await state.update_data(gid=gid)
    await show_text(cb, "📤 آیدی عددی یا یوزرنیم کاربر گیرنده را بفرستید:", None, ikb([[btn("❌ انصراف", f"a:g:{gid}")]]))


@router.message(AdminStates.gift_send_user, F.text)
async def gift_send_user(message: Message, state: FSMContext, session: AsyncSession, admin, bot):
    gid = (await state.get_data())["gid"]
    users = await find_users(session, message.text, limit=2)
    if len(users) != 1:
        await send_text(message.bot, message.chat.id,
                        "❌ دقیقاً یک کاربر پیدا نشد. آیدی عددی دقیق بفرستید.", None, ikb([[btn("❌ انصراف", f"a:g:{gid}")]]))
        return
    u, g = users[0], await session.get(Gift, gid)
    await state.clear()
    session.add(UserGift(user_id=u.id, gift_id=gid, source="admin"))
    await log_action(session, admin.user_id, "gift_send", f"#{gid} -> {u.id}")
    try:
        await send_key_photo(bot, u.id, g.photo_id, "gift_received_admin", None, u, gift_name=g.name, gift_desc=g.description)
        result = f"✅ گیفت برای {u.first_name} ({u.id}) ارسال شد."
    except Exception as e:
        result = f"⚠️ ثبت شد ولی پیام تحویل نشد: {e}"
    await send_text(message.bot, message.chat.id, result, None, ikb([[btn("🔙 گیفت", f"a:g:{gid}")]]))


@router.callback_query(F.data.startswith("a:gall:"))
async def gift_all_confirm(cb: CallbackQuery, session: AsyncSession):
    await cb.answer()
    gid = cb.data.split(":")[2]
    n = await session.scalar(select(func.count(User.id)).where(User.is_blocked.is_(False))) or 0
    await show_text(cb, f"📣 گیفت برای همهٔ {n} کاربر فعال ارسال شود؟\n(ارسال گروهی از موجودی کم نمی‌کند)", None,
                    ikb([[btn("✅ شروع ارسال", f"a:gallok:{gid}"), btn("❌ انصراف", f"a:g:{gid}")]]))


@router.callback_query(F.data.startswith("a:gallok:"))
async def gift_all_go(cb: CallbackQuery, session: AsyncSession, admin, bot):
    gid = int(cb.data.split(":")[2])
    await log_action(session, admin.user_id, "gift_send_all", f"#{gid}")
    await session.commit()
    spawn(run_gift_to_all(bot, gid, cb.from_user.id))
    await cb.answer("🚀 ارسال شروع شد")
    await show_text(cb, "🚀 ارسال گروهی در پس‌زمینه شروع شد. پس از پایان گزارش می‌گیرید.", None,
                    ikb([[btn("🔙 گیفت", f"a:g:{gid}")]]))


# ---------- history ----------
@router.callback_query(F.data.startswith("a:ghist:"))
async def gift_hist(cb: CallbackQuery, session: AsyncSession):
    await cb.answer()
    _, _, gid, page = cb.data.split(":")
    gid = int(gid)
    cond = [UserGift.gift_id == gid] if gid else []
    total = await session.scalar(select(func.count(UserGift.id)).where(*cond)) or 0
    pages = page_count(total)
    page = clamp_page(int(page), pages)
    rows = (await session.execute(
        select(UserGift, User, Gift.name).join(User, User.id == UserGift.user_id).join(Gift, Gift.id == UserGift.gift_id)
        .where(*cond).order_by(UserGift.id.desc()).offset(page * PAGE_SIZE).limit(PAGE_SIZE))).all()
    lines = [f"📜 سوابق دریافت گیفت ({total})\n{sep()}"]
    lines += [f"🎁 {name} → {u.first_name} {uname(u.username)} ({u.id})\n   {ug.source} • {fmt_dt(ug.created_at)}" for ug, u, name in rows] or ["—"]
    kb = [pager_row(lambda p: f"a:ghist:{gid}:{p}", page, pages), [back_btn(f"a:g:{gid}" if gid else "a:gifts")]]
    await show_text(cb, "\n".join(lines), None, ikb(kb))


# ---------- real Telegram gifts (separate feature) ----------
@router.callback_query(F.data == "a:rgift")
async def real_gifts(cb: CallbackQuery, state: FSMContext, bot):
    await cb.answer()
    try:
        available = await bot.get_available_gifts()
        gifts = sorted(available.gifts, key=lambda g: g.star_count)[:30]
    except Exception as e:
        await show_text(cb, f"⚠️ دریافت لیست Telegram Gift ممکن نشد:\n{e}", None, ikb([[back_btn("a:gifts")]]))
        return
    if not gifts:
        await show_text(cb, "📭 گیفتی در دسترس نیست.", None, ikb([[back_btn("a:gifts")]]))
        return
    await state.clear()
    await state.update_data(rg=[g.id for g in gifts])
    rows, row = [], []
    for i, g in enumerate(gifts):
        row.append(btn(f"{g.sticker.emoji or '🎁'} {g.star_count}⭐", f"a:rgpick:{i}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([back_btn("a:gifts")])
    await show_text(cb, "🌟 Telegram Gift واقعی\n"
                        "یک گیفت انتخاب کنید. هزینه از موجودی Stars ربات کسر می‌شود.", None, ikb(rows))


@router.callback_query(F.data.startswith("a:rgpick:"))
async def real_gift_pick(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    idx = int(cb.data.split(":")[2])
    ids = data.get("rg", [])
    if idx >= len(ids):
        await cb.answer("منقضی شد، دوباره باز کنید", show_alert=True)
        return
    await cb.answer()
    await state.update_data(rg_id=ids[idx])
    await state.set_state(AdminStates.real_gift_user)
    await show_text(cb, "👤 آیدی عددی یا یوزرنیم کاربر گیرنده را بفرستید:", None, ikb([[btn("❌ انصراف", "a:gifts")]]))


@router.message(AdminStates.real_gift_user, F.text)
async def real_gift_send(message: Message, state: FSMContext, session: AsyncSession, admin, bot):
    users = await find_users(session, message.text, limit=2)
    if len(users) != 1:
        await send_text(message.bot, message.chat.id, "❌ دقیقاً یک کاربر پیدا نشد. آیدی عددی دقیق بفرستید.", None,
                        ikb([[btn("❌ انصراف", "a:gifts")]]))
        return
    gift_id = (await state.get_data()).get("rg_id")
    await state.clear()
    try:
        await bot.send_gift(gift_id=gift_id, user_id=users[0].id)
        result = f"✅ Telegram Gift برای {users[0].first_name} ({users[0].id}) ارسال شد."
        await log_action(session, admin.user_id, "real_gift", f"{gift_id} -> {users[0].id}")
    except Exception as e:
        result = f"⚠️ ارسال ناموفق (موجودی Stars یا دسترسی را بررسی کنید):\n{e}"
    await send_text(message.bot, message.chat.id, result, None, ikb([[btn("🔙 گیفت‌ها", "a:gifts")]]))
