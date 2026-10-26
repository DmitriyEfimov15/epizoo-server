from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models import Disease, Event, Region, Report, WeeklyCount
from app.services.monitoring import Monitor
from app.services.quarantine import rebuild_quarantines
from etl.fetch import ReportRef
from etl.load import ingest_daily, load_report


async def test_ingest_daily_is_idempotent_and_reports_unknown_names():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        session.add_all(
            [
                Region(code="50", name="Московская область", aliases=[], federal_district="ЦФО"),
                Disease(
                    id=1,
                    name="Бешенство животных",
                    slug="rabies",
                    aliases=["Бешенство"],
                    species=["cattle"],
                    is_zoonosis=True,
                    base_level=5,
                    description="",
                    recommendations=[],
                ),
            ]
        )
        await session.flush()
        report = Report(
            date=date(2026, 10, 12),
            type="daily",
            url="https://example.org/a.pdf",
            sha256="a" * 64,
            parse_status="ok",
        )
        session.add(report)
        await session.flush()
        good = SimpleNamespace(
            disease="Бешенство",
            region="Московская область",
            date=report.date,
            district=None,
            locality="Ивановка",
            species=[],
            kind="quarantine_set",
            text="Событие",
            scores=[1, 4, 2, 0, 5, 4],
            total=2.6,
            source_urls=["https://example.org/act"],
        )
        bad = SimpleNamespace(**{**vars(good), "region": "Неизвестный регион"})
        result = await ingest_daily(session, report, [good, bad], [])
        assert result["events"] == 1
        assert report.parse_status == "partial"
        assert "Неизвестный регион" in report.issues[0]
        second = await ingest_daily(session, report, [good], [])
        assert second["events"] == 0
        event = (await session.scalars(select(Event))).one()
        assert event.level == 3
        assert event.species == ["cattle"]
    await engine.dispose()


async def test_loader_preserves_same_named_places_in_two_districts():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        session.add_all(
            [
                Region(code="50", name="Московская область", aliases=[], federal_district="ЦФО"),
                Disease(
                    id=1,
                    name="Бешенство",
                    slug="rabies",
                    aliases=[],
                    species=["cattle"],
                    is_zoonosis=True,
                    base_level=3,
                    description="",
                    recommendations=[],
                ),
            ]
        )
        await session.flush()
        report = Report(
            date=date(2026, 10, 12),
            type="daily",
            url="https://example.org/two.pdf",
            sha256="d" * 64,
            parse_status="ok",
        )
        session.add(report)
        await session.flush()
        events = [
            SimpleNamespace(
                disease="Бешенство",
                region="Московская область",
                date=report.date,
                district=district,
                locality="Ивановка",
                species=["cattle"],
                kind="quarantine_set",
                text="Акт",
                scores=[],
                total=3.0,
                source_urls=["https://example.org/act"],
            )
            for district in ("Первый район", "Второй район")
        ]
        result = await ingest_daily(session, report, events, [])
        assert result["events"] == 2
        assert {e.district for e in (await session.scalars(select(Event))).all()} == {
            "Первый район",
            "Второй район",
        }
    await engine.dispose()


@pytest.fixture
async def revision_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            session.add_all(
                [
                    Region(
                        code="50", name="Московская область", aliases=[], federal_district="ЦФО"
                    ),
                    Region(
                        code="52", name="Нижегородская область", aliases=[], federal_district="ПФО"
                    ),
                    Disease(
                        id=1,
                        name="Бешенство",
                        slug="rabies",
                        aliases=[],
                        species=["cattle"],
                        is_zoonosis=True,
                        base_level=3,
                        description="",
                        recommendations=[],
                    ),
                ]
            )
            await session.flush()
            yield session
    finally:
        await engine.dispose()


@pytest.mark.parametrize("new_locality", ["Ивановка", "Петровка"])
async def test_daily_revision_replaces_current_facts(
    revision_session, tmp_path, monkeypatch, new_locality
):
    import etl.parse_daily

    session = revision_session
    day = date(2026, 10, 12)
    ref = ReportRef(day, "daily", "https://example.org/report.pdf", "Сводка")
    event = SimpleNamespace(
        disease="Бешенство",
        region="Московская область",
        date=day,
        district="Первый район",
        locality="Ивановка",
        species=["cattle"],
        kind="quarantine_set",
        text="Старая оценка",
        scores=[],
        total=2.0,
        source_urls=["https://example.org/act"],
    )
    parsed = SimpleNamespace(events=[event], issues=[])
    monkeypatch.setattr(etl.parse_daily, "parse_daily", lambda *_: parsed)
    path = tmp_path / "report.pdf"
    path.write_bytes(b"%PDF-original")
    await load_report(session, ref, path)
    event.locality = new_locality
    event.text = "Исправленная оценка"
    event.total = 4.2
    path.write_bytes(b"%PDF-corrected")
    await load_report(session, ref, path)
    await rebuild_quarantines(session, day)
    monitor = await Monitor.load(session)
    assert len(monitor.events) == 1
    assert monitor.events[0].locality == new_locality
    assert monitor.events[0].level == 5
    assert monitor.events[0].text == "Исправленная оценка"
    assert len(monitor.quarantines) == 1
    reports = (await session.scalars(select(Report))).all()
    assert len(reports) == 2
    assert sum(r.is_current for r in reports) == 1
    unchanged = await load_report(session, ref, path)
    assert unchanged["skipped"] == 1


async def test_weekly_revision_removes_disappeared_buckets(revision_session, tmp_path, monkeypatch):
    import etl.parse_weekly

    session = revision_session
    start, end = date(2026, 10, 2), date(2026, 10, 8)
    ref = ReportRef(
        date(2026, 10, 9), "weekly", "https://example.org/week.pdf", "Сводка", start, end
    )
    counts = [
        SimpleNamespace(
            disease="Бешенство", region=r, species=["cattle"], kind="quarantine_set", count=n
        )
        for r, n in [("Нижегородская область", 2), ("Московская область", 3)]
    ]
    parsed = SimpleNamespace(counts=counts, issues=[])
    monkeypatch.setattr(etl.parse_weekly, "parse_weekly", lambda *_: parsed)
    path = tmp_path / "week.pdf"
    path.write_bytes(b"%PDF-original")
    await load_report(session, ref, path)
    parsed.counts = [
        SimpleNamespace(
            disease="Бешенство",
            region="Нижегородская область",
            species=["cattle"],
            kind="quarantine_set",
            count=1,
        )
    ]
    path.write_bytes(b"%PDF-revision")
    await load_report(session, ref, path)
    rows = (await session.scalars(select(WeeklyCount))).all()
    assert [(r.region_code, r.count) for r in rows] == [("52", 1)]


async def test_source_can_restore_previous_bytes(revision_session, tmp_path, monkeypatch):
    import etl.parse_daily

    session = revision_session
    day = date(2026, 10, 12)
    ref = ReportRef(day, "daily", "https://example.org/revert.pdf", "Сводка")
    event = SimpleNamespace(
        disease="Бешенство",
        region="Московская область",
        date=day,
        district=None,
        locality="Ивановка",
        species=["cattle"],
        kind="outbreak",
        text="Первый текст",
        scores=[],
        total=2.0,
        source_urls=[],
    )
    parsed = SimpleNamespace(events=[event], issues=[])
    monkeypatch.setattr(etl.parse_daily, "parse_daily", lambda *_: parsed)
    path = tmp_path / "report.pdf"
    path.write_bytes(b"%PDF-first")
    await load_report(session, ref, path)
    event.text = "Изменённый текст"
    event.total = 4.0
    path.write_bytes(b"%PDF-second")
    await load_report(session, ref, path)
    event.text = "Первый текст"
    event.total = 2.0
    path.write_bytes(b"%PDF-first")
    await load_report(session, ref, path)
    monitor = await Monitor.load(session)
    assert len(monitor.events) == 1
    assert monitor.events[0].text == "Первый текст"
    assert monitor.events[0].level == 2
