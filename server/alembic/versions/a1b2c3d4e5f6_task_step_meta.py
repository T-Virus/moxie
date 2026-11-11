"""task step meta

Revision ID: a1b2c3d4e5f6
Revises: 48def3cadb5b
Create Date: 2026-11-04 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "48def3cadb5b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("task_steps", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "meta",
                sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
                server_default=sa.text("'{}'"),
                nullable=False,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("task_steps", schema=None) as batch_op:
        batch_op.drop_column("meta")
