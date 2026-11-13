# -*- coding: utf-8 -*-
"""统一预设值表：题材 / 枚举 / 分类 / 标签集中入库，供 /presets 与后台维护使用。"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "l2e3f4a5b6c7"
down_revision = "k1d2e3f4a5b6"
branch_labels = None
depends_on = None

BIGINT = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "presets",
        sa.Column("id", BIGINT, primary_key=True, autoincrement=True),
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column("value", sa.String(128), nullable=False),
        sa.Column("label", sa.String(128), nullable=True),
        sa.Column("audience", sa.String(32), nullable=False, server_default="all"),
        sa.Column("sort", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("builtin", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("account_id", BIGINT, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("type", "value", "account_id", name="uq_preset_type_value_account"),
    )
    op.create_index("ix_presets_type", "presets", ["type"])
    op.create_index("ix_presets_account_id", "presets", ["account_id"])


def downgrade() -> None:
    op.drop_index("ix_presets_account_id", table_name="presets")
    op.drop_index("ix_presets_type", table_name="presets")
    op.drop_table("presets")
