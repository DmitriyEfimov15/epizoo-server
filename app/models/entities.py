from datetime import UTC, datetime
from datetime import date as DateValue
from uuid import uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def now() -> datetime:
    return datetime.now(UTC)


class Region(Base):
    __tablename__ = "regions"
    code: Mapped[str] = mapped_column(String(3), primary_key=True)
    name: Mapped[str] = mapped_column(String(150), unique=True)
    aliases: Mapped[list[str]] = mapped_column(JSON, default=list)
    federal_district: Mapped[str] = mapped_column(String(60), default="")


class RegionNeighbor(Base):
    __tablename__ = "region_neighbors"
    region_code: Mapped[str] = mapped_column(ForeignKey("regions.code"), primary_key=True)
    neighbor_code: Mapped[str] = mapped_column(ForeignKey("regions.code"), primary_key=True)
    __table_args__ = (CheckConstraint("region_code != neighbor_code", name="distinct_regions"),)


class Disease(Base):
    __tablename__ = "diseases"
    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    aliases: Mapped[list[str]] = mapped_column(JSON, default=list)
    species: Mapped[list[str]] = mapped_column(JSON, default=list)
    is_zoonosis: Mapped[bool] = mapped_column(default=False)
    base_level: Mapped[int] = mapped_column(default=1)
    description: Mapped[str] = mapped_column(Text, default="")
    recommendations: Mapped[list[dict]] = mapped_column(JSON, default=list)
    symptoms: Mapped[list[str]] = mapped_column(JSON, default=list)
    __table_args__ = (CheckConstraint("base_level BETWEEN 1 AND 5", name="base_level_range"),)


class Report(Base):
    __tablename__ = "reports"
    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[DateValue] = mapped_column(Date, index=True)
    type: Mapped[str] = mapped_column(String(12))
    url: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    parse_status: Mapped[str] = mapped_column(String(16))
    parsed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    issues: Mapped[list[str]] = mapped_column(JSON, default=list)
    is_current: Mapped[bool] = mapped_column(default=True, server_default=true(), index=True)
    week_start: Mapped[DateValue | None] = mapped_column(Date)
    week_end: Mapped[DateValue | None] = mapped_column(Date)


class Event(Base):
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("reports.id"), index=True)
    date: Mapped[DateValue] = mapped_column(Date, index=True)
    disease_id: Mapped[int] = mapped_column(ForeignKey("diseases.id"), index=True)
    region_code: Mapped[str] = mapped_column(ForeignKey("regions.code"), index=True)
    district: Mapped[str | None] = mapped_column(String(500))
    locality: Mapped[str | None] = mapped_column(Text)
    species: Mapped[list[str]] = mapped_column(JSON, default=list)
    kind: Mapped[str] = mapped_column(String(24))
    text: Mapped[str] = mapped_column(Text)
    scores: Mapped[list[int]] = mapped_column(JSON, default=list)
    total: Mapped[float | None] = mapped_column(Float)
    level: Mapped[int] = mapped_column(Integer)
    source_urls: Mapped[list[str]] = mapped_column(JSON, default=list)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True)
    __table_args__ = (
        CheckConstraint("level BETWEEN 1 AND 5", name="event_level_range"),
        CheckConstraint(
            "kind IN ('outbreak','quarantine_set','quarantine_lifted')", name="event_kind"
        ),
        Index("ix_events_region_date", "region_code", "date"),
    )


class Quarantine(Base):
    __tablename__ = "quarantines"
    id: Mapped[int] = mapped_column(primary_key=True)
    set_event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), unique=True)
    lifted_event_id: Mapped[int | None] = mapped_column(ForeignKey("events.id"))
    disease_id: Mapped[int] = mapped_column(ForeignKey("diseases.id"), index=True)
    region_code: Mapped[str] = mapped_column(ForeignKey("regions.code"), index=True)
    locality_norm: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16))
    since: Mapped[DateValue] = mapped_column(Date)
    until: Mapped[DateValue | None] = mapped_column(Date)
    __table_args__ = (
        CheckConstraint("status IN ('active','lifted','unconfirmed')", name="quarantine_status"),
    )


class WeeklyCount(Base):
    __tablename__ = "weekly_counts"
    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("reports.id"))
    week_start: Mapped[DateValue] = mapped_column(Date, index=True)
    week_end: Mapped[DateValue] = mapped_column(Date)
    disease_id: Mapped[int] = mapped_column(ForeignKey("diseases.id"))
    region_code: Mapped[str] = mapped_column(ForeignKey("regions.code"))
    kind: Mapped[str] = mapped_column(String(24))
    species: Mapped[list[str]] = mapped_column(JSON, default=list)
    count: Mapped[int] = mapped_column(Integer)
    __table_args__ = (UniqueConstraint("week_start", "disease_id", "region_code", "kind"),)


class News(Base):
    __tablename__ = "news"
    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[DateValue] = mapped_column(Date, index=True)
    title: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text, unique=True)
    region_code: Mapped[str | None] = mapped_column(ForeignKey("regions.code"))
    disease_id: Mapped[int | None] = mapped_column(ForeignKey("diseases.id"))


class Summary(Base):
    __tablename__ = "summaries"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    text: Mapped[str] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(String(24))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Farm(Base):
    __tablename__ = "farms"
    token: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    region_code: Mapped[str] = mapped_column(ForeignKey("regions.code"))
    district: Mapped[str | None] = mapped_column(String(200))
    species: Mapped[list[str]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Subscription(Base):
    __tablename__ = "subscriptions"
    id: Mapped[int] = mapped_column(primary_key=True)
    farm_token: Mapped[str] = mapped_column(
        ForeignKey("farms.token", ondelete="CASCADE"), unique=True
    )
    chat_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    min_level: Mapped[int] = mapped_column(default=3)
    include_neighbors: Mapped[bool] = mapped_column(default=True)
    digest_enabled: Mapped[bool] = mapped_column(default=True)
    last_digest_week: Mapped[DateValue | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (CheckConstraint("min_level BETWEEN 1 AND 5", name="min_level_range"),)


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    subscription_id: Mapped[int] = mapped_column(ForeignKey("subscriptions.id", ondelete="CASCADE"))
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"))
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (UniqueConstraint("subscription_id", "event_id"),)


class RouteCheck(Base):
    __tablename__ = "route_checks"
    id: Mapped[int] = mapped_column(primary_key=True)
    from_code: Mapped[str] = mapped_column(ForeignKey("regions.code"))
    to_code: Mapped[str] = mapped_column(ForeignKey("regions.code"))
    species: Mapped[str] = mapped_column(String(40))
    verdict: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
