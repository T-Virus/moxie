# -*- coding: utf-8 -*-
"""墨写服务端基准压测（Locust）。

覆盖：鉴权（Bearer Token 校验）、额度查询、任务查询、任务创建+取消。

前置：
    pip install locust
    # 服务端已用 SQLite + 本地存储启动（见 run_local.py），
    # 并提供足够高的注册/登录限流阈值用于账号准备。

运行（无 UI）：
    MOXIE_BASE_URL=http://127.0.0.1:8798 \
    python -m locust -f ops/loadtest/locustfile.py --headless \
        -u 10 -r 2 -t 30s --csv ops/loadtest/results/local

说明：
  · 每个虚拟用户绑定一个独立账号（避免额度串账）。
  · 任务创建后立刻取消：仅对排队中的任务释放预占额度，
    LOCAL_TEST_SECONDS 内可持续循环创建，不会把额度打满。
  · 压测数据全部在服务端临时 SQLite / 临时存储目录中，不写项目 data/。
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from itertools import cycle
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from locust import HttpUser, between, events, task

BASE_URL = os.environ.get("MOXIE_BASE_URL", "http://127.0.0.1:8798").rstrip("/")
API = BASE_URL + "/v1"
ACCOUNT_COUNT = int(os.environ.get("LOADTEST_ACCOUNTS", "10"))
ACCOUNT_PASSWORD = os.environ.get("LOADTEST_PASSWORD", "loadtest-password-123")

_accounts: list[dict] = []
_lock = threading.Lock()
_pool = None


def _request(method: str, path: str, body: dict | None = None, token: str | None = None,
             headers: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = Request(API + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    try:
        with urlopen(req, timeout=20) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else {}
    except HTTPError as exc:
        raw = exc.read()
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {"raw": raw.decode("utf-8", "replace")}
        return exc.code, payload


def _prepare_account(index: int) -> dict:
    email = f"loadtest-{index}-{uuid.uuid4().hex[:8]}@example.com"
    status, data = _request("POST", "/auth/register", {"email": email, "password": ACCOUNT_PASSWORD})
    if status != 201:
        raise RuntimeError(f"注册失败 {status}: {data}")
    token = data["access_token"]

    sub_key = f"loadtest-sub-{uuid.uuid4()}"
    status, sub = _request(
        "POST",
        "/subscriptions",
        {"plan_code": "studio_byok", "cycle": "month", "provider": "mock"},
        token=token,
        headers={"Idempotency-Key": sub_key},
    )
    if status != 201:
        raise RuntimeError(f"订阅下单失败 {status}: {sub}")
    params = sub["payment"]["params"]
    header_name = params.get("header") or "x-mock-signature"
    status, callback = _request(
        "POST",
        params["webhook_path"].removeprefix("/v1"),
        params["body"],
        headers={header_name: params["signature"]},
    )
    if status != 200 or callback.get("order_status") != "paid":
        raise RuntimeError(f"模拟支付回调失败 {status}: {callback}")

    # 预置一个任务用于查询类请求；随后取消以释放额度
    status, created = _request(
        "POST", "/tasks", {"type": "decompose", "params": {}},
        token=token, headers={"Idempotency-Key": f"loadtest-seed-{uuid.uuid4()}"},
    )
    if status not in (200, 201):
        raise RuntimeError(f"预置任务失败 {status}: {created}")
    task_id = created["task"]["id"]
    _request("POST", f"/tasks/{task_id}/cancel", {"reason": "loadtest seed"}, token=token)
    return {"token": token, "email": email, "task_id": task_id}


@events.test_start.add_listener
def _setup_accounts(environment, **_kwargs):
    global _accounts, _pool
    print(f"[loadtest] 准备 {ACCOUNT_COUNT} 个账号（注册 + 模拟订阅 + 预置任务）…")
    _accounts = [_prepare_account(i) for i in range(ACCOUNT_COUNT)]
    _pool = cycle(_accounts)
    print(f"[loadtest] 账号准备完成，目标 {BASE_URL}")


class MoxieUser(HttpUser):
    host = BASE_URL
    wait_time = between(0.1, 0.4)

    def on_start(self):
        with _lock:
            account = next(_pool)
        self.token = account["token"]
        self.task_id = account["task_id"]
        self.headers = {"Authorization": f"Bearer {self.token}"}

    @task(3)
    def auth_me(self):
        """鉴权：JWT 校验 + 账号读取。"""
        with self.client.get("/v1/auth/me", headers=self.headers, name="GET /v1/auth/me",
                             catch_response=True) as response:
            if response.status_code != 200:
                response.failure(f"status={response.status_code}")

    @task(3)
    def quota(self):
        """额度：实时 used/reserved 汇总。"""
        with self.client.get("/v1/entitlements", headers=self.headers,
                             name="GET /v1/entitlements", catch_response=True) as response:
            if response.status_code != 200:
                response.failure(f"status={response.status_code}")

    @task(3)
    def query_task(self):
        """任务查询：按 id 读取任务详情。"""
        with self.client.get(f"/v1/tasks/{self.task_id}", headers=self.headers,
                             name="GET /v1/tasks/{id}", catch_response=True) as response:
            if response.status_code != 200:
                response.failure(f"status={response.status_code}")

    @task(2)
    def create_and_cancel(self):
        """任务创建 + 取消（取消释放排队阶段的额度预占）。"""
        key = f"loadtest-{uuid.uuid4()}"
        with self.client.post(
            "/v1/tasks", json={"type": "decompose", "params": {}},
            headers={**self.headers, "Idempotency-Key": key},
            name="POST /v1/tasks", catch_response=True,
        ) as response:
            if response.status_code not in (200, 201):
                response.failure(f"status={response.status_code} body={response.text[:120]}")
                return
            task_id = response.json().get("task", {}).get("id")
        if task_id:
            with self.client.post(
                f"/v1/tasks/{task_id}/cancel", json={"reason": "loadtest"},
                headers=self.headers, name="POST /v1/tasks/{id}/cancel", catch_response=True,
            ) as response:
                if response.status_code != 200:
                    response.failure(f"status={response.status_code}")
