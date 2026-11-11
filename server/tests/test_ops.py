# -*- coding: utf-8 -*-
"""可观测、限流、回调来源校验与定时/自愈任务。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import create_app
from app.metrics import reset as reset_metrics
from app.models import (
    AuditLog,
    Plan,
    ReconcileReport,
    Subscription,
    Task,
    TaskEvent,
    UsageEvent,
)
from app.scheduler import run_once
from app.services.sentry import init_sentry


def test_metrics_endpoint(client):
    reset_metrics()
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "moxie_queue_depth" in response.text
    assert "text/plain" in response.headers["content-type"]


def test_metrics_can_be_disabled(tmp_path):
    from app.config import Settings

    settings = Settings(
        env="test",
        database_url=f"sqlite:///{(tmp_path / 'm.db').as_posix()}",
        auto_create_tables=True,
        redis_enabled=False,
        jwt_secret="test-jwt-secret-at-least-32-bytes-long",
        metrics_enabled=False,
        license_private_key_pem="",
        log_level="WARNING",
        storage_backend="local",
        storage_local_dir=str(tmp_path / "artifacts"),
        task_source_dirs=str(tmp_path),
    )
    with TestClient(create_app(settings)) as test_client:
        assert test_client.get("/metrics").status_code == 404


def test_register_rate_limited(tmp_path):
    from app.config import Settings

    reset_metrics()
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{(tmp_path / 'rl.db').as_posix()}",
        auto_create_tables=True,
        redis_enabled=False,
        jwt_secret="test-jwt-secret-at-least-32-bytes-long",
        register_rate_limit_per_minute=2,
        legal_gate_enabled=False,
        log_level="WARNING",
        storage_backend="local",
        storage_local_dir=str(tmp_path / "artifacts"),
        task_source_dirs=str(tmp_path),
    )
    with TestClient(create_app(settings)) as test_client:
        codes = []
        for i in range(3):
            codes.append(
                test_client.post(
                    "/v1/auth/register",
                    json={"email": f"limit{i}@example.com", "password": "password123"},
                ).status_code
            )
        assert codes == [201, 201, 429]
        assert test_client.get("/metrics").text.count("moxie_rate_limited_total") >= 1


def test_webhook_source_allowlist(tmp_path):
    from app.config import Settings

    settings = Settings(
        env="test",
        database_url=f"sqlite:///{(tmp_path / 'ip.db').as_posix()}",
        auto_create_tables=True,
        redis_enabled=False,
        jwt_secret="test-jwt-secret-at-least-32-bytes-long",
        payment_webhook_ip_allowlist="10.0.0.9",
        log_level="WARNING",
        storage_backend="local",
        storage_local_dir=str(tmp_path / "artifacts"),
        task_source_dirs=str(tmp_path),
    )
    with TestClient(create_app(settings)) as test_client:
        response = test_client.post("/v1/webhooks/mock", json={"event_id": "e1"})
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "webhook_source_rejected"


def test_sentry_silent_without_dsn():
    from app.config import Settings

    assert init_sentry(Settings(sentry_dsn="")) is False


def test_scheduler_self_healing(client, headers):
    app = client.app
    settings = app.state.settings.model_copy(
        update={
            "decompose_segment_batch": 0,
            "payment_reconcile_providers": "fake",
            "usage_alert_multiplier": 3.0,
        }
    )
    now = datetime.now(timezone.utc)

    me = client.get("/v1/auth/me", headers=headers).json()
    account_id = me["id"]
    plan = None
    with app.state.db.session() as session:
        plan = session.scalar(select(Plan).where(Plan.code == "professional"))
        session.add(
            Subscription(
                account_id=account_id,
                plan_id=plan.id,
                status="past_due",
                seats=1,
                current_start_at=now - timedelta(days=40),
                current_end_at=now - timedelta(days=10),
                version=1,
            )
        )
        session.add(
            Task(
                id="lease-task",
                account_id=account_id,
                type="decompose",
                status="running",
                params={"source_path": "x"},
                lease_until=now - timedelta(minutes=5),
                attempts=1,
            )
        )
        session.commit()

    stats = run_once(settings, app.state.db, now=now)
    assert stats["lease_reclaimed"] == 1
    assert stats["grace_expired"] == 1
    assert "fake" in stats["reconciled"]

    with app.state.db.session() as session:
        task = session.get(Task, "lease-task")
        assert task.status == "queued"
        assert task.lease_until is None
        assert session.scalar(
            select(TaskEvent.task_id).where(TaskEvent.task_id == "lease-task")
        ) is not None
        sub = session.scalar(select(Subscription).where(Subscription.account_id == account_id))
        assert sub.status == "expired"
        assert session.scalar(
            select(ReconcileReport.id).where(ReconcileReport.provider == "fake")
        ) is not None
        assert session.scalar(
            select(AuditLog.id).where(AuditLog.action == "task.lease_reclaim")
        ) is not None

    # 全部任务幂等：再跑一轮不应重复处理
    stats2 = run_once(settings, app.state.db, now=now)
    assert stats2["lease_reclaimed"] == 0
    assert stats2["grace_expired"] == 0


def test_scheduler_reminders_usage_alerts_idempotent(client):
    app = client.app
    settings = app.state.settings.model_copy(
        update={"payment_reconcile_providers": "", "usage_alert_multiplier": 3.0}
    )
    now = datetime.now(timezone.utc)

    # 另一个账号，避免影响上面的订阅
    client.post(
        "/v1/auth/register",
        json={"email": "alert@example.com", "password": "password123"},
    )
    token = client.post(
        "/v1/auth/login",
        json={"email": "alert@example.com", "password": "password123"},
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    account_id = client.get("/v1/auth/me", headers=headers).json()["id"]

    with app.state.db.session() as session:
        plan = session.scalar(select(Plan).where(Plan.code == "professional"))
        sub = Subscription(
            account_id=account_id,
            plan_id=plan.id,
            status="active",
            seats=1,
            current_start_at=now - timedelta(days=27),
            current_end_at=now + timedelta(days=3),
            version=1,
        )
        session.add(sub)
        session.add(
            UsageEvent(
                account_id=account_id,
                task_id=None,
                metric="model_token",
                # 专业版 managed_chars=2,000,000 → 日阈值 = limit/30 × 3.0 = 200,000
                quantity=250_000,
                unit="token",
                idempotency_key="alert-usage-1",
                occurred_at=now,
                meta={},
            )
        )
        session.commit()
        sub_id = sub.id

    stats = run_once(settings, app.state.db, now=now)
    assert stats["reminders"] == 1
    assert stats["usage_alerts"] == 1

    stats2 = run_once(settings, app.state.db, now=now)
    assert stats2["reminders"] == 0
    assert stats2["usage_alerts"] == 0

    with app.state.db.session() as session:
        assert session.scalar(
            select(AuditLog.id).where(
                AuditLog.action == "subscription.renewal_reminder",
                AuditLog.target_id == str(sub_id),
            )
        ) is not None
        assert session.scalar(
            select(AuditLog.id).where(
                AuditLog.action == "usage.anomaly",
                AuditLog.target_id == f"account:{account_id}",
            )
        ) is not None


def test_scheduler_credit_sweep_import_path(client, app, settings):
    """回归：scheduler 以 python -m app.scheduler 运行时，额度清扫不得因相对导入崩溃。"""
    from app.scheduler import sweep_credits

    with app.state.db.session() as session:
        result = sweep_credits(session, settings)
    assert result["expired"] == 0
    assert result["reminded"] == 0
