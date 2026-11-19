# -*- coding: utf-8 -*-
"""忘记密码令牌表：独立的密码重置链路，与邮箱验证分表互不影响。"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "r7b8c9d0e1f2"
down_revision = "q6a7b8c9d0e1"
branch_labels = None
depends_on = None

BIGINT = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", BIGINT, primary_key=True, autoincrement=True),
        sa.Column("account_id", BIGINT, sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_password_reset_tokens_account_id",
        "password_reset_tokens",
        ["account_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_password_reset_tokens_account_id", table_name="password_reset_tokens")
    op.drop_table("password_reset_tokens")
