from datetime import UTC, datetime, time, timedelta

import pytest
from sqlalchemy import select

from app.core.time import today_moscow
from app.db.base import Base
from app.db.session import make_engine, session_factory
from app.models import (
    Disease,
    Event,
    Farm,
    Notification,
    Region,
    RegionNeighbor,
    Report,
    Subscription,
)
from app.services.digest import build_digest
from app.services.monitoring import Monitor


@pytest.fixture
async def notification_session():
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = session_factory(engine)
    async with factory() as session:
        today = today_moscow()
        session.add_all(
            [
                Region(code="50", name="Московская область"),
                Region(code="77", name="Москва"),
                Region(code="71", name="Тульская область"),
                Disease(
                    id=1,
                    slug="rabies",
                    name="Бешенство <животных>",
                    species=["cattle"],
                    recommendations=[
                        {
                            "text": "Выполняйте <ветправила>",
                            "source_url": "https://example.org/rules?a=1&b=2",
                        }
                    ],
                ),
                Disease(
                    id=2, slug="other", name="Другая болезнь", species=["bees"], recommendations=[]
                ),
                Report(
                    id=1,
                    date=today,
                    type="daily",
                    url="https://example.org/report.pdf",
                    sha256="a" * 64,
                    parse_status="ok",
                    parsed_at=datetime.now(UTC),
                ),
                Report(
                    id=2,
                    date=today,
                    type="daily",
                    url="https://example.org/old.pdf",
                    sha256="b" * 64,
                    parse_status="ok",
                    parsed_at=datetime.now(UTC) - timedelta(days=5),
                ),
            ]
        )
        await session.flush()
        session.add(RegionNeighbor(region_code="50", neighbor_code="77"))
        farm = Farm(region_code="50", species=["cattle"])
        session.add(farm)
        await session.flush()
        session.add(
            Subscription(
                farm_token=farm.token,
                chat_id=123,
                min_level=3,
                include_neighbors=True,
                digest_enabled=True,
                created_at=datetime.now(UTC) - timedelta(days=1),
            )
        )
        for event_id, region, species, level, report_id, event_date in [
            (1, "50", ["cattle"], 4, 1, today),
            (2, "77", [], 3, 1, today - timedelta(days=1)),
            (3, "71", ["cattle"], 5, 1, today),
            (4, "50", ["bees"], 4, 1, today),
            (5, "50", ["cattle"], 2, 1, today),
            (6, "50", ["cattle"], 5, 2, today),
            (7, "50", ["cattle"], 5, 1, today + timedelta(days=1)),
        ]:
            session.add(
                Event(
                    id=event_id,
                    region_code=region,
                    disease_id=1,
                    report_id=report_id,
                    date=event_date,
                    species=species,
                    level=level,
                    kind="outbreak",
                    text="Текст <script>",
                    locality="Ивановка <b>",
                    source_urls=["https://example.org/act?a=1&b=2"],
                    fingerprint=str(event_id),
                )
            )
        await session.commit()
        session.test_factory = factory
        yield session
    await engine.dispose()


class RecordingSender:
    def __init__(self, failing=False):
        self.messages = []
        self.failing = failing

    async def send_message(self, chat_id, text):
        if self.failing:
            raise RuntimeError("Секретные данные не должны попадать в лог")
        self.messages.append((chat_id, text))


async def test_notifications_filter_facts_and_send_once(notification_session):
    from app.services.notifications import notify

    session = notification_session
    sender = RecordingSender()
    result = await notify(session, sender, frontend_url="https://example.org")
    await session.commit()
    assert result["sent"] == 2
    assert {(row.event_id) for row in (await session.scalars(select(Notification))).all()} == {1, 2}
    assert all(chat_id == 123 for chat_id, _ in sender.messages)
    text = next(value for _, value in sender.messages if "/regions/50" in value)
    assert "Бешенство &lt;животных&gt;" in text
    assert "Ивановка &lt;b&gt;" in text
    assert "Выполняйте &lt;ветправила&gt;" in text
    assert "https://example.org/regions/50" in text
    assert "&amp;b=2" in text
    assert "4" in text and "высок" in text.lower()
    assert (await notify(session, sender))["sent"] == 0
    assert len(sender.messages) == 2


async def test_notifications_honor_neighbors_toggle_and_unbound_chats(notification_session):
    from app.services.notifications import notify

    session = notification_session
    subscription = await session.scalar(select(Subscription))
    subscription.include_neighbors = False
    await session.commit()
    sender = RecordingSender()
    assert (await notify(session, sender))["sent"] == 1
    await session.commit()
    subscription.chat_id = None
    await session.commit()
    assert (await notify(session, sender))["sent"] == 0


async def test_failed_send_is_retryable_and_not_logged_with_details(notification_session, caplog):
    from app.services.notifications import notify

    session = notification_session
    failing = RecordingSender(failing=True)
    result = await notify(session, failing)
    await session.commit()
    assert result["sent"] == 0 and result["failed"] == 2
    assert (await session.scalars(select(Notification))).all() == []
    assert "Секретные" not in caplog.text
    assert (await notify(session, RecordingSender()))["sent"] == 2


async def test_notification_without_recommendations_refers_to_veterinary_service(
    notification_session,
):
    from app.services.notifications import notify

    session = notification_session
    disease = await session.get(Disease, 1)
    disease.recommendations = []
    await session.commit()
    sender = RecordingSender()
    await notify(session, sender)
    assert "ветслужб" in sender.messages[0][1].lower()


async def test_weekly_digest_is_same_as_web_and_idempotent(notification_session):
    from app.services.notifications import send_digests

    session = notification_session
    farm = await session.scalar(select(Farm))
    expected = build_digest(await Monitor.load(session), farm)
    sender = RecordingSender()
    assert (await send_digests(session, sender))["sent"] == 1
    await session.commit()
    assert sender.messages[0][1] == expected.text
    subscription = await session.scalar(select(Subscription))
    assert subscription.last_digest_week == expected.week_start
    assert (await send_digests(session, sender))["sent"] == 0


async def test_failed_weekly_digest_does_not_mark_week(notification_session):
    from app.services.notifications import send_digests

    session = notification_session
    assert (await send_digests(session, RecordingSender(failing=True)))["failed"] == 1
    await session.commit()
    assert (await session.scalar(select(Subscription))).last_digest_week is None
    assert (await send_digests(session, RecordingSender()))["sent"] == 1


async def test_weekly_digest_disabled_is_not_sent(notification_session):
    from app.services.notifications import send_digests

    session = notification_session
    subscription = await session.scalar(select(Subscription))
    subscription.digest_enabled = False
    await session.commit()
    sender = RecordingSender()
    assert (await send_digests(session, sender))["sent"] == 0
    assert not sender.messages


async def test_new_publication_can_include_old_act_but_backfill_cannot_notify(notification_session):
    from app.services.notifications import notify

    session = notification_session
    event = await session.get(Event, 2)
    event.date = today_moscow() - timedelta(days=20)
    session.add(
        Report(
            id=3,
            date=today_moscow() - timedelta(days=10),
            type="daily",
            url="https://example.org/archive",
            sha256="c" * 64,
            parse_status="ok",
            parsed_at=datetime.now(UTC),
        )
    )
    await session.flush()
    session.add(
        Event(
            id=8,
            report_id=3,
            date=today_moscow() - timedelta(days=10),
            region_code="50",
            disease_id=1,
            species=["cattle"],
            level=5,
            kind="outbreak",
            text="Архивное событие",
            fingerprint="archive-event",
        )
    )
    await session.commit()
    sender = RecordingSender()
    assert (await notify(session, sender))["sent"] == 2
    assert {row.event_id for row in (await session.scalars(select(Notification))).all()} == {1, 2}


async def test_postgres_lock_denies_other_process_before_any_send(
    notification_session, monkeypatch
):
    from types import SimpleNamespace

    from app.services.notifications import notify

    session = notification_session
    monkeypatch.setattr(
        session, "get_bind", lambda: SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
    )

    async def locked(statement):
        assert str(statement) == "SELECT pg_try_advisory_xact_lock(824014)"
        return False

    monkeypatch.setattr(session, "scalar", locked)
    sender = RecordingSender()
    result = await notify(session, sender)
    assert result["locked"] is True
    assert result["sent"] == 0
    assert not sender.messages


async def test_publication_cutoff_uses_moscow_date_not_utc_date(notification_session):
    from app.services.notifications import notify

    session = notification_session
    utc_evening = datetime.combine(today_moscow() - timedelta(days=1), time(22), tzinfo=UTC)
    subscription = await session.scalar(select(Subscription))
    subscription.created_at = utc_evening
    report = await session.get(Report, 1)
    report.date = utc_evening.date()
    report.parsed_at = utc_evening + timedelta(minutes=1)
    await session.commit()
    sender = RecordingSender()
    assert (await notify(session, sender))["sent"] == 0
    assert not sender.messages


@pytest.mark.parametrize("operation", ["notify", "send_digests"])
async def test_dispatch_locks_subscription_until_commit(
    notification_session, monkeypatch, operation
):
    from sqlalchemy.dialects import postgresql

    from app.services import notifications

    session = notification_session
    original = session.scalars
    queries = []

    async def capture(statement, *args, **kwargs):
        queries.append(str(statement.compile(dialect=postgresql.dialect())))
        return await original(statement, *args, **kwargs)

    monkeypatch.setattr(session, "scalars", capture)
    await getattr(notifications, operation)(session, RecordingSender())
    subscription_queries = [query for query in queries if "FROM subscriptions" in query]
    assert subscription_queries and all("FOR UPDATE" in query for query in subscription_queries)


async def test_notification_stays_within_telegram_limit_and_rejects_executable_urls(
    notification_session,
):
    from app.services.notifications import notify

    session = notification_session
    disease = await session.get(Disease, 1)
    disease.name = "<" * 10000
    disease.recommendations = [{"text": "<&" * 5000, "source_url": "javascript:alert(1)"}] * 10
    event = await session.get(Event, 1)
    event.locality = ">" * 10000
    event.source_urls = ["javascript:alert(1)", "https://example.org/source"]
    await session.commit()
    sender = RecordingSender()
    await notify(session, sender)
    assert all(len(value) <= 4096 and "javascript:" not in value for _, value in sender.messages)
    assert "&lt;" in sender.messages[0][1]
