import asyncio
import hashlib
import json
import logging
import re
from datetime import date, timedelta

from sqlalchemy import delete, select, text
from sqlalchemy import update as sql_update

from app.core.config import Settings
from app.core.time import today_moscow
from app.db.seed import seed_reference_data
from app.db.session import make_engine, session_factory
from app.models import Disease, Event, Region, Report, WeeklyCount
from app.services.quarantine import district_key, rebuild_quarantines
from app.services.scoring import level_from_score
from etl.fetch import ReportRef, fetch_since, sha256_of

logger = logging.getLogger(__name__)
_update_lock = asyncio.Lock()


def name_key(value):
    return re.sub(r"[^а-яa-z0-9]", "", value.casefold().replace("ё", "е"))


async def lookup_tables(session):
    regions = {}
    diseases = {}
    for region in (await session.scalars(select(Region))).all():
        for name in [region.name, *region.aliases]:
            regions[name_key(name)] = region
    for disease in (await session.scalars(select(Disease))).all():
        for name in [disease.name, *disease.aliases]:
            diseases[name_key(name)] = disease
    return regions, diseases


def event_fingerprint(item, region, disease):
    payload = [
        region.code,
        disease.slug,
        str(item.date),
        item.kind,
        name_key(item.locality or item.text),
        district_key(item.district),
        sorted(item.species or disease.species),
        sorted(item.source_urls),
    ]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()


async def ingest_daily(session, report, events, issues):
    regions, diseases = await lookup_tables(session)
    warnings = list(issues)
    known = {e.fingerprint: e for e in (await session.scalars(select(Event))).all()}
    inserted = 0
    for item in events:
        region = regions.get(name_key(item.region))
        disease = diseases.get(name_key(item.disease))
        if not region or not disease:
            warnings.append(f"Не сопоставлено: регион «{item.region}», болезнь «{item.disease}»")
            continue
        fingerprint = event_fingerprint(item, region, disease)
        fields = dict(
            report_id=report.id,
            date=item.date,
            region_code=region.code,
            disease_id=disease.id,
            district=item.district,
            locality=item.locality,
            species=item.species or disease.species,
            kind=item.kind,
            text=item.text,
            scores=item.scores,
            total=item.total,
            level=level_from_score(item.total, disease.base_level),
            source_urls=item.source_urls or [report.url],
        )
        previous = known.get(fingerprint)
        if previous:
            previous_report = await session.get(Report, previous.report_id)
            if previous_report.is_current:
                continue
            for key, value in fields.items():
                setattr(previous, key, value)
        else:
            previous = Event(**fields, fingerprint=fingerprint)
            session.add(previous)
            inserted += 1
        known[fingerprint] = previous
    report.issues = warnings
    report.parse_status = "partial" if warnings else "ok"
    await session.flush()
    return {"events": inserted, "issues": warnings}


async def load_report(session, ref: ReportRef, path):
    digest = await asyncio.to_thread(sha256_of, path)
    existing = await session.scalar(select(Report).where(Report.sha256 == digest))
    if existing and existing.is_current:
        return {"skipped": 1, "events": 0, "weekly_counts": 0, "partial": 0, "issues": []}
    # Одна оперативная публикация на дату либо сводная на период: новая версия
    # заменяет производные факты, исходные отчёты и журнал отправок сохраняются.
    criteria = [Report.type == ref.kind]
    if ref.kind == "weekly" and ref.period_from:
        criteria.append(Report.week_start == ref.period_from)
    else:
        criteria.append(Report.date == ref.published)
    await session.execute(sql_update(Report).where(*criteria).values(is_current=False))
    if existing:
        report = existing
        report.is_current = True
        report.url = ref.url
    else:
        report = Report(
            date=ref.published,
            type=ref.kind,
            url=ref.url,
            sha256=digest,
            parse_status="ok",
            week_start=ref.period_from,
            week_end=ref.period_to,
        )
        session.add(report)
    await session.flush()
    if ref.kind == "daily":
        from etl.parse_daily import parse_daily

        parsed = await asyncio.to_thread(parse_daily, path, ref.published)
        result = await ingest_daily(session, report, parsed.events, parsed.issues)
        return {"reports": 1, **result, "partial": int(report.parse_status == "partial")}
    from etl.parse_weekly import parse_weekly

    if not ref.period_from or not ref.period_to:
        report.parse_status = "partial"
        report.issues = ["Не определён период еженедельной сводки"]
        return {"reports": 1, "partial": 1, "issues": report.issues}
    parsed = await asyncio.to_thread(parse_weekly, path, ref.period_from)
    regions, diseases = await lookup_tables(session)
    warnings = list(parsed.issues)
    aggregates = {}
    for item in parsed.counts:
        region = regions.get(name_key(item.region))
        disease = diseases.get(name_key(item.disease))
        if not region or not disease:
            warnings.append(f"Не сопоставлено: регион «{item.region}», болезнь «{item.disease}»")
            continue
        key = (disease.id, region.code, item.kind)
        current = aggregates.setdefault(key, {"count": 0, "species": set()})
        current["count"] += item.count
        current["species"].update(item.species or disease.species)
    await session.execute(delete(WeeklyCount).where(WeeklyCount.week_start == ref.period_from))
    for (disease_id, region_code, kind), value in aggregates.items():
        row = await session.scalar(
            select(WeeklyCount).where(
                WeeklyCount.week_start == ref.period_from,
                WeeklyCount.disease_id == disease_id,
                WeeklyCount.region_code == region_code,
                WeeklyCount.kind == kind,
            )
        )
        fields = dict(
            report_id=report.id,
            week_end=ref.period_to,
            count=value["count"],
            species=sorted(value["species"]),
        )
        if row:
            for key, val in fields.items():
                setattr(row, key, val)
        else:
            session.add(
                WeeklyCount(
                    week_start=ref.period_from,
                    disease_id=disease_id,
                    region_code=region_code,
                    kind=kind,
                    **fields,
                )
            )
    report.issues = warnings
    report.parse_status = "partial" if warnings else "ok"
    await session.flush()
    return {
        "reports": 1,
        "weekly_counts": len(aggregates),
        "partial": int(bool(warnings)),
        "issues": warnings,
    }


async def update(session, since, cache_dir):
    refs = await fetch_since(since, cache_dir)
    result = {
        "reports": 0,
        "events": 0,
        "weekly_counts": 0,
        "skipped": 0,
        "partial": 0,
        "issues": [],
    }
    result["issues"].extend(getattr(refs, "issues", []))
    result["partial"] += len(getattr(refs, "issues", []))
    for ref, path in sorted(refs, key=lambda pair: pair[0].published):
        try:
            async with session.begin_nested():
                item = await load_report(session, ref, path)
            for key, value in item.items():
                if key == "issues":
                    result[key].extend(f"{path.name}: {warning}" for warning in value)
                else:
                    result[key] += value
        except Exception as error:
            logger.warning("Не удалось загрузить %s (%s)", path.name, type(error).__name__)
            result["partial"] += 1
            result["issues"].append(f"{path.name}: ошибка {type(error).__name__}")
    await rebuild_quarantines(session, today_moscow())
    return result


async def run_update(settings: Settings, since: date | None = None, cache_dir=None):
    if _update_lock.locked():
        return {"issues": ["Обновление уже выполняется"]}
    async with _update_lock:
        engine = make_engine(settings.database_url)
        try:
            async with session_factory(engine)() as session:
                if engine.dialect.name == "postgresql":
                    locked = await session.scalar(text("SELECT pg_try_advisory_xact_lock(824013)"))
                    if not locked:
                        return {"issues": ["Обновление уже выполняется в другом процессе"]}
                await seed_reference_data(session, settings.data_dir)
                result = await update(
                    session,
                    since or today_moscow() - timedelta(days=settings.etl_lookback_days),
                    cache_dir or settings.data_dir / "cache",
                )
                from etl.news import load_news

                try:
                    async with session.begin_nested():
                        await load_news(session)
                except Exception as error:
                    result["issues"].append(f"RSS: ошибка {type(error).__name__}")
                await session.commit()
                return result
        finally:
            await engine.dispose()
