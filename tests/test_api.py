import os
from datetime import datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import Settings
from app.db.base import Base
from app.db.session import session_factory
from app.main import create_app
from app.models import Disease, Event, Region, RegionNeighbor, Report, RouteCheck
from app.services.quarantine import rebuild_quarantines


@pytest.fixture
async def client():
    pg_url = os.environ.get("TEST_DATABASE_URL")
    schema = "test_" + uuid4().hex if pg_url else None
    app = create_app(
        Settings(
            database_url=pg_url or "sqlite+aiosqlite:///:memory:",
            api_key="test-key",
            telegram_bot_username="test_bot",
            summary_provider="template",
        )
    )
    admin = app.state.engine
    if schema:
        async with admin.begin() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        app.state.engine = create_async_engine(
            pg_url, connect_args={"server_settings": {"search_path": schema}}
        )
        app.state.session_factory = session_factory(app.state.engine)
    async with app.state.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    today = datetime.now(ZoneInfo("Europe/Moscow")).date()
    async with app.state.session_factory() as session:
        session.add_all(
            [
                Region(code=code, name=name, aliases=[], federal_district="ЦФО")
                for code, name in [
                    ("50", "Московская область"),
                    ("77", "Москва"),
                    ("71", "Тульская область"),
                ]
            ]
        )
        session.add(
            Disease(
                id=1,
                slug="rabies",
                name="Бешенство",
                aliases=[],
                species=["cattle", "carnivores"],
                is_zoonosis=True,
                base_level=3,
                description="Описание",
                recommendations=[],
            )
        )
        session.add(
            Report(
                id=1,
                date=today,
                type="daily",
                url="https://example.org/report.pdf",
                sha256="b" * 64,
                parse_status="ok",
            )
        )
        await session.flush()
        session.add_all(
            [
                RegionNeighbor(region_code="50", neighbor_code="77"),
                RegionNeighbor(region_code="77", neighbor_code="50"),
            ]
        )
        session.add_all(
            [
                Event(
                    id=1,
                    report_id=1,
                    date=today - timedelta(days=60),
                    disease_id=1,
                    region_code="50",
                    locality="Ивановка",
                    species=["cattle"],
                    kind="quarantine_set",
                    text="Установлен карантин",
                    scores=[],
                    total=3.1,
                    level=4,
                    source_urls=["https://example.org/act"],
                    fingerprint="event-1",
                ),
                Event(
                    id=2,
                    report_id=1,
                    date=today,
                    disease_id=1,
                    region_code="77",
                    locality="Петровка",
                    species=["carnivores"],
                    kind="outbreak",
                    text="Случай болезни",
                    scores=[],
                    total=2.6,
                    level=3,
                    source_urls=[],
                    fingerprint="event-2",
                ),
            ]
        )
        await session.flush()
        await rebuild_quarantines(session, today)
        await session.commit()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        c.app = app
        yield c
    await app.state.engine.dispose()
    if schema:
        async with admin.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()


async def test_empty_region_and_unknown(client):
    result = await client.get("/api/v1/regions/71")
    assert result.status_code == 200
    assert result.json()["level"] == 0
    assert result.json()["events"] == []
    unknown = await client.get("/api/v1/regions/999")
    assert unknown.status_code == 404
    assert set(unknown.json()) == {"code", "message"}


async def test_map_keeps_old_quarantine_and_filters_species(client):
    data = (await client.get("/api/v1/map?period=7&species=cattle")).json()
    region = next(row for row in data if row["code"] == "50")
    assert region["level"] == 4
    assert region["event_count"] == 0
    assert region["active_quarantine_count"] == 1
    no_matches = (await client.get("/api/v1/map?species=bees")).json()
    assert all(row["level"] == 0 for row in no_matches)


@pytest.mark.parametrize(
    "path",
    [
        "/map?species=unknown",
        "/events?page=0",
        "/events?from=2026-10-20&to=2026-10-01",
        "/map?disease=unknown",
        "/map?period=0",
    ],
)
async def test_invalid_filters(client, path):
    result = await client.get("/api/v1" + path)
    assert result.status_code in (404, 422)
    assert set(result.json()) == {"code", "message"}


async def test_events_pagination(client):
    data = (await client.get("/api/v1/events?page_size=1")).json()
    assert data["total"] == 2
    assert len(data["items"]) == 1
    assert data["items"][0]["id"] == 2
    assert (await client.get("/api/v1/events?species=bees")).json()["total"] == 0


async def test_route_check_logs_and_is_species_specific(client):
    data = (await client.get("/api/v1/route-check?from=50&to=71&species=cattle")).json()
    assert data["verdict"] == "high"
    assert data["from_region"]["level"] == 4
    assert data["to_region"]["level"] == 0
    assert "справоч" in data["disclaimer"].lower()
    empty = (await client.get("/api/v1/route-check?from=50&to=71&species=bees")).json()
    assert empty["verdict"] == "low"
    async with client.app.state.session_factory() as s:
        assert len((await s.scalars(select(RouteCheck))).all()) == 2


async def test_farm_profile_and_subscription(client):
    result = await client.post("/api/v1/farms", json={"region_code": "50", "species": ["cattle"]})
    assert result.status_code == 201
    token = result.json()["token"]
    assert (await client.get(f"/api/v1/farms/{token}")).json()["species"] == ["cattle"]
    assert (
        await client.put(f"/api/v1/farms/{token}", json={"region_code": "71", "species": ["bees"]})
    ).status_code == 200
    link = (await client.post(f"/api/v1/farms/{token}/telegram-link")).json()["url"]
    assert link == f"https://t.me/test_bot?start={token}"
    settings = {"min_level": 2, "include_neighbors": False, "digest_enabled": True}
    sub = await client.put(f"/api/v1/farms/{token}/subscription", json=settings)
    assert sub.json()["min_level"] == 2
    assert sub.json()["chat_id"] is None
    dashboard = (await client.get(f"/api/v1/farms/{token}/dashboard")).json()
    assert dashboard["region"]["code"] == "71"
    assert (await client.get(f"/api/v1/farms/{token}/digest")).json()["text"]
    assert (await client.delete(f"/api/v1/farms/{token}/subscription")).status_code == 204
    assert (
        await client.post("/api/v1/farms", json={"region_code": "50", "species": []})
    ).status_code == 422
    assert (await client.get("/api/v1/farms/bad-token")).status_code == 422


async def test_meta_refs_catalog_summary_and_openapi(client):
    assert (await client.get("/api/v1/meta")).json()["report_count"] == 1
    assert len((await client.get("/api/v1/refs/regions")).json()) == 3
    assert len((await client.get("/api/v1/refs/species")).json()) == 9
    assert (await client.get("/api/v1/diseases/rabies")).json()["name"] == "Бешенство"
    summary = (await client.get("/api/v1/regions/50/summary?period=90")).json()
    assert summary["provider"] == "template"
    assert "https://example.org/act" in summary["source_urls"]
    assert (await client.get("/api/v1/regions/50/history")).json() == []
    schema = (await client.get("/openapi.json")).json()
    assert "/api/v1/risk" not in schema["paths"]
    assert schema["components"]["schemas"]["EventOut"]["properties"]["source_urls"]


@pytest.mark.parametrize(
    ("from_code", "to_code", "animal", "verdict"),
    [
        ("50", "71", "cattle", "high"),
        ("77", "71", "carnivores", "elevated"),
        ("50", "77", "bees", "low"),
    ],
)
async def test_three_control_routes(client, from_code, to_code, animal, verdict):
    response = await client.get(
        f"/api/v1/route-check?from={from_code}&to={to_code}&species={animal}"
    )
    assert response.status_code == 200
    assert response.json()["verdict"] == verdict


async def test_relevant_offers_and_closed_internal_etl(client):
    offers = (await client.get("/api/v1/offers?region=50&species=cattle")).json()
    assert {o["id"] for o in offers} >= {
        "televeterinarian",
        "livestock-insurance",
        "preferential-farm-credit",
    }
    assert (await client.get("/api/v1/offers?region=71&species=bees")).json() == []
    for key in (None, "incorrect"):
        headers = {"X-API-Key": key} if key else {}
        response = await client.post("/api/v1/internal/etl/run", headers=headers)
        assert response.status_code == 401


async def test_snapshot_is_consistent_during_etl_commit(client, monkeypatch):
    if client.app.state.engine.dialect.name != "postgresql":
        pytest.skip("Проверка конкурентного PostgreSQL требует TEST_DATABASE_URL")
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models import Quarantine
    from app.services.monitoring import Monitor

    original = AsyncSession.scalars
    injected = False

    async def read_then_commit(self, statement, *args, **kwargs):
        nonlocal injected
        result = await original(self, statement, *args, **kwargs)
        if not injected and "FROM events" in str(statement):
            injected = True
            async with client.app.state.session_factory() as writer:
                event = Event(
                    id=999,
                    report_id=1,
                    date=datetime.now(ZoneInfo("Europe/Moscow")).date(),
                    disease_id=1,
                    region_code="50",
                    locality="Новый очаг",
                    species=["cattle"],
                    kind="quarantine_set",
                    text="Новая публикация",
                    scores=[],
                    level=5,
                    source_urls=[],
                    fingerprint="concurrent-new",
                )
                writer.add(event)
                await writer.flush()
                writer.add(
                    Quarantine(
                        set_event_id=999,
                        disease_id=1,
                        region_code="50",
                        locality_norm="новый очаг",
                        status="active",
                        since=event.date,
                    )
                )
                await writer.commit()
        return result

    monkeypatch.setattr(AsyncSession, "scalars", read_then_commit)
    async with client.app.state.session_factory() as reader:
        snapshot = await Monitor.load(reader)
        assert injected
        assert all(q.set_event_id in snapshot.by_event for q in snapshot.quarantines)
        assert snapshot.region_out("50", "cattle").level == 4
    # Новый независимый срез уже видит целиком завершённое обновление.
    async with client.app.state.session_factory() as reader:
        snapshot = await Monitor.load(reader)
        assert snapshot.region_out("50", "cattle").level == 5


async def test_changing_yandex_model_does_not_reuse_previous_summary(client):
    from app.services.monitoring import Monitor
    from app.services.summaries import region_summary

    class Provider:
        name = "yandex"
        timeout = 1

        def __init__(self, text):
            self.text = text

        async def summarize(self, texts, news_titles):
            return self.text

    settings = client.app.state.settings.model_copy(
        update={"summary_provider": "yandex", "yandex_model": "yandexgpt-5-lite"}
    )
    async with client.app.state.session_factory() as session:
        monitor = await Monitor.load(session)
        first = await region_summary(
            session,
            monitor,
            "50",
            None,
            90,
            settings,
            Provider("Первая сводка. Карантин установлен."),
        )
        settings = settings.model_copy(update={"yandex_model": "aliceai-llm"})
        second = await region_summary(
            session,
            monitor,
            "50",
            None,
            90,
            settings,
            Provider("Вторая сводка. Карантин установлен."),
        )
        assert first.text != second.text
        assert second.text == "Вторая сводка. Карантин установлен."
