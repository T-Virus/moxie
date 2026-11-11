# -*- coding: utf-8 -*-
"""通知：额度不足/支付成功钩子、幂等、邮件 fake 通道、重试、管理端记录。"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.db import utcnow
from app.models import Account, Notification, NotificationDelivery
from app.services import notifications as nsvc
from app.services.quota import QuotaService

from .helpers import subscribe


def _promote(app, account_id: int, role: str) -> None:
    with app.state.db.session() as session:
        row = session.get(Account, account_id)
        row.role = role
        session.commit()


def test_quota_exceeded_emits_inapp(client, headers, app, account):
    subscribe(client, headers)
    with app.state.db.session() as session:
        quota = QuotaService(session)
        with pytest.raises(Exception) as exc:
            quota.reserve(account["account"]["id"], "books_month", 6)
        assert getattr(exc.value, "code", "") == "quota_exceeded"
        note = session.scalar(select(Notification).where(Notification.category == "quota_insufficient"))
        assert note is not None and note.account_id == account["account"]["id"]
        session.commit()

    listed = client.get("/v1/notifications", headers=headers).json()
    assert listed["unread_count"] >= 1
    assert any(item["category"] == "quota_insufficient" for item in listed["items"])


def test_payment_success_notification_dedup(client, headers, app, account):
    subscribe(client, headers)
    with app.state.db.session() as session:
        notes = session.scalars(
            select(Notification).where(Notification.category == "payment_succeeded")
        ).all()
        assert len(notes) == 1
        assert "已支付成功" in notes[0].body


def test_email_fake_channel_and_retry(client, app, account):
    settings = app.state.settings
    settings.notification_email_enabled = True
    settings.notification_email_transport = "fake"
    account_id = account["account"]["id"]

    with app.state.db.session() as session:
        note = nsvc.emit(
            session,
            account_id=account_id,
            category="admin_message",
            dedupe_key="admin:test-1",
            context={"title": "维护通知", "body": "今晚 22:00 短暂维护"},
            settings=settings,
            channels=("inapp", "email"),
        )
        deliveries = session.scalars(
            select(NotificationDelivery).where(NotificationDelivery.notification_id == note.id)
        ).all()
        by_channel = {d.channel: d for d in deliveries}
        assert by_channel["inapp"].status == "sent"
        assert by_channel["email"].status == "sent"
        assert by_channel["email"].provider_message_id.startswith("fake-email-")

        # 模拟一次失败后重试
        email = by_channel["email"]
        email.status = "failed"
        email.attempts = 1
        email.last_error = "SMTPTimeout"
        email.next_retry_at = utcnow() - timedelta(seconds=1)
        session.flush()
        retried = nsvc.retry_deliveries(session, settings)
        assert retried == 1
        assert email.status == "sent" and email.attempts == 2
        session.commit()


def test_notification_dedupe_is_idempotent(client, app, account):
    account_id = account["account"]["id"]
    with app.state.db.session() as session:
        first = nsvc.emit(
            session, account_id=account_id, category="admin_message",
            dedupe_key="admin:dup", context={"title": "T", "body": "B"},
        )
        second = nsvc.emit(
            session, account_id=account_id, category="admin_message",
            dedupe_key="admin:dup", context={"title": "T", "body": "B"},
        )
        assert first.id == second.id
        session.commit()
        count = len(session.scalars(select(Notification).where(Notification.dedupe_key.endswith("admin:dup"))).all())
        assert count == 1


def test_admin_delivery_records_roles(client, headers, app, account):
    _promote(app, account["account"]["id"], "support")
    response = client.get("/v1/admin/notification-deliveries", headers=headers)
    assert response.status_code == 200, response.text
    assert "items" in response.json()

    response = client.get("/v1/admin/users", headers=headers)
    assert response.status_code == 200

    # support 不能执行写操作
    response = client.post(
        f"/v1/admin/accounts/{account['account']['id']}/quota-adjustments",
        headers=headers,
        json={"metric": "books_month", "quantity": 1, "reason": "support-should-fail"},
    )
    assert response.status_code == 403
