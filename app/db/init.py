import asyncio

from alembic import command
from alembic.config import Config

from app.core.config import ROOT, Settings
from app.db.seed import seed_reference_data
from app.db.session import make_engine, session_factory


async def seed():
    settings = Settings()
    engine = make_engine(settings.database_url)
    try:
        async with session_factory(engine)() as session:
            await seed_reference_data(session, settings.data_dir)
            await session.commit()
    finally:
        await engine.dispose()


def main():
    command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
    asyncio.run(seed())
    print("Миграции применены, справочники загружены")


if __name__ == "__main__":
    main()
