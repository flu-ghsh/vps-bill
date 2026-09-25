from __future__ import annotations

import asyncio

from aiogram import BaseMiddleware, Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, CallbackQuery, Message

from .config import Settings
from .db import Database
from .handlers import BotHandlers
from .notifier import Notifier
from .updates import cleanup_stale_update_temps


class AdminOnlyMiddleware(BaseMiddleware):
    def __init__(self, admin_ids: frozenset[int]):
        self.admin_ids = admin_ids

    async def __call__(self, handler, event, data):
        user = getattr(event, "from_user", None)
        if not user or user.id not in self.admin_ids:
            if isinstance(event, CallbackQuery):
                await event.answer("Нет доступа", show_alert=True)
            elif isinstance(event, Message):
                await event.answer("⛔ Доступ запрещён")
            return None
        return await handler(event, data)


async def main() -> None:
    settings = Settings.from_env()
    # Self-heal stale updater temp files before Telegram callbacks can use the
    # request directory. This also repairs hosts upgraded from old releases.
    cleanup_stale_update_temps(settings.update_requests_dir)
    db = Database(settings.db_path)
    session = AiohttpSession(proxy=settings.telegram_proxy) if settings.telegram_proxy else AiohttpSession()
    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML), session=session)
    dp = Dispatcher()
    admin = AdminOnlyMiddleware(settings.admin_ids)
    dp.message.outer_middleware(admin)
    dp.callback_query.outer_middleware(admin)
    handlers = BotHandlers(db, settings)
    dp.include_router(handlers.router)
    notifier = Notifier(bot, db, settings)
    notify_task = asyncio.create_task(notifier.run())
    try:
        me = await bot.get_me()
        await bot.set_my_commands([BotCommand(command="start", description="Main menu")])
        print(f"VPS Bill started as @{me.username}", flush=True)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await notifier.stop()
        notify_task.cancel()
        await asyncio.gather(notify_task, return_exceptions=True)
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
