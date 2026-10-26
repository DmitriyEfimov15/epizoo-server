"""Русские тексты Telegram; данные источников не интерпретируются как HTML."""

from html import escape
from urllib.parse import urlsplit

LEVEL_LABELS = {
    0: "событий нет",
    1: "низкий",
    2: "умеренный",
    3: "повышенный",
    4: "высокий",
    5: "очень высокий",
}
KIND_LABELS = {
    "outbreak": "Зарегистрирован очаг",
    "quarantine_set": "Установлен карантин",
    "quarantine_lifted": "Снят карантин",
}
NOT_LINKED = (
    "Хозяйство пока не подключено.\n\n"
    "Откройте профиль хозяйства на сайте и нажмите «Подключить Telegram» — "
    "бот подключится автоматически."
)
PRIVATE_ONLY = "Бот работает только в личном чате."
START_HELP = (
    "👋 Здравствуйте! Я присылаю оповещения об эпизоотической обстановке "
    "рядом с вашим хозяйством: очаги болезней животных и карантины.\n\n"
    "Чтобы начать, откройте профиль хозяйства на сайте и нажмите "
    "«Подключить Telegram»."
)
LINKED = (
    "✅ Хозяйство подключено.\n\n"
    "Я сообщу о новых очагах и карантинах в вашем регионе. "
    "Пользуйтесь кнопками меню внизу экрана."
)
MENU = "Главное меню — выберите действие кнопками внизу экрана."
HELP = (
    "<b>Что умеет бот</b>\n"
    "📊 <b>Обстановка</b> — уровень риска в вашем регионе и у соседей.\n"
    "📰 <b>Дайджест</b> — сводка событий за прошлую неделю.\n"
    "⚙️ <b>Настройки</b> — какие оповещения присылать.\n"
    "🔕 <b>Отключить бота</b> — перестать получать сообщения.\n\n"
    "<b>Уровни риска</b>\n"
    "1 — низкий, 2 — умеренный, 3 — повышенный, 4 — высокий, 5 — очень высокий.\n"
    "Оповещение приходит, если уровень события не ниже выбранного порога."
)
STOP_CONFIRM = "Отключить бота? Оповещения и дайджест перестанут приходить."
STOPPED = "Подписка отключена. Подключить хозяйство заново можно через профиль на сайте."
BOUND_ELSEWHERE = (
    "Хозяйство уже подключено к другому чату. "
    "Сначала отключите существующую подписку в профиле на сайте."
)
CHAT_BUSY = (
    "Этот чат уже подключён к другому хозяйству. "
    "Нажмите «Отключить бота», а затем подключите новое хозяйство."
)


def quoted(value, limit=300):
    """Ограничивает длину с учётом HTML entities, не разрезая их."""
    raw = str(value or "")
    parts = []
    length = 0
    for char in raw[:limit]:
        encoded = escape(char)
        if length + len(encoded) > limit - 1:
            break
        parts.append(encoded)
        length += len(encoded)
    result = "".join(parts)
    return result + ("…" if len(parts) < len(raw) else "")


def link(url, label):
    url = str(url or "")
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in {"https", "http"} or not parsed.hostname:
            return ""
    except ValueError:
        return ""
    encoded = escape(url, quote=True)
    if len(encoded) > 400:
        return ""
    return f'<a href="{encoded}">{escape(label)}</a>'


def event_message(monitor, event, frontend_url):
    disease = monitor.diseases[event.disease_id]
    location = ", ".join(
        filter(None, [monitor.regions[event.region_code].name, event.district, event.locality])
    )
    rows = [
        f"<b>{quoted(disease.name, 180)}</b>",
        f"{KIND_LABELS.get(event.kind, 'Сообщение')} — {event.date:%d.%m.%Y}",
        f"Место: {quoted(location, 400)}",
        f"Уровень: {event.level} — {LEVEL_LABELS[event.level]}.",
    ]
    recommendations = disease.recommendations or []
    if recommendations:
        rows.append("Действия по ветеринарным правилам:")
        for advice in recommendations[:2]:
            rows.append(quoted(advice.get("text", ""), 400))
            rule = link(advice.get("source_url"), "Ветеринарные правила")
            if rule:
                rows.append(rule)
    else:
        rows.append("За рекомендациями обратитесь в местную ветслужбу.")
    for url in event.source_urls[:2]:
        source = link(url, "Первоисточник")
        if source:
            rows.append(source)
    region_link = link(
        f"{frontend_url.rstrip('/')}/regions/{event.region_code}", "Карточка региона"
    )
    if region_link:
        rows.append(region_link)
    return "\n".join(rows)


def status_message(region, frontend_url, with_link=True):
    rows = [
        f"📍 <b>{quoted(region.name)}</b>",
        f"Уровень риска: <b>{region.level} — {LEVEL_LABELS[region.level]}</b>",
        "",
        f"Действующих карантинов: {region.active_quarantine_count}",
        f"Неподтверждённых карантинов: {region.unconfirmed_quarantine_count}",
        f"Сообщений за 30 дней: {region.event_count}",
    ]
    if region.neighbors:
        rows.extend(["", "<b>Соседние регионы</b>"])
        rows.extend(
            f"• {quoted(neighbor.name, 120)}: {neighbor.level} — {LEVEL_LABELS[neighbor.level]}"
            for neighbor in region.neighbors[:10]
        )
    url = link(f"{frontend_url.rstrip('/')}/regions/{region.code}", "Карточка региона")
    if with_link and url:
        rows.extend(["", url])
    return "\n".join(rows)


def settings_message(subscription):
    return (
        "⚙️ Настройки оповещений\n\n"
        f"Порог оповещений: {subscription.min_level} — {LEVEL_LABELS[subscription.min_level]}. "
        "Присылаю события этого уровня и выше.\n"
        f"Соседние регионы: {'включены' if subscription.include_neighbors else 'выключены'}.\n"
        f"Еженедельный дайджест: {'включён' if subscription.digest_enabled else 'выключен'}.\n\n"
        "Нажмите кнопку, чтобы изменить настройку."
    )
