# -*- coding: utf-8 -*-
"""管理员 bootstrap 与生产启动配置别名回归。"""

from __future__ import annotations

from sqlalchemy import select

from app.bootstrap import bootstrap_admin, bootstrap_admins, parse_admin_emails
from app.config import Settings
from app.models import Account, AuditLog


def test_parse_admin_emails_normalizes_and_dedupes():
    raw = " Admin@Example.com ,admin@example.com\nnope@x.com,,"
    assert parse_admin_emails(raw) == ["admin@example.com", "nope@x.com"]
    assert parse_admin_emails(None) == []


def test_bootstrap_promotes_only_existing_account_idempotently(app, account):
    account_id = account["account"]["id"]
    with app.state.db.session() as session:
        assert bootstrap_admin(session, "missing@example.com")["status"] == "account_missing"
        first = bootstrap_admin(session, "tester@example.com", source="test")
        assert first == {
            "email": "tester@example.com",
            "status": "promoted",
            "account_id": account_id,
        }
        second = bootstrap_admin(session, "tester@example.com", source="test")
        assert second["status"] == "already_admin"

    with app.state.db.session() as session:
        assert session.get(Account, account_id).role == "admin"
        audits = session.scalars(
            select(AuditLog).where(AuditLog.action == "account.bootstrap_admin")
        ).all()
        assert len(audits) == 1
        assert audits[0].meta["source"] == "test"


def test_bootstrap_admins_continues_after_bad_entry(app, account):
    with app.state.db.session() as session:
        results = bootstrap_admins(session, "tester@example.com,missing@example.com")
    assert [item["status"] for item in results] == ["promoted", "account_missing"]


def test_settings_expose_production_aliases(monkeypatch):
    monkeypatch.setenv("MAX_REQUEST_BODY_BYTES", "1234")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_EMAILS", "admin@example.com,ops@example.com")
    settings = Settings(env="test")
    assert settings.max_request_body_bytes == 1234
    assert settings.bootstrap_admin_emails == "admin@example.com,ops@example.com"
