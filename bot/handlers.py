from datetime import UTC, datetime
from uuid import UUID

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.models import Farm, Subscription
from app.services.digest import build_digest
from app.services.monitoring import Monitor
from bot import keyboards, texts
from bot.keyboards import settings_keyboard


def is_private(message):
    return (
        message.chat.type == "private"
        and message.from_user is not None
        and message.from_user.id == message.chat.id
    )


async def subscription_for_chat(session, chat_id):
    return await session.scalar(
        select(Subscription).where(Subscription.chat_id == chat_id).with_for_update()
    )


async def start_command(message: Message, session_factory, settings):
    if not is_private(message):
        await message.answer(texts.PRIVATE_ONLY)
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await menu_command(message, session_factory, settings)
        return
    try:
        token = str(UUID(parts[1].strip()))
    except ValueError:
        await message.answer(
            texts.START_HELP, reply_markup=keyboards.site_keyboard(settings.frontend_url)
        )
        return
    response = texts.LINKED
    linked = False
    async with session_factory() as session:
        if session.get_bind().dialect.name == "postgresql":
            await session.execute(text("SELECT pg_advisory_xact_lock(824015)"))
        farm = await session.scalar(select(Farm).where(Farm.token == token).with_for_update())
        if farm is None:
            response = (
                "Хозяйство не найдено. Создайте профиль на сайте "
                "и откройте новую ссылку подключения."
            )
        else:
            subscription = await session.scalar(
                select(Subscription).where(Subscription.farm_token == token).with_for_update()
            )
            existing = await subscription_for_chat(session, message.chat.id)
            if subscription is not None and subscription.chat_id not in (None, message.chat.id):
                response = texts.BOUND_ELSEWHERE
            elif existing is not None and existing.farm_token != token:
                response = texts.CHAT_BUSY
            else:
                if subscription is None:
                    subscription = Subscription(farm_token=token)
                    session.add(subscription)
                if subscription.chat_id is None:
                    subscription.created_at = datetime.now(UTC)
                subscription.chat_id = message.chat.id
                try:
                    await session.commit()
                    linked = True
                except IntegrityError:
                    await session.rollback()
                    response = "Подписка уже изменилась. Проверьте подключение в профиле на сайте."
    await message.answer(response, reply_markup=keyboards.main_menu() if linked else None)


async def menu_command(message: Message, session_factory, settings):
    if not is_private(message):
        await message.answer(texts.PRIVATE_ONLY)
        return
    async with session_factory() as session:
        subscription = await subscription_for_chat(session, message.chat.id)
    if subscription is None:
        await message.answer(
            texts.START_HELP, reply_markup=keyboards.site_keyboard(settings.frontend_url)
        )
    else:
        await message.answer(texts.MENU, reply_markup=keyboards.main_menu())


async def help_command(message: Message):
    await message.answer(texts.HELP, parse_mode="HTML")


async def not_linked(message, settings):
    frontend_url = settings.frontend_url if settings is not None else None
    await message.answer(texts.NOT_LINKED, reply_markup=keyboards.site_keyboard(frontend_url))


async def load_status(session_factory, chat_id, settings):
    """Возвращает текст и клавиатуру обстановки либо None, если чат не подключён."""
    async with session_factory() as session:
        subscription = await subscription_for_chat(session, chat_id)
        if subscription is None:
            return None
        farm = await session.get(Farm, subscription.farm_token)
        region = (await Monitor.load(session)).region_out(farm.region_code, farm.species)
    region_url = keyboards.button_url(settings.frontend_url, f"/regions/{region.code}")
    return (
        texts.status_message(region, settings.frontend_url, with_link=region_url is None),
        keyboards.status_keyboard(region_url),
    )


async def status_command(message: Message, session_factory, settings):
    if not is_private(message):
        await message.answer(texts.PRIVATE_ONLY)
        return
    status = await load_status(session_factory, message.chat.id, settings)
    if status is None:
        await not_linked(message, settings)
        return
    response, markup = status
    await message.answer(response, parse_mode="HTML", reply_markup=markup)


async def status_callback(callback: CallbackQuery, session_factory, settings):
    message = callback.message
    if not is_owner(callback):
        await callback.answer("Доступно только владельцу личного чата.")
        return
    status = await load_status(session_factory, message.chat.id, settings)
    if status is None:
        await callback.answer("Сначала подключите хозяйство.")
        return
    response, markup = status
    try:
        await message.edit_text(response, parse_mode="HTML", reply_markup=markup)
    except TelegramBadRequest:
        pass  # Данные не изменились — Telegram отклоняет одинаковый текст.
    await callback.answer("Данные обновлены.")


async def settings_command(message: Message, session_factory, settings=None):
    if not is_private(message):
        await message.answer(texts.PRIVATE_ONLY)
        return
    async with session_factory() as session:
        subscription = await subscription_for_chat(session, message.chat.id)
        if subscription is None:
            await not_linked(message, settings)
            return
        await message.answer(
            texts.settings_message(subscription), reply_markup=settings_keyboard(subscription)
        )


async def digest_command(message: Message, session_factory, settings=None):
    if not is_private(message):
        await message.answer(texts.PRIVATE_ONLY)
        return
    async with session_factory() as session:
        subscription = await subscription_for_chat(session, message.chat.id)
        if subscription is None:
            response = None
        else:
            farm = await session.get(Farm, subscription.farm_token)
            response = build_digest(await Monitor.load(session), farm).text
    if response is None:
        await not_linked(message, settings)
        return
    await message.answer(response, parse_mode=None)


async def unsubscribe(session_factory, chat_id):
    async with session_factory() as session:
        subscription = await subscription_for_chat(session, chat_id)
        if subscription is not None:
            await session.delete(subscription)
            await session.commit()


async def stop_command(message: Message, session_factory):
    if not is_private(message):
        await message.answer(texts.PRIVATE_ONLY)
        return
    await unsubscribe(session_factory, message.chat.id)
    await message.answer(texts.STOPPED, reply_markup=ReplyKeyboardRemove())


async def stop_button(message: Message, session_factory):
    if not is_private(message):
        await message.answer(texts.PRIVATE_ONLY)
        return
    await message.answer(texts.STOP_CONFIRM, reply_markup=keyboards.stop_confirm_keyboard())


async def stop_callback(callback: CallbackQuery, session_factory):
    message = callback.message
    if not is_owner(callback):
        await callback.answer("Доступно только владельцу личного чата.")
        return
    if callback.data == "stop:yes":
        await unsubscribe(session_factory, message.chat.id)
        await message.edit_text("🔕 Бот отключён.")
        await message.answer(texts.STOPPED, reply_markup=ReplyKeyboardRemove())
    else:
        await message.edit_text("Хорошо, бот остаётся подключённым.")
    await callback.answer()


def is_owner(callback):
    message = callback.message
    return (
        message is not None
        and message.chat.type == "private"
        and callback.from_user.id == message.chat.id
    )


async def settings_callback(callback: CallbackQuery, session_factory):
    message = callback.message
    if not is_owner(callback):
        await callback.answer("Настройки доступны только владельцу личного чата.")
        return
    parts = (callback.data or "").split(":")
    if len(parts) != 3 or parts[0] != "settings":
        await callback.answer("Некорректная настройка.")
        return
    setting, value = parts[1:]
    if setting == "min" and value in {"1", "2", "3", "4", "5"}:
        key, selected = "min_level", int(value)
    elif setting in {"neighbors", "digest"} and value in {"0", "1"}:
        key = "include_neighbors" if setting == "neighbors" else "digest_enabled"
        selected = value == "1"
    else:
        await callback.answer("Некорректная настройка.")
        return
    async with session_factory() as session:
        subscription = await subscription_for_chat(session, message.chat.id)
        if subscription is None:
            await callback.answer("Сначала подключите хозяйство.")
            return
        setattr(subscription, key, selected)
        await session.commit()
        markup = settings_keyboard(subscription)
        response = texts.settings_message(subscription)
    if message.text != response:
        await message.edit_text(response, reply_markup=markup)
    await callback.answer("Настройки сохранены.")


def create_router():
    router = Router(name="farm")
    for command, handler in (
        ("start", start_command),
        ("menu", menu_command),
        ("help", help_command),
        ("status", status_command),
        ("settings", settings_command),
        ("digest", digest_command),
        ("stop", stop_command),
    ):
        router.message.register(handler, Command(command))
    for button, handler in (
        (keyboards.STATUS, status_command),
        (keyboards.DIGEST, digest_command),
        (keyboards.SETTINGS, settings_command),
        (keyboards.HELP, help_command),
        (keyboards.STOP, stop_button),
    ):
        router.message.register(handler, F.text == button)
    router.callback_query.register(settings_callback, F.data.startswith("settings:"))
    router.callback_query.register(status_callback, F.data == "status:refresh")
    router.callback_query.register(stop_callback, F.data.in_({"stop:yes", "stop:no"}))
    router.message.register(menu_command, F.chat.type == "private")
    return router
