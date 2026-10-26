from datetime import datetime
from zoneinfo import ZoneInfo

MOSCOW = ZoneInfo("Europe/Moscow")


def today_moscow():
    return datetime.now(MOSCOW).date()
