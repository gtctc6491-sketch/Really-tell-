import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, ErrorEvent

import admin as admin_pkg
from bot.handlers import buy, fallback, gifts, misc, start, tickets
from bot.middlewares.access import AccessMiddleware
from bot.middlewares.db import DbSessionMiddleware
from bot.services.backup import backup_loop
from bot.services.settings import cfg
from bot.services.texts import T
from config.settings import BOT_TOKEN, LOG_LEVEL, SUPER_ADMIN_IDS
from database.seed import seed_defaults
from database.session import async_session, init_db

log = logging.getLogger("lbank")


async def main() -> None:
    logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not BOT_TOKEN:
        raise SystemExit("BOT_TOKEN تنظیم نشده است.")
    if not SUPER_ADMIN_IDS:
        log.warning("ADMIN_IDS خالی است؛ هیچ مدیر کلی تعریف نشده!")

    await init_db()
    await seed_defaults()
    async with async_session() as s:
        await cfg.load(s)
        await T.load(s)

    bot = Bot(BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())

    dp.update.outer_middleware(DbSessionMiddleware())
    access = AccessMiddleware()
    dp.message.outer_middleware(access)
    dp.callback_query.outer_middleware(access)

    # admin routers first, then user routers; generic fallback last
    for r in admin_pkg.routers:
        dp.include_router(r)
    for r in (start.router, buy.router, gifts.router, tickets.router, misc.router, fallback.router):
        dp.include_router(r)

    @dp.error()
    async def on_error(event: ErrorEvent):
        log.exception("Unhandled error", exc_info=event.exception)
        upd = event.update
        try:
            if upd.callback_query:
                await upd.callback_query.answer(T.plain("error_generic"), show_alert=True)
            elif upd.message:
                await upd.message.answer(T.plain("error_generic"), parse_mode=None)
        except Exception:
            pass
        return True

    await bot.set_my_commands([BotCommand(command="start", description="شروع / منوی اصلی")])
    await bot.delete_webhook(drop_pending_updates=True)
    backup_task = asyncio.create_task(backup_loop(bot))
    me = await bot.get_me()
    log.info("Bot @%s started", me.username)
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        backup_task.cancel()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
