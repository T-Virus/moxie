# -*- coding: utf-8 -*-
"""邮箱验证：email_verifications 表 + accounts.email_verified_at"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "i9c0d1e2f3a4"
down_revision = "h8c9d0e1f2a3"
branch_labels = None
depends_on = None

BIGINT = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.add_column(
        "accounts",
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "email_verifications",
        sa.Column("id", BIGINT, primary_key=True, autoincrement=True),
        sa.Column("account_id", BIGINT, sa.ForeignKey("accounts.id"), nullable=False, index=True),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("token_hash", name="uq_email_verifications_token_hash"),
    )


def downgrade() -> None:
    op.drop_table("email_verifications")
    op.drop_column("accounts", "email_verified_at")
