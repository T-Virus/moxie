# -*- coding: utf-8 -*-
"""离线版安装包表：后台上传纳管 Windows / Android 安装包及其版本。"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "k1d2e3f4a5b6"
down_revision = "j0d1e2f3a4b5"
branch_labels = None
depends_on = None

BIGINT = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "offline_packages",
        sa.Column("id", BIGINT, primary_key=True, autoincrement=True),
        sa.Column("platform", sa.String(16), nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("filename", sa.String(200), nullable=False),
        sa.Column("source_key", sa.String(512), nullable=False),
        sa.Column("content_type", sa.String(120), nullable=False, server_default="application/octet-stream"),
        sa.Column("size", BIGINT, nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("release_notes", sa.Text(), nullable=True),
        sa.Column("uploaded_by", BIGINT, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_offline_packages_platform", "offline_packages", ["platform"])


def downgrade() -> None:
    op.drop_table("offline_packages")
