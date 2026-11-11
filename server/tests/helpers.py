# -*- coding: utf-8 -*-
"""测试辅助函数。"""

from __future__ import annotations

import uuid


def subscribe(
    client, headers, plan_code: str = "creator", cycle: str = "month", pay: bool = True
) -> dict:
    """下单（可选 mock 支付回调），返回 subscription/order/下单响应。"""
    response = client.post(
        "/v1/subscriptions",
        headers={**headers, "Idempotency-Key": f"sub-{uuid.uuid4()}"},
        json={"plan_code": plan_code, "cycle": cycle, "provider": "mock"},
    )
    assert response.status_code == 201, response.text
    data = response.json()
    if pay:
        params = data["payment"]["params"]
        callback = client.post(
            params["webhook_path"],
            headers={"x-mock-signature": params["signature"]},
            json=params["body"],
        )
        assert callback.status_code == 200, callback.text
        assert callback.json()["order_status"] == "paid", callback.text
    return {"subscription": data["subscription"], "order": data["order"], "response": data}


def add_device(client, headers, device_hash: str = "device-hash-0001", platform: str = "windows") -> dict:
    response = client.post(
        "/v1/devices",
        headers=headers,
        json={"device_hash": device_hash, "platform": platform, "name": "test-device"},
    )
    return response


def db_session(app):
    return app.state.db.session()
