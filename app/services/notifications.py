"""Рассылка новых публикаций и дайджеста с журналом успешных отправок.

Вызывающий код обязан выполнить commit после функции. PostgreSQL advisory xact lock
сохраняется до окончания этой транзакции и исключает параллельные рассылки.
Строгая exactly-once доставка Telegram невозможна: если процесс упал после send_message,
но до commit, следующая попытка может повторить сообщение. Неудачная отправка не
создаёт Notification и не меняет last_digest_week; журнал обеспечивает повторяемость
при обычных перезапусках после успешного commit.
"""

import asyncio
import logging
from datetime import UTC

from sqlalchemy import select, text

from app.core.time import MOSCOW
from app.models import Farm, Notification, Subscription
from app.services.digest import build_digest
from app.services.monitoring import Monitor
from bot.texts import event_message

logger = logging.getLogger(__name__)
_local_lock = asyncio.Lock()


async def acquire_dispatch_lock(session):
    if session.get_bind().dialect.name != "postgresql":
        return True
    return bool(await session.scalar(text("SELECT pg_try_advisory_xact_lock(824014)")))


def utc(value):
    # SQLite не сохраняет tzinfo; в БД все timestamp приложения записываются как UTC.
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


async def notify(session, sender, frontend_url="http://localhost:5173") -> dict:
    result = {"sent": 0, "failed": 0, "locked": False}
    async with _local_lock:
        if not await acquire_dispatch_lock(session):
            result["locked"] = True
            return result
        monitor = await Monitor.load(session)
        farms = {farm.token: farm for farm in (await session.scalars(select(Farm))).all()}
        subscriptions = (
            await session.scalars(
                select(Subscription).where(Subscription.chat_id.is_not(None)).with_for_update()
            )
        ).all()
        sent = {
            (row.subscription_id, row.event_id)
            for row in (await session.scalars(select(Notification))).all()
        }
        reports = {report.id: report for report in monitor.reports}
        for subscription in subscriptions:
            farm = farms.get(subscription.farm_token)
            if farm is None:
                continue
            subscribed_at = utc(subscription.created_at)
            subscribed_date = subscribed_at.astimezone(MOSCOW).date()
            codes = {farm.region_code}
            if subscription.include_neighbors:
                codes.update(monitor.neighbors[farm.region_code])
            for event in sorted(monitor.events, key=lambda item: (item.date, item.id)):
                if (
                    (subscription.id, event.id) in sent
                    or event.region_code not in codes
                    or event.date > monitor.today
                    or event.level < subscription.min_level
                    or not monitor.matches(event, farm.species)
                    or reports[event.report_id].date < subscribed_date
                    or utc(reports[event.report_id].parsed_at) < subscribed_at
                ):
                    continue
                try:
                    await sender.send_message(
                        subscription.chat_id, event_message(monitor, event, frontend_url)
                    )
                except Exception as error:
                    logger.warning("Не удалось отправить уведомление (%s)", type(error).__name__)
                    result["failed"] += 1
                    continue
                session.add(Notification(subscription_id=subscription.id, event_id=event.id))
                await session.flush()
                sent.add((subscription.id, event.id))
                result["sent"] += 1
        return result


async def send_digests(session, sender) -> dict:
    result = {"sent": 0, "failed": 0, "locked": False}
    async with _local_lock:
        if not await acquire_dispatch_lock(session):
            result["locked"] = True
            return result
        monitor = await Monitor.load(session)
        subscriptions = (
            await session.scalars(
                select(Subscription)
                .where(Subscription.chat_id.is_not(None), Subscription.digest_enabled.is_(True))
                .with_for_update()
            )
        ).all()
        for subscription in subscriptions:
            farm = await session.get(Farm, subscription.farm_token)
            if farm is None:
                continue
            digest = build_digest(monitor, farm)
            if (
                subscription.last_digest_week is not None
                and subscription.last_digest_week >= digest.week_start
            ):
                continue
            try:
                # DigestOut.text передаётся без изменений; sender использует plain text.
                await sender.send_message(subscription.chat_id, digest.text)
            except Exception as error:
                logger.warning("Не удалось отправить дайджест (%s)", type(error).__name__)
                result["failed"] += 1
                continue
            subscription.last_digest_week = digest.week_start
            await session.flush()
            result["sent"] += 1
        return result
