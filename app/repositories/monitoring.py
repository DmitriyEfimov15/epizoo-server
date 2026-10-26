from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Disease, Event, News, Quarantine, Region, RegionNeighbor, Report, WeeklyCount


async def _read_snapshot(session: AsyncSession):
    # Корпус MVP невелик: один запрос на таблицу, без N+1 по 89 регионам.
    result = {}
    for key, model in [
        ("regions", Region),
        ("diseases", Disease),
        ("events", Event),
        ("quarantines", Quarantine),
        ("neighbors", RegionNeighbor),
        ("weekly_counts", WeeklyCount),
        ("news", News),
        ("reports", Report),
    ]:
        statement = select(model)
        if model is Report:
            statement = statement.where(Report.is_current.is_(True))
        elif model is Event:
            statement = statement.join(Report).where(Report.is_current.is_(True))
        result[key] = list((await session.scalars(statement)).all())
    return result


async def fetch_snapshot(session: AsyncSession):
    if session.get_bind().dialect.name != "postgresql":
        return await _read_snapshot(session)
    # Отдельная read-only транзакция даёт единый срез до/после ETL commit.
    # Изоляция операций записи вызывающего кода не меняется.
    async with AsyncSession(bind=session.bind, expire_on_commit=False) as reader:
        await reader.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        return await _read_snapshot(reader)
