# -*- coding: utf-8 -*-
"""账号注销申请：宽限期 + 到期统一清除。"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "q6a7b8c9d0e1"
down_revision = "p5f6a7b8c9d0"
branch_labels = None
depends_on = None

BIGINT = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
JSON_TYPE = sa.JSON().with_variant(JSONB, "postgresql")


def upgrade() -> None:
    op.create_table(
        "account_deletion_requests",
        sa.Column("id", BIGINT, primary_key=True, autoincrement=True),
        sa.Column("account_id", BIGINT, sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("reason", sa.String(255), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("purge_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("meta", JSON_TYPE, nullable=False),
    )
    op.create_index(
        "idx_account_deletions_purge",
        "account_deletion_requests",
        ["status", "purge_at"],
        unique=False,
    )
    op.create_index(
        "ix_account_deletion_requests_account_id",
        "account_deletion_requests",
        ["account_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_account_deletion_requests_account_id", table_name="account_deletion_requests")
    op.drop_index("idx_account_deletions_purge", table_name="account_deletion_requests")
    op.drop_table("account_deletion_requests")
