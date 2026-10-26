from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import select

from app.core.config import Settings
from app.models import Farm, Subscription
from app.services.digest import build_digest
from app.services.monitoring import Monitor
from tests import test_notifications

notification_session = test_notifications.notification_session


class FakeMessage:
    def __init__(self, text="", chat_id=123, chat_type="private"):
        self.text = text
        self.chat = SimpleNamespace(id=chat_id, type=chat_type)
        self.from_user = SimpleNamespace(id=chat_id)
        self.answers = []

    async def answer(self, text, **kwargs):
        self.answers.append((text, kwargs))

    async def edit_reply_markup(self, **kwargs):
        self.markup = kwargs.get("reply_markup")

    async def edit_text(self, text, **kwargs):
        self.text = text
        self.markup = kwargs.get("reply_markup")


class FakeCallback:
    def __init__(self, data, chat_id=123, chat_type="private"):
        self.data = data
        self.message = FakeMessage(chat_id=chat_id, chat_type=chat_type)
        self.from_user = SimpleNamespace(id=chat_id)
        self.answers = []

    async def answer(self, text=None, **kwargs):
        self.answers.append(text)


async def test_start_links_existing_web_subscription_and_preserves_settings(notification_session):
    from bot.handlers import start_command

    session = notification_session
    subscription = await session.scalar(select(Subscription))
    subscription.chat_id = None
    subscription.min_level = 5
    await session.commit()
    message = FakeMessage(f"/start {subscription.farm_token}", chat_id=321)
    await start_command(message, session.test_factory, Settings())
    await session.refresh(subscription)
    assert subscription.chat_id == 321
    assert subscription.min_level == 5
    assert "подключ" in message.answers[0][0].lower()


async def test_start_cannot_take_over_farm_bound_to_another_chat(notification_session):
    from bot.handlers import start_command

    session = notification_session
    subscription = await session.scalar(select(Subscription))
    message = FakeMessage(f"/start {subscription.farm_token}", chat_id=321)
    await start_command(message, session.test_factory, Settings())
    await session.refresh(subscription)
    assert subscription.chat_id == 123
    assert "отключ" in message.answers[0][0].lower()


async def test_start_creates_subscription_for_farm_without_one(notification_session):
    from bot.handlers import start_command

    session = notification_session
    farm = Farm(region_code="50", species=["cattle"])
    session.add(farm)
    await session.commit()
    message = FakeMessage(f"/start {farm.token}", chat_id=321)
    await start_command(message, session.test_factory, Settings())
    subscription = await session.scalar(
        select(Subscription).where(Subscription.farm_token == farm.token)
    )
    assert subscription.chat_id == 321


async def test_start_refuses_invalid_unknown_uuid_and_groups(notification_session):
    from bot.handlers import start_command

    for value, chat_type in [("not-a-uuid", "private"), (str(uuid4()), "private"), ("", "group")]:
        message = FakeMessage(f"/start {value}", chat_id=321, chat_type=chat_type)
        await start_command(message, notification_session.test_factory, Settings())
        assert message.answers
    assert len((await notification_session.scalars(select(Subscription))).all()) == 1


async def test_bot_digest_uses_web_text(notification_session):
    from bot.handlers import digest_command

    expected = build_digest(
        await Monitor.load(notification_session), await notification_session.scalar(select(Farm))
    )
    message = FakeMessage("/digest")
    await digest_command(message, notification_session.test_factory)
    assert message.answers[0][0] == expected.text


async def test_settings_callback_changes_only_owners_subscription(notification_session):
    from bot.handlers import settings_callback

    session = notification_session
    callback = FakeCallback("settings:min:5")
    callback.message.from_user = SimpleNamespace(id=999)  # Исходное сообщение отправил бот.
    await settings_callback(callback, session.test_factory)
    subscription = await session.scalar(select(Subscription))
    await session.refresh(subscription)
    assert subscription.min_level == 5
    assert "Порог оповещений: 5" in callback.message.text
    await settings_callback(FakeCallback("settings:neighbors:0"), session.test_factory)
    await settings_callback(FakeCallback("settings:digest:0"), session.test_factory)
    await session.refresh(subscription)
    assert subscription.include_neighbors is False and subscription.digest_enabled is False
    await settings_callback(FakeCallback("settings:min:1", chat_id=321), session.test_factory)
    await settings_callback(FakeCallback("settings:min:9"), session.test_factory)
    await session.refresh(subscription)
    assert subscription.min_level == 5


async def test_stop_removes_subscription(notification_session):
    from bot.handlers import stop_command

    message = FakeMessage("/stop")
    await stop_command(message, notification_session.test_factory)
    assert (await notification_session.scalars(select(Subscription))).all() == []


async def test_status_and_settings_render_farm(notification_session):
    from bot.handlers import settings_command, status_command

    message = FakeMessage("/status")
    await status_command(message, notification_session.test_factory, Settings())
    assert "Московская область" in message.answers[0][0]
    assert "5" in message.answers[0][0]
    settings_message = FakeMessage("/settings")
    await settings_command(settings_message, notification_session.test_factory)
    markup = settings_message.answers[0][1]["reply_markup"]
    data = {button.callback_data for row in markup.inline_keyboard for button in row}
    assert {f"settings:min:{i}" for i in range(1, 6)} <= data


def test_scheduler_runs_monday_digest_after_update_without_duplicate_morning():
    from worker.scheduler import create_scheduler

    scheduler = create_scheduler(Settings(), lambda: None)
    jobs = {job.id: job for job in scheduler.get_jobs()}
    assert set(jobs) == {"morning", "afternoon", "weekly"}
    assert str(jobs["weekly"].trigger.timezone) == "Europe/Moscow"
    assert "day_of_week='mon'" in str(jobs["weekly"].trigger)
    assert "day_of_week='tue-sun'" in str(jobs["morning"].trigger)
    assert "hour='9'" in str(jobs["weekly"].trigger)
    assert "hour='15'" in str(jobs["afternoon"].trigger)
    assert all(job.max_instances == 1 and job.coalesce for job in jobs.values())


async def test_worker_without_bot_still_updates(notification_session, monkeypatch):
    from worker.scheduler import run_cycle

    calls = []

    async def fake_update(settings):
        calls.append("etl")
        return {"events": 1}

    monkeypatch.setattr("worker.scheduler.run_update", fake_update)
    result = await run_cycle(Settings(), notification_session.test_factory, sender=None)
    assert calls == ["etl"]
    assert result["etl"] == {"events": 1}


async def test_weekly_worker_updates_before_notifications_and_digest(
    notification_session, monkeypatch
):
    from worker.scheduler import run_cycle

    calls = []

    async def fake_update(settings):
        calls.append("etl")
        return {"events": 2}

    class Sender:
        async def send_message(self, chat_id, text):
            calls.append("digest" if text.startswith("Дайджест") else "notify")

    monkeypatch.setattr("worker.scheduler.run_update", fake_update)
    result = await run_cycle(Settings(), notification_session.test_factory, Sender(), weekly=True)
    assert calls == ["etl", "notify", "notify", "digest"]
    assert result["notifications"]["sent"] == 2
    assert result["digests"]["sent"] == 1
    second = await run_cycle(Settings(), notification_session.test_factory, Sender(), weekly=True)
    assert second["notifications"]["sent"] == 0
    assert second["digests"]["sent"] == 0


async def test_link_shows_main_menu_and_start_without_token_reopens_it(notification_session):
    from aiogram.types import ReplyKeyboardMarkup

    from bot.handlers import start_command

    session = notification_session
    farm = Farm(region_code="50", species=["cattle"])
    session.add(farm)
    await session.commit()
    message = FakeMessage(f"/start {farm.token}", chat_id=321)
    await start_command(message, session.test_factory, Settings())
    assert isinstance(message.answers[0][1]["reply_markup"], ReplyKeyboardMarkup)
    again = FakeMessage("/start", chat_id=321)
    await start_command(again, session.test_factory, Settings())
    assert isinstance(again.answers[0][1]["reply_markup"], ReplyKeyboardMarkup)
    stranger = FakeMessage("/start", chat_id=555)
    await start_command(stranger, session.test_factory, Settings())
    assert "Подключить Telegram" in stranger.answers[0][0]


async def test_menu_buttons_route_to_handlers(notification_session):
    from aiogram.filters import Command

    from bot import keyboards
    from bot.handlers import create_router, help_command, status_command, stop_button

    router = create_router()
    by_text = {}
    for handler in router.message.handlers:
        for flt in handler.filters:
            if not isinstance(flt.callback, Command):
                by_text.setdefault(handler.callback, []).append(flt)
    routed = set(by_text)
    assert {status_command, help_command, stop_button} <= routed
    menu = keyboards.main_menu()
    labels = {button.text for row in menu.keyboard for button in row}
    assert labels == keyboards.MENU_BUTTONS


async def test_status_has_refresh_button_and_public_region_link(notification_session):
    from bot.handlers import status_callback, status_command

    message = FakeMessage("📊 Обстановка")
    await status_command(
        message, notification_session.test_factory, Settings(frontend_url="https://epizoo.ru")
    )
    text, kwargs = message.answers[0]
    buttons = [button for row in kwargs["reply_markup"].inline_keyboard for button in row]
    assert buttons[0].callback_data == "status:refresh"
    assert buttons[1].url == "https://epizoo.ru/regions/50"
    assert "Карточка региона" not in text
    callback = FakeCallback("status:refresh")
    await status_callback(callback, notification_session.test_factory, Settings())
    assert "Московская область" in callback.message.text
    assert callback.answers == ["Данные обновлены."]


def test_localhost_urls_are_not_used_in_buttons():
    from bot.keyboards import button_url

    assert button_url("http://localhost:5173", "/") is None
    assert button_url("http://127.0.0.1:8080", "/") is None
    assert button_url("https://epizoo.ru/", "/regions/50") == "https://epizoo.ru/regions/50"


async def test_stop_button_asks_confirmation(notification_session):
    from bot.handlers import stop_button, stop_callback

    message = FakeMessage("🔕 Отключить бота")
    await stop_button(message, notification_session.test_factory)
    assert "Отключить бота?" in message.answers[0][0]
    await stop_callback(FakeCallback("stop:no"), notification_session.test_factory)
    assert (await notification_session.scalars(select(Subscription))).all()
    confirm = FakeCallback("stop:yes")
    await stop_callback(confirm, notification_session.test_factory)
    assert (await notification_session.scalars(select(Subscription))).all() == []
    assert confirm.message.answers
