# -*- coding: utf-8 -*-
"""运营配置表：Sentry 采样率/去重窗口等后台可热改参数。"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "o4e5f6a7b8c9"
down_revision = "n3f4a5b6c7d8e"
branch_labels = None
depends_on = None

BIGINT = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
JSON_TYPE = sa.JSON().with_variant(JSONB, "postgresql")


def upgrade() -> None:
    op.create_table(
        "operational_settings",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("value", JSON_TYPE, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", BIGINT, nullable=True),
    )


def downgrade() -> None:
    op.drop_table("operational_settings")
