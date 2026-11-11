# -*- coding: utf-8 -*-
"""credits & notifications: credit packs/grants, notification channels"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB, "postgresql")
BIGINT = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "credit_packs",
        sa.Column("id", BIGINT, primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("metric", sa.String(64), nullable=False),
        sa.Column("quantity", BIGINT, nullable=False),
        sa.Column("price_cents", BIGINT, nullable=False),
        sa.Column("currency", sa.String(8), nullable=False, server_default="CNY"),
        sa.Column("validity_days", sa.Integer(), nullable=False, server_default="365"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "credit_grants",
        sa.Column("id", BIGINT, primary_key=True, autoincrement=True),
        sa.Column("account_id", BIGINT, sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("pack_id", BIGINT, sa.ForeignKey("credit_packs.id"), nullable=True),
        sa.Column("order_id", BIGINT, sa.ForeignKey("orders.id"), nullable=True),
        sa.Column("metric", sa.String(64), nullable=False),
        sa.Column("quantity_granted", BIGINT, nullable=False),
        sa.Column("quantity_used", BIGINT, nullable=False, server_default="0"),
        sa.Column("quantity_reserved", BIGINT, nullable=False, server_default="0"),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("meta", JSON_TYPE, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("account_id", "idempotency_key", name="uq_credit_grants_account_idem"),
    )
    op.create_index("idx_credit_grants_account_expiry", "credit_grants", ["account_id", "metric", "expires_at"])
    op.create_index("ix_credit_grants_account_id", "credit_grants", ["account_id"])
    op.create_index(
        "uq_credit_grants_order", "credit_grants", ["order_id"], unique=True,
        sqlite_where=sa.text("order_id IS NOT NULL"),
        postgresql_where=sa.text("order_id IS NOT NULL"),
    )

    op.create_table(
        "notifications",
        sa.Column("id", BIGINT, primary_key=True, autoincrement=True),
        sa.Column("account_id", BIGINT, sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("level", sa.String(16), nullable=False, server_default="info"),
        sa.Column("status", sa.String(16), nullable=False, server_default="unread"),
        sa.Column("dedupe_key", sa.String(200), nullable=False),
        sa.Column("meta", JSON_TYPE, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("account_id", "dedupe_key", name="uq_notifications_account_dedupe"),
    )
    op.create_index("idx_notifications_account_time", "notifications", ["account_id", "created_at"])

    op.create_table(
        "notification_deliveries",
        sa.Column("id", BIGINT, primary_key=True, autoincrement=True),
        sa.Column("notification_id", BIGINT, sa.ForeignKey("notifications.id"), nullable=True),
        sa.Column("account_id", BIGINT, sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("recipient", sa.String(255), nullable=True),
        sa.Column("subject", sa.String(200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("last_error", sa.String(255), nullable=True),
        sa.Column("provider_message_id", sa.String(128), nullable=True),
        sa.Column("dedupe_key", sa.String(200), nullable=False),
        sa.Column("meta", JSON_TYPE, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("channel", "dedupe_key", name="uq_delivery_channel_dedupe"),
    )
    op.create_index("idx_delivery_status_retry", "notification_deliveries", ["status", "next_retry_at"])
    op.create_index("ix_notification_deliveries_account_id", "notification_deliveries", ["account_id"])

    # 额度包订单没有套餐：plan_id 允许为空，新增 pack_id
    with op.batch_alter_table("orders") as batch:
        batch.alter_column("plan_id", existing_type=sa.BigInteger(), nullable=True)
        batch.add_column(sa.Column("pack_id", BIGINT, nullable=True))
        batch.create_foreign_key("fk_orders_pack", "credit_packs", ["pack_id"], ["id"])

    # 任务预占拆分：套餐 / 额度包
    with op.batch_alter_table("tasks") as batch:
        batch.add_column(sa.Column("reserved_plan_quantity", BIGINT, nullable=False, server_default="0"))
        batch.add_column(sa.Column("reserved_pack_items", JSON_TYPE, nullable=False, server_default=sa.text("'[]'")))


def downgrade() -> None:
    with op.batch_alter_table("tasks") as batch:
        batch.drop_column("reserved_pack_items")
        batch.drop_column("reserved_plan_quantity")
    with op.batch_alter_table("orders") as batch:
        batch.drop_constraint("fk_orders_pack", type_="foreignkey")
        batch.drop_column("pack_id")
        batch.alter_column("plan_id", existing_type=sa.BigInteger(), nullable=False)
    op.drop_table("notification_deliveries")
    op.drop_table("notifications")
    op.drop_table("credit_grants")
    op.drop_table("credit_packs")
