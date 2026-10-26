from datetime import date as DateValue
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

SPECIES = {
    "cattle": "КРС",
    "small_ruminants": "МРС",
    "pigs": "Свиньи",
    "poultry": "Птица",
    "horses": "Лошади",
    "bees": "Пчёлы",
    "rabbits": "Кролики",
    "carnivores": "Плотоядные",
    "wildlife": "Дикие животные",
}
SpeciesSlug = Literal[
    "cattle",
    "small_ruminants",
    "pigs",
    "poultry",
    "horses",
    "bees",
    "rabbits",
    "carnivores",
    "wildlife",
]
Kind = Literal["outbreak", "quarantine_set", "quarantine_lifted"]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ErrorOut(BaseModel):
    code: str
    message: str


class RegionRef(ORMModel):
    code: str
    name: str
    aliases: list[str]
    federal_district: str


class SpeciesRef(BaseModel):
    slug: SpeciesSlug
    name: str


class Recommendation(BaseModel):
    text: str
    source_url: str


class DiseaseOut(ORMModel):
    id: int
    slug: str
    name: str
    aliases: list[str]
    species: list[SpeciesSlug]
    is_zoonosis: bool
    base_level: int
    description: str
    recommendations: list[Recommendation]
    symptoms: list[str]


class EventOut(ORMModel):
    id: int
    report_id: int
    date: DateValue
    disease_id: int
    disease_slug: str
    disease_name: str
    region_code: str
    district: str | None
    locality: str | None
    species: list[SpeciesSlug]
    kind: Kind
    text: str
    scores: list[int]
    total: float | None
    level: int
    source_urls: list[str]


class QuarantineOut(ORMModel):
    id: int
    set_event_id: int
    disease_id: int
    disease_slug: str
    disease_name: str
    region_code: str
    locality: str | None
    species: list[SpeciesSlug]
    status: Literal["active", "unconfirmed"]
    since: DateValue
    until: DateValue | None
    level: int
    source_urls: list[str]


class MapRegion(BaseModel):
    code: str
    name: str
    level: int
    event_count: int
    active_quarantine_count: int
    unconfirmed_quarantine_count: int


class RegionOut(MapRegion):
    quarantines: list[QuarantineOut]
    events: list[EventOut]
    neighbors: list[MapRegion]


class EventPage(BaseModel):
    items: list[EventOut]
    total: int
    page: int
    page_size: int


class SummaryOut(BaseModel):
    text: str
    provider: str
    source_urls: list[str]
    created_at: datetime


class HistoryPoint(BaseModel):
    week_start: DateValue
    week_end: DateValue
    kind: Kind
    count: int


class MetaOut(BaseModel):
    last_report_date: DateValue | None
    updated_at: datetime | None
    report_count: int
    partial_report_count: int
    first_report_date: DateValue | None
    source_url: str
    disclaimer: str


class FarmIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    region_code: str = Field(min_length=2, max_length=3)
    district: str | None = Field(default=None, max_length=200)
    species: list[SpeciesSlug] = Field(min_length=1, max_length=9)


class FarmOut(ORMModel):
    token: UUID
    region_code: str
    district: str | None
    species: list[SpeciesSlug]
    created_at: datetime


class SubscriptionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    min_level: int = Field(default=3, ge=1, le=5)
    include_neighbors: bool = True
    digest_enabled: bool = True


class SubscriptionOut(ORMModel):
    id: int
    min_level: int
    include_neighbors: bool
    digest_enabled: bool
    chat_id: int | None


class TelegramLink(BaseModel):
    url: str


class OfferOut(BaseModel):
    id: str
    title: str
    description: str
    url: str


class DigestOut(BaseModel):
    week_start: DateValue
    week_end: DateValue
    text: str
    events: list[EventOut]
    source_urls: list[str]
    recommendations: list[Recommendation]


class DashboardOut(BaseModel):
    farm: FarmOut
    region: RegionOut
    neighbors: list[MapRegion]
    recommendations: list[Recommendation]
    offers: list[OfferOut]
    subscription: SubscriptionOut | None


class RouteResult(BaseModel):
    from_region: RegionOut
    to_region: RegionOut
    species: SpeciesSlug
    verdict: Literal["low", "elevated", "high"]
    checklist: list[str]
    official_url: str
    disclaimer: str


class ETLResult(BaseModel):
    reports: int = 0
    events: int = 0
    weekly_counts: int = 0
    skipped: int = 0
    partial: int = 0
    issues: list[str] = Field(default_factory=list)
