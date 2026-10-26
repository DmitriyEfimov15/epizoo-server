import re
from datetime import date

from rapidfuzz.fuzz import ratio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import today_moscow
from app.models import Event, Quarantine, Report


def locality_key(value: str | None) -> str:
    if not value:
        return ""
    value = value.casefold().replace("ё", "е")
    value = re.sub(r"\b(?:деревня|село|поселок|город|д|с|п|г)\.?\s+", "", value)
    return re.sub(r"[^а-яa-z0-9]+", " ", value).strip()


def district_key(value: str | None) -> str:
    if not value:
        return ""
    value = value.casefold().replace("ё", "е")
    value = re.sub(r"\bм\s*\.\s*[ор]\s*\.?|\bр[-.]н\b", " ", value)
    words = re.findall(r"[а-яa-z0-9]+", value)
    words = [
        w for w in words if not re.fullmatch(r"(?:муниципальн\w*|район\w*|округ\w*|городск\w*)", w)
    ]
    return " ".join(re.sub(r"(?:ого|ому|ыми|ыми|ий|ая|ой|ом|ые|ых)$", "", w) for w in words)


async def rebuild_quarantines(session: AsyncSession, today: date | None = None) -> None:
    today = today or today_moscow()
    events = (
        await session.scalars(
            select(Event)
            .join(Report)
            .where(Report.is_current.is_(True), Event.kind != "outbreak")
            .order_by(Event.date, Event.id)
        )
    ).all()
    await session.execute(delete(Quarantine))
    rows: list[Quarantine] = []
    by_id = {e.id: e for e in events}
    for item in events:
        key = locality_key(item.locality)
        candidates = [
            q
            for q in rows
            if q.status != "lifted"
            and q.disease_id == item.disease_id
            and q.region_code == item.region_code
        ]
        if item.district:
            candidates = [
                q
                for q in candidates
                if district_key(by_id[q.set_event_id].district) == district_key(item.district)
            ]
        exact = [q for q in candidates if key and q.locality_norm == key]
        if item.kind == "quarantine_set":
            exact = [
                q
                for q in exact
                if district_key(by_id[q.set_event_id].district) == district_key(item.district)
            ]
        if item.kind == "quarantine_lifted":
            matches = exact or [
                q
                for q in candidates
                if key
                and q.locality_norm
                and re.findall(r"\d+", key) == re.findall(r"\d+", q.locality_norm)
                and ratio(key, q.locality_norm) >= 95
            ]
            if len(matches) == 1:
                matches[0].status = "lifted"
                matches[0].until = item.date
                matches[0].lifted_event_id = item.id
        elif not exact:
            row = Quarantine(
                set_event_id=item.id,
                disease_id=item.disease_id,
                region_code=item.region_code,
                locality_norm=key,
                status="active",
                since=item.date,
            )
            rows.append(row)
    for row in rows:
        if row.status == "active" and (today - row.since).days >= 90:
            row.status = "unconfirmed"
    session.add_all(rows)
    await session.flush()
