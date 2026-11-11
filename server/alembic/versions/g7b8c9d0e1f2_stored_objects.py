# -*- coding: utf-8 -*-
"""object storage in database: stored_objects"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "g7b8c9d0e1f2"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None

BIGINT = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "stored_objects",
        sa.Column("key", sa.String(255), primary_key=True),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column(
            "content_type",
            sa.String(120),
            nullable=False,
            server_default="application/octet-stream",
        ),
        sa.Column("size", BIGINT, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("stored_objects")
