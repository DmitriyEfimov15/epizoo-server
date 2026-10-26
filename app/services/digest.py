from datetime import timedelta

from app.schemas.api import DigestOut


def build_digest(monitor, farm):
    # Завершённая неделя: одинаковый результат для worker в понедельник и веба.
    monday = monitor.today - timedelta(days=monitor.today.weekday())
    start, end = monday - timedelta(days=7), monday - timedelta(days=1)
    codes = [farm.region_code, *monitor.neighbors[farm.region_code]]
    own = monitor.selected_events(farm.region_code, farm.species, start=start, end=end)
    neighbor = [
        e
        for code in codes[1:]
        for e in monitor.selected_events(code, farm.species, start=start, end=end)
    ]
    events = sorted(own + neighbor, key=lambda e: (e.date, e.id), reverse=True)
    lifted = sum(e.kind == "quarantine_lifted" for e in events)
    text = (
        f"Дайджест за {start:%d.%m.%Y}–{end:%d.%m.%Y}. "
        f"{monitor.regions[farm.region_code].name}: сообщений — {len(own)}; "
        f"у соседей — {len(neighbor)}. Снятий карантина — {lifted}."
    )
    return DigestOut(
        week_start=start,
        week_end=end,
        text=text,
        events=[monitor.event_out(e) for e in events],
        source_urls=sorted({url for e in events for url in e.source_urls}),
        recommendations=monitor.recommendations(events),
    )
