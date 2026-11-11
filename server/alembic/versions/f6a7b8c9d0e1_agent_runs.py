# -*- coding: utf-8 -*-
"""agent orchestration: runs, node checkpoints, SSE events"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB, "postgresql")
BIGINT = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("account_id", BIGINT, sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("audience", sa.String(16), nullable=False),
        sa.Column("length", sa.String(16), nullable=False),
        sa.Column("genre_id", sa.String(64), nullable=True),
        sa.Column("genre_name", sa.String(60), nullable=False),
        sa.Column("source_key", sa.String(255), nullable=True),
        sa.Column("brief", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("current_stage", sa.String(64), nullable=True),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("reserved_metric", sa.String(64), nullable=True),
        sa.Column("reserved_quantity", BIGINT, nullable=False, server_default="0"),
        sa.Column("reserved_plan_quantity", BIGINT, nullable=False, server_default="0"),
        sa.Column("reserved_pack_items", JSON_TYPE, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_total", BIGINT, nullable=False, server_default="0"),
        sa.Column("cost_cents", BIGINT, nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.String(255), nullable=True),
        sa.Column("meta", JSON_TYPE, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("account_id", "idempotency_key", name="uq_agent_runs_account_idem"),
    )
    op.create_index("ix_agent_runs_account_id", "agent_runs", ["account_id"])
    op.create_index("idx_agent_runs_account_time", "agent_runs", ["account_id", "created_at"])
    op.create_index("idx_agent_runs_status", "agent_runs", ["status"])

    op.create_table(
        "agent_run_steps",
        sa.Column("run_id", sa.String(36), sa.ForeignKey("agent_runs.id"), primary_key=True),
        sa.Column("node_key", sa.String(64), primary_key=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output", JSON_TYPE, nullable=True),
        sa.Column("error", sa.String(255), nullable=True),
        sa.Column("meta", JSON_TYPE, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "agent_run_events",
        sa.Column("run_id", sa.String(36), sa.ForeignKey("agent_runs.id"), primary_key=True),
        sa.Column("seq", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("stage", sa.String(64), nullable=False),
        sa.Column("level", sa.String(16), nullable=False, server_default="info"),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("agent_run_events")
    op.drop_table("agent_run_steps")
    op.drop_index("idx_agent_runs_status", table_name="agent_runs")
    op.drop_index("idx_agent_runs_account_time", table_name="agent_runs")
    op.drop_index("ix_agent_runs_account_id", table_name="agent_runs")
    op.drop_table("agent_runs")
