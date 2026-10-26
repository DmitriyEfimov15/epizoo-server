from collections import defaultdict
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import invalid, not_found
from app.db.session import get_session
from app.models import RouteCheck
from app.schemas.api import (
    SPECIES,
    DiseaseOut,
    EventPage,
    HistoryPoint,
    Kind,
    MapRegion,
    MetaOut,
    OfferOut,
    RegionOut,
    RegionRef,
    RouteResult,
    SpeciesRef,
    SummaryOut,
)
from app.services.monitoring import Monitor
from app.services.offers import select_offers
from app.services.route_check import check_route
from app.services.summaries import region_summary
from etl.fetch import INDEX_URL

router = APIRouter()
Session = Annotated[AsyncSession, Depends(get_session)]
Period = Annotated[int, Query(ge=1, le=365)]


@router.get("/meta", response_model=MetaOut)
async def meta(session: Session):
    monitor = await Monitor.load(session)
    reports = monitor.reports
    return MetaOut(
        last_report_date=max((r.date for r in reports), default=None),
        first_report_date=min((r.date for r in reports), default=None),
        updated_at=max((r.parsed_at for r in reports), default=None),
        report_count=len(reports),
        partial_report_count=sum(r.parse_status != "ok" for r in reports),
        source_url=INDEX_URL,
        disclaimer=(
            "Данные по сообщениям ветслужб и СМИ. Отсутствие сообщений не подтверждает "
            "отсутствие заболевания; ограничения уточняйте у ветслужбы."
        ),
    )


@router.get("/refs/regions", response_model=list[RegionRef])
async def regions_ref(session: Session):
    return sorted((await Monitor.load(session)).regions.values(), key=lambda r: r.name)


@router.get("/refs/species", response_model=list[SpeciesRef])
async def species_ref():
    return [SpeciesRef(slug=slug, name=name) for slug, name in SPECIES.items()]


@router.get("/refs/diseases", response_model=list[DiseaseOut])
@router.get("/diseases", response_model=list[DiseaseOut])
async def diseases(session: Session, species: str | None = None):
    monitor = await Monitor.load(session)
    monitor.check_filters(species)
    return sorted(
        [d for d in monitor.diseases.values() if not species or species in d.species],
        key=lambda d: d.name,
    )


@router.get("/diseases/{slug}", response_model=DiseaseOut)
async def disease(slug: str, session: Session):
    monitor = await Monitor.load(session)
    if slug not in monitor.by_slug:
        raise not_found("Болезнь не найдена")
    return monitor.by_slug[slug]


@router.get("/map", response_model=list[MapRegion])
async def map_data(
    session: Session, species: str | None = None, disease: str | None = None, period: Period = 30
):
    monitor = await Monitor.load(session)
    monitor.check_filters(species, disease)
    return [monitor.map_region(code, species, disease, period) for code in sorted(monitor.regions)]


@router.get("/regions/{code}", response_model=RegionOut)
async def region(code: str, session: Session, species: str | None = None, period: Period = 30):
    return (await Monitor.load(session)).region_out(code, species, period=period)


@router.get("/regions/{code}/summary", response_model=SummaryOut)
async def summary(
    code: str, request: Request, session: Session, species: str | None = None, period: Period = 30
):
    return await region_summary(
        session, await Monitor.load(session), code, species, period, request.app.state.settings
    )


@router.get("/regions/{code}/history", response_model=list[HistoryPoint])
async def history(code: str, session: Session, disease: str | None = None):
    monitor = await Monitor.load(session)
    monitor.region(code)
    monitor.check_filters(disease=disease)
    counts = defaultdict(int)
    for row in monitor.weekly_counts:
        if row.region_code == code and (
            not disease or monitor.diseases[row.disease_id].slug == disease
        ):
            counts[(row.week_start, row.week_end, row.kind)] += row.count
    return [
        HistoryPoint(week_start=start, week_end=end, kind=kind, count=count)
        for (start, end, kind), count in sorted(counts.items())
    ]


@router.get("/events", response_model=EventPage)
async def events(
    session: Session,
    region: str | None = None,
    disease: str | None = None,
    species: str | None = None,
    kind: Kind | None = None,
    from_date: Annotated[date | None, Query(alias="from")] = None,
    to_date: Annotated[date | None, Query(alias="to")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
):
    if from_date and to_date and from_date > to_date:
        raise invalid("Дата начала должна быть не позже даты окончания")
    monitor = await Monitor.load(session)
    monitor.check_filters(species, disease)
    if region:
        monitor.region(region)
    rows = monitor.selected_events(region, species, disease, from_date, to_date, kind)
    return EventPage(
        items=[monitor.event_out(e) for e in rows[(page - 1) * page_size : page * page_size]],
        total=len(rows),
        page=page,
        page_size=page_size,
    )


@router.get("/route-check", response_model=RouteResult)
async def route_check(
    session: Session,
    species: str,
    from_code: Annotated[str, Query(alias="from")],
    to_code: Annotated[str, Query(alias="to")],
):
    result = check_route(await Monitor.load(session), from_code, to_code, species)
    session.add(
        RouteCheck(from_code=from_code, to_code=to_code, species=species, verdict=result.verdict)
    )
    return result


@router.get("/offers", response_model=list[OfferOut])
async def offers(request: Request, session: Session, region: str, species: str | None = None):
    return select_offers(
        await Monitor.load(session), region, species, request.app.state.settings.data_dir
    )
