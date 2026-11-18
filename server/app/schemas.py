# -*- coding: utf-8 -*-
"""请求体模型 + 少量结构稳定接口的出参契约。

多数响应仍用 dict，便于按文档字段演进；仅对结构固定、长期不变的接口
（如加密公钥）声明 response_model，让 OpenAPI 出参有 schema。"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel as _Base, Field, StringConstraints, model_validator

# —— 统一输入清洗：进入校验前递归去掉字符串首尾空白 ——
# 这些键是密码、令牌、密钥或长正文，必须保留原始空白，不做 trim。
_NO_TRIM_KEYS = frozenset({
    "password", "refresh_token", "token", "signature", "api_key",
    "secret", "content", "body", "prompt",
})


def _trim_input(value: object, key: str = "") -> object:
    if isinstance(value, str):
        return value if key in _NO_TRIM_KEYS else value.strip()
    if isinstance(value, list):
        return [_trim_input(item, key) for item in value]
    if isinstance(value, dict):
        return {k: _trim_input(v, str(k)) for k, v in value.items()}
    return value


class AppModel(_Base):
    """所有请求模型基类：统一 trim 字符串（含 list / dict 嵌套），防止用户误输入空格。"""

    @model_validator(mode="before")
    @classmethod
    def _trim_whitespace(cls, data: object) -> object:
        if isinstance(data, dict):
            return {k: _trim_input(v, str(k)) for k, v in data.items()}
        return _trim_input(data)


# 自由文本列表元素的统一长度上限，防止超长字符串写入 Text 列
StrMax200 = Annotated[str, StringConstraints(max_length=200, strip_whitespace=True)]
StrMax120 = Annotated[str, StringConstraints(max_length=120, strip_whitespace=True)]
StrMax64 = Annotated[str, StringConstraints(max_length=64, strip_whitespace=True)]


class ConsentEntry(AppModel):
    version: str = Field(min_length=1, max_length=32)
    accepted: bool


class RegisterRequest(AppModel):
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


class LoginRequest(AppModel):
    email: str | None = None
    phone: str | None = None
    password: str = Field(min_length=8, max_length=128)


class RefreshRequest(AppModel):
    refresh_token: str = Field(min_length=16)


class VerifyEmailRequest(AppModel):
    token: str = Field(min_length=16, max_length=512)


class ResendVerificationRequest(AppModel):
    email: str = Field(min_length=3, max_length=255)


class DeviceCreateRequest(AppModel):
    device_hash: str = Field(min_length=8, max_length=128)
    platform: Literal["windows", "android", "web", "macos", "linux"]
    name: str | None = Field(default=None, max_length=120)


class LicenseVerifyRequest(AppModel):
    payload: dict[str, Any]
    signature: str


class TaskCreateRequest(AppModel):
    type: Literal["decompose", "adapt", "review"]
    book_id: int | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    input_artifact: str | None = Field(default=None, max_length=255)
    idempotency_key: str | None = Field(default=None, max_length=200)


class CancelTaskRequest(AppModel):
    reason: str | None = Field(default=None, max_length=200)


class AgentGenre(AppModel):
    id: str | None = Field(default=None, max_length=64)
    name: str = Field(min_length=1, max_length=60)


class AgentRunOptions(AppModel):
    """创作高级选项；全部可选，缺省时沿用模式默认行为。"""

    target_chapters: int | None = Field(default=None, ge=1, le=5000)
    sequel_chapters: int | None = Field(default=None, ge=0, le=200)
    adaptation_style: str | None = Field(default=None, max_length=300)
    adaptation_extra: str | None = Field(default=None, max_length=1000)


class RightsDeclaration(AppModel):
    """参考改编的权利声明，随加密 body 提交（明文头可伪造，仅作兼容回退）。

    basis: own=自有著作权 / authorized=已获授权 / public_domain=公有领域。
    """

    basis: Literal["own", "authorized", "public_domain"]
    rights_confirmed: bool
    ai_notice_ack: bool = False
    note: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def _must_confirm(self):
        if not self.rights_confirmed:
            raise ValueError("rights_confirmed 必须为 true")
        if not self.ai_notice_ack:
            raise ValueError("ai_notice_ack 必须为 true")
        return self


class AgentRunCreateRequest(AppModel):
    mode: Literal["hot", "reference", "custom"]
    title: str = Field(min_length=1, max_length=120)
    audience: Literal["male", "female"]
    length: Literal["long", "short"]
    genre: AgentGenre
    source_key: str | None = Field(default=None, max_length=255)
    brief: str | None = Field(default=None, max_length=4000)
    options: AgentRunOptions | None = None
    rights: RightsDeclaration | None = None


class AgentResumeInput(AppModel):
    chapter_no: int = Field(ge=1, le=5000)
    content: str = Field(min_length=1, max_length=20000)


class AgentResumeRequest(AppModel):
    input: AgentResumeInput | None = None
    approval: bool = False
    retry_failed: bool = False

    @model_validator(mode="after")
    def _need_action(self):
        if not self.approval and self.input is None and not self.retry_failed:
            raise ValueError("approval、input、retry_failed 至少提供一项")
        return self


class AgentInfoUpdateRequest(AppModel):
    """作品信息编辑：必填项由前端校验，这里只做边界与长度约束。"""

    title: str | None = Field(default=None, min_length=1, max_length=120)
    author: str | None = Field(default=None, max_length=60)
    status_label: Literal["连载中", "已签约", "已完结"] | None = None
    audience: Literal["male", "female"] | None = None
    length: Literal["long", "short"] | None = None
    genre: AgentGenre | None = None
    logline: str | None = Field(default=None, max_length=300)
    synopsis: str | None = Field(default=None, max_length=2000)
    themes: list[StrMax120] | None = Field(default=None, max_length=12)
    person: str | None = Field(default=None, max_length=60)
    style: str | None = Field(default=None, max_length=200)
    world: str | None = Field(default=None, max_length=1200)
    conflict: str | None = Field(default=None, max_length=1200)
    mainline: str | None = Field(default=None, max_length=1200)
    selling_points: list[StrMax200] | None = Field(default=None, max_length=12)
    core_hook: str | None = Field(default=None, max_length=500)
    suspense: str | None = Field(default=None, max_length=1200)
    subplots: str | None = Field(default=None, max_length=1200)
    beats: list[StrMax120] | None = Field(default=None, max_length=500)
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
    innovation_points: list[StrMax120] | None = Field(default=None, max_length=12)
    ending_type: str | None = Field(default=None, max_length=60)
    ending_state: str | None = Field(default=None, max_length=1000)
    protagonist_final_fate: str | None = Field(default=None, max_length=1000)
    comparative_titles: list[StrMax200] | None = Field(default=None, max_length=12)
    taboos: str | None = Field(default=None, max_length=2000)
    tone: str | None = Field(default=None, max_length=60)
    target_platform: list[StrMax64] | None = Field(default=None, max_length=20)
    target_reader_age: str | None = Field(default=None, max_length=60)
    update_frequency: str | None = Field(default=None, max_length=60)
    serialization_pace: str | None = Field(default=None, max_length=60)
    content_rating: str | None = Field(default=None, max_length=60)


class AgentCollectionsUpdateRequest(AppModel):
    """人物/势力/道具/卷章概览的增删改：客户端提交整组最新数据，服务端整体覆盖。

    只做边界约束，具体字段由客户端表单保证；未提交的集合保持原值。
    """

    characters: list[dict[str, Any]] | None = Field(default=None, max_length=500)
    factions: list[dict[str, Any]] | None = Field(default=None, max_length=200)
    items: list[dict[str, Any]] | None = Field(default=None, max_length=500)
    volumes: list[dict[str, Any]] | None = Field(default=None, max_length=1000)
    chapter_summaries: list[dict[str, Any]] | None = Field(default=None, max_length=5000)
    chapter_hidden: list[int] | None = Field(default=None, max_length=5000)


class AgentCoverRequest(AppModel):
    prompt: str | None = Field(default=None, max_length=600)
    style: Literal["gold", "white", "ink"] = "gold"
    layout: Literal["top", "middle", "bottom"] = "top"
    width: int | None = Field(default=None, ge=256, le=4096)
    height: int | None = Field(default=None, ge=256, le=4096)


class SubscribeRequest(AppModel):
    plan_code: str = Field(min_length=2, max_length=64)
    cycle: Literal["month", "year"] = "month"
    provider: Literal["mock", "fake", "wechat", "alipay", "stripe"]
    idempotency_key: str | None = Field(default=None, max_length=200)
    # 渠道上下文：微信 JSAPI 需要 openid；scene 覆盖默认支付场景
    openid: str | None = Field(default=None, max_length=128)
    scene: str | None = Field(default=None, max_length=16)


class CancelSubscriptionRequest(AppModel):
    immediate: bool = False


class RenewRequest(AppModel):
    cycle: Literal["month", "year"] = "month"
    provider: Literal["mock", "fake", "wechat", "alipay", "stripe"]
    idempotency_key: str | None = Field(default=None, max_length=200)
    openid: str | None = Field(default=None, max_length=128)
    scene: str | None = Field(default=None, max_length=16)


class UpgradeRequest(AppModel):
    plan_code: str = Field(min_length=2, max_length=64)
    provider: Literal["mock", "fake", "wechat", "alipay", "stripe"]
    idempotency_key: str | None = Field(default=None, max_length=200)
    openid: str | None = Field(default=None, max_length=128)
    scene: str | None = Field(default=None, max_length=16)


class CreditPackPurchaseRequest(AppModel):
    provider: Literal["mock", "fake", "wechat", "alipay", "stripe"]
    idempotency_key: str | None = Field(default=None, max_length=200)
    openid: str | None = Field(default=None, max_length=128)
    scene: str | None = Field(default=None, max_length=16)


class AdminRefundRequest(AppModel):
    amount_cents: int | None = Field(default=None, ge=1)
    reason: str | None = Field(default=None, max_length=200)
    idempotency_key: str | None = Field(default=None, max_length=200)
    # 按已用量/剩余时长自动折算退款金额（优先于 amount_cents）
    prorate: bool = False


class AdminRefundDecisionRequest(AppModel):
    note: str | None = Field(default=None, max_length=200)
    reason: str | None = Field(default=None, max_length=200)


class AdminUserStatusRequest(AppModel):
    status: Literal["active", "banned"]
    reason: str = Field(min_length=2, max_length=200)


class AdminDeleteByEmailRequest(AppModel):
    email: str = Field(min_length=3, max_length=255)


class AccountDeleteRequest(AppModel):
    """用户主动注销：必须带密码与显式确认串，避免误触。"""
    password: str = Field(min_length=1, max_length=128)
    confirmation: Literal["DELETE_MY_ACCOUNT"]


class AccountDeletionRequestView(AppModel):
    id: int
    account_id: int
    status: str
    reason: str | None = None
    requested_at: datetime
    purge_at: datetime
    cancelled_at: datetime | None = None


class AccountDeletionListResponse(AppModel):
    items: list[AccountDeletionRequestView]
    total: int


class AdminModelConfigUpsert(AppModel):
    """后台配置某工序模型。api_key 为 None 表示不改动已存 Key；空串表示清空。"""
    label: str | None = Field(default=None, max_length=128)
    provider: str = Field(default="edgeone", max_length=32)
    model: str = Field(min_length=1, max_length=128)
    base_url: str | None = Field(default=None, max_length=512)
    api_key: str | None = Field(default=None, max_length=2000)
    enabled: bool = True


class AdminModelConfigView(AppModel):
    step_key: str
    label: str
    configured: bool
    provider: str
    model: str
    base_url: str
    enabled: bool
    key_set: bool
    source: str
    updated_at: str | None = None
    # 按工序给出的推荐模型（首选/备选/理由），前端据此提示与一键套用
    recommendation: dict | None = None
    # 当前生效模型是否已命中推荐
    recommended_match: bool = False


class AdminModelConfigDeleteResponse(_Base):
    deleted: bool = True
    step_key: str


class AdminModelConfigTestResponse(_Base):
    ok: bool = True
    model: str
    tokens: int


class OfflinePackageView(_Base):
    """后台离线安装包视图，字段与 admin._offline_view 一一对应。"""

    id: int
    platform: str
    version: str
    filename: str
    size: int
    content_type: str
    is_active: bool
    release_notes: str | None
    uploaded_by: int
    created_at: str | None
    updated_at: str | None
    download_url: str


class OfflinePackageLimitsResponse(_Base):
    max_bytes: int
    suffix: dict[str, str]


class OfflinePackageDeleteResponse(_Base):
    deleted: bool = True
    id: int


class AdminReasonRequest(AppModel):
    reason: str = Field(min_length=2, max_length=200)


class AdminTaskControlRequest(AppModel):
    """运营对单个任务/运行的状态操作。

    source 缺省时按 agent_runs → tasks 的顺序自动识别；
    pause/resume 仅对 agent 运行有效（拆解/改编任务只有取消语义）。
    """

    action: Literal["cancel", "pause", "resume", "requeue", "force_cancel"]
    source: Literal["task", "agent_run"] | None = None
    reason: str | None = Field(default=None, max_length=180)


class AdminSubscriptionPatchRequest(AppModel):
    plan_code: str | None = Field(default=None, max_length=64)
    current_end_at: datetime | None = None
    extend_days: int = Field(default=0, ge=0, le=3650)
    status: Literal["trialing", "active", "past_due", "paused", "canceled", "expired"] | None = None
    note: str = Field(min_length=2, max_length=200)


class AdminSubscriptionAdjustRequest(AppModel):
    plan_code: str | None = Field(default=None, max_length=64)
    status: Literal["trialing", "active", "past_due", "paused", "canceled", "expired"] | None = None
    extend_days: int = Field(default=0, ge=0, le=3650)
    reason: str = Field(min_length=2, max_length=200)


class AdminQuotaAdjustRequest(AppModel):
    metric: str = Field(min_length=2, max_length=64)
    quantity: int = Field(ge=-1000000, le=1000000)
    reason: str = Field(min_length=2, max_length=200)
    idempotency_key: str | None = Field(default=None, max_length=200)


class AdminNotificationRequest(AppModel):
    account_id: int = Field(ge=1)
    title: str = Field(min_length=2, max_length=120)
    body: str = Field(min_length=2, max_length=2000)
    channels: list[Literal["inapp", "email", "sms", "push"]] | None = None


class WebPushKeysInput(AppModel):
    """浏览器订阅的加密密钥对，来自 subscription.toJSON().keys。"""

    p256dh: str = Field(min_length=1, max_length=255)
    auth: str = Field(min_length=1, max_length=255)


class WebPushSubscriptionInput(AppModel):
    """上报/更新 Web Push 订阅；endpoint 必须是 https，避免被用作内网探测。"""

    endpoint: str = Field(min_length=1, max_length=500, pattern=r"^https://")
    keys: WebPushKeysInput
    device_label: str | None = Field(default=None, max_length=128)


class ReconcileRequest(AppModel):
    provider: Literal["mock", "fake", "wechat", "alipay", "stripe"]
    biz_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    # 离线/测试可直接传账单记录；不传则调用渠道下载
    records: list[dict] | None = None


class InvoiceCreateRequest(AppModel):
    title: str = Field(min_length=2, max_length=120)
    tax_no: str | None = Field(default=None, max_length=64)
    email: str | None = Field(default=None, max_length=255)
    note: str | None = Field(default=None, max_length=200)


class InvoiceUpdateRequest(AppModel):
    # requested=待开票，issued=已开具，voided=作废；rejected 为管理端旧叫法（服务端归一为 voided）
    status: Literal["requested", "issued", "voided", "rejected"]
    note: str | None = Field(default=None, max_length=200)


class PublicKeyResponse(_Base):
    """ECDH 公钥出参契约：字段固定，长期不变，可安全声明给 OpenAPI。"""

    algorithm: str
    key_id: str
    public_key: str


class HealthResponse(_Base):
    """存活探针出参：三字段固定，不随业务演进。"""

    status: str
    env: str
    app: str


class GenreItemResponse(_Base):
    id: str
    name: str
    audience: list[str]
    tags: list[str]


class GenresResponse(_Base):
    """题材目录出参：降级时多一个 degraded 说明字段（默认 None 不会裁剪）。"""

    items: list[GenreItemResponse]
    custom_allowed: bool
    degraded: str | None = None


class ClientErrorReport(AppModel):
    """前端错误上报（匿名）：字段全部限长，服务端二次脱敏后再落日志。

    request_id 是"出错的那次请求"的服务端 request_id（前端从错误响应体取），
    用它把浏览器异常与服务端结构化日志串到同一条链路。
    """

    level: Literal["error", "warn"] = "error"
    code: str = Field(default="client_error", max_length=80)
    message: str = Field(default="", max_length=1000)
    source: Literal["client", "admin"] = "client"
    url: str = Field(default="", max_length=500)
    request_id: str = Field(default="", max_length=64)
    trace_id: str = Field(default="", max_length=64)
    user_agent: str = Field(default="", max_length=300)
    ts: str = Field(default="", max_length=40)


class InvoiceApplyRequest(AppModel):
    """申请开票：可指定渠道；留空使用 INVOICE_PROVIDER。"""

    provider: str | None = Field(default=None, max_length=32)
    note: str | None = Field(default=None, max_length=200)


class InvoiceVoidRequest(AppModel):
    reason: str | None = Field(default=None, max_length=200)


class AdminPresetUpsert(AppModel):
    """后台新增/编辑系统级预设值（题材、枚举、分类、标签）。

    type 用小写下划线标识，与前端 usePresets 请求的类型一致；
    audience 为逗号分隔的受众标签（male/female/all）。
    """

    type: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    value: str = Field(min_length=1, max_length=128)
    label: str | None = Field(default=None, max_length=128)
    audience: str = Field(default="all", max_length=32, pattern=r"^[a-z]+(,[a-z]+)*$")
    sort: int = Field(default=0, ge=-100000, le=100000)


class TelemetryCanaryView(_Base):
    """灰度档：只覆盖显式给出的字段，其余回退基线值。"""

    sample_rate: float | None = None
    dedupe_window_seconds: int | None = None
    dedupe_max_entries: int | None = None


class TelemetryConfigView(_Base):
    """后台可热改的前端错误上报策略（稳定出参）。"""

    sample_rate: float
    dedupe_window_seconds: int
    dedupe_max_entries: int
    canary_percent: int = 0
    canary: TelemetryCanaryView = Field(default_factory=TelemetryCanaryView)
    source: str
    updated_at: str | None
    updated_by: int | None


class TelemetryConfigUpdate(AppModel):
    """后台修改上报策略；范围在服务层二次校验。"""

    sample_rate: float = Field(ge=0.0, le=1.0)
    dedupe_window_seconds: int = Field(ge=0, le=86400)
    dedupe_max_entries: int = Field(ge=1, le=1024)
    canary_percent: int = Field(default=0, ge=0, le=100)
    canary: TelemetryCanaryView | None = None


class PaymentProviderView(_Base):
    """支付渠道列表项：只暴露可选渠道，不含任何凭据。"""

    id: str
    name: str
    test_only: bool


class PaymentProvidersResponse(_Base):
    items: list[PaymentProviderView]


class NotificationView(_Base):
    """站内信出参：meta 保留服务端动态内容，不做裁剪。"""

    id: int
    category: str
    title: str
    body: str
    level: str
    status: str
    meta: dict[str, Any] | None
    created_at: str | None
    read_at: str | None


class NotificationListResponse(_Base):
    items: list[NotificationView]
    unread_count: int


class NotificationReadResponse(_Base):
    notification: NotificationView


class WebPushSubscriptionView(_Base):
    """订阅出参：只回显非敏感字段，密钥不出网。"""

    id: int
    endpoint: str
    device_label: str | None
    status: str
    created_at: str | None


class WebPushSubscriptionResponse(_Base):
    items: list[WebPushSubscriptionView]


# —— 稳定出参契约：套餐 / 额度 / 审计 ——
class PlanEntitlementView(_Base):
    key: str
    limit: int
    unit: str
    reset_period: str


class PlanView(_Base):
    """公开套餐项：features 是运营配置的动态字典，原样保留不裁剪。"""

    code: str
    name: str
    price_month_cents: int
    price_year_cents: int
    currency: str
    features: dict[str, Any]
    entitlements: list[PlanEntitlementView]


class PlansResponse(_Base):
    plans: list[PlanView]


class AdminPlanView(PlanView):
    """后台套餐项：比公开视图多 active/status，单独声明避免公开列表被裁剪或多字段。"""

    active: bool
    status: str


class AdminPlansResponse(_Base):
    plans: list[AdminPlanView]


class QuotaPlanView(_Base):
    code: str
    name: str
    status: str


class QuotaMetricView(_Base):
    metric: str
    unit: str
    limit: int
    used: int
    reserved: int
    remaining: int
    pack_remaining: int
    total_remaining: int


class CreditPackView(_Base):
    metric: str
    granted: int
    used: int
    reserved: int
    remaining: int
    active_grants: int
    next_expires_at: str | None


class QuotaSummaryResponse(_Base):
    """额度汇总：plan 未订阅时为 null；metrics/credits 结构固定，动态内容都在值里。"""

    plan: QuotaPlanView | None
    period_start: str
    period_end: str
    metrics: list[QuotaMetricView]
    credits: list[CreditPackView]
    server_time: str


class AuditLogView(_Base):
    """审计记录：meta 动态 dict 原样保留；ua 属内部字段，view 层本就不下发。"""

    id: int
    actor_id: int | None
    action: str
    target_type: str | None
    target_id: str | None
    ip: str | None
    meta: dict[str, Any] | None
    created_at: str | None


class AuditLogsResponse(_Base):
    items: list[AuditLogView]
    total: int
    page: int
    page_size: int


# —— 稳定出参契约：订阅 / 订单 / 任务 / 写作运行 ——
class SubscriptionPlanView(_Base):
    code: str
    name: str


class SubscriptionView(_Base):
    """用户侧订阅视图。renewal_reminder 仅 /subscriptions/current 真实下发，
    其余接口 response_model 补 null（前端按 boolean|null 兼容）。"""

    id: int
    status: str
    plan: SubscriptionPlanView
    seats: int
    cancel_at_period_end: bool
    current_start_at: str
    current_end_at: str
    days_left: float
    provider: str | None
    version: int
    renewal_reminder: bool | None = None


class PaymentIntentView(_Base):
    """支付意图：params 是渠道动态参数（h5_url / 表单等），原样保留不裁剪。"""

    provider: str
    amount_cents: int
    currency: str
    params: dict[str, Any]


class OrderView(_Base):
    """用户侧订单：meta 含 previous_plan_code 等升级关键数据，原样保留不裁剪。"""

    id: int
    subscription_id: int | None
    amount_cents: int
    currency: str
    status: str
    provider: str
    kind: str
    cycle: str
    refunded_cents: int
    meta: dict[str, Any]
    paid_at: str | None
    created_at: str | None


class CreateSubscriptionResponse(_Base):
    subscription: SubscriptionView
    order: OrderView
    payment: PaymentIntentView


class CurrentSubscriptionResponse(SubscriptionView):
    renewal_reminder: bool


class SubscriptionActionResponse(_Base):
    subscription: SubscriptionView


class RenewSubscriptionResponse(_Base):
    order: OrderView
    payment: PaymentIntentView


class UpgradeSubscriptionResponse(_Base):
    order: OrderView
    payment: PaymentIntentView | None  # 订单已支付时不下单，payment 为 null
    subscription: SubscriptionView


class TaskView(_Base):
    """任务视图：params 含权利声明 / source_key / aigc_label 等运行时参数，原样保留。"""

    id: str
    type: str
    status: str
    book_id: int | None
    progress: int
    params: dict[str, Any]
    input_artifact: str | None
    output_artifact: str | None
    error_code: str | None
    cancel_requested: bool
    attempts: int
    next_retry_at: str | None
    prompt_version: str | None
    cost_estimate_cents: int | None
    cost_actual_cents: int | None
    created_at: str | None
    started_at: str | None
    finished_at: str | None


class CreateTaskResponse(_Base):
    task: TaskView
    created: bool
    enqueued: bool


class TaskDetailResponse(_Base):
    task: TaskView


class CancelTaskResponse(_Base):
    task: TaskView
    changed: bool


class TaskEventView(_Base):
    seq: int
    level: str
    message: str
    created_at: str | None


class TaskLogsResponse(_Base):
    events: list[TaskEventView]
    next_seq: int


class CreateAgentRunResponse(_Base):
    """写作运行创建响应：只覆盖固定字段，不含 run_to_dict 的动态明细。"""

    run_id: str
    status: str
    mode: str
    created_at: str | None
    created: bool
    enqueued: bool


class AgentRunHealthReportResponse(_Base):
    run_id: str
    title: str | None
    status: str
    review: dict[str, Any]
    continuity: dict[str, Any] | None
    polish: dict[str, Any] | None
    cover_plan: dict[str, Any] | None
    chapters: list[dict[str, Any]]
    summary: dict[str, Any]
    missing_artifacts: list[str]


class AgentRunActionResponse(_Base):
    run_id: str
    status: str
    changed: bool


class AgentRunCoverDeleteResponse(_Base):
    run_id: str
    deleted: bool


class AgentRunDeleteResponse(_Base):
    run_id: str
    deleted: bool
    title: str | None


class AgentRunCoverResponse(_Base):
    """生成 / 上传封面：cover 是脱敏后的动态字典，原样保留不裁剪。"""

    run_id: str
    cover_url: str | None
    cover: dict[str, Any]


# —— 第十批：订单 / 用量 / 后台列表契约 --------------------------------------
class GetOrderResponse(_Base):
    """用户侧订单详情：复用 OrderView（meta 动态字段保留）。"""

    order: OrderView


class OrderListResponse(_Base):
    """用户侧订单列表：顶层 key 是 orders（不是 items）。"""

    orders: list[OrderView]


class UsageEventView(_Base):
    """用量事件：meta 是事件动态上下文，可能为 None，原样保留不裁剪。"""

    id: int
    task_id: str | None
    metric: str
    quantity: int
    unit: str
    occurred_at: str
    meta: dict[str, Any] | None


class UsageListResponse(_Base):
    items: list[UsageEventView]
    next_before_id: int | None


class AdminSubscriptionView(_Base):
    """后台订阅视图：days_left 是 int（与用户侧 float 不同，分立定义）。"""

    id: int
    account_id: int
    plan_code: str | None
    plan_name: str | None
    status: str
    current_start_at: str
    current_end_at: str
    days_left: int
    seats: int
    provider: str | None
    cancel_at_period_end: bool


class AdminAccountView(_Base):
    """后台用户视图：subscription 内嵌 AdminSubscriptionView 或 None。"""

    id: int
    email: str | None
    phone: str | None
    status: str
    role: str
    created_at: str | None
    subscription: AdminSubscriptionView | None
    devices_count: int


class AdminUsersResponse(_Base):
    items: list[AdminAccountView]
    total: int
    page: int
    page_size: int


class AdminSubscriptionsResponse(_Base):
    items: list[AdminSubscriptionView]
    total: int
    page: int
    page_size: int


class AdminOrderView(_Base):
    """后台订单：meta 可能 None（与用户侧 OrderView 的 dict 非 None 不同）。"""

    id: int
    account_id: int
    amount_cents: int
    currency: str
    status: str
    provider: str
    external_order_no: str | None
    kind: str
    cycle: str
    refunded_cents: int
    created_at: str | None
    paid_at: str | None
    meta: dict[str, Any] | None


class AdminOrdersResponse(_Base):
    items: list[AdminOrderView]
    total: int
    page: int
    page_size: int


class TaskBriefView(_Base):
    """后台任务看板行：Task 与 AgentRun 的合并视图（17 固定字段）。"""

    id: str
    account_id: int
    type: str
    status: str
    progress: int
    error_code: str | None
    error_message: str | None
    attempts: int
    lease_until: str | None
    started_at: str | None
    finished_at: str | None
    created_at: str
    last_activity_at: str | None
    stalled: bool
    source: str
    mode: str | None
    title: str | None


class AdminTasksResponse(_Base):
    items: list[TaskBriefView]
    total: int
    page: int
    page_size: int


class AdminAlertView(_Base):
    """后台告警行：metric/quantity/threshold 从 meta.context 派生，可能 None。"""

    id: int
    account_id: int
    level: str | None
    status: str
    metric: str | None
    quantity: int | float | None
    threshold: int | float | None
    message: str | None
    created_at: str | None


class AdminAlertsResponse(_Base):
    items: list[AdminAlertView]
    total: int
    page: int
    page_size: int
    window_hours: int
    failed_notifications: int
    webhook_failures: int


class AdminTasksDashboardResponse(_Base):
    """任务看板概览：计数 + running/failed 明细（复用 TaskBriefView）。"""

    queue_depth: int
    running_count: int
    failed_count: int
    retryable_count: int
    generated_at: str
    running: list[TaskBriefView]
    failed: list[TaskBriefView]
    by_status: dict[str, int]


class AdminDeadLettersResponse(_Base):
    items: list[TaskBriefView]
    total: int


class AdminTaskReplayRequest(_Base):
    reason: str | None = Field(default=None, max_length=500)
    reset_attempts: bool = True


class AdminTaskReplayResult(_Base):
    task_id: str
    ok: bool
    source: str | None = None
    code: str | None = None


class AdminTaskReplayBatchRequest(_Base):
    task_ids: list[str] = Field(default_factory=list, max_length=100)
    reason: str | None = Field(default=None, max_length=500)


class AdminTaskReplayBatchResponse(_Base):
    items: list[AdminTaskReplayResult]
    succeeded: int
    failed: int


class AdminDashboardTaskView(_Base):
    """兼容旧看板路径的紧凑状态计数。"""

    by_status: dict[str, int]
    queued: int
    running: int
    succeeded: int
    failed: int
    canceled: int


class AdminDashboardResponse(_Base):
    tasks: AdminDashboardTaskView
    alerts: AdminAlertsResponse
    pending_refunds: int
    paid_orders_24h: int


class AdminPerformanceRouteView(_Base):
    path: str
    count: int
    p95_ms: float | None
    p99_ms: float | None
    error_rate: float


class AdminPerformanceResponse(_Base):
    """进程内 HTTP 延迟快照；多 worker 部署时由 Prometheus 聚合更有意义。"""

    generated_at: str
    requests: int
    p95_ms: float | None
    p99_ms: float | None
    error_rate: float
    routes: list[AdminPerformanceRouteView]


class DeliveryMetaSummary(_Base):
    """投递回执摘要：列表页只放计数，完整 receipts 走详情，避免 200 行撑爆响应。"""

    subscribers: int | None = None
    delivered: int | None = None
    expired_count: int | None = None
    receipt_count: int | None = None
    retry_after_seconds: int | None = None
    reason: str | None = None


class AdminNotificationView(_Base):
    """后台投递记录行：meta_summary 是回执摘要，完整 meta 走详情路由。"""

    id: int
    account_id: int
    channel: str | None
    recipient: str | None
    subject: str | None
    template: str | None
    status: str
    attempts: int
    max_attempts: int | None
    last_error: str | None
    next_retry_at: str | None
    provider_message_id: str | None
    meta_summary: DeliveryMetaSummary
    created_at: str
    sent_at: str | None


class AdminNotificationsResponse(_Base):
    items: list[AdminNotificationView]
    total: int
    page: int
    page_size: int


class AdminNotificationDetailView(AdminNotificationView):
    """投递详情：meta 是动态回执字典（receipts/expired/...），原样保留不裁剪。"""

    meta: dict[str, Any]


class AdminNotificationDetailResponse(_Base):
    delivery: AdminNotificationDetailView


# —— 统一技能目录（10 环节）：用户端精简视图 / 管理端完整治理视图 ——

class SkillEntryView(_Base):
    """技能入口：把清单声明的桌面工序、云端技能与 API 合并成可展示的入口。"""

    stages: list[str]
    cloud_skills: list[str]
    api: list[str]


class SkillItemView(_Base):
    """用户端技能卡：只暴露产品语义，不含 ssot/缺口/文件等技术字段。"""

    id: str
    index: int
    name: str
    external: str | None
    trigger: list[str]
    purpose: str
    coverage: str
    available: bool
    entry: SkillEntryView


class SkillsCatalogResponse(_Base):
    items: list[SkillItemView]
    degraded: str | None
    schema_version: str | None
    updated_at: str | None


class AdminSkillItemView(SkillItemView):
    """管理端技能行：在用户端字段上补齐覆盖缺口、写权与注册状态。"""

    gap: str | None
    ssot: str
    writes: list[str]
    next: list[str]
    desktop_note: str
    cloud_note: str
    desktop_files: list[str]
    cloud_files: list[str]
    registered: bool
    reference: str


class AdminSkillsCatalogResponse(_Base):
    items: list[AdminSkillItemView]
    degraded: str | None
    schema_version: str | None
    updated_at: str | None


# —— 第十三批：对账/额度调整/预设/退款/发票稳定出参契约 -----------------------
# 约定：结构固定的字段显式声明；summary/meta 等由业务演进的动态 JSON 保留 Any，
# 避免 response_model 把真实字段裁掉（历史多次踩坑，见 test_openapi_contract）。


class FourLedgerWindowView(_Base):
    start_at: str | None
    end_at: str | None


class FourLedgerSummaryView(_Base):
    orders: int
    anomaly_total: int
    by_code: dict[str, int]


class FourLedgerAnomalyView(_Base):
    order_id: int
    order_no: str
    account_id: int
    code: str
    severity: str
    detail: str


class FourLedgerGroupView(_Base):
    order_id: int
    order_no: str
    external_order_no: str | None
    account_id: int
    kind: str
    provider: str
    amount_cents: int
    created_at: str | None
    paid_at: str | None
    payment: dict[str, Any]
    quota: dict[str, Any]
    invoice: dict[str, Any]
    refund: dict[str, Any]
    anomalies: list[str]


class FourLedgerReconcileResponse(_Base):
    total: int
    window: FourLedgerWindowView
    summary: FourLedgerSummaryView
    groups: list[FourLedgerGroupView]
    anomalies: list[FourLedgerAnomalyView]


class AdminReconcileReportView(_Base):
    id: int
    provider: str
    biz_date: str
    summary: dict[str, Any] | None
    channel_source: str | None


class AdminReconcileReportsResponse(_Base):
    items: list[AdminReconcileReportView]


class AdminQuotaAdjustmentView(_Base):
    id: int
    account_id: int
    metric: str
    quantity: int
    reason: str | None
    actor_id: int | None
    before: int | None
    after: int | None
    created_at: str | None


class AdminQuotaAdjustmentsResponse(_Base):
    items: list[AdminQuotaAdjustmentView]


class AdminQuotaAdjustResponse(_Base):
    """额度调整出参；幂等命中时只返回 duplicate + event_id，其余字段缺省。"""

    adjustment: AdminQuotaAdjustmentView | None = None
    audit: dict[str, Any] | None = None
    duplicate: bool
    event_id: int
    before: int | None = None
    after: int | None = None


class AdminPresetView(_Base):
    id: int
    type: str
    value: str
    label: str
    audience: str
    sort: int
    builtin: bool
    created_at: str | None
    custom: bool
    account_id: int | None


class AdminPresetListResponse(_Base):
    items: list[AdminPresetView]
    total: int
    page: int
    page_size: int
    types: list[str]
    scope: str


class AdminPresetDeleteResponse(_Base):
    deleted: bool
    id: int


class AdminPresetSyncResponse(_Base):
    synced: bool
    inserted: int | None = None
    skipped: int | None = None
    total: int | None = None


class PresetItemView(_Base):
    value: str
    label: str
    audience: list[str]
    custom: bool
    builtin: bool


class PresetsResponse(_Base):
    groups: dict[str, list[PresetItemView]]
    types: list[str]


class PresetCreateResponse(_Base):
    id: int
    type: str
    value: str
    label: str
    custom: bool


class RefundView(_Base):
    id: int
    order_id: int
    amount_cents: int
    currency: str
    status: str
    provider: str
    provider_refund_id: str | None
    reason: str | None
    requested_at: str
    succeeded_at: str | None


class RefundListResponse(_Base):
    items: list[RefundView]
    refunds: list[RefundView]


class InvoiceView(_Base):
    id: int
    order_id: int
    title: str
    tax_no: str | None
    email: str | None
    amount_cents: int
    status: str
    legacy_status: str | None
    note: str | None
    provider: str | None
    provider_invoice_id: str | None
    invoice_url: str | None
    failure_reason: str | None
    created_at: str
    issued_at: str | None


class InvoiceDetailResponse(_Base):
    invoice: InvoiceView


class InvoiceListResponse(_Base):
    invoices: list[InvoiceView]


class AdminInvoiceListResponse(_Base):
    items: list[InvoiceView]
    invoices: list[InvoiceView]
    total: int
    page: int
    page_size: int


# —— 第十三批：Web Push 批量推送 / 回执历史 -----------------------------------

class AdminNotificationBatchRequest(AppModel):
    """批量发送：共享同一条内容，逐账号各自建通知与投递记录。"""

    account_ids: list[int] = Field(min_length=1, max_length=200)
    title: str = Field(min_length=2, max_length=120)
    body: str = Field(min_length=2, max_length=2000)
    channels: list[Literal["inapp", "email", "sms", "push"]] | None = None


class BatchNotificationResultView(_Base):
    account_id: int
    notification_id: int | None
    status: str  # sent / skipped / invalid_account
    detail: str | None


class AdminNotificationBatchResponse(_Base):
    batch_id: str
    total: int
    sent: int
    skipped: int
    results: list[BatchNotificationResultView]


class PushReceiptView(_Base):
    sub_id: int
    status: str
    http_status: int | None = None
    retry_after_seconds: int | None = None
    error: str | None = None


class PushReceiptHistoryView(_Base):
    delivery_id: int
    channel: str
    status: str
    attempts: int
    subscribers: int
    delivered: int
    expired: list[int]
    receipts: list[PushReceiptView]
    retry_after_seconds: int | None
    reason: str | None
    next_retry_at: str | None


class PushReceiptHistoryResponse(_Base):
    delivery: PushReceiptHistoryView


# —— 运维：数据库备份 / 恢复 ——
class BackupNotifyView(_Base):
    enabled: bool = False
    status: str
    reason: str | None = None
    recipients: list[str] = Field(default_factory=list)
    error: str | None = None


class BackupView(_Base):
    id: str
    created_at: str | None = None
    trigger: str
    engine: str
    size_bytes: int
    checksum: str
    email: BackupNotifyView


class BackupListView(_Base):
    items: list[BackupView]


class BackupCreateResponse(_Base):
    item: BackupView


class BackupDeleteResponse(_Base):
    id: str
    deleted: bool


class BackupRestoreRequest(_Base):
    """apply=true 时 confirm 必须精确为 RESTORE，避免误触破坏性恢复。"""

    apply: bool = False
    confirm: str = ""


class BackupRestoreResponse(_Base):
    id: str
    mode: str
    engine: str
    path: str | None = None


# —— 运维：AI 模型消费统计 ——
class ModelUsageRowView(_Base):
    key: str
    label: str
    provider: str
    tokens: int
    cost_cents: int
    calls: int
    account_count: int
    model_count: int


class ModelUsageResponse(_Base):
    generated_at: str
    days: int
    group_by: str
    total_tokens: int
    total_cost_cents: int
    total_calls: int
    scanned_rows: int
    truncated: bool
    items: list[ModelUsageRowView]
