# -*- coding: utf-8 -*-
"""迁移一致性：空库 alembic upgrade head 后，模型表齐全且应用可启动（不自动建表）。"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text

from app.config import Settings
from app.main import create_app
from app.security import LicenseSigner

SERVER_DIR = Path(__file__).resolve().parents[1]

REQUIRED_TABLES = {
    "accounts",
    "orders",
    "tasks",
    "credit_packs",
    "credit_grants",
    "notifications",
    "notification_deliveries",
    "refunds",
    "invoice_requests",
}


def _migrate(monkeypatch, url: str) -> None:
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("AUTO_CREATE_TABLES", "false")
    config = Config(str(SERVER_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(SERVER_DIR / "alembic"))
    command.upgrade(config, "head")


def test_upgrade_head_creates_expected_tables(tmp_path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'migrated.db').as_posix()}"
    _migrate(monkeypatch, url)

    engine = create_engine(url)
    try:
        tables = set(inspect(engine).get_table_names())
        assert REQUIRED_TABLES <= tables
        order_cols = {col["name"] for col in inspect(engine).get_columns("orders")}
        assert {"pack_id", "plan_id", "refunded_cents"} <= order_cols
        task_cols = {col["name"] for col in inspect(engine).get_columns("tasks")}
        assert {"reserved_plan_quantity", "reserved_pack_items"} <= task_cols
    finally:
        engine.dispose()


def test_app_starts_on_migrated_db_without_autocreate(tmp_path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'migrated_app.db').as_posix()}"
    _migrate(monkeypatch, url)

    settings = Settings(
        env="test",
        database_url=url,
        auto_create_tables=False,
        redis_enabled=False,
        jwt_secret="test-jwt-secret-at-least-32-bytes-long",
        license_private_key_pem=LicenseSigner.generate_pem(),
        log_level="WARNING",
        storage_backend="local",
        storage_local_dir=str(tmp_path / "artifacts"),
        task_source_dirs=str(tmp_path),
        notifications_enabled=False,
    )
    with TestClient(create_app(settings)) as client:
        response = client.get("/readyz")
        assert response.status_code == 200, response.text
        assert response.json()["database"] is True

    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            packs = conn.execute(text("SELECT COUNT(*) FROM credit_packs")).scalar_one()
            plans = conn.execute(text("SELECT COUNT(*) FROM plans")).scalar_one()
        assert packs >= 3, "迁移后启动应自动写入额度包种子"
        assert plans >= 3
    finally:
        engine.dispose()
