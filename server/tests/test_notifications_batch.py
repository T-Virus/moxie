# -*- coding: utf-8 -*-
"""第十三批：Web Push 批量推送 + 回执历史。"""

from __future__ import annotations

from unittest.mock import patch

from sqlalchemy import select

from app.models import Account, Notification, NotificationDelivery
from app.services import notifications as nsvc

from .helpers import db_session
from .test_notifications import _PUSH_KEYS, _promote, _push_exception


_BATCH_BODY = {"title": "批量通知", "body": "这是一条批量推送正文", "channels": ["inapp", "push"]}


def test_batch_send_creates_per_account_deliveries(client, headers, app, account):
    _promote(app, account["account"]["id"], "admin")
    with db_session(app) as session:
        other = Account(email="batch-other@example.com", password_hash="x", role="user", status="active")
        session.add(other)
        session.commit()
        other_id = other.id

    response = client.post(
        "/v1/admin/notifications/batch",
        headers=headers,
        json={**_BATCH_BODY, "account_ids": [account["account"]["id"], other_id, 999999]},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["total"] == 3 and data["sent"] == 2 and data["skipped"] == 1
    assert data["batch_id"].startswith("batch-")
    results = {r["account_id"]: r for r in data["results"]}
    assert results[999999]["status"] == "invalid_account"
    assert results[account["account"]["id"]]["status"] == "sent"

    with db_session(app) as session:
        notes = session.scalars(
            select(Notification).where(Notification.category == "admin_message")
        ).all()
        assert len(notes) == 2
        # 每账号独立 dedupe_key（都带 batch_id 前缀），互不覆盖
        keys = {n.dedupe_key for n in notes}
        assert len(keys) == 2
        assert all(data["batch_id"] in k for k in keys)
        deliveries = session.scalars(select(NotificationDelivery)).all()
        assert len(deliveries) >= 2


def test_batch_send_is_idempotent_by_dedupe_key(client, headers, app, account):
    """单账号重复出现在批次里只发一次（account_ids 去重）。"""
    _promote(app, account["account"]["id"], "admin")
    aid = account["account"]["id"]
    body = {**_BATCH_BODY, "channels": ["inapp"], "account_ids": [aid, aid]}
    response = client.post("/v1/admin/notifications/batch", headers=headers, json=body)
    assert response.status_code == 200
    assert response.json()["total"] == 1 and response.json()["sent"] == 1


def test_batch_send_rejects_non_admin(client, headers, app, account):
    response = client.post(
        "/v1/admin/notifications/batch",
        headers=headers,
        json={**_BATCH_BODY, "account_ids": [account["account"]["id"]]},
    )
    assert response.status_code == 403


def test_receipt_history_structured(client, headers, app, account):
    _promote(app, account["account"]["id"], "admin")
    settings = app.state.settings
    settings.notification_push_enabled = True
    settings.vapid_private_key = "test-private-key"
    settings.vapid_subject = "mailto:admin@example.com"
    aid = account["account"]["id"]
    with db_session(app) as session:
        nsvc.upsert_subscription(
            session, account_id=aid, endpoint="https://push.example.com/history",
            p256dh=_PUSH_KEYS["p256dh"], auth=_PUSH_KEYS["auth"],
        )
        session.commit()

    with patch.object(nsvc.webpush, "send_web_push", side_effect=_push_exception(410)):
        with db_session(app) as session:
            note = nsvc.emit(
                session, account_id=aid, category="admin_message",
                dedupe_key="admin:history-test", context={"title": "T", "body": "B"},
                settings=settings, channels=("push",),
            )
            delivery = session.scalar(
                select(NotificationDelivery).where(NotificationDelivery.notification_id == note.id)
            )
            delivery_id = delivery.id
            session.commit()

    response = client.get(f"/v1/admin/notifications/{delivery_id}/receipts", headers=headers)
    assert response.status_code == 200, response.text
    d = response.json()["delivery"]
    assert d["delivery_id"] == delivery_id and d["channel"] == "push"
    assert d["subscribers"] == 1 and d["delivered"] == 0
    assert len(d["expired"]) == 1
    assert d["receipts"][0]["status"] == "expired"
    assert d["receipts"][0]["http_status"] == 410
    assert d["reason"] == "all_subscriptions_expired"


def test_receipt_history_missing_delivery_404(client, headers, app, account):
    _promote(app, account["account"]["id"], "admin")
    response = client.get("/v1/admin/notifications/999999/receipts", headers=headers)
    assert response.status_code == 404


# —— 第十六批：回执 CSV 导出 ---------------------------------------------------

def test_receipt_csv_export(client, headers, app, account):
    _promote(app, account["account"]["id"], "admin")
    settings = app.state.settings
    settings.notification_push_enabled = True
    settings.vapid_private_key = "test-private-key"
    settings.vapid_subject = "mailto:admin@example.com"
    aid = account["account"]["id"]
    with db_session(app) as session:
        nsvc.upsert_subscription(
            session, account_id=aid, endpoint="https://push.example.com/csv-export",
            p256dh=_PUSH_KEYS["p256dh"], auth=_PUSH_KEYS["auth"],
        )
        session.commit()
    with patch.object(nsvc.webpush, "send_web_push", side_effect=_push_exception(410)):
        with db_session(app) as session:
            note = nsvc.emit(
                session, account_id=aid, category="admin_message",
                dedupe_key="admin:csv-export-test", context={"title": "T", "body": "B"},
                settings=settings, channels=("push",),
            )
            delivery = session.scalar(
                select(NotificationDelivery).where(NotificationDelivery.notification_id == note.id)
            )
            delivery_id = delivery.id
            session.commit()

    resp = client.get(f"/v1/admin/notifications/{delivery_id}/receipts/export", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/csv")
    assert "attachment" in resp.headers["content-disposition"]
    assert resp.content.startswith(b"\xef\xbb\xbf")  # UTF-8 BOM
    body = resp.content.decode("utf-8-sig")
    lines = body.strip().splitlines()
    assert lines[0] == "delivery_id,channel,delivery_status,sub_id,status,http_status,retry_after_seconds,error"
    assert str(delivery_id) in body and "expired" in body and "410" in body


def test_receipt_csv_formula_injection_escaped(client, headers, app, account):
    """不可信 error 文本以 = 开头时必须前置单引号，防 Excel 公式注入。"""
    _promote(app, account["account"]["id"], "admin")
    settings = app.state.settings
    aid = account["account"]["id"]
    with db_session(app) as session:
        note = nsvc.emit(
            session, account_id=aid, category="admin_message",
            dedupe_key="admin:csv-injection-test", context={"title": "T", "body": "B"},
            settings=settings, channels=("push",),
        )
        delivery = session.scalar(
            select(NotificationDelivery).where(NotificationDelivery.notification_id == note.id)
        )
        delivery_id = delivery.id
        # 写入以 = 开头的可信度未知错误文本
        delivery.meta = {"receipts": [{"sub_id": 1, "status": "failed", "error": "=CMD|calc"}]}
        session.commit()
    resp = client.get(f"/v1/admin/notifications/{delivery_id}/receipts/export", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.content.decode("utf-8-sig")
    # 以 = 开头的错误文本被前置单引号转义；csv.writer 不加引号（字段无逗号）
    assert "'=CMD|calc" in body


def test_receipt_csv_leading_space_formula_is_escaped(client, headers, app, account):
    """前置空格不能绕过公式注入防护。"""
    _promote(app, account["account"]["id"], "admin")
    with db_session(app) as session:
        delivery = NotificationDelivery(
            account_id=account["account"]["id"], channel="push", status="failed",
            category="admin_message", subject="T", body="B",
            dedupe_key="csv-space-formula-test", meta={
                "receipts": [{"sub_id": 1, "status": "failed", "error": "  =CMD|calc"}]
            },
        )
        session.add(delivery)
        session.commit()
        delivery_id = delivery.id
    resp = client.get(f"/v1/admin/notifications/{delivery_id}/receipts/export", headers=headers)
    assert resp.status_code == 200, resp.text
    assert "'  =CMD|calc" in resp.content.decode("utf-8-sig")


def test_receipt_history_redacts_error_text(client, headers, app, account):
    """回执详情也不能回显 webpush 错误文本中的 endpoint/token。"""
    _promote(app, account["account"]["id"], "admin")
    with db_session(app) as session:
        delivery = NotificationDelivery(
            account_id=account["account"]["id"], channel="push", status="failed",
            category="admin_message", subject="T", body="B",
            dedupe_key="receipt-redact-test", meta={
                "receipts": [{
                    "sub_id": 1, "status": "failed",
                    "error": "post https://push.example.com/sub/abc token=leakme failed",
                }]
            },
        )
        session.add(delivery)
        session.commit()
        delivery_id = delivery.id
    resp = client.get(f"/v1/admin/notifications/{delivery_id}/receipts", headers=headers)
    assert resp.status_code == 200, resp.text
    assert "leakme" not in resp.text


def test_receipt_export_requires_admin(client, headers, app, account):
    """CSV 含订阅级明细：support 只读角色不得导出。"""
    _promote(app, account["account"]["id"], "support")
    resp = client.get("/v1/admin/notifications/1/receipts/export", headers=headers)
    assert resp.status_code == 403


def test_receipt_csv_missing_delivery_404(client, headers, app, account):
    _promote(app, account["account"]["id"], "admin")
    resp = client.get("/v1/admin/notifications/999999/receipts/export", headers=headers)
    assert resp.status_code == 404
