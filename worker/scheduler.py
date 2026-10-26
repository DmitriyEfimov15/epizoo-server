import asyncio
import logging
import signal

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.config import Settings
from app.core.time import MOSCOW
from app.db.session import make_engine, session_factory
from app.services.notifications import notify, send_digests
from etl.load import run_update

logger = logging.getLogger(__name__)
_cycle_lock = asyncio.Lock()


class TelegramSender:
    def __init__(self, bot, parse_mode="HTML"):
        self.bot = bot
        self.parse_mode = parse_mode

    async def send_message(self, chat_id, text):
        return await self.bot.send_message(chat_id, text, parse_mode=self.parse_mode)


async def run_cycle(settings, factory, sender=None, *, weekly=False, digest_sender=None):
    async with _cycle_lock:
        result = {"etl": await run_update(settings)}
        if sender is None:
            return result
        async with factory() as session:
            result["notifications"] = await notify(session, sender, settings.frontend_url)
            await session.commit()
        if weekly:
            async with factory() as session:
                result["digests"] = await send_digests(session, digest_sender or sender)
                await session.commit()
        return result


async def scheduled_cycle(settings, factory, sender=None, *, weekly=False, digest_sender=None):
    try:
        return await run_cycle(
            settings, factory, sender, weekly=weekly, digest_sender=digest_sender
        )
    except Exception as error:
        logger.error("Ошибка планового обновления (%s)", type(error).__name__)
        return {"error": type(error).__name__}


def create_scheduler(settings, factory, sender=None, *, digest_sender=None):
    scheduler = AsyncIOScheduler(timezone=MOSCOW)
    kwargs = {
        "settings": settings,
        "factory": factory,
        "sender": sender,
        "digest_sender": digest_sender,
    }
    options = {
        "trigger": "cron",
        "timezone": MOSCOW,
        "minute": 0,
        "max_instances": 1,
        "coalesce": True,
        "misfire_grace_time": 3600,
    }
    scheduler.add_job(
        scheduled_cycle, id="morning", hour=9, day_of_week="tue-sun", kwargs=kwargs, **options
    )
    scheduler.add_job(scheduled_cycle, id="afternoon", hour=15, kwargs=kwargs, **options)
    scheduler.add_job(
        scheduled_cycle,
        id="weekly",
        hour=9,
        day_of_week="mon",
        kwargs={**kwargs, "weekly": True},
        **options,
    )
    return scheduler


async def main():
    settings = Settings()
    engine = make_engine(settings.database_url)
    bot = Bot(settings.telegram_bot_token) if settings.telegram_bot_token else None
    sender = TelegramSender(bot) if bot is not None else None
    digest_sender = TelegramSender(bot, parse_mode=None) if bot is not None else None
    scheduler = create_scheduler(
        settings, session_factory(engine), sender, digest_sender=digest_sender
    )
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stop.set)
    try:
        scheduler.start()
        await stop.wait()
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=True)
        if bot is not None:
            await bot.session.close()
        await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
