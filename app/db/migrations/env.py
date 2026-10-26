import asyncio

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import Settings
from app.db.base import Base
from app.models import entities  # noqa: F401

config = context.config
config.set_main_option("sqlalchemy.url", Settings().database_url.replace("%", "%%"))
metadata = Base.metadata


def offline():
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run(connection):
    context.configure(connection=connection, target_metadata=metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def online():
    engine = async_engine_from_config(
        config.get_section(config.config_ini_section), prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    async with engine.connect() as conn:
        await conn.run_sync(run)
    await engine.dispose()


if context.is_offline_mode():
    offline()
else:
    asyncio.run(online())
