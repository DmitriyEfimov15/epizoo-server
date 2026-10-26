import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand

from app.core.config import Settings
from app.db.session import make_engine, session_factory
from bot.handlers import create_router

COMMANDS = [
    BotCommand(command="menu", description="Показать меню"),
    BotCommand(command="status", description="Обстановка в регионе"),
    BotCommand(command="help", description="Как пользоваться ботом"),
]


def create_dispatcher(factory, settings):
    dispatcher = Dispatcher(session_factory=factory, settings=settings)
    dispatcher.include_router(create_router())
    return dispatcher


async def main():
    settings = Settings()
    if not settings.telegram_bot_token:
        logging.getLogger(__name__).info("Telegram-бот не настроен")
        return
    engine = make_engine(settings.database_url)
    bot = Bot(settings.telegram_bot_token)
    try:
        await bot.set_my_commands(COMMANDS)
        await create_dispatcher(session_factory(engine), settings).start_polling(bot)
    finally:
        await bot.session.close()
        await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
