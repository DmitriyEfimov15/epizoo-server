from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


def make_engine(url: str):
    engine = create_async_engine(url, pool_pre_ping=True)
    if url.startswith("sqlite"):

        @event.listens_for(engine.sync_engine, "connect")
        def enable_foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

    return engine


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.session_factory() as session:
        yield session
        await session.commit()


def session_factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False)
