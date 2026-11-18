# -*- coding: utf-8 -*-
"""通知：额度不足/支付成功钩子、幂等、邮件 fake 通道、重试、管理端记录。"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.db import utcnow
from app.models import Account, Notification, NotificationDelivery, WebPushSubscription
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


_PUSH_KEYS = {"p256dh": "BPx-p256dh-key", "auth": "auth-secret-b64"}


def _enable_push(app, settings) -> None:
    settings.notification_push_enabled = True
    settings.vapid_private_key = "dGVzdC1wcml2YXRlLWtleQ"
    settings.vapid_public_key = "test-public-key"
    settings.vapid_subject = "mailto:admin@example.com"


def test_push_subscription_upsert_and_delete(client, headers, app, account):
    """上报/去重/退订：endpoint 复用同一行，退订只软删不影响他人。"""
    account_id = account["account"]["id"]
    payload = {
        "endpoint": "https://push.example.com/sub/abc123",
        "keys": _PUSH_KEYS,
        "device_label": "Chrome",
    }
    first = client.post(
        "/v1/notifications/push-subscriptions", headers=headers, json=payload
    )
    assert first.status_code == 200, first.text
    assert len(first.json()["items"]) == 1
    assert first.json()["items"][0]["device_label"] == "Chrome"

    # 再上报一次：endpoint 相同仍只有一条，且能复活 expired
    with app.state.db.session() as session:
        row = session.scalar(select(WebPushSubscription))
        row.status = "expired"
        session.commit()
    second = client.post(
        "/v1/notifications/push-subscriptions", headers=headers, json=payload
    )
    assert second.status_code == 200
    assert len(second.json()["items"]) == 1
    assert second.json()["items"][0]["status"] == "active"

    # 退订后列表为空
    removed = client.delete(
        "/v1/notifications/push-subscriptions",
        headers=headers,
        params={"endpoint": payload["endpoint"]},
    )
    assert removed.status_code == 200
    assert removed.json()["items"] == []
    with app.state.db.session() as session:
        row = session.scalar(select(WebPushSubscription))
        assert row.status == "unsubscribed"
        assert row.account_id == account_id


def test_push_subscription_cannot_be_stolen_by_other_account(client, headers):
    """endpoint 是推送凭据：其他账号重复上报不得静默改绑订阅归属。"""
    payload = {"endpoint": "https://push.example.com/owned", "keys": _PUSH_KEYS}
    first = client.post("/v1/notifications/push-subscriptions", headers=headers, json=payload)
    assert first.status_code == 200, first.text

    other = client.post(
        "/v1/auth/register",
        json={"email": "other@example.com", "password": "password123"},
    )
    assert other.status_code == 201, other.text
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}
    stolen = client.post(
        "/v1/notifications/push-subscriptions", headers=other_headers, json=payload
    )
    assert stolen.status_code == 409
    assert stolen.json()["error"]["code"] == "subscription_owned_by_other"


def test_push_subscription_rejects_http_endpoint(client, headers):
    """endpoint 必须 https，防止被用来探测内网。"""
    response = client.post(
        "/v1/notifications/push-subscriptions",
        headers=headers,
        json={
            "endpoint": "http://127.0.0.1:8080/push",
            "keys": _PUSH_KEYS,
        },
    )
    assert response.status_code == 422


def test_push_delivery_sends_to_all_subscriptions(client, app, account):
    """emit 默认渠道在 push 配置齐全时纳入 push，逐订阅发送并落发送记录。"""
    settings = app.state.settings
    _enable_push(app, settings)
    account_id = account["account"]["id"]
    with app.state.db.session() as session:
        nsvc.upsert_subscription(
            session,
            account_id=account_id,
            endpoint="https://push.example.com/a",
            p256dh=_PUSH_KEYS["p256dh"],
            auth=_PUSH_KEYS["auth"],
        )
        nsvc.upsert_subscription(
            session,
            account_id=account_id,
            endpoint="https://push.example.com/b",
            p256dh=_PUSH_KEYS["p256dh"],
            auth=_PUSH_KEYS["auth"],
        )
        session.commit()

    with patch.object(nsvc.webpush, "send_web_push", return_value="push-stub") as send:
        with app.state.db.session() as session:
            note = nsvc.emit(
                session,
                account_id=account_id,
                category="admin_message",
                dedupe_key="admin:push-test",
                context={"title": "推送测试", "body": "正文"},
                settings=settings,
                channels=("inapp", "push"),
            )
            delivery = session.scalar(
                select(NotificationDelivery).where(
                    NotificationDelivery.notification_id == note.id,
                    NotificationDelivery.channel == "push",
                )
            )
            assert delivery.status == "sent"
            assert delivery.meta["subscribers"] == 2 and delivery.meta["delivered"] == 2
            assert send.call_count == 2
            payload = send.call_args_list[0].kwargs["payload"]
            assert payload["title"] == "推送测试"
            assert payload["url"] == "/"
            session.commit()


def test_push_delivery_skipped_when_unconfigured(client, app, account):
    """未配置 VAPID 私钥/开关时 push 通道只写 skipped，不抛错。"""
    settings = app.state.settings
    settings.notification_push_enabled = False
    with app.state.db.session() as session:
        note = nsvc.emit(
            session,
            account_id=account["account"]["id"],
            category="admin_message",
            dedupe_key="admin:push-skip",
            context={"title": "T", "body": "B"},
            settings=settings,
            channels=("push",),
        )
        delivery = session.scalar(
            select(NotificationDelivery).where(NotificationDelivery.notification_id == note.id)
        )
        assert delivery.status == "skipped"
        assert delivery.meta["reason"] == "push_disabled"
        session.commit()


def _push_exception(status_code: int | None, retry_after: str | None = None):
    """构造带真实 WebPushException 语义的异常（含 .status_code / .retry_after）。"""
    from pywebpush import WebPushException

    response = None
    if status_code:
        headers = {"Retry-After": retry_after} if retry_after else {}
        response = type("Response", (), {"status_code": status_code, "headers": headers})()
    return WebPushException("push failed", response=response)


def test_push_delivery_expired_subscription_cleaned(client, app, account):
    """410 用真实 WebPushException：订阅下线并记回执，全失效时 skipped 不做无效重试。"""
    settings = app.state.settings
    _enable_push(app, settings)
    account_id = account["account"]["id"]
    with app.state.db.session() as session:
        nsvc.upsert_subscription(
            session,
            account_id=account_id,
            endpoint="https://push.example.com/gone",
            p256dh=_PUSH_KEYS["p256dh"],
            auth=_PUSH_KEYS["auth"],
        )
        session.commit()

    with patch.object(nsvc.webpush, "send_web_push", side_effect=_push_exception(410)):
        with app.state.db.session() as session:
            note = nsvc.emit(
                session,
                account_id=account_id,
                category="admin_message",
                dedupe_key="admin:push-gone",
                context={"title": "T", "body": "B"},
                settings=settings,
                channels=("push",),
            )
            delivery = session.scalar(
                select(NotificationDelivery).where(NotificationDelivery.notification_id == note.id)
            )
            assert delivery.status == "skipped"
            assert delivery.meta["reason"] == "all_subscriptions_expired"
            assert delivery.next_retry_at is None
            assert delivery.meta["expired"] and delivery.meta["receipts"][0]["http_status"] == 410
            sub = session.scalar(select(WebPushSubscription))
            assert sub.status == "expired"
            assert sub.updated_at is not None
            session.commit()


def test_push_delivery_404_also_expires(client, app, account):
    """404 Not Found 与 410 同样下线订阅。"""
    settings = app.state.settings
    _enable_push(app, settings)
    with app.state.db.session() as session:
        nsvc.upsert_subscription(
            session, account_id=account["account"]["id"],
            endpoint="https://push.example.com/notfound",
            p256dh=_PUSH_KEYS["p256dh"], auth=_PUSH_KEYS["auth"],
        )
        session.commit()
    with patch.object(nsvc.webpush, "send_web_push", side_effect=_push_exception(404)):
        with app.state.db.session() as session:
            nsvc.emit(
                session, account_id=account["account"]["id"],
                category="admin_message", dedupe_key="admin:push-404",
                context={"title": "T", "body": "B"}, settings=settings, channels=("push",),
            )
            sub = session.scalar(select(WebPushSubscription))
            assert sub.status == "expired"
            session.commit()


@pytest.mark.parametrize("status", [429, 500, 503])
def test_push_delivery_transient_http_error_keeps_subscription(client, app, account, status):
    """429/5xx 是可恢复失败：订阅保留、delivery 进入退避重试。"""
    settings = app.state.settings
    _enable_push(app, settings)
    with app.state.db.session() as session:
        nsvc.upsert_subscription(
            session, account_id=account["account"]["id"],
            endpoint="https://push.example.com/transient",
            p256dh=_PUSH_KEYS["p256dh"], auth=_PUSH_KEYS["auth"],
        )
        session.commit()
    with patch.object(nsvc.webpush, "send_web_push", side_effect=_push_exception(status)):
        with app.state.db.session() as session:
            nsvc.emit(
                session, account_id=account["account"]["id"],
                category="admin_message", dedupe_key=f"admin:push-{status}",
                context={"title": "T", "body": "B"}, settings=settings, channels=("push",),
            )
            delivery = session.scalar(
                select(NotificationDelivery).where(NotificationDelivery.channel == "push")
                .order_by(NotificationDelivery.id.desc())
            )
            assert delivery.status == "failed"
            assert delivery.next_retry_at is not None
            assert delivery.meta["expired"] == []
            assert delivery.meta["receipts"][0]["http_status"] == status
            sub = session.scalar(select(WebPushSubscription))
            assert sub.status == "active"
            session.commit()


def test_push_delivery_no_status_exception_keeps_subscription(client, app, account):
    """无 status_code 的异常（密钥错误/网络故障）不误清理订阅。"""
    settings = app.state.settings
    _enable_push(app, settings)
    with app.state.db.session() as session:
        nsvc.upsert_subscription(
            session, account_id=account["account"]["id"],
            endpoint="https://push.example.com/no-status",
            p256dh=_PUSH_KEYS["p256dh"], auth=_PUSH_KEYS["auth"],
        )
        session.commit()
    with patch.object(nsvc.webpush, "send_web_push", side_effect=RuntimeError("key error")):
        with app.state.db.session() as session:
            nsvc.emit(
                session, account_id=account["account"]["id"],
                category="admin_message", dedupe_key="admin:push-no-status",
                context={"title": "T", "body": "B"}, settings=settings, channels=("push",),
            )
            delivery = session.scalar(
                select(NotificationDelivery).where(NotificationDelivery.channel == "push")
                .order_by(NotificationDelivery.id.desc())
            )
            assert delivery.status == "failed"
            assert delivery.meta["receipts"][0]["status"] == "failed"
            assert "http_status" not in delivery.meta["receipts"][0]
            sub = session.scalar(select(WebPushSubscription))
            assert sub.status == "active"
            session.commit()


def test_push_delivery_partial_expiry_receipts(client, app, account):
    """多订阅混合：一个 410 下线、一个成功，回执逐条记录且只下线失效那条。"""
    settings = app.state.settings
    _enable_push(app, settings)
    account_id = account["account"]["id"]
    with app.state.db.session() as session:
        for ep in ("https://push.example.com/gone", "https://push.example.com/alive"):
            nsvc.upsert_subscription(
                session, account_id=account_id, endpoint=ep,
                p256dh=_PUSH_KEYS["p256dh"], auth=_PUSH_KEYS["auth"],
            )
        session.commit()

    def fake_send(*, endpoint, **kwargs):
        if endpoint.endswith("/gone"):
            raise _push_exception(410)
        return "push-ok"

    with patch.object(nsvc.webpush, "send_web_push", side_effect=fake_send):
        with app.state.db.session() as session:
            nsvc.emit(
                session, account_id=account_id, category="admin_message",
                dedupe_key="admin:push-partial", context={"title": "T", "body": "B"},
                settings=settings, channels=("push",),
            )
            delivery = session.scalar(
                select(NotificationDelivery).where(NotificationDelivery.channel == "push")
                .order_by(NotificationDelivery.id.desc())
            )
            assert delivery.status == "sent"  # 部分成功记 sent，避免重复给成功设备发第二遍
            assert delivery.meta["subscribers"] == 2
            assert delivery.meta["delivered"] == 1
            assert len(delivery.meta["expired"]) == 1
            statuses = {r["status"] for r in delivery.meta["receipts"]}
            assert statuses == {"expired", "sent"}
            rows = session.scalars(
                select(WebPushSubscription).order_by(WebPushSubscription.id)
            ).all()
            assert {r.endpoint.rsplit("/", 1)[-1]: r.status for r in rows} == {
                "gone": "expired", "alive": "active"
            }
            session.commit()


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


# ---- 第十批：429 Retry-After 退避 + 回执可视化 ------------------------------
@pytest.mark.parametrize(
    "header, expected",
    [
        ("120", 120),                      # 纯秒数
        ("0", 0),                          # 0 立即重试
        ("-5", None),                      # 负数不采信
        ("garbage", None),                 # 非法串不采信
        ("999999", 3600),                  # cap 夹紧
    ],
)
def test_retry_after_parse_numeric(header, expected):
    """Retry-After 纯秒数解析：负数/非法串忽略，超大值被 cap 夹紧。"""
    from app.services import webpush

    exc = _push_exception(429, retry_after=header)
    assert webpush.error_retry_after_seconds(exc, cap_seconds=3600) == expected


def test_retry_after_parse_http_date():
    """Retry-After HTTP-date 解析为相对秒数（含时区）。"""
    from datetime import timedelta

    from app.services import webpush

    now = utcnow()
    future = now + timedelta(seconds=90)
    http_date = future.strftime("%a, %d %b %Y %H:%M:%S GMT")
    exc = _push_exception(429, retry_after=http_date)
    value = webpush.error_retry_after_seconds(exc, cap_seconds=3600, now=now)
    assert value is not None and 85 <= value <= 95  # 允许取整误差


def test_retry_after_only_for_429():
    """非 429（含 503 与无状态码）不采信 Retry-After，避免误伤正常退避。"""
    from app.services import webpush

    assert webpush.error_retry_after_seconds(_push_exception(503, retry_after="30")) is None
    assert webpush.error_retry_after_seconds(_push_exception(None, retry_after="30")) is None


def test_push_429_retry_after_drives_backoff(client, app, account):
    """429 + Retry-After 时 next_retry_at 用服务端建议值，而非固定 300s。"""
    settings = app.state.settings
    _enable_push(app, settings)
    account_id = account["account"]["id"]
    with app.state.db.session() as session:
        nsvc.upsert_subscription(
            session, account_id=account_id, endpoint="https://push.example.com/throttled",
            p256dh=_PUSH_KEYS["p256dh"], auth=_PUSH_KEYS["auth"],
        )
        session.commit()

    before = utcnow()
    with patch.object(nsvc.webpush, "send_web_push", side_effect=_push_exception(429, "42")):
        with app.state.db.session() as session:
            note = nsvc.emit(
                session, account_id=account_id, category="admin_message",
                dedupe_key="admin:push-429", context={"title": "T", "body": "B"},
                settings=settings, channels=("push",),
            )
            delivery = session.scalar(
                select(NotificationDelivery).where(NotificationDelivery.notification_id == note.id)
            )
            assert delivery.status == "failed"
            assert delivery.next_retry_at is not None
            elapsed = (delivery.next_retry_at - before).total_seconds()
            assert 40 <= elapsed <= 45  # 用 42s 建议值，而非默认 300s
            assert delivery.meta["retry_after_seconds"] == 42
            assert delivery.meta["receipts"][0]["retry_after_seconds"] == 42
            # 429 不清退订阅
            sub = session.scalar(select(WebPushSubscription))
            assert sub.status == "active"
            session.commit()


def test_push_5xx_falls_back_to_config_backoff(client, app, account):
    """5xx 无 Retry-After 时回退固定退避（300s），保持既有语义。"""
    settings = app.state.settings
    _enable_push(app, settings)
    account_id = account["account"]["id"]
    with app.state.db.session() as session:
        nsvc.upsert_subscription(
            session, account_id=account_id, endpoint="https://push.example.com/err",
            p256dh=_PUSH_KEYS["p256dh"], auth=_PUSH_KEYS["auth"],
        )
        session.commit()

    before = utcnow()
    with patch.object(nsvc.webpush, "send_web_push", side_effect=_push_exception(503)):
        with app.state.db.session() as session:
            note = nsvc.emit(
                session, account_id=account_id, category="admin_message",
                dedupe_key="admin:push-503", context={"title": "T", "body": "B"},
                settings=settings, channels=("push",),
            )
            delivery = session.scalar(
                select(NotificationDelivery).where(NotificationDelivery.notification_id == note.id)
            )
            elapsed = (delivery.next_retry_at - before).total_seconds()
            assert 298 <= elapsed <= 302
            assert delivery.meta["retry_after_seconds"] is None
            session.commit()


def test_admin_notification_detail_returns_full_receipts(client, headers, app, account):
    """后台详情路由返回完整 receipts/expired，列表仅返回摘要。"""
    _promote(app, account["account"]["id"], "admin")
    settings = app.state.settings
    _enable_push(app, settings)
    account_id = account["account"]["id"]
    with app.state.db.session() as session:
        sub = nsvc.upsert_subscription(
            session, account_id=account_id, endpoint="https://push.example.com/detail",
            p256dh=_PUSH_KEYS["p256dh"], auth=_PUSH_KEYS["auth"],
        )
        session.commit()
        sub_id = sub.id

    with patch.object(nsvc.webpush, "send_web_push", side_effect=_push_exception(410)):
        with app.state.db.session() as session:
            note = nsvc.emit(
                session, account_id=account_id, category="admin_message",
                dedupe_key="admin:push-detail", context={"title": "T", "body": "B"},
                settings=settings, channels=("push",),
            )
            delivery = session.scalar(
                select(NotificationDelivery).where(NotificationDelivery.notification_id == note.id)
            )
            delivery_id = delivery.id
            session.commit()

    listing = client.get("/v1/admin/notifications", headers=headers).json()
    row = next(r for r in listing["items"] if r["id"] == delivery_id)
    assert set(row["meta_summary"]) == {
        "subscribers", "delivered", "expired_count", "receipt_count",
        "retry_after_seconds", "reason",
    }
    assert row["meta_summary"]["expired_count"] == 1
    assert "receipts" not in row  # 列表不返回完整回执

    detail = client.get(f"/v1/admin/notifications/{delivery_id}", headers=headers).json()
    assert set(detail) == {"delivery"}
    d = detail["delivery"]
    assert d["meta"]["expired"] == [sub_id]
    assert d["meta"]["receipts"][0]["http_status"] == 410
    assert d["next_retry_at"] is None  # skipped 无下次重试
