from aiogram.filters import BaseFilter
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards.common import btn
from bot.services.perms import can
from bot.services.settings import cfg
from database.models import AdminLog, User
from utils.helpers import norm_digits, uname


class AdminFilter(BaseFilter):
    """Passes only for admins (optionally with a specific permission)."""

    def __init__(self, perm: str | None = None):
        self.perm = perm

    async def __call__(self, event, admin=None) -> bool:
        if admin is None:
            return False
        return can(admin, self.perm) if self.perm else True


async def log_action(session: AsyncSession, admin_id: int, action: str, details: str = "") -> None:
    from database.models import AdminLog
    session.add(AdminLog(admin_id=admin_id, action=action, details=details[:1000]))
    await session.flush()


def sep() -> str:
    return cfg.get("separator")


def back_btn(data: str = "a:home", text: str = "🔙 بازگشت"):
    return btn(text, data)


def home_btn():
    return btn("🏠 پنل مدیریت", "a:home")


def cancel_row():
    return [btn("❌ انصراف", "a:home")]


def user_label(u: User) -> str:
    return f"{u.first_name or '—'} • {uname(u.username)} • {u.id}"


async def find_users(session: AsyncSession, query: str, limit: int = 8) -> list[User]:
    q = norm_digits(query.strip())
    if not q:
        return []
    if q.lstrip("@").isdigit():
        u = await session.get(User, int(q.lstrip("@")))
        return [u] if u else []
    like = f"%{q.lstrip('@')}%"
    stmt = select(User).where(or_(User.username.ilike(like), User.first_name.ilike(like),
                                  User.last_name.ilike(like))).order_by(User.joined_at.desc()).limit(limit)
    return list((await session.execute(stmt)).scalars().all())
