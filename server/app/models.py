# -*- coding: utf-8 -*-
"""SQLAlchemy 2.x 模型。字段与 docs/服务端架构与订阅计费设计-2026-11.md 第 5 节一致。

约定：
  · 主键用 BigInteger，SQLite 下降级为 INTEGER 以支持自增；
  · 所有时间列用 UTCDateTime，读写都是 UTC；
  · 金额一律用「分」的整数；
  · 业务状态用字符串常量，避免枚举迁移成本。
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    LargeBinary,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base, utcnow

BIGINT = BigInteger().with_variant(Integer, "sqlite")
JSON_TYPE = JSON().with_variant(JSONB, "postgresql")


class UTCDateTime(TypeDecorator):
    """统一 UTC 存储：SQLite 落 naive UTC，Postgres 落带时区值。"""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):  # noqa: ANN001
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        value = value.astimezone(timezone.utc)
        if dialect.name == "sqlite":
            return value.replace(tzinfo=None)
        return value

    def process_result_value(self, value, dialect):  # noqa: ANN001
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), unique=True, nullable=True)
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    role: Mapped[str] = mapped_column(String(16), default="user", nullable=False)
    email_verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow, nullable=False)


class EmailVerification(Base):
    """邮箱验证令牌：注册/重发时生成，点击邮件链接消费后激活账号。

    只存令牌哈希，不存明文；过期/消费后留痕，便于审计与防重放。
    """

    __tablename__ = "email_verifications"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("accounts.id"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)


class Device(Base):
    __tablename__ = "devices"
    __table_args__ = (UniqueConstraint("account_id", "device_hash", name="uq_devices_account_hash"),)

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("accounts.id"), nullable=False, index=True)
    device_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    platform: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)


class License(Base):
    __tablename__ = "licenses"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("accounts.id"), nullable=False, index=True)
    device_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("devices.id"), nullable=False, index=True)
    key_id: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON_TYPE, default=dict, nullable=False)
    signature: Mapped[str] = mapped_column(Text, nullable=False)
    issued_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    refresh_after: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    grace_until: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class Plan(Base):
    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    price_month_cents: Mapped[int] = mapped_column(BIGINT, nullable=False)
    price_year_cents: Mapped[int] = mapped_column(BIGINT, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="CNY", nullable=False)
    features: Mapped[dict] = mapped_column(JSON_TYPE, default=dict, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Entitlement(Base):
    __tablename__ = "entitlements"
    __table_args__ = (UniqueConstraint("plan_id", "key", name="uq_entitlements_plan_key"),)

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    plan_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("plans.id"), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    limit_value: Mapped[int] = mapped_column(BIGINT, nullable=False)
    unit: Mapped[str] = mapped_column(String(16), default="count", nullable=False)
    reset_period: Mapped[str] = mapped_column(String(16), default="month", nullable=False)
    overage_price_cents: Mapped[int | None] = mapped_column(BIGINT, nullable=True)


class Subscription(Base):
    __tablename__ = "subscriptions"
    __table_args__ = (
        Index(
            "uq_sub_active",
            "account_id",
            unique=True,
            sqlite_where=text("status IN ('trialing','active','past_due','paused')"),
            postgresql_where=text("status IN ('trialing','active','past_due','paused')"),
        ),
    )

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("accounts.id"), nullable=False, index=True)
    plan_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("plans.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    seats: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    trial_end_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    current_start_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    current_end_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    provider: Mapped[str | None] = mapped_column(String(16), nullable=True)
    provider_sub_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow, nullable=False)


class UsageEvent(Base):
    __tablename__ = "usage_events"
    __table_args__ = (
        UniqueConstraint("account_id", "idempotency_key", name="uq_usage_account_idem"),
        Index("idx_usage_account_time", "account_id", "occurred_at"),
        Index("idx_usage_task", "task_id"),
    )

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("accounts.id"), nullable=False)
    task_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metric: Mapped[str] = mapped_column(String(64), nullable=False)
    quantity: Mapped[int] = mapped_column(BIGINT, nullable=False)
    unit: Mapped[str] = mapped_column(String(16), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    meta: Mapped[dict] = mapped_column(JSON_TYPE, default=dict, nullable=False)


class UsageAggregate(Base):
    __tablename__ = "usage_aggregates"
    __table_args__ = (UniqueConstraint("account_id", "metric", "period_start", name="uq_aggregate_key"),)

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("accounts.id"), nullable=False, index=True)
    metric: Mapped[str] = mapped_column(String(64), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    used: Mapped[int] = mapped_column(BIGINT, default=0, nullable=False)
    reserved: Mapped[int] = mapped_column(BIGINT, default=0, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow, nullable=False)


class CreditPack(Base):
    """一次性额度包目录（不可续订，买一次加一次额度）。"""

    __tablename__ = "credit_packs"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    metric: Mapped[str] = mapped_column(String(64), nullable=False)
    quantity: Mapped[int] = mapped_column(BIGINT, nullable=False)
    price_cents: Mapped[int] = mapped_column(BIGINT, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="CNY", nullable=False)
    # 有效期天数：默认 12 个月；到期后剩余额度作废，不结转、不清零已用
    validity_days: Mapped[int] = mapped_column(Integer, default=365, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)


class CreditGrant(Base):
    """额度包发放账本：一份订单对应一条发放记录，使用按到期时间先到期先扣。"""

    __tablename__ = "credit_grants"
    __table_args__ = (
        UniqueConstraint("account_id", "idempotency_key", name="uq_credit_grants_account_idem"),
        Index("idx_credit_grants_account_expiry", "account_id", "metric", "expires_at"),
        Index(
            "uq_credit_grants_order",
            "order_id",
            unique=True,
            sqlite_where=text("order_id IS NOT NULL"),
            postgresql_where=text("order_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("accounts.id"), nullable=False, index=True)
    pack_id: Mapped[int | None] = mapped_column(BIGINT, ForeignKey("credit_packs.id"), nullable=True)
    order_id: Mapped[int | None] = mapped_column(BIGINT, ForeignKey("orders.id"), nullable=True)
    metric: Mapped[str] = mapped_column(String(64), nullable=False)
    quantity_granted: Mapped[int] = mapped_column(BIGINT, nullable=False)
    quantity_used: Mapped[int] = mapped_column(BIGINT, default=0, nullable=False)
    quantity_reserved: Mapped[int] = mapped_column(BIGINT, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    valid_from: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    meta: Mapped[dict] = mapped_column(JSON_TYPE, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)


class Notification(Base):
    """站内信：同一账号 + dedupe_key 唯一，重放不会产生重复消息。"""

    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("account_id", "dedupe_key", name="uq_notifications_account_dedupe"),
        Index("idx_notifications_account_time", "account_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("accounts.id"), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    level: Mapped[str] = mapped_column(String(16), default="info", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="unread", nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(200), nullable=False)
    meta: Mapped[dict] = mapped_column(JSON_TYPE, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class NotificationDelivery(Base):
    """每个渠道的发送记录：失败可重试，密钥不进 payload。"""

    __tablename__ = "notification_deliveries"
    __table_args__ = (
        UniqueConstraint("channel", "dedupe_key", name="uq_delivery_channel_dedupe"),
        Index("idx_delivery_status_retry", "status", "next_retry_at"),
    )

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    notification_id: Mapped[int | None] = mapped_column(
        BIGINT, ForeignKey("notifications.id"), nullable=True
    )
    account_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("accounts.id"), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    recipient: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="queued", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    last_error: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    dedupe_key: Mapped[str] = mapped_column(String(200), nullable=False)
    meta: Mapped[dict] = mapped_column(JSON_TYPE, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        UniqueConstraint("account_id", "idempotency_key", name="uq_tasks_account_idem"),
        Index("idx_tasks_status_lease", "status", "lease_until"),
        Index("idx_tasks_account_time", "account_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("accounts.id"), nullable=False)
    book_id: Mapped[int | None] = mapped_column(BIGINT, nullable=True)
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="queued", nullable=False)
    params: Mapped[dict] = mapped_column(JSON_TYPE, default=dict, nullable=False)
    input_artifact: Mapped[str | None] = mapped_column(String(255), nullable=True)
    output_artifact: Mapped[str | None] = mapped_column(String(255), nullable=True)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_estimate_cents: Mapped[int | None] = mapped_column(BIGINT, nullable=True)
    cost_actual_cents: Mapped[int | None] = mapped_column(BIGINT, nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    lease_until: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reserved_metric: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reserved_quantity: Mapped[int] = mapped_column(BIGINT, default=0, nullable=False)
    # 预占拆分：套餐先扣，不足部分落到额度包（记录 grant_id 与数量，便于释放/结算）
    reserved_plan_quantity: Mapped[int] = mapped_column(BIGINT, default=0, nullable=False)
    reserved_pack_items: Mapped[list] = mapped_column(JSON_TYPE, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class TaskStep(Base):
    __tablename__ = "task_steps"

    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("tasks.id"), primary_key=True)
    step_key: Mapped[str] = mapped_column(String(120), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    output_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    meta: Mapped[dict] = mapped_column(JSON_TYPE, default=dict, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow, nullable=False)


class TaskEvent(Base):
    __tablename__ = "task_events"

    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("tasks.id"), primary_key=True)
    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    level: Mapped[str] = mapped_column(String(16), default="info", nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("account_id", "idempotency_key", name="uq_orders_account_idem"),
        Index("idx_orders_account_time", "account_id", "created_at"),
        Index(
            "uq_orders_provider_txn",
            "provider",
            "provider_txn_id",
            unique=True,
            sqlite_where=text("provider_txn_id IS NOT NULL"),
            postgresql_where=text("provider_txn_id IS NOT NULL"),
        ),
        Index(
            "uq_orders_external_no",
            "provider",
            "external_order_no",
            unique=True,
            sqlite_where=text("external_order_no IS NOT NULL"),
            postgresql_where=text("external_order_no IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("accounts.id"), nullable=False)
    subscription_id: Mapped[int | None] = mapped_column(BIGINT, ForeignKey("subscriptions.id"), nullable=True)
    # 额度包订单没有套餐；订阅/续费/升级订单才有 plan_id
    plan_id: Mapped[int | None] = mapped_column(BIGINT, ForeignKey("plans.id"), nullable=True)
    pack_id: Mapped[int | None] = mapped_column(BIGINT, ForeignKey("credit_packs.id"), nullable=True)
    amount_cents: Mapped[int] = mapped_column(BIGINT, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="CNY", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    provider_txn_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # 渠道侧商户订单号（微信 out_trade_no / 支付宝 out_trade_no / Stripe payment_intent）
    external_order_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    kind: Mapped[str] = mapped_column(String(16), default="purchase", nullable=False)
    cycle: Mapped[str] = mapped_column(String(16), default="month", nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    refunded_cents: Mapped[int] = mapped_column(BIGINT, default=0, nullable=False)
    failure_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    meta: Mapped[dict] = mapped_column(JSON_TYPE, default=dict, nullable=False)
    paid_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow, nullable=False)


class WebhookEvent(Base):
    __tablename__ = "webhook_events"
    __table_args__ = (UniqueConstraint("provider", "event_id", name="uq_webhook_provider_event"),)

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    # 只存脱敏后的回调摘要，绝不存密钥/证件/银行卡
    payload: Mapped[dict] = mapped_column(JSON_TYPE, default=dict, nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), default="payment", nullable=False)
    signature_valid: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    process_status: Mapped[str] = mapped_column(String(16), default="received", nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    retryable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    raw_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)


class Refund(Base):
    __tablename__ = "refunds"
    __table_args__ = (
        UniqueConstraint("account_id", "idempotency_key", name="uq_refunds_account_idem"),
        Index("idx_refunds_order", "order_id"),
        Index(
            "uq_refunds_provider_ref",
            "provider",
            "provider_refund_id",
            unique=True,
            sqlite_where=text("provider_refund_id IS NOT NULL"),
            postgresql_where=text("provider_refund_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("orders.id"), nullable=False)
    account_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("accounts.id"), nullable=False, index=True)
    amount_cents: Mapped[int] = mapped_column(BIGINT, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="CNY", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    provider_refund_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    meta: Mapped[dict] = mapped_column(JSON_TYPE, default=dict, nullable=False)
    requested_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    succeeded_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class ReconcileReport(Base):
    __tablename__ = "reconcile_reports"
    __table_args__ = (UniqueConstraint("provider", "biz_date", name="uq_reconcile_provider_date"),)

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    biz_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="done", nullable=False)
    summary: Mapped[dict] = mapped_column(JSON_TYPE, default=dict, nullable=False)
    items: Mapped[list] = mapped_column(JSON_TYPE, default=list, nullable=False)
    channel_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)


class InvoiceRequest(Base):
    __tablename__ = "invoice_requests"
    __table_args__ = (UniqueConstraint("order_id", name="uq_invoice_order"),)

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("orders.id"), nullable=False)
    account_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("accounts.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    tax_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    amount_cents: Mapped[int] = mapped_column(BIGINT, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="requested", nullable=False)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    admin_id: Mapped[int | None] = mapped_column(BIGINT, nullable=True)
    issued_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    meta: Mapped[dict] = mapped_column(JSON_TYPE, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("idx_audit_actor_time", "actor_id", "created_at"),
        Index("idx_audit_target", "target_type", "target_id"),
    )

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    actor_id: Mapped[int | None] = mapped_column(BIGINT, nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ua: Mapped[str | None] = mapped_column(String(255), nullable=True)
    meta: Mapped[dict] = mapped_column(JSON_TYPE, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)


class AgentRun(Base):
    """Agent 编排运行：三种写作模式共用一张运行表。

    额度口径与 tasks 一致：创建时预占，成功结算，失败/取消释放；
    运行本身只入队，实际执行由 worker（RQ 或 --once）驱动。
    """

    __tablename__ = "agent_runs"
    __table_args__ = (
        UniqueConstraint("account_id", "idempotency_key", name="uq_agent_runs_account_idem"),
        Index("idx_agent_runs_account_time", "account_id", "created_at"),
        Index("idx_agent_runs_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("accounts.id"), nullable=False, index=True)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    audience: Mapped[str] = mapped_column(String(16), nullable=False)
    length: Mapped[str] = mapped_column(String(16), nullable=False)
    genre_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    genre_name: Mapped[str] = mapped_column(String(60), nullable=False)
    source_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    brief: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="queued", nullable=False)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    current_stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    reserved_metric: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reserved_quantity: Mapped[int] = mapped_column(BIGINT, default=0, nullable=False)
    reserved_plan_quantity: Mapped[int] = mapped_column(BIGINT, default=0, nullable=False)
    reserved_pack_items: Mapped[list] = mapped_column(JSON_TYPE, default=list, nullable=False)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tokens_total: Mapped[int] = mapped_column(BIGINT, default=0, nullable=False)
    cost_cents: Mapped[int] = mapped_column(BIGINT, default=0, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(255), nullable=True)
    meta: Mapped[dict] = mapped_column(JSON_TYPE, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow, nullable=False)


class AgentRunStep(Base):
    """节点级 checkpoint：done 的节点重启后直接复用输出，实现断点续跑。"""

    __tablename__ = "agent_run_steps"

    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("agent_runs.id"), primary_key=True)
    node_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output: Mapped[dict | None] = mapped_column(JSON_TYPE, nullable=True)
    error: Mapped[str | None] = mapped_column(String(255), nullable=True)
    meta: Mapped[dict] = mapped_column(JSON_TYPE, default=dict, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow, nullable=False)


class AgentRunEvent(Base):
    """运行事件流：SSE 按 seq 顺序回放。"""

    __tablename__ = "agent_run_events"

    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("agent_runs.id"), primary_key=True)
    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    stage: Mapped[str] = mapped_column(String(64), nullable=False)
    level: Mapped[str] = mapped_column(String(16), default="info", nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)


class LegalConsent(Base):
    """法律文本同意留痕：每次同意记一条，支持版本演进与审计导出。"""

    __tablename__ = "legal_consents"
    __table_args__ = (
        UniqueConstraint("account_id", "consent_type", "version", name="uq_consents_account_type_version"),
    )

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("accounts.id"), nullable=False, index=True)
    consent_type: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    accepted_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)


class RefreshSession(Base):
    __tablename__ = "refresh_sessions"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("accounts.id"), nullable=False, index=True)
    device_id: Mapped[int | None] = mapped_column(BIGINT, ForeignKey("devices.id"), nullable=True)
    session_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    rotated_from: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)


class StoredObject(Base):
    """对象存储落库形态：产物与上传源文件统一存二进制，不依赖本地磁盘。

    key 与磁盘/S3 版本的相对路径完全一致，便于三种后端互换；
    content_type 保留写入口径，下载时按它回填响应头。
    """

    __tablename__ = "stored_objects"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    content_type: Mapped[str] = mapped_column(
        String(120), default="application/octet-stream", nullable=False
    )
    size: Mapped[int] = mapped_column(BIGINT, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utcnow, onupdate=utcnow, nullable=False
    )


__all__ = [
    "Base",
    "Account",
    "Device",
    "License",
    "Plan",
    "Entitlement",
    "Subscription",
    "UsageEvent",
    "UsageAggregate",
    "Task",
    "TaskStep",
    "TaskEvent",
    "CreditPack",
    "CreditGrant",
    "Notification",
    "NotificationDelivery",
    "Order",
    "WebhookEvent",
    "Refund",
    "ReconcileReport",
    "InvoiceRequest",
    "AuditLog",
    "RefreshSession",
    "AgentRun",
    "AgentRunStep",
    "AgentRunEvent",
    "StoredObject",
    "EmailVerification",
]
