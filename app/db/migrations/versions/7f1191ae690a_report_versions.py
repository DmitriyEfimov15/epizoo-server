"""Текущие версии сводок

Revision ID: 7f1191ae690a
Revises: d4cdf1129689
Create Date: 2026-10-14 17:26:16.468520

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Идентификаторы ревизии Alembic.
revision: str = "7f1191ae690a"
down_revision: str | Sequence[str] | None = "d4cdf1129689"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Добавить признак текущей версии."""
    # Изменение схемы, сгенерированное Alembic.
    op.add_column(
        "reports",
        sa.Column("is_current", sa.Boolean(), server_default=sa.true(), nullable=False),
    )
    op.create_index(op.f("ix_reports_is_current"), "reports", ["is_current"], unique=False)
    # Конец миграции.


def downgrade() -> None:
    """Удалить признак текущей версии."""
    # Изменение схемы, сгенерированное Alembic.
    op.drop_index(op.f("ix_reports_is_current"), table_name="reports")
    op.drop_column("reports", "is_current")
    # Конец миграции.
