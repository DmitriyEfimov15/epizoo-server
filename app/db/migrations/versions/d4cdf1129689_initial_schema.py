"""Начальная схема мониторинга

Revision ID: d4cdf1129689
Revises:
Create Date: 2026-10-14 00:59:23.586875

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Идентификаторы ревизии Alembic.
revision: str = "d4cdf1129689"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Начальная схема, сгенерированная Alembic.
    op.create_table(
        "diseases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("aliases", sa.JSON(), nullable=False),
        sa.Column("species", sa.JSON(), nullable=False),
        sa.Column("is_zoonosis", sa.Boolean(), nullable=False),
        sa.Column("base_level", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("recommendations", sa.JSON(), nullable=False),
        sa.Column("symptoms", sa.JSON(), nullable=False),
        sa.CheckConstraint("base_level BETWEEN 1 AND 5", name=op.f("ck_diseases_base_level_range")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_diseases")),
        sa.UniqueConstraint("slug", name=op.f("uq_diseases_slug")),
    )
    op.create_table(
        "regions",
        sa.Column("code", sa.String(length=3), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("aliases", sa.JSON(), nullable=False),
        sa.Column("federal_district", sa.String(length=60), nullable=False),
        sa.PrimaryKeyConstraint("code", name=op.f("pk_regions")),
        sa.UniqueConstraint("name", name=op.f("uq_regions_name")),
    )
    op.create_table(
        "reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("type", sa.String(length=12), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("parse_status", sa.String(length=16), nullable=False),
        sa.Column("parsed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("issues", sa.JSON(), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=True),
        sa.Column("week_end", sa.Date(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reports")),
        sa.UniqueConstraint("sha256", name=op.f("uq_reports_sha256")),
    )
    op.create_index(op.f("ix_reports_date"), "reports", ["date"], unique=False)
    op.create_table(
        "summaries",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("provider", sa.String(length=24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_summaries")),
    )
    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("report_id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("disease_id", sa.Integer(), nullable=False),
        sa.Column("region_code", sa.String(length=3), nullable=False),
        sa.Column("district", sa.String(length=500), nullable=True),
        sa.Column("locality", sa.Text(), nullable=True),
        sa.Column("species", sa.JSON(), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("scores", sa.JSON(), nullable=False),
        sa.Column("total", sa.Float(), nullable=True),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("source_urls", sa.JSON(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            "kind IN ('outbreak','quarantine_set','quarantine_lifted')",
            name=op.f("ck_events_event_kind"),
        ),
        sa.CheckConstraint("level BETWEEN 1 AND 5", name=op.f("ck_events_event_level_range")),
        sa.ForeignKeyConstraint(
            ["disease_id"], ["diseases.id"], name=op.f("fk_events_disease_id_diseases")
        ),
        sa.ForeignKeyConstraint(
            ["region_code"], ["regions.code"], name=op.f("fk_events_region_code_regions")
        ),
        sa.ForeignKeyConstraint(
            ["report_id"], ["reports.id"], name=op.f("fk_events_report_id_reports")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_events")),
        sa.UniqueConstraint("fingerprint", name=op.f("uq_events_fingerprint")),
    )
    op.create_index(op.f("ix_events_date"), "events", ["date"], unique=False)
    op.create_index(op.f("ix_events_disease_id"), "events", ["disease_id"], unique=False)
    op.create_index(op.f("ix_events_region_code"), "events", ["region_code"], unique=False)
    op.create_index("ix_events_region_date", "events", ["region_code", "date"], unique=False)
    op.create_index(op.f("ix_events_report_id"), "events", ["report_id"], unique=False)
    op.create_table(
        "farms",
        sa.Column("token", sa.String(length=36), nullable=False),
        sa.Column("region_code", sa.String(length=3), nullable=False),
        sa.Column("district", sa.String(length=200), nullable=True),
        sa.Column("species", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["region_code"], ["regions.code"], name=op.f("fk_farms_region_code_regions")
        ),
        sa.PrimaryKeyConstraint("token", name=op.f("pk_farms")),
    )
    op.create_table(
        "news",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("region_code", sa.String(length=3), nullable=True),
        sa.Column("disease_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["disease_id"], ["diseases.id"], name=op.f("fk_news_disease_id_diseases")
        ),
        sa.ForeignKeyConstraint(
            ["region_code"], ["regions.code"], name=op.f("fk_news_region_code_regions")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_news")),
        sa.UniqueConstraint("url", name=op.f("uq_news_url")),
    )
    op.create_index(op.f("ix_news_date"), "news", ["date"], unique=False)
    op.create_table(
        "region_neighbors",
        sa.Column("region_code", sa.String(length=3), nullable=False),
        sa.Column("neighbor_code", sa.String(length=3), nullable=False),
        sa.CheckConstraint(
            "region_code != neighbor_code", name=op.f("ck_region_neighbors_distinct_regions")
        ),
        sa.ForeignKeyConstraint(
            ["neighbor_code"],
            ["regions.code"],
            name=op.f("fk_region_neighbors_neighbor_code_regions"),
        ),
        sa.ForeignKeyConstraint(
            ["region_code"], ["regions.code"], name=op.f("fk_region_neighbors_region_code_regions")
        ),
        sa.PrimaryKeyConstraint("region_code", "neighbor_code", name=op.f("pk_region_neighbors")),
    )
    op.create_table(
        "route_checks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("from_code", sa.String(length=3), nullable=False),
        sa.Column("to_code", sa.String(length=3), nullable=False),
        sa.Column("species", sa.String(length=40), nullable=False),
        sa.Column("verdict", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["from_code"], ["regions.code"], name=op.f("fk_route_checks_from_code_regions")
        ),
        sa.ForeignKeyConstraint(
            ["to_code"], ["regions.code"], name=op.f("fk_route_checks_to_code_regions")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_route_checks")),
    )
    op.create_table(
        "weekly_counts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("report_id", sa.Integer(), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("week_end", sa.Date(), nullable=False),
        sa.Column("disease_id", sa.Integer(), nullable=False),
        sa.Column("region_code", sa.String(length=3), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("species", sa.JSON(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["disease_id"], ["diseases.id"], name=op.f("fk_weekly_counts_disease_id_diseases")
        ),
        sa.ForeignKeyConstraint(
            ["region_code"], ["regions.code"], name=op.f("fk_weekly_counts_region_code_regions")
        ),
        sa.ForeignKeyConstraint(
            ["report_id"], ["reports.id"], name=op.f("fk_weekly_counts_report_id_reports")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_weekly_counts")),
        sa.UniqueConstraint(
            "week_start",
            "disease_id",
            "region_code",
            "kind",
            name=op.f("uq_weekly_counts_week_start"),
        ),
    )
    op.create_index(
        op.f("ix_weekly_counts_week_start"), "weekly_counts", ["week_start"], unique=False
    )
    op.create_table(
        "quarantines",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("set_event_id", sa.Integer(), nullable=False),
        sa.Column("lifted_event_id", sa.Integer(), nullable=True),
        sa.Column("disease_id", sa.Integer(), nullable=False),
        sa.Column("region_code", sa.String(length=3), nullable=False),
        sa.Column("locality_norm", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("since", sa.Date(), nullable=False),
        sa.Column("until", sa.Date(), nullable=True),
        sa.CheckConstraint(
            "status IN ('active','lifted','unconfirmed')",
            name=op.f("ck_quarantines_quarantine_status"),
        ),
        sa.ForeignKeyConstraint(
            ["disease_id"], ["diseases.id"], name=op.f("fk_quarantines_disease_id_diseases")
        ),
        sa.ForeignKeyConstraint(
            ["lifted_event_id"], ["events.id"], name=op.f("fk_quarantines_lifted_event_id_events")
        ),
        sa.ForeignKeyConstraint(
            ["region_code"], ["regions.code"], name=op.f("fk_quarantines_region_code_regions")
        ),
        sa.ForeignKeyConstraint(
            ["set_event_id"], ["events.id"], name=op.f("fk_quarantines_set_event_id_events")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quarantines")),
        sa.UniqueConstraint("set_event_id", name=op.f("uq_quarantines_set_event_id")),
    )
    op.create_index(op.f("ix_quarantines_disease_id"), "quarantines", ["disease_id"], unique=False)
    op.create_index(
        op.f("ix_quarantines_region_code"), "quarantines", ["region_code"], unique=False
    )
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("farm_token", sa.String(length=36), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=True),
        sa.Column("min_level", sa.Integer(), nullable=False),
        sa.Column("include_neighbors", sa.Boolean(), nullable=False),
        sa.Column("digest_enabled", sa.Boolean(), nullable=False),
        sa.Column("last_digest_week", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "min_level BETWEEN 1 AND 5", name=op.f("ck_subscriptions_min_level_range")
        ),
        sa.ForeignKeyConstraint(
            ["farm_token"],
            ["farms.token"],
            name=op.f("fk_subscriptions_farm_token_farms"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_subscriptions")),
        sa.UniqueConstraint("chat_id", name=op.f("uq_subscriptions_chat_id")),
        sa.UniqueConstraint("farm_token", name=op.f("uq_subscriptions_farm_token")),
    )
    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("subscription_id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["event_id"], ["events.id"], name=op.f("fk_notifications_event_id_events")
        ),
        sa.ForeignKeyConstraint(
            ["subscription_id"],
            ["subscriptions.id"],
            name=op.f("fk_notifications_subscription_id_subscriptions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
        sa.UniqueConstraint(
            "subscription_id", "event_id", name=op.f("uq_notifications_subscription_id")
        ),
    )
    # Конец миграции.


def downgrade() -> None:
    """Downgrade schema."""
    # Начальная схема, сгенерированная Alembic.
    op.drop_table("notifications")
    op.drop_table("subscriptions")
    op.drop_index(op.f("ix_quarantines_region_code"), table_name="quarantines")
    op.drop_index(op.f("ix_quarantines_disease_id"), table_name="quarantines")
    op.drop_table("quarantines")
    op.drop_index(op.f("ix_weekly_counts_week_start"), table_name="weekly_counts")
    op.drop_table("weekly_counts")
    op.drop_table("route_checks")
    op.drop_table("region_neighbors")
    op.drop_index(op.f("ix_news_date"), table_name="news")
    op.drop_table("news")
    op.drop_table("farms")
    op.drop_index(op.f("ix_events_report_id"), table_name="events")
    op.drop_index("ix_events_region_date", table_name="events")
    op.drop_index(op.f("ix_events_region_code"), table_name="events")
    op.drop_index(op.f("ix_events_disease_id"), table_name="events")
    op.drop_index(op.f("ix_events_date"), table_name="events")
    op.drop_table("events")
    op.drop_table("summaries")
    op.drop_index(op.f("ix_reports_date"), table_name="reports")
    op.drop_table("reports")
    op.drop_table("regions")
    op.drop_table("diseases")
    # Конец миграции.
