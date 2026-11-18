# -*- coding: utf-8 -*-
"""Web Push 订阅表：保存浏览器 endpoint + 加密公钥，供服务端推送使用。"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "p5f6a7b8c9d0"
down_revision = "o4e5f6a7b8c9"
branch_labels = None
depends_on = None

BIGINT = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "web_push_subscriptions",
        sa.Column("id", BIGINT, primary_key=True, autoincrement=True),
        sa.Column("account_id", BIGINT, sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("endpoint", sa.String(500), nullable=False),
        sa.Column("p256dh", sa.String(255), nullable=False),
        sa.Column("auth", sa.String(255), nullable=False),
        sa.Column("device_label", sa.String(128), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("endpoint", name="uq_webpush_endpoint"),
    )
    op.create_index(
        "idx_webpush_account_status", "web_push_subscriptions", ["account_id", "status"], unique=False
    )


def downgrade() -> None:
    op.drop_index("idx_webpush_account_status", table_name="web_push_subscriptions")
    op.drop_table("web_push_subscriptions")
