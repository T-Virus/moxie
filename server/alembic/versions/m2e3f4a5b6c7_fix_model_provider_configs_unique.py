# -*- coding: utf-8 -*-
"""对齐 model_provider_configs.step_key 的唯一约束形态与 ORM 模型。

原迁移 j0d1e2f3a4b5 建了一个命名 UniqueConstraint(uq_...)
加一个非唯一 Index(ix_...)；而 ORM 模型用的是
`step_key = mapped_column(..., unique=True, index=True)`，
即一个 unique=True 的 ix_ 索引、无命名约束。两者语义相同但对象形态不同，
导致 `alembic check` 判定为漂移。本迁移把库表结构收敛到模型口径：
删除命名唯一约束与非唯一索引，改建唯一索引 ix_model_provider_configs_step_key。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "m2e3f4a5b6c7"
down_revision = "l2e3f4a5b6c7"
branch_labels = None
depends_on = None

TABLE = "model_provider_configs"
INDEX = "ix_model_provider_configs_step_key"
UQ_CONSTRAINT = "uq_model_provider_configs_step_key"


def upgrade() -> None:
    # j0d1e2f3a4b5 同时建了命名唯一约束和非唯一索引。SQLite 不支持直接
    # drop constraint，必须用 batch_alter_table（env.py 已开 render_as_batch）。
    # batch 重建模时按当前 ORM 模型反射会带入正确索引，这里显式描述目标状态。
    with op.batch_alter_table(TABLE) as batch_op:
        batch_op.drop_index(INDEX)
        batch_op.drop_constraint(UQ_CONSTRAINT, type_="unique")
        batch_op.create_index(INDEX, ["step_key"], unique=True)


def downgrade() -> None:
    with op.batch_alter_table(TABLE) as batch_op:
        batch_op.drop_index(INDEX)
        batch_op.create_index(INDEX, ["step_key"], unique=False)
        batch_op.create_unique_constraint(UQ_CONSTRAINT, ["step_key"])
