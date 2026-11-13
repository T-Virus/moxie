# -*- coding: utf-8 -*-
"""安全/合规闸门：mock 支付环境限制、License 私钥、版权确认。"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.errors import ApiError
from app.main import create_app
from app.payments import get_provider
from app.security import LicenseSigner

from .helpers import subscribe


def _task_body(task_type: str = "decompose", **extra) -> dict:
    params = {"book": "闸门样本", "source_text": "一段原文", **extra}
    return {"type": task_type, "params": params, "idempotency_key": f"gate-{uuid.uuid4()}"}


def test_mock_provider_rejected_in_production():
    settings = Settings(env="prod", payments_mock_enabled=True, payments_fake_enabled=False)
    with pytest.raises(ApiError) as exc:
        get_provider("mock", settings)
    assert exc.value.status_code == 403
    assert exc.value.code == "provider_not_allowed_in_env"


def test_mock_disabled_by_default_even_in_test_env():
    settings = Settings(env="test", payments_mock_enabled=False)
    with pytest.raises(ApiError) as exc:
        get_provider("mock", settings)
    assert exc.value.status_code == 403
    assert exc.value.code == "mock_payment_disabled"


def test_production_startup_rejects_fake_payments():
    settings = Settings(env="prod", payments_fake_enabled=True)
    with pytest.raises(RuntimeError, match="PAYMENTS_FAKE_ENABLED"):
        create_app(settings)


def _prod_settings(tmp_path, **overrides) -> Settings:
    base = dict(
        env="prod",
        database_url=f"sqlite:///{(tmp_path / 'prod-gate.db').as_posix()}",
        jwt_secret="test-jwt-secret-at-least-32-bytes-long",
        cors_allow_origins="https://app.example.com",
        license_private_key_pem=LicenseSigner.generate_pem(),
        payload_encryption_enabled=False,
        payments_mock_enabled=False,
        payments_fake_enabled=False,
        artifact_signing_secret="test-artifact-signing-secret",
        model_key_secret="test-model-key-secret",
        redis_enabled=False,
        log_level="WARNING",
    )
    base.update(overrides)
    return Settings(**base)


def test_production_startup_rejects_placeholder_jwt(tmp_path):
    settings = _prod_settings(tmp_path, jwt_secret="dev-only-change-me-in-production")
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        create_app(settings)


def test_production_startup_rejects_short_jwt(tmp_path):
    settings = _prod_settings(tmp_path, jwt_secret="too-short-secret")
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        create_app(settings)


def test_production_startup_rejects_wildcard_cors(tmp_path):
    settings = _prod_settings(tmp_path, cors_allow_origins="*")
    with pytest.raises(RuntimeError, match="CORS_ALLOW_ORIGINS"):
        create_app(settings)


def test_production_startup_rejects_default_database_url(tmp_path):
    default_url = Settings.model_fields["database_url"].default
    settings = _prod_settings(tmp_path, database_url=str(default_url))
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        create_app(settings)


def test_production_startup_rejects_placeholder_database_password(tmp_path):
    settings = _prod_settings(
        tmp_path,
        database_url="postgresql+psycopg://moxie:change-me-in-production@db:5432/moxie",
    )
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        create_app(settings)


def test_production_startup_rejects_default_s3_credentials(tmp_path):
    settings = _prod_settings(
        tmp_path,
        storage_backend="s3",
        s3_access_key="minioadmin",
        s3_secret_key="change-me-minio-secret",
    )
    with pytest.raises(RuntimeError) as exc:
        create_app(settings)
    message = str(exc.value)
    assert "S3_ACCESS_KEY" in message
    assert "S3_SECRET_KEY" in message


def test_subscription_requires_explicit_provider(client, headers):
    response = client.post(
        "/v1/subscriptions",
        headers={**headers, "Idempotency-Key": "no-provider"},
        json={"plan_code": "creator", "cycle": "month"},
    )
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "invalid_request"


def test_payment_providers_endpoint_lists_enabled_channels(client, app):
    response = client.get("/v1/payments/providers")
    assert response.status_code == 200, response.text
    items = {item["id"]: item for item in response.json()["items"]}
    assert "mock" in items
    assert items["mock"]["test_only"] is True

    settings = app.state.settings
    previous = settings.payments_mock_enabled
    settings.payments_mock_enabled = False
    try:
        ids = {item["id"] for item in client.get("/v1/payments/providers").json()["items"]}
        assert "mock" not in ids
    finally:
        settings.payments_mock_enabled = previous


def test_available_providers_excludes_mock_in_production():
    from app.payments import available_providers

    settings = Settings(
        env="prod",
        payments_mock_enabled=True,
        payments_fake_enabled=True,
        mock_payment_secret="test-mock-secret",
    )
    ids = {item["id"] for item in available_providers(settings)}
    assert "mock" not in ids
    assert "fake" not in ids


def test_production_startup_requires_license_key():
    with pytest.raises(ValueError, match="LICENSE_PRIVATE_KEY_PEM"):
        LicenseSigner(None)


def test_ephemeral_license_key_must_be_opted_in():
    signer = LicenseSigner(None, allow_ephemeral=True)
    assert signer.public_key_b64
    with pytest.raises(ValueError, match="LICENSE_PRIVATE_KEY_PEM"):
        LicenseSigner(None, allow_ephemeral=False)


def test_mock_secret_missing_rejects_provider_and_webhook():
    settings = Settings(env="test", payments_mock_enabled=True, mock_payment_secret="")
    with pytest.raises(ApiError) as exc:
        get_provider("mock", settings)
    assert exc.value.status_code == 403
    assert exc.value.code == "mock_secret_missing"


def test_production_mock_checkout_returns_4xx_and_no_subscription(tmp_path):
    settings = Settings(
        env="prod",
        database_url=f"sqlite:///{(tmp_path / 'prod.db').as_posix()}",
        auto_create_tables=True,
        redis_enabled=False,
        jwt_secret="test-jwt-secret-at-least-32-bytes-long",
        license_private_key_pem=LicenseSigner.generate_pem(),
        mock_payment_secret="test-mock-secret",
        payments_mock_enabled=False,
        payments_fake_enabled=False,
        storage_backend="local",
        storage_local_dir=str(tmp_path / "artifacts"),
        task_source_dirs=str(tmp_path),
        notifications_enabled=False,
        log_level="WARNING",
        payload_encryption_enabled=False,
        email_verification_required=False,  # 本用例验证 mock 渠道闸门，不走邮箱验证流程
        artifact_signing_secret="test-artifact-signing-secret",
        model_key_secret="test-model-key-secret",
    )
    with TestClient(create_app(settings)) as client:
        registered = client.post(
            "/v1/auth/register",
            json={
                "email": "prod@example.com",
                "password": "password123",
                "consents": {
                    "terms": {"version": settings.legal_terms_version, "accepted": True},
                    "privacy": {"version": settings.legal_terms_version, "accepted": True},
                },
            },
        )
        assert registered.status_code == 201, registered.text
        headers = {"Authorization": f"Bearer {registered.json()['access_token']}"}

        checkout = client.post(
            "/v1/subscriptions",
            headers={**headers, "Idempotency-Key": "prod-mock-checkout"},
            json={"plan_code": "creator", "cycle": "month", "provider": "mock"},
        )
        assert checkout.status_code == 403, checkout.text
        assert checkout.json()["error"]["code"] == "provider_not_allowed_in_env"

        current = client.get("/v1/subscriptions/current", headers=headers)
        assert current.status_code == 404, "生产环境 mock 下单不得开通订阅"


def test_rights_confirmation_gate(client, headers, app):
    subscribe(client, headers)
    settings = app.state.settings
    previous = settings.legal_gate_enabled
    settings.legal_gate_enabled = True
    try:
        response = client.post("/v1/tasks", headers=headers, json=_task_body())
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "rights_confirmation_required"

        ok = client.post(
            "/v1/tasks",
            headers=headers,
            json=_task_body(rights_confirmed=True, aigc_label=True),
        )
        assert ok.status_code == 201, ok.text
        task = ok.json()["task"]
        assert task["params"]["rights_confirmed"] is True
        assert task["params"]["aigc_label"] is True
    finally:
        settings.legal_gate_enabled = previous


def test_rights_confirmation_header_also_accepted(client, headers, app):
    subscribe(client, headers)
    settings = app.state.settings
    previous = settings.legal_gate_enabled
    settings.legal_gate_enabled = True
    try:
        response = client.post(
            "/v1/tasks",
            headers={**headers, "X-Rights-Confirmed": "true"},
            json=_task_body(task_type="decompose"),
        )
        assert response.status_code == 201, response.text
    finally:
        settings.legal_gate_enabled = previous
