# -*- coding: utf-8 -*-
"""工序模型配置表：每个工序模块可独立选择模型/供应商/Key，入库纳管。"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "j0d1e2f3a4b5"
down_revision = "i9c0d1e2f3a4"
branch_labels = None
depends_on = None

BIGINT = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
JSON_TYPE = sa.JSON().with_variant(sa.dialects.postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "model_provider_configs",
        sa.Column("id", BIGINT, primary_key=True, autoincrement=True),
        sa.Column("step_key", sa.String(64), nullable=False),
        sa.Column("label", sa.String(128), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False, server_default="edgeone"),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("base_url", sa.String(512), nullable=False, server_default="https://ai-gateway.edgeone.link/v1"),
        sa.Column("api_key", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("extra", JSON_TYPE, nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", BIGINT, nullable=True),
        sa.UniqueConstraint("step_key", name="uq_model_provider_configs_step_key"),
    )
    op.create_index("ix_model_provider_configs_step_key", "model_provider_configs", ["step_key"])


def downgrade() -> None:
    op.drop_table("model_provider_configs")
