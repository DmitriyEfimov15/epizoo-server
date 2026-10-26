from datetime import date, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models import Disease, Event, Quarantine, Region, Report
from app.services.quarantine import rebuild_quarantines
from app.services.scoring import level_from_score


@pytest.mark.parametrize(
    ("score", "base", "expected"), [(2.6, 1, 3), (0, 3, 1), (9, 1, 5), (None, 4, 4)]
)
def test_score(score, base, expected):
    assert level_from_score(score, base) == expected


async def test_quarantine_lift_matches_locality_and_ages():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        today = date(2026, 10, 14)
        session.add_all(
            [
                Region(code="50", name="Московская область", aliases=[], federal_district="ЦФО"),
                Disease(
                    id=1,
                    slug="rabies",
                    name="Бешенство",
                    aliases=[],
                    species=["cattle"],
                    is_zoonosis=True,
                    base_level=3,
                    description="",
                    recommendations=[],
                ),
                Report(
                    id=1,
                    date=today,
                    type="daily",
                    url="https://example.org/1.pdf",
                    sha256="a" * 64,
                    parse_status="ok",
                ),
            ]
        )
        await session.flush()
        for eid, locality, kind, age in [
            (1, "д. Ивановка", "quarantine_set", 100),
            (2, "д. Петровка", "quarantine_set", 10),
            (3, "Ивановка", "quarantine_lifted", 5),
            (4, "Сидоровка", "quarantine_set", 90),
        ]:
            session.add(
                Event(
                    id=eid,
                    report_id=1,
                    date=today - timedelta(days=age),
                    disease_id=1,
                    region_code="50",
                    locality=locality,
                    species=["cattle"],
                    kind=kind,
                    text=locality,
                    scores=[],
                    level=3,
                    source_urls=[],
                    fingerprint=str(eid),
                )
            )
        await session.flush()
        await rebuild_quarantines(session, today)
        rows = list((await session.scalars(select(Quarantine))).all())
        by_set = {row.set_event_id: row for row in rows}
        assert by_set[1].status == "lifted"
        assert by_set[1].lifted_event_id == 3
        assert by_set[2].status == "active"
        assert by_set[4].status == "unconfirmed"
        await rebuild_quarantines(session, today)
        assert len((await session.scalars(select(Quarantine))).all()) == 3
    await engine.dispose()


async def test_same_named_villages_in_different_districts_are_independent():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        day = date(2026, 10, 14)
        session.add_all(
            [
                Region(code="50", name="Московская область", aliases=[], federal_district="ЦФО"),
                Disease(
                    id=1,
                    slug="rabies",
                    name="Бешенство",
                    aliases=[],
                    species=["cattle"],
                    is_zoonosis=True,
                    base_level=3,
                    description="",
                    recommendations=[],
                ),
                Report(
                    id=1,
                    date=day,
                    type="daily",
                    url="https://example.org/q.pdf",
                    sha256="c" * 64,
                    parse_status="ok",
                ),
            ]
        )
        await session.flush()
        for eid, district, kind, age in [
            (1, "Первый район", "quarantine_set", 10),
            (2, "Второй район", "quarantine_set", 10),
            (3, "Первый район", "quarantine_lifted", 1),
        ]:
            session.add(
                Event(
                    id=eid,
                    report_id=1,
                    date=day - timedelta(days=age),
                    disease_id=1,
                    region_code="50",
                    district=district,
                    locality="Ивановка",
                    species=["cattle"],
                    kind=kind,
                    text="Текст",
                    scores=[],
                    level=3,
                    source_urls=[],
                    fingerprint=f"q-{eid}",
                )
            )
        await session.flush()
        await rebuild_quarantines(session, day)
        rows = (await session.scalars(select(Quarantine))).all()
        assert len(rows) == 2
        assert {q.set_event_id: q.status for q in rows} == {1: "lifted", 2: "active"}
    await engine.dispose()


@pytest.mark.parametrize(
    ("set_district", "lift_district"),
    [
        ("Лысковский м.о.", "Лысковский муниципальный округ"),
        ("Грибановский муниципальный район", "Грибановский район"),
        ("Людиновского муниципального округа", "Людиновский муниципальный округ"),
    ],
)
async def test_quarantine_lift_accepts_equivalent_district_names(set_district, lift_district):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        day = date(2026, 10, 14)
        session.add_all(
            [
                Region(code="52", name="Нижегородская область", aliases=[], federal_district="ПФО"),
                Disease(
                    id=1,
                    slug="rabies",
                    name="Бешенство",
                    aliases=[],
                    species=["cattle"],
                    is_zoonosis=True,
                    base_level=3,
                    description="",
                    recommendations=[],
                ),
                Report(
                    id=1,
                    date=day,
                    type="daily",
                    url="https://example.org/q1.pdf",
                    sha256="e" * 64,
                    parse_status="ok",
                ),
            ]
        )
        await session.flush()
        for eid, district, kind, age in [
            (1, set_district, "quarantine_set", 100),
            (2, lift_district, "quarantine_lifted", 1),
        ]:
            session.add(
                Event(
                    id=eid,
                    report_id=1,
                    date=day - timedelta(days=age),
                    disease_id=1,
                    region_code="52",
                    district=district,
                    locality="Красный Оселок",
                    species=["cattle"],
                    kind=kind,
                    text="Текст",
                    scores=[],
                    level=3,
                    source_urls=[],
                    fingerprint=f"d-{eid}",
                )
            )
        await session.flush()
        await rebuild_quarantines(session, day)
        row = (await session.scalars(select(Quarantine))).one()
        assert row.status == "lifted"
    await engine.dispose()
