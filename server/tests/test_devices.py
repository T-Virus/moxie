# -*- coding: utf-8 -*-
"""设备绑定上限（2 台）。"""

from __future__ import annotations

from .helpers import add_device


def test_third_device_rejected(client, headers):
    first = add_device(client, headers, "device-hash-1")
    second = add_device(client, headers, "device-hash-2")
    assert first.status_code == 201 and second.status_code == 201

    third = add_device(client, headers, "device-hash-3")
    assert third.status_code == 403
    assert third.json()["error"]["code"] == "device_limit_reached"

    listing = client.get("/v1/devices", headers=headers)
    assert listing.status_code == 200
    assert listing.json()["max_devices"] == 2
    assert len([d for d in listing.json()["devices"] if d["status"] == "active"]) == 2


def test_duplicate_device_is_idempotent(client, headers):
    first = add_device(client, headers, "device-hash-1")
    again = add_device(client, headers, "device-hash-1")
    assert first.status_code == 201
    assert again.status_code == 201
    assert again.json()["created"] is False
    assert first.json()["device"]["id"] == again.json()["device"]["id"]


def test_revoke_frees_a_slot(client, headers):
    first = add_device(client, headers, "device-hash-1").json()["device"]
    add_device(client, headers, "device-hash-2")
    response = client.delete(f"/v1/devices/{first['id']}", headers=headers)
    assert response.status_code == 200

    third = add_device(client, headers, "device-hash-3")
    assert third.status_code == 201
    assert third.json()["created"] is True


def test_devices_are_isolated_by_account(client, headers, account):
    other = client.post(
        "/v1/auth/register",
        json={"email": "other@example.com", "password": "password123"},
    )
    assert other.status_code == 201
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}

    device = add_device(client, headers, "device-hash-1").json()["device"]
    response = client.delete(f"/v1/devices/{device['id']}", headers=other_headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "device_not_found"
