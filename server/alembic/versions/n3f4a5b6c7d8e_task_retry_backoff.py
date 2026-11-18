# -*- coding: utf-8 -*-
"""为任务失败重试增加指数退避到点时间 next_retry_at。

失败重试回到 queued 后不再被 worker 秒级领取，而是等待 next_retry_at 到点，
由常驻 scheduler 扫描到点任务统一重新入队，避免密集重投冲击抖动中的上游。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "n3f4a5b6c7d8e"
down_revision = "m2e3f4a5b6c7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("tasks") as batch_op:
        batch_op.add_column(sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_index("idx_tasks_retry_due", ["status", "next_retry_at"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("tasks") as batch_op:
        batch_op.drop_index("idx_tasks_retry_due")
        batch_op.drop_column("next_retry_at")
