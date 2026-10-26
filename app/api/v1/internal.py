from aiogram import Bot
from fastapi import APIRouter, Depends, Request

from app.core.security import require_api_key
from app.schemas.api import ETLResult
from worker.scheduler import TelegramSender, run_cycle

router = APIRouter(prefix="/internal", dependencies=[Depends(require_api_key)])


@router.post("/etl/run", response_model=ETLResult)
async def run_etl(request: Request):
    settings = request.app.state.settings
    bot = Bot(settings.telegram_bot_token) if settings.telegram_bot_token else None
    try:
        result = await run_cycle(
            settings, request.app.state.session_factory, TelegramSender(bot) if bot else None
        )
        return result["etl"]
    finally:
        if bot:
            await bot.session.close()
