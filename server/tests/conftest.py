# -*- coding: utf-8 -*-
"""测试公共 fixtures：SQLite + fakeredis，不依赖 Docker。"""

from __future__ import annotations

import os

# app.main 模块级会创建 app 对象；测试进程内允许临时 License 密钥，避免 import 时失败
os.environ.setdefault("LICENSE_ALLOW_EPHEMERAL_KEY", "true")

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.security import LicenseSigner

# 测试不读取 server/.env（compose/本地开发配置），避免 MODEL_STUB 等值影响断言
Settings.model_config["env_file"] = None


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        env="test",
        database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        auto_create_tables=True,
        redis_enabled=False,
        jwt_secret="test-jwt-secret-at-least-32-bytes-long",
        license_private_key_pem=LicenseSigner.generate_pem(),
        license_key_id="test-key-1",
        mock_payment_secret="test-mock-secret",
        payments_mock_enabled=True,
        payments_fake_enabled=True,
        invoice_provider="stub",
        invoice_callback_secret="test-invoice-secret",
        legal_gate_enabled=False,
        email_verification_required=False,
        llm_base_url="http://upstream.test",
        llm_api_key="server-secret-key",
        gateway_max_retries=1,
        gateway_rate_limit_per_minute=1000,
        ranking_enabled=False,
        log_level="WARNING",
        storage_backend="local",
        storage_local_dir=str(tmp_path / "artifacts"),
        storage_public_base_url="",
        task_source_dirs=str(tmp_path),
    )


@pytest.fixture
def app(settings):
    return create_app(settings)


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def account(client):
    response = client.post(
        "/v1/auth/register",
        json={"email": "tester@example.com", "password": "password123"},
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def headers(account):
    return {"Authorization": f"Bearer {account['access_token']}"}
