# -*- coding: utf-8 -*-
"""可读体检报告聚合接口回归。"""

from __future__ import annotations

from .helpers import subscribe


def test_health_report_is_scoped_to_account(client, headers, account):
    subscribe(client, headers)
    create = client.post(
        "/v1/agent-runs",
        headers=headers,
        json={
            "mode": "hot",
            "title": "体检报告测试稿",
            "audience": "male",
            "length": "short",
            "genre": {"id": "xuanyi", "name": "悬疑"},
        },
    )
    assert create.status_code == 201, create.text
    run_id = create.json()["run_id"]

    response = client.get(f"/v1/agent-runs/{run_id}/health-report", headers=headers)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["run_id"] == run_id
    assert data["title"] == "体检报告测试稿"
    assert "review" in data and "summary" in data
    assert isinstance(data["chapters"], list)
    assert isinstance(data["missing_artifacts"], list)

    other = client.post(
        "/v1/auth/register",
        json={"email": "other-health@example.test", "password": "password123"},
    )
    assert other.status_code == 201, other.text
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}
    denied = client.get(f"/v1/agent-runs/{run_id}/health-report", headers=other_headers)
    assert denied.status_code == 404
