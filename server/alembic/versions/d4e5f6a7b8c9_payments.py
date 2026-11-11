# -*- coding: utf-8 -*-
"""payments: order fields, webhook audit fields, refunds, reconcile, invoices"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "d4e5f6a7b8c9"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB, "postgresql")
BIGINT = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    with op.batch_alter_table("orders") as batch:
        batch.add_column(sa.Column("external_order_no", sa.String(64), nullable=True))
        batch.add_column(sa.Column("refunded_cents", BIGINT, nullable=False, server_default="0"))
        batch.add_column(sa.Column("failure_reason", sa.String(255), nullable=True))
        batch.add_column(sa.Column("meta", JSON_TYPE, nullable=False, server_default=sa.text("'{}'")))
        batch.add_column(sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.text("CURRENT_TIMESTAMP"))
        )
        batch.create_index(
            "uq_orders_external_no",
            ["provider", "external_order_no"],
            unique=True,
            sqlite_where=sa.text("external_order_no IS NOT NULL"),
            postgresql_where=sa.text("external_order_no IS NOT NULL"),
        )

    with op.batch_alter_table("webhook_events") as batch:
        batch.add_column(sa.Column("event_type", sa.String(32), nullable=False, server_default="payment"))
        batch.add_column(sa.Column("signature_valid", sa.Boolean(), nullable=False, server_default=sa.text("false")))
        batch.add_column(sa.Column("process_status", sa.String(16), nullable=False, server_default="received"))
        batch.add_column(sa.Column("error_code", sa.String(64), nullable=True))
        batch.add_column(sa.Column("retryable", sa.Boolean(), nullable=False, server_default=sa.text("false")))
        batch.add_column(sa.Column("raw_digest", sa.String(64), nullable=True))

    op.create_table(
        "refunds",
        sa.Column("id", BIGINT, primary_key=True, autoincrement=True),
        sa.Column("order_id", BIGINT, sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("account_id", BIGINT, sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("amount_cents", BIGINT, nullable=False),
        sa.Column("currency", sa.String(8), nullable=False, server_default="CNY"),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("provider", sa.String(16), nullable=False),
        sa.Column("provider_refund_id", sa.String(128), nullable=True),
        sa.Column("reason", sa.String(255), nullable=True),
        sa.Column("idempotency_key", sa.String(200), nullable=True),
        sa.Column("meta", JSON_TYPE, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("succeeded_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("account_id", "idempotency_key", name="uq_refunds_account_idem"),
    )
    op.create_index("idx_refunds_order", "refunds", ["order_id"])
    op.create_index("ix_refunds_account_id", "refunds", ["account_id"])
    op.create_index(
        "uq_refunds_provider_ref",
        "refunds",
        ["provider", "provider_refund_id"],
        unique=True,
        sqlite_where=sa.text("provider_refund_id IS NOT NULL"),
        postgresql_where=sa.text("provider_refund_id IS NOT NULL"),
    )

    op.create_table(
        "reconcile_reports",
        sa.Column("id", BIGINT, primary_key=True, autoincrement=True),
        sa.Column("provider", sa.String(16), nullable=False),
        sa.Column("biz_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="done"),
        sa.Column("summary", JSON_TYPE, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("items", JSON_TYPE, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("channel_source", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("provider", "biz_date", name="uq_reconcile_provider_date"),
    )

    op.create_table(
        "invoice_requests",
        sa.Column("id", BIGINT, primary_key=True, autoincrement=True),
        sa.Column("order_id", BIGINT, sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("account_id", BIGINT, sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("tax_no", sa.String(64), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("amount_cents", BIGINT, nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="requested"),
        sa.Column("note", sa.String(255), nullable=True),
        sa.Column("admin_id", BIGINT, nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("meta", JSON_TYPE, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("order_id", name="uq_invoice_order"),
    )
    op.create_index("ix_invoice_requests_account_id", "invoice_requests", ["account_id"])


def downgrade() -> None:
    op.drop_table("invoice_requests")
    op.drop_table("reconcile_reports")
    op.drop_table("refunds")
    with op.batch_alter_table("webhook_events") as batch:
        batch.drop_column("raw_digest")
        batch.drop_column("retryable")
        batch.drop_column("error_code")
        batch.drop_column("process_status")
        batch.drop_column("signature_valid")
        batch.drop_column("event_type")
    with op.batch_alter_table("orders") as batch:
        batch.drop_index("uq_orders_external_no")
        batch.drop_column("updated_at")
        batch.drop_column("closed_at")
        batch.drop_column("meta")
        batch.drop_column("failure_reason")
        batch.drop_column("refunded_cents")
        batch.drop_column("external_order_no")
