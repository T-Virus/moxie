# -*- coding: utf-8 -*-
"""License 签发、签名校验、7 天刷新 + 14 天宽限。"""

from __future__ import annotations

from datetime import timedelta

from app.db import utcnow
from app.models import Device
from app.services.license import issue_license, verify_license
from sqlalchemy import select

from .helpers import add_device, db_session, subscribe


def _prepare(client, headers, app):
    subscribe(client, headers)
    device = add_device(client, headers, "license-device-1")
    assert device.status_code == 201
    return device.json()["device"]["id"], headers


def test_license_issue_and_verify(client, headers, app):
    device_id, _ = _prepare(client, headers, app)
    response = client.get(f"/v1/license?device_id={device_id}", headers=headers)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["license"]["plan_code"] == "creator"
    assert data["public_key"]

    verified = client.post(
        "/v1/license/verify",
        json={"payload": data["license"], "signature": data["signature"]},
    )
    assert verified.status_code == 200
    assert verified.json()["status"] == "ok"


def test_license_requires_active_subscription(client, headers, app):
    device = add_device(client, headers, "license-device-2").json()["device"]
    response = client.get(f"/v1/license?device_id={device['id']}", headers=headers)
    assert response.status_code == 402
    assert response.json()["error"]["code"] == "no_active_subscription"


def test_tampered_license_is_invalid(client, headers, app):
    device_id, _ = _prepare(client, headers, app)
    data = client.get(f"/v1/license?device_id={device_id}", headers=headers).json()
    payload = dict(data["license"])
    payload["plan_code"] = "professional"
    verified = client.post(
        "/v1/license/verify", json={"payload": payload, "signature": data["signature"]}
    )
    assert verified.status_code == 200
    assert verified.json()["valid"] is False
    assert verified.json()["status"] == "invalid"


def test_license_expiry_and_grace_windows(client, headers, app):
    device_id, _ = _prepare(client, headers, app)
    settings = app.state.settings
    signer = app.state.license_signer
    t0 = utcnow()

    with db_session(app) as session:
        account_id = session.scalar(
            select(Device.account_id).where(Device.id == device_id)
        )
        issued = issue_license(
            session,
            account_id=account_id,
            device_id=device_id,
            settings=settings,
            signer=signer,
            now=t0,
        )
        session.commit()

    # 第 6 天：正常
    assert verify_license(issued["license"], issued["signature"], signer=signer,
                          now=t0 + timedelta(days=6))["status"] == "ok"
    # 第 10 天：超过 7 天有效期，但仍在 14 天宽限期内
    assert verify_license(issued["license"], issued["signature"], signer=signer,
                          now=t0 + timedelta(days=10))["status"] == "grace"
    # 第 22 天：超过 7 + 14 天
    expired = verify_license(issued["license"], issued["signature"], signer=signer,
                             now=t0 + timedelta(days=22))
    assert expired["valid"] is False
    assert expired["status"] == "expired"


def test_revoked_device_cannot_get_license(client, headers, app):
    device_id, _ = _prepare(client, headers, app)
    assert client.delete(f"/v1/devices/{device_id}", headers=headers).status_code == 200
    response = client.get(f"/v1/license?device_id={device_id}", headers=headers)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "device_revoked"
