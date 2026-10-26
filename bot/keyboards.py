from ipaddress import ip_address
from urllib.parse import urlsplit

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from bot.texts import LEVEL_LABELS

STATUS = "📊 Обстановка"
DIGEST = "📰 Дайджест"
SETTINGS = "⚙️ Настройки"
HELP = "❓ Помощь"
STOP = "🔕 Отключить бота"
MENU_BUTTONS = {STATUS, DIGEST, SETTINGS, HELP, STOP}


def main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=STATUS), KeyboardButton(text=DIGEST)],
            [KeyboardButton(text=SETTINGS), KeyboardButton(text=HELP)],
            [KeyboardButton(text=STOP)],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Выберите действие в меню ниже",
    )


def button_url(frontend_url, path=""):
    """Telegram принимает в кнопках только публичные адреса, без localhost и IP."""
    url = f"{str(frontend_url or '').rstrip('/')}{path}"
    try:
        parsed = urlsplit(url)
    except ValueError:
        return None
    host = parsed.hostname or ""
    if parsed.scheme not in {"https", "http"} or "." not in host or host.endswith(".localhost"):
        return None
    try:
        ip_address(host)
    except ValueError:
        return url
    return None


def site_keyboard(frontend_url):
    url = button_url(frontend_url, "/")
    if url is None:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🌐 Открыть сайт", url=url)]]
    )


def status_keyboard(region_url):
    rows = [[InlineKeyboardButton(text="🔄 Обновить", callback_data="status:refresh")]]
    if region_url:
        rows.append([InlineKeyboardButton(text="🗺 Карточка региона", url=region_url)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def settings_keyboard(subscription):
    def level(i):
        mark = "✅ " if subscription.min_level == i else ""
        return InlineKeyboardButton(
            text=f"{mark}{i} · {LEVEL_LABELS[i]}", callback_data=f"settings:min:{i}"
        )

    def toggle(name, enabled, label):
        return [
            InlineKeyboardButton(
                text=f"{'✅' if enabled else '⬜️'} {label}",
                callback_data=f"settings:{name}:{int(not enabled)}",
            )
        ]

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [level(1), level(2)],
            [level(3), level(4)],
            [level(5)],
            toggle("neighbors", subscription.include_neighbors, "Следить за соседними регионами"),
            toggle("digest", subscription.digest_enabled, "Дайджест по понедельникам"),
        ]
    )


def stop_confirm_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Да, отключить", callback_data="stop:yes"),
                InlineKeyboardButton(text="Отмена", callback_data="stop:no"),
            ]
        ]
    )
