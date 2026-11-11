# -*- coding: utf-8 -*-
"""C-01 法律文本勾选留痕：注册必须同意当前版本的用户协议与隐私政策。"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import create_app
from app.models import LegalConsent


def _consents(version: str) -> dict:
    return {
        "terms": {"version": version, "accepted": True},
        "privacy": {"version": version, "accepted": True},
    }


def test_register_requires_legal_consent(settings):
    app = create_app(settings.model_copy(update={"legal_gate_enabled": True}))
    version = settings.legal_terms_version
    with TestClient(app) as client:
        # 缺 consents → 422
        r = client.post(
            "/v1/auth/register",
            json={"email": "a@example.com", "password": "password123"},
        )
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "legal_consent_required"

        # 版本不符 → 422
        r = client.post(
            "/v1/auth/register",
            json={"email": "a@example.com", "password": "password123",
                  "consents": _consents("1900-01-01")},
        )
        assert r.status_code == 422

        # 未勾选 → 422
        bad = _consents(version)
        bad["terms"]["accepted"] = False
        r = client.post(
            "/v1/auth/register",
            json={"email": "a@example.com", "password": "password123", "consents": bad},
        )
        assert r.status_code == 422

        # 正确 → 201
        r = client.post(
            "/v1/auth/register",
            json={"email": "a@example.com", "password": "password123",
                  "consents": _consents(version)},
        )
        assert r.status_code == 201, r.text

    with app.state.db.session() as session:
        rows = session.scalars(select(LegalConsent)).all()
        assert {row.consent_type for row in rows} == {"terms", "privacy"}
        assert all(row.version == version for row in rows)
        assert all(row.accepted_at is not None for row in rows)
