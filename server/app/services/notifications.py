# -*- coding: utf-8 -*-
"""通知通道：站内信 + 邮件（SMTP）+ 可选短信适配位。

设计要点：
  · 幂等：notification (account_id, dedupe_key) 唯一；delivery (channel, dedupe_key) 唯一；
  · 可开关：NOTIFICATIONS_ENABLED / NOTIFICATION_EMAIL_ENABLED / NOTIFICATION_SMS_ENABLED；
  · 无凭据时 no-op：短信只写 skipped；邮件未配置 SMTP 也写 skipped，不抛错；
  · 失败重试：failed + attempts < max_attempts 的记录由 scheduler 按退避重投；
  · 敏感信息不入库：正文只包含额度/金额/订单号，不含密钥或凭据。
"""

from __future__ import annotations

import logging
import smtplib
from datetime import datetime, timedelta
from email.message import EmailMessage
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..db import utcnow
from ..models import Account, Notification, NotificationDelivery

logger = logging.getLogger("moxie.notifications")

# 模板：{key} 占位符；标题与正文都走这里，便于统一改文案
TEMPLATES: dict[str, dict[str, str]] = {
    "subscription_renewal_reminder": {
        "title": "订阅即将到期",
        "body": "你的订阅将在 {days_left} 天后到期（{current_end_at}）。如需继续使用，请及时续费。",
        "level": "warning",
    },
    "subscription_expired": {
        "title": "订阅已到期",
        "body": "订阅已到期（{current_end_at}），托管能力已暂停。手动续费或重新购买后可恢复。",
        "level": "warning",
    },
    "payment_succeeded": {
        "title": "支付成功",
        "body": "订单 {order_no} 已支付成功，金额 {amount} 元，权益已开通。",
        "level": "info",
    },
    "payment_failed": {
        "title": "支付失败",
        "body": "订单 {order_no} 支付失败（{reason}），本次不会扣费，可重新发起支付。",
        "level": "error",
    },
    "quota_insufficient": {
        "title": "额度不足",
        "body": "当前 {metric} 额度不足：套餐上限 {limit}，已用 {used}，预占 {reserved}，剩余 {remaining}，本次需要 {requested}。可购买额度包继续使用。",
        "level": "warning",
    },
    "usage_anomaly": {
        "title": "用量异常提醒",
        "body": "检测到 {metric} 今日用量 {used_today} 超过阈值 {threshold}（月额度 {limit}）。仅提醒，不会自动封禁。",
        "level": "warning",
    },
    "credit_pack_expiring": {
        "title": "额度包即将到期",
        "body": "你的额度包将在 {days_left} 天后到期（剩余 {remaining}），到期后剩余额度作废且不结转。",
        "level": "warning",
    },
    "admin_message": {
        "title": "{title}",
        "body": "{body}",
        "level": "info",
    },
}


def _render(category: str, context: dict[str, Any]) -> tuple[str, str, str]:
    template = TEMPLATES.get(category)
    if template is None:
        raise ValueError(f"未知通知模板：{category}")
    safe = {key: context.get(key, "") for key in context}
    return (
        template["title"].format_map(_SafeDict(safe))[:120],
        template["body"].format_map(_SafeDict(safe))[:2000],
        template.get("level", "info"),
    )


class _SafeDict(dict):
    def __missing__(self, key):  # noqa: ANN001 - 模板占位缺失时留空，避免整条通知失败
        return ""


def _deliver(
    delivery: NotificationDelivery, settings: Settings | None, now: datetime, *, forced: bool = False
) -> None:
    """执行一次发送；结果写回 delivery。异常不外抛。

    forced=True 时忽略全局 NOTIFICATION_EMAIL_ENABLED 开关（验证码邮件等关键邮件
    必须发出，不能因普通营销邮件开关被关而静默跳过），但仍受 NOTIFICATIONS_ENABLED 总开关约束。
    """
    if settings is None:
        delivery.status = "skipped"
        delivery.meta = {**(delivery.meta or {}), "reason": "settings_unavailable"}
        return
    if not settings.notifications_enabled:
        delivery.status = "skipped"
        delivery.meta = {**(delivery.meta or {}), "reason": "notifications_disabled"}
        return

    if delivery.channel == "inapp":
        delivery.status = "sent"
        delivery.sent_at = now
        return

    if delivery.channel == "email":
        if not (forced or settings.notification_email_enabled):
            delivery.status = "skipped"
            delivery.meta = {**(delivery.meta or {}), "reason": "email_disabled"}
            return
        if settings.notification_email_transport == "fake":
            delivery.status = "sent"
            delivery.sent_at = now
            delivery.provider_message_id = f"fake-email-{delivery.id}"
            return
        if not settings.smtp_host:
            delivery.status = "skipped"
            delivery.meta = {**(delivery.meta or {}), "reason": "smtp_not_configured"}
            return
        try:
            message = EmailMessage()
            message["Subject"] = delivery.subject
            message["From"] = settings.smtp_from
            message["To"] = delivery.recipient
            message.set_content(delivery.body)
            with smtplib.SMTP(
                settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout_seconds
            ) as smtp:
                if settings.smtp_use_tls:
                    smtp.starttls()
                if settings.smtp_user:
                    smtp.login(settings.smtp_user, settings.smtp_password)
                smtp.send_message(message)
            delivery.status = "sent"
            delivery.sent_at = now
        except Exception as exc:  # noqa: BLE001 - 发送失败进入重试队列
            logger.warning("邮件发送失败 delivery=%s error=%s", delivery.id, type(exc).__name__)
            delivery.status = "failed"
            delivery.last_error = f"{type(exc).__name__}: {str(exc)[:200]}"
        return

    if delivery.channel == "sms":
        if not settings.notification_sms_enabled or settings.sms_provider == "noop":
            delivery.status = "skipped"
            delivery.meta = {**(delivery.meta or {}), "reason": "sms_provider_not_configured"}
            return
        # 适配位：接入真实短信服务时在这里替换
        delivery.status = "sent"
        delivery.sent_at = now
        delivery.provider_message_id = f"sms-{delivery.id}"
        return


def emit(
    session: Session,
    *,
    account_id: int,
    category: str,
    dedupe_key: str,
    context: dict[str, Any] | None = None,
    settings: Settings | None = None,
    channels: tuple[str, ...] | None = None,
    now: datetime | None = None,
) -> Notification | None:
    """创建站内信并按渠道投递；重复 dedupe_key 直接返回已有消息。"""
    now = now or utcnow()
    context = context or {}
    base = f"{account_id}:{dedupe_key}"

    existing = session.scalar(
        select(Notification).where(
            Notification.account_id == account_id, Notification.dedupe_key == base
        )
    )
    if existing is not None:
        return existing

    title, body, level = _render(category, context)
    account = session.get(Account, account_id)
    notification = Notification(
        account_id=account_id,
        category=category,
        title=title,
        body=body,
        level=level,
        status="unread",
        dedupe_key=base,
        meta={"context": context},
        created_at=now,
    )
    session.add(notification)
    session.flush()

    if channels is None:
        channels = ("inapp", "email" if account and account.email else None)
        channels = tuple(c for c in channels if c)
    else:
        channels = tuple(c for c in channels if c)

    for channel in dict.fromkeys(channels):
        recipient = account.email if channel == "email" else (
            account.phone if channel == "sms" else None
        )
        if channel in ("email", "sms") and not recipient:
            continue
        delivery = NotificationDelivery(
            notification_id=notification.id,
            account_id=account_id,
            channel=channel,
            category=category,
            recipient=recipient,
            subject=title,
            body=body,
            status="queued",
            attempts=0,
            max_attempts=(settings.notification_max_attempts if settings else 3),
            dedupe_key=f"{base}:{channel}",
            meta={},
        )
        session.add(delivery)
        session.flush()
        _deliver(delivery, settings, now)
        if delivery.status == "failed" and settings:
            delivery.attempts = 1
            delivery.next_retry_at = now + timedelta(
                seconds=settings.notification_retry_backoff_seconds
            )
    session.flush()
    return notification


def retry_deliveries(session: Session, settings: Settings, now: datetime | None = None) -> int:
    """重投失败邮件/短信；幂等：成功或超过最大次数后不再重试。"""
    now = now or utcnow()
    rows = session.scalars(
        select(NotificationDelivery).where(
            NotificationDelivery.status == "failed",
            NotificationDelivery.attempts < NotificationDelivery.max_attempts,
            NotificationDelivery.next_retry_at.isnot(None),
            NotificationDelivery.next_retry_at <= now,
        )
    ).all()
    for delivery in rows:
        delivery.attempts += 1
        _deliver(delivery, settings, now)
        if delivery.status == "failed":
            delivery.next_retry_at = now + timedelta(
                seconds=settings.notification_retry_backoff_seconds * delivery.attempts
            )
        else:
            delivery.next_retry_at = None
    if rows:
        session.flush()
    return len(rows)


def list_for_account(session: Session, account_id: int, limit: int = 50, unread_only: bool = False) -> list[Notification]:
    query = select(Notification).where(Notification.account_id == account_id)
    if unread_only:
        query = query.where(Notification.status == "unread")
    return list(session.scalars(query.order_by(Notification.id.desc()).limit(limit)).all())


def mark_read(session: Session, notification: Notification, now: datetime | None = None) -> None:
    if notification.status != "read":
        notification.status = "read"
        notification.read_at = now or utcnow()
        session.flush()


def mark_all_read(session: Session, account_id: int, now: datetime | None = None) -> int:
    rows = list_for_account(session, account_id, limit=500, unread_only=True)
    now = now or utcnow()
    for row in rows:
        row.status = "read"
        row.read_at = now
    if rows:
        session.flush()
    return len(rows)


def send_verification_email(
    session: Session,
    *,
    account: Account,
    subject: str,
    body: str,
    settings: Settings | None,
    dedupe_key: str,
) -> NotificationDelivery | None:
    """发送邮箱验证码/验证邮件：绕过全局 email 开关，只要配置了 SMTP 就尽量投递。

    返回 delivery；调用方据 delivery.status == "sent" 判断是否真正发出（未配置 SMTP
    时为 skipped，便于上层在开发环境把验证链接直接返回给前端）。
    """
    now = utcnow()
    if not account or not account.email:
        return None
    delivery = NotificationDelivery(
        account_id=account.id,
        channel="email",
        category="email_verification",
        recipient=account.email,
        subject=subject[:200],
        body=body,
        status="queued",
        attempts=0,
        max_attempts=(settings.notification_max_attempts if settings else 3),
        dedupe_key=dedupe_key,
        meta={},
    )
    session.add(delivery)
    session.flush()
    _deliver(delivery, settings, now, forced=True)
    return delivery
