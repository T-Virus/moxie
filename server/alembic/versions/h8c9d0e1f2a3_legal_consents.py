# -*- coding: utf-8 -*-
"""legal consents: legal_consents"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "h8c9d0e1f2a3"
down_revision = "g7b8c9d0e1f2"
branch_labels = None
depends_on = None

BIGINT = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "legal_consents",
        sa.Column("id", BIGINT, primary_key=True, autoincrement=True),
        sa.Column("account_id", BIGINT, sa.ForeignKey("accounts.id"), nullable=False, index=True),
        sa.Column("consent_type", sa.String(32), nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ip", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.String(255), nullable=True),
        sa.UniqueConstraint("account_id", "consent_type", "version", name="uq_consents_account_type_version"),
    )


def downgrade() -> None:
    op.drop_table("legal_consents")
