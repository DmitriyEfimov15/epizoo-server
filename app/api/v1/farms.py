from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import not_found
from app.db.session import get_session
from app.models import Farm, Subscription
from app.schemas.api import (
    DashboardOut,
    DigestOut,
    FarmIn,
    FarmOut,
    SubscriptionIn,
    SubscriptionOut,
    TelegramLink,
)
from app.services.digest import build_digest
from app.services.monitoring import Monitor
from app.services.offers import select_offers

router = APIRouter(prefix="/farms")
Session = Annotated[AsyncSession, Depends(get_session)]


async def get_farm(session, token):
    farm = await session.get(Farm, str(token))
    if farm is None:
        raise not_found("Хозяйство не найдено")
    return farm


async def get_subscription(session, token):
    return await session.scalar(select(Subscription).where(Subscription.farm_token == str(token)))


@router.post("", response_model=FarmOut, status_code=201)
async def create_farm(payload: FarmIn, session: Session):
    (await Monitor.load(session)).region(payload.region_code)
    farm = Farm(**payload.model_dump())
    farm.species = list(dict.fromkeys(farm.species))
    session.add(farm)
    await session.flush()
    return farm


@router.get("/{token}", response_model=FarmOut)
async def farm(token: UUID, session: Session):
    return await get_farm(session, token)


@router.put("/{token}", response_model=FarmOut)
async def update_farm(token: UUID, payload: FarmIn, session: Session):
    farm = await get_farm(session, token)
    (await Monitor.load(session)).region(payload.region_code)
    for key, value in payload.model_dump().items():
        setattr(farm, key, value)
    farm.species = list(dict.fromkeys(farm.species))
    await session.flush()
    return farm


@router.get("/{token}/dashboard", response_model=DashboardOut)
async def dashboard(token: UUID, request: Request, session: Session):
    farm = await get_farm(session, token)
    monitor = await Monitor.load(session)
    region = monitor.region_out(farm.region_code, farm.species)
    events = monitor.selected_events(farm.region_code, farm.species)
    offers = {
        item.id: item
        for animal in farm.species
        for item in select_offers(
            monitor, farm.region_code, animal, request.app.state.settings.data_dir
        )
    }
    return DashboardOut(
        farm=farm,
        region=region,
        neighbors=region.neighbors,
        recommendations=monitor.recommendations(events),
        offers=list(offers.values()),
        subscription=await get_subscription(session, token),
    )


@router.get("/{token}/digest", response_model=DigestOut)
async def digest(token: UUID, session: Session):
    return build_digest(await Monitor.load(session), await get_farm(session, token))


@router.post("/{token}/telegram-link", response_model=TelegramLink)
async def telegram_link(token: UUID, request: Request, session: Session):
    await get_farm(session, token)
    username = request.app.state.settings.telegram_bot_username.lstrip("@")
    if not username:
        raise HTTPException(
            503, detail={"code": "telegram_unavailable", "message": "Telegram-бот не настроен"}
        )
    if await get_subscription(session, token) is None:
        session.add(Subscription(farm_token=str(token)))
        await session.flush()
    return TelegramLink(url=f"https://t.me/{username}?start={token}")


@router.put("/{token}/subscription", response_model=SubscriptionOut)
async def subscription(token: UUID, payload: SubscriptionIn, session: Session):
    await get_farm(session, token)
    row = await get_subscription(session, token)
    if row is None:
        row = Subscription(farm_token=str(token))
        session.add(row)
    for key, value in payload.model_dump().items():
        setattr(row, key, value)
    await session.flush()
    return row


@router.delete("/{token}/subscription", status_code=204)
async def unsubscribe(token: UUID, session: Session):
    await get_farm(session, token)
    row = await get_subscription(session, token)
    if row is not None:
        await session.delete(row)
    return Response(status_code=204)
