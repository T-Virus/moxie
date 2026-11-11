# -*- coding: utf-8 -*-
"""请求体模型。响应统一用 dict，便于按文档字段演进。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class ConsentEntry(BaseModel):
    version: str = Field(min_length=1, max_length=32)
    accepted: bool


class RegisterRequest(BaseModel):
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=32)
    password: str = Field(min_length=8, max_length=128)
    # 法律文本勾选：terms/privacy 等，键为条款类型，值为版本+是否同意
    consents: dict[str, ConsentEntry] | None = Field(default=None, max_length=16)

    @model_validator(mode="after")
    def _need_identity(self):
        if not self.email and not self.phone:
            raise ValueError("email 或 phone 至少填一个")
        return self


class LoginRequest(BaseModel):
    email: str | None = None
    phone: str | None = None
    password: str = Field(min_length=8, max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=16)


class DeviceCreateRequest(BaseModel):
    device_hash: str = Field(min_length=8, max_length=128)
    platform: Literal["windows", "android", "web", "macos", "linux"]
    name: str | None = Field(default=None, max_length=120)


class LicenseVerifyRequest(BaseModel):
    payload: dict[str, Any]
    signature: str


class TaskCreateRequest(BaseModel):
    type: Literal["decompose", "adapt", "review"]
    book_id: int | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    input_artifact: str | None = Field(default=None, max_length=255)
    idempotency_key: str | None = Field(default=None, max_length=200)


class CancelTaskRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=200)


class AgentGenre(BaseModel):
    id: str | None = Field(default=None, max_length=64)
    name: str = Field(min_length=1, max_length=60)


class AgentRunOptions(BaseModel):
    """创作高级选项；全部可选，缺省时沿用模式默认行为。"""

    target_chapters: int | None = Field(default=None, ge=1, le=500)
    sequel_chapters: int | None = Field(default=None, ge=0, le=200)
    adaptation_style: str | None = Field(default=None, max_length=300)
    adaptation_extra: str | None = Field(default=None, max_length=1000)


class AgentRunCreateRequest(BaseModel):
    mode: Literal["hot", "reference", "custom"]
    title: str = Field(min_length=1, max_length=120)
    audience: Literal["male", "female"]
    length: Literal["long", "short"]
    genre: AgentGenre
    source_key: str | None = Field(default=None, max_length=255)
    brief: str | None = Field(default=None, max_length=4000)
    options: AgentRunOptions | None = None


class AgentResumeInput(BaseModel):
    chapter_no: int = Field(ge=1, le=5000)
    content: str = Field(min_length=1, max_length=20000)


class AgentResumeRequest(BaseModel):
    input: AgentResumeInput | None = None
    approval: bool = False
    retry_failed: bool = False

    @model_validator(mode="after")
    def _need_action(self):
        if not self.approval and self.input is None and not self.retry_failed:
            raise ValueError("approval、input、retry_failed 至少提供一项")
        return self


class AgentInfoUpdateRequest(BaseModel):
    """作品信息编辑：必填项由前端校验，这里只做边界与长度约束。"""

    title: str | None = Field(default=None, min_length=1, max_length=120)
    author: str | None = Field(default=None, max_length=60)
    status_label: Literal["连载中", "已签约", "已完结"] | None = None
    audience: Literal["male", "female"] | None = None
    length: Literal["long", "short"] | None = None
    genre: AgentGenre | None = None
    logline: str | None = Field(default=None, max_length=300)
    synopsis: str | None = Field(default=None, max_length=2000)
    themes: list[str] | None = Field(default=None, max_length=12)
    person: str | None = Field(default=None, max_length=60)
    style: str | None = Field(default=None, max_length=200)
    world: str | None = Field(default=None, max_length=1200)
    conflict: str | None = Field(default=None, max_length=1200)
    mainline: str | None = Field(default=None, max_length=1200)
    selling_points: list[str] | None = Field(default=None, max_length=12)
    core_hook: str | None = Field(default=None, max_length=500)
    suspense: str | None = Field(default=None, max_length=1200)
    subplots: str | None = Field(default=None, max_length=1200)
    beats: list[str] | None = Field(default=None, max_length=500)
    protagonist: str | None = Field(default=None, max_length=1200)
    supporting: str | None = Field(default=None, max_length=1200)
    antagonist: str | None = Field(default=None, max_length=1200)
    foreshadow_text: str | None = Field(default=None, max_length=2000)
    power: str | None = Field(default=None, max_length=1200)
    places: str | None = Field(default=None, max_length=2000)
    items_text: str | None = Field(default=None, max_length=2000)
    terms: str | None = Field(default=None, max_length=2000)
    timeline: str | None = Field(default=None, max_length=2000)
    map_text: str | None = Field(default=None, max_length=2000)
    theme_core: str | None = Field(default=None, max_length=300)
    theme_statement: str | None = Field(default=None, max_length=500)
    innovation_points: list[str] | None = Field(default=None, max_length=12)
    ending_type: str | None = Field(default=None, max_length=60)
    ending_state: str | None = Field(default=None, max_length=1000)
    protagonist_final_fate: str | None = Field(default=None, max_length=1000)
    comparative_titles: list[str] | None = Field(default=None, max_length=12)
    taboos: str | None = Field(default=None, max_length=2000)
    tone: str | None = Field(default=None, max_length=60)
    target_platform: list[str] | None = Field(default=None, max_length=20)
    target_reader_age: str | None = Field(default=None, max_length=60)
    update_frequency: str | None = Field(default=None, max_length=60)
    serialization_pace: str | None = Field(default=None, max_length=60)
    content_rating: str | None = Field(default=None, max_length=60)


class AgentCollectionsUpdateRequest(BaseModel):
    """人物/势力/道具/卷章概览的增删改：客户端提交整组最新数据，服务端整体覆盖。

    只做边界约束，具体字段由客户端表单保证；未提交的集合保持原值。
    """

    characters: list[dict[str, Any]] | None = Field(default=None, max_length=500)
    factions: list[dict[str, Any]] | None = Field(default=None, max_length=200)
    items: list[dict[str, Any]] | None = Field(default=None, max_length=500)
    volumes: list[dict[str, Any]] | None = Field(default=None, max_length=100)
    chapter_summaries: list[dict[str, Any]] | None = Field(default=None, max_length=5000)
    chapter_hidden: list[int] | None = Field(default=None, max_length=5000)


class AgentCoverRequest(BaseModel):
    prompt: str | None = Field(default=None, max_length=600)
    style: Literal["gold", "white", "ink"] = "gold"
    layout: Literal["top", "middle", "bottom"] = "top"
    width: int | None = Field(default=None, ge=256, le=4096)
    height: int | None = Field(default=None, ge=256, le=4096)


class SubscribeRequest(BaseModel):
    plan_code: str = Field(min_length=2, max_length=64)
    cycle: Literal["month", "year"] = "month"
    provider: Literal["mock", "fake", "wechat", "alipay", "stripe"]
    idempotency_key: str | None = Field(default=None, max_length=200)
    # 渠道上下文：微信 JSAPI 需要 openid；scene 覆盖默认支付场景
    openid: str | None = Field(default=None, max_length=128)
    scene: str | None = Field(default=None, max_length=16)


class CancelSubscriptionRequest(BaseModel):
    immediate: bool = False


class RenewRequest(BaseModel):
    cycle: Literal["month", "year"] = "month"
    provider: Literal["mock", "fake", "wechat", "alipay", "stripe"]
    idempotency_key: str | None = Field(default=None, max_length=200)
    openid: str | None = Field(default=None, max_length=128)
    scene: str | None = Field(default=None, max_length=16)


class UpgradeRequest(BaseModel):
    plan_code: str = Field(min_length=2, max_length=64)
    provider: Literal["mock", "fake", "wechat", "alipay", "stripe"]
    idempotency_key: str | None = Field(default=None, max_length=200)
    openid: str | None = Field(default=None, max_length=128)
    scene: str | None = Field(default=None, max_length=16)


class CreditPackPurchaseRequest(BaseModel):
    provider: Literal["mock", "fake", "wechat", "alipay", "stripe"]
    idempotency_key: str | None = Field(default=None, max_length=200)
    openid: str | None = Field(default=None, max_length=128)
    scene: str | None = Field(default=None, max_length=16)


class AdminRefundRequest(BaseModel):
    amount_cents: int | None = Field(default=None, ge=1)
    reason: str | None = Field(default=None, max_length=200)
    idempotency_key: str | None = Field(default=None, max_length=200)
    # 按已用量/剩余时长自动折算退款金额（优先于 amount_cents）
    prorate: bool = False


class AdminRefundDecisionRequest(BaseModel):
    note: str | None = Field(default=None, max_length=200)
    reason: str | None = Field(default=None, max_length=200)


class AdminUserStatusRequest(BaseModel):
    status: Literal["active", "banned"]
    reason: str = Field(min_length=2, max_length=200)


class AdminReasonRequest(BaseModel):
    reason: str = Field(min_length=2, max_length=200)


class AdminSubscriptionPatchRequest(BaseModel):
    plan_code: str | None = Field(default=None, max_length=64)
    current_end_at: datetime | None = None
    extend_days: int = Field(default=0, ge=0, le=3650)
    status: Literal["trialing", "active", "past_due", "paused", "canceled", "expired"] | None = None
    note: str = Field(min_length=2, max_length=200)


class AdminSubscriptionAdjustRequest(BaseModel):
    plan_code: str | None = Field(default=None, max_length=64)
    status: Literal["trialing", "active", "past_due", "paused", "canceled", "expired"] | None = None
    extend_days: int = Field(default=0, ge=0, le=3650)
    reason: str = Field(min_length=2, max_length=200)


class AdminQuotaAdjustRequest(BaseModel):
    metric: str = Field(min_length=2, max_length=64)
    quantity: int = Field(ge=-1000000, le=1000000)
    reason: str = Field(min_length=2, max_length=200)
    idempotency_key: str | None = Field(default=None, max_length=200)


class AdminNotificationRequest(BaseModel):
    account_id: int = Field(ge=1)
    title: str = Field(min_length=2, max_length=120)
    body: str = Field(min_length=2, max_length=2000)
    channels: list[Literal["inapp", "email", "sms"]] | None = None


class ReconcileRequest(BaseModel):
    provider: Literal["mock", "fake", "wechat", "alipay", "stripe"]
    biz_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    # 离线/测试可直接传账单记录；不传则调用渠道下载
    records: list[dict] | None = None


class InvoiceCreateRequest(BaseModel):
    title: str = Field(min_length=2, max_length=120)
    tax_no: str | None = Field(default=None, max_length=64)
    email: str | None = Field(default=None, max_length=255)
    note: str | None = Field(default=None, max_length=200)


class InvoiceUpdateRequest(BaseModel):
    # requested=待开票，issued=已开具，voided=作废；rejected 为管理端旧叫法（服务端归一为 voided）
    status: Literal["requested", "issued", "voided", "rejected"]
    note: str | None = Field(default=None, max_length=200)


class InvoiceApplyRequest(BaseModel):
    """申请开票：可指定渠道；留空使用 INVOICE_PROVIDER。"""

    provider: str | None = Field(default=None, max_length=32)
    note: str | None = Field(default=None, max_length=200)


class InvoiceVoidRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=200)
