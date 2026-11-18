# -*- coding: utf-8 -*-
"""合规闸门：结构化权利声明的服务端校验与法律留痕。"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models import AuditLog, LegalConsent
from app.services.compliance import CONSENT_TYPE

from .helpers import db_session, subscribe
from .test_legal_gates import _task_body


def _enable_gate(app):
    prev = app.state.settings.legal_gate_enabled
    app.state.settings.legal_gate_enabled = True
    return prev


def _restore_gate(app, prev):
    app.state.settings.legal_gate_enabled = prev


def test_structured_declaration_passes_and_records_consent(client, headers, app):
    """结构化声明（basis/ai_notice_ack）通过闸门，并落 LegalConsent + 审计。"""
    subscribe(client, headers)
    prev = _enable_gate(app)
    account_id = client.get("/v1/auth/me", headers=headers).json()["id"]
    try:
        decl = {
            "basis": "authorized",
            "rights_confirmed": True,
            "ai_notice_ack": True,
            "note": "已获作者书面授权",
        }
        body = _task_body("decompose", rights_declaration=decl)
        resp = client.post("/v1/tasks", headers=headers, json=body)
        assert resp.status_code == 201, resp.text

        with db_session(app) as session:
            consents = session.scalars(
                select(LegalConsent).where(
                    LegalConsent.account_id == account_id,
                    LegalConsent.consent_type == CONSENT_TYPE,
                )
            ).all()
            assert len(consents) == 1
            assert consents[0].version == app.state.settings.legal_terms_version

            audits = session.scalars(
                select(AuditLog).where(AuditLog.action == "task.rights_consent")
            ).all()
            assert len(audits) == 1
            meta = audits[0].meta
            assert meta["basis"] == "authorized"
            assert meta["ai_notice_ack"] is True
            assert meta["source"] == "encrypted_body"
            assert meta["note"] == "已获作者书面授权"
    finally:
        _restore_gate(app, prev)


def test_plaintext_header_fallback_marked_as_legacy(client, headers, app):
    """仅明文头无结构化声明时放行，但审计标注来源为 plaintext_header。"""
    subscribe(client, headers)
    prev = _enable_gate(app)
    try:
        resp = client.post(
            "/v1/tasks",
            headers={**headers, "X-Rights-Confirmed": "true"},
            json=_task_body("decompose"),
        )
        assert resp.status_code == 201, resp.text
        with db_session(app) as session:
            audit = session.scalar(
                select(AuditLog).where(AuditLog.action == "task.rights_consent")
            )
            assert audit is not None
            assert audit.meta["source"] == "plaintext_header"
            assert audit.meta["basis"] == "header_legacy"
    finally:
        _restore_gate(app, prev)


def test_no_declaration_rejected(client, headers, app):
    """闸门开启、既无结构化声明也无明文头时必须 422。"""
    subscribe(client, headers)
    prev = _enable_gate(app)
    try:
        resp = client.post("/v1/tasks", headers=headers, json=_task_body("adapt"))
        assert resp.status_code == 422, resp.text
        assert resp.json()["error"]["code"] == "rights_confirmation_required"
    finally:
        _restore_gate(app, prev)


def test_invalid_declaration_values_rejected(client, headers, app):
    """声明字段非法（basis 枚举外 / 未确认 / 未ACK）应被 schema 校验拦截。"""
    subscribe(client, headers)
    prev = _enable_gate(app)
    try:
        for bad in (
            {"basis": "unknown", "rights_confirmed": True, "ai_notice_ack": True},
            {"basis": "own", "rights_confirmed": False, "ai_notice_ack": True},
            {"basis": "own", "rights_confirmed": True, "ai_notice_ack": False},
        ):
            body = _task_body("decompose", rights_declaration=bad)
            resp = client.post("/v1/tasks", headers=headers, json=body)
            assert resp.status_code == 422, resp.text
    finally:
        _restore_gate(app, prev)


def test_consent_is_idempotent(client, headers, app):
    """同一账号同一版本重复声明只记一条 LegalConsent，但每次都有审计。"""
    subscribe(client, headers)
    prev = _enable_gate(app)
    account_id = client.get("/v1/auth/me", headers=headers).json()["id"]
    decl = {"basis": "public_domain", "rights_confirmed": True, "ai_notice_ack": True}
    try:
        for _ in range(2):
            body = _task_body(
                "decompose",
                rights_declaration=decl,
                idempotency_key=f"idem-{uuid.uuid4()}",
            )
            resp = client.post("/v1/tasks", headers=headers, json=body)
            assert resp.status_code == 201, resp.text
        with db_session(app) as session:
            consents = session.scalars(
                select(LegalConsent).where(LegalConsent.account_id == account_id)
            ).all()
            assert len(consents) == 1
            audits = session.scalars(
                select(AuditLog).where(AuditLog.action == "task.rights_consent")
            ).all()
            assert len(audits) == 2
    finally:
        _restore_gate(app, prev)
